import { apiFetch, BASE_URL } from "./api";
import type { ScreenshotsResponse, ScreenCaptureConfig } from "./types";

export function getScreenshotUrl(sessionId: string, filename: string): string {
  return `${BASE_URL}/api/screenshots/${sessionId}/${filename}`;
}

export async function listScreenshots(sessionId: string): Promise<ScreenshotsResponse> {
  return apiFetch(`/api/screenshots/${sessionId}`);
}

export async function deleteScreenshots(
  sessionId: string,
): Promise<{ session_id: string; deleted_count: number }> {
  return apiFetch(`/api/screenshots/${sessionId}`, { method: "DELETE" });
}

export async function getScreenCaptureConfig(): Promise<ScreenCaptureConfig> {
  return apiFetch("/api/config/screenshots");
}

export async function setScreenCaptureConfig(
  config: Partial<ScreenCaptureConfig>,
): Promise<ScreenCaptureConfig> {
  return apiFetch("/api/config/screenshots", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}
