"""Screenshot listing, serving, and deletion endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import settings
from backend.storage.file_store import _validate_session_id, load_screenshots_manifest, delete_screenshots

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screenshots", tags=["screenshots"])


def _screenshots_dir(session_id: str) -> Path:
    _validate_session_id(session_id)
    return settings.sessions_dir / session_id / "screenshots"


@router.get("/{session_id}")
async def list_screenshots(session_id: str):
    """List all screenshots with metadata for a session."""
    manifest = load_screenshots_manifest(session_id)
    if manifest is not None:
        return {"session_id": session_id, "screenshots": manifest}

    # Fallback: scan directory
    screenshots_dir = _screenshots_dir(session_id)
    if not screenshots_dir.exists():
        return {"session_id": session_id, "screenshots": []}

    screenshots = []
    for f in sorted(screenshots_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg"):
            continue
        ts_str = f.stem.replace("cap_", "")
        try:
            relative_seconds = float(ts_str)
        except ValueError:
            relative_seconds = 0.0
        screenshots.append({
            "filename": f.name,
            "relative_seconds": relative_seconds,
            "size_bytes": f.stat().st_size,
        })

    return {"session_id": session_id, "screenshots": screenshots}


@router.get("/{session_id}/{filename}")
async def serve_screenshot(session_id: str, filename: str):
    """Serve a screenshot image file."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")

    file_path = _screenshots_dir(session_id) / filename
    if not file_path.exists():
        raise HTTPException(404, "Screenshot not found")

    suffix = file_path.suffix.lower()
    media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return FileResponse(path=str(file_path), media_type=media_type, filename=filename)


@router.delete("/{session_id}")
async def delete_session_screenshots(session_id: str):
    """Delete all screenshots for a session."""
    count = delete_screenshots(session_id)
    if count == 0:
        raise HTTPException(404, "No screenshots found for this session")
    logger.info("Deleted %d screenshots for session %s", count, session_id)
    return {"session_id": session_id, "deleted_count": count}
