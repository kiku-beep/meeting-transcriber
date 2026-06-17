import { useEffect, useRef, useState } from "react";
import { getHealth } from "../lib/apiHealth";
import { getAuthToken, getBaseUrl, getClientId, setAuthToken, setServerUrl } from "../lib/api";

interface Props {
  onReady: () => void;
}

export default function BackendLoader({ onReady }: Props) {
  const [dots, setDots] = useState("");
  const [serverUrlInput, setServerUrlInput] = useState(getBaseUrl());
  const [authTokenInput, setAuthTokenInput] = useState(getAuthToken());
  const [checking, setChecking] = useState(false);
  const [lastError, setLastError] = useState("");
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  const checkHealth = async () => {
    setChecking(true);
    setLastError("");
    try {
      const res = await getHealth();
      if (res.status === "ok") {
        onReadyRef.current();
        return true;
      }
      setLastError(`Unexpected health status: ${res.status}`);
    } catch (e) {
      setLastError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
    return false;
  };

  const handleConnect = async () => {
    setServerUrl(serverUrlInput);
    setAuthToken(authTokenInput);
    await checkHealth();
  };

  useEffect(() => {
    const dotTimer = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "" : d + "."));
    }, 500);

    let cancelled = false;

    const pollHealth = async () => {
      try {
        const res = await getHealth();
        if (res.status === "ok" && !cancelled) {
          clearInterval(dotTimer);
          onReadyRef.current();
          return true;
        }
      } catch {
        /* not ready yet */
      }
      return false;
    };

    pollHealth();
    const healthTimer = setInterval(pollHealth, 2000);

    return () => {
      cancelled = true;
      clearInterval(dotTimer);
      clearInterval(healthTimer);
    };
  }, []);

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <div className="m-auto w-full max-w-xl px-6">
        <div className="border border-slate-800 bg-slate-900 rounded-lg p-6 shadow-xl">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-10 h-10 rounded-full bg-cyan-500/15 text-cyan-300 flex items-center justify-center text-xl">
              🎙️
            </div>
            <div>
              <h1 className="text-lg font-semibold">Transcriber</h1>
              <p className="text-sm text-slate-400">リモートバックエンドへ接続中{dots}</p>
            </div>
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="block text-xs font-medium text-slate-400 mb-1">バックエンドURL</span>
              <input
                value={serverUrlInput}
                onChange={(e) => setServerUrlInput(e.target.value)}
                placeholder="http://workstation0.tailnet.ts.net:8000"
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm focus:outline-none focus:border-cyan-500"
              />
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-slate-400 mb-1">認証トークン（任意）</span>
              <input
                type="password"
                value={authTokenInput}
                onChange={(e) => setAuthTokenInput(e.target.value)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm focus:outline-none focus:border-cyan-500"
              />
            </label>

            <div className="text-xs text-slate-500">
              Client ID: <span className="font-mono text-slate-400">{getClientId()}</span>
            </div>
          </div>

          {lastError && (
            <div className="mt-4 p-3 bg-red-950/70 border border-red-800 rounded text-red-200 text-xs">
              {lastError}
            </div>
          )}

          <div className="mt-5 flex items-center gap-3">
            <button
              onClick={handleConnect}
              disabled={checking}
              className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 rounded text-sm font-medium"
            >
              {checking ? "確認中..." : "接続"}
            </button>
            <button
              onClick={onReady}
              className="text-sm text-slate-500 hover:text-slate-300 underline"
            >
              アプリを開く
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
