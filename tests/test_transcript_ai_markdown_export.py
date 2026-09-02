import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes_transcript import router
from backend.config import settings


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_md_export_formats_transcript_for_external_ai(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    session_dir = settings.sessions_dir / "2026-06-10_090000"
    write_json(
        session_dir / "metadata.json",
        {
            "session_id": "2026-06-10_090000",
            "session_name": "AI用書き出しテスト",
            "started_at": "2026-06-10T09:00:00",
            "saved_at": "2026-06-10T09:30:00",
            "entry_count": 2,
        },
    )
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "entry-1",
                "timestamp_start": 1.2,
                "timestamp_end": 4.8,
                "speaker_name": "話者A",
                "text": "Roof-1の納まりを確認します。",
            },
            {
                "id": "entry-2",
                "timestamp_start": 65,
                "timestamp_end": 70,
                "speaker_name": "話者B",
                "text": "次回までに見積条件を整理します。",
                "bookmarked": True,
            },
        ],
    )
    (session_dir / "summary.md").write_text("# 古い要約\n\nこれは返さない。", encoding="utf-8")

    response = TestClient(make_app()).get(
        "/api/transcripts/2026-06-10_090000/export?format=md",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    markdown = response.text
    assert "format: \"transcriber-ai-markdown\"" in markdown
    assert "# AI用書き出しテスト" in markdown
    assert "- session_id: `2026-06-10_090000`" in markdown
    assert "- 話者A" in markdown
    assert "- 話者B" in markdown
    assert "### 0001 | 00:01-00:04 | 話者A" in markdown
    assert "Roof-1の納まりを確認します。" in markdown
    assert "### 0002 | 01:05-01:10 | 話者B" in markdown
    assert "> bookmark: true" in markdown
    assert "次回までに見積条件を整理します。" in markdown
    assert "これは返さない" not in markdown


def test_action_md_export_instructs_claude_to_prepare_next_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    session_dir = settings.sessions_dir / "2026-06-25_180000"
    write_json(
        session_dir / "metadata.json",
        {
            "session_id": "2026-06-25_180000",
            "session_name": "アクション準備テスト",
            "started_at": "2026-06-25T18:00:00",
            "saved_at": "2026-06-25T18:30:00",
            "entry_count": 2,
        },
    )
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "entry-1",
                "timestamp_start": 10,
                "timestamp_end": 15,
                "speaker_name": "菊地",
                "text": "来週、大川さんと乾さんの空いている時間を見て打ち合わせを入れてください。",
            },
            {
                "id": "entry-2",
                "timestamp_start": 40,
                "timestamp_end": 48,
                "speaker_name": "話者A",
                "text": "先方にはSlackで確認事項を送っておきます。",
            },
        ],
    )

    response = TestClient(make_app()).get(
        "/api/transcripts/2026-06-25_180000/export?format=action-md",
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    markdown = response.text
    assert 'format: "transcriber-action-brief"' in markdown
    assert "# Meeting Action Brief" in markdown
    assert "実行直前" in markdown
    assert "予定作成・メール送信・Slack送信は、必ずユーザー確認後に実行してください。" in markdown
    assert "Google Calendar" in markdown
    assert "Gmail" in markdown
    assert "Slack" in markdown
    assert "### 0001 | 00:10-00:15 | 菊地" in markdown
    assert "来週、大川さんと乾さんの空いている時間" in markdown
