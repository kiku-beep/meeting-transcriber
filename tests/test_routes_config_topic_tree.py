"""Tests for the topic-tree configuration route."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch):
    from backend.api import routes_config

    written: dict[str, str] = {}
    # 実際の .env（%APPDATA%）を書き換えないよう差し替える。
    monkeypatch.setattr(
        routes_config, "update_env_file", lambda key, value: written.__setitem__(key, value)
    )

    app = FastAPI()
    app.include_router(routes_config.router)
    return TestClient(app), written


def test_get_topic_tree_config_returns_current_values(monkeypatch):
    from backend.api import routes_config

    client, _ = _client(monkeypatch)
    monkeypatch.setattr(routes_config.settings, "topic_tree_enabled", True)
    monkeypatch.setattr(routes_config.settings, "topic_tree_interval_s", 120.0)
    monkeypatch.setattr(routes_config.settings, "topic_tree_codex_reasoning_effort", "high")

    response = client.get("/api/config/topic-tree")

    assert response.status_code == 200
    assert response.json() == {
        "topic_tree_enabled": True,
        "topic_tree_interval_s": 120.0,
        "topic_tree_codex_reasoning_effort": "high",
    }


def test_put_topic_tree_config_persists_both_keys(monkeypatch):
    from backend.api import routes_config

    client, written = _client(monkeypatch)
    monkeypatch.setattr(routes_config.settings, "topic_tree_enabled", False)
    monkeypatch.setattr(routes_config.settings, "topic_tree_interval_s", 90.0)

    response = client.put(
        "/api/config/topic-tree",
        json={"topic_tree_enabled": True, "topic_tree_interval_s": 180},
    )

    assert response.status_code == 200
    assert response.json()["topic_tree_enabled"] is True
    assert response.json()["topic_tree_interval_s"] == 180
    assert written["TOPIC_TREE_ENABLED"] == "true"
    assert written["TOPIC_TREE_INTERVAL_S"] == "180.0"


def test_put_topic_tree_config_rejects_interval_below_one_update(monkeypatch):
    """1回の更新に20〜35秒かかるため、30秒未満は常に busy になり無意味。"""
    from backend.api import routes_config

    client, written = _client(monkeypatch)
    monkeypatch.setattr(routes_config.settings, "topic_tree_interval_s", 90.0)

    response = client.put("/api/config/topic-tree", json={"topic_tree_interval_s": 5})

    assert response.status_code == 400
    assert "TOPIC_TREE_INTERVAL_S" not in written
    assert routes_config.settings.topic_tree_interval_s == 90.0


def test_put_topic_tree_config_persists_reasoning_effort(monkeypatch):
    from backend.api import routes_config

    client, written = _client(monkeypatch)
    monkeypatch.setattr(routes_config.settings, "topic_tree_codex_reasoning_effort", "low")

    response = client.put(
        "/api/config/topic-tree",
        json={"topic_tree_codex_reasoning_effort": "high"},
    )

    assert response.status_code == 200
    assert response.json()["topic_tree_codex_reasoning_effort"] == "high"
    assert routes_config.settings.topic_tree_codex_reasoning_effort == "high"
    assert written["TOPIC_TREE_CODEX_REASONING_EFFORT"] == "high"


def test_put_topic_tree_config_rejects_invalid_reasoning_effort_without_mutating(monkeypatch):
    from backend.api import routes_config

    client, written = _client(monkeypatch)
    monkeypatch.setattr(routes_config.settings, "topic_tree_codex_reasoning_effort", "medium")

    response = client.put(
        "/api/config/topic-tree",
        json={"topic_tree_codex_reasoning_effort": "invalid"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "推論レベルは low / medium / high / xhigh / max のいずれかで指定してください"
    )
    assert routes_config.settings.topic_tree_codex_reasoning_effort == "medium"
    assert "TOPIC_TREE_CODEX_REASONING_EFFORT" not in written
