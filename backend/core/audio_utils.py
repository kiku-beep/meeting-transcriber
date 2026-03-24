"""Common audio resampling utilities."""

from __future__ import annotations

import numpy as np


def resample_to_16k_mono(audio: np.ndarray, sr: int) -> np.ndarray:
    """Resample audio to 16 kHz mono float32.

    Args:
        audio: Input audio array (1-D mono or 2-D multi-channel).
        sr: Source sample rate in Hz.

    Returns:
        1-D float32 numpy array at 16 kHz.
    """
    # Convert to mono if multi-channel
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample if not already 16 kHz
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)

    return audio.astype(np.float32)
