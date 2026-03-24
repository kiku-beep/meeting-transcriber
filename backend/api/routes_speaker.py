import io
import logging

import numpy as np
import soundfile as sf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.core.audio_utils import resample_to_16k_mono
from backend.core.diarizer import Diarizer
from backend.storage.speaker_store import get_speaker_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/speakers", tags=["speakers"])


def _get_diarizer() -> Diarizer:
    """Return the shared Diarizer from the singleton session (avoids a second instance)."""
    from backend.models.session import get_session

    d = get_session()._diarizer
    if not d.is_loaded:
        d.load_model()
    return d


@router.get("")
async def list_speakers():
    store = get_speaker_store()
    return {"speakers": store.list_speakers()}


@router.post("/create")
async def create_speaker_name_only(name: str = Form(...)):
    """Create a speaker with only a name (no audio samples).

    The speaker can be used in expected-speakers seeding or
    have audio samples added later.
    """
    if not name.strip():
        raise HTTPException(400, "Name is required")

    store = get_speaker_store()
    profile = store.create_speaker(name.strip())

    return {
        "speaker": profile.to_dict(sample_count=0),
    }


@router.post("")
async def register_speaker(
    name: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """Register a new speaker with audio samples.

    Upload 3-5 WAV files (5-10s each) + a name.
    The embeddings are extracted, averaged, and stored.
    """
    if not name.strip():
        raise HTTPException(400, "Name is required")
    if len(files) < 1:
        raise HTTPException(400, "At least 1 audio sample is required")

    store = get_speaker_store()
    diarizer = _get_diarizer()

    # Create the speaker profile
    profile = store.create_speaker(name.strip())

    audio_segments: list[np.ndarray] = []

    for i, file in enumerate(files):
        content = await file.read()

        # Decode audio
        try:
            audio, sr = sf.read(io.BytesIO(content), dtype="float32")
        except Exception:
            logger.warning("Failed to decode file %s, skipping", file.filename)
            continue

        audio = resample_to_16k_mono(audio, sr)
        duration = len(audio) / 16000

        # Save raw sample with metadata (user-uploaded = high quality)
        filename = f"sample_{i:02d}.wav"
        buf = io.BytesIO()
        sf.write(buf, audio, 16000, subtype="PCM_16", format="WAV")
        store.save_sample_with_metadata(
            profile.speaker_id, buf.getvalue(), filename,
            quality=0.8, duration=duration,
            confidence=0.8, session_id="manual_upload",
        )
        audio_segments.append(audio)

    if not audio_segments:
        store.delete_speaker(profile.speaker_id)
        raise HTTPException(400, "No valid audio samples could be processed")

    # Compute averaged embedding
    embedding = diarizer.compute_average_embedding(audio_segments)
    store.save_embedding(profile.speaker_id, embedding)

    sample_count = len(store.get_sample_paths(profile.speaker_id))
    return {
        "speaker": profile.to_dict(sample_count=sample_count),
        "samples_processed": len(audio_segments),
    }


class RenameSpeakerRequest(BaseModel):
    name: str


@router.put("/{speaker_id}")
async def rename_speaker(speaker_id: str, req: RenameSpeakerRequest):
    """Rename a speaker."""
    if not req.name.strip():
        raise HTTPException(400, "Name is required")
    store = get_speaker_store()
    profile = store.rename_speaker(speaker_id, req.name.strip())
    if profile is None:
        raise HTTPException(404, "Speaker not found")
    sample_count = len(store.get_sample_paths(speaker_id))
    return {"speaker": profile.to_dict(sample_count=sample_count)}


@router.delete("/{speaker_id}")
async def delete_speaker(speaker_id: str):
    store = get_speaker_store()
    if not store.delete_speaker(speaker_id):
        raise HTTPException(404, "Speaker not found")
    return {"deleted": True}


@router.post("/{speaker_id}/samples")
async def add_samples(
    speaker_id: str,
    files: list[UploadFile] = File(...),
):
    """Add more audio samples to an existing speaker and recompute embedding."""
    store = get_speaker_store()
    profile = store.get_speaker(speaker_id)
    if profile is None:
        raise HTTPException(404, "Speaker not found")

    diarizer = _get_diarizer()
    audio_segments: list[np.ndarray] = []

    # Load existing samples
    for path in store.get_sample_paths(speaker_id):
        try:
            audio, sr = sf.read(str(path), dtype="float32")
            audio = resample_to_16k_mono(audio, sr)
            audio_segments.append(audio)
        except Exception:
            continue

    # Add new samples
    existing_count = len(store.get_sample_paths(speaker_id))
    for i, file in enumerate(files):
        content = await file.read()

        try:
            audio, sr = sf.read(io.BytesIO(content), dtype="float32")
            audio = resample_to_16k_mono(audio, sr)
        except Exception:
            continue

        duration = len(audio) / 16000
        filename = f"sample_{existing_count + i:02d}.wav"
        buf = io.BytesIO()
        sf.write(buf, audio, 16000, subtype="PCM_16", format="WAV")
        store.save_sample_with_metadata(
            speaker_id, buf.getvalue(), filename,
            quality=0.8, duration=duration,
            confidence=0.8, session_id="manual_upload",
        )
        audio_segments.append(audio)

    if audio_segments:
        embedding = diarizer.compute_average_embedding(audio_segments)
        store.save_embedding(speaker_id, embedding)

    sample_count = len(store.get_sample_paths(speaker_id))
    return {
        "speaker": profile.to_dict(sample_count=sample_count),
        "total_samples": len(audio_segments),
    }


@router.post("/recompute-all")
async def recompute_all_embeddings():
    """Recompute embeddings for all speakers that have audio samples but no valid embedding."""
    store = get_speaker_store()
    diarizer = _get_diarizer()
    results = {"recomputed": [], "skipped": [], "failed": []}

    for speaker_data in store.list_speakers():
        sid = speaker_data["id"]
        profile = store.get_speaker(sid)
        if profile is None or profile.embedding is not None:
            continue
        sample_paths = store.get_sample_paths(sid)
        if not sample_paths:
            results["skipped"].append(sid)
            continue
        try:
            audio_segments = []
            for path in sample_paths:
                audio, sr = sf.read(str(path), dtype="float32")
                audio = resample_to_16k_mono(audio, sr)
                audio_segments.append(audio)
            if audio_segments:
                embedding = diarizer.compute_average_embedding(audio_segments)
                store.save_embedding(sid, embedding)
                results["recomputed"].append(sid)
            else:
                results["skipped"].append(sid)
        except Exception as e:
            logger.warning("Failed to recompute for %s: %s", sid, e)
            results["failed"].append(sid)

    return results


@router.post("/{speaker_id}/recompute")
async def recompute_embedding(speaker_id: str):
    """Recompute embedding from stored audio samples."""
    store = get_speaker_store()
    profile = store.get_speaker(speaker_id)
    if profile is None:
        raise HTTPException(404, "Speaker not found")

    sample_paths = store.get_sample_paths(speaker_id)
    if not sample_paths:
        raise HTTPException(400, "No audio samples available for recomputation")

    diarizer = _get_diarizer()
    audio_segments = []
    for path in sample_paths:
        try:
            audio, sr = sf.read(str(path), dtype="float32")
            audio = resample_to_16k_mono(audio, sr)
            audio_segments.append(audio)
        except Exception:
            logger.warning("Failed to read sample %s", path)
            continue

    if not audio_segments:
        raise HTTPException(400, "No valid audio samples could be decoded")

    embedding = diarizer.compute_average_embedding(audio_segments)
    store.save_embedding(speaker_id, embedding)

    sample_count = len(sample_paths)
    return {"speaker": profile.to_dict(sample_count=sample_count)}


@router.post("/test")
async def test_identification(file: UploadFile = File(...)):
    """Test speaker identification with a single audio file."""
    content = await file.read()

    try:
        audio, sr = sf.read(io.BytesIO(content), dtype="float32")
    except Exception:
        raise HTTPException(400, "Could not decode audio file")

    audio = resample_to_16k_mono(audio, sr)

    diarizer = _get_diarizer()
    result = diarizer.identify_speaker(audio)

    return result
