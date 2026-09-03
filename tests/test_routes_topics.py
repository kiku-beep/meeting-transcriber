"""Tests for the live topic-tree API routes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from backend.api.routes_topics import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _tree():
    from backend.core.topic_tree import TopicNode, TopicTree

    return TopicTree(
        nodes=[
            TopicNode(
                id="topic-1",
                label="価格",
                status="open",
                start_sec=1.0,
                end_sec=2.0,
            )
        ],
        active="topic-1",
    )


def _session(tree=None, tracker=None, status="running"):
    from backend.core.topic_tree import TopicTree

    if tracker is None:
        tree = tree or TopicTree()
        tracker = SimpleNamespace(tree=tree, topic_queue=asyncio.Queue())
    else:
        tree = tree or tracker.tree
    return SimpleNamespace(status=status, topic_tree=tree, _topic_tracker=tracker)


def test_get_topics_returns_current_tree(monkeypatch):
    from backend.api import routes_topics

    session = _session(_tree())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().get("/api/topics?client_id=topic-client")

    assert response.status_code == 200
    assert response.json() == {
        "nodes": [
            {
                "id": "topic-1",
                "parent": None,
                "label": "価格",
                "kind": "question",
                "status": "open",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ],
        "links": [],
        "active": "topic-1",
        "error": None,
    }


def test_get_topics_reports_last_periodic_failure(monkeypatch):
    """周期ループの失敗は GET でも見える（画面が「抽出中…」のまま固まらないように）。"""
    from backend.api import routes_topics

    tracker = SimpleNamespace(tree=_tree(), topic_queue=asyncio.Queue(), last_error="RuntimeError: boom")
    session = _session(tracker=tracker)
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)

    response = _client().get("/api/topics")

    assert response.status_code == 200
    assert response.json()["error"] == "RuntimeError: boom"


def test_get_topics_returns_empty_tree_when_session_is_not_running(monkeypatch):
    from backend.api import routes_topics

    monkeypatch.setattr(routes_topics, "get_session", lambda: _session(_tree(), status="idle"))

    response = _client().get("/api/topics")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "links": [], "active": None}


def test_refresh_topics_calls_tracker(monkeypatch):
    from backend.api import routes_topics

    calls = 0

    class FakeTracker:
        tree = _tree()

        async def refresh_now(self):
            nonlocal calls
            calls += 1
            return "updated"

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "refresh-client"})

    assert response.status_code == 200
    assert calls == 1
    assert response.json()["updated"] is True
    assert response.json()["status"] == "updated"
    assert response.json()["tree"]["active"] == "topic-1"


def test_refresh_topics_returns_409_for_duplicate_request(monkeypatch):
    from backend.api import routes_topics

    routes_topics._topic_busy_clients.add("busy-client")
    try:
        response = _client().post(
            "/api/topics/refresh",
            json={"client_id": "busy-client"},
        )
    finally:
        routes_topics._topic_busy_clients.discard("busy-client")

    assert response.status_code == 409


def test_refresh_topics_returns_200_when_tracker_has_nothing_to_update(monkeypatch):
    from backend.api import routes_topics

    class FakeTracker:
        tree = _tree()

        async def refresh_now(self):
            return "no_new_entries"

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "no-op-client"})

    assert response.status_code == 200
    assert response.json() == {"updated": False, "status": "no_new_entries", "tree": {
        "nodes": [
            {
                "id": "topic-1",
                "parent": None,
                "label": "価格",
                "kind": "question",
                "status": "open",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ],
        "links": [],
        "active": "topic-1",
    }}


def test_refresh_topics_returns_500_when_tracker_fails(monkeypatch):
    from backend.api import routes_topics

    class FakeTracker:
        tree = _tree()

        async def refresh_now(self):
            raise RuntimeError("provider failed")

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "error-client"})

    assert response.status_code == 500
    assert "論点ツリー更新に失敗" in response.json()["detail"]


def test_refresh_topics_returns_200_noop_when_topic_tree_is_disabled(monkeypatch):
    from backend.api import routes_topics

    class FakeTracker:
        tree = _tree()
        enabled = False

        async def refresh_now(self):
            return "disabled"

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "disabled-client"})

    assert response.status_code == 200
    assert response.json()["updated"] is False
    assert response.json()["status"] == "disabled"


def test_ws_topic_payload_replaces_nonfinite_timestamps():
    from backend.api.ws_transcription import _sanitize_topic_tree

    payload = _sanitize_topic_tree({
        "nodes": [{
            "id": "topic-1",
            "parent": None,
            "label": "価格",
            "status": "open",
            "start_sec": float("nan"),
            "end_sec": float("inf"),
        }],
        "active": "topic-1",
    })

    assert payload["nodes"][0]["start_sec"] == 0.0
    assert payload["nodes"][0]["end_sec"] == 0.0


def test_ws_topic_payload_preserves_argument_links():
    from backend.api.ws_transcription import _sanitize_topic_tree

    payload = _sanitize_topic_tree({
        "nodes": [
            {"id": "question", "parent": None, "label": "問い", "start_sec": 0, "end_sec": 1},
            {"id": "claim", "parent": None, "label": "案", "start_sec": 1, "end_sec": 2},
        ],
        "links": [{"source": "claim", "target": "question", "type": "objects"}],
        "active": "claim",
    })

    assert payload["links"] == [{"source": "claim", "target": "question", "type": "objects"}]


def test_get_saved_topics_returns_stored_tree(monkeypatch):
    from backend.api import routes_topics

    monkeypatch.setattr(
        routes_topics,
        "load_topics",
        lambda session_id: {
            "nodes": [
                {
                    "id": "t1",
                    "parent": None,
                    "label": "保存済み論点",
                    "status": "decided",
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                }
            ],
            "active": None,
        },
    )

    response = _client().get("/api/topics/session/2026-08-28_120123")

    assert response.status_code == 200
    assert response.json()["session_id"] == "2026-08-28_120123"
    assert response.json()["tree"]["nodes"][0]["label"] == "保存済み論点"


def test_get_saved_topics_returns_404_when_nothing_was_saved(monkeypatch):
    """機能OFFで録った会議には topics.json が無い。空ツリーではなく404で伝える。"""
    from backend.api import routes_topics

    monkeypatch.setattr(
        routes_topics, "load_topics", lambda session_id: {"nodes": [], "active": None}
    )

    response = _client().get("/api/topics/session/2026-01-01_000000")

    assert response.status_code == 404


def test_get_saved_topics_rejects_path_traversal(monkeypatch):
    from backend.api import routes_topics

    def raising_load(session_id: str):
        raise ValueError(f"Invalid session_id: {session_id}")

    monkeypatch.setattr(routes_topics, "load_topics", raising_load)

    response = _client().get("/api/topics/session/..%2F..%2Fsecrets")

    assert response.status_code in (400, 404)
    if response.status_code == 400:
        assert "不正なセッションID" in response.json()["detail"]
