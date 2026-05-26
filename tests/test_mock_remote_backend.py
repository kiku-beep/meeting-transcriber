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
