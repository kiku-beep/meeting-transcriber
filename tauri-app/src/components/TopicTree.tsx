import { useCallback, useEffect, useState } from "react";
import { getSessionStatus } from "../lib/apiSession";
import { fetchTopics, refreshTopics } from "../lib/apiTopics";
import { useWebSocket } from "../lib/useWebSocket";
import type { SessionInfo, TopicNode as TopicNodeData, TopicTree as TopicTreeData } from "../lib/types";
import TopicNode from "./topics/TopicNode";

const EMPTY_TREE: TopicTreeData = { nodes: [], active: null };

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

  const handleTopic = useCallback((nextTree: TopicTreeData) => {
    setTree(nextTree);
    setLoading(false);
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
        if (!cancelled) setTree(initialTree);
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
        setRefreshMessage("他で実行中");
      } else {
        setTree(result.tree);
        setRefreshMessage(result.updated ? "更新しました" : "新しい論点はありません");
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "論点ツリーを更新できませんでした");
    } finally {
      setRefreshing(false);
    }
  }, []);

  const nodesById = new Set(tree.nodes.map((node) => node.id));
  const childrenByParent = new Map<string, TopicNodeData[]>();
  tree.nodes.forEach((node) => {
    if (node.parent === null) return;
    const children = childrenByParent.get(node.parent) ?? [];
    children.push(node);
    childrenByParent.set(node.parent, children);
  });
  const roots = tree.nodes.filter((node) => node.parent === null || !nodesById.has(node.parent));

  // roots から到達できるノードを純粋に求める（レンダー中に共有stateを
  // 書き換えると StrictMode の二重レンダーで2回目に何も描画されない）。
  const reachable = new Set<string>();
  const stack = roots.map((node) => node.id);
  while (stack.length > 0) {
    const id = stack.pop() as string;
    if (reachable.has(id)) continue;
    reachable.add(id);
    (childrenByParent.get(id) ?? []).forEach((child) => stack.push(child.id));
  }
  // 循環だけで構成され roots から辿れないノードも取りこぼさず出す。
  // ただし各連結成分の入口だけを出す（全部を並べると子として描いたものが
  // もう一度トップレベルにも出て二重表示になる）。
  const detachedSeen = new Set<string>();
  const detached: TopicNodeData[] = [];
  tree.nodes.forEach((node) => {
    if (reachable.has(node.id) || detachedSeen.has(node.id)) return;
    detached.push(node);
    const walk = [node.id];
    while (walk.length > 0) {
      const id = walk.pop() as string;
      if (detachedSeen.has(id)) continue;
      detachedSeen.add(id);
      (childrenByParent.get(id) ?? []).forEach((child) => walk.push(child.id));
    }
  });
  const hasNodes = tree.nodes.length > 0;

  return (
    <div className="workspace-page topic-tree-page">
      <div className="page-heading">
        <div>
          <p className="workspace-eyebrow">MEETING MAP</p>
          <h2>論点ツリー</h2>
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
          <div className="topic-tree" role="tree" aria-label="論点ツリー">
            {roots.map((node) => (
              <TopicNode
                key={node.id}
                node={node}
                childrenByParent={childrenByParent}
                activeId={tree.active}
                path={new Set()}
              />
            ))}
            {detached.map((node) => (
              <TopicNode
                key={node.id}
                node={node}
                childrenByParent={childrenByParent}
                activeId={tree.active}
                path={new Set()}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
