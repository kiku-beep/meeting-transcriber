"""Live topic-tree retrieval and refresh API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel

from backend.core.topic_tracker import REFRESH_UPDATED
from backend.core.topic_tree import tree_to_dict
from backend.models.schemas import SessionStatus
from backend.models.session import get_or_create_session, get_session
from backend.storage.file_store import load_topics

router = APIRouter(prefix="/api/topics", tags=["topics"])
_topic_busy_clients: set[str] = set()


class TopicRefreshRequest(BaseModel):
    client_id: str = "default"


def _get_client_session(client_id: str):
    normalized = client_id.strip() or "default"
    if normalized == "default":
        return get_session()
    return get_or_create_session(normalized)


def _empty_tree() -> dict:
    return {"nodes": [], "active": None}


@router.get("")
async def get_topics(client_id: str = Query("default")):
    """Return the current live tree, or an empty tree when no session runs."""
    session = _get_client_session(client_id)
    if session is None or session.status not in (SessionStatus.RUNNING, SessionStatus.PAUSED):
        return _empty_tree()
    return tree_to_dict(session.topic_tree)


@router.get("/session/{session_id}")
async def get_saved_topics(session_id: str):
    """Return the topic tree saved with a finished session.

    live の GET "" とパスが衝突しないよう /session/ 配下に置く。
    保存が無い会議（機能OFFで録った会議）は404で「無い」と伝える。
    """
    try:
        tree = load_topics(session_id)
    except ValueError as exc:
        # パストラバーサル等の不正idは500ではなく400で返す。
        raise HTTPException(400, "不正なセッションIDです") from exc
    if not tree.get("nodes"):
        raise HTTPException(404, "この会議に論点ツリーは保存されていません")
    return {"session_id": session_id, "tree": tree}


@router.post("/refresh")
async def refresh_topics(
    req: TopicRefreshRequest | None = Body(default=None),
    client_id: str | None = Query(default=None),
):
    """Refresh the live tree once without waiting for its periodic interval."""
    requested_client_id = client_id
    if requested_client_id is None:
        requested_client_id = req.client_id if req is not None else "default"
    normalized_client_id = requested_client_id.strip() or "default"
    if normalized_client_id in _topic_busy_clients:
        raise HTTPException(409, "論点ツリー更新を実行中です")

    session = _get_client_session(normalized_client_id)
    _topic_busy_clients.add(normalized_client_id)
    try:
        # status は refresh_now が返す理由（updated / no_new_entries / busy /
        # disabled）。機能OFFも200で返すが、画面が「更新なし」と誤解しないよう
        # 理由をそのまま渡す。LLM失敗はここに来ず例外になる。
        status = await session._topic_tracker.refresh_now()
    except Exception as exc:
        # Match /api/summary/live: provider failures are server errors with context.
        raise HTTPException(500, f"論点ツリー更新に失敗しました: {exc}") from exc
    finally:
        _topic_busy_clients.discard(normalized_client_id)

    return {
        "updated": status == REFRESH_UPDATED,
        "status": status,
        "tree": tree_to_dict(session.topic_tree),
    }
