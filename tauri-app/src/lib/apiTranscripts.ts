import { apiFetch, apiFetchText } from "./api";
import type { TranscriptEntry, TranscriptSession, EntryEditRequest, EntryEditResponse } from "./types";

export async function getSessions(): Promise<{ sessions: TranscriptSession[] }> {
  return apiFetch("/api/transcripts");
}

export async function getTranscript(
  sessionId: string,
): Promise<{ session_id: string; entries: TranscriptEntry[] }> {
  return apiFetch(`/api/transcripts/${sessionId}`);
}

export async function exportTranscript(sessionId: string, format: "txt" | "json" | "md"): Promise<string> {
  if (format === "json") {
    const data = await apiFetch<{ session_id: string; entries: TranscriptEntry[] }>(
      `/api/transcripts/${sessionId}/export?format=json`,
    );
    return JSON.stringify(data, null, 2);
  }
  return apiFetchText(`/api/transcripts/${sessionId}/export?format=${format}`);
}

export async function deleteSession(sessionId: string): Promise<{ deleted: string }> {
  return apiFetch(`/api/transcripts/${sessionId}`, { method: "DELETE" });
}

export async function editSavedEntry(
  sessionId: string,
  entryId: string,
  req: EntryEditRequest,
): Promise<EntryEditResponse> {
  return apiFetch(`/api/transcripts/${sessionId}/entries/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify(req),
  });
}

export async function deleteSavedEntry(
  sessionId: string,
  entryId: string,
): Promise<{ deleted: string }> {
  return apiFetch(`/api/transcripts/${sessionId}/entries/${entryId}`, { method: "DELETE" });
}

export async function renameSession(
  sessionId: string,
  sessionName: string,
): Promise<{ session_id: string; session_name: string }> {
  return apiFetch(`/api/transcripts/${sessionId}/name`, {
    method: "PATCH",
    body: JSON.stringify({ session_name: sessionName }),
  });
}

// ── Favorites & Folders ──────────────────────────────────────────

export async function setSessionFavorite(
  sessionId: string,
  isFavorite: boolean,
): Promise<{ session_id: string; is_favorite: boolean }> {
  return apiFetch(`/api/transcripts/${sessionId}/favorite`, {
    method: "PATCH",
    body: JSON.stringify({ is_favorite: isFavorite }),
  });
}

export async function setSessionFolder(
  sessionId: string,
  folder: string,
): Promise<{ session_id: string; folder: string }> {
  return apiFetch(`/api/transcripts/${sessionId}/folder`, {
    method: "PATCH",
    body: JSON.stringify({ folder }),
  });
}

export async function getSessionFolders(): Promise<{
  folders: { name: string; count: number }[];
}> {
  return apiFetch("/api/transcripts/folders");
}

export async function createFolder(
  name: string,
): Promise<{ name: string }> {
  return apiFetch("/api/transcripts/folders", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function renameFolder(
  oldName: string,
  newName: string,
): Promise<{ old_name: string; new_name: string; updated_sessions: number }> {
  return apiFetch(`/api/transcripts/folders/${encodeURIComponent(oldName)}`, {
    method: "PATCH",
    body: JSON.stringify({ name: newName }),
  });
}

export async function deleteFolderApi(
  folderName: string,
): Promise<{ deleted_folder: string; deleted_sessions: number; failed: string[] }> {
  return apiFetch(`/api/transcripts/folders/${encodeURIComponent(folderName)}`, {
    method: "DELETE",
  });
}
