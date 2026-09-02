from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from backend.models import session as session_mod
from backend.models.schemas import SessionStatus


def audio_device(index: int, name: str):
    return SimpleNamespace(index=index, name=name)


class FakeAudioManager:
    def __init__(self):
        self.current_mic_index = 23
        self.current_mic_name = "マイク (2- INZONE H3)"
        self.current_loopback_indices = (25,)
        self.current_loopback_name = "INZONE H3 [Loopback]"
        self.synced: list[list[int]] = []
        self.reopened: list[tuple[int | None, list[int]]] = []
        self.switched_mics: list[int] = []

    def sync_loopback_streams(self, indices: list[int]) -> list[int]:
        self.synced.append(list(indices))
        self.current_loopback_indices = tuple(indices)
        return list(indices)

    def reopen_devices(
        self,
        mic_index: int | None,
        indices: list[int],
    ) -> list[int]:
        self.reopened.append((mic_index, list(indices)))
        self.current_mic_index = mic_index
        self.current_loopback_indices = tuple(indices)
        return list(indices)

    def switch_mic(self, index: int) -> None:
        self.switched_mics.append(index)
        self.current_mic_index = index


def test_resolve_start_devices_uses_both_preferred_loopbacks(monkeypatch):
    session = session_mod.TranscriptionSession()
    monkeypatch.setattr(
        "backend.core.audio_capture.get_default_microphone",
        lambda: audio_device(23, "INZONE mic"),
    )
    monkeypatch.setattr(
        "backend.core.audio_capture.get_preferred_loopbacks",
        lambda _patterns: [
            audio_device(25, "INZONE H3 [Loopback]"),
            audio_device(29, "Anker PowerConf S330 [Loopback]"),
        ],
    )

    mic_index, loopback_indices, automatic = session._resolve_start_devices(
        None,
        None,
    )

    assert mic_index == 23
    assert loopback_indices == [25, 29]
    assert automatic


def test_resolve_start_devices_falls_back_to_default_loopback(monkeypatch):
    session = session_mod.TranscriptionSession()
    monkeypatch.setattr(
        "backend.core.audio_capture.get_default_microphone",
        lambda: audio_device(23, "INZONE mic"),
    )
    monkeypatch.setattr(
        "backend.core.audio_capture.get_preferred_loopbacks",
        lambda _patterns: [],
    )
    monkeypatch.setattr(
        "backend.core.audio_capture.get_default_loopback",
        lambda: audio_device(27, "Default [Loopback]"),
    )

    _, loopback_indices, automatic = session._resolve_start_devices(None, None)

    assert loopback_indices == [27]
    assert automatic


def test_resolve_start_devices_preserves_explicit_loopback(monkeypatch):
    session = session_mod.TranscriptionSession()
    preferred = Mock()
    monkeypatch.setattr(
        "backend.core.audio_capture.get_preferred_loopbacks",
        preferred,
    )

    mic_index, loopback_indices, automatic = session._resolve_start_devices(
        24,
        29,
    )

    assert mic_index == 24
    assert loopback_indices == [29]
    assert not automatic
    preferred.assert_not_called()


def test_sync_automatic_loopbacks_keeps_both_targets(monkeypatch):
    session = session_mod.TranscriptionSession()
    fake_audio = FakeAudioManager()
    session._audio = fake_audio
    session._automatic_loopback_devices = True
    session._has_loopback = True
    monkeypatch.setattr(
        session,
        "_resolve_automatic_loopback_indices",
        lambda: [25, 29],
    )

    asyncio.run(session._sync_automatic_loopback_devices())

    assert fake_audio.synced == [[25, 29]]
    assert fake_audio.reopened == []


def test_sync_after_device_list_change_reopens_mic_and_loopbacks(monkeypatch):
    session = session_mod.TranscriptionSession()
    fake_audio = FakeAudioManager()
    session._audio = fake_audio
    session._automatic_loopback_devices = True
    session._has_loopback = True
    monkeypatch.setattr(
        session,
        "_resolve_automatic_loopback_indices",
        lambda: [25, 29],
    )
    monkeypatch.setattr(
        "backend.core.audio_capture.get_default_microphone",
        lambda: audio_device(24, "Anker mic"),
    )

    asyncio.run(session._sync_automatic_loopback_devices(recreate_audio=True))

    assert fake_audio.reopened == [(24, [25, 29])]
    assert fake_audio.synced == []


def test_explicit_loopback_is_not_replaced_by_automatic_sync(monkeypatch):
    session = session_mod.TranscriptionSession()
    fake_audio = FakeAudioManager()
    session._audio = fake_audio
    session._automatic_loopback_devices = False
    resolve = Mock(return_value=[25, 29])
    monkeypatch.setattr(session, "_resolve_automatic_loopback_indices", resolve)

    asyncio.run(session._sync_automatic_loopback_devices())

    resolve.assert_not_called()
    assert fake_audio.synced == []
    assert fake_audio.reopened == []


def test_loopback_availability_transition_reconfigures_running_pipeline(monkeypatch):
    session = session_mod.TranscriptionSession()
    session.status = SessionStatus.RUNNING
    session.session_id = "session"
    session.session_name = "meeting"
    session.started_at = datetime.now()
    session._has_loopback = False
    monkeypatch.setattr(session._loopback_buffer, "load_model", Mock())
    monkeypatch.setattr(session._loopback_buffer, "start_session", Mock())
    monkeypatch.setattr(session._pipeline, "configure", Mock())

    session._set_loopback_availability(True)

    assert session._has_loopback
    session._loopback_buffer.load_model.assert_called_once()
    session._loopback_buffer.start_session.assert_called_once()
    session._pipeline.configure.assert_called_once_with(
        "session",
        "meeting",
        session.started_at,
        True,
    )

    session._pipeline.configure.reset_mock()
    session._set_loopback_availability(False)
    assert not session._has_loopback
    session._pipeline.configure.assert_called_once_with(
        "session",
        "meeting",
        session.started_at,
        False,
    )
