import json
from pathlib import Path

import numpy as np
import soundfile as sf

from tools.evaluate_lora_manifest import evaluate_manifest


def write_audio(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = np.zeros(int(duration_s * sample_rate), dtype=np.float32)
    sf.write(path, audio, sample_rate, subtype="PCM_16")


def test_evaluate_manifest_writes_summary_and_per_sample_rows(tmp_path):
    review_dir = tmp_path / "review"
    write_audio(review_dir / "audio" / "a.wav")
    write_audio(review_dir / "audio" / "b.wav")
    manifest = review_dir / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "audio_filepath": "audio/a.wav",
                        "text": "正しい文字",
                        "current_text": "正しい文字",
                        "changed": False,
                        "duration_s": 1.0,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "audio_filepath": "audio/b.wav",
                        "text": "屋根材",
                        "current_text": "屋ね材",
                        "changed": True,
                        "duration_s": 1.0,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    predictions = iter(["正しい文字", "屋根"])

    def fake_transcribe(audio, sample_rate):
        return {"text": next(predictions), "avg_logprob": -0.1, "no_speech_prob": 0.0}

    summary = evaluate_manifest(
        review_dir=review_dir,
        manifest_path=manifest,
        output_prefix=review_dir / "baseline",
        transcribe_fn=fake_transcribe,
    )

    assert summary["total_rows"] == 2
    assert summary["current_cer"] == 0.125
    assert summary["model_cer"] == 0.125
    assert summary["changed_rows"] == 1
    assert (review_dir / "baseline_summary.json").exists()
    csv_text = (review_dir / "baseline_predictions.csv").read_text(encoding="utf-8-sig")
    assert "屋根材" in csv_text
    assert "屋根" in csv_text


def test_evaluate_manifest_can_limit_rows(tmp_path):
    review_dir = tmp_path / "review"
    write_audio(review_dir / "audio" / "a.wav")
    manifest = review_dir / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(
                {
                    "audio_filepath": "audio/a.wav",
                    "text": "a",
                    "current_text": "b",
                    "duration_s": 1.0,
                }
            )
            for _ in range(3)
        )
        + "\n",
        encoding="utf-8",
    )

    summary = evaluate_manifest(
        review_dir=review_dir,
        manifest_path=manifest,
        output_prefix=review_dir / "limited",
        transcribe_fn=lambda audio, sample_rate: {"text": "a"},
        limit=2,
    )

    assert summary["total_rows"] == 2
