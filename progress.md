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
