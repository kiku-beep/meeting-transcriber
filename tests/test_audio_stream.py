from __future__ import annotations

import numpy as np

from backend.models.audio_stream import AudioStreamManager
from backend.models.schemas import SessionStatus


class FakeBuffer:
    def __init__(self):
        self.frames: list[np.ndarray] = []

    def feed(self, audio: np.ndarray) -> None:
        self.frames.append(audio.copy())


class FakeStream:
    def __init__(self, device_index: int, callback):
        self.device_index = device_index
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start_stream(self) -> None:
        self.started = True

    def stop_stream(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakePyAudio:
    def __init__(self, *, fail_indices: set[int] | None = None):
        self.fail_indices = fail_indices or set()
        self.streams: dict[int, FakeStream] = {}
        self.terminated = False

    def get_device_info_by_index(self, index: int) -> dict:
        names = {
            23: "マイク (2- INZONE H3)",
            25: "スピーカー (2- INZONE H3) [Loopback]",
            29: "スピーカー (2- Anker PowerConf S330) [Loopback]",
        }
        return {
            "index": index,
            "name": names[index],
            "defaultSampleRate": 16000,
            "maxInputChannels": 1,
        }

    def open(self, *, input_device_index: int, stream_callback, **_kwargs):
        if input_device_index in self.fail_indices:
            raise OSError(f"cannot open {input_device_index}")
        stream = FakeStream(input_device_index, stream_callback)
        self.streams[input_device_index] = stream
        return stream

    def terminate(self) -> None:
        self.terminated = True


def make_manager(fake_pa: FakePyAudio):
    manager = AudioStreamManager()
    manager._pa = fake_pa
    mic_buffer = FakeBuffer()
    loopback_buffer = FakeBuffer()
    recorded_audio: list[np.ndarray] = []
    recorded_loopback: list[np.ndarray] = []
    status = {"value": SessionStatus.RUNNING}
    manager.setup(
        mic_buffer,
        loopback_buffer,
        recorded_audio,
        lambda: status["value"],
        recorded_loopback=recorded_loopback,
    )
    return manager, loopback_buffer, recorded_loopback, status


def test_open_loopback_streams_opens_each_unique_device():
    fake_pa = FakePyAudio()
    manager, _, _, _ = make_manager(fake_pa)

    opened = manager.open_loopback_streams([25, 29, 25])

    assert opened == [25, 29]
    assert set(fake_pa.streams) == {25, 29}
    assert all(stream.started for stream in fake_pa.streams.values())
    assert manager.current_loopback_name == (
        "スピーカー (2- INZONE H3) [Loopback] / "
        "スピーカー (2- Anker PowerConf S330) [Loopback]"
    )


def test_open_loopback_streams_keeps_working_device_when_other_fails():
    fake_pa = FakePyAudio(fail_indices={29})
    manager, _, _, _ = make_manager(fake_pa)

    opened = manager.open_loopback_streams([25, 29])

    assert opened == [25]
    assert set(fake_pa.streams) == {25}


def test_sync_loopback_streams_closes_removed_device_and_keeps_existing():
    fake_pa = FakePyAudio()
    manager, _, _, _ = make_manager(fake_pa)
    manager.open_loopback_streams([25, 29])
    removed_stream = fake_pa.streams[25]
    retained_stream = fake_pa.streams[29]

    opened = manager.sync_loopback_streams([29])

    assert opened == [29]
    assert removed_stream.stopped and removed_stream.closed
    assert not retained_stream.closed
    assert manager.current_loopback_indices == (29,)


def test_close_streams_closes_mic_and_all_loopbacks():
    fake_pa = FakePyAudio()
    manager, _, _, _ = make_manager(fake_pa)
    manager.open_mic_stream(23)
    manager.open_loopback_streams([25, 29])

    manager.close_streams()

    assert all(stream.stopped and stream.closed for stream in fake_pa.streams.values())
    assert manager.current_mic_index is None
    assert manager.current_loopback_indices == ()


def test_reopen_devices_closes_old_streams_before_recreating_pyaudio(monkeypatch):
    old_pa = FakePyAudio()
    manager, _, _, _ = make_manager(old_pa)
    manager.open_mic_stream(23)
    manager.open_loopback_streams([25, 29])
    old_streams = list(old_pa.streams.values())
    new_pa = FakePyAudio()

    def recreate():
        old_pa.terminate()
        manager._pa = new_pa
        return new_pa

    monkeypatch.setattr(manager, "_recreate_pyaudio", recreate)

    opened = manager.reopen_devices(23, [25, 29])

    assert all(stream.stopped and stream.closed for stream in old_streams)
    assert old_pa.terminated
    assert set(new_pa.streams) == {23, 25, 29}
    assert opened == [25, 29]


def test_callbacks_append_only_selected_source_frames(monkeypatch):
    fake_pa = FakePyAudio()
    manager, loopback_buffer, recorded_loopback, _ = make_manager(fake_pa)
    manager.open_loopback_streams([25, 29])
    clock = {"value": 0.0}
    monkeypatch.setattr(
        "backend.models.audio_stream.time.monotonic",
        lambda: clock["value"],
    )
    signal = np.full(1600, 0.1, dtype=np.float32).tobytes()
    silence = np.zeros(1600, dtype=np.float32).tobytes()

    fake_pa.streams[25].callback(signal, 1600, {}, 0)
    clock["value"] = 0.01
    fake_pa.streams[29].callback(signal, 1600, {}, 0)
    clock["value"] = 0.1
    fake_pa.streams[25].callback(silence, 1600, {}, 0)
    clock["value"] = 0.21
    fake_pa.streams[29].callback(signal, 1600, {}, 0)

    assert len(loopback_buffer.frames) == 3
    assert len(recorded_loopback) == 3
    assert np.allclose(recorded_loopback[0], 0.1)
    assert np.allclose(recorded_loopback[1], 0.0)
    assert np.allclose(recorded_loopback[2], 0.1)


def test_loopback_callbacks_do_not_record_while_paused():
    fake_pa = FakePyAudio()
    manager, loopback_buffer, recorded_loopback, status = make_manager(fake_pa)
    manager.open_loopback_streams([25, 29])
    status["value"] = SessionStatus.PAUSED
    signal = np.full(1600, 0.1, dtype=np.float32).tobytes()

    fake_pa.streams[25].callback(signal, 1600, {}, 0)
    fake_pa.streams[29].callback(signal, 1600, {}, 0)

    assert loopback_buffer.frames == []
    assert recorded_loopback == []
