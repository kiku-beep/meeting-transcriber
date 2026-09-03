/**
 * Audio sidecar control — manages the local audio capture process
 * that streams mic + WASAPI loopback to the remote transcription server.
 */

import { invoke } from "@tauri-apps/api/core";
import { getBaseUrl, getClientId, getAuthToken, isTauriRuntime } from "./api";

export interface AudioSidecarStartOptions {
  sessionName?: string;
  micIndex?: number | null;
  loopbackIndex?: number | null;
}

/** Start the audio capture sidecar. */
export async function startAudioSidecar(
  options: AudioSidecarStartOptions = {},
): Promise<string> {
  if (!isTauriRuntime()) {
    throw new Error("リモート録音はMacアプリでのみ利用できます。Tauriアプリから起動してください。");
  }

  return invoke<string>("start_audio_sidecar", {
    serverUrl: getBaseUrl(),
    clientId: getClientId(),
    token: getAuthToken(),
    sessionName: options.sessionName ?? "",
    micIndex: options.micIndex ?? null,
    loopbackIndex: options.loopbackIndex ?? null,
  });
}

/** Stop the audio capture sidecar. */
export async function stopAudioSidecar(): Promise<string> {
  if (!isTauriRuntime()) {
    return "audio sidecar is unavailable outside Tauri";
  }

  return invoke<string>("stop_audio_sidecar");
}

/** Check if the audio sidecar is running. */
export async function isAudioSidecarRunning(): Promise<boolean> {
  if (!isTauriRuntime()) {
    return false;
  }

  return invoke<boolean>("get_audio_sidecar_status");
}

/**
 * Check if we're in remote server mode (backend URL is not localhost).
 */
export function isRemoteMode(): boolean {
  const url = getBaseUrl();
  return !url.includes("127.0.0.1") && !url.includes("localhost");
}
