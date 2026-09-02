"""Audio stream management — PyAudio mic & loopback capture with resampling."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

from backend.core.audio_buffer import AudioBuffer
from backend.core.loopback_selector import LoopbackSourceSelector
from backend.models.schemas import SessionStatus

logger = logging.getLogger(__name__)


@dataclass
class LoopbackStreamState:
    index: int
    name: str
    sample_rate: int
    channels: int
    stream: object
    callback_count: int = 0


class AudioStreamManager:
    """Manages PyAudio streams for microphone and loopback capture."""

    def __init__(self):
        self._pa = None
        self._stream = None
        self._loopback_streams: dict[int, LoopbackStreamState] = {}

        self._device_sample_rate: int = 16000
        self._device_channels: int = 1
        self._mic_cb_count: int = 0
        self._loopback_selector = LoopbackSourceSelector()

        self._mic_buffer: AudioBuffer | None = None
        self._loopback_buffer: AudioBuffer | None = None
        self._recorded_audio: list[np.ndarray] | None = None
        self._recorded_loopback: list[np.ndarray] | None = None
        self._recorded_audio_raw: list[np.ndarray] | None = None
        self._raw_sample_rate: int = 16000
        self._get_status: Callable[[], SessionStatus] | None = None

        # Current device tracking
        self._current_mic_index: int | None = None
        self._current_mic_name: str = ""
        self._stream_lock = threading.Lock()

    @property
    def current_mic_name(self) -> str:
        return self._current_mic_name

    @property
    def current_loopback_name(self) -> str:
        with self._stream_lock:
            return " / ".join(
                state.name for state in self._loopback_streams.values()
            )

    @property
    def current_mic_index(self) -> int | None:
        return self._current_mic_index

    @property
    def current_loopback_index(self) -> int | None:
        indices = self.current_loopback_indices
        return indices[0] if indices else None

    @property
    def current_loopback_indices(self) -> tuple[int, ...]:
        with self._stream_lock:
            return tuple(self._loopback_streams)

    def setup(self, mic_buffer: AudioBuffer, loopback_buffer: AudioBuffer,
              recorded_audio: list[np.ndarray],
              get_status: Callable[[], SessionStatus],
              recorded_audio_raw: list[np.ndarray] | None = None,
              recorded_loopback: list[np.ndarray] | None = None) -> None:
        """Bind session-specific references."""
        self._mic_buffer = mic_buffer
        self._loopback_buffer = loopback_buffer
        self._recorded_audio = recorded_audio
        self._recorded_loopback = recorded_loopback
        self._recorded_audio_raw = recorded_audio_raw
        self._get_status = get_status

    def reset_counters(self) -> None:
        self._mic_cb_count = 0
        for state in self._loopback_streams.values():
            state.callback_count = 0
        self._loopback_selector.reset()

    def _ensure_pyaudio(self):
        """Ensure a shared PyAudio instance is available (reused across sessions)."""
        import pyaudiowpatch as pyaudio

        if self._pa is None:
            self._pa = pyaudio.PyAudio()
        return self._pa

    def _recreate_pyaudio(self):
        """Terminate and recreate PyAudio to refresh device list."""
        import pyaudiowpatch as pyaudio

        if self._pa:
            self._pa.terminate()
        self._pa = pyaudio.PyAudio()
        return self._pa

    def open_mic_stream(self, device_index: int | None) -> None:
        """Open a PyAudioWPatch input stream for microphone."""
        import pyaudiowpatch as pyaudio

        p = self._ensure_pyaudio()

        if device_index is not None:
            dev_info = p.get_device_info_by_index(device_index)
        else:
            for i in range(p.get_host_api_count()):
                info = p.get_host_api_info_by_index(i)
                if "WASAPI" in info.get("name", ""):
                    default_idx = info.get("defaultInputDevice", -1)
                    if default_idx >= 0:
                        dev_info = p.get_device_info_by_index(default_idx)
                        break
            else:
                dev_info = p.get_default_input_device_info()

        self._device_sample_rate = int(dev_info["defaultSampleRate"])
        self._device_channels = min(int(dev_info["maxInputChannels"]), 2)
        self._current_mic_index = dev_info["index"]
        self._current_mic_name = dev_info["name"]

        logger.info(
            "Opening mic: %s (%dHz, %dch)",
            dev_info["name"],
            self._device_sample_rate,
            self._device_channels,
        )

        frames_per_buffer = self._device_sample_rate // 10

        self._stream = p.open(
            format=pyaudio.paFloat32,
            channels=self._device_channels,
            rate=self._device_sample_rate,
            input=True,
            input_device_index=dev_info["index"],
            frames_per_buffer=frames_per_buffer,
            stream_callback=self._audio_callback,
        )
        self._stream.start_stream()

    def open_loopback_stream(self, loopback_device_index: int) -> None:
        """Open one WASAPI loopback without closing existing loopbacks."""
        self.open_loopback_streams([loopback_device_index])

    def open_loopback_streams(self, device_indices: list[int]) -> list[int]:
        """Open all requested loopbacks independently."""
        with self._stream_lock:
            self._open_loopback_streams_unlocked(device_indices)
            return list(self._loopback_streams)

    def _open_loopback_streams_unlocked(self, device_indices: list[int]) -> None:
        for device_index in dict.fromkeys(device_indices):
            if device_index in self._loopback_streams:
                continue
            try:
                self._open_loopback_stream_unlocked(device_index)
            except Exception:
                logger.warning(
                    "Failed to open loopback device %s",
                    device_index,
                    exc_info=True,
                )

    def _open_loopback_stream_unlocked(self, loopback_device_index: int) -> None:
        import pyaudiowpatch as pyaudio

        p = self._ensure_pyaudio()
        dev_info = p.get_device_info_by_index(loopback_device_index)

        sample_rate = int(dev_info["defaultSampleRate"])
        channels = min(int(dev_info["maxInputChannels"]), 2)
        device_index = int(dev_info["index"])

        logger.info(
            "Opening loopback: %s (%dHz, %dch)",
            dev_info["name"],
            sample_rate,
            channels,
        )

        frames_per_buffer = sample_rate // 10

        stream = p.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=frames_per_buffer,
            stream_callback=self._make_loopback_callback(device_index),
            start=False,
        )
        self._loopback_streams[device_index] = LoopbackStreamState(
            index=device_index,
            name=dev_info["name"],
            sample_rate=sample_rate,
            channels=channels,
            stream=stream,
        )
        try:
            stream.start_stream()
        except Exception:
            self._loopback_streams.pop(device_index, None)
            try:
                stream.close()
            except Exception:
                pass
            raise

    def sync_loopback_streams(self, device_indices: list[int]) -> list[int]:
        """Make open loopbacks match requested indices without reopening retained streams."""
        requested = list(dict.fromkeys(device_indices))
        requested_set = set(requested)
        with self._stream_lock:
            for device_index in list(self._loopback_streams):
                if device_index not in requested_set:
                    self._close_loopback_stream_unlocked(device_index)
            self._open_loopback_streams_unlocked(requested)
            return [
                device_index
                for device_index in requested
                if device_index in self._loopback_streams
            ]

    def reopen_devices(
        self,
        mic_device_index: int | None,
        loopback_device_indices: list[int],
    ) -> list[int]:
        """Safely rebuild PyAudio after a physical device-list change."""
        with self._stream_lock:
            self._close_mic_stream_unlocked()
            for device_index in list(self._loopback_streams):
                self._close_loopback_stream_unlocked(device_index)
            self._recreate_pyaudio()
            if mic_device_index is not None:
                self.open_mic_stream(mic_device_index)
            self._open_loopback_streams_unlocked(loopback_device_indices)
            return [
                device_index
                for device_index in loopback_device_indices
                if device_index in self._loopback_streams
            ]

    def switch_mic(self, new_device_index: int) -> None:
        """Hot-switch microphone stream to a different device."""
        with self._stream_lock:
            self._close_mic_stream_unlocked()
            self.open_mic_stream(new_device_index)

    def _close_mic_stream_unlocked(self) -> None:
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        self._current_mic_index = None
        self._current_mic_name = ""

    def switch_loopback(self, new_device_index: int | None) -> None:
        """Compatibility API: replace all loopbacks with one device or none."""
        with self._stream_lock:
            for device_index in list(self._loopback_streams):
                self._close_loopback_stream_unlocked(device_index)
            if new_device_index is not None:
                self._open_loopback_streams_unlocked([new_device_index])

    def _close_loopback_stream_unlocked(self, device_index: int) -> None:
        state = self._loopback_streams.pop(device_index, None)
        if state is None:
            return
        try:
            state.stream.stop_stream()
            state.stream.close()
        except Exception:
            pass
        self._loopback_selector.remove_source(device_index)

    def close_streams(self) -> None:
        """Close audio streams but keep PyAudio instance alive for reuse."""
        with self._stream_lock:
            self._close_mic_stream_unlocked()
            for device_index in list(self._loopback_streams):
                self._close_loopback_stream_unlocked(device_index)
            self._loopback_selector.reset()

    def terminate(self) -> None:
        """Terminate PyAudio (call only on app shutdown)."""
        self.close_streams()
        if self._pa:
            self._pa.terminate()
            self._pa = None

    def _resample_to_16k(self, audio: np.ndarray, source_rate: int,
                         source_channels: int) -> np.ndarray:
        """Convert audio to 16kHz mono float32."""
        if source_channels > 1:
            stereo = audio.reshape(-1, source_channels)
            audio = stereo[:, 0].copy()
        if source_rate != 16000:
            from math import gcd
            g = gcd(16000, source_rate)
            audio = resample_poly(audio, 16000 // g, source_rate // g)
            audio = audio.astype(np.float32)
        return audio

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback for microphone — runs in a separate thread."""
        import pyaudiowpatch as pyaudio

        if self._get_status() == SessionStatus.PAUSED:
            return (None, pyaudio.paContinue)

        raw_audio = np.frombuffer(in_data, dtype=np.float32)
        # Save raw audio before resampling (for clean WAV export)
        if self._recorded_audio_raw is not None:
            if self._device_channels > 1:
                mono = raw_audio.reshape(-1, self._device_channels)[:, 0].copy()
            else:
                mono = raw_audio.copy()
            self._recorded_audio_raw.append(mono)
            self._raw_sample_rate = self._device_sample_rate

        audio = self._resample_to_16k(raw_audio, self._device_sample_rate,
                                      self._device_channels)
        self._mic_cb_count += 1
        if self._mic_cb_count % 100 == 1:
            amp = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
            logger.info("Mic cb #%d: len=%d, amp=%.4f", self._mic_cb_count, len(audio), amp)
        self._mic_buffer.feed(audio)
        self._recorded_audio.append(audio.copy())
        return (None, pyaudio.paContinue)

    def _make_loopback_callback(self, device_index: int):
        """Build a source-aware callback for one WASAPI loopback."""

        def callback(in_data, frame_count, time_info, status):
            import pyaudiowpatch as pyaudio

            if self._get_status() == SessionStatus.PAUSED:
                return (None, pyaudio.paContinue)

            state = self._loopback_streams.get(device_index)
            if state is None:
                return (None, pyaudio.paContinue)

            raw_audio = np.frombuffer(in_data, dtype=np.float32)
            audio = self._resample_to_16k(
                raw_audio,
                state.sample_rate,
                state.channels,
            )
            state.callback_count += 1
            if state.callback_count % 100 == 1:
                amp = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
                logger.info(
                    "Loopback %s cb #%d: len=%d, amp=%.4f",
                    state.name,
                    state.callback_count,
                    len(audio),
                    amp,
                )

            if self._loopback_selector.should_emit(
                device_index,
                audio,
                now=time.monotonic(),
            ):
                self._loopback_buffer.feed(audio)
                if self._recorded_loopback is not None:
                    self._recorded_loopback.append(audio.copy())

            return (None, pyaudio.paContinue)

        return callback
