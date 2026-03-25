import { useState, useCallback, useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useWebSocket } from "../lib/useWebSocket";
import { startSession, stopSession, pauseSession, discardSession, nameCluster, registerNewSpeaker, setExpectedSpeakers, editSessionEntry, bulkUpdateSpeaker, confirmSuggestion, getSessionEntries, deleteSessionEntry } from "../lib/apiSession";
import { getSpeakers } from "../lib/apiSpeakers";
import { isRemoteMode, startAudioSidecar, stopAudioSidecar } from "../lib/audioSidecar";
import type { TranscriptEntry, SessionInfo, Speaker } from "../lib/types";
import RecordingControls from "./transcription/RecordingControls";
import CallNotificationBanner from "./transcription/CallNotificationBanner";
import SilenceWarningBanner from "./transcription/SilenceWarningBanner";
import MeetingParticipants from "./transcription/MeetingParticipants";
import TranscriptSearch from "./transcription/TranscriptSearch";
import TranscriptList from "./transcription/TranscriptList";
import StatusBar from "./StatusBar";

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
  const [searchQuery, setSearchQuery] = useState("");
  const [silenceWarning, setSilenceWarning] = useState(false);
  const lastEntryAt = useRef<number | null>(null);

  const isRunning = status?.status === "running" || status?.status === "paused";
  const isPaused = status?.status === "paused";

  const filteredEntries = searchQuery
    ? entries.filter(e =>
        e.text.toLowerCase().includes(searchQuery.toLowerCase()) ||
        e.speaker_name.toLowerCase().includes(searchQuery.toLowerCase()))
    : entries;

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
    invoke("set_recording_icon", { recording: status?.status === "running" });
  }, [status?.status]);

  // Fallback: if session is running but WS hasn't delivered entries after 3s,
  // fetch from REST API. Handles cases where WS entry delivery fails.
  const syncAttempted = useRef(false);
  useEffect(() => {
    if (!isRunning) {
      syncAttempted.current = false;
      return;
    }
    if (entries.length > 0 || syncAttempted.current) return;

    const timer = setTimeout(async () => {
      syncAttempted.current = true;
      try {
        const data = await getSessionEntries();
        setEntries((prev) => (prev.length === 0 ? data.entries : prev));
        if (data.entries.length > 0) {
          console.warn("[Transcriber] REST sync: loaded", data.entries.length, "entries (WS fallback)");
        }
      } catch {
        /* ignore */
      }
    }, 3000);

    return () => clearTimeout(timer);
  }, [isRunning, entries.length]);

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
    setLoading(true);
    setError("");
    setEntries([]);
    try {
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
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleStartWithName = useCallback((name: string) => {
    handleStart(name);
  }, [sessionName]);

  const handlePause = async () => {
    try {
      await pauseSession();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      if (isRemoteMode()) {
        // Stop audio sidecar (which sends "stop" to server)
        await stopAudioSidecar();
      }
      const info = await stopSession();
      onSessionStop(info.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDiscard = async () => {
    if (!confirm("録音を破棄しますか？保存されません。")) return;
    setLoading(true);
    try {
      await discardSession();
      setEntries([]);
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
    <div className="flex flex-col h-full relative">
      {/* Controls */}
      <div className="p-4 border-b border-slate-700 space-y-3 shrink-0">
        <RecordingControls
          isRunning={isRunning}
          isPaused={isPaused}
          loading={loading}
          sessionName={sessionName}
          micDevice={status?.mic_device ?? ""}
          loopbackDevice={status?.loopback_device ?? ""}
          onSessionNameChange={setSessionName}
          onStart={() => handleStart()}
          onPause={handlePause}
          onStop={handleStop}
        />

        <CallNotificationBanner isRunning={isRunning} onStartWithName={handleStartWithName} />

        <SilenceWarningBanner
          visible={silenceWarning}
          onStop={handleStop}
          onDismiss={() => { setSilenceWarning(false); lastEntryAt.current = Date.now(); }}
        />

        {error && (
          <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError("")} className="text-red-400 hover:text-red-300 ml-2 shrink-0">&#x2715;</button>
          </div>
        )}

        <MeetingParticipants
          visible={!isRunning}
          speakers={speakers}
          onSubmit={handleSetParticipants}
        />
      </div>

      {/* Search Bar */}
      {entries.length > 0 && (
        <TranscriptSearch value={searchQuery} onChange={setSearchQuery} />
      )}

      {/* Entries */}
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

      {/* Discard Button - bottom right, away from other controls */}
      {isRunning && (
        <button
          onClick={handleDiscard}
          disabled={loading}
          className="absolute bottom-12 right-4 px-4 py-1.5 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-500 rounded text-sm transition-colors opacity-70 hover:opacity-100"
        >
          破棄
        </button>
      )}

      {/* Status Bar */}
      <StatusBar status={status} wsConnected={connected} wsReconnecting={reconnecting} />
    </div>
  );
}
