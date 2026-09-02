"""Tests for persisted topic-tree session data."""

from __future__ import annotations

import pytest


def _entry():
    from backend.models.schemas import TranscriptEntry

    return TranscriptEntry(
        id="entry-1",
        text="発言",
        raw_text="発言",
        timestamp_start=0.0,
        timestamp_end=1.0,
    )


def _tree():
    from backend.core.topic_tree import TopicNode, TopicTree

    return TopicTree(
        nodes=[
            TopicNode(
                id="topic-1",
                label="価格",
                status="decided",
                start_sec=1.0,
                end_sec=2.0,
            )
        ],
        active="topic-1",
    )


def test_save_session_round_trips_topics_and_metadata_count(monkeypatch, tmp_path):
    from backend.storage import file_store
    from backend.core.topic_tree import tree_to_dict

    sessions_dir = tmp_path / "sessions"
    monkeypatch.setenv("SESSIONS_DIR", str(sessions_dir))
    tree = _tree()

    session_dir = file_store.save_session("topic-session", [_entry()], {}, tree)

    assert (session_dir / "topics.json").exists()
    assert file_store.load_topics("topic-session") == tree_to_dict(tree)
    metadata = file_store.load_session_metadata("topic-session")
    assert metadata["topic_count"] == 1


def test_save_session_does_not_create_topics_file_for_empty_tree(monkeypatch, tmp_path):
    from backend.storage import file_store
    from backend.core.topic_tree import TopicTree

    sessions_dir = tmp_path / "sessions"
    monkeypatch.setenv("SESSIONS_DIR", str(sessions_dir))

    session_dir = file_store.save_session(
        "empty-topic-session",
        [_entry()],
        topic_tree=TopicTree(),
    )

    assert not (session_dir / "topics.json").exists()
    metadata = file_store.load_session_metadata("empty-topic-session")
    assert metadata["topic_count"] == 0


def test_load_topics_returns_empty_tree_for_missing_session(monkeypatch, tmp_path):
    from backend.storage import file_store

    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))

    assert file_store.load_topics("missing-topic-session") == {
        "nodes": [],
        "active": None,
    }


def test_load_topics_rejects_path_traversal_session_id(monkeypatch, tmp_path):
    from backend.storage import file_store

    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))

    with pytest.raises(ValueError):
        file_store.load_topics("../outside")


def test_load_topics_degrades_to_empty_tree_for_unreadable_file(monkeypatch, tmp_path):
    """壊れた topics.json で例外を投げないこと。

    このマシンはゼロ埋めでファイルがNUL化する実績があり、履歴画面から
    呼ばれる load_topics が JSONDecodeError で落ちると画面全体が死ぬ。
    """
    from backend.storage import file_store

    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    session_dir = file_store.settings.sessions_dir / "2026-01-01_000000"
    session_dir.mkdir(parents=True)

    # 途中で切れたJSON
    (session_dir / "topics.json").write_text('{"nodes": [truncated', encoding="utf-8")
    assert file_store.load_topics("2026-01-01_000000") == {"nodes": [], "active": None}

    # ゼロ埋め（全NUL）
    (session_dir / "topics.json").write_bytes(b"\x00" * 64)
    assert file_store.load_topics("2026-01-01_000000") == {"nodes": [], "active": None}

    # JSONとしては妥当だが形が違う
    (session_dir / "topics.json").write_text('["not", "a", "tree"]', encoding="utf-8")
    assert file_store.load_topics("2026-01-01_000000") == {"nodes": [], "active": None}
