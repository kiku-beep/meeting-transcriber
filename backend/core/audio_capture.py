"""Audio device enumeration and capture using PyAudioWPatch (WASAPI)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pyaudiowpatch as pyaudio

logger = logging.getLogger(__name__)


@dataclass
class AudioDevice:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    default_sample_rate: float
    is_loopback: bool


def list_audio_devices() -> list[AudioDevice]:
    """Enumerate all available input devices including WASAPI loopback."""
    p = pyaudio.PyAudio()
    devices: list[AudioDevice] = []

    try:
        host_apis = {
            i: p.get_host_api_info_by_index(i)["name"]
            for i in range(p.get_host_api_count())
        }

        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] <= 0:
                continue

            is_loopback = info.get("isLoopbackDevice", False)

            devices.append(
                AudioDevice(
                    index=info["index"],
                    name=info["name"],
                    host_api=host_apis.get(info["hostApi"], "Unknown"),
                    max_input_channels=info["maxInputChannels"],
                    default_sample_rate=info["defaultSampleRate"],
                    is_loopback=is_loopback,
                )
            )
    finally:
        p.terminate()

    return devices


def get_default_microphone() -> AudioDevice | None:
    """Get the default WASAPI microphone device."""
    p = pyaudio.PyAudio()
    try:
        wasapi_index = _find_wasapi_host_api(p)
        if wasapi_index is None:
            return None

        wasapi_info = p.get_host_api_info_by_index(wasapi_index)
        default_idx = wasapi_info.get("defaultInputDevice", -1)
        if default_idx < 0:
            return None

        info = p.get_device_info_by_index(default_idx)
        return AudioDevice(
            index=info["index"],
            name=info["name"],
            host_api="Windows WASAPI",
            max_input_channels=info["maxInputChannels"],
            default_sample_rate=info["defaultSampleRate"],
            is_loopback=False,
        )
    except Exception:
        logger.exception("Failed to get default microphone")
        return None
    finally:
        p.terminate()


def get_default_loopback() -> AudioDevice | None:
    """Get the default WASAPI loopback device (system audio)."""
    p = pyaudio.PyAudio()
    try:
        wasapi_index = _find_wasapi_host_api(p)
        if wasapi_index is None:
            return None

        wasapi_info = p.get_host_api_info_by_index(wasapi_index)
        default_output_idx = wasapi_info.get("defaultOutputDevice", -1)
        if default_output_idx < 0:
            return None

        default_output = p.get_device_info_by_index(default_output_idx)

        # Find the loopback device corresponding to the default output
        for loopback in p.get_loopback_device_info_generator():
            if loopback["name"].startswith(default_output["name"]):
                return AudioDevice(
                    index=loopback["index"],
                    name=loopback["name"],
                    host_api="Windows WASAPI",
                    max_input_channels=loopback["maxInputChannels"],
                    default_sample_rate=loopback["defaultSampleRate"],
                    is_loopback=True,
                )

        return None
    except Exception:
        logger.exception("Failed to get default loopback device")
        return None
    finally:
        p.terminate()


def _find_wasapi_host_api(p: pyaudio.PyAudio) -> int | None:
    """Find the WASAPI host API index."""
    for i in range(p.get_host_api_count()):
        info = p.get_host_api_info_by_index(i)
        if "WASAPI" in info.get("name", ""):
            return i
    return None
