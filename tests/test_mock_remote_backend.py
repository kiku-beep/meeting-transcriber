import json

from fastapi.testclient import TestClient

from scripts.mock_remote_backend import create_app


def test_mock_backend_health_endpoint():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mock": True}


def test_mock_backend_audio_start_broadcasts_fake_transcript_entry():
    client = TestClient(create_app())

    with client.websocket_connect("/ws/transcript?client_id=mac-client") as transcript_ws:
        initial = transcript_ws.receive_json()
        assert initial["type"] == "status"
        assert initial["data"]["status"] == "idle"

        with client.websocket_connect("/ws/audio/mac-client?source=mic") as audio_ws:
            audio_ws.send_text(json.dumps({"type": "start", "session_name": "mock"}))

            started = audio_ws.receive_json()
            status = transcript_ws.receive_json()
            entry = transcript_ws.receive_json()

        assert started["type"] == "started"
        assert status["type"] == "status"
        assert status["data"]["status"] == "running"
        assert entry["type"] == "entry"
        assert "mock backend" in entry["data"]["text"]


def test_mock_backend_rest_start_broadcasts_for_localhost_smoke_test():
    client = TestClient(create_app())

    with client.websocket_connect("/ws/transcript?client_id=mac-client") as transcript_ws:
        transcript_ws.receive_json()

        response = client.post(
            "/api/session/start?client_id=mac-client",
            json={"session_name": "localhost-smoke"},
        )

        assert response.status_code == 200
        status = transcript_ws.receive_json()
        entry = transcript_ws.receive_json()

    assert response.json()["session_name"] == "localhost-smoke"
    assert status["data"]["status"] == "running"
    assert entry["type"] == "entry"


def test_mock_backend_supports_settings_screen_read_endpoints():
    client = TestClient(create_app())

    expected_ok_paths = [
        "/api/health/gpu",
        "/api/audio/devices",
        "/api/speakers",
        "/api/config/status",
        "/api/config/meeting",
        "/api/config/screenshots",
        "/api/session/model",
        "/api/session/model/loading-status",
        "/api/summary/models",
        "/api/summary/engines",
        "/api/call-detection/pending",
    ]

    for path in expected_ok_paths:
        response = client.get(path)
        assert response.status_code == 200, path


def test_mock_backend_generates_live_ai_response_for_client_session():
    client = TestClient(create_app())
    client.post(
        "/api/session/start?client_id=mac-live",
        json={"session_name": "live-ai-test"},
    )

    response = client.post(
        "/api/summary/live",
        json={
            "client_id": "mac-live",
            "mode": "question",
            "range_minutes": 15,
            "question": "何を受信した？",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "question"
    assert body["range_minutes"] == 15
    assert body["entry_count"] == 1
    assert body["usage"]["model"] == "mock"
