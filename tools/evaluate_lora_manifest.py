"""Evaluate ASR output against a corrected LoRA manifest."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Callable

import soundfile as sf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TranscribeFn = Callable[[object, int], dict]


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char_a != char_b),
                )
            )
        previous = current
    return previous[-1]


def _clean_text(value) -> str:
    return str(value or "").strip()


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _default_transcriber(model: str) -> TranscribeFn:
    from backend.core.transcriber import Transcriber

    transcriber = Transcriber(model)
    transcriber.load_model()
    return transcriber.transcribe


def _safe_rate(distance: int, total: int) -> float:
    return round(distance / total, 6) if total else 0.0


def evaluate_manifest(
    review_dir: Path,
    manifest_path: Path,
    output_prefix: Path,
    transcribe_fn: TranscribeFn | None = None,
    model: str = "kotoba-v2.0",
    limit: int | None = None,
) -> dict:
    review_dir = Path(review_dir)
    manifest_path = Path(manifest_path)
    output_prefix = Path(output_prefix)
    records = _load_jsonl(manifest_path)
    if limit is not None:
        records = records[:limit]
    if not records:
        raise ValueError("manifest has no records to evaluate")

    transcribe = transcribe_fn or _default_transcriber(model)
    rows: list[dict] = []
    total_ref_chars = 0
    total_current_distance = 0
    total_model_distance = 0
    total_audio_s = 0.0
    total_transcribe_s = 0.0

    for index, record in enumerate(records, start=1):
        audio_path = _clean_text(record.get("audio_filepath"))
        reference = _clean_text(record.get("text"))
        current_text = _clean_text(record.get("current_text"))
        if not audio_path:
            raise ValueError(f"record {index}: audio_filepath is blank")
        if not reference:
            raise ValueError(f"record {index}: text is blank")

        audio_file = review_dir / audio_path
        if not audio_file.exists():
            raise ValueError(f"record {index}: audio file not found: {audio_path}")

        audio, sample_rate = sf.read(str(audio_file), dtype="float32")
        start = time.monotonic()
        result = transcribe(audio, sample_rate)
        elapsed = time.monotonic() - start
        prediction = _clean_text(result.get("text"))

        ref_chars = len(reference)
        current_distance = edit_distance(current_text, reference)
        model_distance = edit_distance(prediction, reference)
        duration_s = float(record.get("duration_s") or (len(audio) / sample_rate))

        total_ref_chars += ref_chars
        total_current_distance += current_distance
        total_model_distance += model_distance
        total_audio_s += duration_s
        total_transcribe_s += elapsed

        rows.append(
            {
                "index": index,
                "audio_filepath": audio_path,
                "reference": reference,
                "current_text": current_text,
                "prediction": prediction,
                "changed": bool(record.get("changed", current_text != reference)),
                "ref_chars": ref_chars,
                "current_distance": current_distance,
                "model_distance": model_distance,
                "current_cer": _safe_rate(current_distance, ref_chars),
                "model_cer": _safe_rate(model_distance, ref_chars),
                "duration_s": round(duration_s, 3),
                "transcribe_s": round(elapsed, 3),
                "rtf": round(elapsed / duration_s, 6) if duration_s else 0.0,
                "avg_logprob": result.get("avg_logprob", ""),
                "no_speech_prob": result.get("no_speech_prob", ""),
                "confidence": result.get("confidence", ""),
            }
        )

    predictions_path = output_prefix.with_name(output_prefix.name + "_predictions.csv")
    summary_path = output_prefix.with_name(output_prefix.name + "_summary.json")

    with predictions_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    changed_rows = [row for row in rows if row["changed"]]
    changed_ref_chars = sum(int(row["ref_chars"]) for row in changed_rows)
    changed_current_distance = sum(int(row["current_distance"]) for row in changed_rows)
    changed_model_distance = sum(int(row["model_distance"]) for row in changed_rows)

    summary = {
        "model": model,
        "total_rows": len(rows),
        "changed_rows": len(changed_rows),
        "unchanged_rows": len(rows) - len(changed_rows),
        "total_audio_s": round(total_audio_s, 3),
        "total_transcribe_s": round(total_transcribe_s, 3),
        "rtf": round(total_transcribe_s / total_audio_s, 6) if total_audio_s else 0.0,
        "ref_chars": total_ref_chars,
        "current_distance": total_current_distance,
        "model_distance": total_model_distance,
        "current_cer": _safe_rate(total_current_distance, total_ref_chars),
        "model_cer": _safe_rate(total_model_distance, total_ref_chars),
        "changed_current_cer": _safe_rate(changed_current_distance, changed_ref_chars),
        "changed_model_cer": _safe_rate(changed_model_distance, changed_ref_chars),
        "manifest_path": str(manifest_path),
        "predictions_csv": str(predictions_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _default_review_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "training_data" / "review_samples_recent"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate current ASR against corrected review samples.",
    )
    parser.add_argument("--review-dir", type=Path, default=_default_review_dir())
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output-prefix", type=Path, default=None)
    parser.add_argument("--model", default="kotoba-v2.0")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    review_dir = args.review_dir
    manifest = args.manifest or (review_dir / "manifest.jsonl")
    output_prefix = args.output_prefix or (review_dir / "baseline")
    summary = evaluate_manifest(
        review_dir=review_dir,
        manifest_path=manifest,
        output_prefix=output_prefix,
        model=args.model,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
