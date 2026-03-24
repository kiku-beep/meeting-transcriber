import { useRef, useEffect } from "react";
import type { TranscriptEntry, Speaker } from "../../lib/types";
import TranscriptEntryComponent from "../TranscriptEntry";

interface Props {
  entries: TranscriptEntry[];
  filteredEntries: TranscriptEntry[];
  speakers: Speaker[];
  searchQuery: string;
  isRunning: boolean;
  onEditText: (entryId: string, newText: string) => Promise<void>;
  onEditSpeaker: (entryId: string, speakerName: string, speakerId: string) => Promise<void>;
  onEditSpeakerBulk?: (entryId: string, speakerName: string, speakerId: string) => Promise<void>;
  onNameCluster?: (clusterId: string, name: string, isGuest: boolean) => Promise<void>;
  onRegisterNewSpeaker?: (entryId: string, name: string, isGuest: boolean) => Promise<void>;
  onConfirmSuggestion?: (clusterId: string, speakerId: string, speakerName: string) => Promise<void>;
  onDeleteEntry?: (entryId: string) => void;
}

export default function TranscriptList({
  entries,
  filteredEntries,
  speakers,
  searchQuery,
  isRunning,
  onEditText,
  onEditSpeaker,
  onEditSpeakerBulk,
  onNameCluster,
  onRegisterNewSpeaker,
  onConfirmSuggestion,
  onDeleteEntry,
}: Props) {
  const entriesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottom = useRef(true);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
  };

  // Auto-scroll on new entries only when user is near bottom
  useEffect(() => {
    if (isNearBottom.current) {
      entriesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [entries]);

  return (
    <div className="flex-1 overflow-y-auto p-2" ref={containerRef} onScroll={handleScroll}>
      {entries.length === 0 ? (
        <p className="text-slate-500 text-center mt-20">
          {isRunning ? "音声を待っています..." : "録音を開始してください"}
        </p>
      ) : filteredEntries.length === 0 ? (
        <p className="text-slate-500 text-center mt-20">
          一致するエントリがありません
        </p>
      ) : (
        filteredEntries.map((e) => (
          <TranscriptEntryComponent
            key={e.id}
            entry={e}
            index={entries.indexOf(e)}
            speakers={speakers}
            onEditText={onEditText}
            onEditSpeaker={onEditSpeaker}
            onEditSpeakerBulk={onEditSpeakerBulk}
            onNameCluster={onNameCluster}
            onRegisterNewSpeaker={onRegisterNewSpeaker}
            onConfirmSuggestion={onConfirmSuggestion}
            searchQuery={searchQuery}
            onDeleteEntry={onDeleteEntry}
          />
        ))
      )}
      <div ref={entriesEndRef} />
    </div>
  );
}
