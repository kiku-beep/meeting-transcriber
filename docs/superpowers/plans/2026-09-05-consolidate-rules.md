# Transcriber rule consolidation implementation plan

> **For agentic workers:** Use subagent-driven-development. Preserve concurrent changes and stay within the assigned file manifest.

**Goal:** Reduce duplicated decisions and compatibility branches while preserving recording, stored data, AI routing, and public result shapes. User approved these three areas on 2026-09-05.

**Architecture:** Reuse the existing ordered provider runner; separate prompt/result formatting from provider execution. Resolve client sessions centrally. Normalize legacy AI usage for presentation in one frontend helper. Avoid a new service, framework, or dependency.

**Tech Stack:** Python/FastAPI/pytest; React/TypeScript and existing frontend tooling.

## Chunk 1: AI summary execution

Files: `backend/core/summarizer.py`, `tests/test_summary_engine.py` (and `tests/test_live_ai.py` only if needed).

- [x] Characterize direct Gemini and Claude summary behavior, auto fallback, empty input, error and usage contracts before editing.
- [x] Consolidate summary execution with the existing provider routing. Keep summary auto order Claude → Codex → Gemini and question order Claude → Gemini; explicit engines never fall back. Preserve direct Gemini summary's three attempts with 1/2-second backoff, detailed cost usage (or empty usage without metadata), prompt/title handling. Generic Gemini used by auto/live/topic stays single-attempt with model/billing and optional total tokens. Extract shared transport/result formatting without erasing those explicit policies. There are no explicit temperature/token settings in these baseline calls.
- [x] Check aliases and public wrappers. The existing text alias retains its tested public compatibility contract; provider wrappers delegate to the shared execution helpers.
- [x] Run focused summary/live tests with external calls mocked, using the existing E:/transcriber/.venv/Scripts/python.exe. Combined focused suite: 63 passed after four added characterization cases. Spec and code reviews: no outstanding findings.

## Chunk 2: Session resolution

Files: `backend/models/session.py`, `backend/api/routes_session.py`, `backend/api/routes_topics.py`, `backend/api/routes_summary.py`, `backend/api/ws_transcription.py`; relevant existing session/route/websocket tests.

- [x] Characterize default and named client resolution, REST/WebSocket identity, and current whitespace normalization.
- [x] Add one shared resolver and use it in the four entry points. The resolver accepts an already-prepared ID and does only default-vs-named lookup. Keep ID preparation at the transport boundary: session REST maps empty to default without trimming; topics/live trim then map empty to default; WS preserves raw IDs including empty. Test `default`, empty, ` default `, and ` a `, plus topics refresh query priority. Do not alter connection/cleanup keys or introduce normalization policy flags.
- [x] Verify existing busy-client keys still refer to the same session; preserve creation/capacity behavior.
- [x] Run session registry, client-ID route, live-AI, topic and websocket binding tests. RED confirmed missing resolver; final full suite passed 236 tests.

## Chunk 3: Frontend compatibility

Files: `tauri-app/src/lib/api.ts`, `tauri-app/src/lib/types.ts`, optional `tauri-app/src/lib/summaryUsage.ts`, `tauri-app/src/components/history/SummaryView.tsx`, `tauri-app/src/components/transcription/LiveAiPanel.tsx`; a focused test using installed tooling.

- [x] Test old/new usage diagnostics and billing interpretation, retaining each view's current legacy display semantics where they differ.
- [x] Centralize presentation decisions; keep stored data untouched and modern billing authoritative. Remove unused BASE_URL/WS_URL after confirming no repository consumers.
- [x] Run focused behavior tests and `tsc --noEmit` with existing dependencies. No dependency installation. Six behavior tests, 23 existing history/live UI tests, and `npm run build` passed. Spec and code reviews: no outstanding findings.

Frontend behavior command (Node 22.18+; verified with Node 24): `node --experimental-strip-types --test tauri-app/tests/summaryUsage.test.ts` from repository root.
UI command from `tauri-app`: `node node_modules/@playwright/test/cli.js test --project=history --project=live-ai --reporter=line`.

## Acceptance

- [x] Independent review: scope/behavior first, then code quality. All three chunks approved, final integration review findings: 0. Generic Gemini zero/missing-total and direct None-response contracts were preserved following initial inspection.
- [x] Run full Python tests and frontend type/build checks. Final Python: 236 passed (baseline 226), one existing pynvml deprecation warning. Frontend: 6 behavior tests, 23 UI tests, type check and build passed. Python and Vite required normal user permissions to use the installed runtime/cache; no dependencies were added.
- [x] Inspect final diff and record changes and validation. Diff check passed; only approved source/test/design files changed. No external AI requests, push, deployment, or cleanup of user data.

Workspace: `D:/Desktop/Claude/.claude/tmp/transcriber-refactor-20260905`, branch `refactor/consolidate-rules-20260905`, base `2fb8395`.
