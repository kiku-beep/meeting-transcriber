"""Whisper model comparison tool: large-v3 vs kotoba-v2.0

Records audio (or loads WAV), transcribes with both models sequentially,
and generates an HTML report for side-by-side accuracy comparison.

Usage:
    # Record from mic (default 30s)
    python whisper_compare.py --duration 60

    # Use existing WAV file
    python whisper_compare.py --input meeting.wav

    # List audio devices
    python whisper_compare.py --list-devices

    # Specify device
    python whisper_compare.py --device 5 --duration 45
"""

from __future__ import annotations

import argparse
import gc
import html
import logging
import struct
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1

# Model definitions
MODELS = {
    "large-v3": {
        "hf_id": "Systran/faster-whisper-large-v3",
        "vram_mb": 4500,
        "compute_type": "float16",
        "description": "Whisper large-v3 (multilingual, highest accuracy)",
    },
    "kotoba-v2.0": {
        "hf_id": "kotoba-tech/kotoba-whisper-v2.0-faster",
        "vram_mb": 2500,
        "compute_type": "float16",
        "description": "Kotoba Whisper v2.0 (Japanese-tuned distil-whisper)",
    },
}


# ──────────────────────────── Audio Recording ────────────────────────────


def list_devices() -> None:
    """Print available audio input devices."""
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()
    try:
        print("\n=== Audio Input Devices ===\n")
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] <= 0:
                continue
            is_lb = info.get("isLoopbackDevice", False)
            tag = " [loopback]" if is_lb else ""
            print(f"  [{info['index']:3d}] {info['name']}{tag}")
            print(f"        channels={info['maxInputChannels']}, rate={info['defaultSampleRate']:.0f}")
        print()
    finally:
        p.terminate()


def record_audio(duration_s: int, device_index: int | None = None) -> np.ndarray:
    """Record audio from microphone via WASAPI."""
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()

    if device_index is None:
        # Find default WASAPI mic
        for i in range(p.get_host_api_count()):
            info = p.get_host_api_info_by_index(i)
            if "WASAPI" in info.get("name", ""):
                device_index = info.get("defaultInputDevice", -1)
                break
        if device_index is None or device_index < 0:
            p.terminate()
            raise RuntimeError("No WASAPI microphone found")

    dev_info = p.get_device_info_by_index(device_index)
    logger.info("Recording device: %s (index=%d)", dev_info["name"], device_index)
    logger.info("Duration: %d seconds", duration_s)

    chunks: list[bytes] = []
    total_frames = SAMPLE_RATE * duration_s

    stream = p.open(
        format=pyaudio.paFloat32,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=1024,
    )

    print(f"\n  Recording for {duration_s}s... (speak now)")
    print("  ", end="", flush=True)

    frames_read = 0
    last_dot = 0
    try:
        while frames_read < total_frames:
            to_read = min(1024, total_frames - frames_read)
            data = stream.read(to_read, exception_on_overflow=False)
            chunks.append(data)
            frames_read += to_read

            # Progress dots
            elapsed = frames_read / SAMPLE_RATE
            if int(elapsed) > last_dot:
                last_dot = int(elapsed)
                if last_dot % 5 == 0:
                    print(f"{last_dot}s", end="", flush=True)
                else:
                    print(".", end="", flush=True)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    print(" done!\n")

    audio = np.frombuffer(b"".join(chunks), dtype=np.float32)
    rms = float(np.sqrt(np.mean(audio**2)))
    peak = float(np.max(np.abs(audio)))
    logger.info("Recorded %d samples (%.1fs), RMS=%.4f, Peak=%.4f", len(audio), len(audio) / SAMPLE_RATE, rms, peak)

    return audio


def load_wav(path: str) -> np.ndarray:
    """Load a WAV file and convert to float32 mono 16kHz."""
    import soundfile as sf

    audio, sr = sf.read(path, dtype="float32")

    # Stereo to mono
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    # Resample if needed
    if sr != SAMPLE_RATE:
        from scipy.signal import resample

        n_samples = int(len(audio) * SAMPLE_RATE / sr)
        audio = resample(audio, n_samples).astype(np.float32)
        logger.info("Resampled %dHz -> %dHz", sr, SAMPLE_RATE)

    logger.info("Loaded %s: %.1fs, RMS=%.4f", path, len(audio) / SAMPLE_RATE, float(np.sqrt(np.mean(audio**2))))
    return audio


