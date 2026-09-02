import pytest

from backend.models import session as session_mod
from backend.models.schemas import SessionStatus


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    monkeypatch.setattr(session_mod, "_client_connections", {})
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


def test_empty_idle_client_sessions_can_be_cleaned_without_completed_sessions(monkeypatch):
    reset_registry(monkeypatch)

    empty = session_mod.get_or_create_session("empty-client")
    empty.status = SessionStatus.IDLE

    completed = session_mod.get_or_create_session("completed-client")
    completed.status = SessionStatus.IDLE
    completed.session_id = "completed-session"

    running = session_mod.get_or_create_session("running-client")
    running.status = SessionStatus.RUNNING

    removed = session_mod.cleanup_empty_idle_client_sessions()

    assert removed == ["empty-client"]
    assert "empty-client" not in session_mod._sessions
    assert "completed-client" in session_mod._sessions
    assert "running-client" in session_mod._sessions
    assert session_mod.empty_idle_client_session_count() == 0


def test_connected_empty_idle_client_session_is_not_cleaned(monkeypatch):
    reset_registry(monkeypatch)

    session_mod.get_or_create_session("connected-client")
    session_mod.register_client_connection("connected-client")

    removed = session_mod.cleanup_empty_idle_client_sessions()

    assert removed == []
    assert "connected-client" in session_mod._sessions
    assert session_mod.empty_idle_client_session_count() == 0

    session_mod.unregister_client_connection("connected-client")
    assert session_mod.cleanup_empty_idle_client_sessions() == ["connected-client"]


def test_model_switch_reservation_blocks_session_start(monkeypatch):
    reset_registry(monkeypatch)
    session = session_mod.get_or_create_session("alice")

    assert session_mod.reserve_model_switch() is True
    try:
        with pytest.raises(RuntimeError, match="モデル切替中"):
            session_mod.begin_session_start(session)
    finally:
        session_mod.release_model_switch()

    session_mod.begin_session_start(session)
    assert session.status == SessionStatus.STARTING
    assert session_mod.reserve_model_switch() is False
