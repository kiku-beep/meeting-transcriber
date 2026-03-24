import { apiFetch } from "./api";
import type {
  SessionInfo,
  StartRequest,
  TranscriptEntry,
  Speaker,
  ModelStatus,
  ModelSwitchRequest,
  ModelLoadingStatus,
  RegisterSpeakerRequest,
  RegisterSpeakerResponse,
  NameClusterRequest,
  NameClusterResponse,
  ExpectedSpeakersRequest,
  ExpectedSpeakersResponse,
  EntryEditRequest,
  EntryEditResponse,
} from "./types";

export async function startSession(req: StartRequest): Promise<SessionInfo> {
  return apiFetch("/api/session/start", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function stopSession(): Promise<SessionInfo> {
  return apiFetch("/api/session/stop", { method: "POST" });
}

export async function pauseSession(): Promise<SessionInfo> {
  return apiFetch("/api/session/pause", { method: "POST" });
}

export async function discardSession(): Promise<SessionInfo> {
  return apiFetch("/api/session/discard", { method: "POST" });
}

export async function getSessionStatus(): Promise<SessionInfo> {
  return apiFetch("/api/session/status");
}

export async function getSessionEntries(): Promise<{ entries: TranscriptEntry[] }> {
  return apiFetch("/api/session/entries");
}

export async function getModelStatus(): Promise<ModelStatus> {
  return apiFetch("/api/session/model");
}

export async function switchModel(req: ModelSwitchRequest): Promise<{ model_size: string; is_loaded: boolean }> {
  return apiFetch("/api/session/model", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function warmModelCache(modelSize: string): Promise<{ status: string }> {
  return apiFetch("/api/session/model/warm-cache", {
    method: "POST",
    body: JSON.stringify({ model_size: modelSize }),
  });
}

export async function getModelLoadingStatus(): Promise<ModelLoadingStatus> {
  return apiFetch("/api/session/model/loading-status");
}

export async function registerSpeakerFromEntry(req: RegisterSpeakerRequest): Promise<RegisterSpeakerResponse> {
  return apiFetch("/api/session/register-speaker", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function nameCluster(req: NameClusterRequest): Promise<NameClusterResponse> {
  return apiFetch("/api/session/name-cluster", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function setExpectedSpeakers(req: ExpectedSpeakersRequest): Promise<ExpectedSpeakersResponse> {
  return apiFetch("/api/session/expected-speakers", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getExpectedSpeakers(): Promise<ExpectedSpeakersResponse> {
  return apiFetch("/api/session/expected-speakers");
}

export async function editSessionEntry(entryId: string, req: EntryEditRequest): Promise<EntryEditResponse> {
  return apiFetch(`/api/session/entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(req),
  });
}

export async function deleteSessionEntry(entryId: string): Promise<{ deleted: string }> {
  return apiFetch(`/api/session/entries/${entryId}`, { method: "DELETE" });
}

export async function registerNewSpeaker(
  entryId: string,
  name: string,
  isGuest: boolean = false,
): Promise<{ speaker: Speaker; entries: TranscriptEntry[] }> {
  return apiFetch("/api/session/register-new-speaker", {
    method: "POST",
    body: JSON.stringify({ entry_id: entryId, name, is_guest: isGuest || undefined }),
  });
}

export async function bulkUpdateSpeaker(
  oldSpeakerId: string,
  newSpeakerId: string,
  newSpeakerName: string,
): Promise<{ updated_count: number; entries: TranscriptEntry[] }> {
  return apiFetch("/api/session/entries/bulk-update-speaker", {
    method: "PATCH",
    body: JSON.stringify({
      old_speaker_id: oldSpeakerId,
      new_speaker_id: newSpeakerId,
      new_speaker_name: newSpeakerName,
    }),
  });
}

export async function confirmSuggestion(
  clusterId: string,
  speakerId: string,
  speakerName: string,
): Promise<{ updated_count: number; entries: TranscriptEntry[] }> {
  return apiFetch("/api/session/confirm-suggestion", {
    method: "POST",
    body: JSON.stringify({
      cluster_id: clusterId,
      speaker_id: speakerId,
      speaker_name: speakerName,
    }),
  });
}
