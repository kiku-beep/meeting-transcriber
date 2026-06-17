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

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
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
    saved_at: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)
    transcript_sockets: set[WebSocket] = field(default_factory=set)


class MockState:
    def __init__(self) -> None:
        self.sessions: dict[str, MockSession] = {}

    def session(self, client_id: str) -> MockSession:
        if client_id not in self.sessions:
            self.sessions[client_id] = MockSession(client_id=client_id)
        return self.sessions[client_id]

    def session_by_id(self, session_id: str) -> MockSession:
        for session in self.sessions.values():
            if session.session_id == session_id:
                return session
        raise HTTPException(status_code=404, detail="session not found")

    def transcript_sessions(self) -> list[dict[str, Any]]:
        sessions = [session for session in self.sessions.values() if session.session_id]
        sessions.sort(key=lambda session: session.started_at or "", reverse=True)
        return [
            {
                "session_id": session.session_id,
                "session_name": session.session_name,
                "started_at": session.started_at,
                "saved_at": session.saved_at,
                "entry_count": len(session.entries),
                "screenshot_count": 0,
                "total_size_bytes": 0,
                "is_favorite": False,
                "folder": "",
            }
            for session in sessions
        ]

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
        session.saved_at = datetime.now().isoformat()
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

    @app.get("/api/config/status")
    async def config_status() -> dict[str, Any]:
        return {
            "gemini_api_key_set": False,
            "gemini_api_key_masked": None,
            "text_refine_enabled": False,
        }

    @app.get("/api/config/meeting")
    async def meeting_config() -> dict[str, Any]:
        return {
            "call_notification_enabled": True,
            "screenshot_enabled": False,
            "audio_saving_enabled": False,
        }

    @app.get("/api/config/screenshots")
    async def screenshots_config() -> dict[str, Any]:
        return {
            "screenshot_enabled": False,
            "screenshot_interval": 10,
            "screenshot_quality": 80,
        }

    @app.get("/api/session/model")
    async def model_status() -> dict[str, Any]:
        return {
            "current_model": "mock",
            "is_loaded": True,
            "available_models": [
                {"name": "mock", "vram_mb": 0},
                {"name": "kotoba-v2.0", "vram_mb": 2500},
            ],
        }

    @app.get("/api/session/model/loading-status")
    async def model_loading_status() -> dict[str, Any]:
        return {"stage": "ready", "progress": 1.0}

    @app.get("/api/summary/models")
    async def summary_models() -> dict[str, Any]:
        return {
            "current_model": "mock",
            "models": [
                {
                    "id": "mock",
                    "label": "Mock Summary",
                    "input_price": 0,
                    "output_price": 0,
                    "speed": "very_fast",
                    "accuracy": "low",
                }
            ],
        }

    @app.get("/api/call-detection/pending")
    async def pending_calls() -> dict[str, Any]:
        return {"calls": []}

    @app.get("/api/transcripts/folders")
    async def transcript_folders() -> dict[str, Any]:
        return {"folders": []}

    @app.get("/api/transcripts")
    async def transcripts() -> dict[str, Any]:
        return {"sessions": state.transcript_sessions()}

    @app.get("/api/transcripts/{session_id}")
    async def transcript(session_id: str) -> dict[str, Any]:
        session = state.session_by_id(session_id)
        return {"session_id": session.session_id, "entries": session.entries}

    @app.get("/api/transcripts/{session_id}/export")
    async def transcript_export(
        session_id: str, format: str = Query("txt")
    ) -> Any:
        session = state.session_by_id(session_id)
        if format == "json":
            return {"session_id": session.session_id, "entries": session.entries}
        lines = [entry["text"] for entry in session.entries]
        if format == "md":
            text = "\n".join(f"- {line}" for line in lines)
        else:
            text = "\n".join(lines)
        return PlainTextResponse(text)

    @app.get("/api/summary/{session_id}")
    async def summary(session_id: str) -> dict[str, Any]:
        state.session_by_id(session_id)
        return {"session_id": session_id, "summary": ""}

    @app.post("/api/summary/generate")
    async def generate_summary(
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "")
        session = state.session_by_id(session_id)
        summary = f"Mock summary for {session.session_name or session.session_id}"
        return {
            "session_id": session.session_id,
            "summary": summary,
            "model": "mock",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0,
            },
        }

    @app.get("/api/playback/{session_id}/audio/info")
    async def audio_info(session_id: str) -> dict[str, Any]:
        state.session_by_id(session_id)
        return {
            "has_audio": False,
            "format": None,
            "duration_seconds": None,
            "file_size_bytes": None,
        }

    @app.post("/api/playback/{session_id}/compress")
    async def compress_audio(session_id: str) -> dict[str, Any]:
        state.session_by_id(session_id)
        return {"status": "no_audio", "session_id": session_id}

    @app.get("/api/screenshots/{session_id}")
    async def screenshots(session_id: str) -> dict[str, Any]:
        state.session_by_id(session_id)
        return {"session_id": session_id, "screenshots": []}

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
