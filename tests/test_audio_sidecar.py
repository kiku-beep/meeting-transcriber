import json

import audio_sidecar.main as sidecar


def test_start_ws_reader_drains_incoming_frames():
    sidecar._stop.clear()

    class FakeWebSocket:
        def __init__(self):
            self.recv_calls = 0

        def recv(self):
            self.recv_calls += 1
            if self.recv_calls == 1:
                return json.dumps({"type": "pong"})
            raise RuntimeError("closed")

    ws = FakeWebSocket()

    thread = sidecar.start_ws_reader(ws, "mic")
    thread.join(timeout=1)
    sidecar._stop.set()

    assert not thread.is_alive()
    assert ws.recv_calls == 2

    sidecar._stop.clear()


def test_send_stop_does_not_wait_for_response():
    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.recv_called = False

        def send(self, message):
            self.sent.append(message)

        def recv(self):
            self.recv_called = True
            raise AssertionError("stop response should be handled by the reader")

    ws = FakeWebSocket()

    sidecar.send_stop_if_needed(ws, "mic")

    assert json.loads(ws.sent[0]) == {"type": "stop"}
    assert ws.recv_called is False
