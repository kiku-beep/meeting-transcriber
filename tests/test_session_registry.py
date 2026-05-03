import pytest

from backend.models import session as session_mod
from backend.models.schemas import SessionStatus


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    return default


def test_idle_client_sessions_do_not_consume_concurrency_slots(monkeypatch):
    reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "max_concurrent_sessions", 1)

    session_mod.get_or_create_session("alice")
    session_mod.get_or_create_session("bob")

    assert session_mod.active_session_count() == 0


def test_active_session_limit_blocks_new_recordings(monkeypatch):
    reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "max_concurrent_sessions", 1)

    alice = session_mod.get_or_create_session("alice")
    alice.status = SessionStatus.RUNNING
    session_mod.get_or_create_session("bob")

    with pytest.raises(RuntimeError, match="Max concurrent sessions"):
        session_mod.ensure_session_capacity("bob")

    session_mod.ensure_session_capacity("alice")
