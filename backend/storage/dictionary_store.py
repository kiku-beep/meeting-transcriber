"""Dictionary rules persistence (JSON file)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY = {
    "version": 1,
    "replacements": [],
    "fillers": ["えーと", "あのー", "えー", "まあ", "そのー", "うーん", "なんか"],
    "filler_removal_enabled": True,
    "hallucination_phrases": [
        "お疲れ様です", "お疲れ様でした",
        "ありがとうございました", "ありがとうございます",
        "ご視聴ありがとうございました",
        "おやすみなさい", "おはようございます",
        "よろしくお願いします", "お願いします",
        "こんにちは", "こんばんは",
        "失礼します", "失礼しました",
        "すみません", "ごめんなさい", "ごめん",
    ],
    "hallucination_filter_enabled": True,
}


class DictionaryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.dictionary_path
        self._data: dict = {}
        self._mtime: float = 0.0
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                self._mtime = self.path.stat().st_mtime
                logger.info("Dictionary loaded: %d replacements, %d fillers",
                            len(self._data.get("replacements", [])),
                            len(self._data.get("fillers", [])))
                return
            except Exception:
                logger.exception("Failed to load dictionary, using defaults")
        self._data = DEFAULT_DICTIONARY.copy()
        self._data["fillers"] = list(DEFAULT_DICTIONARY["fillers"])
        self._data["replacements"] = list(DEFAULT_DICTIONARY["replacements"])
        self._save()

    def _check_external_change(self) -> None:
        """Reload if the file was modified externally (e.g. by Aqua Dictation)."""
        try:
            if self.path.exists():
                current_mtime = self.path.stat().st_mtime
                if current_mtime > self._mtime:
                    logger.info("Dictionary file changed externally, reloading")
                    self._load()
        except Exception:
            pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_suffix('.tmp')
        tmp_path.write_text(text, encoding='utf-8')
        os.replace(str(tmp_path), str(self.path))
        self._mtime = self.path.stat().st_mtime

    def reload(self) -> None:
        """Re-read dictionary from disk."""
        self._load()

    def get_all(self) -> dict:
        self._check_external_change()
        return self._data

    # --- Replacements ---

    def get_replacements(self) -> list[dict]:
        self._check_external_change()
        return self._data.get("replacements", [])

    def has_replacement(self, from_text: str) -> bool:
        for rule in self._data.get("replacements", []):
            if rule.get("from") == from_text:
                return True
        return False

    def add_replacement(self, from_text: str, to_text: str,
                        case_sensitive: bool = False, enabled: bool = True,
                        is_regex: bool = False, note: str = "",
                        auto_learned: bool = False, confidence: float = 1.0,
                        occurrence_count: int = 0) -> dict:
        if self.has_replacement(from_text):
            raise ValueError(f"「{from_text}」は既に辞書に登録されています")
        rule = {
            "from": from_text,
            "to": to_text,
            "case_sensitive": case_sensitive,
            "enabled": enabled,
            "is_regex": is_regex,
            "note": note,
            "auto_learned": auto_learned,
            "confidence": confidence,
            "occurrence_count": occurrence_count,
        }
        self._data.setdefault("replacements", []).append(rule)
        self._save()
        return rule

    def update_replacement(self, index: int, rule: dict) -> dict:
        replacements = self._data.get("replacements", [])
        if index < 0 or index >= len(replacements):
            raise IndexError(f"Replacement index {index} out of range")
        replacements[index].update(rule)
        self._save()
        return replacements[index]

    def delete_replacement(self, index: int) -> bool:
        replacements = self._data.get("replacements", [])
        if index < 0 or index >= len(replacements):
            return False
        replacements.pop(index)
        self._save()
        return True

    # --- Fillers ---

    def get_fillers(self) -> list[str]:
        return self._data.get("fillers", [])

    def set_fillers(self, fillers: list[str]) -> None:
        self._data["fillers"] = fillers
        self._save()

    def is_filler_removal_enabled(self) -> bool:
        return self._data.get("filler_removal_enabled", True)

    def set_filler_removal_enabled(self, enabled: bool) -> None:
        self._data["filler_removal_enabled"] = enabled
        self._save()

    # --- Hallucination phrases ---

    def get_hallucination_phrases(self) -> list[str]:
        return self._data.get("hallucination_phrases", [])

    def set_hallucination_phrases(self, phrases: list[str]) -> None:
        self._data["hallucination_phrases"] = phrases
        self._save()

    def is_hallucination_filter_enabled(self) -> bool:
        return self._data.get("hallucination_filter_enabled", True)

    def set_hallucination_filter_enabled(self, enabled: bool) -> None:
        self._data["hallucination_filter_enabled"] = enabled
        self._save()


_store: DictionaryStore | None = None


def get_dictionary_store() -> DictionaryStore:
    global _store
    if _store is None:
        _store = DictionaryStore()
    return _store
