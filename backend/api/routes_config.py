"""Configuration management API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings, update_env_file

router = APIRouter(prefix="/api/config", tags=["config"])


def _mask_key(key: str) -> str:
    """Return a masked version of an API key for display."""
    if len(key) >= 8:
        return key[:4] + "..." + key[-3:]
    return "****"


@router.get("/status")
async def get_config_status():
    """Return config status with masked API keys."""
    return {
        "gemini_api_key_set": bool(settings.gemini_api_key),
        "gemini_api_key_masked": _mask_key(settings.gemini_api_key) if settings.gemini_api_key else None,
        "summary_engine": settings.summary_engine,
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
    update_env_file("GEMINI_API_KEY", key)

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
        update_env_file("CALL_NOTIFICATION_ENABLED", str(req.call_notification_enabled))
    if req.screenshot_enabled is not None:
        settings.screenshot_enabled = req.screenshot_enabled
        update_env_file("SCREENSHOT_ENABLED", str(req.screenshot_enabled))
    if req.audio_saving_enabled is not None:
        settings.audio_saving_enabled = req.audio_saving_enabled
        update_env_file("AUDIO_SAVING_ENABLED", str(req.audio_saving_enabled))
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
        update_env_file("SCREENSHOT_ENABLED", str(req.screenshot_enabled))
    if req.screenshot_interval is not None:
        if req.screenshot_interval not in (5, 10, 30, 60):
            raise HTTPException(400, "Interval must be 5, 10, 30, or 60 seconds")
        settings.screenshot_interval = req.screenshot_interval
        update_env_file("SCREENSHOT_INTERVAL", str(req.screenshot_interval))
    if req.screenshot_quality is not None:
        if req.screenshot_quality < 10 or req.screenshot_quality > 100:
            raise HTTPException(400, "Quality must be 10-100")
        settings.screenshot_quality = req.screenshot_quality
        update_env_file("SCREENSHOT_QUALITY", str(req.screenshot_quality))
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
    update_env_file("TEXT_REFINE_ENABLED", str(req.enabled).lower())
    return {"text_refine_enabled": settings.text_refine_enabled}


@router.get("/topic-tree")
async def get_topic_tree_config():
    """Return meeting-time topic-tree settings."""
    return {
        "topic_tree_enabled": settings.topic_tree_enabled,
        "topic_tree_interval_s": settings.topic_tree_interval_s,
    }


class SetTopicTreeConfigRequest(BaseModel):
    topic_tree_enabled: bool | None = None
    topic_tree_interval_s: float | None = None


@router.put("/topic-tree")
async def set_topic_tree_config(req: SetTopicTreeConfigRequest):
    """Update meeting-time topic-tree settings.

    TopicTracker は start() 時に設定を読むため、変更は次の録音開始から効く。
    """
    if req.topic_tree_enabled is not None:
        settings.topic_tree_enabled = req.topic_tree_enabled
        update_env_file("TOPIC_TREE_ENABLED", str(req.topic_tree_enabled).lower())
    if req.topic_tree_interval_s is not None:
        # 下限30秒: 1回の更新に20〜35秒かかる実測があり、これより短いと
        # 常に前回の更新が走っていて busy になる。
        if req.topic_tree_interval_s < 30 or req.topic_tree_interval_s > 600:
            raise HTTPException(400, "更新間隔は30〜600秒で指定してください")
        settings.topic_tree_interval_s = req.topic_tree_interval_s
        update_env_file("TOPIC_TREE_INTERVAL_S", str(req.topic_tree_interval_s))
    return {
        "topic_tree_enabled": settings.topic_tree_enabled,
        "topic_tree_interval_s": settings.topic_tree_interval_s,
    }
