import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from backend.api.routes_summary import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _entry(start: float, end: float, text: str = "発言"):
    from backend.models.schemas import TranscriptEntry

    return TranscriptEntry(
        id=f"entry-{start}",
        text=text,
        raw_text=text,
        speaker_name="話者A",
        speaker_id="speaker-a",
        timestamp_start=start,
        timestamp_end=end,
    )


def test_live_summary_uses_requested_client_session(monkeypatch):
    from backend.api import routes_summary
    from backend.models import session as session_mod

    remote = session_mod.get_or_create_session("mac-test")
    remote.entries = [_entry(0, 2, "遠隔クライアントの発言")]

    async def fake_generate(entries, mode, question=None):
        assert entries[0]["text"] == "遠隔クライアントの発言"
        return {"content": "途中要約", "usage": {"model": "test"}}

    monkeypatch.setattr(routes_summary, "generate_live_ai", fake_generate)

    response = _client().post(
        "/api/summary/live",
        json={"client_id": "mac-test", "mode": "summary", "range_minutes": None},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "途中要約"
    assert body["entry_count"] == 1
    assert body["range_start_seconds"] == 0
    assert body["range_end_seconds"] == 2
    assert body["generated_at"]


def test_live_question_requires_question():
    response = _client().post(
        "/api/summary/live",
        json={"client_id": "default", "mode": "question", "question": ""},
    )

    assert response.status_code == 400
    assert "質問を入力" in response.json()["detail"]


def test_live_ai_failure_does_not_change_recording_status(monkeypatch):
    from backend.api import routes_summary
    from backend.models import session as session_mod
    from backend.models.schemas import SessionStatus

    session = session_mod.get_or_create_session("recording-client")
    session.entries = [_entry(0, 1)]
    session.status = SessionStatus.RUNNING

    async def fail(*args, **kwargs):
        raise RuntimeError("AI failed")

    monkeypatch.setattr(routes_summary, "generate_live_ai", fail)

    response = _client().post(
        "/api/summary/live",
        json={"client_id": "recording-client", "mode": "summary"},
    )

    assert response.status_code == 500
    assert session.status == SessionStatus.RUNNING


def test_live_ai_rejects_duplicate_request(monkeypatch):
    from backend.api import routes_summary
    from backend.models import session as session_mod

    session = session_mod.get_or_create_session("busy-client")
    session.entries = [_entry(0, 1)]
    routes_summary._live_ai_busy_clients.add("busy-client")
    try:
        response = _client().post(
            "/api/summary/live",
            json={"client_id": "busy-client", "mode": "summary"},
        )
    finally:
        routes_summary._live_ai_busy_clients.discard("busy-client")

    assert response.status_code == 409

