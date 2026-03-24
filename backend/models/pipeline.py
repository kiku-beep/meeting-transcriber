"""Transcription pipeline — VAD segment collection, Whisper transcription, diarization."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from functools import partial

import numpy as np

from backend.config import settings
from backend.core.audio_buffer import AudioBuffer
from backend.core.diarizer import Diarizer
from backend.core.post_processor import post_process, split_sentences
from backend.core.speaker_cluster import SessionClusterManager
from backend.core.transcriber import Transcriber
from backend.models.schemas import TranscriptEntry
from backend.storage.dictionary_store import get_dictionary_store
from backend.storage.file_store import save_session

logger = logging.getLogger(__name__)

AUTOSAVE_INTERVAL_ENTRIES = 50


class TranscriptionPipeline:
    """Collects VAD segments, transcribes, diarizes, and appends entries."""

    def __init__(self, mic_buffer: AudioBuffer, loopback_buffer: AudioBuffer,
                 transcriber: Transcriber, diarizer: Diarizer,
                 cluster_manager: SessionClusterManager,
                 entries: list[TranscriptEntry],
                 entry_embeddings: dict[str, np.ndarray],
                 entry_audio: dict[str, np.ndarray],
                 new_entry_event: asyncio.Event,
                 stop_event: asyncio.Event):
        self._mic_buffer = mic_buffer
        self._loopback_buffer = loopback_buffer
        self._transcriber = transcriber
        self._diarizer = diarizer
        self._cluster_manager = cluster_manager
        self._entries = entries
        self._entry_embeddings = entry_embeddings
        self._entry_audio = entry_audio
        self._new_entry_event = new_entry_event
        self._stop_event = stop_event

        self._last_autosave: int = 0
        self._last_autosave_time: float = 0.0
        self._has_loopback: bool = False
        self._session_id: str = ""
        self._session_name: str = ""
        self._started_at: datetime | None = None

    def configure(self, session_id: str, session_name: str,
                  started_at: datetime | None, has_loopback: bool) -> None:
        """Set session metadata at start time."""
        self._session_id = session_id
        self._session_name = session_name
        self._started_at = started_at
        self._has_loopback = has_loopback
        self._last_autosave = 0
        self._last_autosave_time = time.time()

    def collect_segments(self) -> list[dict]:
        """Collect ready segments from all audio buffers."""
        segments = []
        for buf, source in [(self._mic_buffer, "microphone"), (self._loopback_buffer, "loopback")]:
            while True:
                try:
                    seg = buf.segment_queue.get_nowait()
                    seg["source"] = source
                    segments.append(seg)
                except asyncio.QueueEmpty:
                    break
        return segments

    async def process_segment(self, segment: dict, loop) -> None:
        """Transcribe and diarize a single segment, append to entries."""
        audio_data = segment["audio"]

        if settings.debug_save_segments:
            try:
                import soundfile as sf
                seg_dir = settings.sessions_dir / self._session_id / "segments"
                seg_dir.mkdir(parents=True, exist_ok=True)
                ts = f"{segment['timestamp_start']:.1f}"
                peak = float(np.max(np.abs(audio_data)))
                seg_path = seg_dir / f"seg_{ts}s_peak{peak:.4f}.wav"
                sf.write(str(seg_path), audio_data, segment["sample_rate"], subtype="FLOAT")
                logger.info("Debug segment saved: %s (%.1fs, peak=%.4f)", seg_path.name,
                            len(audio_data) / segment["sample_rate"], peak)
            except Exception:
                logger.exception("Failed to save debug segment")

        duration = segment["timestamp_end"] - segment["timestamp_start"]
        MIN_EMBEDDING_DURATION = 2.0

        # Audio quality gating
        peak = float(np.max(np.abs(audio_data)))
        rms = float(np.sqrt(np.mean(audio_data ** 2)))

        # Layer 1: RMS energy gate — skip transcription entirely for noise spikes
        if rms < settings.hallucination_rms_threshold:
            logger.info(
                "Segment filtered (low RMS): peak=%.4f, rms=%.6f < %.6f, duration=%.1fs",
                peak, rms, settings.hallucination_rms_threshold, duration,
            )
            return

        skip_embedding = duration < MIN_EMBEDDING_DURATION or peak < 0.01

        try:
            if skip_embedding:
                result = await loop.run_in_executor(
                    None,
                    partial(self._transcriber.transcribe, audio_data, segment["sample_rate"]),
                )
                speaker = self._get_previous_speaker()
            else:
                result, speaker = await asyncio.gather(
                    loop.run_in_executor(
                        None,
                        partial(self._transcriber.transcribe, audio_data, segment["sample_rate"]),
                    ),
                    loop.run_in_executor(
                        None,
                        partial(self._diarizer.identify_speaker, audio_data, segment["sample_rate"]),
                    ),
                )
        except Exception:
            logger.exception("Transcription/diarization failed for segment, skipping")
            return

        if not result["text"]:
            return

        # Layer 2: Whisper confidence metrics filtering
        no_speech_prob = result.get("no_speech_prob", 0.0)
        avg_logprob = result.get("avg_logprob", 0.0)
        compression_ratio = result.get("compression_ratio", 0.0)

        if no_speech_prob > settings.hallucination_no_speech_threshold:
            logger.info(
                "Segment filtered (high no_speech_prob): %.3f > %.3f, text='%s'",
                no_speech_prob, settings.hallucination_no_speech_threshold,
                result["text"][:50],
            )
            return

        if avg_logprob < settings.hallucination_logprob_threshold:
            logger.info(
                "Segment filtered (low avg_logprob): %.3f < %.3f, text='%s'",
                avg_logprob, settings.hallucination_logprob_threshold,
                result["text"][:50],
            )
            return

        if compression_ratio > settings.hallucination_compression_threshold:
            logger.info(
                "Segment filtered (high compression_ratio): %.2f > %.2f, text='%s'",
                compression_ratio, settings.hallucination_compression_threshold,
                result["text"][:50],
            )
            return

        cluster_id = None
        suggested_speaker_id = speaker.get("suggested_speaker_id")
        suggested_speaker_name = speaker.get("suggested_speaker_name")
        if speaker["speaker_id"] == "unknown" and "embedding" in speaker:
            prev_cid = self._entries[-1].cluster_id if self._entries else None
            time_gap = segment["timestamp_start"] - self._entries[-1].timestamp_end if self._entries else 999.0
            cid, label, conf = self._cluster_manager.match_or_create(
                speaker["embedding"], prev_cluster_id=prev_cid, time_gap=time_gap)
            speaker["speaker_id"] = cid
            speaker["speaker_name"] = label
            speaker["confidence"] = conf
            cluster_id = cid

        cleaned = post_process(result["text"])
        if not cleaned:
            return

        # Layer 3: Repetitive text filter (e.g. "映像 映像 映像 映像")
        if self._is_repetitive_text(cleaned):
            logger.info(
                "Segment filtered (repetitive text): text='%s', duration=%.1fs",
                cleaned[:60], duration,
            )
            return

        # Layer 4: Hallucination phrase filter
        speech_ratio = segment.get("speech_ratio", 1.0)
        if self._is_hallucination_phrase(cleaned, duration, no_speech_prob, avg_logprob, speech_ratio):
            logger.info(
                "Segment filtered (hallucination phrase): text='%s', duration=%.1fs, "
                "no_speech_prob=%.3f, avg_logprob=%.3f, speech_ratio=%.2f",
                cleaned, duration, no_speech_prob, avg_logprob, speech_ratio,
            )
            return

        sentences = split_sentences(cleaned)
        seg_start = segment["timestamp_start"]
        seg_end = segment["timestamp_end"]
        seg_duration = seg_end - seg_start
        total_chars = sum(len(s) for s in sentences)

        cursor = seg_start
        for sentence in sentences:
            ratio = len(sentence) / total_chars if total_chars > 0 else 1.0
            part_duration = seg_duration * ratio

            entry_id = str(uuid.uuid4())[:8]
            entry = TranscriptEntry(
                id=entry_id,
                text=sentence,
                raw_text=result["text"] if sentence is sentences[0] else "",
                speaker_name=speaker["speaker_name"],
                speaker_id=speaker["speaker_id"],
                speaker_confidence=speaker["confidence"],
                cluster_id=cluster_id,
                suggested_speaker_id=suggested_speaker_id,
                suggested_speaker_name=suggested_speaker_name,
                source=segment.get("source", ""),
                timestamp_start=cursor,
                timestamp_end=cursor + part_duration,
            )
            self._entries.append(entry)
            if "embedding" in speaker:
                self._entry_embeddings[entry_id] = speaker["embedding"]
            # Save audio segment for this entry
            self._entry_audio[entry_id] = audio_data.copy()
            logger.info("[%s] %s", entry.speaker_name, entry.text)
            cursor += part_duration

        self._new_entry_event.set()

    def _is_repetitive_text(self, text: str) -> bool:
        """Detect repetitive hallucinations like '映像 映像 映像 映像'."""
        import re
        clean = text.strip()
        if len(clean) < 4:
            return False

        # Pattern 1: Same token repeated 3+ times (space/comma separated)
        # e.g. "映像 映像 映像" or "エネチーム、エネチーム、エネチーム"
        tokens = re.split(r'[\s、,，]+', clean)
        tokens = [t for t in tokens if t]
        if len(tokens) >= 3:
            from collections import Counter
            counts = Counter(tokens)
            most_common_count = counts.most_common(1)[0][1]
            if most_common_count >= 3 and most_common_count / len(tokens) >= 0.5:
                return True

        # Pattern 2: Substring repeated 3+ times consecutively
        # e.g. "携帯電子 携帯電子 携帯電子"
        for ngram_len in range(2, min(len(clean) // 3 + 1, 20)):
            for start in range(len(clean) - ngram_len * 3 + 1):
                sub = clean[start:start + ngram_len]
                if sub.strip() and clean.count(sub) >= 3:
                    consecutive = sub * 3
                    if consecutive in clean:
                        return True

        return False

    def _is_hallucination_phrase(
        self, text: str, duration: float, no_speech_prob: float,
        avg_logprob: float = 0.0, speech_ratio: float = 1.0,
    ) -> bool:
        """Check if text matches a known hallucination phrase with supporting evidence.

        Standalone phrase (text == phrase exactly) is filtered unless ALL rescue
        conditions are met (high speech_ratio + high confidence + sufficient duration).
        Phrase embedded in longer text (e.g. "それではありがとうございました") is allowed.
        """
        store = get_dictionary_store()
        data = store.get_all()

        if not data.get("hallucination_filter_enabled", True):
            return False

        phrases = data.get("hallucination_phrases", [])
        if not phrases:
            return False

        # Normalize: strip whitespace and trailing punctuation
        cleaned = text.strip().rstrip("。、.!?！？")

        # Check if any hallucination phrase appears in the text
        matched_phrase = None
        for phrase in phrases:
            if phrase in cleaned:
                matched_phrase = phrase
                break

        if matched_phrase is None:
            return False

        # Phrase is embedded in longer text — allow it (genuine speech)
        if cleaned != matched_phrase:
            return False

        # Standalone phrase — filter unless ALL rescue conditions are met
        if (
            speech_ratio > settings.hallucination_speech_ratio_threshold
            and avg_logprob > settings.hallucination_logprob_rescue_threshold
            and duration > settings.hallucination_phrase_max_duration
            and no_speech_prob < 0.3
        ):
            logger.info(
                "Hallucination phrase rescued: text='%s', speech_ratio=%.2f, "
                "avg_logprob=%.3f, duration=%.1fs",
                cleaned, speech_ratio, avg_logprob, duration,
            )
            return False

        return True

    def _get_previous_speaker(self) -> dict:
        """Get speaker info from the most recent entry (for short segments)."""
        if self._entries:
            prev = self._entries[-1]
            return {
                "speaker_id": prev.speaker_id,
                "speaker_name": prev.speaker_name,
                "confidence": prev.speaker_confidence,
            }
        return {
            "speaker_id": "unknown",
            "speaker_name": "Unknown",
            "confidence": 0.0,
        }

    async def run(self) -> None:
        """Main processing loop: VAD -> Whisper -> entries."""
        logger.info("Pipeline loop started (has_loopback=%s)", self._has_loopback)
        loop = asyncio.get_event_loop()
        loop_count = 0

        while not self._stop_event.is_set():
            loop_count += 1
            if loop_count % 200 == 0:
                logger.info("Pipeline loop #%d: mic_pending=%d, lb_pending=%d",
                            loop_count, len(self._mic_buffer._pending),
                            len(self._loopback_buffer._pending))

            await self._mic_buffer.process_pending()
            if self._has_loopback:
                await self._loopback_buffer.process_pending()

            segments = self.collect_segments()
            if not segments:
                await asyncio.sleep(0.02)
                continue

            for segment in segments:
                await self.process_segment(segment, loop)

            # Try merging similar clusters and update entry labels
            merge_count = self._cluster_manager.try_merge_clusters()
            if merge_count > 0:
                merge_map = self._cluster_manager.pop_merge_map()
                for entry in self._entries:
                    if entry.cluster_id in merge_map:
                        new_cid = merge_map[entry.cluster_id]
                        new_label = self._cluster_manager.get_cluster_label(new_cid)
                        entry.cluster_id = new_cid
                        if new_label:
                            entry.speaker_name = new_label
                self._new_entry_event.set()

            now = time.time()
            entries_since = len(self._entries) - self._last_autosave
            if entries_since >= AUTOSAVE_INTERVAL_ENTRIES or (entries_since > 0 and now - self._last_autosave_time >= 300):
                save_session(self._session_id, self._entries, {
                    "session_name": self._session_name,
                    "started_at": self._started_at.isoformat() if self._started_at else None,
                })
                self._last_autosave = len(self._entries)
                self._last_autosave_time = now
                logger.info("Auto-saved session %s (%d entries)", self._session_id, len(self._entries))

        await self._mic_buffer.process_pending()
        if self._has_loopback:
            await self._loopback_buffer.process_pending()
        self._mic_buffer.flush()
        if self._has_loopback:
            self._loopback_buffer.flush()
        for segment in self.collect_segments():
            await self.process_segment(segment, loop)

        logger.info("Pipeline loop ended")
