import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import ws_audio_ingest
from backend.models import session as session_mod
from backend.models.schemas import SessionStatus


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    return default


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_audio_ingest.router)
    return app


def test_audio_ws_reports_capacity_error_before_starting_session(monkeypatch):
    reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "max_concurrent_sessions", 1)
    monkeypatch.setattr(ws_audio_ingest.settings, "auth_token", "")

    alice = session_mod.get_or_create_session("alice")
    alice.status = SessionStatus.RUNNING

    async def fake_start(session, client_id, session_name):
        session.status = SessionStatus.RUNNING
        session.session_id = "fake-session"

    monkeypatch.setattr(ws_audio_ingest, "_start_server_session", fake_start)

    client = TestClient(make_app())
    with client.websocket_connect("/ws/audio/bob?source=mic") as ws:
        ws.send_text(json.dumps({"type": "start", "session_name": "busy"}))

        message = ws.receive_json()

    assert message["type"] == "error"
    assert "Max concurrent sessions" in message["detail"]
