from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes_session import router
from backend.models import session as session_mod
from backend.models.schemas import SessionStatus, TranscriptEntry


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    return default


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_status_uses_requested_client_session(monkeypatch):
    default = reset_registry(monkeypatch)
    default.status = SessionStatus.IDLE

    alice = session_mod.get_or_create_session("alice")
    alice.status = SessionStatus.RUNNING
    alice.session_id = "alice-session"

    client = TestClient(make_app())
    response = client.get("/api/session/status?client_id=alice")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["session_id"] == "alice-session"


def test_entries_use_requested_client_session(monkeypatch):
    reset_registry(monkeypatch)

    alice = session_mod.get_or_create_session("alice")
    alice.entries.append(TranscriptEntry(id="alice-entry", text="alice text"))

    client = TestClient(make_app())
    response = client.get("/api/session/entries?client_id=alice")

    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()["entries"]] == ["alice-entry"]
