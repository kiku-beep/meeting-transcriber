from dataclasses import asdict

from fastapi import APIRouter

from backend.core.audio_capture import (
    get_default_loopback,
    get_default_microphone,
    list_audio_devices,
)

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.get("/devices")
async def get_audio_devices():
    devices = list_audio_devices()
    default_mic = get_default_microphone()
    default_loopback = get_default_loopback()

    return {
        "devices": [asdict(d) for d in devices],
        "default_mic_index": default_mic.index if default_mic else None,
        "default_loopback_index": default_loopback.index if default_loopback else None,
        "default_microphone": asdict(default_mic) if default_mic else None,
        "default_loopback": asdict(default_loopback) if default_loopback else None,
    }
