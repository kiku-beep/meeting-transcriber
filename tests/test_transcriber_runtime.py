import sys
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core import transcriber as transcriber_mod


class FakeWhisperModel:
    calls: list[dict] = []
    transcribe_calls: list[dict] = []

    def __init__(self, model_id, device, compute_type):
        self.model_id = model_id
        self.device = device
        self.compute_type = compute_type
        FakeWhisperModel.calls.append(
            {
                "model_id": model_id,
                "device": device,
                "compute_type": compute_type,
            }
        )

    def transcribe(self, audio, **kwargs):
        FakeWhisperModel.transcribe_calls.append(kwargs)
        return [
            SimpleNamespace(
                text="テスト",
                no_speech_prob=0.1,
                avg_logprob=-0.1,
                compression_ratio=1.0,
            )
        ], SimpleNamespace(language="ja", language_probability=0.99)


class FakeWhisperCppBackend:
    calls: list[dict] = []
    transcribe_calls: list[dict] = []

    def __init__(self, model_size):
        self.model_size = model_size
        self.is_loaded = False
        FakeWhisperCppBackend.calls.append({"model_size": model_size})

    def load_model(self):
        self.is_loaded = True
        FakeWhisperCppBackend.calls.append({"action": "load_model"})

    def unload_model(self):
        self.is_loaded = False
        FakeWhisperCppBackend.calls.append({"action": "unload_model"})

    def transcribe(self, audio, sample_rate=16000):
        FakeWhisperCppBackend.transcribe_calls.append(
            {"duration": len(audio) / sample_rate, "sample_rate": sample_rate}
        )
        return {
            "text": "Vulkanテスト",
            "language": "ja",
            "confidence": 0.9,
            "no_speech_prob": 0.1,
            "avg_logprob": -0.2,
            "compression_ratio": 1.0,
        }


def install_fake_torch(monkeypatch, cuda_available: bool):
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda_available),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)


def test_load_model_uses_cpu_int8_when_cuda_is_unavailable(monkeypatch):
    FakeWhisperModel.calls.clear()
    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber_mod, "check_vram_available", lambda required_mb: True)

    transcriber = transcriber_mod.Transcriber("tiny")
    transcriber.load_model()

    assert FakeWhisperModel.calls == [
        {
            "model_id": "tiny",
            "device": "cpu",
            "compute_type": "int8",
        }
    ]


def test_load_model_uses_cuda_float16_when_cuda_is_available(monkeypatch):
    FakeWhisperModel.calls.clear()
    install_fake_torch(monkeypatch, cuda_available=True)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber_mod, "check_vram_available", lambda required_mb: True)

    transcriber = transcriber_mod.Transcriber("tiny")
    transcriber.load_model()

    assert FakeWhisperModel.calls == [
        {
            "model_id": "tiny",
            "device": "cuda",
            "compute_type": "float16",
        }
    ]


def test_transcribe_uses_fast_decode_options_on_cpu(monkeypatch):
    FakeWhisperModel.calls.clear()
    FakeWhisperModel.transcribe_calls.clear()
    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber_mod, "check_temperature_safe", lambda threshold: True)

    transcriber = transcriber_mod.Transcriber("tiny")
    transcriber.load_model()
    result = transcriber.transcribe(np.zeros(16000, dtype=np.float32))

    assert result["text"] == "テスト"
    assert FakeWhisperModel.transcribe_calls[-1]["beam_size"] == 1
    assert FakeWhisperModel.transcribe_calls[-1]["best_of"] == 1
    assert FakeWhisperModel.transcribe_calls[-1]["temperature"] == 0.0


def test_transcribe_keeps_quality_decode_options_on_cuda(monkeypatch):
    FakeWhisperModel.calls.clear()
    FakeWhisperModel.transcribe_calls.clear()
    install_fake_torch(monkeypatch, cuda_available=True)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber_mod, "check_vram_available", lambda required_mb: True)
    monkeypatch.setattr(transcriber_mod, "check_temperature_safe", lambda threshold: True)

    transcriber = transcriber_mod.Transcriber("tiny")
    transcriber.load_model()
    transcriber.transcribe(np.zeros(16000, dtype=np.float32))

    assert FakeWhisperModel.transcribe_calls[-1]["beam_size"] == 5
    assert "best_of" not in FakeWhisperModel.transcribe_calls[-1]
    assert "temperature" not in FakeWhisperModel.transcribe_calls[-1]


