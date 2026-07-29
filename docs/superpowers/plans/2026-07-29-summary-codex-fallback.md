# Summary Codex Fallback Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development (if subagents available) or executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route post-meeting and interim summaries through Claude Code CLI, Codex CLI, then Gemini API while keeping questions on Claude Code CLI then Gemini API.

**Architecture:** A private provider-chain runner returns one stable text result shape and records every failed provider. Post-meeting summaries adapt that text result to the existing `summary/title/usage` API, while live AI calls explicit summary or question wrappers. Codex runs only with verified ChatGPT authentication in an empty temporary directory.

**Tech Stack:** Python 3.13, asyncio subprocesses, pytest, React/TypeScript, Playwright

---

## Chunk 1: Backend Provider Chain

### Task 1: Define Codex settings and provider contracts

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/core/summarizer.py`
- Test: `tests/test_summary_engine.py`

- [ ] **Step 1: Write failing settings and engine-label tests**

Assert the settings defaults are `codex`, `gen`, and `300.0`, and that the
`auto` engine label describes all three providers.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:
`.venv\Scripts\python.exe -m pytest tests/test_summary_engine.py -k "codex_settings or engine_route" -v`

Expected: failures because the Codex settings and label do not exist.

- [ ] **Step 3: Add the minimal settings and label changes**

Add:

```python
codex_cli_command: str = "codex"
codex_cli_profile: str = "gen"
codex_cli_timeout_s: float = 300.0
```

Update only the `auto` engine label and description.

- [ ] **Step 4: Re-run the focused tests**

Expected: PASS.

### Task 2: Add the subscription-safe Codex provider

**Files:**
- Modify: `backend/core/summarizer.py`
- Test: `tests/test_summary_engine.py`

- [ ] **Step 1: Write failing Codex provider tests**

Cover:

- API credential environment variables reject Codex before generation.
- `codex login status` must report `Logged in using ChatGPT`.
- `codex login status` uses `codex_cli_timeout_s`; timeout kills the process,
  cleans the temporary directory, and is treated as a provider failure so the
  chain can proceed to Gemini.
- `codex exec -p gen` receives the prompt through stdin.
- execution uses `--ephemeral`, `--sandbox read-only`, `--ignore-rules`,
  `--skip-git-repo-check`, and `--output-last-message`.
- the launch directory is empty.
- the final-message file is the only content returned.
- success, non-zero exit, and timeout remove the temporary directory.

- [ ] **Step 2: Run the Codex-provider tests and confirm they fail**

Run:
`.venv\Scripts\python.exe -m pytest tests/test_summary_engine.py -k "codex_cli" -v`

Expected: failures because the provider does not exist.

- [ ] **Step 3: Implement the minimal Codex provider**

Add `_ensure_codex_subscription_mode`, provider-aware subprocess timeout
handling, and `_generate_text_with_codex_cli`. Keep the `gen` profile as the
model/reasoning source of truth.

- [ ] **Step 4: Re-run the Codex-provider tests**

Expected: PASS.

### Task 3: Add the ordered summary runner

**Files:**
- Modify: `backend/core/summarizer.py`
- Test: `tests/test_summary_engine.py`

- [ ] **Step 1: Write failing provider-order and metadata tests**

Verify:

- Claude success skips Codex and Gemini.
- Claude failure plus Codex success skips Gemini.
- two failures call Gemini.
- all failures produce one combined diagnostic.
- usage includes `fallback_from`, `fallback_detail`, `fallback_chain`,
  `fallback_details`, and `fallback_reason="provider-error"`.
- `generate_summary()` still returns `summary`, `title`, and `usage`.
- explicit `summary_engine="claude-code"` calls only Claude and never falls
  back.
- explicit `summary_engine="gemini"` calls only Gemini and never calls Claude
  or Codex.

- [ ] **Step 2: Run the focused fallback tests and confirm they fail**

Run:
`.venv\Scripts\python.exe -m pytest tests/test_summary_engine.py -k "fallback or provider_chain" -v`

Expected: failures showing the current two-provider behavior.

- [ ] **Step 3: Implement the runner and explicit wrappers**

Implement:

```python
async def _run_provider_chain(prompt: str, providers: tuple[Provider, ...]) -> dict
async def generate_summary_text(prompt: str) -> dict
async def generate_question_text(prompt: str) -> dict
```

Adapt `generate_summary_auto` to extract the title and preserve its public
return shape. Both text wrappers read `settings.summary_engine`: `auto` uses
their defined chain, while explicit `gemini` and `claude-code` select only
that provider with no fallback.

- [ ] **Step 4: Run all summary-engine tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_summary_engine.py -v`

