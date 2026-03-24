"""Correction-based dictionary learning engine.

Analyzes user corrections to extract recurring patterns and propose dictionary rules.
Inspired by Aqua Dictation's auto-learning system.
"""

from __future__ import annotations

import logging
from collections import Counter

from backend.storage.correction_store import get_correction_store
from backend.storage.dictionary_store import get_dictionary_store

logger = logging.getLogger(__name__)

MIN_OCCURRENCES = 2
MIN_CONFIDENCE = 0.6
MAX_PHRASE_LEN = 30
MIN_PHRASE_LEN = 1


def _char_type(ch: str) -> str:
    """Classify a character by type for tokenization."""
    cp = ord(ch)
    if 0x4E00 <= cp <= 0x9FFF:
        return "kanji"
    if 0x3040 <= cp <= 0x309F:
        return "hiragana"
    if 0x30A0 <= cp <= 0x30FF:
        return "katakana"
    if ch.isascii() and ch.isalpha():
        return "alpha"
    if ch.isdigit():
        return "digit"
    if ch.isspace():
        return "space"
    return "punct"


def _tokenize(text: str) -> list[str]:
    """Split text into tokens by character type boundaries.

    e.g., "ABCあいう漢字123" -> ["ABC", "あいう", "漢字", "123"]
    """
    if not text:
        return []
    tokens = []
    current = text[0]
    current_type = _char_type(text[0])
    for ch in text[1:]:
        ct = _char_type(ch)
        if ct == current_type and ct != "kanji":
            current += ch
        else:
            if current.strip():
                tokens.append(current)
            current = ch
            current_type = ct
    if current.strip():
        tokens.append(current)
    return tokens


def _extract_changes(original: str, corrected: str) -> list[tuple[str, str]]:
    """Extract word-level changes between original and corrected text.

    Returns list of (from_text, to_text) pairs.
    Uses simple token-level comparison approach.
    """
    orig_tokens = _tokenize(original)
    corr_tokens = _tokenize(corrected)

    if orig_tokens == corr_tokens:
        return []

    changes = []

    # Simple approach: find common prefix and suffix, extract diff in the middle
    # This handles the most common case: a single word/phrase correction
    prefix_len = 0
    for i in range(min(len(orig_tokens), len(corr_tokens))):
        if orig_tokens[i] == corr_tokens[i]:
            prefix_len = i + 1
        else:
            break

    suffix_len = 0
    for i in range(1, min(len(orig_tokens) - prefix_len, len(corr_tokens) - prefix_len) + 1):
        if orig_tokens[-i] == corr_tokens[-i]:
            suffix_len = i
        else:
            break

    orig_end = len(orig_tokens) - suffix_len if suffix_len else len(orig_tokens)
    corr_end = len(corr_tokens) - suffix_len if suffix_len else len(corr_tokens)

    orig_diff = orig_tokens[prefix_len:orig_end]
    corr_diff = corr_tokens[prefix_len:corr_end]

    if orig_diff or corr_diff:
        from_text = "".join(orig_diff)
        to_text = "".join(corr_diff)
        if (from_text or to_text) and from_text != to_text:
            changes.append((from_text, to_text))

    return changes


def analyze_corrections() -> list[dict]:
    """Analyze all text corrections and return dictionary rule candidates.

    Returns:
        List of candidate rules: {from_text, to_text, count, confidence, corrections}
    """
    store = get_correction_store()
    dict_store = get_dictionary_store()

    text_corrections = store.get_text_corrections()
    if not text_corrections:
        return []

    # Extract all changes
    change_counter: Counter[tuple[str, str]] = Counter()
    change_examples: dict[tuple[str, str], list[dict]] = {}

    for correction in text_corrections:
        original = correction.get("original", "")
        corrected = correction.get("corrected", "")
        changes = _extract_changes(original, corrected)

        for from_text, to_text in changes:
            if len(from_text) < MIN_PHRASE_LEN or len(from_text) > MAX_PHRASE_LEN:
                continue
            if len(to_text) > MAX_PHRASE_LEN:
                continue

            key = (from_text, to_text)
            change_counter[key] += 1
            change_examples.setdefault(key, []).append({
                "session_id": correction.get("session_id", ""),
                "timestamp": correction.get("timestamp", ""),
            })

    # Filter and score candidates
    existing_rules = {r["from"] for r in dict_store.get_replacements()}
    candidates = []

    for (from_text, to_text), count in change_counter.most_common():
        if count < MIN_OCCURRENCES:
            continue
        if from_text in existing_rules:
            continue

        # Confidence based on occurrence count
        confidence = min(1.0, count / 5.0)  # Max confidence at 5 occurrences
        if confidence < MIN_CONFIDENCE:
            continue

        candidates.append({
            "from_text": from_text,
            "to_text": to_text,
            "count": count,
            "confidence": round(confidence, 2),
            "examples": change_examples[(from_text, to_text)][:3],  # Max 3 examples
        })

    candidates.sort(key=lambda c: (-c["confidence"], -c["count"]))
    logger.info("Found %d dictionary rule candidates from %d corrections",
                len(candidates), len(text_corrections))
    return candidates


def auto_register_correction(original: str, corrected: str) -> list[dict]:
    """Auto-register word-level corrections to the dictionary.

    Called when the user edits a transcript entry. Extracts the changed
    word(s) and immediately adds them as dictionary replacement rules.

    Returns list of newly added rules.
    """
    changes = _extract_changes(original, corrected)
    if not changes:
        return []

    dict_store = get_dictionary_store()
    existing_rules = {r["from"]: r["to"] for r in dict_store.get_replacements()}
    added = []

    for from_text, to_text in changes:
        # Skip insertions/deletions (only handle replacements)
        if not from_text or not to_text:
            continue
        # Skip very short patterns (single char is too noisy)
        if len(from_text) < 2:
            continue
        if len(from_text) > MAX_PHRASE_LEN or len(to_text) > MAX_PHRASE_LEN:
            continue
        # Skip if identical mapping already exists
        if from_text in existing_rules:
            continue

        rule = dict_store.add_replacement(
            from_text=from_text,
            to_text=to_text,
            case_sensitive=False,
            enabled=True,
            is_regex=False,
            note="修正から自動学習",
            auto_learned=True,
        )
        added.append(rule)
        logger.info("Auto-registered: '%s' -> '%s'", from_text, to_text)

    return added


def accept_suggestion(from_text: str, to_text: str) -> dict:
    """Accept a learning suggestion and add it to the dictionary.

    Returns the created rule.
    """
    dict_store = get_dictionary_store()
    rule = dict_store.add_replacement(
        from_text=from_text,
        to_text=to_text,
        case_sensitive=False,
        enabled=True,
        is_regex=False,
        note="自動学習",
        auto_learned=True,
    )
    logger.info("Accepted suggestion: '%s' -> '%s'", from_text, to_text)
    return rule
