import { useEffect, useRef, useState } from "react";
import { getHealth } from "../lib/apiHealth";
import { getAuthToken, getBaseUrl, getClientId, setAuthToken, setServerUrl } from "../lib/api";

interface Props {
  onReady: () => void;
}

export default function BackendLoader({ onReady }: Props) {
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
    let cancelled = false;

    const pollHealth = async () => {
      try {
        const res = await getHealth();
        if (res.status === "ok" && !cancelled) {
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
      clearInterval(healthTimer);
    };
  }, []);

  return (
    <div className="backend-loader" data-testid="backend-loader">
      <header className="backend-loader__topbar">
        <span>Transcriber</span>
      </header>

      <main className="backend-loader__main">
        <section className="backend-loader__content" aria-labelledby="backend-loader-title">
          <div className="backend-loader__status" role="status" aria-live="polite">
            <span className="backend-loader__indicator" aria-hidden="true" />
            <p className="backend-loader__eyebrow">STARTING</p>
            <h1 id="backend-loader-title">バックエンドに接続しています</h1>
            <p className="backend-loader__description">
              音声認識モデルと保存領域を準備しています。接続できると自動で文字起こし画面を開きます。
            </p>
          </div>

          {lastError && (
            <div className="backend-loader__error" role="alert">
              <strong>接続を確認できませんでした</strong>
              <span>{lastError}</span>
            </div>
          )}

          <details className="backend-loader__settings">
            <summary>接続設定</summary>
            <div className="backend-loader__settings-body">
              <label htmlFor="backend-url">
                <span>バックエンドURL</span>
              <input
                id="backend-url"
                value={serverUrlInput}
                onChange={(e) => setServerUrlInput(e.target.value)}
                placeholder="http://workstation0.tailnet.ts.net:8000"
              />
            </label>

              <label htmlFor="backend-token">
                <span>認証トークン（任意）</span>
              <input
                id="backend-token"
                type="password"
                value={authTokenInput}
                onChange={(e) => setAuthTokenInput(e.target.value)}
              />
            </label>

              <div className="backend-loader__client-id">
                Client ID: <span>{getClientId()}</span>
            </div>

              <div className="backend-loader__actions">
            <button
              onClick={handleConnect}
              disabled={checking}
                  className="backend-loader__button backend-loader__button--primary"
            >
              {checking ? "確認中..." : "接続"}
            </button>
            <button
              onClick={onReady}
                  className="backend-loader__button backend-loader__button--secondary"
            >
                  接続せずに開く
            </button>
          </div>
            </div>
          </details>
        </section>
      </main>
    </div>
  );
}
