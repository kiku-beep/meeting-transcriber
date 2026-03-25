import asyncio
import logging
from contextlib import asynccontextmanager

# Initialize CUDA context early and disable cuDNN to avoid cudnnGetLibConfig crash
# on Windows (cuDNN 9.x symbol missing → STATUS_STACK_BUFFER_OVERRUN)
import torch
torch.backends.cudnn.enabled = False
if torch.cuda.is_available():
    try:
        _cuda_init = torch.zeros(1, device="cuda")
        del _cuda_init
    except Exception:
        pass

# Patch huggingface_hub for SpeechBrain 1.0.3 / pyannote.audio compatibility.
# Primary patch is in pyinstaller_entry.py (runs before all imports).
# This fallback covers dev mode (running backend.main directly).
import huggingface_hub as _hf_hub

if not getattr(_hf_hub.hf_hub_download, "_patched", False):
    from huggingface_hub.errors import EntryNotFoundError as _EntryNotFoundError
    from requests.exceptions import HTTPError as _RequestsHTTPError
    import huggingface_hub.file_download as _hfh_fd

    _orig_hf_download = _hf_hub.hf_hub_download

    def _patched_hf_hub_download(*args, **kwargs):
        kwargs.pop("local_dir_use_symlinks", None)
        kwargs.pop("force_filename", None)
        if "use_auth_token" in kwargs:
            kwargs.setdefault("token", kwargs.pop("use_auth_token"))
        try:
            return _orig_hf_download(*args, **kwargs)
        except _EntryNotFoundError as e:
            raise _RequestsHTTPError(f"404 Client Error: {e}") from e

    _patched_hf_hub_download._patched = True
    _hf_hub.hf_hub_download = _patched_hf_hub_download
    _hfh_fd.hf_hub_download = _patched_hf_hub_download

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes_audio import router as audio_router
from backend.api.routes_health import router as health_router
from backend.api.routes_session import router as session_router
from backend.api.routes_speaker import router as speaker_router
from backend.api.routes_dictionary import router as dictionary_router
from backend.api.routes_transcript import router as transcript_router
from backend.api.routes_config import router as config_router
from backend.api.routes_summary import router as summary_router
from backend.api.routes_playback import router as playback_router
from backend.api.routes_screenshot import router as screenshot_router
from backend.api.routes_call_detection import router as call_detection_router
from backend.api.ws_transcription import router as ws_router
from backend.config import settings
from backend.models.session import get_session
from backend.services.call_detector import get_call_detector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _preload_models():
    try:
        session = get_session()
        logger.info("Pre-loading models...")

        loop = asyncio.get_event_loop()
        # Load sequentially to avoid CUDA initialization race conditions on Windows
        await loop.run_in_executor(None, session._mic_buffer.load_model)
        await loop.run_in_executor(None, session._transcriber.load_model)
        await loop.run_in_executor(None, session._diarizer.load_model)
        logger.info("All models pre-loaded")

        # Auto-recompute invalid embeddings from stored audio samples
        await loop.run_in_executor(None, _auto_recompute_embeddings, session._diarizer)
    except Exception:
        logger.exception("CRITICAL: Model preload failed")


def _auto_recompute_embeddings(diarizer) -> None:
    """Recompute embeddings for speakers with samples but no valid embedding."""
    try:
        import soundfile as sf
        from backend.core.audio_utils import resample_to_16k_mono
        from backend.storage.speaker_store import get_speaker_store

        store = get_speaker_store()
        recomputed = 0
        for speaker_data in store.list_speakers():
            if speaker_data.get("has_embedding"):
                continue
            sid = speaker_data["id"]
            sample_paths = store.get_sample_paths(sid)
            if not sample_paths:
                continue
            try:
                audio_segments = []
                for path in sample_paths:
                    audio, sr = sf.read(str(path), dtype="float32")
                    audio = resample_to_16k_mono(audio, sr)
                    audio_segments.append(audio)
                if audio_segments:
                    embedding = diarizer.compute_average_embedding(audio_segments)
                    store.save_embedding(sid, embedding)
                    recomputed += 1
                    logger.info("Auto-recomputed embedding for speaker %s", sid)
            except Exception:
                logger.warning("Failed to auto-recompute for %s", sid, exc_info=True)

        if recomputed > 0:
            logger.info("Auto-recomputed %d speaker embeddings", recomputed)
    except Exception:
        logger.exception("Auto-recompute failed")


def _start_call_detector():
    """Initialize and start the call detection background service."""
    detector = get_call_detector()
    detector._poll_interval = settings.call_detection_interval
    detector.dismiss_duration = settings.call_detection_dismiss_duration
    detector.start()
    logger.info("Call auto-detection enabled")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.speakers_dir.mkdir(parents=True, exist_ok=True)
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Transcriber backend started")
    logger.info(f"Data directory: {settings.data_dir}")

    task = asyncio.create_task(_preload_models())
    task.add_done_callback(
        lambda t: t.result() if not t.cancelled() and t.exception() is None else None
    )

    # Start call auto-detection
    if settings.call_detection_enabled:
        _start_call_detector()

    yield

    # shutdown
    get_call_detector().stop()
    session = get_session()
    await session.stop()
    session.terminate_pyaudio()
    logger.info("Transcriber backend shutting down")


app = FastAPI(title="Transcriber", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(audio_router)
app.include_router(session_router)
app.include_router(speaker_router)
app.include_router(dictionary_router)
app.include_router(transcript_router)
app.include_router(summary_router)
app.include_router(config_router)
app.include_router(playback_router)
app.include_router(screenshot_router)
app.include_router(call_detection_router)
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=True,
    )
