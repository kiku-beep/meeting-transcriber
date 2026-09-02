from backend.core.model_runtime import ModelRuntime
from backend.models.session import TranscriptionSession

import pytest


def test_sessions_share_heavy_models_but_keep_session_state_isolated():
    runtime = ModelRuntime()

    first = TranscriptionSession(model_runtime=runtime)
    second = TranscriptionSession(model_runtime=runtime)

    assert first._transcriber is second._transcriber

    assert first._diarizer is not second._diarizer
    assert first._diarizer._model_backend is second._diarizer._model_backend
    assert first._diarizer._threshold_tracker is not second._diarizer._threshold_tracker

    assert first._refiner is not second._refiner
    assert first._refiner._model_backend is second._refiner._model_backend
    assert first._refiner._last_processed_time == second._refiner._last_processed_time == 0.0


def test_runtime_preload_uses_each_shared_core_model_once():
    class FakeModel:
        def __init__(self):
            self.loads = 0

        def load_model(self):
            self.loads += 1

    transcriber = FakeModel()
    speaker_model = FakeModel()
    runtime = ModelRuntime(
        transcriber=transcriber,
        speaker_model=speaker_model,
    )

    runtime.load_core_models()

    assert transcriber.loads == 1
    assert speaker_model.loads == 1


@pytest.mark.anyio
async def test_session_loads_segmentation_when_core_models_are_already_loaded(monkeypatch):
    class FakeModel:
        def __init__(self, loaded: bool):
            self.is_loaded = loaded
            self.loads = 0

        def load_model(self):
            self.loads += 1
            self.is_loaded = True

    class FakeBuffer:
        def __init__(self):
            self.loads = 0

        def load_model(self):
            self.loads += 1

    session = TranscriptionSession()
    session._transcriber = FakeModel(loaded=True)
    session._diarizer = FakeModel(loaded=True)
    session._refiner = FakeModel(loaded=False)
    session._mic_buffer = FakeBuffer()
    monkeypatch.setattr(
        "backend.models.session.should_run_segmentation_refinement",
        lambda: True,
    )

    await session._ensure_models_loaded()

    assert session._mic_buffer.loads == 1
    assert session._transcriber.loads == 0
    assert session._diarizer.loads == 0
    assert session._refiner.loads == 1
