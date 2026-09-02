"""whisper.cpp server backend for AMD/Vulkan ASR."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from backend.config import settings

logger = logging.getLogger(__name__)

WHISPER_CPP_MODEL_FILES = {
    "kotoba-v2.0": "ggml-kotoba-whisper-v2.0-q5_0.bin",
    "large-v3": "ggml-large-v3-q5_0.bin",
}

_SERVER_START_LOCK = threading.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def _pyinstaller_internal_dir() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "_internal"
    return None


def _configured_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    return path if path.exists() else None


def resolve_whisper_cpp_server_path() -> Path | None:
    configured = _configured_path(settings.whisper_cpp_server_path)
    if configured:
        return configured

    root = _runtime_root()
    internal = _pyinstaller_internal_dir()
    candidates = [
        root / "whispercpp" / "whisper-server.exe",
        root.parent / "whispercpp" / "whisper-server.exe",
        root / "tools" / "whispercpp-vulkan" / "extracted" / "whisper-server.exe",
    ]
    if internal is not None:
        candidates.insert(0, internal / "whispercpp" / "whisper-server.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate

    found = shutil.which("whisper-server") or shutil.which("whisper-server.exe")
    return Path(found) if found else None


def resolve_whisper_cpp_model_path(model_size: str) -> Path | None:
    configured = _configured_path(settings.whisper_cpp_model_path)
    if configured:
        return configured

    filename = WHISPER_CPP_MODEL_FILES.get(model_size)
    if not filename:
        return None

    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "koepen" / "models" / filename)

    root = _runtime_root()
    candidates.extend(
        [
            root / "models" / filename,
            root.parent / "models" / filename,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def is_whisper_cpp_available(model_size: str) -> bool:
    return (
        resolve_whisper_cpp_server_path() is not None
        and resolve_whisper_cpp_model_path(model_size) is not None
    )


class WhisperCppServerBackend:
    """Persistent whisper.cpp HTTP server wrapper."""

    def __init__(self, model_size: str):
        self.model_size = model_size
        self._server_path: Path | None = None
        self._model_path: Path | None = None
        self._process: subprocess.Popen | None = None
        self._base_url = f"http://{settings.whisper_cpp_host}:{settings.whisper_cpp_port}"
        self.is_loaded = False

    def load_model(self) -> None:
        if self.is_loaded:
            return

        self._server_path = resolve_whisper_cpp_server_path()
        self._model_path = resolve_whisper_cpp_model_path(self.model_size)
        if self._server_path is None:
            raise RuntimeError("whisper.cpp server executable not found")
        if self._model_path is None:
            raise RuntimeError(f"whisper.cpp model not found for {self.model_size}")

        with _SERVER_START_LOCK:
            if not self._is_healthy():
                self._start_server()
                self._wait_until_ready()

        self.is_loaded = True
        logger.info(
            "whisper.cpp backend ready: server=%s model=%s url=%s",
            self._server_path,
            self._model_path,
            self._base_url,
        )

    def unload_model(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self.is_loaded = False

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> dict:
        if not self.is_loaded:
            raise RuntimeError("whisper.cpp backend not loaded")

        self._ensure_server_ready()
        t0 = time.monotonic()
        try:
            result = self._transcribe_once(audio, sample_rate)
        except httpx.TransportError:
            logger.warning("whisper.cpp server request failed; restarting server and retrying once")
            self._restart_server()
            result = self._transcribe_once(audio, sample_rate)

        elapsed = time.monotonic() - t0
        logger.info(
            "Transcribed %.1fs audio in %.1fs (device=vulkan, backend=whisper.cpp): %s",
            len(audio) / sample_rate,
            elapsed,
            result["text"][:80],
        )
        return result

    def _transcribe_once(self, audio: np.ndarray, sample_rate: int) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        try:
            sf.write(str(wav_path), audio, sample_rate, subtype="PCM_16")
            with httpx.Client(timeout=settings.whisper_cpp_request_timeout_s) as client:
                with wav_path.open("rb") as fh:
                    response = client.post(
                        f"{self._base_url}/inference",
                        files={"file": (wav_path.name, fh, "audio/wav")},
                        data={
                            "temperature": "0.0",
                            "response_format": "verbose_json",
                        },
                    )
            response.raise_for_status()
            result = self._parse_response(response.json())
        finally:
            try:
                wav_path.unlink()
            except OSError:
                pass

        return result

    def _ensure_server_ready(self) -> None:
        if self._is_healthy():
            return
        logger.warning("whisper.cpp backend is loaded but server is not healthy; restarting")
        self._restart_server()

    def _restart_server(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        self._process = None
        self._start_server()
        self._wait_until_ready()

    def _start_server(self) -> None:
        assert self._server_path is not None
        assert self._model_path is not None
        cmd = [
            str(self._server_path),
            "-m",
            str(self._model_path),
            "--host",
            settings.whisper_cpp_host,
            "--port",
            str(settings.whisper_cpp_port),
            "-l",
            settings.whisper_language,
            "-nt",
            "-bs",
            "1",
            "-bo",
            "1",
            "-nf",
            "-dev",
            str(settings.whisper_cpp_device),
        ]
        logger.info("Starting whisper.cpp server: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            cwd=str(self._server_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                raise RuntimeError(f"whisper.cpp server exited with {self._process.returncode}")
            if self._is_healthy():
                return
            time.sleep(0.5)
        raise RuntimeError("Timed out waiting for whisper.cpp server")

    def _is_healthy(self) -> bool:
        try:
            response = httpx.get(self._base_url, timeout=1.0)
            return response.status_code < 500
        except Exception:
            return False

    def _parse_response(self, data: dict) -> dict:
        segments = data.get("segments") or []
        text = str(data.get("text") or "").strip()
        if not text and segments:
            text = " ".join(str(seg.get("text") or "").strip() for seg in segments).strip()

        no_speech_probs = [
            float(seg.get("no_speech_prob", 0.0))
            for seg in segments
            if seg.get("no_speech_prob") is not None
        ]
        avg_logprobs = [
            float(seg.get("avg_logprob", 0.0))
            for seg in segments
            if seg.get("avg_logprob") is not None
        ]

        language = settings.whisper_language
        if str(data.get("detected_language") or "").lower().startswith("japanese"):
            language = "ja"

        return {
            "text": text,
            "language": language,
            "confidence": float(data.get("detected_language_probability", 1.0) or 0.0),
            "no_speech_prob": max(no_speech_probs) if no_speech_probs else 0.0,
            "avg_logprob": sum(avg_logprobs) / len(avg_logprobs) if avg_logprobs else 0.0,
            "compression_ratio": 0.0,
        }
