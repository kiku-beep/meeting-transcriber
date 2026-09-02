import numpy as np
import soundfile as sf

from backend.models import session as session_mod


def test_save_audio_records_loopback_when_mic_chunks_are_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))
    session = session_mod.TranscriptionSession()
    session.session_id = "loopback-only"
    session._recorded_loopback.append(np.full(16000, 0.25, dtype=np.float32))

    session._save_audio()

    wav_path = tmp_path / "loopback-only" / "recording.wav"
    assert wav_path.exists()
    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
    assert sample_rate == 16000
    assert len(audio) == 16000
    assert float(np.max(np.abs(audio))) > 0.2
    assert session._recorded_loopback == []


def test_save_audio_snapshot_keeps_buffers_for_final_save(monkeypatch, tmp_path):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path))
    session = session_mod.TranscriptionSession()
    session.session_id = "snapshot"
    session._recorded_audio.append(np.full(8000, 0.1, dtype=np.float32))
    session._recorded_loopback.append(np.full(8000, 0.2, dtype=np.float32))

    session._save_audio(clear_buffers=False)

    wav_path = tmp_path / "snapshot" / "recording.wav"
    assert wav_path.exists()
    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
    assert sample_rate == 16000
    assert len(audio) == 8000
    assert float(np.max(np.abs(audio))) > 0.25
    assert len(session._recorded_audio) == 1
    assert len(session._recorded_loopback) == 1
