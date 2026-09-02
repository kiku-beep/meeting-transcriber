import { useEffect, useRef, useState, useCallback } from "react";
import { getSessions, getTranscript, exportTranscript, deleteSession, editSavedEntry, renameSession, deleteSavedEntry } from "../lib/apiTranscripts";
import type { TranscriptExportFormat } from "../lib/apiTranscripts";
import { generateSummary, getSummary } from "../lib/apiSummary";
import { getSpeakers } from "../lib/apiSpeakers";
import { fetchAudioBlobUrl, getAudioInfo, deleteAudio, compressAudio, toggleBookmark } from "../lib/apiPlayback";
import { listScreenshots } from "../lib/apiScreenshots";
import { fetchSavedTopics } from "../lib/apiTopics";
import { useAudioPlayer } from "../lib/useAudioPlayer";
import { isTauriRuntime } from "../lib/api";
import { isBackendConnectionError, waitForBackendHealth } from "../lib/apiHealth";
import type { TranscriptEntry, TranscriptSession, SummaryResult, Speaker, TopicTree as TopicTreeData } from "../lib/types";
import HistoryHeader from "./history/HistoryHeader";
import SessionList from "./history/SessionList";
import TranscriptView from "./history/TranscriptView";
import SummaryView from "./history/SummaryView";
import ScreenshotPanel from "./history/ScreenshotPanel";
import PlayerBar from "./playback/PlayerBar";
import TopicTreeView from "./topics/TopicTreeView";

interface Props {
  autoSummarizeSessionId: string | null;
  onAutoSummarizeComplete: () => void;
}

