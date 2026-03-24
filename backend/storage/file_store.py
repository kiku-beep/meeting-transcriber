"""Transcript and session file I/O."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from backend.config import settings
from backend.models.schemas import TranscriptEntry

logger = logging.getLogger(__name__)

_folders_lock = threading.Lock()
_FOLDER_NAME_MAX_LEN = 50
_FOLDER_MAX_COUNT = 50
_FOLDER_NAME_INVALID_CHARS = re.compile(r'[/\\:*?"<>|]')


def _validate_session_id(session_id: str) -> None:
    """Reject suspicious session IDs to prevent path traversal."""
    if not re.match(r'^[\w-]+$', session_id):
        raise ValueError(f"Invalid session_id: {session_id}")
    resolved = (settings.sessions_dir / session_id).resolve()
    if not str(resolved).startswith(str(settings.sessions_dir.resolve())):
        raise ValueError(f"Path traversal detected: {session_id}")


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON atomically via tmp file + os.replace."""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_suffix('.tmp')
    tmp_path.write_text(text, encoding='utf-8')
    os.replace(str(tmp_path), str(path))


def save_session(session_id: str, entries: list[TranscriptEntry],
                 metadata: dict | None = None) -> Path:
    """Save a completed session to disk.

    Creates:
      data/sessions/{session_id}/
        transcript.json  — structured entries
        transcript.txt   — plain text
        metadata.json    — session metadata
    """
    _validate_session_id(session_id)
    session_dir = settings.sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # transcript.json
    entries_data = [
        {
            "id": e.id,
            "text": e.text,
            "raw_text": e.raw_text,
            "speaker_name": e.speaker_name,
            "speaker_id": e.speaker_id,
            "speaker_confidence": e.speaker_confidence,
            "timestamp_start": e.timestamp_start,
            "timestamp_end": e.timestamp_end,
            "created_at": e.created_at.isoformat(),
            "bookmarked": e.bookmarked,
        }
        for e in entries
    ]
    _atomic_write_json(session_dir / "transcript.json", entries_data)

    # transcript.txt
    lines = []
    for e in entries:
        ts = f"[{_format_time(e.timestamp_start)} - {_format_time(e.timestamp_end)}]"
        lines.append(f"{ts} {e.speaker_name}: {e.text}")
    (session_dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")

    # metadata.json
    meta = {
        "session_id": session_id,
        "entry_count": len(entries),
        "saved_at": datetime.now().isoformat(),
        **(metadata or {}),
    }
    _atomic_write_json(session_dir / "metadata.json", meta)

    # screenshots.json (if screenshots exist)
    screenshots_dir = session_dir / "screenshots"
    if screenshots_dir.exists():
        screenshots_meta = []
        for f in sorted(screenshots_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg"):
                ts_str = f.stem.replace("cap_", "")
                try:
                    relative_seconds = float(ts_str)
                except ValueError:
                    relative_seconds = 0.0
                screenshots_meta.append({
                    "filename": f.name,
                    "relative_seconds": relative_seconds,
                    "size_bytes": f.stat().st_size,
                })
        if screenshots_meta:
            _atomic_write_json(session_dir / "screenshots.json", screenshots_meta)
            # Update metadata with screenshot count
            meta["screenshot_count"] = len(screenshots_meta)
            _atomic_write_json(session_dir / "metadata.json", meta)

    logger.info("Session %s saved: %d entries", session_id, len(entries))
    return session_dir


def _dir_size(path: Path) -> int:
    """Calculate total size of all files in a directory recursively."""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def list_sessions() -> list[dict]:
    """List all saved sessions."""
    sessions = []
    if not settings.sessions_dir.exists():
        return sessions

    for session_dir in sorted(settings.sessions_dir.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue
        meta_path = session_dir / "metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["total_size_bytes"] = _dir_size(session_dir)
                sessions.append(meta)
            except Exception:
                sessions.append({"session_id": session_dir.name, "error": "corrupt metadata"})
        else:
            sessions.append({"session_id": session_dir.name, "total_size_bytes": _dir_size(session_dir)})
    return sessions


def load_transcript(session_id: str) -> list[dict] | None:
    """Load transcript entries for a session."""
    _validate_session_id(session_id)
    path = settings.sessions_dir / session_id / "transcript.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_transcript_text(session_id: str) -> str | None:
    """Load plain text transcript."""
    _validate_session_id(session_id)
    path = settings.sessions_dir / session_id / "transcript.txt"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_summary(session_id: str) -> str | None:
    """Load generated summary markdown."""
    _validate_session_id(session_id)
    path = settings.sessions_dir / session_id / "summary.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_summary(session_id: str, summary_md: str) -> Path:
    """Save a generated summary."""
    _validate_session_id(session_id)
    session_dir = settings.sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "summary.md"
    path.write_text(summary_md, encoding="utf-8")
    logger.info("Summary saved for session %s", session_id)
    return path


def update_session_name(session_id: str, name: str) -> bool:
    """Update session_name in metadata.json."""
    _validate_session_id(session_id)
    meta_path = settings.sessions_dir / session_id / "metadata.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["session_name"] = name
        _atomic_write_json(meta_path, meta)
        logger.info("Session %s renamed to '%s'", session_id, name)
        return True
    except Exception:
        logger.exception("Failed to update session name")
        return False


def save_entries(session_id: str, entries: list[dict]) -> None:
    """Overwrite transcript.json for a session."""
    _validate_session_id(session_id)
    session_dir = settings.sessions_dir / session_id
    if not session_dir.exists():
        return
    _atomic_write_json(session_dir / "transcript.json", entries)
    # Regenerate transcript.txt
    lines = []
    for e in entries:
        ts = f"[{_format_time(e.get('timestamp_start', 0))} - {_format_time(e.get('timestamp_end', 0))}]"
        lines.append(f"{ts} {e.get('speaker_name', 'Unknown')}: {e.get('text', '')}")
    (session_dir / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    logger.info("Entries updated for session %s", session_id)


def delete_session(session_id: str) -> bool:
    """Delete a saved session directory."""
    _validate_session_id(session_id)
    session_dir = settings.sessions_dir / session_id
    if not session_dir.exists():
        return False
    shutil.rmtree(session_dir)
    logger.info("Session %s deleted", session_id)
    return True


def load_screenshots_manifest(session_id: str) -> list[dict] | None:
    """Load screenshots.json manifest. Returns None if not found."""
    _validate_session_id(session_id)
    path = settings.sessions_dir / session_id / "screenshots.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def delete_screenshots(session_id: str) -> int:
    """Delete screenshots directory and manifest for a session. Returns count deleted."""
    _validate_session_id(session_id)
    session_dir = settings.sessions_dir / session_id
    screenshots_dir = session_dir / "screenshots"
    manifest_path = session_dir / "screenshots.json"
    count = 0
    if screenshots_dir.exists():
        count = sum(1 for f in screenshots_dir.iterdir() if f.is_file())
        shutil.rmtree(screenshots_dir)
    if manifest_path.exists():
        manifest_path.unlink()
    return count


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


# ── Session metadata helpers ──────────────────────────────────────


def update_session_metadata(session_id: str, updates: dict) -> dict:
    """Update specific fields in a session's metadata.json."""
    _validate_session_id(session_id)
    meta_path = settings.sessions_dir / session_id / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Session {session_id} not found")
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data.update(updates)
    _atomic_write_json(meta_path, data)
    return data


# ── Folder management ─────────────────────────────────────────────


def _folders_path() -> Path:
    return settings.sessions_dir / "folders.json"


def _read_folders() -> list[str]:
    path = _folders_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("folders", [])
    except Exception:
        return []


def _write_folders(folders: list[str]) -> None:
    _atomic_write_json(_folders_path(), {"folders": folders})


def _validate_folder_name(name: str) -> str:
    """Validate and return stripped folder name. Raises ValueError on invalid."""
    name = name.strip()
    if not name:
        raise ValueError("Folder name cannot be empty")
    if len(name) > _FOLDER_NAME_MAX_LEN:
        raise ValueError(f"Folder name too long (max {_FOLDER_NAME_MAX_LEN})")
    if _FOLDER_NAME_INVALID_CHARS.search(name):
        raise ValueError("Folder name contains invalid characters")
    return name


def list_folders() -> list[dict]:
    """Return all folders with session counts."""
    with _folders_lock:
        folder_names = _read_folders()

    counts: dict[str, int] = {name: 0 for name in folder_names}
    if settings.sessions_dir.exists():
        for session_dir in settings.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            meta_path = session_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                folder = data.get("folder", "")
                if folder and folder in counts:
                    counts[folder] += 1
            except Exception:
                continue

    return [{"name": name, "count": counts.get(name, 0)} for name in folder_names]


def create_folder(name: str) -> str:
    """Create a new folder. Returns the folder name."""
    name = _validate_folder_name(name)
    with _folders_lock:
        folders = _read_folders()
        if name in folders:
            raise ValueError(f"Folder '{name}' already exists")
        if len(folders) >= _FOLDER_MAX_COUNT:
            raise ValueError(f"Maximum folder count ({_FOLDER_MAX_COUNT}) reached")
        folders.append(name)
        _write_folders(folders)
    logger.info("Created folder: %s", name)
    return name


def rename_folder(old_name: str, new_name: str) -> int:
    """Rename a folder and update all sessions. Returns updated session count."""
    new_name = _validate_folder_name(new_name)
    with _folders_lock:
        folders = _read_folders()
        if old_name not in folders:
            raise FileNotFoundError(f"Folder '{old_name}' not found")
        if new_name in folders:
            raise ValueError(f"Folder '{new_name}' already exists")
        folders[folders.index(old_name)] = new_name
        _write_folders(folders)

    updated = 0
    if settings.sessions_dir.exists():
        for session_dir in settings.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            meta_path = session_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                if data.get("folder") == old_name:
                    data["folder"] = new_name
                    _atomic_write_json(meta_path, data)
                    updated += 1
            except Exception:
                continue
    logger.info("Renamed folder '%s' -> '%s' (%d sessions updated)", old_name, new_name, updated)
    return updated


def delete_folder(folder_name: str) -> tuple[int, list[str]]:
    """Delete a folder and all its sessions. Returns (deleted_count, failed_ids)."""
    with _folders_lock:
        folders = _read_folders()
        if folder_name not in folders:
            raise FileNotFoundError(f"Folder '{folder_name}' not found")
        folders.remove(folder_name)
        _write_folders(folders)

    deleted = 0
    failed: list[str] = []
    if settings.sessions_dir.exists():
        for session_dir in settings.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            meta_path = session_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                if data.get("folder") == folder_name:
                    shutil.rmtree(session_dir)
                    deleted += 1
            except Exception:
                failed.append(session_dir.name)
    logger.info("Deleted folder '%s' (%d sessions deleted, %d failed)", folder_name, deleted, len(failed))
    return deleted, failed


def folder_exists(folder_name: str) -> bool:
    """Check if a folder exists."""
    with _folders_lock:
        return folder_name in _read_folders()
