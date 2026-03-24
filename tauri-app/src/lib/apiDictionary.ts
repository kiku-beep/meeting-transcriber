import { apiFetch } from "./api";
import type { DictionaryConfig, ReplacementRule, ReplacementRuleRequest, FillerConfigRequest, LearningSuggestion } from "./types";

export async function getDictionary(): Promise<DictionaryConfig> {
  return apiFetch("/api/dictionary");
}

export async function reloadDictionary(): Promise<DictionaryConfig> {
  return apiFetch("/api/dictionary/reload", { method: "POST" });
}

export async function addReplacement(rule: ReplacementRuleRequest): Promise<ReplacementRule> {
  return apiFetch("/api/dictionary", {
    method: "POST",
    body: JSON.stringify(rule),
  });
}

export async function updateReplacement(index: number, rule: ReplacementRuleRequest): Promise<ReplacementRule> {
  return apiFetch(`/api/dictionary/${index}`, {
    method: "PUT",
    body: JSON.stringify(rule),
  });
}

export async function deleteReplacement(index: number): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/dictionary/${index}`, { method: "DELETE" });
}

export async function updateFillers(config: FillerConfigRequest): Promise<DictionaryConfig> {
  return apiFetch("/api/dictionary/fillers", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function testDictionary(text: string): Promise<Record<string, string>> {
  return apiFetch("/api/dictionary/test", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function getSuggestions(): Promise<{ suggestions: LearningSuggestion[] }> {
  return apiFetch("/api/dictionary/suggestions");
}

export async function acceptSuggestion(from_text: string, to_text: string): Promise<ReplacementRule> {
  return apiFetch("/api/dictionary/suggestions/accept", {
    method: "POST",
    body: JSON.stringify({ from_text, to_text }),
  });
}

export async function getCorrections(): Promise<{ corrections: Record<string, unknown>[] }> {
  return apiFetch("/api/dictionary/corrections");
}
