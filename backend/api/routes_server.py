from fastapi import APIRouter

from backend.config import settings
from backend.models.session import active_session_count, list_active_sessions

router = APIRouter(prefix="/api/server", tags=["server"])


@router.get("/sessions")
async def server_sessions():
    return {"sessions": list_active_sessions()}


@router.get("/diagnostics")
async def server_diagnostics():
    return {
        "deployment_mode": settings.deployment_mode,
        "auth_required": bool(settings.auth_token),
        "audio_ws_path": "/ws/audio/{client_id}",
        "transcript_ws_path": "/ws/transcript",
        "active_session_count": active_session_count(),
        "max_concurrent_sessions": settings.max_concurrent_sessions,
    }
