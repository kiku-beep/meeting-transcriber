import csv
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from tools.build_lora_review_samples import build_review_samples


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def write_recording(path: Path, duration_s: float = 4.0, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = int(duration_s * sample_rate)
    audio = np.linspace(-0.5, 0.5, samples, dtype=np.float32)
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def test_build_review_samples_prefers_human_corrections_and_cuts_audio(tmp_path):
    data_dir = tmp_path / "data"
    session_dir = data_dir / "sessions" / "2026-01-01_120000"
    output_dir = tmp_path / "review_samples"

    write_recording(session_dir / "recording.wav", duration_s=4.0)
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "entry-a",
                "text": "ルーファンEを使います",
                "raw_text": "ルーファンEを使います",
                "timestamp_start": 0.5,
                "timestamp_end": 1.5,
            },
            {
                "id": "entry-b",
                "text": "短すぎる",
                "raw_text": "短すぎる",
                "timestamp_start": 2.0,
                "timestamp_end": 2.4,
            },
            {
                "id": "entry-c",
                "text": "外装材の説明です",
                "raw_text": "外装材の説明です",
                "timestamp_start": 2.5,
                "timestamp_end": 3.7,
            },
        ],
    )
    write_json(
        data_dir / "corrections.json",
        [
            {
                "field": "text",
                "session_id": "2026-01-01_120000",
                "entry_id": "entry-a",
                "original": "ルーファンEを使います",
                "corrected": "Roof-1Eを使います",
            },
            {
                "field": "text",
                "session_id": "2026-01-01_120000",
                "entry_id": "missing-entry",
                "original": "存在しない",
                "corrected": "無視する",
            },
        ],
    )

    rows = build_review_samples(data_dir=data_dir, output_dir=output_dir, limit=2, seed=7)

    assert [row["entry_id"] for row in rows] == ["entry-a", "entry-c"]
    assert rows[0]["corrected_text"] == "Roof-1Eを使います"
    assert rows[1]["corrected_text"] == "外装材の説明です"

    csv_path = output_dir / "review.csv"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        csv_rows = list(csv.DictReader(f))

    assert [row["entry_id"] for row in csv_rows] == ["entry-a", "entry-c"]
    assert set(csv_rows[0]) == {
        "audio_path",
        "current_text",
        "corrected_text",
        "session_id",
        "entry_id",
        "start",
        "end",
    }

    first_audio = output_dir / csv_rows[0]["audio_path"]
    audio, sample_rate = sf.read(first_audio, dtype="float32")
    assert sample_rate == 16000
    assert abs((len(audio) / sample_rate) - 1.0) < 0.05


def test_build_review_samples_finds_nested_session_directories(tmp_path):
    data_dir = tmp_path / "data"
    session_dir = data_dir / "sessions" / "sessions" / "2026-01-02_090000"
    output_dir = tmp_path / "review_samples"

    write_recording(session_dir / "recording.wav", duration_s=3.0)
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "nested",
                "text": "嵌合部を確認します",
                "raw_text": "嵌合部を確認します",
                "timestamp_start": 0.25,
                "timestamp_end": 1.75,
            }
        ],
    )
    write_json(data_dir / "corrections.json", [])

    rows = build_review_samples(data_dir=data_dir, output_dir=output_dir, limit=10, seed=1)

    assert len(rows) == 1
    assert rows[0]["session_id"] == "2026-01-02_090000"
    assert (output_dir / rows[0]["audio_path"]).exists()


def test_build_review_samples_uses_segments_when_recording_is_missing(tmp_path):
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / "transcriber-sessions"
    session_dir = sessions_dir / "2026-05-18_120000"
    output_dir = tmp_path / "review_samples"

    write_recording(session_dir / "segments" / "seg_10.0s_peak0.5000.wav", duration_s=4.0)
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "recent-segment",
                "text": "水密性を確認します",
                "raw_text": "水密性を確認します",
                "timestamp_start": 11.0,
                "timestamp_end": 12.5,
            }
        ],
    )
    write_json(data_dir / "corrections.json", [])

    rows = build_review_samples(
        data_dir=data_dir,
        output_dir=output_dir,
        sessions_dir=sessions_dir,
        min_session_id="2026-05-18",
        limit=10,
        seed=1,
    )

    assert len(rows) == 1
    assert rows[0]["session_id"] == "2026-05-18_120000"

    audio, sample_rate = sf.read(output_dir / rows[0]["audio_path"], dtype="float32")
    assert sample_rate == 16000
    assert abs((len(audio) / sample_rate) - 1.5) < 0.05


def test_build_review_samples_excludes_sessions_before_min_session_id(tmp_path):
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / "transcriber-sessions"
    output_dir = tmp_path / "review_samples"

    old_dir = sessions_dir / "2026-02-27_120000"
    write_recording(old_dir / "segments" / "seg_0.0s_peak0.5000.wav", duration_s=3.0)
    write_json(
        old_dir / "transcript.json",
        [
            {
                "id": "old",
                "text": "古い録音です",
                "timestamp_start": 0.0,
                "timestamp_end": 2.0,
            }
        ],
    )

    recent_dir = sessions_dir / "2026-05-18_120000"
    write_recording(recent_dir / "segments" / "seg_0.0s_peak0.5000.wav", duration_s=3.0)
    write_json(
        recent_dir / "transcript.json",
        [
            {
                "id": "recent",
                "text": "最近の録音です",
                "timestamp_start": 0.0,
                "timestamp_end": 2.0,
            }
        ],
    )
    write_json(data_dir / "corrections.json", [])

    rows = build_review_samples(
        data_dir=data_dir,
        output_dir=output_dir,
        sessions_dir=sessions_dir,
        min_session_id="2026-05-18",
        limit=10,
        seed=1,
    )

    assert [row["entry_id"] for row in rows] == ["recent"]


def test_build_review_samples_indexes_segments_once_per_session(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / "transcriber-sessions"
    session_dir = sessions_dir / "2026-05-18_120000"
    output_dir = tmp_path / "review_samples"

    write_recording(session_dir / "segments" / "seg_0.0s_peak0.5000.wav", duration_s=5.0)
    write_recording(session_dir / "segments" / "seg_10.0s_peak0.5000.wav", duration_s=5.0)
    write_json(
        session_dir / "transcript.json",
        [
            {
                "id": "entry-a",
                "text": "水密性の確認です",
                "timestamp_start": 0.5,
                "timestamp_end": 2.0,
            },
            {
                "id": "entry-b",
                "text": "漏水量を見ます",
                "timestamp_start": 2.2,
                "timestamp_end": 3.7,
            },
            {
                "id": "entry-c",
                "text": "エプトシーラーです",
                "timestamp_start": 10.5,
                "timestamp_end": 12.0,
            },
        ],
    )
    write_json(data_dir / "corrections.json", [])

    original_info = sf.info
    call_count = 0

    def counting_info(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_info(*args, **kwargs)

    monkeypatch.setattr("tools.build_lora_review_samples.sf.info", counting_info)

    rows = build_review_samples(
        data_dir=data_dir,
        output_dir=output_dir,
        sessions_dir=sessions_dir,
        min_session_id="2026-05-18",
        limit=3,
        seed=1,
    )

    assert len(rows) == 3
    assert call_count <= 5
