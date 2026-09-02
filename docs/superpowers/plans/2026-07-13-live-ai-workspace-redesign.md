# Live AI Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 録音を止めずに途中要約・質問を実行できるAIパネルと、5画面で統一された業務用UIを実装する。

**Architecture:** ライブAIは実行中セッションの発言スナップショットを専用APIで処理し、既存のClaude優先要約エンジンを再利用する。フロントは常時マウントされるTranscription配下にAI状態を置き、共通CSSコンポーネントで全画面を段階的に更新する。

**Tech Stack:** Python 3.13, FastAPI, Pydantic, pytest, React 19, TypeScript, Tailwind CSS 4, Tauri 2, Playwright

---

## Chunk 1: Live AI Backend

### Task 1: Transcript range selection

**Files:**
- Create: `backend/core/live_ai.py`
- Create: `tests/test_live_ai.py`

- [ ] Write failing tests for whole-meeting and rolling-minute selection based on the latest entry timestamp.
- [ ] Run `py -3.13 -m pytest tests/test_live_ai.py -v` and verify the missing module failure.
- [ ] Implement `select_live_entries(entries, range_minutes)` with range validation and immutable list snapshots.
- [ ] Run the focused tests and verify they pass.
- [ ] Add failing tests for empty input, non-positive/custom range, and boundary-overlapping entries.
- [ ] Implement the minimal validation and boundary behavior.
- [ ] Run the focused tests again.

### Task 2: Live summary and question generation

**Files:**
- Modify: `backend/core/live_ai.py`
- Modify: `backend/core/summarizer.py`
- Modify: `tests/test_live_ai.py`
- Modify: `tests/test_summary_engine.py`

- [ ] Write failing tests for distinct summary and question prompts and empty-question rejection.
- [ ] Run focused tests and verify expected failures.
- [ ] Extract a reusable engine runner in `summarizer.py` without changing existing completion-summary behavior.
- [ ] Implement live summary/question prompt construction and result metadata.
- [ ] Verify focused tests pass, including Claude-first and limit-only Gemini fallback.

### Task 3: Live AI route and concurrency guard

**Files:**
- Modify: `backend/api/routes_summary.py`
- Create: `tests/test_routes_live_ai.py`

- [ ] Write failing API tests for whole/ranged summary, question, client-specific session, invalid input, and empty entries.
- [ ] Run `py -3.13 -m pytest tests/test_routes_live_ai.py -v` and verify failures.
- [ ] Add Pydantic request/response models and `POST /api/summary/live`.
- [ ] Add a per-client non-blocking concurrency guard returning 409 for duplicate work.
- [ ] Verify the route tests pass and session status remains running when generation fails.

## Chunk 2: Shared UI And Recording Screen

### Task 4: Frontend live AI contract

**Files:**
- Modify: `tauri-app/src/lib/types.ts`
- Modify: `tauri-app/src/lib/apiSummary.ts`
- Modify: `scripts/mock_remote_backend.py`
- Modify: `tests/test_mock_remote_backend.py`

- [ ] Add failing mock-backend tests for `/api/summary/live` request validation and response shape.
- [ ] Implement mock behavior used by Playwright.
- [ ] Add TypeScript request/result types and `generateLiveAi` API client.
- [ ] Run Python tests and `npx tsc --noEmit`.

### Task 5: Shared visual foundation

**Files:**
- Modify: `tauri-app/src/App.css`
- Modify: `tauri-app/src/App.tsx`
- Create: `tauri-app/src/components/ui/Alert.tsx`
- Create: `tauri-app/src/components/ui/PageHeader.tsx`
- Create: `tauri-app/src/components/ui/EmptyState.tsx`

- [ ] Add Playwright assertions for navigation semantics, focus visibility, and common loading/error classes.
- [ ] Run the focused E2E and verify failures.
- [ ] Define design tokens, shared controls, scrollbar, reduced-motion rules, and application shell.
- [ ] Implement focused shared components with existing React/Tailwind patterns and no new dependency.
- [ ] Re-run focused E2E and TypeScript.

### Task 6: Live AI panel

**Files:**
- Create: `tauri-app/src/components/transcription/LiveAiPanel.tsx`
- Create: `tauri-app/src/components/transcription/liveAiState.ts`
- Modify: `tauri-app/src/components/Transcription.tsx`
- Modify: `tauri-app/e2e/interaction.spec.ts`

