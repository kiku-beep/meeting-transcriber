"""Summary generation and retrieval API routes."""

import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings
from backend.core.summarizer import GEMINI_MODELS, generate_summary
from backend.storage.file_store import (
    load_summary, load_transcript, save_summary, update_session_name, list_sessions,
)

router = APIRouter(prefix="/api/summary", tags=["summary"])


class GenerateRequest(BaseModel):
    session_id: str
    force_regenerate: bool = False  # デフォルトはキャッシュ優先


@router.post("/generate")
async def generate(req: GenerateRequest):
    """Generate a meeting summary for the given session."""
    entries = load_transcript(req.session_id)
    if entries is None:
        raise HTTPException(404, "セッションが見つかりません")

    if not entries:
        raise HTTPException(400, "文字起こしが空です")

    # Check for existing summary (cache)
    existing_summary = load_summary(req.session_id)
    cached = False

    if existing_summary and not req.force_regenerate:
        # Validate cache freshness: check if transcript is newer than summary
        session_dir = settings.sessions_dir / req.session_id
        transcript_path = session_dir / "transcript.json"
        summary_path = session_dir / "summary.md"

        cache_valid = True
        if transcript_path.exists() and summary_path.exists():
            transcript_mtime = transcript_path.stat().st_mtime
            summary_mtime = summary_path.stat().st_mtime
            if transcript_mtime > summary_mtime:
                cache_valid = False

        if cache_valid:
            # Cache HIT: return existing summary
            cached = True
            summary_md = existing_summary
            title = None  # Extract title from existing summary if needed
            usage = {}

            # Try to extract title from cached summary
            from backend.core.summarizer import extract_title
            title = extract_title(summary_md)

            return {
                "session_id": req.session_id,
                "summary": summary_md,
                "title": title,
                "usage": usage,
                "cached": cached,
            }

    # Cache MISS or force_regenerate: generate new summary
    try:
        result = await generate_summary(entries)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"要約生成に失敗しました: {e}\n\n{tb}")

    summary_md = result["summary"]
    title = result.get("title")
    usage = result.get("usage", {})

    save_summary(req.session_id, summary_md)

    # Auto-name session if no name was set
    if title:
        sessions = list_sessions()
        for s in sessions:
            if s.get("session_id") == req.session_id:
                if not s.get("session_name"):
                    update_session_name(req.session_id, title)
                break

    return {
        "session_id": req.session_id,
        "summary": summary_md,
        "title": title,
        "usage": usage,
        "cached": cached,
    }


@router.get("/models")
async def get_models():
    """Get available Gemini models with metadata."""
    models = []
    for model_id, info in GEMINI_MODELS.items():
        models.append({
            "id": model_id,
            "label": info["label"],
            "input_price": info["input"],
            "output_price": info["output"],
            "speed": info["speed"],
            "accuracy": info["accuracy"],
        })
    return {
        "current_model": settings.gemini_model,
        "models": models,
    }


class SetModelRequest(BaseModel):
    model_id: str


@router.put("/model")
async def set_model(req: SetModelRequest):
    """Change the active Gemini model."""
    if req.model_id not in GEMINI_MODELS:
        raise HTTPException(400, f"不明なモデル: {req.model_id}")
    settings.gemini_model = req.model_id
    return {"current_model": settings.gemini_model}


@router.get("/{session_id}")
async def get_summary(session_id: str):
    """Get a previously generated summary."""
    summary = load_summary(session_id)
    if summary is None:
        raise HTTPException(404, "要約が見つかりません")
    return {"session_id": session_id, "summary": summary}
