from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes_server import router
from backend.models import session as session_mod
from backend.models.schemas import SessionStatus


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    monkeypatch.setattr(session_mod, "_client_connections", {})
    return default


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_server_diagnostics_exposes_remote_backend_state(monkeypatch):
    reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "deployment_mode", "server")
    monkeypatch.setattr(session_mod.settings, "auth_token", "secret")
    monkeypatch.setattr(session_mod.settings, "max_concurrent_sessions", 2)

    alice = session_mod.get_or_create_session("alice")
    alice.status = SessionStatus.RUNNING

    client = TestClient(make_app())
    response = client.get("/api/server/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert data["deployment_mode"] == "server"
    assert data["auth_required"] is True
    assert data["audio_ws_path"] == "/ws/audio/{client_id}"
    assert data["transcript_ws_path"] == "/ws/transcript"
    assert data["active_session_count"] == 1
    assert data["max_concurrent_sessions"] == 2
    assert data["client_session_count"] == 1
    assert data["empty_idle_session_count"] == 0


def test_cleanup_empty_idle_sessions_endpoint(monkeypatch):
    reset_registry(monkeypatch)

    session_mod.get_or_create_session("empty-client")
    completed = session_mod.get_or_create_session("completed-client")
    completed.session_id = "completed-session"

    client = TestClient(make_app())
    response = client.post("/api/server/cleanup-empty-idle-sessions")

    assert response.status_code == 200
    assert response.json() == {"removed": ["empty-client"], "removed_count": 1}
    assert "empty-client" not in session_mod._sessions
    assert "completed-client" in session_mod._sessions
