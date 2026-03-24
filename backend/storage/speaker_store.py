"""Speaker profile and embedding persistence."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.config import settings

logger = logging.getLogger(__name__)

# Embedding model identifier — bump this when switching models
EMBEDDING_MODEL_ID = "wespeaker-resnet34-lm-256"


class SpeakerProfile:
    def __init__(self, speaker_id: str, name: str, created_at: str,
                 embedding: np.ndarray | None = None,
                 accepted_threshold: float | None = None):
        self.speaker_id = speaker_id
        self.name = name
        self.created_at = created_at
        self.embedding = embedding
        self.accepted_threshold = accepted_threshold

    def to_dict(self, sample_count: int = 0) -> dict:
        return {
            "id": self.speaker_id,
            "speaker_id": self.speaker_id,  # Keep for backward compatibility
            "name": self.name,
            "created_at": self.created_at,
            "sample_count": sample_count,
            "has_embedding": self.embedding is not None,
        }


class SpeakerStore:
    """Manages speaker profiles and embeddings on disk.

    Layout per speaker:
      data/speakers/{speaker_id}/
        profile.json          — {speaker_id, name, created_at, session_count, last_updated}
        embedding.npz         — averaged embedding vector
        sample_metadata.json  — quality metadata per sample
        samples/              — original audio files
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or settings.speakers_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SpeakerProfile] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all speaker profiles from disk into cache."""
        self._cache.clear()
        if not self.base_dir.exists():
            return

        for speaker_dir in self.base_dir.iterdir():
            if not speaker_dir.is_dir():
                continue
            profile_path = speaker_dir / "profile.json"
            if not profile_path.exists():
                continue
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
                embedding = None
                emb_path = speaker_dir / "embedding.npz"
                if emb_path.exists():
                    npz = np.load(str(emb_path))
                    loaded_emb = npz["embedding"]
                    stored_model = data.get("embedding_model")
                    from backend.core.diarizer import EMBEDDING_DIM
                    if loaded_emb.shape[0] != EMBEDDING_DIM:
                        logger.warning(
                            "Speaker %s has %d-dim embedding (expected %d), "
                            "needs recomputation",
                            speaker_dir.name, loaded_emb.shape[0], EMBEDDING_DIM,
                        )
                    elif stored_model and stored_model != EMBEDDING_MODEL_ID:
                        logger.warning(
                            "Speaker %s embedding model mismatch (%s != %s), "
                            "needs recomputation",
                            speaker_dir.name, stored_model, EMBEDDING_MODEL_ID,
                        )
                    else:
                        embedding = loaded_emb

                profile = SpeakerProfile(
                    speaker_id=data["speaker_id"],
                    name=data["name"],
                    created_at=data["created_at"],
                    embedding=embedding,
                    accepted_threshold=data.get("accepted_threshold"),
                )
                self._cache[profile.speaker_id] = profile
            except Exception:
                logger.exception("Failed to load speaker %s", speaker_dir.name)

        logger.info("Loaded %d speaker profiles", len(self._cache))

    def list_speakers(self) -> list[dict]:
        """Return all speaker profiles as dicts."""
        result = []
        for p in self._cache.values():
            sample_count = len(self.get_sample_paths(p.speaker_id))
            result.append(p.to_dict(sample_count=sample_count))
        return result

    def get_speaker(self, speaker_id: str) -> SpeakerProfile | None:
        return self._cache.get(speaker_id)

    def create_speaker(self, name: str) -> SpeakerProfile:
        """Create a new speaker profile (without embedding yet)."""
        speaker_id = str(uuid.uuid4())[:8]
        created_at = datetime.now().isoformat()

        speaker_dir = self.base_dir / speaker_id
        speaker_dir.mkdir(parents=True, exist_ok=True)
        (speaker_dir / "samples").mkdir(exist_ok=True)

        profile_data = {
            "speaker_id": speaker_id,
            "name": name,
            "created_at": created_at,
        }
        (speaker_dir / "profile.json").write_text(
            json.dumps(profile_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        profile = SpeakerProfile(
            speaker_id=speaker_id,
            name=name,
            created_at=created_at,
        )
        self._cache[speaker_id] = profile
        logger.info("Created speaker: %s (%s)", name, speaker_id)
        return profile

    def save_embedding(self, speaker_id: str, embedding: np.ndarray) -> None:
        """Save the averaged embedding vector for a speaker."""
        profile = self._cache.get(speaker_id)
        if profile is None:
            raise ValueError(f"Speaker {speaker_id} not found")

        speaker_dir = self.base_dir / speaker_id
        np.savez(str(speaker_dir / "embedding.npz"), embedding=embedding)
        profile.embedding = embedding

        # Record model version in profile.json
        profile_path = speaker_dir / "profile.json"
        if profile_path.exists():
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            data["embedding_model"] = EMBEDDING_MODEL_ID
            profile_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        logger.info("Saved embedding for %s (model=%s)", profile.name, EMBEDDING_MODEL_ID)

    def set_accepted_threshold(self, speaker_id: str, threshold: float) -> None:
        """Set per-speaker accepted threshold (lowers match requirement after user confirmation)."""
        profile = self._cache.get(speaker_id)
        if profile is None:
            raise ValueError(f"Speaker {speaker_id} not found")

        # Floor at suggestion threshold
        threshold = max(threshold, settings.speaker_suggestion_threshold)
        profile.accepted_threshold = threshold

        speaker_dir = self.base_dir / speaker_id
        profile_path = speaker_dir / "profile.json"
        if profile_path.exists():
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            data["accepted_threshold"] = threshold
            profile_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        logger.info("Set accepted_threshold=%.3f for %s", threshold, profile.name)

    def save_sample_embeddings(self, speaker_id: str, embeddings: list[np.ndarray]) -> None:
        """Save per-sample embeddings for a speaker."""
        if speaker_id not in self._cache:
            raise ValueError(f"Speaker {speaker_id} not found")
        speaker_dir = self.base_dir / speaker_id
        stacked = np.stack(embeddings)
        np.savez(str(speaker_dir / "samples_embeddings.npz"), embeddings=stacked)
        logger.info("Saved %d sample embeddings for %s", len(embeddings), speaker_id)

    def update_embedding(
        self,
        speaker_id: str,
        embedding: np.ndarray,
        weight: float = 0.1,
        *,
        session_confidence: float | None = None,
        session_match_count: int | None = None,
    ) -> None:
        """Update a speaker's embedding with EMA or legacy weighted averaging.

        When session_confidence and session_match_count are provided, uses
        momentum-based EMA with session-count-aware learning rate.
        Otherwise falls back to simple linear interpolation (legacy).
        """
        profile = self._cache.get(speaker_id)
        if profile is None or profile.embedding is None:
            return

        if session_confidence is not None and session_match_count is not None:
            session_count = self.get_session_count(speaker_id)
            base_alpha = 1.0 - settings.speaker_embedding_momentum  # 0.1
            early_boost = max(1.0, 4.0 / (1.0 + session_count))
            confidence_factor = min(1.0, session_match_count / 10.0) * session_confidence
            alpha = min(0.40, base_alpha * early_boost * confidence_factor)
            alpha = max(0.02, alpha)
            logger.info(
                "EMA update for %s: session_count=%d, alpha=%.4f "
                "(base=%.2f, boost=%.2f, conf_factor=%.3f)",
                speaker_id, session_count, alpha,
                base_alpha, early_boost, confidence_factor,
            )
        else:
            alpha = weight

        new_emb = profile.embedding * (1 - alpha) + embedding * alpha
        norm = np.linalg.norm(new_emb)
        if norm > 0:
            new_emb = new_emb / norm
        self.save_embedding(speaker_id, new_emb)

    def save_sample(self, speaker_id: str, audio_data: bytes, filename: str) -> Path:
        """Save an audio sample file for a speaker."""
        profile = self._cache.get(speaker_id)
        if profile is None:
            raise ValueError(f"Speaker {speaker_id} not found")

        samples_dir = self.base_dir / speaker_id / "samples"
        samples_dir.mkdir(exist_ok=True)
        sample_path = samples_dir / filename
        sample_path.write_bytes(audio_data)
        return sample_path

    def save_sample_with_metadata(
        self,
        speaker_id: str,
        audio_data: bytes,
        filename: str,
        quality: float,
        duration: float,
        confidence: float,
        session_id: str,
    ) -> Path:
        """Save an audio sample with quality metadata for rotation."""
        path = self.save_sample(speaker_id, audio_data, filename)

        metadata = self.get_sample_metadata(speaker_id)
        metadata[filename] = {
            "quality": round(quality, 4),
            "duration": round(duration, 2),
            "confidence": round(confidence, 4),
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
        }
        self.save_sample_metadata(speaker_id, metadata)
        return path

    def get_sample_paths(self, speaker_id: str) -> list[Path]:
        """List all audio sample files for a speaker."""
        samples_dir = self.base_dir / speaker_id / "samples"
        if not samples_dir.exists():
            return []
        return sorted(samples_dir.glob("*.wav"))

    def get_sample_metadata(self, speaker_id: str) -> dict[str, dict]:
        """Load quality metadata for all samples."""
        meta_path = self.base_dir / speaker_id / "sample_metadata.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_sample_metadata(self, speaker_id: str, metadata: dict[str, dict]) -> None:
        """Save quality metadata for all samples."""
        meta_path = self.base_dir / speaker_id / "sample_metadata.json"
        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def rotate_samples(
        self,
        speaker_id: str,
        new_samples: list[dict],
        max_samples: int,
    ) -> int:
        """Replace lowest-quality existing samples with higher-quality new ones.

        Returns number of samples added/replaced.
        """
        existing_paths = self.get_sample_paths(speaker_id)
        metadata = self.get_sample_metadata(speaker_id)

        existing_scored: list[tuple[float, str, Path]] = []
        for path in existing_paths:
            fname = path.name
            meta = metadata.get(fname, {})
            q = meta.get("quality", 0.5)
            existing_scored.append((q, fname, path))
        existing_scored.sort(key=lambda x: x[0])

        new_sorted = sorted(new_samples, key=lambda x: x["quality"], reverse=True)

        replaced = 0
        for ns in new_sorted:
            if len(existing_scored) < max_samples:
                self.save_sample_with_metadata(
                    speaker_id, ns["audio_data"], ns["filename"],
                    ns["quality"], ns["duration"],
                    ns["confidence"], ns["session_id"],
                )
                existing_scored.append((ns["quality"], ns["filename"], None))
                existing_scored.sort(key=lambda x: x[0])
                replaced += 1
            elif existing_scored and ns["quality"] > existing_scored[0][0] + 0.05:
                worst_q, worst_fname, worst_path = existing_scored[0]
                if worst_path and worst_path.exists():
                    worst_path.unlink()
                if worst_fname in metadata:
                    del metadata[worst_fname]
                self.save_sample_with_metadata(
                    speaker_id, ns["audio_data"], ns["filename"],
                    ns["quality"], ns["duration"],
                    ns["confidence"], ns["session_id"],
                )
                existing_scored.pop(0)
                existing_scored.append((ns["quality"], ns["filename"], None))
                existing_scored.sort(key=lambda x: x[0])
                replaced += 1

        return replaced

    def get_session_count(self, speaker_id: str) -> int:
        """Get the number of sessions that have updated this speaker."""
        profile_path = self.base_dir / speaker_id / "profile.json"
        if not profile_path.exists():
            return 0
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            return data.get("session_count", 0)
        except Exception:
            return 0

    def increment_session_count(self, speaker_id: str) -> int:
        """Increment session_count and update last_updated in profile.json."""
        profile_path = self.base_dir / speaker_id / "profile.json"
        if not profile_path.exists():
            return 0
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        count = data.get("session_count", 0) + 1
        data["session_count"] = count
        data["last_updated"] = datetime.now().isoformat()
        profile_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return count

    def rename_speaker(self, speaker_id: str, new_name: str) -> SpeakerProfile | None:
        """Rename a speaker and persist to disk."""
        profile = self._cache.get(speaker_id)
        if profile is None:
            return None

        profile.name = new_name

        profile_path = self.base_dir / speaker_id / "profile.json"
        if profile_path.exists():
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            data["name"] = new_name
            data["last_updated"] = datetime.now().isoformat()
            profile_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        logger.info("Renamed speaker %s to '%s'", speaker_id, new_name)
        return profile

    def delete_speaker(self, speaker_id: str) -> bool:
        """Delete a speaker and all associated data."""
        if speaker_id not in self._cache:
            return False

        speaker_dir = self.base_dir / speaker_id
        if speaker_dir.exists():
            shutil.rmtree(speaker_dir)

        del self._cache[speaker_id]
        logger.info("Deleted speaker %s", speaker_id)
        return True

    def get_all_embeddings(self) -> list[tuple[str, str, np.ndarray, float | None]]:
        """Return (speaker_id, name, embedding, accepted_threshold) for all speakers with embeddings."""
        result = []
        for p in self._cache.values():
            if p.embedding is not None:
                result.append((p.speaker_id, p.name, p.embedding, p.accepted_threshold))
        return result


# Singleton
_store: SpeakerStore | None = None


def get_speaker_store() -> SpeakerStore:
    global _store
    if _store is None:
        _store = SpeakerStore()
    return _store
