import sys
import threading
from pathlib import Path

import numpy as np

from backend.config import settings
from backend.core import whispercpp_backend


def test_resolve_server_path_finds_pyinstaller_internal_dir(tmp_path, monkeypatch):
    sidecar_dir = tmp_path / "sidecar"
    internal_dir = sidecar_dir / "_internal" / "whispercpp"
    internal_dir.mkdir(parents=True)
    server = internal_dir / "whisper-server.exe"
    server.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(sidecar_dir / "transcriber-backend.exe"))
    monkeypatch.setattr(settings, "whisper_cpp_server_path", "")
    monkeypatch.setattr(whispercpp_backend.shutil, "which", lambda name: None)

    assert whispercpp_backend.resolve_whisper_cpp_server_path() == server


def test_transcribe_restarts_loaded_backend_when_server_is_unhealthy(tmp_path, monkeypatch):
    backend = whispercpp_backend.WhisperCppServerBackend("kotoba-v2.0")
    backend.is_loaded = True
    backend._server_path = tmp_path / "whisper-server.exe"
    backend._server_path.write_text("", encoding="utf-8")
    backend._model_path = tmp_path / "model.bin"
    backend._model_path.write_text("", encoding="utf-8")

    starts: list[str] = []
    waits: list[str] = []
    health_checks: list[str] = []

    monkeypatch.setattr(whispercpp_backend.sf, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(backend, "_is_healthy", lambda: health_checks.append("check") and False)
    monkeypatch.setattr(backend, "_start_server", lambda: starts.append("start"))
    monkeypatch.setattr(backend, "_wait_until_ready", lambda: waits.append("wait"))

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"text": "復旧しました", "segments": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            assert starts == ["start"]
            assert waits == ["wait"]
            return FakeResponse()

    monkeypatch.setattr(whispercpp_backend.httpx, "Client", FakeClient)

    result = backend.transcribe(np.zeros(16000, dtype=np.float32), sample_rate=16000)

    assert result["text"] == "復旧しました"
    assert health_checks == ["check"]


def test_concurrent_backend_instances_start_server_once(tmp_path, monkeypatch):
    server = tmp_path / "whisper-server.exe"
    server.write_text("", encoding="utf-8")
    model = tmp_path / "model.bin"
    model.write_text("", encoding="utf-8")
    healthy = {"value": False}
    first_starting = threading.Event()
    release_start = threading.Event()
    starts: list[int] = []

    monkeypatch.setattr(whispercpp_backend, "resolve_whisper_cpp_server_path", lambda: server)
    monkeypatch.setattr(whispercpp_backend, "resolve_whisper_cpp_model_path", lambda model_size: model)
    monkeypatch.setattr(
        whispercpp_backend.WhisperCppServerBackend,
        "_is_healthy",
        lambda self: healthy["value"],
    )

    def start_server(self):
        starts.append(id(self))
        first_starting.set()
        assert release_start.wait(timeout=2)

    def wait_until_ready(self):
        healthy["value"] = True

    monkeypatch.setattr(whispercpp_backend.WhisperCppServerBackend, "_start_server", start_server)
    monkeypatch.setattr(whispercpp_backend.WhisperCppServerBackend, "_wait_until_ready", wait_until_ready)

    first = whispercpp_backend.WhisperCppServerBackend("kotoba-v2.0")
    second = whispercpp_backend.WhisperCppServerBackend("kotoba-v2.0")
    errors: list[BaseException] = []

    def load(backend):
        try:
            backend.load_model()
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=load, args=(first,))
    second_thread = threading.Thread(target=load, args=(second,))
    first_thread.start()
    assert first_starting.wait(timeout=2)
    second_thread.start()
    second_thread.join(timeout=0.2)
    release_start.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert errors == []
    assert len(starts) == 1
    assert first.is_loaded is True
    assert second.is_loaded is True
