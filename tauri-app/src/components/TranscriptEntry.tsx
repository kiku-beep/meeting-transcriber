import { useEffect, useRef, useState } from "react";
import type { TranscriptEntry as EntryType, Speaker } from "../lib/types";
import EntrySpeaker from "./transcription/EntrySpeaker";
import EntryEditor from "./transcription/EntryEditor";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  entry: EntryType;
  index: number;
  speakers?: Speaker[];
  onEditText?: (entryId: string, newText: string) => Promise<void>;
  onEditSpeaker?: (entryId: string, speakerName: string, speakerId: string) => Promise<void>;
  onEditSpeakerBulk?: (entryId: string, speakerName: string, speakerId: string) => Promise<void>;
  onNameCluster?: (clusterId: string, name: string, isGuest: boolean) => Promise<void>;
  onRegisterNewSpeaker?: (entryId: string, name: string, isGuest: boolean) => Promise<void>;
  onConfirmSuggestion?: (clusterId: string, speakerId: string, speakerName: string) => Promise<void>;
  searchQuery?: string;
  isCurrentlyPlaying?: boolean;
  onPlayFromEntry?: (timestampStart: number) => void;
  onToggleBookmark?: (entryId: string) => void;
  onDeleteEntry?: (entryId: string) => void;
}

export default function TranscriptEntry({
  entry, index, speakers, onEditText, onEditSpeaker, onEditSpeakerBulk, onNameCluster, onRegisterNewSpeaker, onConfirmSuggestion, searchQuery,
  isCurrentlyPlaying, onPlayFromEntry, onToggleBookmark, onDeleteEntry,
}: Props) {
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Auto-scroll when this entry becomes the currently playing one
  useEffect(() => {
    if (isCurrentlyPlaying && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [isCurrentlyPlaying]);

  const handleEditSpeaker = async (name: string, id: string) => {
    if (!onEditSpeaker) return;
    setSaving(true);
    try {
      await onEditSpeaker(entry.id, name, id);
    } finally {
      setSaving(false);
    }
  };

  const handleEditSpeakerBulk = async (name: string, id: string) => {
    if (!onEditSpeakerBulk) return;
    setSaving(true);
    try {
      await onEditSpeakerBulk(entry.id, name, id);
    } finally {
      setSaving(false);
    }
  };

  const handleRegisterNewSpeaker = async (name: string, isGuest: boolean) => {
    if (!onRegisterNewSpeaker) return;
    setSaving(true);
    try {
      await onRegisterNewSpeaker(entry.id, name, isGuest);
    } finally {
      setSaving(false);
    }
  };

  const handleNameCluster = async (clusterId: string, name: string, isGuest: boolean) => {
    if (!onNameCluster) return;
    setSaving(true);
    try {
      await onNameCluster(clusterId, name, isGuest);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      ref={ref}
      data-transcript-entry-start={entry.timestamp_start}
      className={`transcript-entry group ${saving ? "opacity-50" : ""} ${isCurrentlyPlaying ? "is-playing" : ""}`}
    >
      <span className="transcript-entry__index">
        #{index}
        {entry.refined && <span style={{ color: "#4ade80", fontSize: "0.7em", marginLeft: 2 }} title="AI補正済み">✓</span>}
      </span>

      {/* Play button */}
      {onPlayFromEntry && (
        <button
          onClick={() => onPlayFromEntry(entry.timestamp_start)}
          className="transcript-entry__action transcript-entry__play"
          title="ここから再生"
        >
          ▶
        </button>
      )}

      <span className="transcript-entry__time">
        {formatTime(entry.timestamp_start)}
      </span>

      {/* Bookmark */}
      {onToggleBookmark && (
        <button
          onClick={() => onToggleBookmark(entry.id)}
          className={`transcript-entry__action ${entry.bookmarked ? "is-bookmarked" : ""}`}
          title={entry.bookmarked ? "ブックマーク解除" : "ブックマーク"}
        >
          {entry.bookmarked ? "★" : "☆"}
        </button>
      )}

      {/* Delete */}
      {onDeleteEntry && (
        <button
          onClick={() => onDeleteEntry(entry.id)}
          className="transcript-entry__action transcript-entry__delete"
          title="エントリを削除"
        >
          ✕
        </button>
      )}

      <div className="transcript-entry__speaker"><EntrySpeaker
        speakerName={entry.speaker_name}
        speakerId={entry.speaker_id}
        speakerConfidence={entry.speaker_confidence}
        clusterId={entry.cluster_id}
        suggestedSpeakerId={entry.suggested_speaker_id}
        suggestedSpeakerName={entry.suggested_speaker_name}
        speakers={speakers}
        onEditSpeaker={onEditSpeaker ? handleEditSpeaker : undefined}
        onEditSpeakerBulk={onEditSpeakerBulk ? handleEditSpeakerBulk : undefined}
        onNameCluster={onNameCluster ? handleNameCluster : undefined}
        onRegisterNewSpeaker={onRegisterNewSpeaker ? handleRegisterNewSpeaker : undefined}
        onConfirmSuggestion={onConfirmSuggestion}
      /></div>

      <div className="transcript-entry__message"><EntryEditor
        text={entry.text}
        entryId={entry.id}
        searchQuery={searchQuery}
        onEditText={onEditText}
        onSavingChange={setSaving}
      /></div>
    </div>
  );
}
