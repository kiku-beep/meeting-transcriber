# Progress

## 2026-05-03

- Created investigation plan files for the transcriber remote distribution work.
- No production code changes made in this investigation yet.
- Ran `git fetch origin --prune`.
- Confirmed local `master` is 5 commits behind `origin/master`.
- Identified remote-only files implementing audio sidecar and WebSocket audio ingest.
- Confirmed local `HEAD` lacks `/ws/audio`; `origin/master` adds it.
- Found `scripts/start_server.ps1` sets a default `AUTH_TOKEN`, which may explain a pre-accept WebSocket 403 if clients omit token.
- Inspected frontend/Tauri sidecar wiring.
- Found remote transcript WebSocket is client-aware, but many REST session operations are still default-session only.
- Found audio sidecar and packaging are Windows-only/incomplete for distribution; Mac audio capture is not implemented.
- Ran a lightweight FastAPI/WebSocket reproduction confirming both missing routes and pre-accept auth closes surface as the same 403 handshake error.
- Checked multi-user session registry behavior; found session slots can be consumed by UI WebSocket connections and are not cleaned up.
- Checked `transcriber-mac` audio capture; found sounddevice + BlackHole/Soundflower logic that can be reused for Mac client capture.
- Completed read-only code investigation and wrote next implementation order.
- Fast-forwarded local `master` to `origin/master`.
- Added session registry tests for server-mode concurrency behavior.
- Changed session capacity enforcement from session creation time to recording start time.
- Ran `python -m pytest tests\test_session_registry.py -q` and confirmed 2 passing tests.
- Added WebSocket capacity test and changed `/ws/audio` start handling to return a JSON `error` when capacity is full.
- Removed the default shared auth token from `scripts/start_server.ps1`; token auth is now opt-in via `-AuthToken`.
- Updated README to document VPN-only default and optional token auth.
- Added `pytest.ini` so pytest only collects project tests under `tests/`, not PyInstaller sidecar internals.
- Ran full project pytest with `python -m pytest -q`: 4 passed, 2 warnings.

## 2026-05-04

- Updated `scripts/start_server.ps1` to avoid a hard-coded Tailscale IP.
- Added `-BindHost` and `-Port` parameters.
- Added Tailscale IP auto-detection via `tailscale ip -4`, falling back to `0.0.0.0` with a warning.
- Updated README server startup instructions for Chrome Remote Desktop/company PC setup.

## 2026-05-26

- Cloned `https://github.com/kiku-beep/meeting-transcriber.git` branch `transcriber` into the current workspace.
- Opened PR #3 context from GitHub and confirmed the branch summary is focused on local ASR/non-CUDA updates plus runtime safeguards.
- User clarified that backend work is on another PC; this Mac should own the frontend/client side and send data to the backend.
- Inspected Tauri app, API client, WebSocket client, recording controls, settings, Rust sidecar launcher, and Python audio sidecar.
- Identified the main implementation gap: current capture sidecar is Windows/WASAPI-only and production packaging is Windows-only, while the React UI has partial remote-server support.
- Added current-session goal, clear conditions, findings, and progress notes to planning files.
- Implemented persisted remote server URL, auth token, and stable client ID handling in the Tauri frontend.
- Added a connection-first backend loader for remote URL/token setup.
- Added Mac/Linux `sounddevice` support to `audio_sidecar/main.py`, while preserving Windows `pyaudiowpatch` support.
- Added graceful audio sidecar shutdown over stdin so the Python sidecar can send `stop` to the backend before exiting.
- Added `scripts/setup_mac_client.sh` to install audio sidecar dependencies, frontend dependencies, and copy `.env.remote` to `.env.local`.
- Updated Tauri bundle config to use platform-specific `all` targets and include `audio_sidecar` as a resource.
- Ran `scripts/setup_mac_client.sh`; it installed the Mac sidecar venv and frontend dependencies.
- Ran `audio_sidecar/.venv/bin/python audio_sidecar/main.py --list-devices --server ws://127.0.0.1:8000 --client-id test`; detected MacBook mic only, no BlackHole/Soundflower loopback.
- Ran `audio_sidecar/.venv/bin/python audio_sidecar/main.py --server ws://127.0.0.1:9 --client-id test --no-loopback`; confirmed startup exits non-zero when the backend WebSocket cannot be reached immediately.
- Ran `npm run build` successfully after dependency install.
- Ran `npm run tauri dev`; blocked because Rust/Cargo is not installed on this Mac.
- Ran `npx playwright test`; all tests failed before execution because Playwright Chromium was missing.
- Attempted `npx playwright install chromium`; download reached 100% but install hung, so the install process was stopped.
- Verified the Vite UI with Codex in-app browser at `http://127.0.0.1:1430/`, including connection screen, main transcription screen, and settings screen.
- Installed Rust with `rustup`; verified `rustc 1.95.0`, `cargo 1.95.0`, and the stable aarch64 Apple toolchain.
- Ran `npm run tauri dev`; Rust compiled successfully and launched the native `transcriber` app in dev mode.
- Confirmed the dev frontend responded with HTTP 200 on `http://localhost:1430/` and the native process appeared as a foreground macOS app via `lsappinfo`.
- Updated the Rust audio sidecar resolver so release bundles built from this source tree can use `audio_sidecar/.venv` before falling back to bundled script resources.
- Removed the macOS Rust unused-import warning by making `tauri::Manager` Windows-only.
- Ran `npm run tauri build`; generated `Transcriber.app` and `Transcriber_0.1.0_aarch64.dmg`.
- Resolved a transient DMG bundling failure by detaching a leftover writable image and rerunning the build.
- Launched `Transcriber.app` from the generated macOS bundle and confirmed it registered as a foreground ARM64 app process.

## 2026-05-27

- Added `scripts/diagnose_server.ps1` for Chrome Remote Desktop/company PC backend setup.
- The diagnostic checks Git, Python, Tailscale, NVIDIA GPU, CUDA/PyTorch, required Python modules, `%APPDATA%\transcriber\.env`, port 8000, and backend health endpoints.
- Added static and PowerShell parse tests for the diagnostic script.
- Ran the diagnostic locally with `-SkipHealth`; it correctly reported missing Tailscale/GPU on this non-server environment and showed suggested startup command.
- Added `scripts/mock_remote_backend.py` so the Mac client can test remote URL setup, audio WebSocket start, and transcript WebSocket rendering before the company PC is configured.
- Added mock backend tests covering `/api/health`, `/ws/audio/{client_id}`, `/ws/transcript`, and REST `/api/session/start` for localhost smoke checks.
- Documented that audio-sidecar testing must use a non-localhost URL, even when the mock backend runs on the same Mac, because localhost is treated as local standalone mode by the Tauri app.
- Fixed the Tauri frontend so browser/Vite verification does not call `set_recording_icon` outside the native Tauri runtime.
- Extended the mock backend with settings/model/summary/call-detection read endpoints so the app can use the mock without noisy `Not Found` errors.
- Verified the Vite UI against the mock backend: connection health passed, `録音開始` created a fake transcript row, and the settings screen rendered without `Not Found`.
