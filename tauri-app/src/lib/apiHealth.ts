import { apiFetch } from "./api";
import type { GpuStatus, AudioDevicesResponse } from "./types";

export async function getHealth(): Promise<{ status: string }> {
  return apiFetch("/api/health");
}

export async function getGpuStatus(): Promise<GpuStatus> {
  return apiFetch("/api/health/gpu");
}

export async function getAudioDevices(): Promise<AudioDevicesResponse> {
  return apiFetch("/api/audio/devices");
}
