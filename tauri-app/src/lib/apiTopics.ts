import { ApiError, apiFetch, getClientId } from "./api";
import type { TopicTree } from "./types";

// サーバが「なぜ更新されなかったか」を返す。updated だけでは
// 発話不足 / 実行中 / 機能OFF が区別できず、LLMが壊れていても
// 画面が「更新なし」と表示してしまうため。
export type TopicRefreshStatus = "updated" | "no_new_entries" | "busy" | "disabled";

export interface TopicRefreshResponse {
  updated: boolean;
  status?: TopicRefreshStatus;
  tree: TopicTree;
  conflict?: false;
}

export interface TopicRefreshBusyResponse {
  updated: false;
  status: "busy";
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
      return { updated: false, status: "busy", tree: null, conflict: true };
    }
    throw error;
  }
}

/** 保存済み会議の論点ツリー。機能OFFで録った会議は保存が無く null を返す。 */
export async function fetchSavedTopics(sessionId: string): Promise<TopicTree | null> {
  try {
    const result = await apiFetch<{ session_id: string; tree: TopicTree }>(
      `/api/topics/session/${encodeURIComponent(sessionId)}`,
    );
    return result.tree;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}
