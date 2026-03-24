"""Auto-detect Google Meet / Slack Huddle calls via window title monitoring."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# Win32 API
user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


@dataclass
class CallPattern:
    """A pattern to match against window titles."""
    name: str  # e.g. "Google Meet", "Slack Huddle"
    patterns: list[re.Pattern]
    session_name_prefix: str  # e.g. "Meet", "Huddle"
    call_type: str = ""  # e.g. "google_meet", "slack_huddle"


@dataclass
class DetectedCall:
    """Info about a detected call."""
    call_type: str  # "google_meet" or "slack_huddle"
    display_name: str  # e.g. "Google Meet", "Slack ハドル"
    window_title: str
    session_name_suggestion: str  # auto-generated session name
    detected_at: float = field(default_factory=time.time)


# Exclude patterns: windows matching these are never treated as calls
_EXCLUDE_PATTERNS: list[re.Pattern] = [
    re.compile(r"Visual Studio Code", re.IGNORECASE),
    re.compile(r"- Code$", re.IGNORECASE),  # VSCode window suffix
]

# Default detection patterns
DEFAULT_PATTERNS: list[CallPattern] = [
    CallPattern(
        name="Google Meet",
        call_type="google_meet",
        patterns=[
            # Active Meet call: "Meet - Meeting Name - Google Chrome"
            # Must have a meeting name part (not just "Meet - Google Chrome")
            re.compile(r"Meet\s*[-–—]\s*(?!Google\s*Chrome|Microsoft\s*Edge|Mozilla\s*Firefox).+[-–—]\s*(?:Google\s*Chrome|Microsoft\s*Edge|Mozilla\s*Firefox)", re.IGNORECASE),
        ],
        session_name_prefix="Meet",
    ),
    CallPattern(
        name="Slack ハドル",
        call_type="slack_huddle",
        patterns=[
            # Slack app window with Huddle active
            re.compile(r"^Slack\b.*[Hh]uddle"),
            re.compile(r"^Slack\b.*ハドル"),
            # Huddle in a Slack-titled window
            re.compile(r"[Hh]uddle.*\|\s*Slack"),
            re.compile(r"ハドル.*\|\s*Slack"),
        ],
        session_name_prefix="Huddle",
    ),
]


def _get_visible_window_titles() -> list[str]:
    """Enumerate all visible window titles using Win32 API."""
    titles: list[str] = []

    def callback(hwnd, _lparam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    titles.append(buf.value)
        return True  # continue enumeration

    EnumWindows(WNDENUMPROC(callback), 0)
    return titles


def _extract_meeting_name(title: str, pattern: CallPattern) -> str:
    """Try to extract a meaningful meeting name from the window title."""
    # For "Meet - Meeting Name - Google Chrome", extract "Meeting Name"
    if pattern.name == "Google Meet":
        m = re.match(
            r"Meet\s*[-–—]\s*(.+?)\s*[-–—]\s*(?:Google\s+Chrome|Microsoft\s+Edge|Mozilla\s+Firefox)$",
            title,
        )
        if m:
            return m.group(1).strip()
    return pattern.session_name_prefix


def detect_calls(patterns: list[CallPattern] | None = None) -> list[DetectedCall]:
    """Scan visible windows and return any detected calls."""
    if patterns is None:
        patterns = DEFAULT_PATTERNS

    titles = _get_visible_window_titles()
    detected: list[DetectedCall] = []

    for title in titles:
        # Skip excluded windows (IDEs, editors, etc.)
        if any(ep.search(title) for ep in _EXCLUDE_PATTERNS):
            continue

        for cp in patterns:
            for pat in cp.patterns:
                if pat.search(title):
                    meeting_name = _extract_meeting_name(title, cp)
                    detected.append(DetectedCall(
                        call_type=cp.call_type or cp.name.lower().replace(" ", "_"),
                        display_name=cp.name,
                        window_title=title,
                        session_name_suggestion=meeting_name,
                    ))
                    break  # don't match same title with multiple patterns of same CallPattern
            else:
                continue
            break  # matched this title, move to next

    return detected


class CallDetectorService:
    """Background service that monitors for calls and notifies via callback."""

    def __init__(
        self,
        on_call_detected: Callable[[DetectedCall], None] | None = None,
        poll_interval: float = 5.0,
    ):
        self._on_call_detected = on_call_detected
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._enabled = True
        # Track dismissed calls: {window_title: dismiss_until_timestamp}
        self._dismissed: dict[str, float] = {}
        self._dismiss_duration = 300.0  # 5 minutes
        # Track currently active (already notified) calls
        self._active_calls: set[str] = set()
        # Pending notifications for frontend polling (capped to avoid unbounded growth)
        self._pending: list[DetectedCall] = []
        self._pending_lock = asyncio.Lock()
        self._max_pending = 10
        self._stop_event = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    @property
    def dismiss_duration(self) -> float:
        return self._dismiss_duration

    @dismiss_duration.setter
    def dismiss_duration(self, value: float):
        if value <= 0:
            raise ValueError("dismiss_duration must be positive")
        self._dismiss_duration = value

    @property
    def active_calls(self) -> set[str]:
        return set(self._active_calls)

    async def pop_pending(self) -> list[DetectedCall]:
        """Return and clear all pending notifications (for frontend polling)."""
        async with self._pending_lock:
            result = list(self._pending)
            self._pending.clear()
            return result

    def dismiss(self, window_title: str):
        """Dismiss a detected call for a period (won't notify again)."""
        self._dismissed[window_title] = time.time() + self._dismiss_duration
        self._active_calls.discard(window_title)

    def dismiss_all(self):
        """Dismiss all currently detected calls."""
        for title in list(self._active_calls):
            self._dismissed[title] = time.time() + self._dismiss_duration
        self._active_calls.clear()

    def start(self):
        """Start the background monitoring task."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("CallDetectorService started (interval=%.1fs)", self._poll_interval)

    def stop(self):
        """Stop the background monitoring task."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("CallDetectorService stopped")

    async def _monitor_loop(self):
        """Main monitoring loop."""
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                if self._enabled:
                    await self._check_once(loop)
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("CallDetector error")
                await asyncio.sleep(self._poll_interval)

    async def _check_once(self, loop: asyncio.AbstractEventLoop):
        """Run one detection cycle."""
        # Run Win32 enumeration in thread (it's blocking)
        detected = await loop.run_in_executor(None, detect_calls)

        now = time.time()
        # Clean expired dismissals
        self._dismissed = {k: v for k, v in self._dismissed.items() if v > now}

        current_titles = set()
        for call in detected:
            current_titles.add(call.window_title)

            # Skip if dismissed
            if call.window_title in self._dismissed:
                continue

            # Skip if already notified (still active)
            if call.window_title in self._active_calls:
                continue

            # New detection!
            self._active_calls.add(call.window_title)
            if len(self._pending) < self._max_pending:
                self._pending.append(call)
            logger.info("Call detected: %s (%s)", call.display_name, call.window_title)

            if self._on_call_detected:
                self._on_call_detected(call)

        # Clean up calls that are no longer active
        gone = self._active_calls - current_titles
        self._active_calls -= gone


# Module-level singleton
_detector: CallDetectorService | None = None


def get_call_detector() -> CallDetectorService:
    global _detector
    if _detector is None:
        _detector = CallDetectorService()
    return _detector
