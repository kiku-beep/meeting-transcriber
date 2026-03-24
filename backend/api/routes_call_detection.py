"""API routes for call auto-detection."""

import logging
from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.call_detector import get_call_detector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/call-detection", tags=["call-detection"])


class CallDetectionConfigRequest(BaseModel):
    enabled: bool | None = None
    dismiss_duration: float | None = Field(default=None, gt=0)


@router.get("/config")
async def get_config():
    detector = get_call_detector()
    return {
        "enabled": detector.enabled,
        "dismiss_duration": detector.dismiss_duration,
    }


@router.post("/config")
async def update_config(req: CallDetectionConfigRequest):
    detector = get_call_detector()
    if req.enabled is not None:
        detector.enabled = req.enabled
        if req.enabled:
            detector.start()  # ensure background task is running
    if req.dismiss_duration is not None:
        detector.dismiss_duration = req.dismiss_duration
    return {
        "enabled": detector.enabled,
        "dismiss_duration": detector.dismiss_duration,
    }


@router.post("/dismiss")
async def dismiss_call(window_title: str):
    """Dismiss a specific call notification."""
    detector = get_call_detector()
    detector.dismiss(window_title)
    return {"ok": True}


@router.post("/dismiss-all")
async def dismiss_all_calls():
    """Dismiss all current call notifications."""
    detector = get_call_detector()
    detector.dismiss_all()
    return {"ok": True}


@router.get("/pending")
async def pending_calls():
    """Poll for new call detection notifications (frontend calls this every second)."""
    detector = get_call_detector()
    pending = await detector.pop_pending()
    return {
        "calls": [
            {
                "call_type": c.call_type,
                "display_name": c.display_name,
                "window_title": c.window_title,
                "session_name_suggestion": c.session_name_suggestion,
            }
            for c in pending
        ],
    }


@router.get("/status")
async def detection_status():
    detector = get_call_detector()
    return {
        "enabled": detector.enabled,
        "active_calls": list(detector.active_calls),
    }
