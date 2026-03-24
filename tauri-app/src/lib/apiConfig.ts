import { apiFetch } from "./api";
import type { MeetingConfig } from "./types";

export interface ConfigStatus {
  gemini_api_key_set: boolean;
  gemini_api_key_masked: string | null;
  text_refine_enabled?: boolean;
}

export async function getConfigStatus(): Promise<ConfigStatus> {
  return apiFetch("/api/config/status");
}

export async function setGeminiApiKey(key: string): Promise<ConfigStatus> {
  return apiFetch("/api/config/gemini-api-key", {
    method: "PUT",
    body: JSON.stringify({ gemini_api_key: key }),
  });
}

export async function getMeetingConfig(): Promise<MeetingConfig> {
  return apiFetch("/api/config/meeting");
}

export async function setMeetingConfig(
  config: Partial<MeetingConfig>,
): Promise<MeetingConfig> {
  return apiFetch("/api/config/meeting", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function setTextRefine(enabled: boolean): Promise<{ text_refine_enabled: boolean }> {
  return apiFetch("/api/config/text-refine", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}
