import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.transcriber import AVAILABLE_MODELS, VRAM_REQUIREMENTS, warm_disk_cache
from backend.models.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])


class StartRequest(BaseModel):
    device_index: int | None = None
    loopback_device_index: int | None = None
    session_name: str = ""


class RegisterSpeakerRequest(BaseModel):
    entry_index: int
    name: str


class NameClusterRequest(BaseModel):
    cluster_id: str
    name: str
    is_guest: bool = False


class ExpectedSpeakersRequest(BaseModel):
    names: list[str]
    speaker_ids: list[str] = []


class ConfirmSuggestionRequest(BaseModel):
    cluster_id: str
    speaker_id: str
    speaker_name: str


class ModelSwitchRequest(BaseModel):
    model_size: str


class ModelWarmCacheRequest(BaseModel):
    model_size: str


@router.post("/start")
async def start_session(req: StartRequest = StartRequest()):
    session = get_session()
    try:
        await session.start(
            device_index=req.device_index,
            loopback_device_index=req.loopback_device_index,
            session_name=req.session_name,
        )
        return session.info
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_session():
    session = get_session()
    await session.stop()
    return session.info


@router.post("/discard")
async def discard_session():
    session = get_session()
    await session.discard()
    return session.info


@router.post("/pause")
async def pause_session():
    session = get_session()
    await session.pause()
    return session.info


@router.get("/status")
async def session_status():
    session = get_session()
    return session.info


@router.get("/model")
async def get_model():
    session = get_session()
    return {
        "current_model": session._transcriber.model_size,
        "is_loaded": session._transcriber.is_loaded,
        "available_models": [
            {"name": m, "vram_mb": VRAM_REQUIREMENTS[m]} for m in AVAILABLE_MODELS
        ],
    }


@router.post("/model")
async def switch_model(req: ModelSwitchRequest):
    if req.model_size not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Invalid model: {req.model_size}. Available: {AVAILABLE_MODELS}")

    session = get_session()
    if session.status.value != "idle":
        raise HTTPException(409, "セッション中はモデルを変更できません")

    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, session._transcriber.switch_model, req.model_size)
    return {
        "model_size": session._transcriber.model_size,
        "is_loaded": session._transcriber.is_loaded,
    }


@router.post("/model/warm-cache")
async def warm_model_cache(req: ModelWarmCacheRequest):
    """Pre-read model files into OS page cache for faster switching."""
    if req.model_size not in AVAILABLE_MODELS:
        raise HTTPException(400, f"Invalid model: {req.model_size}")

    session = get_session()
    # Don't warm the currently loaded model
    if req.model_size == session._transcriber.model_size and session._transcriber.is_loaded:
        return {"status": "already_loaded", "bytes_read": 0, "elapsed_s": 0.0}

    session._transcriber.start_cache_warm(req.model_size)
    return {"status": "warming_started"}


@router.get("/model/loading-status")
async def get_loading_status():
    """Get current model loading stage for progress display."""
    session = get_session()
    return {
        "stage": session._transcriber._loading_stage,
        "progress": session._transcriber._loading_progress,
    }


@router.get("/entries")
async def get_entries():
    session = get_session()
    return {"entries": [e.model_dump() for e in session.entries]}


