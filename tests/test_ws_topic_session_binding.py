"""WSとRESTが同じセッションへ束ねられていることの回帰テスト。

standalone では WS だけが `deployment_mode == "server"` を条件に既定セッションへ
固定されていた。UIは localStorage が空なら `mac_<ts>_<rand>` の client_id を必ず
自動生成するため、実運用では

  - 録音と周期的な論点更新 → client セッション（RESTが解決）
  - WSの配信元                → 既定セッション

に分かれ、周期更新の topic が画面へ一度も届かなかった。手動更新ボタンだけは
REST の応答本文でツリーが返るため動いて見え、原因が隠れる。

判定は「受信メッセージを待つ」ではなく「WSがどちらのキューを飲んだか」で行う。
受信待ちにすると、壊れている側では配信が来ないまま receive_json が永久に
ブロックし、テストが失敗ではなくハングして回帰テストの役に立たない。
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import ws_transcription
from backend.models import session as session_mod
from backend.models.schemas import SessionStatus

DRAIN_TIMEOUT_S = 5.0


def reset_registry(monkeypatch):
    default = session_mod.TranscriptionSession()
    monkeypatch.setattr(session_mod, "_default_session", default)
    monkeypatch.setattr(session_mod, "_sessions", {"default": default})
    monkeypatch.setattr(session_mod, "_client_connections", {})
    return default


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_transcription.router)
    return app


def sample_tree() -> dict:
    return {
        "nodes": [{
            "id": "t1", "parent": None, "kind": "question",
            "label": "自動更新の確認", "status": "open",
            "start_sec": 0.0, "end_sec": 1.0,
        }],
        "links": [],
        "active": "t1",
        "error": None,
    }


def wait_until_drained(queue) -> bool:
    deadline = time.monotonic() + DRAIN_TIMEOUT_S
    while time.monotonic() < deadline:
        if queue.empty():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("deployment_mode", ["standalone", "server"])
def test_ws_drains_client_session_topic_queue(monkeypatch, deployment_mode):
    """deployment_mode に関わらず、REST と同じ client セッションへ繋ぐ。"""
    default = reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "deployment_mode", deployment_mode)

    client_id = "mac_1788400000_abcdef12"
    client_session = session_mod.get_or_create_session(client_id)
    client_session.status = SessionStatus.RUNNING
    assert client_session is not default

    # 周期更新が積んだ topic を client セッション側のキューへ入れる。
    client_session.topic_queue.put_nowait(sample_tree())
    default.topic_queue.put_nowait(sample_tree())

    with TestClient(make_app()).websocket_connect(f"/ws/transcript?client_id={client_id}"):
        drained = wait_until_drained(client_session.topic_queue)

    assert drained, "WSが client セッションの topic を飲まなかった（既定セッションに繋いでいる）"
    # 既定セッション側は触られていないこと（取り違えの逆方向も検出する）。
    assert not default.topic_queue.empty()


def test_ws_drains_default_session_for_default_client_id(monkeypatch):
    """client_id が default のときは従来どおり既定セッションを使う。"""
    default = reset_registry(monkeypatch)
    monkeypatch.setattr(session_mod.settings, "deployment_mode", "standalone")
    default.status = SessionStatus.RUNNING
    default.topic_queue.put_nowait(sample_tree())

    with TestClient(make_app()).websocket_connect("/ws/transcript?client_id=default"):
        drained = wait_until_drained(default.topic_queue)

    assert drained
    assert list(session_mod._sessions) == ["default"]


def test_rest_and_ws_share_the_same_named_session(monkeypatch):
    from backend.api.routes_session import get_client_session

    reset_registry(monkeypatch)
    client_id = "shared-client"
    rest_session = get_client_session(client_id)
    rest_session.status = SessionStatus.RUNNING
    rest_session.topic_queue.put_nowait(sample_tree())

    with TestClient(make_app()).websocket_connect(f"/ws/transcript?client_id={client_id}"):
        drained = wait_until_drained(rest_session.topic_queue)

    assert drained
    assert session_mod.get_session(client_id) is rest_session
