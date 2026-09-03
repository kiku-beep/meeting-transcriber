import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import type { TopicKind, TopicNode as TopicNodeData } from "../../lib/types";

export interface TopicNodePosition {
  x: number;
  y: number;
}

interface Props {
  node: TopicNodeData;
  position: TopicNodePosition;
  active: boolean;
  /** 与えると時刻から再生できる（履歴表示用）。ライブでは省略する。 */
  onSeek?: (seconds: number) => void;
  children?: ReactNode;
}

const BOX_WIDTH = 160;
const BOX_HEIGHT = 44;

const STATUS_META = {
  open: { symbol: "○", label: "未決" },
  decided: { symbol: "✓", label: "決定" },
  parked: { symbol: "Ⅱ", label: "保留" },
} as const;

const KIND_META: Record<TopicKind, { fill: string; stroke: string; text: string }> = {
  question: { fill: "#1f355e", stroke: "#14233f", text: "#ffffff" },
  claim: { fill: "#dbeafe", stroke: "#2563eb", text: "#173b73" },
  constraint: { fill: "#fee2e2", stroke: "#dc2626", text: "#7f1d1d" },
  decision: { fill: "#dcfce7", stroke: "#16a34a", text: "#14532d" },
};

function isTopicKind(value: unknown): value is TopicKind {
  return value === "question" || value === "claim" || value === "constraint" || value === "decision";
}

function formatTime(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(safeSeconds / 60);
  return `${minutes}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

export default function TopicNode({ node, position, active, onSeek, children }: Props) {
  const kind = isTopicKind(node.kind) ? node.kind : "question";
  const colors = KIND_META[kind];
  const status = STATUS_META[node.status] ?? STATUS_META.open;

  const seek = () => onSeek?.(node.start_sec);
  const handleClick = (event: MouseEvent<SVGGElement>) => {
    event.stopPropagation();
    seek();
  };
  const handleKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (!onSeek || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    event.stopPropagation();
    seek();
  };

  return (
    <g
      className={`topic-node ${active ? "topic-node--active" : ""}`}
      data-topic-node-id={node.id}
      data-topic-active={active ? "true" : "false"}
      role="button"
      tabIndex={onSeek ? 0 : -1}
      aria-disabled={onSeek ? undefined : "true"}
      aria-label={`${node.label}（開始時刻 ${formatTime(node.start_sec)}）`}
      onClick={onSeek ? handleClick : undefined}
      onKeyDown={handleKeyDown}
    >
      <rect
        x={position.x}
        y={position.y}
        width={BOX_WIDTH}
        height={BOX_HEIGHT}
        rx={8}
        fill={colors.fill}
        stroke={active ? "#b7791f" : colors.stroke}
        strokeWidth={active ? 3 : 1.5}
      />
      <text
        x={position.x + 10}
        y={position.y + 17}
        className="topic-node__time"
        fill={colors.text}
      >
        {formatTime(node.start_sec)}
      </text>
      <text
        x={position.x + 51}
        y={position.y + 20}
        className="topic-node__label"
        fill={colors.text}
      >
        {node.label}
      </text>
      <text
        x={position.x + 10}
        y={position.y + 36}
        className="topic-node__status"
        fill={colors.text}
      >
        {/* 記号と文言を別 tspan にする。1つの text に結合すると要素の全文が
            「○ 未決」になり、ステータスだけを指せなくなる（E2Eが検出した）。 */}
        <tspan aria-hidden="true">{status.symbol}</tspan>
        <tspan dx={5}>{status.label}</tspan>
      </text>
      {active && (
        <g className="topic-node__active-badge" aria-label="いま話している論点">
          <rect
            // 箱の中に置くとラベル本文へ重なる。上端をまたがせる。
            x={position.x + BOX_WIDTH - 36}
            y={position.y - 9}
            width={32}
            height={17}
            rx={8}
            fill="#b7791f"
          />
          <text
            x={position.x + BOX_WIDTH - 20}
            y={position.y + 3}
            textAnchor="middle"
            fill="#ffffff"
          >
            いま
          </text>
        </g>
      )}
      {children}
    </g>
  );
}

export { BOX_HEIGHT, BOX_WIDTH };
