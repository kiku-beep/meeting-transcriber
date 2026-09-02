import { useState, useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useWebSocket } from "../lib/useWebSocket";
import { isTauriRuntime } from "../lib/api";
import { startSession, stopSession, pauseSession, discardSession, nameCluster, registerNewSpeaker, setExpectedSpeakers, editSessionEntry, bulkUpdateSpeaker, confirmSuggestion, getSessionEntries, deleteSessionEntry, getSessionStatus } from "../lib/apiSession";
import { getSpeakers } from "../lib/apiSpeakers";
import { renameSession } from "../lib/apiTranscripts";
import { isBackendConnectionError, waitForBackendHealth } from "../lib/apiHealth";
import { isRemoteMode, startAudioSidecar, stopAudioSidecar } from "../lib/audioSidecar";
import type { TranscriptEntry, SessionInfo, Speaker } from "../lib/types";
import RecordingControls from "./transcription/RecordingControls";
import CallNotificationBanner from "./transcription/CallNotificationBanner";
import SilenceWarningBanner from "./transcription/SilenceWarningBanner";
import MeetingParticipants from "./transcription/MeetingParticipants";
import TranscriptList from "./transcription/TranscriptList";
import StatusBar from "./StatusBar";
import LiveAiPanel from "./transcription/LiveAiPanel";

interface Props {
  onSessionStop: (sessionId: string) => void;
}

