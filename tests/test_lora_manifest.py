import json
from pathlib import Path

import numpy as np
import soundfile as sf

from tools.build_lora_manifest import build_lora_manifest


def write_audio(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.zeros(int(duration_s * sample_rate), dtype=np.float32)
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def test_build_lora_manifest_uses_corrected_text_and_relative_audio(tmp_path):
    review_dir = tmp_path / "review_samples"
    write_audio(review_dir / "audio" / "a.wav", duration_s=1.25)
    write_audio(review_dir / "audio" / "b.wav", duration_s=2.0)
    (review_dir / "review.csv").write_text(
        "\ufeffaudio_path,current_text,corrected_text,session_id,entry_id,start,end\n"
        "audio/a.wav,誤り,正しい文字,session-a,entry-a,0.000,1.250\n"
        "audio/b.wav,そのまま,そのまま,session-b,entry-b,2.000,4.000\n",
        encoding="utf-8",
    )

    summary = build_lora_manifest(review_dir=review_dir, validation_ratio=0.5, seed=1)

    manifest_rows = [
        json.loads(line)
        for line in (review_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    train_rows = (review_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()
    validation_rows = (review_dir / "validation.jsonl").read_text(encoding="utf-8").splitlines()

    assert summary["total_rows"] == 2
    assert summary["changed_rows"] == 1
    assert len(train_rows) == 1
    assert len(validation_rows) == 1
    assert manifest_rows[0]["audio_filepath"] == "audio/a.wav"
    assert manifest_rows[0]["text"] == "正しい文字"
    assert manifest_rows[0]["current_text"] == "誤り"
    assert manifest_rows[0]["duration_s"] == 1.25


def test_build_lora_manifest_rejects_blank_corrected_text(tmp_path):
    review_dir = tmp_path / "review_samples"
    write_audio(review_dir / "audio" / "a.wav")
    (review_dir / "review.csv").write_text(
        "audio_path,current_text,corrected_text,session_id,entry_id,start,end\n"
        "audio/a.wav,誤り,,session-a,entry-a,0.000,1.000\n",
        encoding="utf-8",
    )

    try:
        build_lora_manifest(review_dir=review_dir)
    except ValueError as exc:
        assert "corrected_text" in str(exc)
    else:
        raise AssertionError("blank corrected_text should fail")
