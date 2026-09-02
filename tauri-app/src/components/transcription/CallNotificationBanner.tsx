import { useEffect, useState, useCallback, useRef } from "react";
import { getPendingCalls, dismissCall, type DetectedCall } from "../../lib/apiCallDetection";
import { getMeetingConfig } from "../../lib/apiConfig";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

interface Props {
  /** Whether a recording session is currently active */
  isRunning: boolean;
  /** Called when user wants to start recording with the detected call's suggested name */
  onStartWithName: (sessionName: string) => void;
}

export default function CallNotificationBanner({ isRunning, onStartWithName }: Props) {
  const [calls, setCalls] = useState<DetectedCall[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const notifiedRef = useRef<Set<string>>(new Set());

  // Poll for pending call notifications every 2 seconds
  useEffect(() => {
    const poll = async () => {
      try {
        const { calls: pending } = await getPendingCalls();
        if (pending.length > 0) {
          setCalls((prev) => {
            // Deduplicate by window_title
            const existing = new Set(prev.map((c) => c.window_title));
            const newCalls = pending.filter((c) => !existing.has(c.window_title));
            return newCalls.length > 0 ? [...prev, ...newCalls] : prev;
          });

          // Send OS notification for truly new calls (if enabled)
          for (const call of pending) {
            if (!notifiedRef.current.has(call.window_title)) {
              notifiedRef.current.add(call.window_title);
              getMeetingConfig()
                .then((cfg) => {
                  if (cfg.call_notification_enabled) {
                    sendOsNotification(call);
                  }
                })
                .catch(() => {/* API失敗時は通知しない */});
            }
          }
        }
      } catch {
        // Backend not ready or network error — ignore
      }
    };

    pollRef.current = setInterval(poll, 2000);
    // Initial poll immediately
    poll();

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Auto-dismiss all when recording starts
  useEffect(() => {
    if (isRunning) {
      setCalls([]);
    }
  }, [isRunning]);

  const handleStart = useCallback(
    (call: DetectedCall) => {
      onStartWithName(call.session_name_suggestion);
      setCalls((prev) => prev.filter((c) => c.window_title !== call.window_title));
    },
    [onStartWithName],
  );

  const handleDismiss = useCallback(async (call: DetectedCall) => {
    setCalls((prev) => prev.filter((c) => c.window_title !== call.window_title));
    try {
      await dismissCall(call.window_title);
    } catch {
      // ignore
    }
  }, []);

  if (calls.length === 0 || isRunning) return null;

  return (
    <div className="call-notification-stack">
      {calls.map((call) => (
        <div
          key={call.window_title}
          className="call-notification"
        >
          {/* Icon */}
          <div className="call-notification__icon">
            {call.call_type === "google_meet" ? (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            )}
          </div>

          {/* Text */}
          <div className="call-notification__content">
            <div className="call-notification__title">
              {call.display_name} を検出しました
            </div>
            <div className="call-notification__subtitle">
              {call.session_name_suggestion}
            </div>
          </div>

          {/* Actions */}
          <button
            onClick={() => handleStart(call)}
            className="call-notification__start"
          >
            録音開始
          </button>
          <button
            onClick={() => handleDismiss(call)}
            className="call-notification__dismiss"
          >
            閉じる
          </button>
        </div>
      ))}
    </div>
  );
}

async function sendOsNotification(call: DetectedCall) {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === "granted";
    }
    if (granted) {
      sendNotification({
        title: `${call.display_name} を検出しました`,
        body: call.session_name_suggestion,
      });
    }
  } catch {
    // Notification API unavailable — ignore
  }
}
