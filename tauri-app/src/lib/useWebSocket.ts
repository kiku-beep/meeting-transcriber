import { useEffect, useRef, useState } from "react";
import { getWsUrl, getClientId, getAuthToken } from "./api";
import type { TranscriptEntry, SessionInfo, WsMessage } from "./types";

interface UseWebSocketOptions {
  onEntry?: (entry: TranscriptEntry) => void;
  onStatus?: (status: SessionInfo) => void;
  onClear?: () => void;
  onRefresh?: () => void;
  onUpdate?: (updates: Array<{ id: string; text: string; refined: boolean }>) => void;
  enabled?: boolean;
}

export function useWebSocket({ onEntry, onStatus, onClear, onRefresh, onUpdate, enabled = true }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const onEntryRef = useRef(onEntry);
  const onStatusRef = useRef(onStatus);
  const onClearRef = useRef(onClear);
  const onRefreshRef = useRef(onRefresh);
  const onUpdateRef = useRef(onUpdate);

  onEntryRef.current = onEntry;
  onStatusRef.current = onStatus;
  onClearRef.current = onClear;
  onRefreshRef.current = onRefresh;
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!enabled) return;

    let reconnectTimer: ReturnType<typeof setTimeout>;
    let closed = false;

    let pingTimer: ReturnType<typeof setInterval>;

    function connect() {
      const wsUrl = getWsUrl();
      const clientId = getClientId();
      const token = getAuthToken();
      const params = new URLSearchParams({ client_id: clientId });
      if (token) params.set("token", token);
      const ws = new WebSocket(`${wsUrl}/ws/transcript?${params}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setReconnecting(false);
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };
      ws.onclose = () => {
        clearInterval(pingTimer);
        setConnected(false);
        if (!closed) {
          setReconnecting(true);
          reconnectTimer = setTimeout(connect, 2000);
        }
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        try {
          const msg: WsMessage = JSON.parse(event.data);
          if (msg.type === "entry") onEntryRef.current?.(msg.data);
          else if (msg.type === "status") onStatusRef.current?.(msg.data);
          else if (msg.type === "clear") onClearRef.current?.();
          else if (msg.type === "refresh") onRefreshRef.current?.();
          else if (msg.type === "update") onUpdateRef.current?.(msg.data);
        } catch {
          /* ignore parse errors */
        }
      };
    }

    connect();

    return () => {
      closed = true;
      clearTimeout(reconnectTimer);
      clearInterval(pingTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [enabled]);

  return { connected, reconnecting };
}
