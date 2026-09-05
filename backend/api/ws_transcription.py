"""WebSocket endpoint for real-time transcription streaming."""

from __future__ import annotations

import asyncio
import json
import math
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from backend.core.topic_tree import VALID_LINK_TYPES, tree_to_dict
from backend.models.session import (
    register_client_connection,
    remove_empty_idle_client_session,
    resolve_client_session,
    unregister_client_connection,
)

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


def _sanitize_topic_tree(tree_or_payload) -> dict:
    """Build a JSON-safe topic-tree payload, handling NaN/Inf timestamps."""
    payload = (
        tree_or_payload
        if isinstance(tree_or_payload, dict)
        else tree_to_dict(tree_or_payload)
    )
    nodes = []
    for raw_node in payload.get("nodes", []):
        node = dict(raw_node)
        for key in ("start_sec", "end_sec"):
            try:
                value = float(node.get(key, 0.0))
            except (TypeError, ValueError, OverflowError):
                value = 0.0
            node[key] = value if math.isfinite(value) else 0.0
        nodes.append(node)
    node_ids = {node.get("id") for node in nodes if isinstance(node.get("id"), str)}
    raw_links = payload.get("links", [])
    links = []
    if isinstance(raw_links, list):
        for raw_link in raw_links:
            if not isinstance(raw_link, dict):
                continue
            source = raw_link.get("source")
            target = raw_link.get("target")
            if (
                isinstance(source, str)
                and isinstance(target, str)
                and source != target
                and source in node_ids
                and target in node_ids
                and raw_link.get("type") in VALID_LINK_TYPES
            ):
                links.append(dict(raw_link))
    sanitized = {"nodes": nodes, "links": links, "active": payload.get("active")}
    # 周期更新の失敗を画面へ届ける。これが無いと「論点を抽出中…」のまま
    # 会議が終わる（実機で6分間気づけなかった）。
    if "error" in payload:
        sanitized["error"] = payload["error"]
    return sanitized


@router.websocket("/ws/transcript")
async def ws_transcript(ws: WebSocket, client_id: str = Query("default")):
    await ws.accept()
    _clients.add(ws)
    logger.info("WebSocket client connected (%d total, client=%s)", len(_clients), client_id)

    # REST側（/api/session/*, /api/topics/*）は deployment_mode を見ず、
    # client_id != "default" なら常に client セッションを使う。WSだけが standalone で
    # 既定セッションに固定されていたため、UIが自動生成する client_id
    # （mac_<ts>_<rand>。localStorage が空なら必ずこの形になる）では
    # 「録音と論点更新は client セッション、WSの配信元は既定セッション」に分かれ、
    # 周期更新のtopicが画面へ一切届かなかった。手動更新だけはRESTの応答本文で
    # ツリーが返るため動いて見え、原因に気づけない。REST側の規則に合わせる。
    use_client_session = client_id != "default"

    if use_client_session:
        register_client_connection(client_id)
    session = resolve_client_session(client_id)
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

            # Initial state is fetched via GET /api/topics; WS only sends queued updates.
            try:
                topic_tree = session.topic_queue.get_nowait()
                await ws.send_json({
                    "type": "topic",
                    "data": _sanitize_topic_tree(topic_tree),
                })
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
        if use_client_session:
            unregister_client_connection(client_id)
            remove_empty_idle_client_session(client_id)
        logger.info("WebSocket client disconnected (%d remaining)", len(_clients))
