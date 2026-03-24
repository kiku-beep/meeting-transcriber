"""Correction history store — logs user edits for dictionary auto-learning."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)


class CorrectionStore:
    """Stores text/speaker corrections made by users.

    Each correction is a record of (original_text, corrected_text, field, session_id, timestamp).
    These are analyzed by the learner to propose dictionary rules.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (settings.data_dir / "corrections.json")
        self._corrections: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._corrections = json.loads(self.path.read_text(encoding="utf-8"))
                logger.info("Loaded %d corrections", len(self._corrections))
                return
            except Exception:
                logger.exception("Failed to load corrections")
        self._corrections = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._corrections, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_suffix('.tmp')
        tmp_path.write_text(text, encoding='utf-8')
        os.replace(str(tmp_path), str(self.path))

    def add(self, original: str, corrected: str, field: str = "text",
            session_id: str = "", entry_id: str = "") -> dict:
        """Record a correction.

        Args:
            original: Original text before correction
            corrected: Text after user correction
            field: Which field was corrected ("text" or "speaker_name")
            session_id: Session where the correction was made
            entry_id: Entry ID that was corrected
        """
        if original == corrected:
            return {}
        record = {
            "original": original,
            "corrected": corrected,
            "field": field,
            "session_id": session_id,
            "entry_id": entry_id,
            "timestamp": datetime.now().isoformat(),
        }
        self._corrections.append(record)
        self._save()
        logger.info("Correction recorded: '%s' -> '%s' (%s)", original, corrected, field)
        return record

    def get_all(self) -> list[dict]:
        return self._corrections

    def get_text_corrections(self) -> list[dict]:
        """Get only text corrections (not speaker corrections)."""
        return [c for c in self._corrections if c.get("field") == "text"]

    def clear(self) -> None:
        self._corrections = []
        self._save()


_store: CorrectionStore | None = None


def get_correction_store() -> CorrectionStore:
    global _store
    if _store is None:
        _store = CorrectionStore()
    return _store
