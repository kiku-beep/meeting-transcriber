import asyncio

import pytest


def _entry(start: float, end: float, text: str = "発言") -> dict:
    return {
        "id": f"entry-{start}",
        "speaker_name": "話者A",
        "text": text,
        "timestamp_start": start,
        "timestamp_end": end,
    }


def test_select_live_entries_returns_snapshot_for_entire_meeting():
    from backend.core.live_ai import select_live_entries

    entries = [_entry(0, 5), _entry(120, 125)]

    selected, start, end = select_live_entries(entries, None)

    assert selected == entries
    assert selected is not entries
    assert start == 0
    assert end == 125


def test_select_live_entries_uses_latest_timestamp_for_rolling_window():
    from backend.core.live_ai import select_live_entries

    entries = [_entry(0, 5), _entry(300, 305), _entry(900, 905)]

    selected, start, end = select_live_entries(entries, 10)

    assert [entry["timestamp_start"] for entry in selected] == [300, 900]
    assert start == 305
    assert end == 905


def test_select_live_entries_includes_entry_overlapping_window_boundary():
    from backend.core.live_ai import select_live_entries

    entries = [_entry(290, 310), _entry(900, 910)]

    selected, start, end = select_live_entries(entries, 10)

    assert len(selected) == 2
    assert start == 310
    assert end == 910


@pytest.mark.parametrize("value", [0, -1, 121])
def test_select_live_entries_rejects_invalid_range(value):
    from backend.core.live_ai import select_live_entries

    with pytest.raises(ValueError, match="対象時間"):
        select_live_entries([_entry(0, 1)], value)


def test_select_live_entries_rejects_empty_transcript():
    from backend.core.live_ai import select_live_entries

    with pytest.raises(ValueError, match="文字起こしが空"):
        select_live_entries([], 15)


def test_generate_live_ai_rejects_empty_question():
    from backend.core.live_ai import generate_live_ai

    with pytest.raises(ValueError, match="質問を入力"):
        asyncio.run(generate_live_ai([_entry(0, 1)], mode="question", question="  "))


def test_generate_live_ai_routes_summary_to_summary_provider_chain(monkeypatch):
    from backend.core import live_ai

    captured = {}

    async def fake_summary(prompt: str):
        captured["prompt"] = prompt
        return {
            "content": "途中要約",
            "usage": {"model": "codex-cli", "billing": "codex-subscription"},
        }

    async def fail_wrong_path(prompt: str):
        raise AssertionError("summary must not use the question or legacy path")

    monkeypatch.setattr(live_ai, "generate_summary_text", fake_summary, raising=False)
    monkeypatch.setattr(live_ai, "generate_question_text", fail_wrong_path, raising=False)
    monkeypatch.setattr(
        live_ai, "generate_text_with_summary_engine", fail_wrong_path, raising=False
    )

    result = asyncio.run(
        live_ai.generate_live_ai(
            [_entry(60, 65, "来週火曜に検証します")],
            mode="summary",
        )
    )

    assert "ここまでの内容だけ" in captured["prompt"]
    assert result["content"] == "途中要約"
    assert result["usage"]["billing"] == "codex-subscription"


def test_generate_live_ai_routes_question_to_two_provider_chain(monkeypatch):
    from backend.core import live_ai

    captured = {}

    async def fake_generate(prompt: str):
        captured["prompt"] = prompt
        return {
            "content": "回答",
            "usage": {"model": "claude-code", "billing": "claude-subscription"},
        }

    async def fail_wrong_path(prompt: str):
        raise AssertionError("question must not use the summary or legacy path")

    monkeypatch.setattr(live_ai, "generate_summary_text", fail_wrong_path, raising=False)
    monkeypatch.setattr(live_ai, "generate_question_text", fake_generate, raising=False)
    monkeypatch.setattr(
        live_ai, "generate_text_with_summary_engine", fail_wrong_path, raising=False
    )

    result = asyncio.run(
        live_ai.generate_live_ai(
            [_entry(60, 65, "次回は火曜日です")],
            mode="question",
            question="次回はいつ？",
        )
    )

    assert "次回はいつ？" in captured["prompt"]
    assert "文字起こしにない内容を推測" in captured["prompt"]
    assert result["content"] == "回答"
