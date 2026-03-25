"""WebSocket endpoint for real-time transcription streaming."""

from __future__ import annotations

import asyncio
import json
import math
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from backend.models.session import get_session, get_or_create_session
from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_clients: set[WebSocket] = set()


def _sanitize_entry(entry) -> dict:
    """Build a JSON-safe dict from a TranscriptEntry, handling NaN/Inf."""
    def _safe_float(v: float) -> float:
        if math.isfinite(v):
            return v
        return 0.0

    return {
        "id": entry.id,
        "text": entry.text,
        "raw_text": entry.raw_text,
        "speaker_name": entry.speaker_name,
        "speaker_id": entry.speaker_id,
        "speaker_confidence": _safe_float(float(entry.speaker_confidence)),
        "timestamp_start": _safe_float(float(entry.timestamp_start)),
        "timestamp_end": _safe_float(float(entry.timestamp_end)),
        "refined": getattr(entry, "refined", False),
    }


@router.websocket("/ws/transcript")
async def ws_transcript(ws: WebSocket, client_id: str = Query("default")):
    await ws.accept()
    _clients.add(ws)
    logger.info("WebSocket client connected (%d total, client=%s)", len(_clients), client_id)

    # In server mode, use client-specific session; in standalone, use default
    if settings.deployment_mode == "server" and client_id != "default":
        session = get_or_create_session(client_id)
    else:
        session = get_session()
    last_index = 0
    last_status: dict | None = None

    # Background task: drain incoming messages (ping → pong, others ignored).
    # Runs concurrently so that incoming data doesn't pile up in the ASGI
    # receive queue, and to detect client disconnect promptly.
    incoming: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _reader():
        try:
            while True:
                data = await ws.receive_json()
                await incoming.put(data)
        except (WebSocketDisconnect, Exception):
            await incoming.put(None)  # sentinel: connection lost

    reader_task = asyncio.create_task(_reader())

    try:
        while True:
            # --- Process any received messages (non-blocking) ---
            while not incoming.empty():
                msg = incoming.get_nowait()
                if msg is None:
                    # Client disconnected — detected by reader
                    raise WebSocketDisconnect()
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

            # --- Send any new entries ---
            entries = session.entries
            current_len = len(entries)

            # Detect session reset (entries were cleared for a new session)
            if current_len < last_index:
                last_index = 0
                await ws.send_json({"type": "clear"})
                logger.info("WS: session reset detected, sent clear")

            if current_len > last_index:
                batch = entries[last_index:current_len]
                for entry in batch:
                    await ws.send_json({
                        "type": "entry",
                        "data": _sanitize_entry(entry),
                    })
                logger.info("WS: sent %d entries (index %d→%d)",
                            len(batch), last_index, current_len)
                last_index = current_len
            elif current_len == last_index and current_len > 0 and session._new_entry_event.is_set():
                # Entries were modified in-place (e.g., cluster merge) — ask frontend to refresh
                await ws.send_json({"type": "refresh"})
                logger.info("WS: sent refresh (entry labels updated)")

            # --- Send refined text updates ---
            try:
                updates = session.refined_queue.get_nowait()
                await ws.send_json({"type": "update", "data": updates})
            except asyncio.QueueEmpty:
                pass

            # --- Send status only when changed ---
            current_status = session.info
            if current_status != last_status:
                await ws.send_json({
                    "type": "status",
                    "data": current_status,
                })
                last_status = current_status

            # --- Wait for new entry event OR timeout ---
            session._new_entry_event.clear()
            try:
                await asyncio.wait_for(session._new_entry_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        reader_task.cancel()
        _clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(_clients))
