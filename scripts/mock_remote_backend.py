"""Lightweight mock backend for client-side remote-flow testing.

This server is intentionally small: it does not run ASR, diarization, or GPU
work. It lets the Mac/Windows client verify connection setup, audio WebSocket
startup, and transcript WebSocket rendering before the company GPU backend is
available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


def _session_info(session: "MockSession") -> dict[str, Any]:
    return {
        "status": session.status,
        "session_id": session.session_id,
        "session_name": session.session_name,
        "started_at": session.started_at,
        "segment_count": len(session.entries),
        "entry_count": len(session.entries),
        "elapsed_seconds": 0.0,
        "mic_device": "mock mic",
        "loopback_device": "mock loopback",
        "mic_speaking": session.status == "running",
        "loopback_speaking": False,
    }


def _fake_entry(session: "MockSession", source: str) -> dict[str, Any]:
    index = len(session.entries) + 1
    now = datetime.now().isoformat()
    return {
        "id": f"mock-{index}",
        "text": f"mock backend received {source} audio stream",
        "raw_text": f"mock backend received {source} audio stream",
        "speaker_name": "Mock Speaker",
        "speaker_id": "mock-speaker",
        "speaker_confidence": 1.0,
        "timestamp_start": float(index - 1),
        "timestamp_end": float(index),
        "created_at": now,
        "refined": True,
    }


@dataclass
class MockSession:
    client_id: str
    status: str = "idle"
    session_id: str = ""
    session_name: str = ""
    started_at: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)
    transcript_sockets: set[WebSocket] = field(default_factory=set)


class MockState:
    def __init__(self) -> None:
        self.sessions: dict[str, MockSession] = {}

    def session(self, client_id: str) -> MockSession:
        if client_id not in self.sessions:
            self.sessions[client_id] = MockSession(client_id=client_id)
        return self.sessions[client_id]

    async def broadcast(self, session: MockSession, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(session.transcript_sockets):
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            session.transcript_sockets.discard(ws)

    async def start(
        self,
        session: MockSession,
        source: str,
        session_name: str = "mock",
    ) -> dict[str, Any]:
        session.status = "running"
        session.session_id = (
            datetime.now().strftime("%Y-%m-%d_%H%M%S") + f"_{session.client_id}"
        )
        session.started_at = datetime.now().isoformat()
        session.session_name = session_name or "mock"
        entry = _fake_entry(session, source)
        session.entries.append(entry)
        await self.broadcast(session, {"type": "status", "data": _session_info(session)})
        await self.broadcast(session, {"type": "entry", "data": entry})
        return _session_info(session)

    async def stop(self, session: MockSession) -> dict[str, Any]:
        session.status = "idle"
        await self.broadcast(session, {"type": "status", "data": _session_info(session)})
        return _session_info(session)


def create_app() -> FastAPI:
    state = MockState()
    app = FastAPI(title="Transcriber Mock Remote Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "mock": True}

    @app.get("/api/health/gpu")
    async def gpu_health() -> dict[str, Any]:
        return {
            "available": True,
            "name": "Mock GPU",
            "temperature_c": 42,
            "gpu_utilization_pct": 0,
            "vram_total_mb": 8192,
            "vram_used_mb": 0,
            "vram_free_mb": 8192,
        }

    @app.get("/api/audio/devices")
    async def audio_devices() -> dict[str, Any]:
        return {
            "devices": [],
            "default_mic_index": None,
            "default_loopback_index": None,
            "default_microphone": None,
            "default_loopback": None,
        }

    @app.get("/api/speakers")
    async def speakers() -> dict[str, Any]:
        return {"speakers": []}

    @app.get("/api/session/status")
    async def session_status(client_id: str = Query("default")) -> dict[str, Any]:
        return _session_info(state.session(client_id))

    @app.get("/api/session/entries")
    async def session_entries(client_id: str = Query("default")) -> dict[str, Any]:
        return {"entries": state.session(client_id).entries}

    @app.post("/api/session/start")
    async def start_session(
        client_id: str = Query("default"),
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        return await state.start(
            state.session(client_id),
            source="rest",
            session_name=str(body.get("session_name") or "mock"),
        )

    @app.post("/api/session/stop")
    async def stop_session(client_id: str = Query("default")) -> dict[str, Any]:
        return await state.stop(state.session(client_id))

    @app.websocket("/ws/transcript")
    async def transcript_ws(ws: WebSocket, client_id: str = Query("default")) -> None:
        session = state.session(client_id)
        await ws.accept()
        session.transcript_sockets.add(ws)
        await ws.send_json({"type": "status", "data": _session_info(session)})
        try:
            while True:
                message = await ws.receive_json()
                if isinstance(message, dict) and message.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            session.transcript_sockets.discard(ws)

    @app.websocket("/ws/audio/{client_id}")
    async def audio_ws(
        ws: WebSocket, client_id: str, source: str = Query("mic")
    ) -> None:
        session = state.session(client_id)
        await ws.accept()
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break

                if message.get("text"):
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        data = {}

                    if data.get("type") == "start":
                        info = await state.start(
                            session,
                            source=source,
                            session_name=str(data.get("session_name") or "mock"),
                        )
                        await ws.send_json(
                            {"type": "started", "session_id": info["session_id"]}
                        )
                    elif data.get("type") == "stop":
                        await state.stop(session)
                        await ws.send_json({"type": "stopped"})
                    elif data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})

                elif message.get("bytes"):
                    # Binary audio frames are accepted but intentionally ignored.
                    await asyncio.sleep(0)
        except WebSocketDisconnect:
            pass

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mock Transcriber backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