def save_wav(audio: np.ndarray, path: str) -> None:
    """Save float32 audio as 16-bit PCM WAV."""
    pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())
    logger.info("Saved WAV: %s (%.1fs)", path, len(audio) / SAMPLE_RATE)


# ──────────────────────────── Transcription ──────────────────────────────


def transcribe_with_model(
    audio: np.ndarray,
    model_name: str,
    language: str = "ja",
) -> dict:
    """Load model, transcribe, unload. Returns results dict."""
    from faster_whisper import WhisperModel

    cfg = MODELS[model_name]
    model_id = cfg["hf_id"]

    # Normalize audio
    peak = float(np.max(np.abs(audio)))
    if peak > 1e-4:
        audio_norm = audio / peak
    else:
        audio_norm = audio

    # Load
    logger.info("Loading %s (%s)...", model_name, model_id)
    t_load_start = time.monotonic()

    model = WhisperModel(
        model_id,
        device="cuda",
        compute_type=cfg["compute_type"],
    )

    t_load = time.monotonic() - t_load_start
    logger.info("  Loaded in %.1fs", t_load)

    # Transcribe
    logger.info("Transcribing with %s...", model_name)
    t_transcribe_start = time.monotonic()

    kwargs = {}
    if model_name == "kotoba-v2.0":
        kwargs["chunk_length"] = 15
        kwargs["condition_on_previous_text"] = False

    segments_iter, info = model.transcribe(
        audio_norm,
        language=language,
        beam_size=3,
        vad_filter=True,
        word_timestamps=True,
        **kwargs,
    )

    # Collect segments
    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "probability": w.probability,
                })
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "no_speech_prob": seg.no_speech_prob,
            "avg_logprob": seg.avg_logprob,
            "compression_ratio": seg.compression_ratio,
            "words": words,
        })

    t_transcribe = time.monotonic() - t_transcribe_start
    full_text = " ".join(s["text"] for s in segments)

    logger.info("  Transcribed in %.1fs (%d segments)", t_transcribe, len(segments))
    logger.info("  Text: %s", full_text[:100] + ("..." if len(full_text) > 100 else ""))

    # Unload
    del model
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass

    logger.info("  Model unloaded")

    return {
        "model_name": model_name,
        "model_description": cfg["description"],
        "language": info.language,
        "language_probability": info.language_probability,
        "duration_s": info.duration,
        "load_time_s": t_load,
        "transcribe_time_s": t_transcribe,
        "segments": segments,
        "full_text": full_text,
    }


# ──────────────────────────── HTML Report ────────────────────────────────