Expected: PASS.

## Chunk 2: Live Summary and UI Metadata

### Task 4: Keep the question path at two providers

**Files:**
- Modify: `backend/core/live_ai.py`
- Test: `tests/test_live_ai.py`

- [ ] **Step 1: Write failing mode-routing tests**

Patch `generate_summary_text` and `generate_question_text` separately. Assert
that `mode="summary"` calls only the summary wrapper and `mode="question"`
calls only the question wrapper. Also assert explicit `gemini` and
`claude-code` settings remain single-provider routes for both live modes.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_live_ai.py -k "provider or question_prompt" -v`

Expected: failures because both modes currently use one shared function.

- [ ] **Step 3: Route each mode to its explicit wrapper**

Select the wrapper inside the existing mode branch and return its result after
prompt construction.

- [ ] **Step 4: Run all live-AI tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_live_ai.py tests/test_routes_live_ai.py -v`

Expected: PASS.

### Task 5: Represent Codex and multi-step fallback in the UI

**Files:**
- Modify: `tauri-app/src/lib/types.ts`
- Modify: `tauri-app/src/components/history/SummaryView.tsx`
- Modify: `tauri-app/src/components/transcription/LiveAiPanel.tsx`
- Modify: `tauri-app/e2e/live-ai.spec.ts`

- [ ] **Step 1: Add failing UI assertions**

Add mocked Codex-success and Gemini-after-two-failures cases. Assert:

- Codex results show `Codex CLI` and `Codexサブスク枠`.
- Gemini results list both Claude and Codex failure details.
- the existing single `fallback_detail` remains accepted.

- [ ] **Step 2: Run the focused Playwright test and confirm it fails**

Run from `tauri-app`:
`npx playwright test --project=live-ai --grep "Codex|two-step fallback"`

Expected: failures because TypeScript and badges support only Claude/Gemini.

- [ ] **Step 3: Extend additive usage metadata and rendering**

Add `codex-subscription`, `fallback_chain`, and `fallback_details` to the type.
Render provider badges from `billing`; render all available fallback details
without removing the compatibility field.

- [ ] **Step 4: Run the focused Playwright test**

Expected: PASS.

## Chunk 3: Verification and Build

### Task 6: Run regression checks

**Files:**
- Verify only; do not deploy or restart.

- [ ] **Step 1: Run backend regression tests**

Run:
`.venv\Scripts\python.exe -m pytest tests/test_summary_engine.py tests/test_live_ai.py tests/test_routes_live_ai.py -v`

Expected: PASS.

- [ ] **Step 2: Run frontend typecheck and targeted E2E**

Run from `tauri-app`:

```powershell
npm run build
npx playwright test --project=live-ai --grep "Codex|fallback|meeting AI"
```

Expected: PASS.

- [ ] **Step 3: Build the backend sidecar artifact without deployment**

Run:
`.venv\Scripts\python.exe -m PyInstaller --noconfirm transcriber-backend.spec`

Do not run `build_sidecar.ps1`, because it may install a dependency and copy
over the Tauri sidecar directory. Do not use `-Deploy` or replace the running
binary.

- [ ] **Step 4: Inspect the final diff**

Confirm only the planned files changed for this feature and preserve all
unrelated working-tree changes.

- [ ] **Step 5: Stop at the production approval gate**

Report the artifact and test results. Do not restart, deploy, or consume a real
Claude/Codex/Gemini request until the user explicitly approves that step and
the session is idle.
