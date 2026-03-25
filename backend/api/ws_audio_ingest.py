"""WebSocket endpoint for receiving remote audio from client-side capture.

Clients (Tauri app with audio sidecar) capture audio locally via WASAPI
and stream PCM16 data to this endpoint. The server feeds it into the
transcription pipeline (AudioBuffer.feed) just like local capture would.

Wire protocol:
  - Binary frames: PCM16LE, 16kHz, mono (raw Int16 samples)
  - JSON control frames:
    {"type": "start", "session_name": "...", "source": "mic"|"loopback"}
    {"type": "stop"}
    {"type": "config", "sample_rate": 16000}
"""

from __future__ import annotations

import asyncio
import json
import logging

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from backend.config import settings
from backend.models.session import get_or_create_session, get_session, remove_session
from backend.models.schemas import SessionStatus

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/audio/{client_id}")
async def ws_audio_ingest(ws: WebSocket, client_id: str, source: str = Query("mic")):
    """Receive audio stream from a remote client.

    Args:
        client_id: Unique client identifier
        source: "mic" or "loopback" — which buffer to feed
    """
    # Auth check
    if settings.auth_token:
        # Check token from query param or first message
        token = ws.query_params.get("token", "")
        if token != settings.auth_token:
            await ws.close(code=4001, reason="Unauthorized")
            return

    await ws.accept()
    logger.info("Audio ingest connected: client=%s source=%s", client_id, source)

    session = get_or_create_session(client_id)
    is_loopback = source == "loopback"

    # Pick the right buffer
    buffer = session._loopback_buffer if is_loopback else session._mic_buffer
    recorded_list = (
        session._recorded_loopback if is_loopback else session._recorded_audio
    )

    try:
        while True:
            message = await ws.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # Binary frame: raw PCM16LE audio
            if "bytes" in message and message["bytes"]:
                raw_bytes = message["bytes"]
                # Convert PCM16LE to float32 [-1, 1]
                int16_data = np.frombuffer(raw_bytes, dtype=np.int16)
                float32_data = int16_data.astype(np.float32) / 32768.0

                buffer.feed(float32_data)
                if recorded_list is not None:
                    recorded_list.append(float32_data.copy())

            # Text frame: JSON control message
            elif "text" in message and message["text"]:
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "start":
                    session_name = msg.get("session_name", "")
                    if session.status == SessionStatus.IDLE:
                        # Start session in server mode (no local audio)
                        await _start_server_session(session, client_id, session_name)
                        await ws.send_json({"type": "started", "session_id": session.session_id})

                elif msg_type == "stop":
                    if session.status in (SessionStatus.RUNNING, SessionStatus.PAUSED):
                        await session.stop()
                        await ws.send_json({"type": "stopped"})

                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Audio ingest error for client %s", client_id)
    finally:
        logger.info("Audio ingest disconnected: client=%s source=%s", client_id, source)


async def _start_server_session(
    session, client_id: str, session_name: str
) -> None:
    """Start a transcription session in server mode (no local audio devices)."""
    from datetime import datetime

    session.status = SessionStatus.STARTING
    session.session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S") + f"_{client_id}"
    session.session_name = session_name
    session.started_at = datetime.now()
    session.entries.clear()
    session._entry_embeddings.clear()
    session._entry_audio.clear()
    session._cluster_manager.reset()
    session._recorded_audio.clear()
    session._recorded_audio_raw.clear()
    session._recorded_loopback.clear()
    session._stop_event.clear()

    # Load models if needed
    if not session._transcriber.is_loaded or not session._diarizer.is_loaded:
        logger.info("Loading models for client %s...", client_id)
        session._mic_buffer.load_model()
        loop = asyncio.get_event_loop()
        loads = [
            loop.run_in_executor(None, session._transcriber.load_model),
            loop.run_in_executor(None, session._diarizer.load_model),
        ]
        if settings.segmentation_refine_enabled and not session._refiner.is_loaded:
            loads.append(loop.run_in_executor(None, session._refiner.load_model))
        await asyncio.gather(*loads)
    else:
        session._mic_buffer.load_model()

    session._transcriber.build_vocab_hints()

    # Mark loopback as available (client may stream it)
    session._has_loopback = True
    session._loopback_buffer.load_model()

    # Start mic buffer session
    session._mic_buffer.start_session()
    session._loopback_buffer.start_session()

    # Configure and start pipeline
    session._pipeline.configure(
        session.session_id, session.session_name,
        session.started_at, session._has_loopback,
    )
    session._pipeline_task = asyncio.create_task(session._pipeline.run())

    # Start segmentation refinement
    if settings.segmentation_refine_enabled and session._refiner.is_loaded:
        session._refiner_task = asyncio.create_task(
            session._refiner.run(
                session._stop_event,
                session._recorded_audio,
                session.entries,
                session._entry_embeddings,
                session._cluster_manager,
                session._new_entry_event,
            )
        )

    # Start text refinement
    session._text_refiner.start(session.entries)

    session.status = SessionStatus.RUNNING
    logger.info("Server-mode session %s started for client %s", session.session_id, client_id)
