"""Configuration management API routes."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings, _env_file_path

router = APIRouter(prefix="/api/config", tags=["config"])


def _mask_key(key: str) -> str:
    """Return a masked version of an API key for display."""
    if len(key) >= 8:
        return key[:4] + "..." + key[-3:]
    return "****"


def _update_env_file(key: str, value: str) -> None:
    """Update a key=value pair in the .env file (%APPDATA%/transcriber/.env)."""
    env_path = _env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
    else:
        content = ""

    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += new_line + "\n"

    env_path.write_text(content, encoding="utf-8")


@router.get("/status")
async def get_config_status():
    """Return config status with masked API keys."""
    return {
        "gemini_api_key_set": bool(settings.gemini_api_key),
        "gemini_api_key_masked": _mask_key(settings.gemini_api_key) if settings.gemini_api_key else None,
        "screenshot_enabled": settings.screenshot_enabled,
        "screenshot_interval": settings.screenshot_interval,
        "screenshot_quality": settings.screenshot_quality,
        "text_refine_enabled": settings.text_refine_enabled,
    }


class SetApiKeyRequest(BaseModel):
    gemini_api_key: str


@router.put("/gemini-api-key")
async def set_gemini_api_key(req: SetApiKeyRequest):
    """Update the Gemini API key (in memory + .env file)."""
    key = req.gemini_api_key.strip()
    if not key:
        raise HTTPException(400, "APIキーを入力してください")

    settings.gemini_api_key = key
    _update_env_file("GEMINI_API_KEY", key)

    return {
        "gemini_api_key_set": True,
        "gemini_api_key_masked": _mask_key(key),
    }


@router.get("/meeting")
async def get_meeting_config():
    """Return meeting-related feature toggles."""
    return {
        "call_notification_enabled": settings.call_notification_enabled,
        "screenshot_enabled": settings.screenshot_enabled,
        "audio_saving_enabled": settings.audio_saving_enabled,
    }


class SetMeetingConfigRequest(BaseModel):
    call_notification_enabled: bool | None = None
    screenshot_enabled: bool | None = None
    audio_saving_enabled: bool | None = None


@router.put("/meeting")
async def set_meeting_config(req: SetMeetingConfigRequest):
    """Update meeting-related feature toggles."""
    if req.call_notification_enabled is not None:
        settings.call_notification_enabled = req.call_notification_enabled
        _update_env_file("CALL_NOTIFICATION_ENABLED", str(req.call_notification_enabled))
    if req.screenshot_enabled is not None:
        settings.screenshot_enabled = req.screenshot_enabled
        _update_env_file("SCREENSHOT_ENABLED", str(req.screenshot_enabled))
    if req.audio_saving_enabled is not None:
        settings.audio_saving_enabled = req.audio_saving_enabled
        _update_env_file("AUDIO_SAVING_ENABLED", str(req.audio_saving_enabled))
    return {
        "call_notification_enabled": settings.call_notification_enabled,
        "screenshot_enabled": settings.screenshot_enabled,
        "audio_saving_enabled": settings.audio_saving_enabled,
    }


@router.get("/screenshots")
async def get_screenshot_config():
    """Return screenshot capture settings."""
    return {
        "screenshot_enabled": settings.screenshot_enabled,
        "screenshot_interval": settings.screenshot_interval,
        "screenshot_quality": settings.screenshot_quality,
    }


class SetScreenshotConfigRequest(BaseModel):
    screenshot_enabled: bool | None = None
    screenshot_interval: int | None = None
    screenshot_quality: int | None = None


@router.put("/screenshots")
async def set_screenshot_config(req: SetScreenshotConfigRequest):
    """Update screenshot capture settings."""
    if req.screenshot_enabled is not None:
        settings.screenshot_enabled = req.screenshot_enabled
        _update_env_file("SCREENSHOT_ENABLED", str(req.screenshot_enabled))
    if req.screenshot_interval is not None:
        if req.screenshot_interval not in (5, 10, 30, 60):
            raise HTTPException(400, "Interval must be 5, 10, 30, or 60 seconds")
        settings.screenshot_interval = req.screenshot_interval
        _update_env_file("SCREENSHOT_INTERVAL", str(req.screenshot_interval))
    if req.screenshot_quality is not None:
        if req.screenshot_quality < 10 or req.screenshot_quality > 100:
            raise HTTPException(400, "Quality must be 10-100")
        settings.screenshot_quality = req.screenshot_quality
        _update_env_file("SCREENSHOT_QUALITY", str(req.screenshot_quality))
    return {
        "screenshot_enabled": settings.screenshot_enabled,
        "screenshot_interval": settings.screenshot_interval,
        "screenshot_quality": settings.screenshot_quality,
    }


class SetTextRefineRequest(BaseModel):
    enabled: bool


@router.put("/text-refine")
async def set_text_refine(req: SetTextRefineRequest):
    """Toggle text refinement (Gemini Flash Pass 2)."""
    settings.text_refine_enabled = req.enabled
    _update_env_file("TEXT_REFINE_ENABLED", str(req.enabled).lower())
    return {"text_refine_enabled": settings.text_refine_enabled}
