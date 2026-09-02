import { ApiError, apiFetch, apiUpload, getBaseUrl } from "./api";
import type { Speaker } from "./types";

const SPEAKER_RETRY_COUNT = 4;
const SPEAKER_RETRY_DELAY_MS = 600;
const SPEAKER_CACHE_TTL_MS = 10_000;

type SpeakerResponse = { speakers: Speaker[] };

let cachedSpeakers: { baseUrl: string; value: SpeakerResponse; cachedAt: number } | null = null;
let inFlightRequest: { baseUrl: string; promise: Promise<SpeakerResponse> } | null = null;

function invalidateSpeakerCache(): void {
  cachedSpeakers = null;
}

async function fetchSpeakersWithRetry(): Promise<SpeakerResponse> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= SPEAKER_RETRY_COUNT; attempt += 1) {
    try {
      return await apiFetch("/api/speakers");
    } catch (error) {
      lastError = error;
      const retryable = !(error instanceof ApiError) || error.status === 429 || error.status >= 500;
      if (attempt < SPEAKER_RETRY_COUNT && retryable) {
        await new Promise((resolve) => window.setTimeout(resolve, SPEAKER_RETRY_DELAY_MS));
      } else {
        break;
      }
    }
  }
  throw lastError;
}

export async function getSpeakers(): Promise<{ speakers: Speaker[] }> {
  const baseUrl = getBaseUrl();
  if (
    cachedSpeakers?.baseUrl === baseUrl
    && Date.now() - cachedSpeakers.cachedAt < SPEAKER_CACHE_TTL_MS
  ) {
    return cachedSpeakers.value;
  }
  if (inFlightRequest?.baseUrl === baseUrl) {
    return inFlightRequest.promise;
  }

  const promise = fetchSpeakersWithRetry()
    .then((value) => {
      cachedSpeakers = { baseUrl, value, cachedAt: Date.now() };
      return value;
    })
    .finally(() => {
      if (inFlightRequest?.promise === promise) inFlightRequest = null;
    });
  inFlightRequest = { baseUrl, promise };
  return promise;
}

export async function createSpeakerNameOnly(name: string): Promise<{ speaker: Speaker }> {
  const fd = new FormData();
  fd.append("name", name);
  const result = await apiUpload<{ speaker: Speaker }>("/api/speakers/create", fd);
  invalidateSpeakerCache();
  return result;
}

export async function registerSpeaker(
  name: string,
  files: File[],
): Promise<{ speaker: Speaker; samples_processed: number }> {
  const fd = new FormData();
  fd.append("name", name);
  files.forEach((f) => fd.append("files", f));
  const result = await apiUpload<{ speaker: Speaker; samples_processed: number }>("/api/speakers", fd);
  invalidateSpeakerCache();
  return result;
}

export async function renameSpeaker(speakerId: string, name: string): Promise<{ speaker: Speaker }> {
  const result = await apiFetch<{ speaker: Speaker }>(`/api/speakers/${speakerId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  invalidateSpeakerCache();
  return result;
}

export async function deleteSpeaker(speakerId: string): Promise<{ deleted: boolean }> {
  const result = await apiFetch<{ deleted: boolean }>(`/api/speakers/${speakerId}`, { method: "DELETE" });
  invalidateSpeakerCache();
  return result;
}

export async function addSpeakerSamples(
  speakerId: string,
  files: File[],
): Promise<{ speaker: Speaker; total_samples: number }> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const result = await apiUpload<{ speaker: Speaker; total_samples: number }>(`/api/speakers/${speakerId}/samples`, fd);
  invalidateSpeakerCache();
  return result;
}

export async function recomputeEmbedding(speakerId: string): Promise<{ speaker: Speaker }> {
  const result = await apiFetch<{ speaker: Speaker }>(`/api/speakers/${speakerId}/recompute`, { method: "POST" });
  invalidateSpeakerCache();
  return result;
}

export async function recomputeAll(): Promise<{ recomputed: string[]; skipped: string[]; failed: string[] }> {
  const result = await apiFetch<{ recomputed: string[]; skipped: string[]; failed: string[] }>("/api/speakers/recompute-all", { method: "POST" });
  invalidateSpeakerCache();
  return result;
}
