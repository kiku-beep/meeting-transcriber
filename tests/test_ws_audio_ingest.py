import json

import pytest
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


def test_audio_ws_reports_auth_error_after_accept(monkeypatch):
    reset_registry(monkeypatch)
    monkeypatch.setattr(ws_audio_ingest.settings, "auth_token", "secret")

    client = TestClient(make_app())
    with client.websocket_connect("/ws/audio/alice?source=mic&token=wrong") as ws:
        message = ws.receive_json()

    assert message == {"type": "error", "detail": "Unauthorized"}


@pytest.mark.anyio
async def test_start_message_acks_existing_running_session(monkeypatch):
    reset_registry(monkeypatch)
    session = session_mod.get_or_create_session("alice")
    session.status = SessionStatus.RUNNING
    session.session_id = "alice-session"

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("running session should be joined, not restarted")

    monkeypatch.setattr(ws_audio_ingest, "_start_server_session", fail_if_called)

    result = await ws_audio_ingest._start_or_join_server_session(
        session, "alice", "meeting"
    )

    assert result == {
        "type": "started",
        "session_id": "alice-session",
        "already_running": True,
    }
