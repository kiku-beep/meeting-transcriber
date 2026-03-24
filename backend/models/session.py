"""Session state machine — manages the transcription pipeline lifecycle."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import numpy as np

from backend.config import settings
from backend.core.audio_buffer import AudioBuffer
from backend.core.diarizer import Diarizer
from backend.core.speaker_cluster import SessionClusterManager
from backend.core.transcriber import Transcriber
from backend.models.audio_stream import AudioStreamManager
from backend.models.pipeline import TranscriptionPipeline
from backend.models.schemas import SessionStatus, TranscriptEntry
from backend.storage.file_store import save_session
from backend.core.segmentation_refiner import SegmentationRefiner
from backend.core.text_refiner import TextRefiner
from backend.storage.dictionary_store import get_dictionary_store
from backend.storage.speaker_store import get_speaker_store

logger = logging.getLogger(__name__)


def compute_sample_quality(
    audio: np.ndarray,
    duration: float,
    speaker_confidence: float,
    embedding: np.ndarray | None,
    profile_embedding: np.ndarray | None,
) -> float:
    """Compute quality score for an audio sample (0.0 to 1.0).

    Components:
      - duration (0.20): Longer = more reliable embedding
      - confidence (0.35): Higher = better match certainty
      - energy (0.15): Higher RMS = cleaner speech signal
      - coherence (0.30): How well embedding matches existing profile
    """
    duration_score = min(duration / 8.0, 1.0)
    confidence_score = speaker_confidence
    rms = float(np.sqrt(np.mean(audio ** 2)))
    energy_score = min(rms / 0.05, 1.0)
    if embedding is not None and profile_embedding is not None:
        coherence_score = max(0.0, float(np.dot(embedding, profile_embedding)))
    else:
        coherence_score = 0.5
    quality = (
        0.20 * duration_score
        + 0.35 * confidence_score
        + 0.15 * energy_score
        + 0.30 * coherence_score
    )
    return float(np.clip(quality, 0.0, 1.0))


class TranscriptionSession:
    """Facade — owns session state and delegates audio/pipeline work."""

    def __init__(self):
        self.session_id: str = ""
        self.session_name: str = ""
        self.status: SessionStatus = SessionStatus.IDLE
        self.started_at: datetime | None = None
        self.entries: list[TranscriptEntry] = []

        self._mic_buffer = AudioBuffer()
        self._loopback_buffer = AudioBuffer()
        self._transcriber = Transcriber()
        self._diarizer = Diarizer()
        self._cluster_manager = SessionClusterManager()
        self._new_entry_event = asyncio.Event()
        self._entry_embeddings: dict[str, np.ndarray] = {}
        self._entry_audio: dict[str, np.ndarray] = {}  # entry_id -> audio segment

        self._recorded_audio: list[np.ndarray] = []
        self._recorded_audio_raw: list[np.ndarray] = []
        self._recorded_loopback: list[np.ndarray] = []

        self._audio = AudioStreamManager()
        self._audio.setup(
            self._mic_buffer, self._loopback_buffer,
            self._recorded_audio, lambda: self.status,
            self._recorded_audio_raw,
            self._recorded_loopback,
        )

        self._stop_event = asyncio.Event()
        self._pipeline = TranscriptionPipeline(
            self._mic_buffer, self._loopback_buffer,
            self._transcriber, self._diarizer, self._cluster_manager,
            self.entries, self._entry_embeddings, self._entry_audio,
            self._new_entry_event, self._stop_event,
        )
        self._pipeline_task: asyncio.Task | None = None
        self._refiner = SegmentationRefiner()
        self._refiner_task: asyncio.Task | None = None
        self._text_refiner = TextRefiner(settings, get_dictionary_store())
        self._text_refiner_task: asyncio.Task | None = None
        self._has_loopback: bool = False

        self._device_monitor_task: asyncio.Task | None = None
        self._device_watcher = None  # Initialized on first start

    @property
    def refined_queue(self) -> asyncio.Queue:
        return self._text_refiner._refined_queue

    @property
    def info(self) -> dict:
        elapsed = 0.0
        if self.started_at and self.status == SessionStatus.RUNNING:
            elapsed = (datetime.now() - self.started_at).total_seconds()
        return {
            "status": self.status.value,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "entry_count": len(self.entries),
            "elapsed_seconds": round(elapsed, 1),
            "mic_speaking": self._mic_buffer._is_speaking,
            "loopback_speaking": self._loopback_buffer._is_speaking,
            "mic_device": self._audio.current_mic_name,
            "loopback_device": self._audio.current_loopback_name,
        }

    async def start(self, device_index: int | None = None,
                    loopback_device_index: int | None = None,
                    session_name: str = "") -> None:
        """Start a transcription session."""
        if self.status != SessionStatus.IDLE:
            raise RuntimeError(f"Cannot start session in {self.status} state")

        self.status = SessionStatus.STARTING
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.session_name = session_name
        self.started_at = datetime.now()
        self.entries.clear()
        self._entry_embeddings.clear()
        self._entry_audio.clear()
        self._cluster_manager.reset()
        self._recorded_audio.clear()
        self._recorded_audio_raw.clear()
        self._recorded_loopback.clear()
        self._stop_event.clear()
        self._audio.reset_counters()

        try:
            if not self._transcriber.is_loaded or not self._diarizer.is_loaded:
                logger.info("Loading models...")
                self._mic_buffer.load_model()
                loop = asyncio.get_event_loop()
                loads = [
                    loop.run_in_executor(None, self._transcriber.load_model),
                    loop.run_in_executor(None, self._diarizer.load_model),
                ]
                if settings.segmentation_refine_enabled and not self._refiner.is_loaded:
                    loads.append(loop.run_in_executor(None, self._refiner.load_model))
                await asyncio.gather(*loads)
            else:
                self._mic_buffer.load_model()

            self._transcriber.build_vocab_hints()

            # Auto-detect devices from Windows defaults if not specified
            if device_index is None and loopback_device_index is None:
                from backend.core.audio_capture import get_default_microphone, get_default_loopback
                default_mic = get_default_microphone()
                default_lb = get_default_loopback()
                if default_mic:
                    device_index = default_mic.index
                if default_lb:
                    loopback_device_index = default_lb.index

            self._audio.open_mic_stream(device_index)
            self._has_loopback = loopback_device_index is not None
            if self._has_loopback:
                self._loopback_buffer.load_model()
                self._audio.open_loopback_stream(loopback_device_index)

            self._mic_buffer.start_session()
            if self._has_loopback:
                self._loopback_buffer.start_session()

            self._pipeline.configure(
                self.session_id, self.session_name,
                self.started_at, self._has_loopback,
            )
            self._pipeline_task = asyncio.create_task(self._pipeline.run())

            # Start segmentation refinement background task (Pass 2)
            if settings.segmentation_refine_enabled and self._refiner.is_loaded:
                self._refiner_task = asyncio.create_task(
                    self._refiner.run(
                        self._stop_event,
                        self._recorded_audio,
                        self.entries,
                        self._entry_embeddings,
                        self._cluster_manager,
                        self._new_entry_event,
                    )
                )

            # Start text refinement (Pass 2 — Gemini Flash)
            self._text_refiner.start(self.entries)

            self.status = SessionStatus.RUNNING

            # Start device change detection (event-driven with polling fallback)
            self._start_device_watcher()

            # Start screen capture if enabled
            if settings.screenshot_enabled:
                from backend.core.screen_capture import get_screen_capturer
                try:
                    get_screen_capturer().start(self.session_id)
                except Exception:
                    logger.warning("Failed to start screen capture", exc_info=True)

            logger.info("Session %s started", self.session_id)

        except Exception:
            self._audio.close_streams()
            self.status = SessionStatus.IDLE
            logger.exception("Failed to start session")
            raise

    async def stop(self) -> None:
        """Stop the current session."""
        if self.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED):
            return

        self.status = SessionStatus.STOPPING

        # Stop device watcher
        self._stop_device_watcher()

        # Stop screen capture
        from backend.core.screen_capture import get_screen_capturer
        try:
            get_screen_capturer().stop()
        except Exception:
            logger.warning("Failed to stop screen capture", exc_info=True)

        self._stop_event.set()

        self._audio.close_streams()

        if self._pipeline_task:
            try:
                await asyncio.wait_for(self._pipeline_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("Pipeline drain timed out, cancelling")
                self._pipeline_task.cancel()
                try:
                    await self._pipeline_task
                except asyncio.CancelledError:
                    pass
            self._pipeline_task = None

        if self._refiner_task:
            try:
                await asyncio.wait_for(self._refiner_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._refiner_task.cancel()
                try:
                    await self._refiner_task
                except asyncio.CancelledError:
                    pass
            self._refiner_task = None

        await self._text_refiner.stop()

        await self._update_speaker_profiles()
        self._auto_accumulate_samples()
        self._offline_recluster()

        meta = {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "session_name": self.session_name,
        }
        save_session(self.session_id, self.entries, meta)

        if self._recorded_audio and settings.audio_saving_enabled:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._save_audio)
        elif self._recorded_audio:
            logger.info("Audio saving disabled — skipping WAV save")
            self._recorded_audio.clear()
            self._recorded_audio_raw.clear()
            self._recorded_loopback.clear()

        # Trim trailing silence (forgot-to-stop detection)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._trim_trailing_silence
            )
        except Exception:
            logger.warning("Trailing silence trim failed", exc_info=True)

        self.status = SessionStatus.IDLE
        logger.info(
            "Session %s stopped. %d entries.", self.session_id, len(self.entries)
        )

    async def discard(self) -> None:
        """Discard the current session without saving any data."""
        if self.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED):
            return

        self.status = SessionStatus.STOPPING

        # Stop device monitor
        if self._device_monitor_task:
            self._device_monitor_task.cancel()
            try:
                await self._device_monitor_task
            except asyncio.CancelledError:
                pass
            self._device_monitor_task = None

        # Stop screen capture
        from backend.core.screen_capture import get_screen_capturer
        try:
            get_screen_capturer().stop()
        except Exception:
            logger.warning("Failed to stop screen capture", exc_info=True)

        self._stop_event.set()
        self._audio.close_streams()

        # Cancel pipeline immediately (no drain needed)
        if self._pipeline_task:
            self._pipeline_task.cancel()
            try:
                await self._pipeline_task
            except asyncio.CancelledError:
                pass
            self._pipeline_task = None

        if self._refiner_task:
            self._refiner_task.cancel()
            try:
                await self._refiner_task
            except asyncio.CancelledError:
                pass
            self._refiner_task = None

        await self._text_refiner.stop()

        # Delete any screenshots already saved for this session
        import shutil
        session_dir = settings.sessions_dir / self.session_id
        if session_dir.exists():
            shutil.rmtree(session_dir)

        self.status = SessionStatus.IDLE
        logger.info("Session %s discarded.", self.session_id)

    async def pause(self) -> None:
        """Toggle pause/resume."""
        if self.status == SessionStatus.RUNNING:
            self.status = SessionStatus.PAUSED
            logger.info("Session paused")
        elif self.status == SessionStatus.PAUSED:
            self.status = SessionStatus.RUNNING
            logger.info("Session resumed")

    def terminate_pyaudio(self) -> None:
        """Terminate PyAudio (call only on app shutdown)."""
        self._audio.terminate()

    def _offline_recluster(self) -> None:
        """Re-cluster anonymous entries using HAC after session ends."""
        # Collect anonymous entries with embeddings (skip manually corrected / registered)
        anon_indices = []
        anon_embeddings = []
        for i, entry in enumerate(self.entries):
            if not entry.cluster_id or not entry.cluster_id.startswith("cluster_"):
                continue
            emb = self._entry_embeddings.get(entry.id)
            if emb is not None:
                anon_indices.append(i)
                anon_embeddings.append(emb)

        if len(anon_embeddings) < 3:
            return

        try:
            from scipy.cluster.hierarchy import fcluster, linkage
            from scipy.spatial.distance import pdist

            emb_matrix = np.stack(anon_embeddings)
            dists = pdist(emb_matrix, metric="cosine")
            Z = linkage(dists, method="average")
            threshold = 1.0 - settings.speaker_cluster_threshold
            labels = fcluster(Z, t=threshold, criterion="distance")

            # Build new label map
            label_map: dict[int, str] = {}
            for idx, label_id in enumerate(labels):
                entry_idx = anon_indices[idx]
                old_cid = self.entries[entry_idx].cluster_id
                if int(label_id) not in label_map:
                    # Reuse old label if possible
                    label_map[int(label_id)] = old_cid or f"recluster_{label_id}"

            reassigned = 0
            for idx, label_id in enumerate(labels):
                entry_idx = anon_indices[idx]
                new_cid = label_map[int(label_id)]
                if self.entries[entry_idx].cluster_id != new_cid:
                    self.entries[entry_idx].cluster_id = new_cid
                    reassigned += 1

            if reassigned > 0:
                logger.info("Offline re-clustering: %d entries reassigned across %d clusters",
                            reassigned, len(set(labels)))
        except ImportError:
            logger.warning("scipy not available, skipping offline re-clustering")
        except Exception:
            logger.exception("Offline re-clustering failed")

    async def _update_speaker_profiles(self) -> None:
        """Update registered speaker profiles with session embeddings (EMA)."""
        speaker_embs: dict[str, list[tuple[np.ndarray, float]]] = {}
        for entry in self.entries:
            if entry.speaker_id.startswith("cluster_") or entry.speaker_id.startswith("guest_") or entry.speaker_id == "unknown":
                continue
            if entry.speaker_confidence >= 0.65:
                emb = self._entry_embeddings.get(entry.id)
                if emb is not None:
                    speaker_embs.setdefault(entry.speaker_id, []).append(
                        (emb, entry.speaker_confidence)
                    )

        store = get_speaker_store()
        for sid, emb_conf_pairs in speaker_embs.items():
            if len(emb_conf_pairs) < settings.speaker_min_session_matches:
                continue

            embs = [e for e, c in emb_conf_pairs]
            confidences = [c for e, c in emb_conf_pairs]

            weights = np.array(confidences)
            weights /= weights.sum()
            session_avg = np.zeros_like(embs[0])
            for emb, w in zip(embs, weights):
                session_avg += emb * w
            norm = np.linalg.norm(session_avg)
            if norm > 0:
                session_avg /= norm

            avg_confidence = float(np.mean(confidences))
            match_count = len(emb_conf_pairs)

            store.update_embedding(
                sid, session_avg,
                session_confidence=avg_confidence,
                session_match_count=match_count,
            )
            store.increment_session_count(sid)

            logger.info(
                "Updated speaker %s profile: %d embeddings, avg_confidence=%.3f",
                sid, match_count, avg_confidence,
            )

    def _auto_accumulate_samples(self) -> None:
        """Auto-save audio samples with quality-based rotation."""
        import io
        import soundfile as sf

        store = get_speaker_store()
        max_samples = settings.speaker_max_samples

        speaker_entries: dict[str, list[TranscriptEntry]] = {}
        for entry in self.entries:
            if entry.speaker_id.startswith("cluster_") or entry.speaker_id.startswith("guest_") or entry.speaker_id == "unknown":
                continue
            if entry.speaker_confidence >= 0.60:
                speaker_entries.setdefault(entry.speaker_id, []).append(entry)

        total_saved = 0
        for speaker_id, entries in speaker_entries.items():
            profile = store.get_speaker(speaker_id)
            if profile is None:
                continue

            candidates: list[dict] = []
            existing_count = len(store.get_sample_paths(speaker_id))

            for entry in entries:
                audio = self._entry_audio.get(entry.id)
                if audio is None:
                    continue
                duration = len(audio) / 16000
                if duration < 1.5:
                    continue

                emb = self._entry_embeddings.get(entry.id)
                quality = compute_sample_quality(
                    audio, duration, entry.speaker_confidence,
                    emb, profile.embedding,
                )

                if quality < settings.speaker_sample_min_quality:
                    continue

                try:
                    buf = io.BytesIO()
                    sf.write(buf, audio, 16000, subtype="PCM_16", format="WAV")
                    filename = f"sample_{existing_count + len(candidates):02d}_s.wav"
                    candidates.append({
                        "audio_data": buf.getvalue(),
                        "filename": filename,
                        "quality": quality,
                        "duration": duration,
                        "confidence": entry.speaker_confidence,
                        "session_id": self.session_id,
                    })
                except Exception:
                    logger.warning("Failed to encode sample for %s", speaker_id,
                                   exc_info=True)

            if not candidates:
                continue

            candidates.sort(key=lambda x: x["quality"], reverse=True)
            candidates = candidates[:5]

            if settings.speaker_sample_rotation_enabled:
                saved = store.rotate_samples(speaker_id, candidates, max_samples)
            else:
                existing = store.get_sample_paths(speaker_id)
                if len(existing) >= max_samples:
                    continue
                saved = 0
                for c in candidates:
                    if len(existing) + saved >= max_samples:
                        break
                    store.save_sample_with_metadata(
                        speaker_id, c["audio_data"], c["filename"],
                        c["quality"], c["duration"], c["confidence"],
                        c["session_id"],
                    )
                    saved += 1

            if saved > 0:
                total_saved += saved
                logger.info(
                    "Auto-accumulated %d samples for speaker %s (%s), quality=[%.3f..%.3f]",
                    saved, profile.name, speaker_id,
                    candidates[-1]["quality"], candidates[0]["quality"],
                )

        if total_saved > 0:
            logger.info("Auto-accumulated %d total speaker samples this session", total_saved)

    def _trim_trailing_silence(self) -> None:
        """Trim trailing silence from audio and remove corresponding screenshots.

        If the gap between the last transcript entry and the end of the
        recording is >= 5 minutes, the user likely forgot to press stop.
        Trim the WAV to last_entry.timestamp_end + 10s and delete
        screenshots beyond that point.
        """
        import json
        import soundfile as sf

        SILENCE_THRESHOLD_S = 300  # 5 minutes
        TRIM_BUFFER_S = 10  # keep 10s after last entry

        if not self.entries:
            return

        last_entry = max(self.entries, key=lambda e: e.timestamp_end)
        trim_point = last_entry.timestamp_end + TRIM_BUFFER_S

        session_dir = settings.sessions_dir / self.session_id
        wav_path = session_dir / "recording.wav"
        ogg_path = session_dir / "recording.ogg"

        # Determine recording duration from audio file
        audio_path = wav_path if wav_path.exists() else (ogg_path if ogg_path.exists() else None)
        if audio_path is None:
            return

        try:
            info = sf.info(str(audio_path))
            total_duration = info.duration
        except Exception:
            logger.warning("Failed to read audio info for trimming", exc_info=True)
            return

        gap = total_duration - last_entry.timestamp_end
        if gap < SILENCE_THRESHOLD_S:
            return

        logger.info(
            "Trailing silence detected: %.1fs gap (last entry at %.1fs, recording %.1fs). Trimming to %.1fs",
            gap, last_entry.timestamp_end, total_duration, trim_point,
        )

        # --- Trim WAV ---
        if wav_path.exists():
            try:
                data, sr = sf.read(str(wav_path), dtype="float32")
                keep_samples = min(int(trim_point * sr), len(data))
                trimmed = data[:keep_samples]
                sf.write(str(wav_path), trimmed, sr, subtype="PCM_16")
                logger.info(
                    "WAV trimmed: %.1fs -> %.1fs (saved %.1f MB)",
                    total_duration, keep_samples / sr,
                    (total_duration - keep_samples / sr) * sr * 2 / (1024 * 1024),
                )
            except Exception:
                logger.exception("Failed to trim WAV")

        # --- Trim screenshots ---
        screenshots_dir = session_dir / "screenshots"
        if screenshots_dir.exists():
            deleted = 0
            kept = []
            for f in sorted(screenshots_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg"):
                    continue
                ts_str = f.stem.replace("cap_", "")
                try:
                    relative_seconds = float(ts_str)
                except ValueError:
                    continue
                if relative_seconds > trim_point:
                    f.unlink()
                    deleted += 1
                else:
                    kept.append({
                        "filename": f.name,
                        "relative_seconds": relative_seconds,
                        "size_bytes": f.stat().st_size,
                    })
            if deleted > 0:
                logger.info("Deleted %d screenshots beyond trim point %.1fs", deleted, trim_point)
                # Rewrite screenshots.json
                manifest_path = session_dir / "screenshots.json"
                if kept:
                    text = json.dumps(kept, ensure_ascii=False, indent=2)
                    manifest_path.write_text(text, encoding="utf-8")
                elif manifest_path.exists():
                    manifest_path.unlink()

    def _save_audio(self) -> None:
        """Concatenate recorded audio chunks and save as WAV.

        Mic and loopback audio are stored in separate lists, then mixed
        (summed) here to avoid the interleaving bug.  Uses raw (pre-resample)
        mic audio when available.  Saves as PCM_16.
        """
        import soundfile as sf

        try:
            session_dir = settings.sessions_dir / self.session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            wav_path = session_dir / "recording.wav"

            # Build mic audio
            if self._recorded_audio_raw:
                raw = np.concatenate(self._recorded_audio_raw)
                source_rate = self._audio._raw_sample_rate
                if source_rate != 16000:
                    from math import gcd
                    from scipy.signal import resample_poly
                    g = gcd(16000, source_rate)
                    mic_audio = resample_poly(raw, 16000 // g, source_rate // g).astype(np.float32)
                else:
                    mic_audio = raw
                logger.info("Mic audio: bulk-resampled %dHz→16kHz (%d samples)", source_rate, len(mic_audio))
            elif self._recorded_audio:
                mic_audio = np.concatenate(self._recorded_audio)
            else:
                return

            # Mix in loopback audio if available
            if self._recorded_loopback:
                loopback_audio = np.concatenate(self._recorded_loopback)
                # Align lengths: pad shorter to match longer
                mic_len = len(mic_audio)
                lb_len = len(loopback_audio)
                if mic_len > lb_len:
                    loopback_audio = np.pad(loopback_audio, (0, mic_len - lb_len))
                elif lb_len > mic_len:
                    mic_audio = np.pad(mic_audio, (0, lb_len - mic_len))
                audio = mic_audio + loopback_audio
                logger.info("Mixed mic (%d) + loopback (%d) samples", mic_len, lb_len)
            else:
                audio = mic_audio

            # Normalize to [-1, 1] range for PCM_16
            peak = float(np.max(np.abs(audio)))
            if peak > 1.0:
                audio = audio / peak

            sf.write(str(wav_path), audio, 16000, subtype="PCM_16")
            duration = len(audio) / 16000
            logger.info(
                "Audio saved: %s (%.1fs, %.1f MB, PCM_16)",
                wav_path, duration, wav_path.stat().st_size / (1024 * 1024),
            )
        except Exception:
            logger.exception("Failed to save audio recording")
        finally:
            self._recorded_audio.clear()
            self._recorded_audio_raw.clear()
            self._recorded_loopback.clear()

    def _save_speaker_samples(self, store, speaker_id: str,
                               source_entry: TranscriptEntry,
                               cluster_id: str | None) -> None:
        """Save WAV audio samples from entry audio to the speaker profile."""
        import io
        import soundfile as sf

        candidates = [source_entry]
        if cluster_id:
            for other in self.entries:
                if other.id == source_entry.id:
                    continue
                if other.cluster_id == cluster_id:
                    candidates.append(other)

        saved = 0
        existing_count = len(store.get_sample_paths(speaker_id))
        logger.info("_save_speaker_samples: speaker=%s, candidates=%d, existing=%d, entry_audio_keys=%d",
                     speaker_id, len(candidates), existing_count, len(self._entry_audio))
        for entry in candidates:
            if saved >= 5:
                break
            audio = self._entry_audio.get(entry.id)
            if audio is None:
                logger.debug("No audio found for entry %s", entry.id)
                continue
            duration = len(audio) / 16000
            if duration < 1.5:
                continue
            try:
                buf = io.BytesIO()
                sf.write(buf, audio, 16000, subtype="PCM_16", format="WAV")
                filename = f"sample_{existing_count + saved:02d}.wav"
                store.save_sample(speaker_id, buf.getvalue(), filename)
                saved += 1
            except Exception:
                logger.warning("Failed to save audio sample for %s", speaker_id,
                               exc_info=True)
        if saved > 0:
            logger.info("Saved %d audio samples for speaker %s", saved, speaker_id)

    def register_speaker_from_entry(self, entry_index: int, name: str) -> dict:
        """Register a speaker using the embedding from a transcript entry."""
        if entry_index < 0 or entry_index >= len(self.entries):
            raise ValueError(f"Invalid entry index: {entry_index}")

        entry = self.entries[entry_index]
        embedding = self._entry_embeddings.get(entry.id)
        if embedding is None:
            raise ValueError(f"No embedding available for entry {entry_index}")

        store = get_speaker_store()
        profile = store.create_speaker(name.strip())

        # Collect high-quality embeddings from same cluster for better profile
        source_cluster_id = entry.cluster_id
        quality_embeddings = [embedding]
        for other in self.entries:
            if other.id == entry.id:
                continue
            if source_cluster_id and other.cluster_id == source_cluster_id:
                other_emb = self._entry_embeddings.get(other.id)
                if other_emb is None:
                    continue
                duration = other.timestamp_end - other.timestamp_start
                sim = float(np.dot(other_emb, embedding))
                if duration >= 2.0 and sim >= 0.5:
                    quality_embeddings.append(other_emb)

        # Outlier removal: drop embeddings far from mean
        if len(quality_embeddings) >= 3:
            avg = np.mean(quality_embeddings, axis=0)
            avg /= np.linalg.norm(avg)
            sims = [float(np.dot(e, avg)) for e in quality_embeddings]
            median_sim = float(np.median(sims))
            filtered = [e for e, s in zip(quality_embeddings, sims) if s >= median_sim - 0.15]
            if filtered:
                quality_embeddings = filtered

        avg_embedding = np.mean(quality_embeddings, axis=0)
        norm = np.linalg.norm(avg_embedding)
        if norm > 0:
            avg_embedding = avg_embedding / norm

        store.save_embedding(profile.speaker_id, avg_embedding)
        store.save_sample_embeddings(profile.speaker_id, quality_embeddings)

        # Save WAV audio samples for the speaker profile
        self._save_speaker_samples(store, profile.speaker_id, entry, source_cluster_id)

        entry.speaker_name = name.strip()
        entry.speaker_id = profile.speaker_id
        threshold = settings.speaker_similarity_threshold
        relabeled = 0
        total_with_emb = 0
        for i, other in enumerate(self.entries):
            if other.id == entry.id:
                continue
            if source_cluster_id and other.cluster_id == source_cluster_id:
                other.speaker_name = name.strip()
                other.speaker_id = profile.speaker_id
                other.cluster_id = None
                relabeled += 1
                continue
            other_emb = self._entry_embeddings.get(other.id)
            if other_emb is None:
                continue
            total_with_emb += 1
            score = float(np.dot(embedding, other_emb))
            if score >= threshold:
                other.speaker_name = name.strip()
                other.speaker_id = profile.speaker_id
                other.cluster_id = None
                relabeled += 1
                logger.debug("  Entry #%d: score=%.3f -> relabeled", i, score)
            else:
                logger.debug("  Entry #%d: score=%.3f (below %.2f)", i, score, threshold)

        if source_cluster_id:
            self._cluster_manager.merge_to_speaker(source_cluster_id, profile.speaker_id)
        entry.cluster_id = None

        logger.info(
            "Registered speaker '%s' from entry #%d: relabeled %d entries (threshold=%.2f)",
            name, entry_index, relabeled, threshold,
        )
        return profile.to_dict()

    def _start_device_watcher(self) -> None:
        """Start event-driven device watcher, falling back to polling."""
        from backend.core.device_watcher import DeviceWatcher

        if self._device_watcher is None:
            self._device_watcher = DeviceWatcher(asyncio.get_event_loop())

        self._device_watcher.start(callback=self._on_device_changed)

        if not self._device_watcher.is_event_driven:
            logger.info("Falling back to polling device monitor")
            self._device_monitor_task = asyncio.create_task(self._monitor_devices())

    def _stop_device_watcher(self) -> None:
        """Stop device watcher and polling fallback."""
        if self._device_watcher:
            self._device_watcher.stop()
        if self._device_monitor_task:
            self._device_monitor_task.cancel()
            self._device_monitor_task = None

    async def _on_device_changed(self, event) -> None:
        """Event-driven handler: called by DeviceWatcher on device change."""
        if self.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED):
            return

        from backend.core.audio_capture import get_default_microphone, get_default_loopback

        try:
            if event.event_type == "removed" or event.event_type == "added":
                # Device list changed — recreate PyAudio to refresh indices
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._audio._recreate_pyaudio)

            new_mic = get_default_microphone()
            new_lb = get_default_loopback()

            # Switch mic if default changed
            if new_mic and new_mic.index != self._audio.current_mic_index:
                logger.info(
                    "Device event → mic switch: %s -> %s",
                    self._audio.current_mic_name, new_mic.name,
                )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._audio.switch_mic, new_mic.index)

            # Switch loopback if default output changed
            if new_lb and new_lb.index != self._audio.current_loopback_index:
                logger.info(
                    "Device event → loopback switch: %s -> %s",
                    self._audio.current_loopback_name, new_lb.name,
                )
                if not self._has_loopback:
                    self._loopback_buffer.load_model()
                    self._loopback_buffer.start_session()
                    self._has_loopback = True
                    self._pipeline.configure(
                        self.session_id, self.session_name,
                        self.started_at, True,
                    )
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._audio.switch_loopback, new_lb.index)
            elif new_lb is None and self._audio.current_loopback_index is not None:
                logger.info("Device event → loopback gone, closing")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._audio.switch_loopback, None)

        except Exception:
            logger.warning("Device change handler failed", exc_info=True)

    async def _monitor_devices(self) -> None:
        """Background task: polling fallback when COM is unavailable."""
        from backend.core.audio_capture import get_default_microphone, get_default_loopback

        POLL_INTERVAL = 3.0
        logger.info("Device monitor started (poll every %.0fs)", POLL_INTERVAL)

        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                if self.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED):
                    break

                try:
                    new_mic = get_default_microphone()
                    new_lb = get_default_loopback()

                    # Switch mic if default changed
                    if new_mic and new_mic.index != self._audio.current_mic_index:
                        logger.info(
                            "Default mic changed: %s -> %s",
                            self._audio.current_mic_name, new_mic.name,
                        )
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, self._audio.switch_mic, new_mic.index
                        )

                    # Switch loopback if default output changed
                    if new_lb and new_lb.index != self._audio.current_loopback_index:
                        logger.info(
                            "Default loopback changed: %s -> %s",
                            self._audio.current_loopback_name, new_lb.name,
                        )
                        if not self._has_loopback:
                            self._loopback_buffer.load_model()
                            self._loopback_buffer.start_session()
                            self._has_loopback = True
                            self._pipeline.configure(
                                self.session_id, self.session_name,
                                self.started_at, True,
                            )
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, self._audio.switch_loopback, new_lb.index
                        )
                    elif new_lb is None and self._audio.current_loopback_index is not None:
                        logger.info("Default loopback gone, closing loopback stream")
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, self._audio.switch_loopback, None
                        )

                except Exception:
                    logger.warning("Device monitor check failed", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Device monitor stopped")
            raise


# Singleton session instance
_session = TranscriptionSession()


def get_session() -> TranscriptionSession:
    return _session
