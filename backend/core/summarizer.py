"""Gemini API integration for meeting summary generation."""

from __future__ import annotations

import asyncio
import logging
import re

from backend.config import settings

logger = logging.getLogger(__name__)

_PROMPT_HEADER = """\
以下は会議の文字起こしです。話者名とタイムスタンプ付きです。

{transcript}

上記の会議内容を以下のMarkdown形式で要約してください。
日本語で出力してください。内容がない項目は「特になし」と書いてください。

## タイトル
（会議内容を表す簡潔なタイトル。15文字以内。例: 「週次進捗報告」「新機能設計レビュー」）

"""

_PROMPT_BODY_SHORT = """\
## 概要
（2-3文の要約）

## 決定事項
- 決定1
- 決定2

## 次のアクション
- アクション1（担当者名）
- アクション2（担当者名）

## 主な議論ポイント
- ポイント1
  - 補足説明や詳細（具体的な数値、背景、議論の結論など）
- ポイント2
  - 補足説明や詳細
"""

_PROMPT_BODY_MEDIUM = """\
## 概要
（3-4文の要約。主要な議題と結論を含める）

## 決定事項
- 決定1
- 決定2

## 次のアクション
- アクション1（担当者名）
- アクション2（担当者名）

## 主な議論ポイント
- ポイント1
  - 具体的にどのような意見が出たか、背景や理由も含めて記述
  - 最終的にどう結論づけられたか
- ポイント2
  - 具体的にどのような意見が出たか、背景や理由も含めて記述
  - 最終的にどう結論づけられたか
"""

_PROMPT_BODY_LONG = """\
## 概要
（5-6文の要約。会議全体の流れ、主要な議題、重要な決定の背景を含める）

## 決定事項
- 決定1
- 決定2

## 次のアクション
- アクション1（担当者名）
- アクション2（担当者名）

## 主な議論ポイント
- ポイント1
  - 発言者名: 主張した内容
  - 反対意見や異なる視点があれば、その発言者名と内容
  - 結論: 最終的にどう決まったか、その理由
- ポイント2
  - 発言者名: 主張した内容
  - 反対意見や異なる視点があれば、その発言者名と内容
  - 結論: 最終的にどう決まったか、その理由
"""

# Tier thresholds (minutes)
_TIER_MEDIUM_MIN = 20
_TIER_LONG_MIN = 70

_PROMPT_BODIES = {
    "short": _PROMPT_BODY_SHORT,
    "medium": _PROMPT_BODY_MEDIUM,
    "long": _PROMPT_BODY_LONG,
}

# Keep backward compat for any external references
SUMMARY_PROMPT = _PROMPT_HEADER + _PROMPT_BODY_SHORT


def _get_meeting_tier(entries: list[dict]) -> str:
    """Determine summary detail tier based on meeting duration."""
    if not entries:
        return "short"
    max_ts = max(e.get("timestamp_start", 0) for e in entries)
    duration_min = max_ts / 60
    if duration_min >= _TIER_LONG_MIN:
        return "long"
    if duration_min >= _TIER_MEDIUM_MIN:
        return "medium"
    return "short"

# Gemini model catalog: pricing (per 1M tokens), speed, accuracy
GEMINI_MODELS: dict[str, dict] = {
    "gemini-3-flash-preview": {
        "label": "Gemini 3 Flash",
        "input": 0.15, "output": 0.60,
        "speed": "fast", "accuracy": "high",
    },
    "gemini-3-pro-preview": {
        "label": "Gemini 3 Pro",
        "input": 1.25, "output": 10.00,
        "speed": "slow", "accuracy": "very_high",
    },
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash",
        "input": 0.15, "output": 0.60,
        "speed": "fast", "accuracy": "high",
    },
    "gemini-2.5-flash-lite-preview": {
        "label": "Gemini 2.5 Flash Lite",
        "input": 0.04, "output": 0.16,
        "speed": "very_fast", "accuracy": "medium",
    },
    "gemini-2.5-pro": {
        "label": "Gemini 2.5 Pro",
        "input": 1.25, "output": 10.00,
        "speed": "slow", "accuracy": "very_high",
    },
    "gemini-2.0-flash": {
        "label": "Gemini 2.0 Flash",
        "input": 0.10, "output": 0.40,
        "speed": "fast", "accuracy": "medium",
    },
    "gemini-2.0-flash-lite": {
        "label": "Gemini 2.0 Flash Lite",
        "input": 0.025, "output": 0.10,
        "speed": "very_fast", "accuracy": "low",
    },
}

