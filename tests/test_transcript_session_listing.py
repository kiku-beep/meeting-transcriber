import json

from backend.storage import file_store
from backend.config import settings


def test_list_sessions_uses_metadata_without_scanning_session_contents(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    session_dir = settings.sessions_dir / "2026-06-14_160000"
    session_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps(
            {
                "session_id": "2026-06-14_160000",
                "session_name": "一覧高速化テスト",
                "entry_count": 1,
                "saved_at": "2026-06-14T16:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    screenshots = session_dir / "screenshots"
    screenshots.mkdir()
    (screenshots / "large.jpg").write_bytes(b"x" * 1024)

    def fail_if_scanned(_path):
      raise AssertionError("list_sessions should not recursively scan session contents")

    monkeypatch.setattr(file_store, "_dir_size", fail_if_scanned)

    sessions = file_store.list_sessions()

    assert sessions == [
        {
            "session_id": "2026-06-14_160000",
            "session_name": "一覧高速化テスト",
            "entry_count": 1,
            "saved_at": "2026-06-14T16:00:00",
        }
    ]