- [ ] Write failing E2E tests for panel toggle, tabs, preset/custom range, summary request, question request, duplicate-submit prevention, error retention, and answer history.
- [ ] Run the focused E2E and verify expected failures.
- [ ] Implement pure range-label/history helpers and the panel UI.
- [ ] Integrate panel state into `Transcription`, preserving it across app-tab switches and resetting it only on a successful new session start.
- [ ] Keep recording controls independent from AI loading state.
- [ ] Re-run E2E and TypeScript.

### Task 7: Recording workspace polish

**Files:**
- Modify: `tauri-app/src/components/Transcription.tsx`
- Modify: `tauri-app/src/components/transcription/RecordingControls.tsx`
- Modify: `tauri-app/src/components/transcription/TranscriptSearch.tsx`
- Modify: `tauri-app/src/components/transcription/TranscriptList.tsx`
- Modify: `tauri-app/src/components/StatusBar.tsx`
- Modify: `tauri-app/e2e/audio.spec.ts`

- [ ] Extend recording E2E to assert controls remain usable while AI is loading.
- [ ] Consolidate recording metadata and controls into a compact toolbar.
- [ ] Preserve WebSocket, REST fallback, audio sidecar, silence warning, discard, and session-stop behavior.
- [ ] Verify recording E2E, TypeScript, and existing backend startup guard tests.

## Chunk 3: Remaining Screens

### Task 8: Speakers and dictionary

**Files:**
- Modify: `tauri-app/src/components/Speakers.tsx`
- Modify: `tauri-app/src/components/Dictionary.tsx`
- Modify: `tauri-app/e2e/interaction.spec.ts`

- [ ] Add failing E2E assertions for page headers, split speaker layout, dictionary table states, and keyboard focus.
- [ ] Update layout and state presentation without changing API behavior.
- [ ] Verify E2E and TypeScript.

### Task 9: History

**Files:**
- Modify: `tauri-app/src/components/History.tsx`
- Modify: `tauri-app/src/components/history/HistoryHeader.tsx`
- Modify: `tauri-app/src/components/history/SessionList.tsx`
- Modify: `tauri-app/src/components/history/TranscriptView.tsx`
- Modify: `tauri-app/src/components/history/ScreenshotPanel.tsx`
- Modify: `tauri-app/src/components/history/SummaryView.tsx`
- Modify: `tauri-app/e2e/interaction.spec.ts`
- Modify: `tauri-app/e2e/history-screenshot-sync.spec.ts`

- [ ] Add failing tests for loading versus empty state and separated checkbox/star/row targets.
- [ ] Update list and detail toolbars using shared styles.
- [ ] Preserve startup retries, manual refresh, export behavior, and smooth screenshot synchronization.
- [ ] Verify focused E2E and TypeScript.

### Task 10: Settings

**Files:**
- Modify: `tauri-app/src/components/Settings.tsx`
- Modify: `tauri-app/src/components/settings/*.tsx`
- Modify: `tauri-app/e2e/settings.spec.ts`

- [ ] Add failing E2E assertions for connection, recognition, AI, recording, and storage sections.
- [ ] Recompose existing controls into those sections, keeping validation and persistence unchanged.
- [ ] Verify focused E2E and TypeScript.

## Chunk 4: Integration Verification

### Task 11: Automated regression suite

**Files:**
- Modify only files required by failures attributable to this feature.

- [ ] Run `py -3.13 -m pytest -q`.
- [ ] Run `npm run build` in `tauri-app`.
- [ ] Start the mock backend and run the complete Playwright suite.
- [ ] Fix only regressions introduced by this plan, using a failing test for each fix.
- [ ] Repeat until all suites pass.

### Task 12: Visual and live recording verification

**Files:**
- Store temporary screenshots outside Git-tracked source paths.

- [ ] Start the backend and Vite frontend on unused local ports.
- [ ] Capture transcription/AI, speakers, dictionary, history list/detail, and settings at desktop width.
- [ ] Capture the recording/AI screen at narrow width and confirm no overlap or clipped text.
- [ ] Check nonblank rendering, focus, panel motion, reduced motion, scroll ownership, and stable layout dimensions.
- [ ] Perform a short real recording, generate a live summary and a question, and confirm recording continues throughout.
- [ ] Record any environment-only blocker explicitly; do not claim unrun hardware checks passed.

## Self-Review Gate

Before implementation, confirm:

- The live AI route cannot block or mutate the recording pipeline.
- Gemini fallback remains limited to Claude subscription-limit errors.
- Existing dirty changes are preserved.
- No new dependency is required.
- The first implementation slice is independently testable and reversible.
- UI redesign does not replace working data/loading logic with visual-only state.

Run `strategic-checkpoint` after this review. Proceed only on `CONTINUE` or after completing a reversible `CORRECT`; stop for user direction on `REPLAN`.
