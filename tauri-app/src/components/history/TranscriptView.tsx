import { useState } from "react";
import type { TranscriptEntry, Speaker } from "../../lib/types";
import TranscriptEntryComponent from "../TranscriptEntry";

interface Props {
  entries: TranscriptEntry[];
  speakers: Speaker[];
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  onEditText: (entryId: string, newText: string) => Promise<void>;
  onEditSpeaker: (entryId: string, speakerName: string, speakerId: string) => Promise<void>;
  currentEntryId?: string | null;
  onPlayFromEntry?: (timestampStart: number) => void;
  onToggleBookmark?: (entryId: string) => void;
  onDeleteEntry?: (entryId: string) => void;
}

export default function TranscriptView({
  entries,
  speakers,
  searchQuery,
  onSearchQueryChange,
  onEditText,
  onEditSpeaker,
  currentEntryId,
  onPlayFromEntry,
  onToggleBookmark,
  onDeleteEntry,
}: Props) {
  const [bookmarkFilter, setBookmarkFilter] = useState(false);

  if (entries.length === 0) {
    return <p className="text-slate-500">エントリがありません</p>;
  }

  let filtered = entries;
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    filtered = filtered.filter(e =>
      e.text.toLowerCase().includes(q) ||
      e.speaker_name.toLowerCase().includes(q));
  }
  if (bookmarkFilter) {
    filtered = filtered.filter(e => e.bookmarked);
  }

  return (
    <div className="space-y-0.5">
      <div className="mb-2 flex gap-2">
        <input
          value={searchQuery}
          onChange={e => onSearchQueryChange(e.target.value)}
          placeholder="検索..."
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1 text-sm flex-1"
        />
        {onToggleBookmark && (
          <button
            onClick={() => setBookmarkFilter(!bookmarkFilter)}
            className={`px-3 py-1 rounded text-sm border ${
              bookmarkFilter
                ? "bg-yellow-500/20 border-yellow-500 text-yellow-400"
                : "bg-slate-700 border-slate-600 text-slate-400 hover:text-yellow-400"
            }`}
            title="ブックマークのみ表示"
          >
            ★
          </button>
        )}
      </div>
      {filtered.length === 0 ? (
        <p className="text-slate-500">一致するエントリがありません</p>
      ) : (
        filtered.map((e) => (
          <TranscriptEntryComponent
            key={e.id}
            entry={e}
            index={entries.indexOf(e)}
            speakers={speakers}
            onEditText={onEditText}
            onEditSpeaker={onEditSpeaker}
            searchQuery={searchQuery}
            isCurrentlyPlaying={currentEntryId === e.id}
            onPlayFromEntry={onPlayFromEntry}
            onToggleBookmark={onToggleBookmark}
            onDeleteEntry={onDeleteEntry}
          />
        ))
      )}
    </div>
  );
}
