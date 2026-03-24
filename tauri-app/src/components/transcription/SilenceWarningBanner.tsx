import { useEffect, useRef } from "react";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

interface Props {
  visible: boolean;
  onStop: () => void;
  onDismiss: () => void;
}

export default function SilenceWarningBanner({ visible, onStop, onDismiss }: Props) {
  const notifiedRef = useRef(false);

  useEffect(() => {
    if (visible && !notifiedRef.current) {
      notifiedRef.current = true;
      sendOsNotification();
    }
    if (!visible) {
      notifiedRef.current = false;
    }
  }, [visible]);

  if (!visible) return null;

  return (
    <div className="flex items-center gap-3 p-3 bg-amber-900/40 border border-amber-700/60 rounded-lg animate-in fade-in">
      {/* Icon */}
      <div className="shrink-0 text-amber-400">
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-amber-200">
          3分間音声が検出されていません
        </div>
        <div className="text-xs text-slate-400">
          録音を停止しますか？
        </div>
      </div>

      {/* Actions */}
      <button
        onClick={onStop}
        className="shrink-0 px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded text-xs font-medium transition-colors"
      >
        録音停止
      </button>
      <button
        onClick={onDismiss}
        className="shrink-0 px-2 py-1.5 text-slate-400 hover:text-slate-200 text-xs transition-colors"
      >
        閉じる
      </button>
    </div>
  );
}

async function sendOsNotification() {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === "granted";
    }
    if (granted) {
      sendNotification({
        title: "3分間音声が検出されていません",
        body: "録音を停止しますか？",
      });
    }
  } catch {
    // Notification API unavailable — ignore
  }
}
