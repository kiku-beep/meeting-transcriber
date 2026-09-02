from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_transcription_waits_for_backend_health_before_starting_recording():
    source = (ROOT / "tauri-app" / "src" / "components" / "Transcription.tsx").read_text(
        encoding="utf-8"
    )

    assert "waitForBackendHealth" in source
    wait_index = source.index("await waitForBackendHealth")
    local_start_index = source.index("await startSession")
    remote_start_index = source.index("await startAudioSidecar")

    assert wait_index < local_start_index
    assert wait_index < remote_start_index


def test_settings_treats_initial_backend_connection_failure_as_starting_state():
    source = (ROOT / "tauri-app" / "src" / "components" / "Settings.tsx").read_text(
        encoding="utf-8"
    )

    assert "isBackendConnectionError" in source
    assert "起動待ち" in source
