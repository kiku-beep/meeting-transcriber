import { apiFetch, getClientId } from "./api";
import type { GeminiModelsResponse, LiveAiMode, LiveAiResult, SummaryEnginesResponse, SummaryResult } from "./types";

export async function generateSummary(sessionId: string, forceRegenerate = false): Promise<SummaryResult> {
  return apiFetch("/api/summary/generate", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, force_regenerate: forceRegenerate }),
  });
}

export async function generateLiveAi(
  mode: LiveAiMode,
  rangeMinutes: number | null,
  question?: string,
): Promise<LiveAiResult> {
  return apiFetch("/api/summary/live", {
    method: "POST",
    body: JSON.stringify({
      client_id: getClientId(),
      mode,
      range_minutes: rangeMinutes,
      question: question || null,
    }),
  });
}

export async function getSummary(sessionId: string): Promise<{ session_id: string; summary: string }> {
  return apiFetch(`/api/summary/${sessionId}`);
}

export async function getGeminiModels(): Promise<GeminiModelsResponse> {
  return apiFetch("/api/summary/models");
}

export async function getSummaryEngines(): Promise<SummaryEnginesResponse> {
  return apiFetch("/api/summary/engines");
}

export async function setGeminiModel(modelId: string): Promise<{ current_model: string }> {
  return apiFetch("/api/summary/model", {
    method: "PUT",
    body: JSON.stringify({ model_id: modelId }),
  });
}

export async function setSummaryEngine(engineId: string): Promise<{ current_engine: string }> {
  return apiFetch("/api/summary/engine", {
    method: "PUT",
    body: JSON.stringify({ engine_id: engineId }),
  });
}