const SESSION_LOAD_RETRY_COUNT = 5;
const SESSION_LOAD_RETRY_DELAY_MS = 1000;
const EMPTY_SESSION_AUTO_RETRY_DELAY_MS = 2000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function History({ autoSummarizeSessionId, onAutoSummarizeComplete }: Props) {
  const [sessions, setSessions] = useState<TranscriptSession[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [subTab, setSubTab] = useState<"transcript" | "summary" | "topics">("transcript");
  const [savedTopics, setSavedTopics] = useState<TopicTreeData | null>(null);
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [summary, setSummary] = useState("");
  const [summaryResult, setSummaryResult] = useState<SummaryResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [hasAudio, setHasAudio] = useState(false);
  const [hasScreenshots, setHasScreenshots] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [activeTranscriptTime, setActiveTranscriptTime] = useState<number | null>(null);
  const transcriptScrollRef = useRef<HTMLDivElement>(null);

  const [playerState, playerActions] = useAudioPlayer(entries);

  const updateActiveTranscriptTimeFromScroll = useCallback(() => {
    const container = transcriptScrollRef.current;
    if (!container || subTab !== "transcript") return;

    const containerRect = container.getBoundingClientRect();
    const anchorY = containerRect.top + Math.min(containerRect.height * 0.35, 160);
    const entryElements = Array.from(
      container.querySelectorAll<HTMLElement>("[data-transcript-entry-start]"),
    );

    let previous: { time: number; centerY: number } | null = null;
    let next: { time: number; centerY: number } | null = null;

    for (const element of entryElements) {
      const time = Number(element.dataset.transcriptEntryStart);
      if (!Number.isFinite(time)) continue;

      const rect = element.getBoundingClientRect();
      const centerY = rect.top + rect.height / 2;

      if (centerY <= anchorY) {
        if (!previous || centerY > previous.centerY) {
          previous = { time, centerY };
        }
      }
      if (centerY >= anchorY) {
        if (!next || centerY < next.centerY) {
          next = { time, centerY };
        }
      }
    }

    let activeTime: number | null = null;
    if (previous && next) {
      const span = next.centerY - previous.centerY;
      const ratio = span === 0 ? 0 : (anchorY - previous.centerY) / span;
      activeTime = previous.time + (next.time - previous.time) * Math.max(0, Math.min(1, ratio));
    } else {
      activeTime = previous?.time ?? next?.time ?? null;
    }

    if (activeTime !== null) {
      setActiveTranscriptTime((prev) => (
        prev !== null && Math.abs(prev - activeTime) < 0.05 ? prev : activeTime
      ));
    }
  }, [subTab]);

  const refreshSessions = useCallback(async () => {
    setLoadingSessions(true);
    let lastError: unknown = null;
    try {
      for (let attempt = 0; attempt < SESSION_LOAD_RETRY_COUNT; attempt += 1) {
        try {
          if (attempt > 0) {
            await waitForBackendHealth({ timeoutMs: 5000, intervalMs: 500 });
          }
          const data = await getSessions();
          setSessions(data.sessions);
          setError("");
          return;
        } catch (e) {
          lastError = e;
          if (!isBackendConnectionError(e) || attempt === SESSION_LOAD_RETRY_COUNT - 1) {
            throw e;
          }
          await sleep(SESSION_LOAD_RETRY_DELAY_MS);
        }
      }
    } catch {
      setError(lastError instanceof Error ? lastError.message : String(lastError));
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    refreshSessions();
    getSpeakers()
      .then((data) => setSpeakers(data.speakers))
      .catch(() => {});
  }, [refreshSessions]);

  useEffect(() => {
    if (selectedId || loadingSessions || sessions.length > 0 || !error) return;
    if (!isBackendConnectionError(error)) return;

    const timer = window.setTimeout(() => {
      void refreshSessions();
    }, EMPTY_SESSION_AUTO_RETRY_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [error, loadingSessions, refreshSessions, selectedId, sessions.length]);

  // Auto-summarize + compress on session stop
  useEffect(() => {
    if (!autoSummarizeSessionId) return;
    setSelectedId(autoSummarizeSessionId);
    setSubTab("summary");
    refreshSessions();

    const doSummarize = async () => {
      setGenerating(true);
      try {
        const result = await generateSummary(autoSummarizeSessionId);
        setSummary(result.summary);
        setSummaryResult(result);
        await refreshSessions();

        // Compress audio after summary
        try {
          await compressAudio(autoSummarizeSessionId);
        } catch {
          // Non-critical: ffmpeg not found or already compressed
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setGenerating(false);
        onAutoSummarizeComplete();
      }
    };
    doSummarize();
  }, [autoSummarizeSessionId, onAutoSummarizeComplete, refreshSessions]);

  // Load selected session
  useEffect(() => {
    if (!selectedId) {
      setEntries([]);
      setSummary("");
      setSummaryResult(null);
      setSearchQuery("");
      setHasAudio(false);
      setHasScreenshots(false);
      setSavedTopics(null);
      setActiveTranscriptTime(null);
      playerActions.destroy();
      return;
    }
    setSearchQuery("");
    setActiveTranscriptTime(null);
    let cancelled = false;

    const load = async () => {
      const [transcriptResult, summaryResult, audioInfoResult, screenshotsResult, topicsResult] =
        await Promise.allSettled([
          getTranscript(selectedId),
          getSummary(selectedId),
          getAudioInfo(selectedId),
          listScreenshots(selectedId),
          fetchSavedTopics(selectedId),
        ]);
      if (cancelled) return;

      // 論点ツリーは機能ONで録った会議にしか無い。無ければタブも出さない。
      setSavedTopics(
        topicsResult.status === "fulfilled" ? topicsResult.value : null,
      );

      if (transcriptResult.status === "fulfilled") {
        setEntries(transcriptResult.value.entries);
      }
      if (summaryResult.status === "fulfilled") {
        setSummary(summaryResult.value.summary);
      } else {
        setSummary("");
      }
      if (audioInfoResult.status === "fulfilled" && audioInfoResult.value.has_audio) {
        setHasAudio(true);
        try {
          // Auto-compress WAV → OGG if needed (329MB WAV → ~26MB OGG)
          const audioInfo = audioInfoResult.value;
          if (audioInfo.format === "wav") {
            console.log("[History] WAV detected, compressing to OGG...");
            playerActions.setLoading(true);
            const compResult = await compressAudio(selectedId);
            if (cancelled) return;
            if (compResult.status === "ffmpeg_not_found") {
              console.warn("[History] ffmpeg not found, loading WAV directly (may be slow)");
            }
          }
          if (cancelled) return;
          // Use tauriFetch + Blob URL (bypasses WebView2 network stack)
          const blobUrl = await fetchAudioBlobUrl(selectedId);
          if (cancelled) {
            URL.revokeObjectURL(blobUrl);
            return;
          }
          playerActions.setSource(blobUrl);
        } catch (err) {
          if (!cancelled) {
            console.error("[History] Failed to load audio:", err);
            setHasAudio(false);
            playerActions.setLoading(false);
          }
        }
      } else {
        setHasAudio(false);
        playerActions.destroy();
      }
      if (cancelled) return;
      if (screenshotsResult.status === "fulfilled" && screenshotsResult.value.screenshots.length > 0) {
        setHasScreenshots(true);
      } else {
        setHasScreenshots(false);
      }
    };
    load();

    return () => { cancelled = true; };
  }, [selectedId]);

  // 論点ツリーが無い会議へ切り替えたとき、空のタブに取り残されないよう戻す。
  useEffect(() => {
    if (subTab === "topics" && !savedTopics) setSubTab("transcript");
  }, [savedTopics, subTab]);

  useEffect(() => {
    if (subTab !== "transcript") return;
    const frame = requestAnimationFrame(updateActiveTranscriptTimeFromScroll);
    return () => cancelAnimationFrame(frame);
  }, [entries, searchQuery, subTab, updateActiveTranscriptTimeFromScroll]);

  const handleGenerate = async () => {
    if (!selectedId) return;
    setGenerating(true);
    setError("");
    try {
      const result = await generateSummary(selectedId, true);
      setSummary(result.summary);
      setSummaryResult(result);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async (format: TranscriptExportFormat) => {
    if (!selectedId) return;
    try {
      const content = await exportTranscript(selectedId, format);
      const defaultFilename = format === "action-md" ? `${selectedId}-action.md` : `${selectedId}.${format}`;
      const extension = format === "action-md" ? "md" : format;
      if (format === "action-md") {
        navigator.clipboard?.writeText(content).catch(() => {});
      }
      // Try Tauri native save dialog first
      if (isTauriRuntime()) {
        try {
          const { save } = await import("@tauri-apps/plugin-dialog");
          const { writeTextFile } = await import("@tauri-apps/plugin-fs");
          const path = await save({
            defaultPath: defaultFilename,
            filters: [{ name: extension.toUpperCase(), extensions: [extension] }],
          });
          if (path) {
            await writeTextFile(path, content);
            return;
          }
          return; // user cancelled
        } catch {
          /* Tauri plugins not available, fall through to browser method */
        }
      }
      // Browser fallback
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = defaultFilename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async () => {
    if (!selectedId || !confirm("このセッションを削除しますか？")) return;
    try {
      playerActions.destroy();
      await deleteSession(selectedId);
      setSelectedId("");
      setEntries([]);
      setSummary("");
      setHasAudio(false);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEditText = async (entryId: string, newText: string) => {
    if (!selectedId) return;
    try {
      const result = await editSavedEntry(selectedId, entryId, { text: newText });
      setEntries((prev) =>
        prev.map((e) => (e.id === entryId ? { ...e, text: result.entry.text } : e)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEditSpeaker = async (entryId: string, speakerName: string, speakerId: string) => {
    if (!selectedId) return;
    try {
      const result = await editSavedEntry(selectedId, entryId, {
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

  const handlePlayFromEntry = useCallback((timestampStart: number) => {
    playerActions.play(timestampStart);
  }, [playerActions]);

  const handleToggleBookmark = useCallback(async (entryId: string) => {
    if (!selectedId) return;
    try {
      const result = await toggleBookmark(selectedId, entryId);
      setEntries((prev) =>
        prev.map((e) => (e.id === entryId ? { ...e, bookmarked: result.bookmarked } : e)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedId]);

  const handleDeleteEntry = useCallback(async (entryId: string) => {
    if (!selectedId) return;
    try {
      await deleteSavedEntry(selectedId, entryId);
      setEntries((prev) => prev.filter((e) => e.id !== entryId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedId]);

  const handleDeleteAudio = useCallback(async () => {
    if (!selectedId) return;
    try {
      playerActions.destroy();
      await deleteAudio(selectedId);
      setHasAudio(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedId, playerActions]);

  const handleDeleteFromList = useCallback(async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshSessions]);

  const handleDeleteSessions = useCallback(async (ids: string[]) => {
    try {
      await Promise.all(ids.map((id) => deleteSession(id)));
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshSessions]);

  const handleRename = useCallback(async (sessionId: string, newName: string) => {
    try {
      await renameSession(sessionId, newName);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshSessions]);

  const selectedSession = sessions.find((s) => s.session_id === selectedId);
  const sessionName = selectedSession?.session_name || selectedId;

  return (
    <div className="workspace-screen flex flex-col h-full">
      {!selectedId ? (
        <>
          {error && (
            <div className="inline-alert inline-alert--error mx-4 mt-3 flex items-center gap-3" role="alert">
              <span className="flex-1">{error}</span>
              <button
                onClick={() => void refreshSessions()}
                className="inline-alert__action px-2 py-1"
              >
                再読み込み
              </button>
              <button onClick={() => setError("")} className="inline-alert__dismiss">
                &#x2715;
              </button>
            </div>
          )}
          <SessionList
            sessions={sessions}
            loading={loadingSessions}
            onSelectSession={setSelectedId}
            onRenameSession={handleRename}
            onDeleteSession={handleDeleteFromList}
            onDeleteSessions={handleDeleteSessions}
            onRefresh={refreshSessions}
          />
        </>
      ) : (
        <>
          <HistoryHeader
            sessionName={sessionName}
            onBack={() => setSelectedId("")}
            onExport={handleExport}
            onDelete={handleDelete}
            onRename={async (newName) => { await handleRename(selectedId, newName); }}
            error={error}
            onClearError={() => setError("")}
            subTab={subTab}
            onSubTabChange={setSubTab}
            hasTopics={savedTopics !== null}
          />

          <div className="flex flex-1 overflow-hidden">
            <div
              ref={transcriptScrollRef}
              onScroll={updateActiveTranscriptTimeFromScroll}
              className="flex-1 overflow-y-auto p-4"
            >
              {subTab === "transcript" ? (
                <TranscriptView
                  entries={entries}
                  speakers={speakers}
                  searchQuery={searchQuery}
                  onSearchQueryChange={setSearchQuery}
                  onEditText={handleEditText}
                  onEditSpeaker={handleEditSpeaker}
                  currentEntryId={hasAudio ? playerState.currentEntryId : undefined}
                  onPlayFromEntry={hasAudio ? handlePlayFromEntry : undefined}
                  onToggleBookmark={handleToggleBookmark}
                  onDeleteEntry={handleDeleteEntry}
                />
              ) : subTab === "topics" ? (
                savedTopics && (
                  <TopicTreeView
                    tree={savedTopics}
                    onSeek={hasAudio ? handlePlayFromEntry : undefined}
                  />
                )
              ) : (
                <SummaryView
                  onGenerate={handleGenerate}
                  generating={generating}
                  summary={summary}
                  summaryResult={summaryResult}
                />
              )}
            </div>

            {hasScreenshots && (
              <div className="history-screenshot-panel w-56 shrink-0">
                <ScreenshotPanel
                  sessionId={selectedId}
                  activeTimeSeconds={activeTranscriptTime}
                />
              </div>
            )}
          </div>

          {hasAudio && (
            <PlayerBar
              state={playerState}
              actions={playerActions}
              onDeleteAudio={handleDeleteAudio}
            />
          )}
        </>
      )}
    </div>
  );
}
