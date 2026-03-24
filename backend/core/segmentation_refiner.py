"""Pass 2: Delayed speaker label refinement using pyannote/segmentation-3.0.

Runs as a background task during transcription sessions. Every N seconds,
processes the most recent audio window with the segmentation model to detect
speaker turns and overlapping speech, then derives cannot-link constraints
to correct speaker labels assigned by the online Pass 1 pipeline.

VRAM: ~400MB.  Inference: ~8ms per 10s chunk (GPU).  No additional deps.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
import torch

from backend.config import settings
from backend.models.schemas import TranscriptEntry

logger = logging.getLogger(__name__)

# segmentation-3.0 output: 10s input → 767 frames, 7 powerset classes
_CHUNK_DURATION = 10.0
_FRAMES_PER_CHUNK = 767


class SegmentationRefiner:
    """Background refinement of speaker labels using segmentation model."""

    def __init__(self):
        self._seg_model = None
        self._to_multilabel = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._last_processed_time: float = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._seg_model is not None

    def load_model(self) -> None:
        """Load pyannote/segmentation-3.0 model."""
        if self._seg_model is not None:
            return

        from pyannote.audio import Model
        from pyannote.audio.utils.powerset import Powerset

        hf_token = settings.hf_token or None

        logger.info("Loading pyannote/segmentation-3.0 model...")
        model = Model.from_pretrained(
            "pyannote/segmentation-3.0",
            token=hf_token,
        )
        model.to(self._device)
        model.eval()
        self._seg_model = model

        # Powerset → multi-label converter (3 speakers max, 2 simultaneous max)
        self._to_multilabel = Powerset(
            num_classes=3,
            max_set_size=2,
        ).to_multilabel

        logger.info("segmentation-3.0 loaded on %s", self._device)

    def unload_model(self) -> None:
        """Release model from GPU."""
        if self._seg_model is not None:
            del self._seg_model
            self._seg_model = None
            self._to_multilabel = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("segmentation-3.0 unloaded")

    def _run_segmentation(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Run segmentation on a 10-second audio chunk.

        Returns:
            multi-label output of shape (num_frames, 3) — activation per local speaker.
        """
        # Ensure exactly 10s of audio
        expected_samples = int(_CHUNK_DURATION * sample_rate)
        if len(audio) < expected_samples:
            audio = np.pad(audio, (0, expected_samples - len(audio)))
        elif len(audio) > expected_samples:
            audio = audio[:expected_samples]

        waveform = torch.from_numpy(audio).float().unsqueeze(0).unsqueeze(0)  # (1, 1, samples)
        waveform = waveform.to(self._device)

        with torch.no_grad():
            powerset_output = self._seg_model(waveform)  # (1, num_frames, 7)

        # Convert powerset → multi-label: (1, num_frames, 3)
        multilabel = self._to_multilabel(powerset_output)
        return multilabel[0].cpu().numpy()  # (num_frames, 3)

    def refine_labels(
        self,
        recorded_audio: list[np.ndarray],
        entries: list[TranscriptEntry],
        entry_embeddings: dict[str, np.ndarray],
        cluster_manager,
        new_entry_event: asyncio.Event,
        window_s: float | None = None,
    ) -> int:
        """Refine speaker labels for recent entries using segmentation.

        Returns the number of entries relabeled.
        """
        if not self.is_loaded or not entries or not recorded_audio:
            return 0

        if window_s is None:
            window_s = settings.segmentation_refine_window_s

        # Reconstruct continuous audio from recorded chunks
        all_audio = np.concatenate(recorded_audio)
        total_duration = len(all_audio) / settings.audio_sample_rate

        # Only process the most recent window
        window_start = max(0.0, total_duration - window_s)
        start_sample = int(window_start * settings.audio_sample_rate)
        window_audio = all_audio[start_sample:]

        if len(window_audio) < settings.audio_sample_rate:  # less than 1 second
            return 0

        # Find entries within this time window
        window_entries = [
            e for e in entries
            if e.timestamp_start >= window_start and e.cluster_id
            and e.cluster_id.startswith("cluster_")
        ]
        if len(window_entries) < 2:
            return 0

        # Process in 10-second chunks
        chunk_samples = int(_CHUNK_DURATION * settings.audio_sample_rate)
        num_chunks = max(1, len(window_audio) // chunk_samples)
        if len(window_audio) % chunk_samples > settings.audio_sample_rate:
            num_chunks += 1

        # Collect cannot-link constraints
        cannot_links: set[tuple[str, str]] = set()

        for chunk_idx in range(num_chunks):
            chunk_start_sample = chunk_idx * chunk_samples
            chunk_audio = window_audio[chunk_start_sample:chunk_start_sample + chunk_samples]
            chunk_start_time = window_start + chunk_idx * _CHUNK_DURATION
            chunk_end_time = chunk_start_time + _CHUNK_DURATION

            if len(chunk_audio) < settings.audio_sample_rate:
                continue

            # Run segmentation
            multilabel = self._run_segmentation(chunk_audio, settings.audio_sample_rate)
            num_frames = multilabel.shape[0]
            frame_duration = _CHUNK_DURATION / num_frames

            # Find entries in this chunk
            chunk_entries = [
                e for e in window_entries
                if e.timestamp_start < chunk_end_time and e.timestamp_end > chunk_start_time
            ]
            if len(chunk_entries) < 2:
                continue

            # Assign local speaker ID to each entry based on segmentation
            entry_local_speakers: dict[str, int] = {}
            for entry in chunk_entries:
                # Map entry time range to frames
                rel_start = max(0.0, entry.timestamp_start - chunk_start_time)
                rel_end = min(_CHUNK_DURATION, entry.timestamp_end - chunk_start_time)
                frame_start = max(0, int(rel_start / frame_duration))
                frame_end = min(num_frames, int(rel_end / frame_duration))

                if frame_end <= frame_start:
                    continue

                # Average activation across entry's frames
                segment_activations = multilabel[frame_start:frame_end]  # (N, 3)
                avg_activation = segment_activations.mean(axis=0)  # (3,)

                # Dominant local speaker (if any activation > 0.3)
                if avg_activation.max() > 0.3:
                    entry_local_speakers[entry.id] = int(np.argmax(avg_activation))

            # Derive cannot-link constraints:
            # entries in the same chunk assigned to different local speakers
            entry_ids = list(entry_local_speakers.keys())
            for i, eid_a in enumerate(entry_ids):
                for eid_b in entry_ids[i + 1:]:
                    if entry_local_speakers[eid_a] != entry_local_speakers[eid_b]:
                        pair = tuple(sorted([eid_a, eid_b]))
                        cannot_links.add(pair)

        if not cannot_links:
            return 0

        # Register cannot-link constraints at cluster level for future clustering
        entry_map_cl = {e.id: e for e in window_entries}
        for eid_a, eid_b in cannot_links:
            ea = entry_map_cl.get(eid_a)
            eb = entry_map_cl.get(eid_b)
            if (ea and eb and ea.cluster_id and eb.cluster_id
                    and ea.cluster_id != eb.cluster_id):
                cluster_manager.add_cannot_link(ea.cluster_id, eb.cluster_id)

        # Apply cannot-link constraints via constrained re-clustering
        relabeled = self._constrained_recluster(
            window_entries, entry_embeddings, cannot_links, cluster_manager
        )

        if relabeled > 0:
            new_entry_event.set()
            logger.info("Segmentation refinement: %d entries relabeled (from %d cannot-links)",
                        relabeled, len(cannot_links))

        return relabeled

    def _constrained_recluster(
        self,
        entries: list[TranscriptEntry],
        entry_embeddings: dict[str, np.ndarray],
        cannot_links: set[tuple[str, str]],
        cluster_manager,
    ) -> int:
        """Re-cluster entries respecting cannot-link constraints.

        Uses a greedy approach: for each entry pair that is currently in the
        same cluster but has a cannot-link constraint, split the less-similar
        entry to the next-best cluster.
        """
        relabeled = 0

        # Build entry lookup
        entry_map = {e.id: e for e in entries}

        # Check which cannot-link pairs share the same cluster
        violations = []
        for eid_a, eid_b in cannot_links:
            ea = entry_map.get(eid_a)
            eb = entry_map.get(eid_b)
            if not ea or not eb:
                continue
            if ea.cluster_id and ea.cluster_id == eb.cluster_id:
                violations.append((eid_a, eid_b))

        if not violations:
            return 0

        # For each violation, move the less-confident entry to the next-best cluster
        for eid_a, eid_b in violations:
            ea = entry_map[eid_a]
            eb = entry_map[eid_b]
            emb_a = entry_embeddings.get(eid_a)
            emb_b = entry_embeddings.get(eid_b)
            if emb_a is None or emb_b is None:
                continue

            # Which entry has lower confidence? Move that one.
            if ea.speaker_confidence <= eb.speaker_confidence:
                target_entry = ea
                target_emb = emb_a
                keep_entry = eb
            else:
                target_entry = eb
                target_emb = emb_b
                keep_entry = ea

            # Find the best alternative cluster (not the current one)
            current_cid = target_entry.cluster_id
            best_cid = None
            best_label = None
            best_score = -1.0

            for cluster in cluster_manager._clusters:
                if cluster.cluster_id == current_cid:
                    continue
                score = cluster.similarity(target_emb)
                if score > best_score:
                    best_score = score
                    best_cid = cluster.cluster_id
                    best_label = cluster.label

            if best_cid and best_label:
                cluster_manager.add_cannot_link(current_cid, best_cid)
                target_entry.cluster_id = best_cid
                target_entry.speaker_name = best_label
                target_entry.speaker_id = best_cid
                relabeled += 1

        return relabeled

    async def run(
        self,
        stop_event: asyncio.Event,
        recorded_audio: list[np.ndarray],
        entries: list[TranscriptEntry],
        entry_embeddings: dict[str, np.ndarray],
        cluster_manager,
        new_entry_event: asyncio.Event,
    ) -> None:
        """Background loop: periodically refine speaker labels."""
        interval = settings.segmentation_refine_interval_s
        logger.info("Segmentation refinement task started (interval=%ds)", interval)
        loop = asyncio.get_event_loop()

        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, do work

            if not entries:
                continue

            try:
                count = await loop.run_in_executor(
                    None,
                    self.refine_labels,
                    recorded_audio, entries, entry_embeddings,
                    cluster_manager, new_entry_event,
                )
                if count > 0:
                    logger.info("Refinement pass: %d entries updated", count)
            except Exception:
                logger.exception("Segmentation refinement failed")

        logger.info("Segmentation refinement task stopped")
