import sys
from pathlib import Path

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