def fmt_time(seconds: float) -> str:
    """Format seconds as MM:SS.s"""
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def generate_html_report(
    result_a: dict,
    result_b: dict,
    audio_duration: float,
    audio_path: str | None,
    output_path: str,
) -> None:
    """Generate side-by-side HTML comparison report."""

    def seg_rows(result: dict) -> str:
        rows = []
        for i, seg in enumerate(result["segments"]):
            confidence_class = ""
            if seg["no_speech_prob"] > 0.5:
                confidence_class = "low-conf"
            elif seg["avg_logprob"] < -1.0:
                confidence_class = "med-conf"

            word_spans = ""
            if seg["words"]:
                for w in seg["words"]:
                    prob = w["probability"]
                    if prob < 0.3:
                        wclass = "word-low"
                    elif prob < 0.7:
                        wclass = "word-med"
                    else:
                        wclass = "word-high"
                    word_spans += f'<span class="{wclass}" title="p={prob:.2f}">{html.escape(w["word"])}</span>'
            else:
                word_spans = html.escape(seg["text"])

            rows.append(f"""
            <tr class="{confidence_class}">
                <td class="ts">{fmt_time(seg['start'])} - {fmt_time(seg['end'])}</td>
                <td class="text">{word_spans}</td>
                <td class="metrics">
                    nsp={seg['no_speech_prob']:.2f}<br>
                    lp={seg['avg_logprob']:.2f}<br>
                    cr={seg['compression_ratio']:.1f}
                </td>
            </tr>""")
        return "\n".join(rows)

    def summary_stats(result: dict) -> str:
        segs = result["segments"]
        if not segs:
            return "<p>No segments</p>"
        avg_nsp = sum(s["no_speech_prob"] for s in segs) / len(segs)
        avg_lp = sum(s["avg_logprob"] for s in segs) / len(segs)
        all_words = [w for s in segs for w in s.get("words", [])]
        avg_wp = sum(w["probability"] for w in all_words) / len(all_words) if all_words else 0
        rtf = result["transcribe_time_s"] / audio_duration if audio_duration > 0 else 0
        return f"""
        <div class="stats">
            <div class="stat"><span class="label">Segments</span><span class="value">{len(segs)}</span></div>
            <div class="stat"><span class="label">Load time</span><span class="value">{result['load_time_s']:.1f}s</span></div>
            <div class="stat"><span class="label">Transcribe</span><span class="value">{result['transcribe_time_s']:.1f}s</span></div>
            <div class="stat"><span class="label">RTF</span><span class="value">{rtf:.2f}x</span></div>
            <div class="stat"><span class="label">Avg no_speech</span><span class="value">{avg_nsp:.3f}</span></div>
            <div class="stat"><span class="label">Avg logprob</span><span class="value">{avg_lp:.3f}</span></div>
            <div class="stat"><span class="label">Avg word prob</span><span class="value">{avg_wp:.3f}</span></div>
            <div class="stat"><span class="label">Language</span><span class="value">{result['language']} ({result['language_probability']:.1%})</span></div>
        </div>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    audio_info = f"File: {html.escape(audio_path)}" if audio_path else "Live recording"

    report_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>Whisper Model Comparison - {now}</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --text-dim: #8b949e; --accent-a: #58a6ff; --accent-b: #3fb950;
    --red: #f85149; --orange: #d29922; --green: #3fb950;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 8px; }}
  .meta {{ color: var(--text-dim); font-size: 0.85rem; margin-bottom: 24px; }}

  .comparison {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  .panel-header {{ padding: 16px 20px; border-bottom: 1px solid var(--border); }}
  .panel-header h2 {{ font-size: 1.1rem; margin-bottom: 4px; }}
  .panel-header.model-a h2 {{ color: var(--accent-a); }}
  .panel-header.model-b h2 {{ color: var(--accent-b); }}
  .panel-header .desc {{ color: var(--text-dim); font-size: 0.8rem; }}

  .stats {{ display: flex; flex-wrap: wrap; gap: 12px; padding: 12px 20px; border-bottom: 1px solid var(--border); }}
  .stat {{ display: flex; flex-direction: column; min-width: 80px; }}
  .stat .label {{ font-size: 0.7rem; color: var(--text-dim); text-transform: uppercase; }}
  .stat .value {{ font-size: 0.95rem; font-weight: 600; }}

  .full-text {{ padding: 16px 20px; border-bottom: 1px solid var(--border); }}
  .full-text h3 {{ font-size: 0.85rem; color: var(--text-dim); margin-bottom: 8px; }}
  .full-text p {{ font-size: 0.9rem; line-height: 1.6; white-space: pre-wrap; }}

  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; padding: 8px 12px; font-size: 0.75rem; color: var(--text-dim); border-bottom: 1px solid var(--border); text-transform: uppercase; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 0.85rem; vertical-align: top; }}
  td.ts {{ white-space: nowrap; color: var(--text-dim); font-family: monospace; font-size: 0.8rem; width: 120px; }}
  td.text {{ line-height: 1.5; }}
  td.metrics {{ font-family: monospace; font-size: 0.75rem; color: var(--text-dim); white-space: nowrap; width: 100px; }}

  tr.low-conf {{ background: rgba(248, 81, 73, 0.08); }}
  tr.med-conf {{ background: rgba(210, 153, 34, 0.06); }}

  .word-high {{ }}
  .word-med {{ color: var(--orange); text-decoration: underline dotted; }}
  .word-low {{ color: var(--red); text-decoration: underline wavy; font-weight: 600; }}

  .diff-section {{ margin-top: 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }}
  .diff-section h2 {{ font-size: 1.1rem; margin-bottom: 12px; }}
  .diff-line {{ display: flex; gap: 16px; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.85rem; }}
  .diff-line .ts {{ width: 100px; color: var(--text-dim); font-family: monospace; flex-shrink: 0; }}
  .diff-line .col {{ flex: 1; line-height: 1.5; }}
  .diff-line .col-a {{ border-left: 3px solid var(--accent-a); padding-left: 8px; }}
  .diff-line .col-b {{ border-left: 3px solid var(--accent-b); padding-left: 8px; }}
  .diff-same {{ color: var(--text-dim); font-style: italic; }}

  @media (max-width: 1200px) {{
    .comparison {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<h1>Whisper Model Comparison</h1>
<p class="meta">{now} | Audio: {audio_info} | Duration: {fmt_time(audio_duration)} ({audio_duration:.1f}s)</p>

<div class="comparison">
  <!-- Model A: large-v3 -->
  <div class="panel">
    <div class="panel-header model-a">
      <h2>{html.escape(result_a['model_name'])}</h2>
      <div class="desc">{html.escape(result_a['model_description'])}</div>
    </div>
    {summary_stats(result_a)}
    <div class="full-text">
      <h3>Full Text</h3>
      <p>{html.escape(result_a['full_text'])}</p>
    </div>
    <table>
      <tr><th>Time</th><th>Text</th><th>Metrics</th></tr>
      {seg_rows(result_a)}
    </table>
  </div>

  <!-- Model B: kotoba-v2.0 -->
  <div class="panel">
    <div class="panel-header model-b">
      <h2>{html.escape(result_b['model_name'])}</h2>
      <div class="desc">{html.escape(result_b['model_description'])}</div>
    </div>
    {summary_stats(result_b)}
    <div class="full-text">
      <h3>Full Text</h3>
      <p>{html.escape(result_b['full_text'])}</p>
    </div>
    <table>
      <tr><th>Time</th><th>Text</th><th>Metrics</th></tr>
      {seg_rows(result_b)}
    </table>
  </div>
</div>

{_build_diff_section(result_a, result_b)}

</body>
</html>"""

    Path(output_path).write_text(report_html, encoding="utf-8")
    logger.info("Report saved: %s", output_path)


