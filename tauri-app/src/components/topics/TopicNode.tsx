import type { TopicNode as TopicNodeData } from "../../lib/types";

interface Props {
  node: TopicNodeData;
  childrenByParent: Map<string, TopicNodeData[]>;
  activeId: string | null;
  depth?: number;
  path: Set<string>;
  /** 与えると時刻ボタンが押せる（履歴表示）。ライブ録音中は音声が無いので省略する。 */
  onSeek?: (seconds: number) => void;
}

const STATUS_META = {
  open: { symbol: "○", label: "未決", className: "topic-node__status--open" },
  decided: { symbol: "✓", label: "決定", className: "topic-node__status--decided" },
  parked: { symbol: "Ⅱ", label: "保留", className: "topic-node__status--parked" },
} as const;

const MAX_DEPTH = 40;

function formatTime(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(safeSeconds / 60);
  return `${minutes}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

export default function TopicNode({
  node,
  childrenByParent,
  activeId,
  depth = 0,
  path,
  onSeek,
}: Props) {
  if (path.has(node.id)) {
    return <div className="topic-node__guard" role="note">循環を検出しました</div>;
  }
  if (depth >= MAX_DEPTH) {
    return <div className="topic-node__guard" role="note">深さ上限に達しました</div>;
  }
  const nextPath = new Set(path);
  nextPath.add(node.id);
  const meta = STATUS_META[node.status] ?? STATUS_META.open;
  const children = childrenByParent.get(node.id) ?? [];
  const active = activeId === node.id;

  return (
    <article
      className={`topic-node ${active ? "topic-node--active" : ""}`}
      data-topic-node-id={node.id}
      data-topic-active={active ? "true" : "false"}
    >
      <div className="topic-node__content">
        <button
          type="button"
          className="topic-node__time"
          disabled={!onSeek}
          onClick={onSeek ? () => onSeek(node.start_sec) : undefined}
          title={onSeek ? "この時刻から再生" : "ライブ録音中はシークできません"}
          aria-label={
            onSeek
              ? `${formatTime(node.start_sec)} から再生`
              : `開始時刻 ${formatTime(node.start_sec)}（ライブ中はシーク不可）`
          }
        >
          {formatTime(node.start_sec)}
        </button>
        <span className="topic-node__label" title={node.label}>{node.label}</span>
        <span className={`topic-node__status ${meta.className}`}>
          <span aria-hidden="true">{meta.symbol}</span>
          <span>{meta.label}</span>
        </span>
      </div>
      {active && <div className="topic-node__active-label">いま話している論点</div>}
      {children.length > 0 && (
        <div className="topic-node__children">
          {children.map((child) => (
            <TopicNode
              key={child.id}
              node={child}
              childrenByParent={childrenByParent}
              activeId={activeId}
              depth={depth + 1}
              path={nextPath}
              onSeek={onSeek}
            />
          ))}
        </div>
      )}
    </article>
  );
}
