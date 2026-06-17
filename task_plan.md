# Transcriber Remote Distribution Investigation

Started: 2026-05-03 15:29:04 +09:00

## Goal

Investigate the existing `meeting-transcriber` codebase so it can support a company desktop PC as the shared GPU backend, with Mac/Windows employee clients sending mic + system audio through Tailscale.

## Scope

- Read-only code investigation unless explicitly approved later.
- Preserve existing uncommitted local change in `backend/core/text_refiner.py`.
- Focus first on the path to one remote client successfully streaming audio to the backend.

## Phases

| Phase | Status | Purpose |
|---|---|---|
| 1 | complete | Compare local `E:\transcriber` against GitHub latest |
| 2 | complete | Trace remote audio WebSocket flow and the recorded 403 issue |
| 3 | complete | Inspect client audio sidecar design for Windows and Mac |
| 4 | complete | Identify concrete implementation risks and next actions |

## Decisions So Far

- Backend runs on company desktop PC over Tailscale/VPN.
- Employee clients are Mac and Windows apps.
- Clients send mic + system audio to backend.
- Validation target is user + a few employees, mixed Mac/Windows.
- Initial model is `kotoba-v2.0`.
- Initial concurrent active session limit is 2; overflow is rejected clearly.
- Tailscale restricts network access; employee email is used for per-user data later.

## Recommended Next Implementation Order

1. Preserve the existing local `backend/core/text_refiner.py` change, then fast-forward local `master` to `origin/master`.
2. Start the backend with explicit server config and no app token for the VPN-only validation path.
3. Add a lightweight route/diagnostic check confirming `/ws/audio/{client_id}` is registered on the running backend.
4. Fix remote session scoping for REST operations or avoid those operations during the first one-client audio-stream validation.
5. Fix concurrent-session accounting so only active recordings count, and return a clear max-capacity message.
6. Build Windows audio sidecar packaging.
7. Add Mac audio sidecar by adapting the `transcriber-mac` sounddevice + BlackHole/Soundflower capture code.
8. After one Windows and one Mac client work, add email-based per-user storage separation.

## Current Session: 2026-05-26 Mac Frontend Work

### Goal

Build the Mac-side frontend so this machine runs only the client UI/audio capture path and sends data to a backend running on another PC.

### Clear Conditions / E2E Test Design

- Mac client can configure and persist the remote backend URL.
- Client identity remains stable across app restarts so WebSocket transcript and REST calls address the same remote session.
- Health check makes remote connection status obvious before recording.
- Starting recording on Mac launches only local audio capture and streams to `/ws/audio/{client_id}` on the remote backend.
- Transcript updates arrive through `/ws/transcript?client_id=...`.
- Stopping recording finalizes the remote session and opens history/summary flow.
- Frontend build passes, and a local mocked E2E flow verifies settings and recording controls.

### Current Proposed Phases

| Phase | Status | Purpose |
|---|---|---|
| 1 | complete | Inspect PR branch and existing frontend/sidecar boundaries |
| 2 | complete | Confirm design for Mac front-only architecture |
| 3 | complete | Implement persistent remote connection/client identity and Mac capture sidecar |
| 4 | complete | Add frontend/browser verification for remote Mac flow |
| 5 | complete | Build and run local Mac verification without a live remote backend |

### Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| `tsc: command not found` | Ran `npm run build` before installing frontend dependencies | Ran `npm install`; build then passed |
| `cargo metadata` failed because `cargo` was missing | Ran `npm run tauri dev` | Installed Rust via `rustup`; verified `rustc 1.95.0` and `cargo 1.95.0`; Tauri dev/build now run |
| Playwright tests all failed before execution because Chromium was not installed | Ran `npx playwright test` | Attempted `npx playwright install chromium`; download reached 100% but hung during install, so used Codex in-app browser for UI verification |
| Detached `npm run tauri dev` exited immediately with no log | Tried to keep dev mode running in the background | Switched to production `.app` build and actual macOS app launch for 실機確認 |
| DMG bundling left a temporary writable image mounted | Re-ran `npm run tauri build` after code changes | Detached `/dev/disk9`, removed partial DMG artifacts, re-ran build successfully |

### Verification Status

- `scripts/setup_mac_client.sh` completed.
- `audio_sidecar/.venv/bin/python audio_sidecar/main.py --list-devices ...` detects the built-in MacBook microphone.
- No BlackHole/Soundflower loopback device is currently installed/visible on this Mac, so system-audio capture remains mic-only until a loopback driver is configured.
- `npm run build` passes.
- `npm run tauri dev` compiled and launched the native app in dev mode.
- `npm run tauri build` created both `Transcriber.app` and `Transcriber_0.1.0_aarch64.dmg`.
- `Transcriber.app` launched as a foreground ARM64 macOS app process.
- Native UI screenshot/inspection through automation is blocked by macOS accessibility/screen-capture permissions in this environment.
