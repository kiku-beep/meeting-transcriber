import { apiFetch } from "./api";

export interface DetectedCall {
  call_type: string;       // "google_meet" | "slack_huddle"
  display_name: string;    // "Google Meet" | "Slack ハドル"
  window_title: string;
  session_name_suggestion: string;
}

export interface CallDetectionConfig {
  enabled: boolean;
  dismiss_duration: number;
}

export async function getCallDetectionConfig(): Promise<CallDetectionConfig> {
  return apiFetch("/api/call-detection/config");
}

export async function updateCallDetectionConfig(
  config: Partial<CallDetectionConfig>,
): Promise<CallDetectionConfig> {
  return apiFetch("/api/call-detection/config", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function getPendingCalls(): Promise<{ calls: DetectedCall[] }> {
  return apiFetch("/api/call-detection/pending");
}

export async function dismissCall(windowTitle: string): Promise<void> {
  await apiFetch(`/api/call-detection/dismiss?window_title=${encodeURIComponent(windowTitle)}`, {
    method: "POST",
  });
}

export async function dismissAllCalls(): Promise<void> {
  await apiFetch("/api/call-detection/dismiss-all", { method: "POST" });
}