def _build_diff_section(result_a: dict, result_b: dict) -> str:
    """Build a time-aligned diff section comparing both models' output."""
    # Build time-to-text mappings at 1-second granularity
    def text_by_second(result: dict) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for seg in result["segments"]:
            start_s = int(seg["start"])
            end_s = int(seg["end"]) + 1
            for t in range(start_s, end_s):
                if t not in mapping:
                    mapping[t] = ""
                mapping[t] += seg["text"] + " "
        return {k: v.strip() for k, v in mapping.items()}

    map_a = text_by_second(result_a)
    map_b = text_by_second(result_b)

    # Merge segments by finding contiguous time ranges with text
    all_times = sorted(set(map_a.keys()) | set(map_b.keys()))
    if not all_times:
        return ""

    rows = []
    # Group into segment-level blocks (by original segments)
    segs_a = result_a["segments"]
    segs_b = result_b["segments"]

    # Use segment boundaries for alignment
    boundaries = set()
    for s in segs_a + segs_b:
        boundaries.add(round(s["start"], 1))

    boundaries = sorted(boundaries)

    def find_seg_text(segs: list, t: float) -> str:
        for s in segs:
            if s["start"] <= t + 0.5 and s["end"] >= t - 0.5:
                return s["text"]
        return ""

    seen_a: set[str] = set()
    seen_b: set[str] = set()
    for t in boundaries:
        text_a = find_seg_text(segs_a, t)
        text_b = find_seg_text(segs_b, t)

        # Skip duplicates
        key_a = f"{t:.0f}:{text_a}"
        key_b = f"{t:.0f}:{text_b}"
        if key_a in seen_a and key_b in seen_b:
            continue
        seen_a.add(key_a)
        seen_b.add(key_b)

        if not text_a and not text_b:
            continue

        same = text_a.strip() == text_b.strip()
        if same:
            rows.append(f"""
            <div class="diff-line">
                <div class="ts">{fmt_time(t)}</div>
                <div class="col diff-same" style="flex:2">{html.escape(text_a)}</div>
            </div>""")
        else:
            rows.append(f"""
            <div class="diff-line">
                <div class="ts">{fmt_time(t)}</div>
                <div class="col col-a">{html.escape(text_a) if text_a else '<em>-</em>'}</div>
                <div class="col col-b">{html.escape(text_b) if text_b else '<em>-</em>'}</div>
            </div>""")

    if not rows:
        return ""

    return f"""
    <div class="diff-section">
        <h2>Time-Aligned Comparison</h2>
        <p style="color: var(--text-dim); font-size: 0.8rem; margin-bottom: 12px;">
            <span style="color: var(--accent-a);">&#9632;</span> {result_a['model_name']}
            &nbsp;&nbsp;
            <span style="color: var(--accent-b);">&#9632;</span> {result_b['model_name']}
            &nbsp;&nbsp;
            <span style="color: var(--text-dim);">Gray = identical output</span>
        </p>
        {"".join(rows)}
    </div>"""


