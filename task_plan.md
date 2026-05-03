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
