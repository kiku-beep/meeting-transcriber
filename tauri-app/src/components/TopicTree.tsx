import { useCallback, useEffect, useState } from "react";
import { getSessionStatus } from "../lib/apiSession";
import { fetchTopics, refreshTopics, type TopicRefreshStatus } from "../lib/apiTopics";
import { useWebSocket } from "../lib/useWebSocket";
import type { SessionInfo, TopicTree as TopicTreeData } from "../lib/types";
import TopicTreeView from "./topics/TopicTreeView";

const EMPTY_TREE: TopicTreeData = { nodes: [], links: [], active: null };

// 「更新なし」をひとまとめにすると、機能OFFやLLM失敗を取り違える。
// 失敗はサーバが500で返すので error 側に出る。
const REFRESH_MESSAGES: Record<TopicRefreshStatus, string> = {
  updated: "更新しました",
  no_new_entries: "新しい発話が足りません",
  busy: "他で実行中",
  disabled: "論点ツリーが無効です（設定でONにしてください）",
};

function isRecording(status: SessionInfo | null): boolean {
  return status?.status === "starting" || status?.status === "running" || status?.status === "paused";
}

export default function TopicTree() {
  const [tree, setTree] = useState<TopicTreeData>(EMPTY_TREE);
  const [sessionStatus, setSessionStatus] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [refreshMessage, setRefreshMessage] = useState("");

  // 周期更新の失敗もこの経路で届く（error 付きのツリー）。ツリーの中身は
  // 変わらないので置き換えて問題ない。成功すると error が消えるので晴れる。
  const handleTopic = useCallback((nextTree: TopicTreeData) => {
    setTree(nextTree);
    setLoading(false);
    setError(nextTree.error ? `自動更新に失敗しています: ${nextTree.error}` : "");
  }, []);

  const handleStatus = useCallback((nextStatus: SessionInfo) => {
    setSessionStatus(nextStatus);
  }, []);

  const handleClear = useCallback(() => {
    setTree(EMPTY_TREE);
  }, []);

  useWebSocket({ onTopic: handleTopic, onStatus: handleStatus, onClear: handleClear, enabled: true });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    fetchTopics()
      .then((initialTree) => {
        if (cancelled) return;
        setTree(initialTree);
        if (initialTree.error) setError(`自動更新に失敗しています: ${initialTree.error}`);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "論点ツリーを取得できませんでした");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    getSessionStatus()
      .then((status) => {
        if (!cancelled) setSessionStatus(status);
      })
      .catch(() => {
        // The WebSocket status is the primary source when REST is unavailable.
      });

    return () => { cancelled = true; };
  }, []);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setError("");
    setRefreshMessage("");
    try {
      const result = await refreshTopics();
      if (result.conflict) {
        setRefreshMessage(REFRESH_MESSAGES.busy);
      } else {
        setTree(result.tree);
        setRefreshMessage(
          (result.status && REFRESH_MESSAGES[result.status]) ??
            (result.updated ? REFRESH_MESSAGES.updated : REFRESH_MESSAGES.no_new_entries),
        );
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "論点ツリーを更新できませんでした");
    } finally {
      setRefreshing(false);
    }
  }, []);

  const hasNodes = tree.nodes.length > 0;

  return (
    <div className="workspace-page topic-tree-page">
      <div className="page-heading">
        <div>
          <p className="workspace-eyebrow">MEETING MAP</p>
          <h2>議論マップ</h2>
        </div>
        <div className="topic-tree-page__actions">
          {sessionStatus && (
            <span className={`status-chip ${isRecording(sessionStatus) ? "status-chip--ok" : "status-chip--waiting"}`}>
              {isRecording(sessionStatus) ? "録音中" : "待機中"}
            </span>
          )}
          <button type="button" className="button-secondary" onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? "更新中…" : "更新"}
          </button>
        </div>
      </div>

      {error && <div className="inline-alert inline-alert--error" role="alert">{error}</div>}
      {refreshMessage && <div className="inline-alert inline-alert--warning" role="status">{refreshMessage}</div>}

      <section className="topic-tree-page__section" aria-label="論点一覧">
        {loading ? (
          <div className="topic-tree-page__empty">読み込み中…</div>
        ) : !hasNodes ? (
          <div className="topic-tree-page__empty">
            <strong>{isRecording(sessionStatus) ? "論点を抽出中…" : "録音を開始すると論点が表示されます"}</strong>
            <span>{isRecording(sessionStatus) ? "会議の内容がまとまると、ここに論点が追加されます。" : "録音中の会議から、話題の流れを整理します。"}</span>
          </div>
        ) : (
          <TopicTreeView tree={tree} />
        )}
      </section>
    </div>
  );
}
