"""WAV → OGG Opus compression using ffmpeg subprocess."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def find_ffmpeg() -> str | None:
    """Return ffmpeg executable path, or None if not found."""
    return shutil.which("ffmpeg")


def compress_wav_to_ogg(wav_path: Path, ogg_path: Path | None = None) -> Path | None:
    """Compress a WAV file to OGG Opus format.

    Returns the output path on success, None on failure.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        logger.warning("ffmpeg not found – skipping compression")
        return None

    if not wav_path.exists():
        logger.warning("WAV file not found: %s", wav_path)
        return None

    if ogg_path is None:
        ogg_path = wav_path.with_suffix(".ogg")

    try:
        result = subprocess.run(
            [
                ffmpeg, "-y",
                "-i", str(wav_path),
                "-c:a", "libopus",
                "-b:a", "32k",
                "-ar", "16000",
                "-ac", "1",
                str(ogg_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error("ffmpeg failed: %s", result.stderr[-500:] if result.stderr else "no output")
            return None

        logger.info(
            "Compressed %s → %s (%.1f MB → %.1f MB)",
            wav_path.name,
            ogg_path.name,
            wav_path.stat().st_size / 1_048_576,
            ogg_path.stat().st_size / 1_048_576,
        )
        return ogg_path
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out compressing %s", wav_path)
        return None
    except Exception:
        logger.exception("Unexpected error during compression")
        return None