@router.post("/register-speaker")
async def register_speaker_from_entry(req: RegisterSpeakerRequest):
    if not req.name.strip():
        raise HTTPException(400, "名前を入力してください")
    session = get_session()
    try:
        result = session.register_speaker_from_entry(req.entry_index, req.name)
        return {
            "speaker": result,
            "entry_index": req.entry_index,
            "entries": [e.model_dump() for e in session.entries],
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/name-cluster")
async def name_cluster(req: NameClusterRequest):
    """Name a speaker cluster and promote it to a registered speaker."""
    if not req.name.strip():
        raise HTTPException(400, "名前を入力してください")

    session = get_session()
    embedding = session._cluster_manager.get_cluster_embedding(req.cluster_id)
    if embedding is None:
        raise HTTPException(404, f"Cluster {req.cluster_id} not found")

    # Guest tag: rename cluster label and update entries without SpeakerStore
    if req.is_guest:
        guest_id = f"guest_{req.cluster_id}"
        updated_ids = []
        for entry in session.entries:
            if entry.cluster_id == req.cluster_id:
                entry.speaker_name = req.name.strip()
                entry.speaker_id = guest_id
                updated_ids.append(entry.id)
        session._cluster_manager.rename_cluster(req.cluster_id, req.name.strip())
        return {
            "speaker": {"id": guest_id, "name": req.name.strip(),
                        "sample_count": 0, "has_embedding": False},
            "updated_entry_ids": updated_ids,
            "entries": [e.model_dump() for e in session.entries],
        }

    from backend.storage.speaker_store import get_speaker_store

    store = get_speaker_store()
    profile = store.create_speaker(req.name.strip())
    store.save_embedding(profile.speaker_id, embedding)

    # Save WAV audio samples from cluster entries
    source_entry = None
    for entry in session.entries:
        if entry.cluster_id == req.cluster_id:
            source_entry = entry
            break
    if source_entry:
        session._save_speaker_samples(store, profile.speaker_id, source_entry, req.cluster_id)

    # Update all entries in this cluster
    updated_ids = []
    for entry in session.entries:
        if entry.cluster_id == req.cluster_id:
            entry.speaker_name = req.name.strip()
            entry.speaker_id = profile.speaker_id
            entry.cluster_id = None
            updated_ids.append(entry.id)

    session._cluster_manager.merge_to_speaker(req.cluster_id, profile.speaker_id)

    return {
        "speaker": profile.to_dict(),
        "updated_entry_ids": updated_ids,
        "entries": [e.model_dump() for e in session.entries],
    }


@router.post("/expected-speakers")
async def set_expected_speakers(req: ExpectedSpeakersRequest):
    """Set expected participant names before starting a session."""
    from backend.storage.speaker_store import get_speaker_store

    session = get_session()
    names = [n.strip() for n in req.names if n.strip()]

    # Load seed embeddings from registered speakers
    seed_embeddings: dict[str, "np.ndarray"] = {}
    if req.speaker_ids:
        store = get_speaker_store()
        for sid in req.speaker_ids:
            profile = store.get_speaker(sid)
            if profile and profile.embedding is not None:
                seed_embeddings[profile.name] = profile.embedding

    session._cluster_manager.set_expected_speakers(names, seed_embeddings=seed_embeddings or None)
    return {"expected_speakers": names}


@router.get("/expected-speakers")
async def get_expected_speakers():
    """Get currently set expected participant names."""
    session = get_session()
    return {"expected_speakers": session._cluster_manager._expected_speakers}


class EntryEditRequest(BaseModel):
    text: str | None = None
    speaker_name: str | None = None
    speaker_id: str | None = None


class BulkUpdateSpeakerRequest(BaseModel):
    old_speaker_id: str
    new_speaker_id: str
    new_speaker_name: str


@router.patch("/entries/bulk-update-speaker")
async def bulk_update_speaker(req: BulkUpdateSpeakerRequest):
    """Update all entries with old_speaker_id to new speaker."""
    import io
    from backend.storage.correction_store import get_correction_store
    from backend.storage.speaker_store import get_speaker_store as _get_store

    session = get_session()
    correction_store = get_correction_store()
    store = _get_store()
    updated_count = 0
    audio_samples_collected: list[tuple[str, "np.ndarray"]] = []

    for entry in session.entries:
        if entry.speaker_id == req.old_speaker_id:
            # Update speaker name if changed
            if entry.speaker_name != req.new_speaker_name:
                correction_store.add(
                    original=entry.speaker_name,
                    corrected=req.new_speaker_name,
                    field="speaker_name",
                    session_id=session.session_id,
                    entry_id=entry.id,
                )
                entry.speaker_name = req.new_speaker_name

            # Update speaker ID
            entry.speaker_id = req.new_speaker_id

            # Feedback learning: update new speaker's embedding
            if not req.new_speaker_id.startswith("guest_") and entry.id in session._entry_embeddings:
                emb = session._entry_embeddings[entry.id]
                store.update_embedding(req.new_speaker_id, emb, weight=0.15)

            # Collect audio samples for voice profile
            if not req.new_speaker_id.startswith("guest_") and entry.id in session._entry_audio:
                audio_samples_collected.append(
                    (entry.id, session._entry_audio[entry.id])
                )

            updated_count += 1

    # Save collected audio samples to speaker profile (best-effort)
    samples_saved = 0
    if audio_samples_collected and req.new_speaker_id != "unknown":
        profile = store.get_speaker(req.new_speaker_id)
        if profile:
            import soundfile as sf

            existing_count = len(store.get_sample_paths(req.new_speaker_id))
            for i, (_eid, audio_data) in enumerate(audio_samples_collected[:5]):
                try:
                    duration = len(audio_data) / 16000
                    buf = io.BytesIO()
                    sf.write(buf, audio_data, 16000, subtype="PCM_16", format="WAV")
                    filename = f"sample_{existing_count + i:02d}_manual.wav"
                    store.save_sample_with_metadata(
                        req.new_speaker_id, buf.getvalue(), filename,
                        quality=0.8, duration=duration,
                        confidence=0.8,
                        session_id=session.session_id,
                    )
                    samples_saved += 1
                except Exception as e:
                    logger.warning("Failed to save audio sample %d: %s", i, e)

            # Recompute embedding with all samples (existing + new)
            if samples_saved > 0:
                try:
                    all_audio_segments = []
                    from backend.core.audio_utils import resample_to_16k_mono
                    for path in store.get_sample_paths(req.new_speaker_id):
                        try:
                            audio, sr = sf.read(str(path), dtype="float32")
                            audio = resample_to_16k_mono(audio, sr)
                            all_audio_segments.append(audio)
                        except Exception:
                            logger.warning("Failed to load sample %s", path)

                    if all_audio_segments:
                        diarizer = session._diarizer
                        if diarizer.is_loaded:
                            new_embedding = diarizer.compute_average_embedding(all_audio_segments)
                            store.save_embedding(req.new_speaker_id, new_embedding)
                            logger.info("Updated voice profile for %s with %d new samples",
                                        req.new_speaker_name, samples_saved)
                except Exception as e:
                    logger.warning("Failed to recompute embedding: %s", e)

    return {
        "updated_count": updated_count,
        "audio_samples_saved": samples_saved,
        "entries": [e.model_dump() for e in session.entries],
    }


@router.post("/confirm-suggestion")
async def confirm_suggestion(req: ConfirmSuggestionRequest):
    """Confirm a speaker suggestion: assign cluster entries to registered speaker and learn threshold."""
    from backend.storage.speaker_store import get_speaker_store as _get_store

    session = get_session()
    store = _get_store()
    updated_count = 0
    min_confidence = 1.0

    profile = store.get_speaker(req.speaker_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Speaker {req.speaker_id} not found")

    for entry in session.entries:
        if entry.cluster_id == req.cluster_id:
            entry.speaker_id = req.speaker_id
            entry.speaker_name = req.speaker_name
            entry.cluster_id = None
            entry.suggested_speaker_id = None
            entry.suggested_speaker_name = None

            # Embedding learning
            if entry.id in session._entry_embeddings:
                emb = session._entry_embeddings[entry.id]
                store.update_embedding(req.speaker_id, emb, weight=0.15)

            if entry.speaker_confidence > 0:
                min_confidence = min(min_confidence, entry.speaker_confidence)

            updated_count += 1

    # Learn per-speaker accepted threshold (slightly below the lowest confirmed confidence)
    if updated_count > 0 and min_confidence < 1.0:
        new_threshold = min_confidence - 0.03
        current = profile.accepted_threshold
        if current is None or new_threshold < current:
            store.set_accepted_threshold(req.speaker_id, new_threshold)

    return {
        "updated_count": updated_count,
        "entries": [e.model_dump() for e in session.entries],
    }


@router.patch("/entries/{entry_id}")
async def edit_entry(entry_id: str, req: EntryEditRequest):
    """Edit a transcript entry in the current live session."""
    from backend.storage.correction_store import get_correction_store

    session = get_session()
    for entry in session.entries:
        if entry.id == entry_id:
            correction_store = get_correction_store()

            if req.text is not None and req.text != entry.text:
                original_text = entry.text
                correction_store.add(
                    original=original_text,
                    corrected=req.text,
                    field="text",
                    session_id=session.session_id,
                    entry_id=entry_id,
                )
                entry.text = req.text

                # Auto-register word corrections to dictionary
                from backend.core.correction_learner import auto_register_correction
                auto_register_correction(original_text, req.text)

            if req.speaker_name is not None:
                if req.speaker_name != entry.speaker_name:
                    correction_store.add(
                        original=entry.speaker_name,
                        corrected=req.speaker_name,
                        field="speaker_name",
                        session_id=session.session_id,
                        entry_id=entry_id,
                    )
                    entry.speaker_name = req.speaker_name

            if req.speaker_id is not None:
                old_speaker_id = entry.speaker_id
                entry.speaker_id = req.speaker_id

                # Feedback learning: update new speaker's embedding (skip for guest speakers)
                if not req.speaker_id.startswith("guest_") and req.speaker_id != old_speaker_id and entry_id in session._entry_embeddings:
                    from backend.storage.speaker_store import get_speaker_store as _get_store
                    emb = session._entry_embeddings[entry_id]
                    store = _get_store()
                    store.update_embedding(req.speaker_id, emb, weight=0.15)

            return {"entry": entry.model_dump()}

    raise HTTPException(404, f"Entry {entry_id} not found")


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str):
    """Delete a transcript entry from the current live session."""
    session = get_session()
    for entry in session.entries:
        if entry.id == entry_id:
            session.entries.remove(entry)
            session._entry_embeddings.pop(entry_id, None)
            return {"deleted": entry_id}
    raise HTTPException(404, f"Entry {entry_id} not found")


class RegisterNewSpeakerRequest(BaseModel):
    entry_id: str
    name: str
    is_guest: bool = False


@router.post("/register-new-speaker")
async def register_new_speaker(req: RegisterNewSpeakerRequest):
    """Register a new speaker and assign to a specific entry."""
    if not req.name.strip():
        raise HTTPException(400, "名前を入力してください")

    session = get_session()
    target = None
    for entry in session.entries:
        if entry.id == req.entry_id:
            target = entry
            break
    if target is None:
        raise HTTPException(404, f"Entry {req.entry_id} not found")

    if req.is_guest:
        guest_id = f"guest_{req.entry_id[:8]}"
        target.speaker_name = req.name.strip()
        target.speaker_id = guest_id
        return {
            "speaker": {"id": guest_id, "name": req.name.strip(),
                        "sample_count": 0, "has_embedding": False},
            "entries": [e.model_dump() for e in session.entries],
        }

    # Normal registration: create SpeakerStore profile
    from backend.storage.speaker_store import get_speaker_store

    store = get_speaker_store()
    profile = store.create_speaker(req.name.strip())
    embedding = session._entry_embeddings.get(req.entry_id)
    if embedding is not None:
        store.save_embedding(profile.speaker_id, embedding)
    if req.entry_id in session._entry_audio:
        session._save_speaker_samples(store, profile.speaker_id, target, target.cluster_id)
    target.speaker_name = req.name.strip()
    target.speaker_id = profile.speaker_id
    return {
        "speaker": profile.to_dict(),
        "entries": [e.model_dump() for e in session.entries],
    }
