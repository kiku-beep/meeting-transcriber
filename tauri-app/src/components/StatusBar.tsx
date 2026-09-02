import type { SessionInfo } from "../lib/types";

interface Props {
  status: SessionInfo | null;
  wsConnected: boolean;
  wsReconnecting?: boolean;
}

export default function StatusBar({ status, wsConnected, wsReconnecting }: Props) {
  const wsLabel = wsConnected
    ? "● WS接続中"
    : wsReconnecting
      ? "◐ WS再接続中..."
      : "○ WS切断";
  const wsState = wsConnected
    ? "status-connected"
    : wsReconnecting
      ? "status-reconnecting"
      : "status-disconnected";

  return (
    <div className="app-statusbar">
      <span data-testid="statusbar-connection" className={`app-statusbar__connection ${wsState}`}>
        {wsLabel}
      </span>
      <span className="app-statusbar__count">
        文字起こし&nbsp; | &nbsp;{status?.entry_count ?? 0}件
      </span>
    </div>
  );
}
