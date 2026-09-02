"""Faster-Whisper transcription wrapper."""

from __future__ import annotations

import logging
import os
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

from backend.config import settings
from backend.core.vram_manager import check_temperature_safe, check_vram_available
from backend.core.whispercpp_backend import (
    WHISPER_CPP_MODEL_FILES,
    WhisperCppServerBackend,
    is_whisper_cpp_available,
)
from backend.storage.dictionary_store import get_dictionary_store

logger = logging.getLogger(__name__)

# Approximate VRAM requirements (float16)
VRAM_REQUIREMENTS = {
    "tiny": 150,
    "base": 300,
    "small": 1000,
    "medium": 2500,
    "large-v3": 4500,
    "kotoba-v2.0": 2500,
}

# Map short names to HuggingFace model IDs (None = use name as-is)
MODEL_HF_IDS = {
    "kotoba-v2.0": "kotoba-tech/kotoba-whisper-v2.0-faster",
}

# Models that use int8_float16 for faster loading and lower VRAM
# NOTE: large-v3 removed — int8_float16 caused transcription quality issues
INT8_MODELS: set[str] = set()

# Models that need special transcription parameters
KOTOBA_MODELS = {"kotoba-v2.0"}

AVAILABLE_MODELS = list(VRAM_REQUIREMENTS.keys())

DEFAULT_BEAM_SIZE = 5
CPU_BEAM_SIZE = 1


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _select_runtime(model_size: str) -> tuple[str, str]:
    """Return Faster-Whisper device and compute_type for the current machine."""
    if _cuda_available():
        compute = "int8_float16" if model_size in INT8_MODELS else "float16"
        return "cuda", compute
    return "cpu", "int8"


def _should_use_whisper_cpp(model_size: str) -> bool:
    backend = settings.asr_backend.lower().replace("_", "-")
    if backend in {"faster-whisper", "fasterwhisper"}:
        return False
    if backend in {"whisper.cpp", "whisper-cpp", "whispercpp"}:
        return True
    return (
        not _cuda_available()
        and model_size in WHISPER_CPP_MODEL_FILES
        and is_whisper_cpp_available(model_size)
    )


def _resolve_model_id(model_size: str) -> str:
    """Resolve model size to HuggingFace model ID."""
    model_id = MODEL_HF_IDS.get(model_size, model_size)
    # Standard faster-whisper models use Systran/ prefix
    if "/" not in model_id:
        model_id = f"Systran/faster-whisper-{model_id}"
    return model_id


def warm_disk_cache(model_size: str) -> dict:
    """Read model files into OS page cache for faster subsequent loading.

    Returns dict with bytes_read and elapsed time.
    """
    model_id = _resolve_model_id(model_size)

    try:
        from huggingface_hub import snapshot_download

        model_dir = snapshot_download(model_id, local_files_only=True)
    except Exception:
        logger.warning("Model %s not cached locally, skipping warm", model_size)
        return {"bytes_read": 0, "elapsed_s": 0.0, "status": "not_cached"}

    t0 = time.monotonic()
    total_bytes = 0
    for root, _dirs, files in os.walk(model_dir):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "rb") as fh:
                    while chunk := fh.read(1024 * 1024):  # 1MB chunks
                        total_bytes += len(chunk)
            except Exception:
                pass

    elapsed = time.monotonic() - t0
    logger.info(
        "Warmed disk cache for %s: %.0f MB in %.1fs",
        model_size,
        total_bytes / 1024 / 1024,
        elapsed,
    )
    return {"bytes_read": total_bytes, "elapsed_s": elapsed, "status": "warmed"}