# Backward-compat alias
PRICING = {k: {"input": v["input"], "output": v["output"]} for k, v in GEMINI_MODELS.items()}


def extract_title(summary: str) -> str | None:
    """Extract the title from the generated summary markdown."""
    match = re.search(r"## タイトル\s*\n+(.+)", summary)
    if match:
        title = match.group(1).strip().strip("「」")
        if title and len(title) <= 30:
            return title
    return None


# Singleton client
_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    """Get or create a singleton Gemini API client."""
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY が設定されていません")
        from google import genai
        from google.genai.types import HttpOptions
        import httpx

        # Set timeout for long meetings (120 seconds)
        http_options = HttpOptions(
            clientArgs={"timeout": httpx.Timeout(120.0)}
        )
        _client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=http_options
        )
        logger.info("Gemini Client initialized (singleton, timeout=120s)")
    return _client


def reset_gemini_client() -> None:
    """Reset the singleton client (for testing or API key changes)."""
    global _client
    _client = None


async def generate_summary(entries: list[dict]) -> dict:
    """Generate a meeting summary from transcript entries using Gemini API.

    Args:
        entries: List of TranscriptEntry dicts with text, speaker_name, timestamp_start.

    Returns:
        dict with keys: summary, title, usage (token counts and cost)

    Raises:
        RuntimeError: If GEMINI_API_KEY is not configured.
        Exception: On API errors.
    """
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")

    # Format transcript for the prompt
    lines = []
    for e in entries:
        speaker = e.get("speaker_name", "Unknown")
        text = e.get("text", "")
        t = e.get("timestamp_start", 0)
        mins, secs = divmod(int(t), 60)
        lines.append(f"[{mins:02d}:{secs:02d}] {speaker}: {text}")

    transcript_text = "\n".join(lines)
    if not transcript_text.strip():
        raise RuntimeError("文字起こしが空です。要約を生成できません。")

    tier = _get_meeting_tier(entries)
    prompt = (_PROMPT_HEADER + _PROMPT_BODIES[tier]).format(transcript=transcript_text)

    logger.info("Generating summary with Gemini (%d entries, %d chars, tier=%s)",
                len(entries), len(transcript_text), tier)

    client = get_gemini_client()

    # Retry on transient errors (500, 503, etc.)
    max_retries = 3
    response = None
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
            )
            if attempt > 0:
                logger.info("Gemini API succeeded after %d retries", attempt)
            break
        except Exception as e:
            last_error = e
            err_str = str(e)
            # Retry on 500, 503, UNAVAILABLE, or overloaded
            is_retryable = (
                "500" in err_str or
                "503" in err_str or
                "UNAVAILABLE" in err_str or
                "overloaded" in err_str.lower() or
                "InternalServerError" in err_str
            )
            if is_retryable and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("Gemini API error (attempt %d/%d): %s, retrying in %ds...",
                               attempt + 1, max_retries, err_str[:100], wait)
                await asyncio.sleep(wait)
            else:
                logger.error("Gemini API error (attempt %d/%d): %s", attempt + 1, max_retries, err_str)
                raise

    if response is None:
        raise RuntimeError("Gemini API呼び出しに失敗しました")

    summary = response.text

    # Extract token usage
    usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        input_tokens = getattr(meta, "prompt_token_count", 0) or 0
        output_tokens = getattr(meta, "candidates_token_count", 0) or 0
        total_tokens = getattr(meta, "total_token_count", 0) or (input_tokens + output_tokens)

        # Calculate cost
        model = settings.gemini_model
        pricing = PRICING.get(model, PRICING.get("gemini-2.0-flash", {}))
        input_cost = input_tokens / 1_000_000 * pricing.get("input", 0)
        output_cost = output_tokens / 1_000_000 * pricing.get("output", 0)
        total_cost = input_cost + output_cost

        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "model": model,
            "cost_usd": round(total_cost, 6),
        }

    title = extract_title(summary)

    # Enhanced logging with cost information
    if usage:
        cost_jpy = usage.get("cost_usd", 0) * 150  # $1 = ¥150
        logger.info(
            "Summary generated: %d chars, title=%s | Model: %s | "
            "Tokens: %d input + %d output = %d total | "
            "Cost: $%.6f (¥%.2f)",
            len(summary), title, usage.get("model", "unknown"),
            usage.get("input_tokens", 0), usage.get("output_tokens", 0),
            usage.get("total_tokens", 0),
            usage.get("cost_usd", 0), cost_jpy
        )
    else:
        logger.info("Summary generated: %d chars, title=%s (no usage data)", len(summary), title)

    return {"summary": summary, "title": title, "usage": usage}
