"""Audio capture sidecar for Transcriber client.

Captures microphone and/or system audio (WASAPI loopback) on the local PC
and streams PCM16 data to the remote transcription server via WebSocket.

Usage:
    python main.py --server ws://192.168.1.100:8000 --client-id my-pc
    python main.py --server ws://192.168.1.100:8000 --client-id my-pc --list-devices
    python main.py --server ws://192.168.1.100:8000 --client-id my-pc --mic 1 --loopback 5

When packaged with PyInstaller:
    audio_sidecar.exe --server ws://192.168.1.100:8000 --client-id my-pc
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from math import gcd

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("audio_sidecar")

# Global stop flag
_stop = threading.Event()


def list_devices():
    """Print all audio devices and exit."""
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()
    print("\n=== Audio Devices ===")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        direction = []
        if dev["maxInputChannels"] > 0:
            direction.append("IN")
        if dev["maxOutputChannels"] > 0:
            direction.append("OUT")
        is_loopback = dev.get("isLoopbackDevice", False)
        lb_tag = " [LOOPBACK]" if is_loopback else ""
        print(
            f"  [{i}] {dev['name']} ({'/'.join(direction)}) "
            f"- {int(dev['defaultSampleRate'])}Hz, "
            f"{dev['maxInputChannels']}ch{lb_tag}"
        )
    p.terminate()


def get_default_devices():
    """Find default WASAPI mic and loopback devices."""
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()

    mic_index = None
    loopback_index = None

    # Find WASAPI host API
    for i in range(p.get_host_api_count()):
        info = p.get_host_api_info_by_index(i)
        if "WASAPI" in info.get("name", ""):
            default_input = info.get("defaultInputDevice", -1)
            if default_input >= 0:
                mic_index = default_input

            default_output = info.get("defaultOutputDevice", -1)
            if default_output >= 0:
                # Find the loopback device for this output
                for j in range(p.get_device_count()):
                    dev = p.get_device_info_by_index(j)
                    if dev.get("isLoopbackDevice", False):
                        # Match by name prefix (loopback names contain output device name)
                        out_name = p.get_device_info_by_index(default_output)["name"]
                        if out_name in dev["name"]:
                            loopback_index = j
                            break
            break

    p.terminate()
    return mic_index, loopback_index


def resample_to_16k(audio: np.ndarray, source_rate: int, source_channels: int) -> np.ndarray:
    """Convert audio to 16kHz mono float32."""
    if source_channels > 1:
        stereo = audio.reshape(-1, source_channels)
        audio = stereo[:, 0].copy()
    if source_rate != 16000:
        from scipy.signal import resample_poly

        g = gcd(16000, source_rate)
        audio = resample_poly(audio, 16000 // g, source_rate // g)
        audio = audio.astype(np.float32)
    return audio


def audio_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    """Convert float32 audio [-1, 1] to PCM16LE bytes."""
    int16 = np.clip(audio * 32768, -32768, 32767).astype(np.int16)
    return int16.tobytes()


def stream_audio(
    ws_url: str,
    client_id: str,
    source: str,
    device_index: int,
    token: str = "",
    session_name: str = "",
):
    """Capture audio from a device and stream via WebSocket.

    This runs in its own thread.
    """
    import pyaudiowpatch as pyaudio
    import websocket

    # Build WebSocket URL
    params = f"source={source}"
    if token:
        params += f"&token={token}"
    url = f"{ws_url}/ws/audio/{client_id}?{params}"

    logger.info("Connecting to %s (device=%d, source=%s)", ws_url, device_index, source)

    ws = None
    try:
        ws = websocket.create_connection(
            url,
            timeout=10,
            header={"Origin": f"http://{ws_url.split('//')[1].split('/')[0]}"},
        )
        logger.info("WebSocket connected for %s", source)

        # Send start control message (only from mic stream)
        if source == "mic":
            ws.send(json.dumps({
                "type": "start",
                "session_name": session_name,
                "source": source,
            }))
            resp = ws.recv()
            logger.info("Start response: %s", resp)

        p = pyaudio.PyAudio()
        dev_info = p.get_device_info_by_index(device_index)
        sample_rate = int(dev_info["defaultSampleRate"])
        channels = min(int(dev_info["maxInputChannels"]), 2)
        frames_per_buffer = sample_rate // 10  # 100ms chunks

        logger.info(
            "Opening %s: %s (%dHz, %dch)",
            source, dev_info["name"], sample_rate, channels,
        )

        cb_count = 0

        def callback(in_data, frame_count, time_info, status):
            nonlocal cb_count
            if _stop.is_set():
                return (None, pyaudio.paComplete)

            raw = np.frombuffer(in_data, dtype=np.float32)
            audio = resample_to_16k(raw, sample_rate, channels)

            cb_count += 1
            if cb_count % 100 == 1:
                amp = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
                logger.info("%s cb #%d: len=%d, amp=%.4f", source, cb_count, len(audio), amp)

            try:
                pcm_bytes = audio_to_pcm16_bytes(audio)
                ws.send_binary(pcm_bytes)
            except Exception:
                logger.warning("Failed to send %s audio", source)
                _stop.set()

            return (None, pyaudio.paContinue)

        stream = p.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=callback,
        )
        stream.start_stream()
        logger.info("%s stream started", source)

        # Keep running until stop signal
        while not _stop.is_set():
            _stop.wait(timeout=0.5)

        stream.stop_stream()
        stream.close()
        p.terminate()

        # Send stop control message (only from mic stream)
        if source == "mic":
            try:
                ws.send(json.dumps({"type": "stop"}))
                ws.recv()
            except Exception:
                pass

    except Exception:
        logger.exception("Audio stream error (%s)", source)
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        logger.info("%s stream stopped", source)


def main():
    parser = argparse.ArgumentParser(description="Audio capture sidecar for Transcriber")
    parser.add_argument("--server", required=True, help="WebSocket server URL (e.g., ws://192.168.1.100:8000)")
    parser.add_argument("--client-id", required=True, help="Unique client identifier")
    parser.add_argument("--mic", type=int, default=None, help="Microphone device index")
    parser.add_argument("--loopback", type=int, default=None, help="Loopback device index")
    parser.add_argument("--token", default="", help="Auth token")
    parser.add_argument("--session-name", default="", help="Session name")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--no-loopback", action="store_true", help="Disable loopback capture")

    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        sys.exit(0)

    # Resolve device indices
    mic_index = args.mic
    loopback_index = args.loopback

    if mic_index is None or (loopback_index is None and not args.no_loopback):
        default_mic, default_lb = get_default_devices()
        if mic_index is None:
            mic_index = default_mic
        if loopback_index is None and not args.no_loopback:
            loopback_index = default_lb

    if mic_index is None:
        logger.error("No microphone device found")
        sys.exit(1)

    logger.info("Using mic device: %d", mic_index)
    if loopback_index is not None:
        logger.info("Using loopback device: %d", loopback_index)

    # Handle signals
    def signal_handler(sig, frame):
        logger.info("Received signal %d, stopping...", sig)
        _stop.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start audio streams
    threads = []

    mic_thread = threading.Thread(
        target=stream_audio,
        args=(args.server, args.client_id, "mic", mic_index, args.token, args.session_name),
        daemon=True,
    )
    mic_thread.start()
    threads.append(mic_thread)

    if loopback_index is not None:
        # Small delay to let mic start first and create the session
        time.sleep(1)
        lb_thread = threading.Thread(
            target=stream_audio,
            args=(args.server, args.client_id, "loopback", loopback_index, args.token),
            daemon=True,
        )
        lb_thread.start()
        threads.append(lb_thread)

    # Output ready signal for Tauri to detect
    print("SIDECAR_READY", flush=True)

    # Wait for stop
    try:
        while not _stop.is_set():
            _stop.wait(timeout=1)
    except KeyboardInterrupt:
        _stop.set()

    logger.info("Waiting for threads to finish...")
    for t in threads:
        t.join(timeout=5)

    logger.info("Audio sidecar exited")


if __name__ == "__main__":
    main()