# ──────────────────────────── Main ───────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Compare Whisper large-v3 vs kotoba-v2.0 transcription accuracy",
    )
    parser.add_argument("--input", "-i", help="Path to WAV file (if omitted, records from mic)")
    parser.add_argument("--duration", "-d", type=int, default=30, help="Recording duration in seconds (default: 30)")
    parser.add_argument("--device", type=int, default=None, help="Audio device index for recording")
    parser.add_argument("--language", "-l", default="ja", help="Language code (default: ja)")
    parser.add_argument("--output", "-o", default=None, help="Output HTML path (default: auto-generated)")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--save-wav", action="store_true", help="Save recorded audio as WAV file")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    # Get audio
    audio_path = args.input
    if audio_path:
        audio = load_wav(audio_path)
    else:
        audio = record_audio(args.duration, args.device)
        if args.save_wav:
            wav_name = f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            wav_path = str(Path(__file__).parent / wav_name)
            save_wav(audio, wav_path)
            audio_path = wav_path
        else:
            # Always save so user can replay
            wav_name = f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            wav_path = str(Path(__file__).parent / wav_name)
            save_wav(audio, wav_path)
            audio_path = wav_path

    audio_duration = len(audio) / SAMPLE_RATE

    print(f"  Audio: {audio_duration:.1f}s")
    print()

    # Transcribe with both models sequentially
    print("=" * 60)
    print(f"  [1/2] Transcribing with large-v3...")
    print("=" * 60)
    result_a = transcribe_with_model(audio, "large-v3", args.language)

    print()
    print("=" * 60)
    print(f"  [2/2] Transcribing with kotoba-v2.0...")
    print("=" * 60)
    result_b = transcribe_with_model(audio, "kotoba-v2.0", args.language)

    # Quick console comparison
    print()
    print("=" * 60)
    print("  Quick Comparison")
    print("=" * 60)
    print(f"\n  large-v3    ({result_a['transcribe_time_s']:.1f}s):")
    print(f"    {result_a['full_text'][:200]}")
    print(f"\n  kotoba-v2.0 ({result_b['transcribe_time_s']:.1f}s):")
    print(f"    {result_b['full_text'][:200]}")
    print()

    # Generate HTML report
    if args.output:
        output_path = args.output
    else:
        output_path = str(Path(__file__).parent / f"compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")

    generate_html_report(result_a, result_b, audio_duration, audio_path, output_path)

    print(f"  HTML report: {output_path}")
    print()

    # Auto-open in browser
    import webbrowser
    webbrowser.open(output_path)


if __name__ == "__main__":
    main()
