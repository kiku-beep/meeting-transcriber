# Dual Loopback Capture Design

## Goal

Transcriber must capture Windows system audio regardless of whether playback is routed to the user's `INZONE H3` headset or `Anker PowerConf S330` speaker. Microphone capture and the existing transcription, diarization, recording, pause, and device-recovery behavior must continue to work.

## Current Behavior

- `TranscriptionSession.start()` resolves one Windows default WASAPI loopback endpoint.
- `AudioStreamManager` owns one loopback stream and feeds one `AudioBuffer`.
- The device watcher hot-switches that one stream when the Windows default output changes.
- This can miss audio when an application is routed to a non-default endpoint or when the output changes without a usable default-device transition.

## Chosen Approach

Open the two preferred WASAPI loopback endpoints concurrently and arbitrate their 100 ms callback frames into the existing single loopback pipeline.

Preferred endpoints are identified by stable name fragments, not PyAudio indices:

1. `INZONE H3`
2. `Anker PowerConf S330`

The fragments are configuration defaults so they can be overridden without changing code. Matching is case-insensitive and restricted to WASAPI loopback devices.

### Why Not Mix Every Callback

Appending callbacks from two streams directly to the existing buffer would double the apparent audio duration and could interleave frames out of order. Summing both endpoints would also duplicate audio when Windows mirrors the same signal. The implementation therefore emits exactly one loopback frame for each callback interval.

## Architecture

### Device Discovery

Add a discovery function in `backend/core/audio_capture.py` that returns all loopback devices matching the configured name fragments.

- Resolve devices at session start because indices can change after reboot or reconnect.
- Deduplicate matches by device index.
- If no preferred endpoint is available, retain the existing default-loopback fallback.
- If only one preferred endpoint is available, start with that endpoint and continue normally.

### Multi-stream Ownership

Change `AudioStreamManager` from one loopback stream to a mapping keyed by device index. Each stream keeps its own sample rate, channel count, callback counter, latest signal timestamp, and name.

The existing microphone stream remains unchanged.

Expose active loopback names as a list internally and as a joined string in `SessionStatus.loopback_device` to preserve the current API type.

### Frame Arbitration

Each loopback callback resamples its frame to 16 kHz mono and calculates RMS energy.

- One source is the selected source at a time.
- The selected source continues to emit frames while it has signal.
- A different source with signal takes over immediately when the selected source has been silent for at least two callback intervals.
- When both sources are active, the current source remains selected to prevent rapid switching and duplicate transcription.
- Silent frames from the selected source continue to be emitted so saved audio duration remains aligned with the microphone track.
- Pause behavior remains unchanged: callbacks do not feed or record frames while paused.

This arbitration is internal. Users do not select a source during recording.

### Recording and Transcription

The arbitrated loopback frame continues to feed the existing `_loopback_buffer` and `_recorded_loopback` list. Therefore:

- all applications rendered to either preferred endpoint are captured;
- the pipeline still processes one system-audio source;
- WAV export still mixes one microphone track with one loopback track;
- no downstream schema or transcript-entry change is required.

### Device Changes

The existing device watcher continues to track the default microphone. For loopback outputs, an add/remove/default-device event triggers a rescan of the preferred endpoint names.

- Newly connected preferred endpoints are opened without restarting the session.
- Removed endpoints are closed and removed from the stream map.
- If the selected endpoint disappears, selection is cleared and the next endpoint with signal takes over.
- A failure to open one endpoint is logged, but does not stop capture from the other endpoint. The existing status string lists only endpoints that opened successfully.

### Explicit Device Requests

The existing `loopback_device_index` request field remains supported. When a caller explicitly supplies an index, Transcriber opens only that endpoint. Multi-endpoint discovery applies only to the current automatic local-recording path.

Remote audio ingest is unchanged.

## Configuration

Add a comma-separated setting with these defaults:

```text
LOOPBACK_DEVICE_PATTERNS=INZONE H3,Anker PowerConf S330
```

An empty setting restores the existing default-output-only behavior.

## Error Handling

- No preferred device found: use the Windows default loopback.
- One preferred device fails: continue with the other and log the failed name.
- All loopback devices fail: continue microphone-only and expose an empty loopback device status.
- Device refresh fails: keep currently open streams and retry on the next watcher event or polling interval.
- Stream callback failure: isolate it to that endpoint; do not stop the microphone or other loopback stream.

## Testing

Backend unit tests must cover:

1. Case-insensitive preferred-device discovery and index deduplication.
2. Two loopback streams opening and closing independently.
3. INZONE-to-Anker and Anker-to-INZONE arbitration after two silent frames.
4. No switching while both endpoints have sustained signal.
5. Exactly one frame appended per callback interval and no duplicate recording.
6. One-device and no-preferred-device fallback behavior.
7. Hot-add and hot-remove synchronization.
8. Explicit `loopback_device_index` preserving single-device behavior.
9. Pause and session-stop cleanup across all streams.

The implementation must also pass the existing session audio-recording, route, and transcription test suites. A manual verification records short playback on each endpoint during one session and confirms both portions appear in the saved WAV and transcript.

## Out of Scope

- Capturing HDMI monitor outputs that do not match the configured names.
- Capturing audio from a remote PC over the network.
- Per-application Windows audio-session selection.
- Mixing simultaneous conversations from both endpoints.
- Frontend device-selection controls.
