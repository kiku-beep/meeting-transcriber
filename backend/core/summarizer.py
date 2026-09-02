"""Gemini API integration for meeting summary generation."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

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

SUMMARY_ENGINES: dict[str, dict] = {
    "auto": {
        "label": "Claude Code → Codex CLI → Gemini",
        "description": "Claude Code、Codex CLIの順に試し、失敗時はGeminiへフォールバックします。",
        "billing": "auto",
    },
    "gemini": {
        "label": "Gemini API",
        "description": "Gemini APIキーを使って従量課金で要約します。",
        "billing": "api",
    },
    "claude-code": {
        "label": "Claude Code",
        "description": "ローカルのClaude Code CLIを使ってClaudeサブスク枠で要約します。",
        "billing": "claude-subscription",
    },
}

_CLAUDE_CODE_API_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)

_CODEX_API_ENV_VARS = (
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
)

TextProvider = tuple[str, Callable[[str], Awaitable[dict]]]

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


def _format_transcript(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        speaker = e.get("speaker_name", "Unknown")
        text = e.get("text", "")
        t = e.get("timestamp_start", 0)
        mins, secs = divmod(int(t), 60)
        lines.append(f"[{mins:02d}:{secs:02d}] {speaker}: {text}")
    return "\n".join(lines)


def _build_summary_prompt(entries: list[dict]) -> tuple[str, str, str]:
    transcript_text = _format_transcript(entries)
    if not transcript_text.strip():
        raise RuntimeError("文字起こしが空です。要約を生成できません。")

    tier = _get_meeting_tier(entries)
    prompt = (_PROMPT_HEADER + _PROMPT_BODIES[tier]).format(transcript=transcript_text)
    return prompt, transcript_text, tier


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip().lower() not in ("", "0", "false", "no", "off")


def _ensure_claude_code_subscription_mode() -> str:
    configured = [name for name in _CLAUDE_CODE_API_ENV_VARS if _truthy_env(name)]
    if configured:
        joined = ", ".join(configured)
        raise RuntimeError(
            f"{joined} が設定されています。Claude CodeがAPI/外部プロバイダ課金に流れる恐れがあるため、"
            "Claude Code要約を停止しました。サブスク枠で使う場合は該当環境変数を外してから再実行してください。"
        )

    resolved_command = shutil.which(settings.claude_code_command)
    if not resolved_command:
        raise RuntimeError(
            f"Claude Code CLI `{settings.claude_code_command}` が見つかりません。"
            "`claude --version` が通る状態にしてから再実行してください。"
        )
    return resolved_command


def _format_fallback_error(error: Exception, max_length: int = 300) -> str:
    """Return a compact, single-line error suitable for UI diagnostics."""
    detail = re.sub(r"\s+", " ", str(error)).strip() or type(error).__name__
    if len(detail) <= max_length:
        return detail
    return detail[: max_length - 3].rstrip() + "..."


async def _communicate_with_timeout(
    process,
    prompt: str | None,
    *,
    provider_label: str,
    timeout_s: float,
) -> tuple[bytes, bytes]:
    try:
        return await asyncio.wait_for(
            process.communicate(
                prompt.encode("utf-8") if prompt is not None else None
            ),
            timeout=timeout_s,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"{provider_label}がタイムアウトしました。")


async def generate_summary_with_claude_code(entries: list[dict]) -> dict:
    """Generate a meeting summary through the local Claude Code CLI."""
    claude_code_command = _ensure_claude_code_subscription_mode()
    prompt, transcript_text, tier = _build_summary_prompt(entries)

    cmd = [
        claude_code_command,
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "text",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--safe-mode",
        "--no-session-persistence",
    ]
    if settings.claude_code_model:
        cmd.extend(["--model", settings.claude_code_model])

    logger.info(
        "Generating summary with Claude Code CLI (%d entries, %d chars, tier=%s)",
        len(entries), len(transcript_text), tier,
    )

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        process,
        prompt,
        provider_label="Claude Code",
        timeout_s=settings.claude_code_timeout_s,
    )

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()

    if process.returncode != 0:
        detail = stderr_text or stdout_text or f"exit code {process.returncode}"
        raise RuntimeError(f"Claude Code CLI呼び出しに失敗しました: {detail}")

    if not stdout_text:
        detail = stderr_text or "出力が空でした"
        raise RuntimeError(f"Claude Code CLIから要約を取得できませんでした: {detail}")

    title = extract_title(stdout_text)
    usage = {
        "model": "claude-code",
        "billing": SUMMARY_ENGINES["claude-code"]["billing"],
    }
    logger.info("Summary generated with Claude Code: %d chars, title=%s", len(stdout_text), title)
    return {"summary": stdout_text, "title": title, "usage": usage}

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
    """Generate a meeting summary from transcript entries using the configured engine."""
    engine = settings.summary_engine
    if engine == "auto":
        return await generate_summary_auto(entries)
    if engine == "claude-code":
        return await generate_summary_with_claude_code(entries)
    if engine != "gemini":
        raise RuntimeError(f"不明な要約エンジンです: {engine}")
    return await generate_summary_with_gemini(entries)


async def _run_provider_chain(
    prompt: str,
    providers: tuple[TextProvider, ...],
) -> dict:
    failed_ids: list[str] = []
    failure_details: dict[str, str] = {}
    last_error: Exception | None = None

    for provider_id, provider in providers:
        try:
            result = await provider(prompt)
        except Exception as error:
            last_error = error
            detail = _format_fallback_error(error)
            failed_ids.append(provider_id)
            failure_details[provider_id] = detail
            logger.warning("%s failed; trying next provider: %s", provider_id, detail)
            continue

        if failed_ids:
            usage = result.setdefault("usage", {})
            usage["fallback_from"] = failed_ids[-1]
            usage["fallback_detail"] = failure_details[failed_ids[-1]]
            usage["fallback_chain"] = list(failed_ids)
            usage["fallback_details"] = dict(failure_details)
            usage["fallback_reason"] = "provider-error"
        return result

    diagnostics = " / ".join(
        f"{provider_id}: {failure_details[provider_id]}"
        for provider_id in failed_ids
    )
    raise RuntimeError(
        f"すべてのAIプロバイダで処理に失敗しました。 {diagnostics}"
    ) from last_error


def _providers_for_engine(*, include_codex: bool) -> tuple[TextProvider, ...]:
    engine = settings.summary_engine
    if engine == "claude-code":
        return (("claude-code", _generate_text_with_claude_code),)
    if engine == "gemini":
        return (("gemini", _generate_text_with_gemini),)
    if engine != "auto":
        raise RuntimeError(f"不明な要約エンジンです: {engine}")

    providers: list[TextProvider] = [
        ("claude-code", _generate_text_with_claude_code),
    ]
    if include_codex:
        providers.append(("codex-cli", _generate_text_with_codex_cli))
    providers.append(("gemini", _generate_text_with_gemini))
    return tuple(providers)


async def generate_summary_text(prompt: str) -> dict:
    return await _run_provider_chain(
        prompt,
        _providers_for_engine(include_codex=True),
    )


async def generate_question_text(prompt: str) -> dict:
    return await _run_provider_chain(
        prompt,
        _providers_for_engine(include_codex=False),
    )


async def generate_text_with_summary_engine(prompt: str) -> dict:
    """Backward-compatible alias for the two-provider question path."""
    return await generate_question_text(prompt)


async def _generate_text_with_claude_code(prompt: str) -> dict:
    claude_code_command = _ensure_claude_code_subscription_mode()
    cmd = [
        claude_code_command,
        "-p",
        "--input-format",
        "text",
        "--output-format",
        "text",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--safe-mode",
        "--no-session-persistence",
    ]
    if settings.claude_code_model:
        cmd.extend(["--model", settings.claude_code_model])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        process,
        prompt,
        provider_label="Claude Code",
        timeout_s=settings.claude_code_timeout_s,
    )
    content = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise RuntimeError(f"Claude Code CLI呼び出しに失敗しました: {error or content or process.returncode}")
    if not content:
        raise RuntimeError(f"Claude Code CLIから回答を取得できませんでした: {error or '出力が空でした'}")
    return {
        "content": content,
        "usage": {"model": "claude-code", "billing": "claude-subscription"},
    }


def _resolve_codex_subscription_command() -> str:
    configured = [name for name in _CODEX_API_ENV_VARS if _truthy_env(name)]
    if configured:
        joined = ", ".join(configured)
        raise RuntimeError(
            f"{joined} が設定されています。Codex CLIがAPI課金に流れる恐れがあるため、"
            "Codex要約を停止しました。ChatGPTサブスク枠で使う場合は該当環境変数を外してください。"
        )

    resolved_command = shutil.which(settings.codex_cli_command)
    if not resolved_command:
        raise RuntimeError(
            f"Codex CLI `{settings.codex_cli_command}` が見つかりません。"
            "`codex --version` が通る状態にしてください。"
        )
    return resolved_command


async def _verify_codex_chatgpt_login(command: str, cwd: str) -> None:
    process = await asyncio.create_subprocess_exec(
        command,
        "login",
        "status",
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_with_timeout(
        process,
        None,
        provider_label="Codex CLI認証確認",
        timeout_s=settings.codex_cli_timeout_s,
    )
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    status_text = "\n".join(part for part in (output, error) if part)
    if process.returncode != 0:
        raise RuntimeError(
            f"Codex CLI認証確認に失敗しました: {status_text or process.returncode}"
        )
    if "Logged in using ChatGPT" not in status_text:
        raise RuntimeError(
            "Codex CLIがChatGPTサブスク認証ではありません。"
            f" `codex login status` の結果: {status_text or '出力なし'}"
        )


async def _generate_text_with_codex_cli(prompt: str) -> dict:
    command = _resolve_codex_subscription_command()
    with tempfile.TemporaryDirectory(prefix="transcriber-codex-") as temp_dir:
        await _verify_codex_chatgpt_login(command, temp_dir)
        output_path = Path(temp_dir) / "last-message.txt"
        cmd = [
            command,
            "exec",
            "-p",
            settings.codex_cli_profile,
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "-",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=temp_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await _communicate_with_timeout(
            process,
            prompt,
            provider_label="Codex CLI要約",
            timeout_s=settings.codex_cli_timeout_s,
        )
        diagnostic = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise RuntimeError(
                f"Codex CLI呼び出しに失敗しました: "
                f"{error or diagnostic or process.returncode}"
            )
        if not output_path.exists():
            raise RuntimeError(
                f"Codex CLIから回答を取得できませんでした: "
                f"{error or diagnostic or '最終応答ファイルがありません'}"
            )
        content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            raise RuntimeError(
                f"Codex CLIから回答を取得できませんでした: "
                f"{error or diagnostic or '出力が空でした'}"
            )

    return {
        "content": content,
        "usage": {"model": "codex-cli", "billing": "codex-subscription"},
    }


async def _generate_text_with_gemini(prompt: str) -> dict:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")
    client = get_gemini_client()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.gemini_model,
        contents=prompt,
    )
    content = response.text
    usage = {"model": settings.gemini_model, "billing": "api"}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        usage["total_tokens"] = getattr(meta, "total_token_count", 0) or 0
    return {"content": content, "usage": usage}


async def generate_summary_auto(entries: list[dict]) -> dict:
    """Use Claude, Codex, and then Gemini for automatic summaries."""
    prompt, _, _ = _build_summary_prompt(entries)
    result = await generate_summary_text(prompt)
    summary = result["content"]
    return {
        "summary": summary,
        "title": extract_title(summary),
        "usage": result.get("usage", {}),
    }


async def generate_summary_with_gemini(entries: list[dict]) -> dict:
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

    prompt, transcript_text, tier = _build_summary_prompt(entries)

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
            "billing": "api",
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
