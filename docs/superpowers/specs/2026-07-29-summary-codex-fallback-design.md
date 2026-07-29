# Summary Codex Fallback Design

## Goal

Use subscription-backed local CLIs before the metered Gemini API for meeting
summaries:

1. Claude Code CLI
2. Codex CLI
3. Gemini API

This order applies to post-meeting summaries and in-recording interim
summaries. Meeting questions keep the existing Claude Code to Gemini path.

## Approaches Considered

### A. Duplicate nested fallback logic

Add Claude, Codex, and Gemini `try/except` blocks independently to post-meeting
and live-summary functions.

- Advantage: smallest initial diff.
- Disadvantage: error metadata and fallback behavior will drift between paths.

### B. Shared ordered fallback runner

Implement a small internal runner that tries named providers in order, records
each failure, and annotates the successful result.

- Advantage: one tested definition of ordering, metadata, and all-provider
  failure behavior.
- Disadvantage: adds one small abstraction.

This is the recommended approach.

### C. Separate orchestration service

Move provider routing into a standalone service or process.

- Advantage: maximum isolation and future extensibility.
- Disadvantage: unnecessary process, deployment, and failure complexity for
  three local providers.

## Provider Boundaries

### Claude Code

Keep the existing subscription-safety checks and invocation behavior.

### Codex CLI

- Add explicit settings with these defaults:
  - `codex_cli_command="codex"`
  - `codex_cli_profile="gen"`
  - `codex_cli_timeout_s=300.0`
- Resolve `codex_cli_command` from `PATH`.
- Refuse Codex fallback when `OPENAI_API_KEY`, `CODEX_API_KEY`, or
  `AZURE_OPENAI_API_KEY` is active.
- Run `codex login status` before generation and require the output to contain
  `Logged in using ChatGPT`. Any other authentication state is a provider
  failure, so it cannot silently consume metered OpenAI API credit.
- Invoke `codex exec` non-interactively with the `gen` profile.
- Send the complete summary prompt through stdin.
- Run ephemeral, read-only, without repository rules, from an empty temporary
  working directory.
- Write the final response through `--output-last-message` and use only that
  file as summary content.
- Refactor subprocess timeout handling to receive a provider label and timeout,
  so Claude and Codex failures are reported accurately.
- Remove the temporary directory on success, non-zero exit, and timeout.
- Report usage as `model=codex-cli` and
  `billing=codex-subscription`.

The `gen` profile remains the source of truth for the Codex model and
reasoning effort. The application does not add a second model override.

## Routing API

Use one private ordered runner and two explicit public text-generation
wrappers:

- `_run_provider_chain(prompt, providers)` owns ordering, failure collection,
  and success metadata. It always returns
  `{"content": str, "usage": dict}`.
- `generate_summary_text(prompt)` uses Claude, Codex, then Gemini.
- `generate_question_text(prompt)` uses Claude then Gemini.

`generate_text_with_summary_engine` is replaced by these explicit wrappers.
This prevents a future refactor from accidentally inserting Codex into the
question path.

`generate_summary_auto(entries)` builds the post-meeting prompt, calls
`generate_summary_text`, extracts the title from `content`, and preserves the
existing public return shape:

`{"summary": str, "title": str, "usage": dict}`.

`generate_live_ai` returns the text wrapper result unchanged, preserving its
existing `{"content": str, "usage": dict}` shape.

## Data Flow

### Post-meeting summary

`generate_summary_auto(entries)` builds and validates the prompt once, then
tries:

1. Claude summary provider
2. Codex summary provider
3. Gemini summary provider

### Interim summary

`generate_live_ai(..., mode="summary")` calls `generate_summary_text` for its
prepared prompt.

### Question

`generate_live_ai(..., mode="question")` calls `generate_question_text`, which
retains the existing Claude then Gemini behavior. Codex is not inserted.

## Result Metadata

Every successful result keeps its provider's `model` and `billing`.

When fallback occurs, usage also includes:

- `fallback_from`: the immediately preceding failed provider.
- `fallback_chain`: ordered failed provider IDs.
- `fallback_details`: compact error text keyed by provider ID.
- `fallback_detail`: the error for `fallback_from`, retained for compatibility.
- `fallback_reason`: `provider-error`.

The UI type union adds `codex-subscription`. Summary and interim-summary views
use `billing` for the active-provider badge and render all entries in
`fallback_chain` using `fallback_details`. Existing single-error clients can
continue to read `fallback_from` and `fallback_detail`.

The `auto` engine label and description become
`Claude Code -> Codex CLI -> Gemini`.

## Failure Behavior

- Claude failure always proceeds to Codex for summary requests.
- Codex failure always proceeds to Gemini for summary requests.
- If all three fail, return one error containing compact Claude, Codex, and
  Gemini diagnostics.
- Empty transcripts fail before invoking any provider.
- A missing or unauthenticated Codex CLI is treated as a Codex provider
  failure, not as a fatal routing error.

## Testing

Add regression tests for:

1. Claude success does not call Codex or Gemini.
2. Claude failure and Codex success do not call Gemini.
3. Claude and Codex failure invoke Gemini with complete fallback metadata.
4. All-provider failure reports all three diagnostics.
5. Calling `generate_live_ai(..., mode="summary")` uses the three-provider
   chain.
6. Calling `generate_live_ai(..., mode="question")` retains the two-provider
   chain and never invokes Codex.
7. Codex subprocess receives the prompt through stdin with the constrained
   execution options and reads content from `--output-last-message`.
8. API credential environment variables prevent Codex from launching and
   proceed to Gemini.
9. A non-ChatGPT `codex login status` prevents Codex from launching and
   proceeds to Gemini.
10. Temporary working directories are empty at launch and removed after
    success, non-zero exit, and timeout.
11. UI types and badges represent Claude subscription, Codex subscription,
    and Gemini API results, including one- and two-step fallback diagnostics.
12. `generate_summary()` preserves the `summary`, `title`, and `usage` API
    contract, while `generate_live_ai()` preserves `content` and `usage`.

After unit tests, build the backend sidecar artifact but do not deploy,
restart, or run a real provider-backed summary without a separate explicit
user approval. At that approval gate, confirm the session status is idle,
deploy the sidecar, and run one real summary through Codex fallback without
changing transcription behavior.
