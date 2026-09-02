import { ApiError, apiFetch, getClientId } from "./api";
import type { TopicTree } from "./types";

export interface TopicRefreshResponse {
  updated: boolean;
  tree: TopicTree;
  conflict?: false;
}

export interface TopicRefreshBusyResponse {
  updated: false;
  tree: null;
  conflict: true;
}

export type TopicRefreshResult = TopicRefreshResponse | TopicRefreshBusyResponse;

function topicsPath(clientId: string): string {
  return `/api/topics?client_id=${encodeURIComponent(clientId)}`;
}

export async function fetchTopics(clientId = getClientId()): Promise<TopicTree> {
  return apiFetch<TopicTree>(topicsPath(clientId));
}

export async function refreshTopics(clientId = getClientId()): Promise<TopicRefreshResult> {
  try {
    return await apiFetch<TopicRefreshResponse>("/api/topics/refresh", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId }),
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      return { updated: false, tree: null, conflict: true };
    }
    throw error;
  }
}
