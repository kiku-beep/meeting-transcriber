import sys
from types import SimpleNamespace

import numpy as np

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
