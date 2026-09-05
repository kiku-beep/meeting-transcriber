import assert from "node:assert/strict";
import test from "node:test";
import { getUsagePresentation } from "../src/lib/summaryUsage.ts";

test("missing usage has no provider or diagnostics in either view", () => {
  for (const view of ["history", "live"] as const) {
    assert.deepEqual(getUsagePresentation(undefined, view), {
      provider: undefined,
      diagnostics: [],
    });
  }
});

test("explicit billing overrides legacy fallback inference in both views", () => {
  for (const view of ["history", "live"] as const) {
    for (const [billing, provider] of [
      ["claude-subscription", "claude-code"],
      ["codex-subscription", "codex-cli"],
      ["api", "gemini"],
    ] as const) {
      assert.equal(getUsagePresentation({ billing, fallback_from: "claude-code" }, view).provider, provider);
    }
  }
});

test("legacy fallback infers Gemini only in history and retains diagnostics in live", () => {
  const usage = { fallback_from: "codex-cli", fallback_detail: "timeout" };
  const history = getUsagePresentation(usage, "history");
  const live = getUsagePresentation(usage, "live");
  assert.equal(history.provider, "gemini");
  assert.equal(live.provider, undefined);
  assert.deepEqual(history.diagnostics, [{ provider: "codex-cli", label: "Codex", detail: "timeout" }]);
  assert.deepEqual(live.diagnostics, history.diagnostics);
});

test("modern chain preserves order and ignores missing details without using legacy detail", () => {
  const usage = {
    billing: "api" as const,
    fallback_chain: ["codex-cli", "other", "claude-code"],
    fallback_details: { "codex-cli": "codex failure", other: "other failure" },
    fallback_detail: "legacy failure",
  };
  assert.deepEqual(getUsagePresentation(usage, "history").diagnostics, [
    { provider: "codex-cli", label: "Codex", detail: "codex failure" },
    { provider: "other", label: "other", detail: "other failure" },
  ]);
  assert.deepEqual(getUsagePresentation({ ...usage, fallback_details: {} }, "history").diagnostics, []);
});

test("legacy diagnostics default to Claude and do not imply billing without fallback_from", () => {
  const result = getUsagePresentation({ fallback_detail: "failure" }, "history");
  assert.equal(result.provider, undefined);
  assert.deepEqual(result.diagnostics, [{ provider: "claude-code", label: "Claude", detail: "failure" }]);
});

test("empty modern chain uses legacy diagnostic and never mutates saved usage", () => {
  const usage = Object.freeze({ fallback_chain: [], fallback_from: "gemini", fallback_detail: "failure" });
  assert.deepEqual(getUsagePresentation(usage, "history").diagnostics, [
    { provider: "gemini", label: "Gemini", detail: "failure" },
  ]);
});
