import { apiFetch } from "./api";
import type { GpuStatus, AudioDevicesResponse } from "./types";

const DEFAULT_HEALTH_WAIT_TIMEOUT_MS = 45_000;
const DEFAULT_HEALTH_WAIT_INTERVAL_MS = 1_000;

export async function getHealth(): Promise<{ status: string }> {
  return apiFetch("/api/health");
}

export function isBackendConnectionError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return (
    message.includes("error sending request") ||
    message.includes("Failed to fetch") ||
    message.includes("NetworkError") ||
    message.includes("backend not ready") ||
    message.includes("接続できません") ||
    message.includes("connection refused") ||
    message.includes("Connection refused")
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitForBackendHealth(options: {
  timeoutMs?: number;
  intervalMs?: number;
} = {}): Promise<void> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_HEALTH_WAIT_TIMEOUT_MS;
  const intervalMs = options.intervalMs ?? DEFAULT_HEALTH_WAIT_INTERVAL_MS;
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;

  while (Date.now() <= deadline) {
    try {
      const health = await getHealth();
      if (health.status === "ok") return;
      lastError = new Error(`Unexpected health status: ${health.status}`);
    } catch (e) {
      lastError = e;
    }
    await sleep(intervalMs);
  }

  if (lastError instanceof Error) throw lastError;
  throw new Error("Backend health check timed out");
}

export async function getGpuStatus(): Promise<GpuStatus> {
  return apiFetch("/api/health/gpu");
}

export async function getAudioDevices(): Promise<AudioDevicesResponse> {
  return apiFetch("/api/audio/devices");
}
