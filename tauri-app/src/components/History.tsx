import { useEffect, useState, useCallback } from "react";
import { getSessions, getTranscript, exportTranscript, deleteSession, editSavedEntry, renameSession, deleteSavedEntry } from "../lib/apiTranscripts";
import { generateSummary, getSummary, getGeminiModels } from "../lib/apiSummary";
import { getSpeakers } from "../lib/apiSpeakers";
import { fetchAudioBlobUrl, getAudioInfo, deleteAudio, compressAudio, toggleBookmark } from "../lib/apiPlayback";
import { listScreenshots } from "../lib/apiScreenshots";
import { useAudioPlayer } from "../lib/useAudioPlayer";
import type { TranscriptEntry, TranscriptSession, SummaryResult, Speaker, GeminiModelInfo } from "../lib/types";
import HistoryHeader from "./history/HistoryHeader";
import SessionList from "./history/SessionList";
import TranscriptView from "./history/TranscriptView";
import SummaryView from "./history/SummaryView";
import ScreenshotPanel from "./history/ScreenshotPanel";
import PlayerBar from "./playback/PlayerBar";

interface Props {
  autoSummarizeSessionId: string | null;
  onAutoSummarizeComplete: () => void;
}

export default function History({ autoSummarizeSessionId, onAutoSummarizeComplete }: Props) {
  const [sessions, setSessions] = useState<TranscriptSession[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [subTab, setSubTab] = useState<"transcript" | "summary">("transcript");
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [summary, setSummary] = useState("");
  const [summaryResult, setSummaryResult] = useState<SummaryResult | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [geminiModels, setGeminiModels] = useState<GeminiModelInfo[]>([]);
  const [geminiCurrent, setGeminiCurrent] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [hasAudio, setHasAudio] = useState(false);
  const [hasScreenshots, setHasScreenshots] = useState(false);

  const [playerState, playerActions] = useAudioPlayer(entries);

  const refreshSessions = useCallback(async () => {
    try {
      const data = await getSessions();
      setSessions(data.sessions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refreshSessions();
    getSpeakers()
      .then((data) => setSpeakers(data.speakers))
      .catch(() => {});
    getGeminiModels()
      .then((data) => {
        setGeminiModels(data.models);
        setGeminiCurrent(data.current_model);
      })
      .catch(() => {});
  }, [refreshSessions]);

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
      playerActions.destroy();
      return;
    }
    setSearchQuery("");
    let cancelled = false;

    const load = async () => {
      const [transcriptResult, summaryResult, audioInfoResult, screenshotsResult] = await Promise.allSettled([
        getTranscript(selectedId),
        getSummary(selectedId),
        getAudioInfo(selectedId),
        listScreenshots(selectedId),
      ]);
      if (cancelled) return;

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

  const handleGenerate = async () => {
    if (!selectedId) return;
    setGenerating(true);
    setError("");
    try {
      const result = await generateSummary(selectedId);
      setSummary(result.summary);
      setSummaryResult(result);
      await refreshSessions();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async (format: "txt" | "json" | "md") => {
    if (!selectedId) return;
    try {
      const content = await exportTranscript(selectedId, format);
      // Try Tauri native save dialog first
      if ((window as any).__TAURI__) {
        try {
          const { save } = await import("@tauri-apps/plugin-dialog");
          const { writeTextFile } = await import("@tauri-apps/plugin-fs");
          const path = await save({
            defaultPath: `${selectedId}.${format}`,
            filters: [{ name: format.toUpperCase(), extensions: [format] }],
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
      a.download = `${selectedId}.${format}`;
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
    <div className="flex flex-col h-full">
      {!selectedId ? (
        <SessionList
          sessions={sessions}
          onSelectSession={setSelectedId}
          onRenameSession={handleRename}
          onDeleteSession={handleDeleteFromList}
          onDeleteSessions={handleDeleteSessions}
          onRefresh={refreshSessions}
        />
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
          />

          <div className="flex flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-4">
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
              ) : (
                <SummaryView
                  geminiModels={geminiModels}
                  geminiCurrent={geminiCurrent}
                  onGeminiCurrentChange={setGeminiCurrent}
                  onGenerate={handleGenerate}
                  generating={generating}
                  summary={summary}
                  summaryResult={summaryResult}
                  onError={setError}
                />
              )}
            </div>

            {hasScreenshots && (
              <div className="w-56 border-l border-slate-700 shrink-0">
                <ScreenshotPanel sessionId={selectedId} />
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
