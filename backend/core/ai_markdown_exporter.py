"""Markdown export formatted as input material for external AI tools."""

from __future__ import annotations

import json


def build_ai_markdown(session_id: str, entries: list[dict], metadata: dict | None = None) -> str:
    """Build an AI-readable Markdown transcript without calling any AI API."""
    metadata = metadata or {}
    title = _clean_inline(metadata.get("session_name") or session_id)
    speakers = _unique_speakers(entries)

    lines: list[str] = [
        "---",
        'format: "transcriber-ai-markdown"',
        "version: 1",
        f"session_id: {_yaml_string(session_id)}",
        f"session_name: {_yaml_string(metadata.get('session_name') or '')}",
        f"started_at: {_yaml_string(metadata.get('started_at') or '')}",
        f"saved_at: {_yaml_string(metadata.get('saved_at') or '')}",
        f"entry_count: {len(entries)}",
        "---",
        "",
        f"# {title}",
        "",
        "## AIへの前提",
        "- これは会議の文字起こしです。",
        "- 各発話は `番号 | 開始-終了 | 話者` の順で並んでいます。",
        "- 内容を整理する場合は、発言の時系列、話者、タイムスタンプを根拠として扱ってください。",
        "",
        "## メタデータ",
        f"- session_id: `{session_id}`",
        f"- session_name: {_markdown_value(metadata.get('session_name'))}",
        f"- started_at: {_markdown_value(metadata.get('started_at'))}",
        f"- saved_at: {_markdown_value(metadata.get('saved_at'))}",
        f"- entry_count: `{len(entries)}`",
        "",
        "## 話者一覧",
    ]

    if speakers:
        lines.extend(f"- {speaker}" for speaker in speakers)
    else:
        lines.append("- Unknown")

    lines.extend(["", "## 文字起こし", ""])

    for index, entry in enumerate(entries, start=1):
        speaker = _clean_inline(entry.get("speaker_name") or "Unknown")
        start = _format_time(entry.get("timestamp_start", 0))
        end = _format_time(entry.get("timestamp_end", entry.get("timestamp_start", 0)))
        text = _clean_text(entry.get("text") or "")

        lines.append(f"### {index:04d} | {start}-{end} | {speaker}")
        if entry.get("bookmarked"):
            lines.append("> bookmark: true")
            lines.append("")
        lines.append(text if text else "(無音または空文字)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_action_markdown(session_id: str, entries: list[dict], metadata: dict | None = None) -> str:
    """Build a Markdown brief that tells Claude/Codex to prepare executable actions."""
    metadata = metadata or {}
    title = _clean_inline(metadata.get("session_name") or session_id)
    speakers = _unique_speakers(entries)

    lines: list[str] = [
        "---",
        'format: "transcriber-action-brief"',
        "version: 1",
        f"session_id: {_yaml_string(session_id)}",
        f"session_name: {_yaml_string(metadata.get('session_name') or '')}",
        f"started_at: {_yaml_string(metadata.get('started_at') or '')}",
        f"saved_at: {_yaml_string(metadata.get('saved_at') or '')}",
        f"entry_count: {len(entries)}",
        "---",
        "",
        "# Meeting Action Brief",
        "",
        f"対象会議: {title}",
        "",
        "## 指示",
        "- この議事録から、ユーザー本人が次に動けるタスクを抽出してください。",
        "- 各タスクを、実行直前の状態まで準備してください。",
        "- 予定作成・メール送信・Slack送信は、必ずユーザー確認後に実行してください。",
        "- 不明点がある場合は、推測で送信・予定作成せず、確認事項として分離してください。",
        "",
        "## 実行準備の方針",
        "- 予定調整: 関係者、所要時間、期限、候補期間を特定し、Google Calendarで空き時間を確認する前提で候補を整理してください。",
        "- Gmail: 宛先候補、件名、本文、添付や参照元を整理し、送信前の下書きにしてください。",
        "- Slack: 投稿先またはDM相手、スレッド返信の要否、本文を整理し、送信前の下書きにしてください。",
        "- 自分の作業: すぐ着手できる順に、最初の具体アクションまで分解してください。",
        "",
        "## 出力してほしいもの",
        "1. 自分が担当するNext Action",
        "2. 予定調整が必要なもの",
        "3. Gmail下書きが必要なもの",
        "4. Slack下書きが必要なもの",
        "5. 不明点・確認すべきこと",
        "6. すぐ実行できる順の優先順位",
        "",
        "## 会議情報",
        f"- session_id: `{session_id}`",
        f"- session_name: {_markdown_value(metadata.get('session_name'))}",
        f"- started_at: {_markdown_value(metadata.get('started_at'))}",
        f"- saved_at: {_markdown_value(metadata.get('saved_at'))}",
        f"- entry_count: `{len(entries)}`",
        "",
        "## 話者一覧",
    ]

    if speakers:
        lines.extend(f"- {speaker}" for speaker in speakers)
    else:
        lines.append("- Unknown")

    lines.extend(["", "## 議事録本文", ""])

    for index, entry in enumerate(entries, start=1):
        speaker = _clean_inline(entry.get("speaker_name") or "Unknown")
        start = _format_time(entry.get("timestamp_start", 0))
        end = _format_time(entry.get("timestamp_end", entry.get("timestamp_start", 0)))
        text = _clean_text(entry.get("text") or "")

        lines.append(f"### {index:04d} | {start}-{end} | {speaker}")
        lines.append(text if text else "(無音または空文字)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _unique_speakers(entries: list[dict]) -> list[str]:
    speakers: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        speaker = _clean_inline(entry.get("speaker_name") or "Unknown")
        if speaker not in seen:
            seen.add(speaker)
            speakers.append(speaker)
    return speakers


def _format_time(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _clean_inline(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return " ".join(text.split()) or "Unknown"


def _clean_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _yaml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _markdown_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "`なし`"
    return f"`{text}`"