export default function Transcription({ onSessionStop }: Props) {
  const [status, setStatus] = useState<SessionInfo | null>(null);
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [sessionName, setSessionName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [silenceWarning, setSilenceWarning] = useState(false);
  const [aiPanelOpen, setAiPanelOpen] = useState(true);
  const lastEntryAt = useRef<number | null>(null);

  const isRunning = status?.status === "running" || status?.status === "paused";
  const isPaused = status?.status === "paused";

  const searchQuery = "";
  const filteredEntries = entries;

  const handleEntry = useCallback((entry: TranscriptEntry) => {
    setEntries((prev) => [...prev, entry]);
    lastEntryAt.current = Date.now();
  }, []);

  const handleStatus = useCallback((s: SessionInfo) => {
    setStatus(s);
  }, []);

  const handleClear = useCallback(() => {
    setEntries([]);
  }, []);

  const handleRefresh = useCallback(async () => {
    try {
      const data = await getSessionEntries();
      setEntries(data.entries);
    } catch {
      /* ignore */
    }
  }, []);

  const syncSessionStatus = useCallback(async () => {
    try {
      const latest = await getSessionStatus();
      setStatus(latest);
      return latest;
    } catch {
      return null;
    }
  }, []);

  const handleUpdate = useCallback((updates: Array<{ id: string; text: string; refined: boolean }>) => {
    setEntries(prev => prev.map(entry => {
      const update = updates.find(u => u.id === entry.id);
      if (update) {
        return { ...entry, text: update.text, refined: update.refined };
      }
      return entry;
    }));
  }, []);

  const { connected, reconnecting } = useWebSocket({
    onEntry: handleEntry,
    onStatus: handleStatus,
    onClear: handleClear,
    onRefresh: handleRefresh,
    onUpdate: handleUpdate,
    enabled: true,
  });

  // Load speakers
  useEffect(() => {
    getSpeakers()
      .then((data) => setSpeakers(data.speakers))
      .catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;

    const sync = async () => {
      try {
        const latest = await getSessionStatus();
        if (!cancelled) setStatus(latest);
      } catch {
        /* status sync is best-effort; WebSocket remains primary */
      }
    };

    sync();
    const timer = setInterval(sync, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // Refresh speakers when session starts (might register new speakers during session)
  useEffect(() => {
    if (isRunning) {
      getSpeakers()
        .then((data) => setSpeakers(data.speakers))
        .catch(() => {});
    }
  }, [isRunning]);

  // Update taskbar icon when recording starts/stops
  useEffect(() => {
    if (!isTauriRuntime()) return;
    invoke("set_recording_icon", { recording: status?.status === "running" });
  }, [status?.status]);

  // Fallback: if WebSocket entry delivery is missed, keep REST-syncing while
  // the backend reports more entries than the UI currently has.
  useEffect(() => {
    if (!isRunning) return;

    let cancelled = false;
    let inFlight = false;

    const syncMissingEntries = async () => {
      const backendEntryCount = status?.entry_count ?? 0;
      const shouldSync = backendEntryCount > entries.length || entries.length === 0;
      if (!shouldSync || inFlight) return;

      inFlight = true;
      try {
        const data = await getSessionEntries();
        if (cancelled) return;
        setEntries((prev) => (data.entries.length > prev.length ? data.entries : prev));
        if (data.entries.length > entries.length) {
          lastEntryAt.current = Date.now();
          setSilenceWarning(false);
          console.warn("[Transcriber] REST sync: loaded", data.entries.length, "entries");
        }
      } catch {
        /* ignore */
      } finally {
        inFlight = false;
      }
    };

    syncMissingEntries();
    const timer = setInterval(syncMissingEntries, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isRunning, status?.entry_count, entries.length]);

  // Silence detection: show warning if no entry received for 3 minutes while running
  const SILENCE_THRESHOLD_MS = 3 * 60 * 1000;
  useEffect(() => {
    if (!isRunning) {
      setSilenceWarning(false);
      lastEntryAt.current = null;
      return;
    }
    // Initialize baseline when recording starts
    if (lastEntryAt.current === null) {
      lastEntryAt.current = Date.now();
    }
    const interval = setInterval(() => {
      if (lastEntryAt.current !== null && Date.now() - lastEntryAt.current > SILENCE_THRESHOLD_MS) {
        setSilenceWarning(true);
      }
    }, 30_000);
    return () => clearInterval(interval);
  }, [isRunning]);

  const handleStart = async (overrideName?: string) => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      await waitForBackendHealth();
      const latest = await syncSessionStatus();
      if (latest && latest.status !== "idle") {
        if (latest.status === "running" || latest.status === "paused") {
          await handleRefresh();
          return;
        }
        setError("録音状態を同期しています。数秒後にもう一度開始してください。");
        return;
      }

      setEntries([]);
      const name = overrideName || sessionName || undefined;
      if (isRemoteMode()) {
        // Remote mode: start audio sidecar (which sends "start" to server)
        await startAudioSidecar({ sessionName: name });
      } else {
        // Standalone mode: tell backend to start with local audio
        await startSession({ session_name: name });
      }
      if (overrideName) setSessionName(overrideName);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (message.includes("Cannot start session") || message.includes("409")) {
        const latest = await syncSessionStatus();
        if (latest && latest.status !== "idle") {
          await handleRefresh();
          return;
        }
      }
      setError(
        isBackendConnectionError(e)
          ? "バックエンドを起動中です。数秒後にもう一度開始してください。"
          : message
      );
    } finally {
      setLoading(false);
    }
  };

  const handleStartWithName = useCallback((name: string) => {
    handleStart(name);
  }, [sessionName]);

  const handlePause = async () => {
    if (isRemoteMode()) {
      setError("リモート録音の一時停止は未対応です。停止してから再開してください。");
      return;
    }
    try {
      await pauseSession();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      let stoppedSessionId: string;
      if (isRemoteMode()) {
        const remoteSessionId = status?.session_id;
        await stopAudioSidecar();
        if (remoteSessionId) {
          stoppedSessionId = remoteSessionId;
        } else {
          const info = await stopSession();
          stoppedSessionId = info.session_id;
        }
      } else {
        const info = await stopSession();
        stoppedSessionId = info.session_id;
      }

      const trimmedSessionName = sessionName.trim();
      if (trimmedSessionName) {
        await renameSession(stoppedSessionId, trimmedSessionName);
      }
      onSessionStop(stoppedSessionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDiscard = async () => {
    if (!confirm("この録音を破棄しますか？文字起こしと録音は保存されません。")) return;
    setLoading(true);
    setError("");
    try {
      await discardSession();
      setEntries([]);
      setSessionName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleSetParticipants = async (names: string[], speakerIds: string[]) => {
    try {
      await setExpectedSpeakers({ names, speaker_ids: speakerIds.length > 0 ? speakerIds : undefined });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleNameCluster = async (clusterId: string, name: string, isGuest: boolean = false) => {
    try {
      const result = await nameCluster({ cluster_id: clusterId, name, is_guest: isGuest || undefined });
      setEntries(result.entries);
      if (!isGuest) {
        getSpeakers()
          .then((data) => setSpeakers(data.speakers))
          .catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRegisterNewSpeaker = async (entryId: string, name: string, isGuest: boolean) => {
    try {
      const result = await registerNewSpeaker(entryId, name, isGuest);
      setEntries(result.entries);
      if (!isGuest) {
        getSpeakers()
          .then((data) => setSpeakers(data.speakers))
          .catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEditText = async (entryId: string, newText: string) => {
    try {
      const result = await editSessionEntry(entryId, { text: newText });
      setEntries((prev) =>
        prev.map((e) => (e.id === entryId ? { ...e, text: result.entry.text } : e)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDeleteEntry = async (entryId: string) => {
    try {
      await deleteSessionEntry(entryId);
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEditSpeaker = async (entryId: string, speakerName: string, speakerId: string) => {
    try {
      const result = await editSessionEntry(entryId, {
        speaker_name: speakerName,
        speaker_id: speakerId,
      });
      setEntries((prev) =>
        prev.map((e) =>
          e.id === entryId
            ? { ...e, speaker_name: result.entry.speaker_name, speaker_id: result.entry.speaker_id }
            : e,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEditSpeakerBulk = async (entryId: string, speakerName: string, speakerId: string) => {
    try {
      const entry = entries.find((e) => e.id === entryId);
      if (!entry) return;

      const oldSpeakerId = entry.speaker_id;

      const result = await bulkUpdateSpeaker(oldSpeakerId, speakerId, speakerName);
      setEntries(result.entries);

      getSpeakers()
        .then((data) => setSpeakers(data.speakers))
        .catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleConfirmSuggestion = async (clusterId: string, speakerId: string, speakerName: string) => {
    try {
      const result = await confirmSuggestion(clusterId, speakerId, speakerName);
      setEntries(result.entries);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="transcription-workspace flex flex-col h-full relative workspace-screen">
      {/* Controls */}
      <div className="workspace-toolbar shrink-0">
        <RecordingControls
          isRunning={isRunning}
          isPaused={isPaused}
          loading={loading}
          sessionName={sessionName}
          micDevice={status?.mic_device ?? ""}
          loopbackDevice={status?.loopback_device ?? ""}
          elapsedSeconds={status?.elapsed_seconds ?? 0}
          aiOpen={aiPanelOpen}
          onSessionNameChange={setSessionName}
          onStart={() => handleStart()}
          onPause={handlePause}
          onStop={handleStop}
          onDiscard={handleDiscard}
          onAiToggle={() => setAiPanelOpen((open) => !open)}
        />

        <CallNotificationBanner isRunning={isRunning} onStartWithName={handleStartWithName} />

        <SilenceWarningBanner
          visible={silenceWarning}
          onStop={handleStop}
          onDismiss={() => { setSilenceWarning(false); lastEntryAt.current = Date.now(); }}
        />

        {error && (
          <div className="inline-alert inline-alert--error flex items-center justify-between" role="alert">
            <span>{error}</span>
            <button onClick={() => setError("")} className="inline-alert__dismiss ml-2 shrink-0">&#x2715;</button>
          </div>
        )}

        <MeetingParticipants
          visible={!isRunning}
          speakers={speakers}
          onSubmit={handleSetParticipants}
        />
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <section className="transcript-surface flex flex-col flex-1 min-w-0" aria-label="文字起こし">
          <header className="transcript-surface__header">
            <span>リアルタイム文字起こし</span>
            <span className="subscription-badge">Claudeサブスク枠</span>
          </header>
          <TranscriptList
            entries={entries}
            filteredEntries={filteredEntries}
            speakers={speakers}
            searchQuery={searchQuery}
            isRunning={isRunning}
            onEditText={handleEditText}
            onEditSpeaker={handleEditSpeaker}
            onEditSpeakerBulk={handleEditSpeakerBulk}
            onNameCluster={isRunning ? handleNameCluster : undefined}
            onRegisterNewSpeaker={isRunning ? handleRegisterNewSpeaker : undefined}
            onConfirmSuggestion={isRunning ? handleConfirmSuggestion : undefined}
            onDeleteEntry={handleDeleteEntry}
          />
        </section>
        <LiveAiPanel
          open={aiPanelOpen}
          sessionId={status?.session_id || null}
          hasEntries={entries.length > 0}
          onClose={() => setAiPanelOpen(false)}
        />
      </div>
      {/* Status Bar */}
      <StatusBar status={status} wsConnected={connected} wsReconnecting={reconnecting} />
    </div>
  );
}
