import type { SummaryUsage } from "./types";

interface FallbackDiagnostic {
  provider: string;
  label: string;
  detail: string;
}

type Provider = "claude-code" | "codex-cli" | "gemini";

const BILLING_PROVIDERS: Record<NonNullable<SummaryUsage["billing"]>, Provider> = {
  "claude-subscription": "claude-code",
  "codex-subscription": "codex-cli",
  api: "gemini",
};

const FALLBACK_PROVIDER_LABELS: Record<string, string> = {
  "claude-code": "Claude",
  "codex-cli": "Codex",
  gemini: "Gemini",
};

function getFallbackDiagnostics(usage?: SummaryUsage): FallbackDiagnostic[] {
  if (usage?.fallback_chain?.length && usage.fallback_details) {
    return usage.fallback_chain.flatMap((provider) => {
      const detail = usage.fallback_details?.[provider];
      return detail
        ? [{ provider, label: FALLBACK_PROVIDER_LABELS[provider] ?? provider, detail }]
        : [];
    });
  }
  if (!usage?.fallback_detail) return [];
  const provider = usage.fallback_from ?? "claude-code";
  return [{
    provider,
    label: FALLBACK_PROVIDER_LABELS[provider] ?? provider,
    detail: usage.fallback_detail,
  }];
}

export function getUsagePresentation(usage: SummaryUsage | undefined, view: "history" | "live") {
  // Older saved summaries predate billing; live results require explicit billing.
  const provider = usage?.billing
    ? BILLING_PROVIDERS[usage.billing]
    : view === "history" && usage?.fallback_from ? "gemini" : undefined;
  return { provider, diagnostics: getFallbackDiagnostics(usage) };
}
