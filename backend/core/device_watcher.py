"""Event-driven Windows audio device change detection using IMMNotificationClient.

Uses pycaw/comtypes to receive instant OS-level callbacks when the default
audio device changes, a device is added/removed, etc.
Falls back to polling if COM initialization fails (e.g. non-Windows).
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
import threading
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

DEBOUNCE_SEC = 0.5  # Aggregate rapid-fire COM events (device change fires up to 6x)


@dataclass
class DeviceChangeEvent:
    event_type: Literal["default_changed", "added", "removed"]
    flow: Literal["render", "output", "capture", "input"]
    device_id: str
    timestamp: float


class DeviceWatcher:
    """Watches for Windows audio device changes via COM IMMNotificationClient.

    Usage:
        watcher = DeviceWatcher(asyncio.get_event_loop())
        watcher.start(callback=my_async_handler)
        ...
        watcher.stop()
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._callback: Callable[[DeviceChangeEvent], Awaitable[None]] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_event_driven = False

        # Debounce state
        self._debounce_timer: threading.Timer | None = None
        self._debounce_lock = threading.Lock()
        self._pending_events: dict[str, DeviceChangeEvent] = {}  # key: flow

    @property
    def is_event_driven(self) -> bool:
        """True if COM-based event detection is active (vs polling fallback)."""
        return self._is_event_driven

    def start(self, callback: Callable[[DeviceChangeEvent], Awaitable[None]]) -> None:
        """Start watching for device changes."""
        self._callback = callback
        try:
            import comtypes  # noqa: F401
            from pycaw.callbacks import MMNotificationClient  # noqa: F401
            self._thread = threading.Thread(
                target=self._com_thread, daemon=True, name="DeviceWatcher-COM"
            )
            self._thread.start()
            # Wait briefly for COM init
            time.sleep(0.1)
            if self._is_event_driven:
                logger.info("DeviceWatcher started (event-driven via IMMNotificationClient)")
            else:
                logger.warning("DeviceWatcher COM init failed, will use polling fallback")
        except ImportError:
            logger.warning("pycaw/comtypes not available, will use polling fallback")

    def stop(self) -> None:
        """Stop the watcher."""
        self._stop_event.set()
        with self._debounce_lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
                self._debounce_timer = None
        if self._thread and self._thread.is_alive():
            # Post WM_QUIT to break the message loop
            try:
                if hasattr(self, '_thread_id') and self._thread_id:
                    ctypes.windll.user32.PostThreadMessageW(
                        self._thread_id, 0x0012, 0, 0  # WM_QUIT
                    )
            except Exception:
                pass
            self._thread.join(timeout=3)
        self._thread = None
        self._is_event_driven = False
        logger.info("DeviceWatcher stopped")

    def _com_thread(self) -> None:
        """Dedicated STA thread for COM message pump."""
        import comtypes
        from pycaw.callbacks import MMNotificationClient
        from pycaw.utils import AudioUtilities

        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        except Exception:
            logger.exception("COM CoInitializeEx failed")
            return

        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()

            class _Callback(MMNotificationClient):
                def __init__(cb_self):
                    super().__init__()
                    cb_self._watcher = self

                def on_default_device_changed(cb_self, flow, role, device_id):
                    # role: 0=eConsole, 1=eMultimedia, 2=eCommunications
                    # Only react to eConsole (general default)
                    if role != 0:
                        return
                    flow_name = "capture" if flow == 1 else "render"
                    event = DeviceChangeEvent(
                        event_type="default_changed",
                        flow=flow_name,
                        device_id=device_id or "",
                        timestamp=time.monotonic(),
                    )
                    cb_self._watcher._debounce_event(event)

                def on_device_added(cb_self, device_id):
                    event = DeviceChangeEvent(
                        event_type="added", flow="render",
                        device_id=device_id or "", timestamp=time.monotonic(),
                    )
                    cb_self._watcher._debounce_event(event)

                def on_device_removed(cb_self, device_id):
                    event = DeviceChangeEvent(
                        event_type="removed", flow="render",
                        device_id=device_id or "", timestamp=time.monotonic(),
                    )
                    cb_self._watcher._debounce_event(event)

                def on_device_state_changed(cb_self, device_id, new_state, new_state_id):
                    pass

            callback_obj = _Callback()
            # Must keep a strong reference to prevent GC
            self._com_callback = callback_obj

            enumerator.RegisterEndpointNotificationCallback(callback_obj)
            self._is_event_driven = True

            # STA message pump
            msg = ctypes.wintypes.MSG()
            while not self._stop_event.is_set():
                result = ctypes.windll.user32.MsgWaitForMultipleObjects(
                    0, None, False, 500, 0x04FF  # QS_ALLINPUT, 500ms timeout
                )
                if result == 0xFFFFFFFF:  # WAIT_FAILED
                    break
                while ctypes.windll.user32.PeekMessageW(
                    ctypes.byref(msg), None, 0, 0, 0x0001  # PM_REMOVE
                ):
                    if msg.message == 0x0012:  # WM_QUIT
                        self._stop_event.set()
                        break
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

            enumerator.UnregisterEndpointNotificationCallback(callback_obj)

        except Exception:
            logger.exception("DeviceWatcher COM thread error")
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
            self._is_event_driven = False

    def _debounce_event(self, event: DeviceChangeEvent) -> None:
        """Aggregate rapid-fire events and fire once after DEBOUNCE_SEC."""
        with self._debounce_lock:
            # Store latest event per flow (overwrite previous)
            key = f"{event.event_type}:{event.flow}"
            self._pending_events[key] = event

            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(DEBOUNCE_SEC, self._fire_events)
            self._debounce_timer.start()

    def _fire_events(self) -> None:
        """Push debounced events to asyncio loop."""
        with self._debounce_lock:
            events = list(self._pending_events.values())
            self._pending_events.clear()
            self._debounce_timer = None

        for event in events:
            logger.info(
                "Device change: %s %s (id=%s)",
                event.event_type, event.flow, event.device_id[:30] if event.device_id else "none",
            )
            if self._callback:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._callback(event),
                )
