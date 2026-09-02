import json
from pathlib import Path

import pytest

from tools.train_kotoba_lora import (
    DEFAULT_BASE_MODEL,
    check_training_environment,
    load_manifest_records,
    resolve_training_paths,
)


def test_resolve_training_paths_defaults_to_review_sample_outputs(tmp_path):
    review_dir = tmp_path / "review"

    paths = resolve_training_paths(review_dir=review_dir)

    assert paths.train_jsonl == review_dir / "train.jsonl"
    assert paths.validation_jsonl == review_dir / "validation.jsonl"
    assert paths.output_dir == review_dir / "lora_kotoba_v2"
    assert paths.base_model == DEFAULT_BASE_MODEL


def test_load_manifest_records_requires_existing_audio(tmp_path):
    review_dir = tmp_path / "review"
    manifest = review_dir / "train.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "audio_filepath": "audio/missing.wav",
                "text": "屋根材",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="audio file not found"):
        load_manifest_records(manifest, review_dir)


def test_check_training_environment_reports_missing_packages(monkeypatch):
    def fake_find_spec(name):
        if name == "torch":
            class Spec:
                pass

            return Spec()
        return None

    monkeypatch.setattr("tools.train_kotoba_lora.importlib.util.find_spec", fake_find_spec)

    report = check_training_environment()

    assert "transformers" in report["missing_packages"]
    assert report["ok"] is False
