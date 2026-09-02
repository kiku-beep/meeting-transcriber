"""Select one loopback source from concurrent WASAPI callbacks."""

from __future__ import annotations

import math
import threading

import numpy as np


class LoopbackSourceSelector:
    """Keep one timeline source while allowing silent-device handoff."""

    def __init__(
        self,
        *,
        activity_threshold: float = 0.001,
        switch_after_s: float = 0.2,
    ) -> None:
        self._activity_threshold = activity_threshold
        self._switch_after_s = switch_after_s
        self._selected_source: int | None = None
        self._last_signal_at: dict[int, float] = {}
        self._lock = threading.Lock()

    @property
    def selected_source(self) -> int | None:
        with self._lock:
            return self._selected_source

    def should_emit(
        self,
        source_id: int,
        audio: np.ndarray,
        *,
        now: float,
    ) -> bool:
        level = self._rms(audio)
        has_signal = level >= self._activity_threshold

        with self._lock:
            if has_signal:
                self._last_signal_at[source_id] = now

            if self._selected_source is None:
                self._selected_source = source_id
                return True

            if self._selected_source == source_id:
                return True

            if not has_signal:
                return False

            selected_last_signal = self._last_signal_at.get(
                self._selected_source,
                -math.inf,
            )
            if now - selected_last_signal >= self._switch_after_s:
                self._selected_source = source_id
                return True

            return False

    def remove_source(self, source_id: int) -> None:
        with self._lock:
            self._last_signal_at.pop(source_id, None)
            if self._selected_source == source_id:
                self._selected_source = None

    def reset(self) -> None:
        with self._lock:
            self._selected_source = None
            self._last_signal_at.clear()

    @staticmethod
    def _rms(audio: np.ndarray) -> float:
        if audio.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
