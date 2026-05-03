# Findings

## Current Known Facts

- Local repository: `E:\transcriber`.
- Remote repository: `https://github.com/kiku-beep/meeting-transcriber.git`.
- Local worktree has an existing uncommitted one-line change in `backend/core/text_refiner.py`.
- GitHub latest contains remote server/audio sidecar commits beyond the local checked-out commit.
- After `git fetch`, local `master` is 5 commits behind `origin/master`.
- Remote-only commits add the core remote-client pieces:
  - `backend/api/ws_audio_ingest.py`
  - `audio_sidecar/main.py`
  - `tauri-app/src-tauri/src/audio_sidecar.rs`
  - `tauri-app/src/lib/audioSidecar.ts`
  - `scripts/start_server.ps1`
- The remote-only changes are directly relevant to the desired company-PC backend + employee-client architecture.

## Open Questions

- Why did `/ws/audio/{client_id}` return 403 in the prior remote setup?
- Is the current local code missing the remote audio ingest implementation from GitHub?
- Does the audio sidecar support both Windows and Mac mic + system audio, or only Windows today?
- What is the smallest test path to prove one employee client can stream audio to the company backend?

## Remote Audio WebSocket Evidence

- Local `HEAD` has no `ws/audio`, `ws_audio_ingest`, or `audio_ingest` references under `backend`, `tauri-app`, `audio_sidecar`, or `scripts`.
- `origin/master` adds `/ws/audio/{client_id}` in `backend/api/ws_audio_ingest.py` and registers it in `backend/main.py`.
- `REMOTE_SETUP_REPORT.md` says `/api/health` and `/ws/transcript` worked, but `/ws/audio/{client_id}` returned 403.
- `scripts/start_server.ps1` in `origin/master` sets `AUTH_TOKEN` to `"monochrome2026"` by default.
- `backend/api/ws_audio_ingest.py` closes the WebSocket before `accept()` when `settings.auth_token` is set and the query token does not match; this can surface to clients as an HTTP 403-style WebSocket rejection.
- Two plausible 403 causes now need separation:
  1. backend process was still running old local code without `/ws/audio`;
  2. backend had `AUTH_TOKEN` set but the audio sidecar did not pass the matching token.
- Lightweight FastAPI reproduction showed both cases produce the same client-visible error:
  - missing WebSocket route -> `Handshake status 403 Forbidden`
  - `ws.close()` before `accept()` -> `Handshake status 403 Forbidden`
- Therefore the prior 403 response alone cannot distinguish stale backend code from token/auth rejection. Backend route inventory/logs or a token-controlled connection test are required.

## Remote Client Implementation Status

- `audio_sidecar/main.py` accepts `--token` and appends it as a `token` query param to `/ws/audio/{client_id}`.
- Tauri passes `getAuthToken()` to `start_audio_sidecar`, so token flow exists if the user enters it in Settings before recording.
- The auth token is stored only in memory (`_authToken`), while the server URL is persisted to `localStorage`. Restarting the app loses the token.
- `getClientId()` is also process-local random state, not persisted; later employee email identity work must replace or back it with stable storage.
- `/ws/transcript` supports `client_id` and can stream the matching server-mode session.
- Most REST session endpoints in `routes_session.py` still call `get_session()` with no `client_id`, so remote live-session operations like stop/status/entries/edit/register-speaker are not fully client-scoped yet.
- `audio_sidecar/main.py` is Windows-only today:
  - imports `pyaudiowpatch`
  - uses WASAPI loopback discovery
  - `audio_sidecar/requirements.txt` has Windows-specific `pyaudiowpatch`
- Tauri packaging currently has `bundle.targets: ["nsis"]` and `resources: []`; there is no packaged `audio_sidecar.exe`, no Mac app packaging, and no Mac audio capture implementation.

## Multi-User Risks in `origin/master`

- `get_or_create_session()` enforces `settings.max_concurrent_sessions`, but counts session objects in `_sessions`, not only running recordings.
- `/ws/transcript?client_id=...` calls `get_or_create_session()` in server mode, so simply opening the client can consume a session slot before recording starts.
- `remove_session()` exists but is not called from the audio ingest or transcript WebSocket cleanup paths. Client session objects can accumulate until backend restart.
- `ws_audio_ingest.py` imports `remove_session` but does not use it.
- When max sessions are exceeded, `get_or_create_session()` raises `RuntimeError`; `ws_audio_ingest.py` does not catch this around session creation, so clients will not receive the intended clear "currently unavailable" message yet.
- For the target behavior, the concurrency gate should count active/running recordings, not open UI clients.

## Mac Audio Reuse Possibility

- `D:\Desktop\Claude\transcriber-mac` has reusable macOS audio capture code based on `sounddevice`.
- It detects virtual loopback devices named `BlackHole` or `Soundflower`.
- Its comments explicitly state macOS has no native system audio loopback and requires a virtual driver.
- This is a useful starting point for the Mac client sidecar, but it is not integrated into `meeting-transcriber` remote sidecar yet.

## Recommended First Validation Path

1. Update local code to `origin/master` after preserving the existing `text_refiner.py` change.
2. On the backend PC, start with:
   - `DEPLOYMENT_MODE=server`
   - `BACKEND_HOST=<Tailscale IP or 0.0.0.0>`
   - no `AUTH_TOKEN` for the first VPN-only validation, or pass the same token from the client settings.
3. Verify route registration before testing audio:
   - `GET /api/health`
   - WebSocket connect to `/ws/audio/test?source=mic`
   - WebSocket connect to `/ws/transcript?client_id=test`
4. Test Windows client first because the current `audio_sidecar/main.py` is Windows/WASAPI-only.
5. Treat Mac support as a follow-on implementation using `transcriber-mac` sounddevice capture code.

## Root-Cause Assessment for Prior 403

Most likely causes are tied:

- stale backend code without `/ws/audio` because local `E:\transcriber` did not yet contain that route;
- token mismatch because `start_server.ps1` sets `AUTH_TOKEN=monochrome2026` by default, while the token is optional and in-memory in the client UI.

Both produce the same 403 handshake symptom, so the next validation must log route inventory and auth state on backend startup.
