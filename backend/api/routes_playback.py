"""Audio playback, compression, and deletion endpoints."""

from __future__ import annotations

import logging
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from backend.config import settings
from backend.core.audio_compressor import compress_wav_to_ogg, find_ffmpeg
from backend.storage.file_store import _validate_session_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playback", tags=["playback"])


def _session_dir(session_id: str) -> Path:
    _validate_session_id(session_id)
    return settings.sessions_dir / session_id


def _find_audio(session_id: str) -> tuple[Path | None, str]:
    """Find best available audio file. Returns (path, format)."""
    d = _session_dir(session_id)
    ogg = d / "recording.ogg"
    wav = d / "recording.wav"
    if ogg.exists():
        return ogg, "ogg"
    if wav.exists():
        return wav, "wav"
    return None, ""


@router.get("/{session_id}/audio")
async def stream_audio(session_id: str, request: Request):
    """Stream audio file with HTTP Range support for seeking."""
    audio_path, fmt = _find_audio(session_id)
    if audio_path is None:
        raise HTTPException(404, "No audio file found for this session")

    media_type = "audio/ogg; codecs=opus" if fmt == "ogg" else "audio/wav"
    file_size = audio_path.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        # Parse "bytes=START-END" or "bytes=START-"
        range_str = range_header.replace("bytes=", "")
        parts = range_str.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def iter_range():
            with open(audio_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=media_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    # No Range header — return full file
    return FileResponse(
        path=str(audio_path),
        media_type=media_type,
        filename=audio_path.name,
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{session_id}/audio/info")
async def audio_info(session_id: str):
    """Return audio file metadata."""
    audio_path, fmt = _find_audio(session_id)
    if audio_path is None:
        return {
            "has_audio": False,
            "format": None,
            "duration_seconds": None,
            "file_size_bytes": None,
        }

    duration = None
    if fmt == "wav":
        try:
            with wave.open(str(audio_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration = frames / rate
        except Exception:
            pass

    return {
        "has_audio": True,
        "format": fmt,
        "duration_seconds": duration,
        "file_size_bytes": audio_path.stat().st_size,
    }


@router.delete("/{session_id}/audio")
async def delete_audio(session_id: str):
    """Delete audio files (WAV and/or OGG) for a session."""
    d = _session_dir(session_id)
    deleted = []
    for name in ("recording.wav", "recording.ogg"):
        p = d / name
        if p.exists():
            p.unlink()
            deleted.append(name)
            logger.info("Deleted %s for session %s", name, session_id)

    if not deleted:
        raise HTTPException(404, "No audio files found")

    return {"deleted": deleted, "session_id": session_id}


@router.post("/{session_id}/compress")
async def compress_audio(session_id: str):
    """Compress WAV to OGG Opus. Deletes WAV on success."""
    d = _session_dir(session_id)
    wav_path = d / "recording.wav"

    if not wav_path.exists():
        ogg_path = d / "recording.ogg"
        if ogg_path.exists():
            return {"status": "already_compressed", "session_id": session_id}
        raise HTTPException(404, "No WAV file found for this session")

    if find_ffmpeg() is None:
        return {"status": "ffmpeg_not_found", "session_id": session_id}

    ogg_path = compress_wav_to_ogg(wav_path)
    if ogg_path is None:
        raise HTTPException(500, "Compression failed")

    # Delete original WAV after successful compression
    wav_path.unlink()
    logger.info("Deleted original WAV after compression: %s", wav_path)

    return {
        "status": "compressed",
        "session_id": session_id,
        "ogg_size_bytes": ogg_path.stat().st_size,
    }
