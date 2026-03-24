"""Periodic screen capture during recording sessions."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import mss
from PIL import Image

from backend.config import settings

logger = logging.getLogger(__name__)


class ScreenCapturer:
    """Captures the primary monitor at regular intervals."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._screenshots_dir: Path | None = None
        self._start_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, session_id: str, interval: int | None = None, quality: int | None = None) -> None:
        """Start periodic screen capture."""
        if self.is_running:
            logger.warning("Screen capture already running, stopping first")
            self.stop()

        _interval = interval or settings.screenshot_interval
        _quality = quality or settings.screenshot_quality

        screenshots_dir = settings.sessions_dir / session_id / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._screenshots_dir = screenshots_dir
        self._start_time = time.monotonic()

        self._task = asyncio.create_task(
            self._capture_loop(_interval, _quality)
        )
        logger.info("Screen capture started: session=%s, interval=%ds, quality=%d",
                     session_id, _interval, _quality)

    def stop(self) -> None:
        """Stop the capture loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Screen capture stopped")
        self._task = None

    async def _capture_loop(self, interval: int, quality: int) -> None:
        """Background loop that captures at regular intervals."""
        try:
            while True:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._capture_one, quality
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.debug("Capture loop cancelled")
        except Exception:
            logger.exception("Capture loop crashed")

    def _capture_one(self, quality: int) -> None:
        """Take a single screenshot and save as JPEG."""
        if not self._screenshots_dir:
            return
        try:
            relative_secs = time.monotonic() - self._start_time
            filename = f"cap_{relative_secs:09.3f}.jpg"
            filepath = self._screenshots_dir / filename

            with mss.mss() as sct:
                # Monitor 1 = primary monitor (monitor 0 is "all monitors combined")
                monitor = sct.monitors[1]
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            img.save(str(filepath), "JPEG", quality=quality)
            logger.debug("Screenshot saved: %s (%.1f KB)", filename, filepath.stat().st_size / 1024)
        except Exception:
            logger.warning("Screenshot capture failed", exc_info=True)


# Singleton
_capturer = ScreenCapturer()


def get_screen_capturer() -> ScreenCapturer:
    return _capturer
