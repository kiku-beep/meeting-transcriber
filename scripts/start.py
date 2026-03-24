"""Launch backend and frontend together."""

from __future__ import annotations

import subprocess
import sys
import signal
import time
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

IS_WINDOWS = sys.platform == "win32"


def _wait_for_backend(url: str = "http://127.0.0.1:8000/api/health",
                      timeout: float = 30) -> bool:
    """Poll backend health endpoint until it responds or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)
    return False


def main():
    procs: list[subprocess.Popen] = []

    def shutdown(sig=None, frame=None):
        print("\n[start] Shutting down...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if IS_WINDOWS:
        signal.signal(signal.SIGBREAK, shutdown)
    else:
        signal.signal(signal.SIGTERM, shutdown)

    # On Windows, CREATE_NEW_PROCESS_GROUP prevents child from receiving
    # the parent's Ctrl+C directly — we manage shutdown ourselves.
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0

    # Start backend (no --reload; reload spawns extra processes)
    print("[start] Launching backend (uvicorn) ...")
    backend = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT),
        creationflags=creation_flags,
    )
    procs.append(backend)

    # Wait for backend to be ready
    print("[start] Waiting for backend health check ...")
    if not _wait_for_backend():
        print("[start] ERROR: Backend did not start within 30s. Aborting.")
        shutdown()
        return

    print("[start] Backend is ready.")

    # Start frontend
    print("[start] Launching frontend (Gradio) ...")
    frontend = subprocess.Popen(
        [PYTHON, "-m", "frontend.app"],
        cwd=str(ROOT),
        creationflags=creation_flags,
    )
    procs.append(frontend)

    print("[start] Backend:  http://127.0.0.1:8000")
    print("[start] Frontend: http://127.0.0.1:7860")
    print("[start] Press Ctrl+C to stop both.\n")

    # Wait for either to exit
    try:
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    name = "Backend" if p is backend else "Frontend"
                    print(f"[start] {name} (pid {p.pid}) exited with code {ret}")
                    shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
