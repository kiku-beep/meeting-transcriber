import { useEffect, useRef, useState } from "react";
import { getHealth } from "../lib/apiHealth";

interface Props {
  onReady: () => void;
}

export default function BackendLoader({ onReady }: Props) {
  const [dots, setDots] = useState("");
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    const dotTimer = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "" : d + "."));
    }, 500);

    let cancelled = false;

    const checkHealth = async () => {
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

    checkHealth();
    const healthTimer = setInterval(checkHealth, 2000);

    return () => {
      cancelled = true;
      clearInterval(dotTimer);
      clearInterval(healthTimer);
    };
  }, []);

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-slate-900 text-slate-100">
      <div className="text-5xl mb-6">🎙️</div>
      <h1 className="text-xl font-semibold mb-2">Transcriber</h1>
      <p className="text-slate-400">バックエンド起動中{dots}</p>
      <div className="mt-6 w-48 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full bg-cyan-500 rounded-full animate-pulse w-2/3" />
      </div>
    </div>
  );
}
