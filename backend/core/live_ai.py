"""Live-session AI summary and question helpers."""

from __future__ import annotations

from copy import deepcopy

from backend.core.summarizer import generate_question_text, generate_summary_text


def select_live_entries(
    entries: list[dict], range_minutes: int | None
) -> tuple[list[dict], float, float]:
    """Return an immutable snapshot for the requested rolling time range."""
    if not entries:
        raise ValueError("文字起こしが空です")
    if range_minutes is not None and not 1 <= range_minutes <= 120:
        raise ValueError("対象時間は1分から120分で指定してください")

    end = max(float(entry.get("timestamp_end", 0)) for entry in entries)
    if range_minutes is None:
        selected = entries
        start = min(float(entry.get("timestamp_start", 0)) for entry in entries)
    else:
        start = max(0.0, end - range_minutes * 60)
        selected = [
            entry
            for entry in entries
            if float(entry.get("timestamp_end", 0)) >= start
        ]

    if not selected:
        raise ValueError("指定した時間範囲に文字起こしがありません")
    return deepcopy(selected), start, end


def _format_entries(entries: list[dict]) -> str:
    lines: list[str] = []
    for entry in entries:
        seconds = int(float(entry.get("timestamp_start", 0)))
        minutes, remainder = divmod(seconds, 60)
        speaker = entry.get("speaker_name") or "不明"
        text = entry.get("text") or ""
        lines.append(f"[{minutes:02d}:{remainder:02d}] {speaker}: {text}")
    return "\n".join(lines)


async def generate_live_ai(
    entries: list[dict], mode: str, question: str | None = None
) -> dict:
    """Generate a live summary or a grounded answer from a transcript snapshot."""
    transcript = _format_entries(entries)
    if not transcript.strip():
        raise ValueError("文字起こしが空です")

    if mode == "summary":
        generate = generate_summary_text
        prompt = f"""以下は進行中の会議の文字起こしです。

{transcript}

ここまでの内容だけを日本語のMarkdownで簡潔に整理してください。
次の見出しを使用してください。

## ここまでの要点
## 決定事項
## 未決事項
## 次のアクション

文字起こしにない内容は補わないでください。"""
    elif mode == "question":
        generate = generate_question_text
        cleaned_question = (question or "").strip()
        if not cleaned_question:
            raise ValueError("質問を入力してください")
        prompt = f"""以下は進行中の会議の文字起こしです。

{transcript}

質問: {cleaned_question}

文字起こしの内容だけを根拠に日本語で回答してください。
文字起こしにない内容を推測せず、判断できない場合はその旨を明記してください。"""
    else:
        raise ValueError("modeはsummaryまたはquestionを指定してください")

    return await generate(prompt)
