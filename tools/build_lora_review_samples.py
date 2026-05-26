"""Build review samples for local Whisper LoRA fine-tuning.

The generated CSV is meant for human correction.  The corrected_text column can
then be used as the supervised label for a later fine-tuning dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


CSV_COLUMNS = [
    "audio_path",
    "current_text",
    "corrected_text",
    "session_id",
    "entry_id",
    "start",
    "end",
]

MIN_DURATION_S = 1.0
MAX_DURATION_S = 15.0
TARGET_SAMPLE_RATE = 16000
SEGMENT_NAME_RE = re.compile(r"^seg_([0-9]+(?:\.[0-9]+)?)s_")

BASE_DOMAIN_TERMS = {
    "Roof-1",
    "Roof-1E",
    "ルーフ",
    "ルーファン",
    "屋根",
    "屋根材",
    "壁材",
    "外壁",
    "外装材",
    "防耐火",
    "耐火",
    "準耐火",
    "認定",
    "告示",
    "嵌合",
    "板金",
    "塗膜",
    "エプトシーラー",
    "ニチハ",
    "サイディング",
    "下地",
    "保証",
    "メンテナンス",
    "通則",
}


@dataclass(frozen=True)
class ReviewCandidate:
    session_id: str
    session_dir: Path
    audio_path: Path
    clip_start: float
    clip_end: float
    entry_id: str
    current_text: str
    corrected_text: str
    start: float
    end: float
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class SegmentSource:
    path: Path
    start: float
    end: float
    duration: float


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _clean_text(value) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _load_text_corrections(data_dir: Path) -> dict[tuple[str, str], str]:
    corrections = _read_json(data_dir / "corrections.json", [])
    result: dict[tuple[str, str], str] = {}
    if not isinstance(corrections, list):
        return result

    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        if correction.get("field") != "text":
            continue
        session_id = _clean_text(correction.get("session_id"))
        entry_id = _clean_text(correction.get("entry_id"))
        corrected = _clean_text(correction.get("corrected"))
        if not session_id or not entry_id or not corrected:
            continue
        result[(session_id, entry_id)] = corrected
    return result


def _load_domain_terms(data_dir: Path) -> set[str]:
    terms = set(BASE_DOMAIN_TERMS)
    dictionary = _read_json(data_dir / "dictionary.json", {})
    replacements = dictionary.get("replacements", []) if isinstance(dictionary, dict) else []
    if not isinstance(replacements, list):
        return terms

    for replacement in replacements:
        if not isinstance(replacement, dict):
            continue
        if replacement.get("enabled", True) is False:
            continue
        for key in ("from", "to"):
            term = _clean_text(replacement.get(key))
            if len(term) >= 2:
                terms.add(term)
    return terms


def _score_domain_terms(text: str, terms: set[str]) -> int:
    return sum(1 for term in terms if term and term in text)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "sample"


def _iter_session_dirs(
    data_dir: Path,
    sessions_dir: Path | None = None,
    min_session_id: str | None = None,
) -> list[Path]:
    sessions_root = sessions_dir or (data_dir / "sessions")
    if not sessions_root.exists():
        return []
    session_dirs = sorted(path.parent for path in sessions_root.rglob("transcript.json"))
    if min_session_id:
        session_dirs = [
            session_dir
            for session_dir in session_dirs
            if session_dir.name >= min_session_id
        ]
    return session_dirs


def _parse_entry_time(entry: dict) -> tuple[float, float] | None:
    try:
        start = float(entry.get("timestamp_start"))
        end = float(entry.get("timestamp_end"))
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    return start, end


def _parse_segment_start(path: Path) -> float | None:
    match = SEGMENT_NAME_RE.match(path.name)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _build_segment_index(session_dir: Path) -> list[SegmentSource]:
    segments_dir = session_dir / "segments"
    if not segments_dir.exists():
        return []

    segments: list[SegmentSource] = []
    for path in segments_dir.glob("seg_*s_*.wav"):
        segment_start = _parse_segment_start(path)
        if segment_start is None:
            continue
        try:
            info = sf.info(str(path))
        except Exception:
            continue
        duration = float(info.duration)
        segments.append(
            SegmentSource(
                path=path,
                start=segment_start,
                end=segment_start + duration,
                duration=duration,
            )
        )
    return sorted(segments, key=lambda segment: (segment.start, segment.path.name))


def _resolve_audio_source(
    session_dir: Path,
    start: float,
    end: float,
    segment_index: list[SegmentSource] | None = None,
) -> tuple[Path, float, float] | None:
    recording_path = session_dir / "recording.wav"
    if recording_path.exists():
        return recording_path, start, end

    segments = segment_index if segment_index is not None else _build_segment_index(session_dir)

    matches: list[tuple[float, Path, float, float]] = []
    for segment in segments:
        if start >= segment.start - 0.05 and end <= segment.end + 0.05:
            clip_start = max(0.0, start - segment.start)
            clip_end = min(segment.duration, end - segment.start)
            if clip_end > clip_start:
                matches.append((abs(start - segment.start), segment.path, clip_start, clip_end))

    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    _, path, clip_start, clip_end = matches[0]
    return path, clip_start, clip_end


def _collect_candidates(
    data_dir: Path,
    limit: int,
    seed: int,
    sessions_dir: Path | None = None,
    min_session_id: str | None = None,
) -> list[ReviewCandidate]:
    rng = random.Random(seed)
    corrections = _load_text_corrections(data_dir)
    domain_terms = _load_domain_terms(data_dir)
    candidates: list[ReviewCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for session_dir in _iter_session_dirs(data_dir, sessions_dir, min_session_id):
        session_id = session_dir.name
        transcript = _read_json(session_dir / "transcript.json", [])
        if not isinstance(transcript, list):
            continue
        segment_index: list[SegmentSource] | None = None
        if not (session_dir / "recording.wav").exists():
            segment_index = _build_segment_index(session_dir)
            if not segment_index:
                continue

        for entry in transcript:
            if not isinstance(entry, dict):
                continue
            entry_id = _clean_text(entry.get("id"))
            if not entry_id:
                continue

            times = _parse_entry_time(entry)
            if times is None:
                continue
            start, end = times
            duration = end - start
            if duration < MIN_DURATION_S or duration > MAX_DURATION_S:
                continue
            audio_source = _resolve_audio_source(session_dir, start, end, segment_index)
            if audio_source is None:
                continue
            audio_path, clip_start, clip_end = audio_source
            if clip_end - clip_start < MIN_DURATION_S:
                continue

            current_text = _clean_text(entry.get("text") or entry.get("raw_text"))
            if not current_text:
                continue

            corrected = corrections.get((session_id, entry_id))
            corrected_text = corrected or current_text
            key = (str(session_dir.resolve()), entry_id, f"{start:.3f}")
            if key in seen:
                continue
            seen.add(key)

            term_hits = _score_domain_terms(f"{current_text}\n{corrected_text}", domain_terms)
            score = rng.random()
            if corrected:
                score += 1000
            score += term_hits * 25
            if 2.0 <= duration <= 10.0:
                score += 5

            candidates.append(
                ReviewCandidate(
                    session_id=session_id,
                    session_dir=session_dir,
                    audio_path=audio_path,
                    clip_start=clip_start,
                    clip_end=clip_end,
                    entry_id=entry_id,
                    current_text=current_text,
                    corrected_text=corrected_text,
                    start=start,
                    end=end,
                    score=score,
                )
            )

    candidates.sort(
        key=lambda item: (
            -item.score,
            item.session_id,
            item.start,
            item.entry_id,
        )
    )
    return candidates[: max(limit * 5, limit)]


def _read_audio_clip(path: Path, start_s: float, end_s: float) -> tuple[np.ndarray, int]:
    info = sf.info(str(path))
    start = max(0, int(start_s * info.samplerate))
    stop = min(info.frames, int(end_s * info.samplerate))
    if stop <= start:
        raise ValueError(f"Invalid audio slice {start_s:.3f}-{end_s:.3f}: {path}")

    audio, sample_rate = sf.read(
        str(path),
        start=start,
        stop=stop,
        dtype="float32",
        always_2d=False,
    )
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != TARGET_SAMPLE_RATE:
        from math import gcd
        from scipy.signal import resample_poly

        factor = gcd(sample_rate, TARGET_SAMPLE_RATE)
        audio = resample_poly(audio, TARGET_SAMPLE_RATE // factor, sample_rate // factor).astype(np.float32)
        sample_rate = TARGET_SAMPLE_RATE
    return audio.astype(np.float32, copy=False), sample_rate


def _write_clip(candidate: ReviewCandidate, audio_dir: Path, index: int) -> str:
    start_label = f"{candidate.start:.2f}".replace(".", "p")
    end_label = f"{candidate.end:.2f}".replace(".", "p")
    filename = (
        f"{index:04d}_"
        f"{_safe_name(candidate.session_id)}_"
        f"{_safe_name(candidate.entry_id)}_"
        f"{start_label}-{end_label}.wav"
    )
    audio, sample_rate = _read_audio_clip(
        candidate.audio_path,
        candidate.clip_start,
        candidate.clip_end,
    )
    sf.write(audio_dir / filename, audio, sample_rate, subtype="PCM_16")
    return f"audio/{filename}"


def _clear_generated_audio(audio_dir: Path) -> None:
    if not audio_dir.exists():
        return
    for path in audio_dir.glob("*.wav"):
        if path.is_file():
            path.unlink()


def build_review_samples(
    data_dir: Path,
    output_dir: Path,
    limit: int = 200,
    seed: int = 42,
    sessions_dir: Path | None = None,
    min_session_id: str | None = None,
) -> list[dict[str, str]]:
    data_dir = Path(data_dir)
    if sessions_dir is not None:
        sessions_dir = Path(sessions_dir)
    output_dir = Path(output_dir)
    audio_dir = output_dir / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated_audio(audio_dir)

    rows: list[dict[str, str]] = []
    for candidate in _collect_candidates(
        data_dir,
        limit,
        seed,
        sessions_dir=sessions_dir,
        min_session_id=min_session_id,
    ):
        if len(rows) >= limit:
            break
        try:
            audio_path = _write_clip(candidate, audio_dir, len(rows) + 1)
        except Exception:
            continue

        rows.append(
            {
                "audio_path": audio_path,
                "current_text": candidate.current_text,
                "corrected_text": candidate.corrected_text,
                "session_id": candidate.session_id,
                "entry_id": candidate.entry_id,
                "start": f"{candidate.start:.3f}",
                "end": f"{candidate.end:.3f}",
            }
        )

    csv_path = output_dir / "review.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return rows


def _default_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "transcriber"
    return Path(__file__).resolve().parents[1] / "data"


def _default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "training_data" / "review_samples"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build human-review samples from saved Transcriber sessions.",
    )
    parser.add_argument("--data-dir", type=Path, default=_default_data_dir())
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help="Session directory to scan instead of DATA_DIR/sessions.",
    )
    parser.add_argument(
        "--min-session-id",
        default=None,
        help="Only include sessions whose folder name is >= this value, e.g. 2026-05-18.",
    )
    args = parser.parse_args()

    rows = build_review_samples(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        limit=args.limit,
        seed=args.seed,
        sessions_dir=args.sessions_dir,
        min_session_id=args.min_session_id,
    )
    print(f"Wrote {len(rows)} review samples")
    print(f"CSV: {args.output_dir / 'review.csv'}")
    print(f"Audio: {args.output_dir / 'audio'}")


if __name__ == "__main__":
    main()