class Transcriber:
    """Wraps Faster-Whisper for transcription."""

    def __init__(self, model_size: str | None = None):
        self.model_size = model_size or settings.whisper_model
        self._model: WhisperModel | None = None
        self._whisper_cpp: WhisperCppServerBackend | None = None
        self._initial_prompt: str = ""
        self._hotwords: str = ""
        # Loading stage tracking for progress UI
        self._loading_stage: str = ""  # "", "unloading", "warming", "loading", "ready"
        self._loading_progress: float = 0.0  # 0.0 - 1.0
        self._cache_warm_thread: threading.Thread | None = None
        self._model_load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._runtime_device: str = ""
        self._runtime_compute: str = ""

    def load_model(self) -> None:
        """Load the Whisper model."""
        with self._model_load_lock:
            self._load_model_once()

    def _load_model_once(self) -> None:
        if self.is_loaded:
            return

        if _should_use_whisper_cpp(self.model_size):
            logger.info("Loading whisper.cpp backend for %s", self.model_size)
            self._loading_stage = "loading"
            self._loading_progress = 0.3
            t0 = time.monotonic()
            whisper_cpp = WhisperCppServerBackend(self.model_size)
            whisper_cpp.load_model()
            self._whisper_cpp = whisper_cpp
            elapsed = time.monotonic() - t0
            self._runtime_device = "vulkan"
            self._runtime_compute = "whisper.cpp"
            self._loading_stage = "ready"
            self._loading_progress = 1.0
            logger.info(
                "whisper.cpp %s loaded in %.1fs (device=vulkan)",
                self.model_size,
                elapsed,
            )
            return

        # Resolve HuggingFace model ID if needed
        model_id = MODEL_HF_IDS.get(self.model_size, self.model_size)
        device, compute = _select_runtime(self.model_size)

        if device == "cuda":
            required_mb = VRAM_REQUIREMENTS.get(self.model_size, 3000)
            if not check_vram_available(required_mb):
                logger.warning(
                    "Insufficient VRAM for %s (need %dMB). Loading anyway...",
                    self.model_size,
                    required_mb,
                )
        else:
            logger.warning(
                "CUDA is not available; loading Faster-Whisper %s on CPU (%s).",
                self.model_size,
                compute,
            )

        logger.info(
            "Loading Faster-Whisper model: %s (%s, device=%s, compute=%s)",
            self.model_size,
            model_id,
            device,
            compute,
        )
        self._loading_stage = "loading"
        self._loading_progress = 0.3
        t0 = time.monotonic()

        self._model = WhisperModel(
            model_id,
            device=device,
            compute_type=compute,
        )
        self._runtime_device = device
        self._runtime_compute = compute

        elapsed = time.monotonic() - t0
        self._loading_stage = "ready"
        self._loading_progress = 1.0
        logger.info(
            "Whisper %s loaded in %.1fs (device=%s, compute=%s)",
            self.model_size,
            elapsed,
            device,
            compute,
        )

    def unload_model(self) -> None:
        """Release the model and free VRAM."""
        with self._model_load_lock, self._inference_lock:
            self._unload_model_once()

    def _unload_model_once(self) -> None:
        if self._whisper_cpp is not None:
            self._loading_stage = "unloading"
            self._loading_progress = 0.1
            self._whisper_cpp.unload_model()
            self._whisper_cpp = None
            self._runtime_device = ""
            self._runtime_compute = ""
            logger.info("whisper.cpp backend unloaded")

        if self._model is not None:
            self._loading_stage = "unloading"
            self._loading_progress = 0.1
            del self._model
            self._model = None
            self._runtime_device = ""
            self._runtime_compute = ""

            import gc
            import torch

            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Whisper model unloaded")

    def _decode_options(self) -> dict:
        """Return Faster-Whisper decode options for the active runtime."""
        if self._runtime_device == "cpu":
            # CPU decoding must keep up with live audio. Beam search 5 is much
            # slower on kotoba-v2.0 and causes realtime backlog on non-CUDA GPUs.
            return {
                "beam_size": CPU_BEAM_SIZE,
                "best_of": 1,
                "temperature": 0.0,
            }
        return {
            "beam_size": DEFAULT_BEAM_SIZE,
        }

    def build_vocab_hints(self) -> None:
        """Build initial_prompt and hotwords from the dictionary.

        initial_prompt: feeds vocabulary as prior context so Whisper
                        knows these words exist (max ~200 tokens).
        hotwords:       biases decoding toward specific terms.
        """
        try:
            store = get_dictionary_store()
            data = store.get_all()
            replacements = data.get("replacements", [])

            # Collect unique "to" values (the correct forms)
            vocab = []
            seen = set()
            for r in replacements:
                if not r.get("enabled", True):
                    continue
                word = r["to"].strip()
                if word and word not in seen:
                    seen.add(word)
                    vocab.append(word)

            # initial_prompt: natural sentence with vocabulary hints
            # Whisper uses this as "previous context", improving recognition
            # CTranslate2 position encoding limit = 448 tokens.
            # Japanese: ~1.5-2 tokens/char, so 150 chars ≈ 100-150 tokens (safe).
            prompt_words = []
            char_count = 0
            for w in vocab:
                if char_count + len(w) + 1 > 150:
                    break
                prompt_words.append(w)
                char_count += len(w) + 1

            self._initial_prompt = "、".join(prompt_words)

            # hotwords: space-separated for CTranslate2 hotword biasing
            self._hotwords = " ".join(vocab)

            logger.info(
                "Vocab hints: %d words in initial_prompt, %d in hotwords",
                len(prompt_words), len(vocab),
            )
        except Exception:
            logger.exception("Failed to build vocab hints")
            self._initial_prompt = ""
            self._hotwords = ""

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> dict:
        """Transcribe an audio segment.

        Args:
            audio: float32 numpy array of PCM samples
            sample_rate: sample rate (must be 16000)

        Returns:
            dict with keys: text, language, confidence
        """
        with self._inference_lock:
            return self._transcribe_once(audio, sample_rate)

    def _transcribe_once(self, audio: np.ndarray, sample_rate: int = 16000) -> dict:
        if self._model is None:
            if self._whisper_cpp is None or not self._whisper_cpp.is_loaded:
                raise RuntimeError("Model not loaded. Call load_model() first.")
            return self._whisper_cpp.transcribe(audio, sample_rate)

        if not check_temperature_safe(settings.gpu_temp_warning):
            logger.warning("GPU temperature high, transcription may be slower")

        t0 = time.monotonic()

        kwargs = {}

        if self.model_size in KOTOBA_MODELS:
            # kotoba-whisper: Japanese-tuned, skip initial_prompt and hotwords
            # to avoid breaking distil-whisper decoding (long hotwords cause empty output).
            kwargs["chunk_length"] = 15
            kwargs["condition_on_previous_text"] = False
        else:
            kwargs["condition_on_previous_text"] = False
            # hotwords only — initial_prompt は「直前の書き起こし」として注入され、
            # 無音区間で辞書単語をハルシネーションする原因になるため使わない
            if self._hotwords:
                kwargs["hotwords"] = self._hotwords

        decode_options = self._decode_options()
        segments, info = self._model.transcribe(
            audio,
            language=settings.whisper_language,
            vad_filter=False,  # We do our own VAD
            **decode_options,
            **kwargs,
        )

        # Collect all segment texts and confidence metrics
        texts = []
        no_speech_probs = []
        avg_logprobs = []
        compression_ratios = []

        for seg in segments:
            texts.append(seg.text.strip())
            no_speech_probs.append(seg.no_speech_prob)
            avg_logprobs.append(seg.avg_logprob)
            compression_ratios.append(seg.compression_ratio)

        text = " ".join(texts).strip()
        elapsed = time.monotonic() - t0

        # Aggregate metrics (worst-case for hallucination detection)
        if no_speech_probs:
            no_speech_prob = max(no_speech_probs)
            avg_logprob = sum(avg_logprobs) / len(avg_logprobs)
            compression_ratio = max(compression_ratios)
        else:
            no_speech_prob = 1.0
            avg_logprob = -2.0
            compression_ratio = 0.0

        logger.info(
            "Transcribed %.1fs audio in %.1fs (device=%s, beam=%s, no_speech=%.3f, logprob=%.3f, comp=%.2f): %s",
            len(audio) / sample_rate,
            elapsed,
            self._runtime_device or "unknown",
            decode_options.get("beam_size"),
            no_speech_prob,
            avg_logprob,
            compression_ratio,
            text[:80],
        )

        return {
            "text": text,
            "language": info.language,
            "confidence": info.language_probability,
            "no_speech_prob": no_speech_prob,
            "avg_logprob": avg_logprob,
            "compression_ratio": compression_ratio,
        }

    def start_cache_warm(self, model_size: str) -> None:
        """Start warming disk cache for a model in background thread."""
        if self._cache_warm_thread and self._cache_warm_thread.is_alive():
            return  # Already warming
        self._cache_warm_thread = threading.Thread(
            target=warm_disk_cache, args=(model_size,), daemon=True,
        )
        self._cache_warm_thread.start()
        logger.info("Started background cache warming for %s", model_size)

    def switch_model(self, new_model_size: str) -> None:
        """Switch to a different Whisper model size."""
        with self._model_load_lock:
            if new_model_size == self.model_size and self.is_loaded:
                self._loading_stage = ""
                return

            # Wait for any background cache warming to complete
            if self._cache_warm_thread and self._cache_warm_thread.is_alive():
                self._loading_stage = "warming"
                self._loading_progress = 0.15
                self._cache_warm_thread.join(timeout=120)

            with self._inference_lock:
                self._unload_model_once()
                self.model_size = new_model_size
                self._load_model_once()
            self._loading_stage = ""

    @property
    def is_loaded(self) -> bool:
        return self._model is not None or (
            self._whisper_cpp is not None and self._whisper_cpp.is_loaded
        )
