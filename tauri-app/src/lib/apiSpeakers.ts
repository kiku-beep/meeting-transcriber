import { apiFetch, apiUpload } from "./api";
import type { Speaker } from "./types";

export async function getSpeakers(): Promise<{ speakers: Speaker[] }> {
  return apiFetch("/api/speakers");
}

export async function createSpeakerNameOnly(name: string): Promise<{ speaker: Speaker }> {
  const fd = new FormData();
  fd.append("name", name);
  return apiUpload("/api/speakers/create", fd);
}

export async function registerSpeaker(
  name: string,
  files: File[],
): Promise<{ speaker: Speaker; samples_processed: number }> {
  const fd = new FormData();
  fd.append("name", name);
  files.forEach((f) => fd.append("files", f));
  return apiUpload("/api/speakers", fd);
}

export async function renameSpeaker(speakerId: string, name: string): Promise<{ speaker: Speaker }> {
  return apiFetch(`/api/speakers/${speakerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function deleteSpeaker(speakerId: string): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/speakers/${speakerId}`, { method: "DELETE" });
}

export async function addSpeakerSamples(
  speakerId: string,
  files: File[],
): Promise<{ speaker: Speaker; total_samples: number }> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  return apiUpload(`/api/speakers/${speakerId}/samples`, fd);
}

export async function recomputeEmbedding(speakerId: string): Promise<{ speaker: Speaker }> {
  return apiFetch(`/api/speakers/${speakerId}/recompute`, { method: "POST" });
}

export async function recomputeAll(): Promise<{ recomputed: string[]; skipped: string[]; failed: string[] }> {
  return apiFetch("/api/speakers/recompute-all", { method: "POST" });
}
