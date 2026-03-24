from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.storage.file_store import (
    create_folder,
    delete_folder,
    delete_session,
    folder_exists,
    list_folders,
    list_sessions,
    load_summary,
    load_transcript,
    load_transcript_text,
    rename_folder,
    save_entries,
    update_session_metadata,
    update_session_name,
)

router = APIRouter(prefix="/api/transcripts", tags=["transcripts"])


class EntryEditRequest(BaseModel):
    text: str | None = None
    speaker_name: str | None = None
    speaker_id: str | None = None


class SessionRenameRequest(BaseModel):
    session_name: str


class SetFavoriteRequest(BaseModel):
    is_favorite: bool


class SetFolderRequest(BaseModel):
    folder: str


class CreateFolderRequest(BaseModel):
    name: str


class RenameFolderRequest(BaseModel):
    name: str


@router.get("")
async def get_sessions():
    return {"sessions": list_sessions()}


# ── Folder endpoints (MUST be before /{session_id}) ───────────────


@router.get("/folders")
async def get_folders():
    return {"folders": list_folders()}


@router.post("/folders")
async def post_create_folder(req: CreateFolderRequest):
    try:
        name = create_folder(req.name)
        return {"name": name}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/folders/{folder_name:path}")
async def patch_rename_folder(folder_name: str, req: RenameFolderRequest):
    try:
        updated = rename_folder(folder_name, req.name)
        return {"old_name": folder_name, "new_name": req.name, "updated_sessions": updated}
    except FileNotFoundError:
        raise HTTPException(404, f"Folder '{folder_name}' not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/folders/{folder_name:path}")
async def delete_folder_endpoint(folder_name: str):
    try:
        deleted, failed = delete_folder(folder_name)
        return {"deleted_folder": folder_name, "deleted_sessions": deleted, "failed": failed}
    except FileNotFoundError:
        raise HTTPException(404, f"Folder '{folder_name}' not found")


# ── Session favorite/folder ───────────────────────────────────────


@router.patch("/{session_id}/favorite")
async def set_favorite(session_id: str, req: SetFavoriteRequest):
    try:
        data = update_session_metadata(session_id, {"is_favorite": req.is_favorite})
        return {"session_id": session_id, "is_favorite": data.get("is_favorite", False)}
    except FileNotFoundError:
        raise HTTPException(404, f"Session '{session_id}' not found")


@router.patch("/{session_id}/folder")
async def set_session_folder(session_id: str, req: SetFolderRequest):
    folder = req.folder.strip()
    if folder and not folder_exists(folder):
        raise HTTPException(400, f"Folder '{folder}' does not exist")
    try:
        data = update_session_metadata(session_id, {"folder": folder})
        return {"session_id": session_id, "folder": data.get("folder", "")}
    except FileNotFoundError:
        raise HTTPException(404, f"Session '{session_id}' not found")


@router.patch("/{session_id}/name")
async def rename_session(session_id: str, req: SessionRenameRequest):
    """Rename a session."""
    name = req.session_name.strip()
    if not name:
        raise HTTPException(400, "セッション名が空です")
    if not update_session_name(session_id, name):
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, "session_name": name}


@router.get("/{session_id}")
async def get_transcript(session_id: str):
    entries = load_transcript(session_id)
    if entries is None:
        raise HTTPException(404, "Session not found")
    return {"session_id": session_id, "entries": entries}


@router.get("/{session_id}/export")
async def export_transcript(session_id: str, format: str = "txt"):
    if format == "json":
        entries = load_transcript(session_id)
        if entries is None:
            raise HTTPException(404, "Session not found")
        return {"session_id": session_id, "entries": entries}

    elif format == "txt":
        text = load_transcript_text(session_id)
        if text is None:
            raise HTTPException(404, "Session not found")
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    elif format == "md":
        summary = load_summary(session_id)
        if summary is None:
            raise HTTPException(404, "Summary not found for this session")
        return PlainTextResponse(summary, media_type="text/markdown; charset=utf-8")

    else:
        raise HTTPException(400, f"Unsupported format: {format}")


@router.patch("/{session_id}/entries/{entry_id}")
async def edit_saved_entry(session_id: str, entry_id: str, req: EntryEditRequest):
    """Edit a transcript entry in a saved session."""
    from backend.storage.correction_store import get_correction_store

    entries = load_transcript(session_id)
    if entries is None:
        raise HTTPException(404, "Session not found")

    for entry in entries:
        if entry.get("id") == entry_id:
            correction_store = get_correction_store()

            if req.text is not None and req.text != entry.get("text"):
                original_text = entry.get("text", "")
                correction_store.add(
                    original=original_text,
                    corrected=req.text,
                    field="text",
                    session_id=session_id,
                    entry_id=entry_id,
                )
                entry["text"] = req.text

                # Auto-register word corrections to dictionary
                from backend.core.correction_learner import auto_register_correction
                auto_register_correction(original_text, req.text)

            if req.speaker_name is not None and req.speaker_name != entry.get("speaker_name"):
                correction_store.add(
                    original=entry.get("speaker_name", ""),
                    corrected=req.speaker_name,
                    field="speaker_name",
                    session_id=session_id,
                    entry_id=entry_id,
                )
                entry["speaker_name"] = req.speaker_name

            if req.speaker_id is not None:
                entry["speaker_id"] = req.speaker_id

            # Save back to disk
            save_entries(session_id, entries)
            return {"entry": entry}

    raise HTTPException(404, f"Entry {entry_id} not found")


@router.patch("/{session_id}/entries/{entry_id}/bookmark")
async def toggle_bookmark(session_id: str, entry_id: str):
    """Toggle bookmark on a transcript entry."""
    entries = load_transcript(session_id)
    if entries is None:
        raise HTTPException(404, "Session not found")

    for entry in entries:
        if entry.get("id") == entry_id:
            entry["bookmarked"] = not entry.get("bookmarked", False)
            save_entries(session_id, entries)
            return {"entry_id": entry_id, "bookmarked": entry["bookmarked"]}

    raise HTTPException(404, f"Entry {entry_id} not found")


@router.delete("/{session_id}/entries/{entry_id}")
async def delete_entry(session_id: str, entry_id: str):
    """Delete a single transcript entry from a saved session."""
    entries = load_transcript(session_id)
    if entries is None:
        raise HTTPException(404, "Session not found")
    new_entries = [e for e in entries if e.get("id") != entry_id]
    if len(new_entries) == len(entries):
        raise HTTPException(404, f"Entry {entry_id} not found")
    save_entries(session_id, new_entries)
    return {"deleted": entry_id}


@router.delete("/{session_id}")
async def delete_transcript(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(404, "Session not found")
    return {"deleted": session_id}
