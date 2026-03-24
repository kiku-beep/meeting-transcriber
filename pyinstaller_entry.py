"""PyInstaller entry point for Transcriber backend sidecar."""
import argparse
import os
import shutil
import sys


def get_base_dir():
    """Get the application base directory.

    In PyInstaller --onedir mode, the exe is in sidecar/ subdir,
    so base dir is one level up (the install directory).
    In normal Python, base dir is the project root.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_appdata_dir():
    """Get %APPDATA%/transcriber as the standard data directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "transcriber")
    return None


def _migrate_items(src_base, dst_base, items):
    """Move items from src_base to dst_base (skip if dst already has data)."""
    if not os.path.isdir(src_base):
        return
    if os.path.normpath(src_base) == os.path.normpath(dst_base):
        return

    has_src = any(os.path.exists(os.path.join(src_base, i)) for i in items)
    if not has_src:
        return
    has_dst = any(os.path.exists(os.path.join(dst_base, i)) for i in items)
    if has_dst:
        return

    print(f"[migrate] Moving from {src_base} -> {dst_base}")
    os.makedirs(dst_base, exist_ok=True)
    for item in items:
        src = os.path.join(src_base, item)
        dst = os.path.join(dst_base, item)
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        try:
            shutil.move(src, dst)
            print(f"  [migrate] Moved: {item}")
        except Exception:
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                print(f"  [migrate] Copied: {item}")
            except Exception as e:
                print(f"  [migrate] WARNING: Failed to migrate {item}: {e}")


def migrate_legacy_data(legacy_dir, data_dir, sessions_dir):
    """Migrate from old exe-relative data/ to split locations."""
    # Light data → AppData
    _migrate_items(legacy_dir, data_dir, ["speakers", "dictionary.json", "corrections.json"])
    # Heavy data → sessions dir (same drive as exe)
    legacy_sessions = os.path.join(legacy_dir, "sessions")
    if os.path.isdir(legacy_sessions) and os.listdir(legacy_sessions):
        if os.path.normpath(legacy_sessions) != os.path.normpath(sessions_dir):
            if not os.path.isdir(sessions_dir) or not os.listdir(sessions_dir):
                print(f"[migrate] Moving sessions {legacy_sessions} -> {sessions_dir}")
                os.makedirs(os.path.dirname(sessions_dir), exist_ok=True)
                try:
                    shutil.move(legacy_sessions, sessions_dir)
                    print("  [migrate] Sessions moved")
                except Exception:
                    try:
                        shutil.copytree(legacy_sessions, sessions_dir)
                        print("  [migrate] Sessions copied")
                    except Exception as e:
                        print(f"  [migrate] WARNING: Failed to migrate sessions: {e}")


def load_env_file(env_path):
    """Load a .env file into environment variables (setdefault)."""
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)


def main():
    parser = argparse.ArgumentParser(description="Transcriber Backend Sidecar")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--sessions-dir", default=None)
    parser.add_argument("--legacy-data-dir", default=None)
    args = parser.parse_args()

    base_dir = get_base_dir()

    # Light data (dict, speakers, corrections) → AppData
    data_dir = args.data_dir or get_appdata_dir() or os.path.join(base_dir, "data")
    os.environ["DATA_DIR"] = data_dir
    os.makedirs(data_dir, exist_ok=True)

    # Heavy data (sessions with audio/screenshots) → same drive as exe
    sessions_dir = args.sessions_dir or os.path.join(data_dir, "sessions")
    os.environ["SESSIONS_DIR"] = sessions_dir
    os.makedirs(sessions_dir, exist_ok=True)

    # Auto-migrate from old exe-relative location
    legacy_dir = args.legacy_data_dir or os.path.join(base_dir, "data")
    migrate_legacy_data(legacy_dir, data_dir, sessions_dir)

    # Redirect stdout/stderr to log file when running as frozen exe
    if getattr(sys, "frozen", False):
        log_path = os.path.join(data_dir, "backend.log")
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
        import atexit
        atexit.register(log_file.flush)

    # Load .env from AppData (survives redeployment), fallback to base dir
    appdata_env = os.path.join(data_dir, ".env")
    base_env = os.path.join(base_dir, ".env")
    # Migrate old .env from install dir to AppData
    if not os.path.exists(appdata_env) and os.path.exists(base_env):
        shutil.copy2(base_env, appdata_env)
    load_env_file(appdata_env)
    load_env_file(base_env)  # fallback for any missing keys

    # Patch huggingface_hub BEFORE any ML library imports.
    # SpeechBrain 1.0.x passes deprecated kwargs (use_auth_token, force_filename,
    # local_dir_use_symlinks) that were removed in huggingface_hub >=1.0.
    # Also: SpeechBrain catches requests.HTTPError for 404, but huggingface_hub >=1.0
    # raises its own EntryNotFoundError hierarchy instead.
    import huggingface_hub as _hfh
    import huggingface_hub.file_download as _hfh_fd
    from huggingface_hub import errors as _hfh_errors
    from requests.exceptions import HTTPError as _RequestsHTTPError

    _orig_hf_download = _hfh.hf_hub_download

    def _patched_hf_hub_download(*args, **kwargs):
        kwargs.pop("local_dir_use_symlinks", None)
        kwargs.pop("force_filename", None)
        if "use_auth_token" in kwargs:
            kwargs.setdefault("token", kwargs.pop("use_auth_token"))
        try:
            return _orig_hf_download(*args, **kwargs)
        except (
            getattr(_hfh_errors, "EntryNotFoundError", Exception),
            getattr(_hfh_errors, "RemoteEntryNotFoundError", Exception),
        ) as e:
            raise _RequestsHTTPError(f"404 Client Error: {e}") from e

    _patched_hf_hub_download._patched = True
    _hfh.hf_hub_download = _patched_hf_hub_download
    _hfh_fd.hf_hub_download = _patched_hf_hub_download

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
