import asyncio
import time

from backend.api import routes_playback


def test_compress_audio_does_not_block_event_loop(monkeypatch, tmp_path):
    session_id = "2026-07-28_120000"
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    wav_path = session_dir / "recording.wav"
    wav_path.write_bytes(b"wav")

    monkeypatch.setattr(routes_playback, "_session_dir", lambda _: session_dir)
    monkeypatch.setattr(routes_playback, "find_ffmpeg", lambda: "ffmpeg")

    def slow_compress(source):
        time.sleep(0.2)
        ogg_path = source.with_suffix(".ogg")
        ogg_path.write_bytes(b"ogg")
        return ogg_path

    monkeypatch.setattr(routes_playback, "compress_wav_to_ogg", slow_compress)

    async def run_scenario():
        started_at = time.perf_counter()
        compression = asyncio.create_task(routes_playback.compress_audio(session_id))
        await asyncio.sleep(0.02)
        event_loop_delay = time.perf_counter() - started_at
        result = await compression
        return event_loop_delay, result

    event_loop_delay, result = asyncio.run(run_scenario())

    assert event_loop_delay < 0.1
    assert result["status"] == "compressed"
    assert not wav_path.exists()
