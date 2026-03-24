"""Post-processing: filler removal + dictionary replacement + whitespace normalization."""

from __future__ import annotations

import re

from backend.storage.dictionary_store import get_dictionary_store

# ------------------------------------------------------------------ #
#  Constants                                                           #
# ------------------------------------------------------------------ #

# Unicode character class shorthands for regex patterns in dictionary rules
SHORTHANDS = {
    "{漢字}": "[\u4e00-\u9fff]",
    "{ひらがな}": "[\u3040-\u309f]",
    "{カタカナ}": "[\u30a0-\u30ff]",
    "{数字}": "[0-9\uff10-\uff19]",
    "{英字}": "[a-zA-Z\uff21-\uff3a\uff41-\uff5a]",
}

# Short hiragana-only patterns (<=this length) get automatic word boundaries
# to prevent partial matches inside longer hiragana words.
_HIRAGANA_AUTO_BOUNDARY_MAX_LEN = 4
_HIRAGANA_BOUNDARY_PREFIX = "(?<![ぁ-んー])"
_HIRAGANA_BOUNDARY_SUFFIX = "(?![ぁ-んー])"

# Default maximum length before sentence splitting kicks in
DEFAULT_MAX_SENTENCE_LEN = 60


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

def post_process(text: str) -> str:
    """Apply filler removal, dictionary replacement, and normalization."""
    store = get_dictionary_store()
    data = store.get_all()

    # Step 1: Filler removal
    if data.get("filler_removal_enabled", True):
        fillers = data.get("fillers", [])
        text = _remove_fillers(text, fillers)

    # Step 2: Dictionary replacement (longest match first)
    replacements = [r for r in data.get("replacements", []) if r.get("enabled", True)]
    replacements.sort(key=lambda r: len(r["from"]), reverse=True)
    text = _apply_replacements(text, replacements)

    # Step 3: Whitespace normalization
    text = _normalize_whitespace(text)

    return text


def split_sentences(text: str, max_len: int = DEFAULT_MAX_SENTENCE_LEN) -> list[str]:
    """Split text into sentences at natural boundaries when too long.

    Splitting priority:
      1. 。？！?! (sentence-ending punctuation)
      2. 、,  (clause boundaries, only if a piece exceeds max_len)

    Returns a list of non-empty strings. If the text is short enough,
    returns a single-element list unchanged.
    """
    if len(text) <= max_len:
        return [text]

    # Primary split: sentence-ending punctuation (keep delimiter at end of piece)
    pieces = re.split(r'(?<=[。？！?!])', text)
    pieces = [p for p in pieces if p.strip()]

    if len(pieces) <= 1:
        return _split_on_clause(text, max_len)

    # Secondary split: if any piece is still too long, split on clauses
    result = []
    for piece in pieces:
        if len(piece) > max_len:
            result.extend(_split_on_clause(piece, max_len))
        else:
            result.append(piece)

    return [p for p in result if p.strip()]


def test_post_process(text: str) -> dict:
    """Test post-processing on sample text, returning before/after."""
    return {
        "original": text,
        "processed": post_process(text),
    }


# ------------------------------------------------------------------ #
#  Step 1: Filler removal                                              #
# ------------------------------------------------------------------ #

def _remove_fillers(text: str, fillers: list[str]) -> str:
    """Remove filler words from text."""
    if not fillers:
        return text
    sorted_fillers = sorted(fillers, key=len, reverse=True)
    escaped = [re.escape(f) for f in sorted_fillers]
    pattern = r'(?:' + '|'.join(escaped) + r')[\s、,]*'
    return re.sub(pattern, '', text)


# ------------------------------------------------------------------ #
#  Step 2: Dictionary replacement                                      #
# ------------------------------------------------------------------ #

def _apply_replacements(text: str, replacements: list[dict]) -> str:
    """Apply dictionary replacement rules.

    For short hiragana-only patterns (<=4 chars, non-regex), automatically
    adds a lookbehind check to prevent matching inside longer hiragana words.
    e.g., "てい"->"邸" won't match inside "している" because "し" precedes it.
    """
    for rule in replacements:
        if rule.get("is_regex", False):
            text = _apply_regex_rule(text, rule)
        else:
            text = _apply_literal_rule(text, rule)
    return text


def _apply_regex_rule(text: str, rule: dict) -> str:
    """Apply a single regex-based replacement rule."""
    pattern = _expand_shorthands(rule["from"])
    flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE
    try:
        text = re.sub(pattern, rule["to"], text, flags=flags)
    except re.error:
        pass
    return text


def _apply_literal_rule(text: str, rule: dict) -> str:
    """Apply a single literal (non-regex) replacement rule."""
    from_text = rule["from"]
    escaped = re.escape(from_text)
    flags = 0 if rule.get("case_sensitive", False) else re.IGNORECASE

    if _is_all_hiragana(from_text) and len(from_text) <= _HIRAGANA_AUTO_BOUNDARY_MAX_LEN:
        pattern = f"{_HIRAGANA_BOUNDARY_PREFIX}{escaped}{_HIRAGANA_BOUNDARY_SUFFIX}"
    else:
        pattern = escaped

    return re.sub(pattern, rule["to"], text, flags=flags)


def _expand_shorthands(pattern: str) -> str:
    """Expand {漢字} etc. to actual Unicode ranges."""
    for key, value in SHORTHANDS.items():
        pattern = pattern.replace(key, value)
    return pattern


def _is_all_hiragana(text: str) -> bool:
    """Check if text consists only of hiragana (+ chōon mark ー)."""
    return bool(text) and all(
        '\u3040' <= ch <= '\u309f' or ch == 'ー' for ch in text
    )


# ------------------------------------------------------------------ #
#  Step 3: Whitespace normalization                                    #
# ------------------------------------------------------------------ #

def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace: collapse multiple spaces, strip edges."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ------------------------------------------------------------------ #
#  Sentence splitting helpers                                          #
# ------------------------------------------------------------------ #

def _split_on_clause(text: str, max_len: int) -> list[str]:
    """Split on 、or , when text exceeds max_len."""
    if len(text) <= max_len:
        return [text]

    parts = re.split(r'(?<=[、,])', text)
    parts = [p for p in parts if p.strip()]
    if len(parts) <= 1:
        return [text]

    merged: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) > max_len:
            merged.append(buf)
            buf = part
        else:
            buf += part
    if buf:
        merged.append(buf)

    return [p for p in merged if p.strip()]
