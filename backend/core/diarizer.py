"""Speaker identification using WeSpeaker ResNet34-LM embedding model.

Uses WeSpeaker ResNet34-LM (EER 0.723%) for speaker embedding extraction (~500MB VRAM).
Compares audio segment embeddings against pre-registered speaker embeddings
via cosine similarity.
"""

from __future__ import annotations

import logging

import numpy as np
import torch

from backend.config import settings
from backend.core.speaker_cluster import AdaptiveThresholdTracker
from backend.storage.speaker_store import get_speaker_store

logger = logging.getLogger(__name__)

# Embedding dimension for WeSpeaker ResNet34-LM (pyannote/wespeaker-voxceleb-resnet34-LM)
EMBEDDING_DIM = 256


class Diarizer:
    """Extract speaker embeddings and match against registered speakers."""

    def __init__(self):
        self._model = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._threshold_tracker = AdaptiveThresholdTracker(settings.speaker_similarity_threshold)

    def load_model(self) -> None:
        """Load the WeSpeaker ResNet34-LM embedding model."""
        if self._model is not None:
            return

        from pyannote.audio import Model

        # Monkey-patch torch.load to force weights_only=False during model loading.
        # PyTorch 2.6 defaults weights_only=True, but pyannote checkpoints contain
        # custom classes (TorchVersion, Specifications, Problem) that fail unpickling.
        # Patching torch.load directly is necessary because multiple call sites
        # (pyannote.audio.core.model, pytorch_lightning.core.saving) each import
        # lightning_fabric's _load independently.
        _orig_torch_load = torch.load

        def _patched_torch_load(*args, **kwargs):
            kwargs["weights_only"] = False
            return _orig_torch_load(*args, **kwargs)

        # Disable cuDNN to avoid cudnnGetLibConfig crash on Windows
        # (cuDNN 9.1 symbol missing → 0xC0000409 stack buffer overrun)
        torch.backends.cudnn.enabled = False

        hf_token = settings.hf_token or None
        logger.info("Loading WeSpeaker ResNet34-LM model...")
        try:
            torch.load = _patched_torch_load
            self._model = Model.from_pretrained(
                "pyannote/wespeaker-voxceleb-resnet34-LM",
                token=hf_token,
            )
        finally:
            torch.load = _orig_torch_load
        self._model.to(self._device)
        self._model.eval()
        logger.info("WeSpeaker ResNet34-LM loaded on %s (cudnn disabled)", self._device)

    def unload_model(self) -> None:
        """Release the model."""
        if self._model is not None:
            del self._model
            self._model = None
            if self._device == "cuda":
                import gc

                gc.collect()
                torch.cuda.empty_cache()
            logger.info("WeSpeaker ResNet34-LM model unloaded")

    def extract_embedding(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Extract a 256-dim embedding from an audio segment.

        Args:
            audio: float32 numpy array (mono)
            sample_rate: sample rate of the audio

        Returns:
            L2-normalized 256-dim embedding vector
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        # Peak normalization
        peak = float(np.max(np.abs(audio)))
        if peak > 1e-4:
            audio = audio / peak

        # WeSpeaker expects tensor of shape (batch, channel, sample)
        waveform = torch.from_numpy(audio).float().unsqueeze(0).unsqueeze(0)

        # Resample if needed (WeSpeaker expects 16kHz)
        if sample_rate != 16000:
            import torchaudio
            waveform = torchaudio.functional.resample(
                waveform.squeeze(0), sample_rate, 16000
            ).unsqueeze(0)

        with torch.inference_mode():
            embeddings = self._model(waveform.to(self._device))

        # L2 normalize
        emb = embeddings.squeeze().cpu().numpy()
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm

        return emb

    def extract_embedding_windowed(self, audio: np.ndarray, sample_rate: int = 16000,
                                      window_s: float = 3.0, hop_s: float = 1.5) -> np.ndarray:
        """Extract embedding using windowed averaging for longer segments."""
        total_duration = len(audio) / sample_rate
        if total_duration <= window_s + 1.0:
            return self.extract_embedding(audio, sample_rate)

        embeddings = []
        window_samples = int(window_s * sample_rate)
        hop_samples = int(hop_s * sample_rate)
        for start in range(0, len(audio) - window_samples + 1, hop_samples):
            chunk = audio[start:start + window_samples]
            embeddings.append(self.extract_embedding(chunk, sample_rate))

        avg = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(avg)
        if norm > 0:
            avg = avg / norm
        return avg

    def identify_speaker(self, audio: np.ndarray, sample_rate: int = 16000) -> dict:
        """Identify the speaker in an audio segment.

        Returns:
            dict with keys: speaker_id, speaker_name, confidence, embedding
        """
        embedding = self.extract_embedding_windowed(audio, sample_rate)
        store = get_speaker_store()
        registered = store.get_all_embeddings()

        if not registered:
            return {
                "speaker_id": "unknown",
                "speaker_name": "Unknown",
                "confidence": 0.0,
                "embedding": embedding,
            }

        best_id = "unknown"
        best_name = "Unknown"
        best_score = 0.0
        best_accepted_threshold: float | None = None

        for speaker_id, name, ref_embedding, accepted_threshold in registered:
            score = float(np.dot(embedding, ref_embedding))
            if score > best_score:
                best_score = score
                best_id = speaker_id
                best_name = name
                best_accepted_threshold = accepted_threshold

        # Per-speaker threshold takes priority over global threshold
        effective_threshold = self._threshold_tracker.get_threshold()
        if best_accepted_threshold is not None:
            effective_threshold = min(effective_threshold, best_accepted_threshold)

        if best_score < effective_threshold:
            self._threshold_tracker.record(best_score, matched=False)
            result = {
                "speaker_id": "unknown",
                "speaker_name": "Unknown",
                "confidence": best_score,
                "embedding": embedding,
            }
            # Add suggestion if score is above suggestion threshold
            suggestion_threshold = settings.speaker_suggestion_threshold
            if best_score >= suggestion_threshold and best_id != "unknown":
                result["suggested_speaker_id"] = best_id
                result["suggested_speaker_name"] = best_name
            return result

        self._threshold_tracker.record(best_score, matched=True)
        return {
            "speaker_id": best_id,
            "speaker_name": best_name,
            "confidence": best_score,
            "embedding": embedding,
        }

    def compute_average_embedding(self, audio_segments: list[np.ndarray], sample_rate: int = 16000) -> np.ndarray:
        """Compute averaged L2-normalized embedding from multiple audio samples."""
        embeddings = []
        for audio in audio_segments:
            emb = self.extract_embedding(audio, sample_rate)
            embeddings.append(emb)

        avg = np.mean(embeddings, axis=0)
        norm = np.linalg.norm(avg)
        if norm > 0:
            avg = avg / norm

        return avg

    @property
    def is_loaded(self) -> bool:
        return self._model is not None
