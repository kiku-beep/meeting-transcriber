# Transcriber: duplicated rule consolidation

User-approved scope (2026-09-05): consolidate AI summary execution, session selection, and frontend compatibility interpretation while retaining existing behavior.

## Design

Reuse the ordered provider runner and provider functions already present. Direct summary functions own entry validation, prompt construction and title formatting; provider execution owns subprocess/API behavior. Share duplicate code without changing genuine policies: automatic summaries use Claude, Codex, Gemini in order; questions use Claude, Gemini; explicit engines do not fail over.

Direct Gemini summaries retain three attempts with 1/2-second waits and detailed cost usage (empty when metadata is absent). Generic Gemini calls used by auto/live/topic retain one attempt and their simpler usage. Claude/Codex authentication and billing guards remain intact. No external calls are needed for verification.

A shared session resolver accepts a prepared client ID and returns either the default session or the named registry session. Existing transport preparation remains explicit: session REST maps empty to default without trimming; topics/live trim then default; WebSocket retains raw IDs. Connection cleanup and busy-client bookkeeping keep those same keys. Session lifecycle and recording initialization are out of scope.

Frontend usage interpretation has one presentation boundary. Modern billing fields take precedence; older saved diagnostics still render. Preserve the existing difference between history's legacy Gemini inference and live results' explicit billing. Remove unused static URL exports after checking consumers; keep dynamic connection configuration.

## Alternatives

Deleting compatibility outright would break older saved summaries. Unifying recording startup would mix local and remote lifecycle differences. A new provider service/framework would add complexity. This change therefore extracts shared decisions within the existing modules.

## Verification

Baseline: 226 Python tests pass, frontend `tsc --noEmit` passes. Add focused behavior coverage for provider errors/retries/usage, session-ID edge cases and UI usage interpretation before refactoring. Review requirements and code quality independently, then run full Python regression and frontend type/build checks. No dependency changes, stored-data migration, deployment or remote push.
