import { apiFetch } from "./api";
import type { GeminiModelsResponse, SummaryResult } from "./types";

export async function generateSummary(sessionId: string): Promise<SummaryResult> {
  return apiFetch("/api/summary/generate", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function getSummary(sessionId: string): Promise<{ session_id: string; summary: string }> {
  return apiFetch(`/api/summary/${sessionId}`);
}

export async function getGeminiModels(): Promise<GeminiModelsResponse> {
  return apiFetch("/api/summary/models");
}

export async function setGeminiModel(modelId: string): Promise<{ current_model: string }> {
  return apiFetch("/api/summary/model", {
    method: "PUT",
    body: JSON.stringify({ model_id: modelId }),
  });
}
