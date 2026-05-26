from pathlib import Path


def test_transcription_recording_icon_invoke_is_tauri_guarded():
    source = Path("tauri-app/src/components/Transcription.tsx").read_text(
        encoding="utf-8"
    )

    assert "isTauriRuntime" in source
    assert "if (!isTauriRuntime()) return;" in source
    assert 'invoke("set_recording_icon"' in source