def test_auto_runtime_uses_whispercpp_for_kotoba_when_cuda_is_unavailable(monkeypatch):
    FakeWhisperModel.calls.clear()
    FakeWhisperCppBackend.calls.clear()
    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(transcriber_mod, "WhisperCppServerBackend", FakeWhisperCppBackend, raising=False)
    monkeypatch.setattr(transcriber_mod, "is_whisper_cpp_available", lambda model_size: True, raising=False)

    transcriber = transcriber_mod.Transcriber("kotoba-v2.0")
    transcriber.load_model()

    assert FakeWhisperModel.calls == []
    assert FakeWhisperCppBackend.calls == [
        {"model_size": "kotoba-v2.0"},
        {"action": "load_model"},
    ]
    assert transcriber._runtime_device == "vulkan"
    assert transcriber._runtime_compute == "whisper.cpp"


def test_concurrent_load_model_initializes_whispercpp_once(monkeypatch):
    first_loading = threading.Event()
    release_loading = threading.Event()

    class BlockingWhisperCppBackend:
        instances = 0
        loads = 0

        def __init__(self, model_size):
            self.model_size = model_size
            self.is_loaded = False
            BlockingWhisperCppBackend.instances += 1

        def load_model(self):
            BlockingWhisperCppBackend.loads += 1
            first_loading.set()
            assert release_loading.wait(timeout=2)
            self.is_loaded = True

    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperCppServerBackend", BlockingWhisperCppBackend)
    monkeypatch.setattr(transcriber_mod, "is_whisper_cpp_available", lambda model_size: True)

    transcriber = transcriber_mod.Transcriber("kotoba-v2.0")
    errors: list[BaseException] = []

    def load():
        try:
            transcriber.load_model()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=load)
    second = threading.Thread(target=load)
    first.start()
    assert first_loading.wait(timeout=2)
    second.start()
    second.join(timeout=0.2)
    release_loading.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert errors == []
    assert BlockingWhisperCppBackend.instances == 1
    assert BlockingWhisperCppBackend.loads == 1


def test_transcribe_delegates_to_whispercpp_backend(monkeypatch):
    FakeWhisperCppBackend.calls.clear()
    FakeWhisperCppBackend.transcribe_calls.clear()
    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperCppServerBackend", FakeWhisperCppBackend, raising=False)
    monkeypatch.setattr(transcriber_mod, "is_whisper_cpp_available", lambda model_size: True, raising=False)
    monkeypatch.setattr(transcriber_mod, "check_temperature_safe", lambda threshold: True)

    transcriber = transcriber_mod.Transcriber("kotoba-v2.0")
    transcriber.load_model()
    result = transcriber.transcribe(np.zeros(32000, dtype=np.float32), sample_rate=16000)

    assert result["text"] == "Vulkanテスト"
    assert FakeWhisperCppBackend.transcribe_calls == [
        {"duration": 2.0, "sample_rate": 16000}
    ]


def test_concurrent_transcribe_calls_are_serialized(monkeypatch):
    active_calls = 0
    max_active_calls = 0
    state_lock = threading.Lock()

    class BlockingWhisperModel(FakeWhisperModel):
        def transcribe(self, audio, **kwargs):
            nonlocal active_calls, max_active_calls
            with state_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.05)
            try:
                return super().transcribe(audio, **kwargs)
            finally:
                with state_lock:
                    active_calls -= 1

    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperModel", BlockingWhisperModel)
    monkeypatch.setattr(transcriber_mod, "check_temperature_safe", lambda threshold: True)

    transcriber = transcriber_mod.Transcriber("tiny")
    transcriber.load_model()
    errors: list[BaseException] = []

    def run_transcription():
        try:
            transcriber.transcribe(np.zeros(16000, dtype=np.float32))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run_transcription) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert max_active_calls == 1


def test_failed_whispercpp_load_does_not_publish_broken_backend(monkeypatch):
    class FailingWhisperCppBackend:
        def __init__(self, model_size):
            self.model_size = model_size
            self.is_loaded = False

        def load_model(self):
            raise RuntimeError("server failed")

    install_fake_torch(monkeypatch, cuda_available=False)
    monkeypatch.setattr(transcriber_mod, "WhisperCppServerBackend", FailingWhisperCppBackend)
    monkeypatch.setattr(transcriber_mod, "is_whisper_cpp_available", lambda model_size: True)

    transcriber = transcriber_mod.Transcriber("kotoba-v2.0")
    with pytest.raises(RuntimeError, match="server failed"):
        transcriber.load_model()

    assert transcriber._whisper_cpp is None
    with pytest.raises(RuntimeError, match="Model not loaded"):
        transcriber.transcribe(np.zeros(16000, dtype=np.float32))
