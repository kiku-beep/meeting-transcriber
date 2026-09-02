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
                "status": "open",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ],
        "active": "topic-1",
    }


def test_get_topics_returns_empty_tree_when_session_is_not_running(monkeypatch):
    from backend.api import routes_topics

    monkeypatch.setattr(routes_topics, "get_session", lambda: _session(_tree(), status="idle"))

    response = _client().get("/api/topics")

    assert response.status_code == 200
    assert response.json() == {"nodes": [], "active": None}


def test_refresh_topics_calls_tracker(monkeypatch):
    from backend.api import routes_topics

    calls = 0

    class FakeTracker:
        tree = _tree()

        async def refresh_now(self):
            nonlocal calls
            calls += 1
            return True

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "refresh-client"})

    assert response.status_code == 200
    assert calls == 1
    assert response.json()["updated"] is True
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
            return False

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "no-op-client"})

    assert response.status_code == 200
    assert response.json() == {"updated": False, "tree": {
        "nodes": [
            {
                "id": "topic-1",
                "parent": None,
                "label": "価格",
                "status": "open",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ],
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
            return False

    session = _session(tracker=FakeTracker())
    monkeypatch.setattr(routes_topics, "get_session", lambda: session)
    monkeypatch.setattr(routes_topics, "get_or_create_session", lambda client_id: session)

    response = _client().post("/api/topics/refresh", json={"client_id": "disabled-client"})

    assert response.status_code == 200
    assert response.json()["updated"] is False


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
