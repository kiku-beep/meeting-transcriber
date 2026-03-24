import { apiFetch } from "./api";
import { BASE_URL } from "./api";
import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

export interface AudioInfo {
  has_audio: boolean;
  format: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
}

export function getAudioUrl(sessionId: string): string {
  return `${BASE_URL}/api/playback/${sessionId}/audio`;
}

export async function fetchAudioBlobUrl(sessionId: string): Promise<string> {
  const url = `${BASE_URL}/api/playback/${sessionId}/audio`;
  const res = await tauriFetch(url);
  if (!res.ok) throw new Error(`Audio fetch failed: HTTP ${res.status}`);
  const arrayBuffer = await res.arrayBuffer();
  const contentType = res.headers.get("content-type") || "audio/ogg";
  const blob = new Blob([arrayBuffer], { type: contentType });
  return URL.createObjectURL(blob);
}

export async function getAudioInfo(sessionId: string): Promise<AudioInfo> {
  return apiFetch(`/api/playback/${sessionId}/audio/info`);
}

export async function deleteAudio(sessionId: string): Promise<{ deleted: string[]; session_id: string }> {
  return apiFetch(`/api/playback/${sessionId}/audio`, { method: "DELETE" });
}

export async function compressAudio(sessionId: string): Promise<{ status: string; session_id: string }> {
  return apiFetch(`/api/playback/${sessionId}/compress`, { method: "POST" });
}

export async function toggleBookmark(
  sessionId: string,
  entryId: string,
): Promise<{ entry_id: string; bookmarked: boolean }> {
  return apiFetch(`/api/transcripts/${sessionId}/entries/${entryId}/bookmark`, {
    method: "PATCH",
  });
}
