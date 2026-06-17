# Transcriber Agent Coordination

Shared GitHub issue: https://github.com/kiku-beep/meeting-transcriber/issues/4

This file defines how the Mac-side agent and Windows/backend-side agent coordinate work.

## Current Goal

Validate the vanilla LAN remote setup:

- Mac runs the frontend/Tauri client and local audio sidecar.
- Windows PC runs the FastAPI backend, ASR model, WebSocket ingest, and session storage.
- Both sides use branch `transcriber`.

## Current Contract

- Backend URL for LAN validation: `http://192.168.10.17:8000`
- Frontend dev URL from Windows PC: `http://192.168.10.17:1430`
- Audio ingest WS: `/ws/audio/{client_id}`
- Transcript WS: `/ws/transcript?client_id=...`
- Live session REST: `/api/session/*?client_id=...`
- Diagnostics: `/api/server/diagnostics`
- Auth token: empty for vanilla LAN validation

## Ownership

- Mac agent owns: `tauri-app/`, `audio_sidecar/`, Mac setup scripts, frontend UX.
- Windows/backend agent owns: `backend/`, `scripts/start_server.ps1`, server runtime, model/ASR behavior, backend tests.
- Shared docs and tests can be edited by either side after claiming in Issue #4.

## Required Workflow

1. Read Issue #4 before starting.
2. Comment `CLAIM` with the side, task, and files/area to touch.
3. Pull latest branch:

   ```bash
   git pull --ff-only origin transcriber
   ```

4. Do not edit the other side's claimed area unless the issue log says it is released.
5. After finishing, run relevant checks, commit, push, then comment `DONE`.
6. If blocked, comment `BLOCKED` with repro steps, logs, and the exact ask.

## Message Templates

### Claim

```md
### CLAIM | mac | short task name
Area: `tauri-app/src/...`, `audio_sidecar/...`
Plan:
- ...
Needs from windows: none / specific ask
```

```md
### CLAIM | windows | short task name
Area: `backend/api/...`, `backend/models/...`
Plan:
- ...
Needs from mac: none / specific ask
```

### Done

```md
### DONE | side | short task name
Commit: `<sha>`
Checks: `<commands/results>`
Changed contract: yes/no
Next ask: `<what the other side should do>`
```

### Blocked

```md
### BLOCKED | side | short task name
Expected: ...
Actual: ...
Repro: ...
Logs: ...
Ask: ...
```

## Current Next Test

Mac side:

1. Open `http://192.168.10.17:1430`.
2. Set Backend URL to `http://192.168.10.17:8000`.
3. Leave Auth token blank.
4. Verify connection.
5. Try one short mic-only recording.

Windows/backend side:

1. Keep backend running on `0.0.0.0:8000`.
2. Watch backend logs during the Mac recording test.
3. If Mac cannot connect, check Windows firewall for inbound `8000` and `1430`.
