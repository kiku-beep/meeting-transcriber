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
    """Wraps Faster-Whisper for GPU-accelerated transcription."""

    def __init__(self, model_size: str | None = None):
        self.model_size = model_size or settings.whisper_model
        self._model: WhisperModel | None = None
        self._initial_prompt: str = ""
        self._hotwords: str = ""
        # Loading stage tracking for progress UI
        self._loading_stage: str = ""  # "", "unloading", "warming", "loading", "ready"
        self._loading_progress: float = 0.0  # 0.0 - 1.0
        self._cache_warm_thread: threading.Thread | None = None

    def load_model(self) -> None:
        """Load the Whisper model onto GPU."""
        if self._model is not None:
            return

        required_mb = VRAM_REQUIREMENTS.get(self.model_size, 3000)
        if not check_vram_available(required_mb):
            logger.warning(
                "Insufficient VRAM for %s (need %dMB). Loading anyway...",
                self.model_size,
                required_mb,
            )

        # Resolve HuggingFace model ID if needed
        model_id = MODEL_HF_IDS.get(self.model_size, self.model_size)
        compute = "int8_float16" if self.model_size in INT8_MODELS else "float16"

        logger.info("Loading Faster-Whisper model: %s (%s, %s)", self.model_size, model_id, compute)
        self._loading_stage = "loading"
        self._loading_progress = 0.3
        t0 = time.monotonic()

        self._model = WhisperModel(
            model_id,
            device="cuda",
            compute_type=compute,
        )

        elapsed = time.monotonic() - t0
        self._loading_stage = "ready"
        self._loading_progress = 1.0
        logger.info("Whisper %s loaded in %.1fs (compute=%s)", self.model_size, elapsed, compute)

    def unload_model(self) -> None:
        """Release the model and free VRAM."""
        if self._model is not None:
            self._loading_stage = "unloading"
            self._loading_progress = 0.1
            del self._model
            self._model = None

            import gc
            import torch

            gc.collect()
            torch.cuda.empty_cache()
            logger.info("Whisper model unloaded")

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
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

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

        segments, info = self._model.transcribe(
            audio,
            language=settings.whisper_language,
            beam_size=5,
            vad_filter=False,  # We do our own VAD
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
            "Transcribed %.1fs audio in %.1fs (no_speech=%.3f, logprob=%.3f, comp=%.2f): %s",
            len(audio) / sample_rate,
            elapsed,
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
        if new_model_size == self.model_size and self._model is not None:
            self._loading_stage = ""
            return

        # Wait for any background cache warming to complete
        if self._cache_warm_thread and self._cache_warm_thread.is_alive():
            self._loading_stage = "warming"
            self._loading_progress = 0.15
            self._cache_warm_thread.join(timeout=120)

        self.unload_model()
        self.model_size = new_model_size
        self.load_model()
        self._loading_stage = ""

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
