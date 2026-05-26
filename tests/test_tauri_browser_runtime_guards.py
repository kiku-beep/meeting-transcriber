from pathlib import Path


def test_transcription_recording_icon_invoke_is_tauri_guarded():
    source = Path("tauri-app/src/components/Transcription.tsx").read_text(
        encoding="utf-8"
    )

    assert "isTauriRuntime" in source
    assert "if (!isTauriRuntime()) return;" in source
    assert 'invoke("set_recording_icon"' in source


def test_audio_sidecar_invokes_are_tauri_guarded():
    source = Path("tauri-app/src/lib/audioSidecar.ts").read_text(encoding="utf-8")

    assert "isTauriRuntime" in source
    assert 'invoke<string>("start_audio_sidecar"' in source
    assert 'invoke<string>("stop_audio_sidecar"' in source
    assert 'invoke<boolean>("get_audio_sidecar_status"' in source
    assert "リモート録音はMacアプリでのみ利用できます" in source
