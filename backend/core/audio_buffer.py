"""Silero VAD integration and audio segmentation.

Accumulates audio frames, uses Silero VAD to detect speech,
and emits AudioSegment objects when a speech segment is complete.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

import numpy as np
import torch

from backend.config import settings

logger = logging.getLogger(__name__)

# Silero VAD operates on 512 samples at 16kHz (32ms per chunk)
VAD_CHUNK_SAMPLES = 512
_MS_PER_FRAME = (VAD_CHUNK_SAMPLES / 16000) * 1000  # 32ms at 16kHz
_DEBUG_LOG_INTERVAL = 100


class AudioBuffer:
    """Buffers incoming audio, applies VAD, and emits speech segments.

    Methods are organized in three logical groups:
      1. Initialization & model management
      2. Session lifecycle & audio feed
      3. VAD processing & segment emission
    """

    # ------------------------------------------------------------------ #
    #  1. Initialization & model management                               #
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float | None = None,
        min_silence_ms: int | None = None,
        max_segment_s: float | None = None,
        min_segment_s: float | None = None,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold or settings.vad_threshold
        self.min_silence_ms = min_silence_ms or settings.vad_min_silence_ms
        self.max_segment_s = max_segment_s or settings.vad_max_segment_s
        self.min_segment_s = min_segment_s or settings.vad_min_segment_s

        self._vad_model: torch.jit.ScriptModule | None = None
        self._speech_frames: list[np.ndarray] = []
        self._silence_counter_ms: float = 0
        self._is_speaking = False
        self._segment_start_time: float = 0.0
        self._session_start_time: float = 0.0
        self._pending: deque[np.ndarray] = deque()
        self._leftover: np.ndarray | None = None

        # Output queue for completed segments
        self.segment_queue: asyncio.Queue[dict] = asyncio.Queue()

        # Debug counters
        self._feed_count: int = 0
        self._frame_count: int = 0
        self._max_prob: float = 0.0

        # Speech ratio tracking (speech frames vs total frames in current segment)
        self._seg_speech_frames: int = 0
        self._seg_total_frames: int = 0

    def load_model(self) -> None:
        """Load Silero VAD model (CPU only, ~20MB)."""
        if self._vad_model is not None:
            return
        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._vad_model = model
        logger.info("Silero VAD model loaded")

    # ------------------------------------------------------------------ #
    #  2. Session lifecycle & audio feed                                   #
    # ------------------------------------------------------------------ #

    def start_session(self) -> None:
        """Reset state for a new session."""
        self._speech_frames.clear()
        self._silence_counter_ms = 0
        self._is_speaking = False
        self._segment_start_time = 0.0
        self._session_start_time = time.monotonic()
        self._pending.clear()
        self._leftover = None
        self._feed_count = 0
        self._frame_count = 0
        self._max_prob = 0.0
        self._drain_stale_segments()
        if self._vad_model is not None:
            self._vad_model.reset_states()
        logger.info("AudioBuffer session started (threshold=%.2f, model=%s)",
                     self.threshold, "loaded" if self._vad_model else "NONE")

    def _drain_stale_segments(self) -> None:
        """Remove any leftover segments from a previous session."""
        drained = 0
        while not self.segment_queue.empty():
            try:
                self.segment_queue.get_nowait()
                drained += 1
            except asyncio.QueueEmpty:
                break
        if drained:
            logger.info("Drained %d stale segments from previous session", drained)

    def feed(self, pcm_float32: np.ndarray) -> None:
        """Feed raw audio (16kHz mono float32) into the buffer.

        Called from the audio capture callback thread.
        """
        self._feed_count += 1
        if self._feed_count % _DEBUG_LOG_INTERVAL == 1:
            amp_max = float(np.max(np.abs(pcm_float32))) if len(pcm_float32) > 0 else 0.0
            logger.info(
                "AudioBuffer.feed #%d: len=%d, dtype=%s, amp_max=%.4f",
                self._feed_count, len(pcm_float32), pcm_float32.dtype, amp_max,
            )
        self._pending.append(pcm_float32)

    async def process_pending(self) -> None:
        """Process all pending audio chunks. Call from asyncio loop."""
        if self._vad_model is None and self._pending:
            logger.warning("process_pending: VAD model is None! Dropping %d chunks", len(self._pending))
            self._pending.clear()
            return
        count = len(self._pending)
        if count > 0 and count % 50 == 0:
            logger.info("process_pending: %d chunks queued", count)
        while self._pending:
            chunk = self._pending.popleft()
            self._process_chunk(chunk)

    def flush(self) -> None:
        """Force-emit any in-progress speech segment (called at session end)."""
        if self._is_speaking and self._speech_frames:
            self._emit_segment()

    # ------------------------------------------------------------------ #
    #  3. VAD processing & segment emission                                #
    # ------------------------------------------------------------------ #

    def _process_chunk(self, pcm: np.ndarray) -> None:
        """Run VAD on a chunk and manage speech segments."""
        if self._vad_model is None:
            return

        pcm = self._prepend_leftover(pcm)

        offset = 0
        while offset + VAD_CHUNK_SAMPLES <= len(pcm):
            frame = pcm[offset : offset + VAD_CHUNK_SAMPLES]
            offset += VAD_CHUNK_SAMPLES
            self._process_vad_frame(frame)

        if offset < len(pcm):
            self._leftover = pcm[offset:].copy()

    def _prepend_leftover(self, pcm: np.ndarray) -> np.ndarray:
        """Prepend leftover samples from previous chunk, if any."""
        if self._leftover is not None:
            pcm = np.concatenate([self._leftover, pcm])
            self._leftover = None
        return pcm

    def _process_vad_frame(self, frame: np.ndarray) -> None:
        """Classify a single VAD frame and update speech state."""
        tensor = torch.from_numpy(frame.copy())
        speech_prob = self._vad_model(tensor, self.sample_rate).item()
        is_speech = speech_prob >= self.threshold

        self._log_vad_debug(speech_prob)

        if is_speech:
            self._handle_speech_frame(frame, speech_prob)
        elif self._is_speaking:
            self._handle_silence_during_speech(frame)

        if self._is_speaking and self._speech_frames:
            duration = len(self._speech_frames) * VAD_CHUNK_SAMPLES / self.sample_rate
            if duration >= self.max_segment_s:
                self._emit_segment()

    def _log_vad_debug(self, speech_prob: float) -> None:
        """Track max probability and log periodically."""
        self._frame_count += 1
        if speech_prob > self._max_prob:
            self._max_prob = speech_prob
        if self._frame_count % _DEBUG_LOG_INTERVAL == 0:
            logger.info(
                "VAD frame #%d: prob=%.3f, max_prob=%.3f, is_speaking=%s",
                self._frame_count, speech_prob, self._max_prob, self._is_speaking,
            )
            self._max_prob = 0.0

    def _handle_speech_frame(self, frame: np.ndarray, speech_prob: float) -> None:
        """Handle a frame classified as speech."""
        if not self._is_speaking:
            self._is_speaking = True
            now = time.monotonic()
            self._segment_start_time = now - self._session_start_time
            logger.info("Speech started at %.1fs (prob=%.3f)", self._segment_start_time, speech_prob)
        self._speech_frames.append(frame)
        self._seg_speech_frames += 1
        self._seg_total_frames += 1
        self._silence_counter_ms = 0

    def _handle_silence_during_speech(self, frame: np.ndarray) -> None:
        """Handle a silence frame while speech is in progress."""
        self._speech_frames.append(frame)  # Keep trailing audio
        self._seg_total_frames += 1
        self._silence_counter_ms += _MS_PER_FRAME
        if self._silence_counter_ms >= self.min_silence_ms:
            self._emit_segment()

    def _emit_segment(self) -> None:
        """Finalize and enqueue a speech segment."""
        if not self._speech_frames:
            self._is_speaking = False
            return

        audio = np.concatenate(self._speech_frames)
        duration = len(audio) / self.sample_rate

        if duration < self.min_segment_s:
            logger.info("Segment too short (%.1fs < %.1fs), discarding", duration, self.min_segment_s)
            self._reset_speech_state()
            return

        speech_ratio = (
            self._seg_speech_frames / self._seg_total_frames
            if self._seg_total_frames > 0 else 0.0
        )

        segment = {
            "audio": audio,
            "sample_rate": self.sample_rate,
            "timestamp_start": self._segment_start_time,
            "timestamp_end": self._segment_start_time + duration,
            "speech_ratio": speech_ratio,
        }

        try:
            self.segment_queue.put_nowait(segment)
            logger.info(
                "Speech segment: %.1fs - %.1fs (%.1fs, speech_ratio=%.2f)",
                segment["timestamp_start"],
                segment["timestamp_end"],
                duration,
                speech_ratio,
            )
        except asyncio.QueueFull:
            logger.warning("Segment queue full, dropping segment")

        self._reset_speech_state()
        if self._vad_model is not None:
            self._vad_model.reset_states()

    def _reset_speech_state(self) -> None:
        """Clear speech accumulation state after segment emission or discard."""
        self._speech_frames.clear()
        self._is_speaking = False
        self._silence_counter_ms = 0
        self._seg_speech_frames = 0
        self._seg_total_frames = 0
