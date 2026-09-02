"""Build JSONL manifests from corrected LoRA review samples."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

import soundfile as sf


REQUIRED_COLUMNS = {
    "audio_path",
    "current_text",
    "corrected_text",
    "session_id",
    "entry_id",
    "start",
    "end",
}


def _clean_text(value) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _load_review_rows(review_csv: Path) -> list[dict[str, str]]:
    with review_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"review.csv is missing columns: {', '.join(missing)}")
        return [dict(row) for row in reader]


def _build_record(review_dir: Path, row: dict[str, str], row_number: int) -> dict:
    audio_path = _clean_text(row.get("audio_path"))
    current_text = _clean_text(row.get("current_text"))
    corrected_text = _clean_text(row.get("corrected_text"))
    if not audio_path:
        raise ValueError(f"row {row_number}: audio_path is blank")
    if not corrected_text:
        raise ValueError(f"row {row_number}: corrected_text is blank")

    audio_file = review_dir / audio_path
    if not audio_file.exists():
        raise ValueError(f"row {row_number}: audio file not found: {audio_path}")

    info = sf.info(str(audio_file))
    try:
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or 0.0)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: invalid start/end") from exc

    return {
        "audio_filepath": audio_path.replace("\\", "/"),
        "text": corrected_text,
        "current_text": current_text,
        "changed": corrected_text != current_text,
        "session_id": _clean_text(row.get("session_id")),
        "entry_id": _clean_text(row.get("entry_id")),
        "start": start,
        "end": end,
        "duration_s": round(float(info.duration), 3),
        "sample_rate": int(info.samplerate),
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")


def build_lora_manifest(
    review_dir: Path,
    validation_ratio: float = 0.1,
    seed: int = 42,
    changed_only: bool = False,
) -> dict:
    """Convert corrected review.csv rows into train/validation JSONL files."""
    review_dir = Path(review_dir)
    review_csv = review_dir / "review.csv"
    rows = _load_review_rows(review_csv)

    records = [
        _build_record(review_dir, row, index)
        for index, row in enumerate(rows, start=2)
    ]
    if changed_only:
        records = [record for record in records if record["changed"]]
    if not records:
        raise ValueError("no usable rows found in review.csv")

    rng = random.Random(seed)
    split_records = records.copy()
    rng.shuffle(split_records)
    validation_count = int(round(len(split_records) * validation_ratio))
    if len(split_records) >= 2:
        validation_count = max(1, min(validation_count, len(split_records) - 1))
    else:
        validation_count = 0

    validation_records = split_records[:validation_count]
    train_records = split_records[validation_count:]

    _write_jsonl(review_dir / "manifest.jsonl", records)
    _write_jsonl(review_dir / "train.jsonl", train_records)
    _write_jsonl(review_dir / "validation.jsonl", validation_records)

    summary = {
        "total_rows": len(records),
        "train_rows": len(train_records),
        "validation_rows": len(validation_records),
        "changed_rows": sum(1 for record in records if record["changed"]),
        "unchanged_rows": sum(1 for record in records if not record["changed"]),
        "total_duration_s": round(sum(record["duration_s"] for record in records), 3),
        "review_csv": str(review_csv),
        "manifest_jsonl": str(review_dir / "manifest.jsonl"),
        "train_jsonl": str(review_dir / "train.jsonl"),
        "validation_jsonl": str(review_dir / "validation.jsonl"),
        "validation_ratio": validation_ratio,
        "seed": seed,
        "changed_only": changed_only,
    }
    (review_dir / "metadata.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _default_review_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "training_data" / "review_samples_recent"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Whisper LoRA training manifests from corrected review.csv.",
    )
    parser.add_argument("--review-dir", type=Path, default=_default_review_dir())
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--changed-only", action="store_true")
    args = parser.parse_args()

    summary = build_lora_manifest(
        review_dir=args.review_dir,
        validation_ratio=args.validation_ratio,
        seed=args.seed,
        changed_only=args.changed_only,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
