import type { SessionInfo } from "../lib/types";

interface Props {
  status: SessionInfo | null;
  wsConnected: boolean;
  wsReconnecting?: boolean;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

const STATUS_BADGES: Record<string, { label: string; color: string }> = {
  idle: { label: "待機中", color: "bg-slate-600" },
  starting: { label: "開始中", color: "bg-yellow-600" },
  running: { label: "録音中", color: "bg-red-600 animate-pulse" },
  paused: { label: "一時停止", color: "bg-amber-600" },
  stopping: { label: "停止中", color: "bg-yellow-600" },
};

export default function StatusBar({ status, wsConnected, wsReconnecting }: Props) {
  const badge = STATUS_BADGES[status?.status ?? "idle"] ?? STATUS_BADGES.idle;

  const wsLabel = wsConnected
    ? "● WS接続中"
    : wsReconnecting
      ? "◐ WS再接続中..."
      : "○ WS切断";
  const wsColor = wsConnected
    ? "text-emerald-400"
    : wsReconnecting
      ? "text-amber-400 animate-pulse"
      : "text-red-400";

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-slate-800 border-t border-slate-700 text-xs shrink-0">
      <span className={`px-2 py-0.5 rounded-full text-white ${badge.color}`}>
        {badge.label}
      </span>
      {status && status.status !== "idle" && (
        <>
          <span className="text-slate-400 tabular-nums">
            {formatElapsed(status.elapsed_seconds)}
          </span>
          <span className="text-slate-400">
            {status.entry_count} エントリ / {status.segment_count} セグメント
          </span>
        </>
      )}
      <span className={`ml-auto ${wsColor}`}>
        {wsLabel}
      </span>
    </div>
  );
}
