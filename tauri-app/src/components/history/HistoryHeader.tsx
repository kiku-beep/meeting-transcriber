import { useState, useRef, useEffect } from "react";
import type { TranscriptExportFormat } from "../../lib/apiTranscripts";

const EXPORT_OPTIONS: { format: TranscriptExportFormat; label: string }[] = [
  { format: "txt", label: "TXT" },
  { format: "json", label: "JSON" },
  { format: "md", label: "MD" },
  { format: "action-md", label: "AIアクション" },
];

interface Props {
  sessionName: string;
  onBack: () => void;
  onExport: (format: TranscriptExportFormat) => void;
  onDelete: () => void;
  onRename: (newName: string) => Promise<void>;
  error: string;
  onClearError: () => void;
  subTab: "transcript" | "summary" | "topics";
  onSubTabChange: (tab: "transcript" | "summary" | "topics") => void;
  /** 論点ツリーが保存されている会議だけタブを出す（機能OFFで録った会議には無い）。 */
  hasTopics?: boolean;
}

export default function HistoryHeader({
  sessionName,
  onBack,
  onExport,
  onDelete,
  onRename,
  error,
  onClearError,
  subTab,
  onSubTabChange,
  hasTopics = false,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const startEdit = () => {
    setEditName(sessionName);
    setEditing(true);
  };

  const commitEdit = async () => {
    const name = editName.trim();
    if (name && name !== sessionName) {
      await onRename(name);
    }
    setEditing(false);
  };

  return (
    <div className="history-header p-4 space-y-3 shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="history-header__button flex items-center gap-1 px-2 py-1.5 text-sm shrink-0"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          戻る
        </button>
        {editing ? (
          <input
            ref={inputRef}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitEdit();
              if (e.key === "Escape") setEditing(false);
            }}
            onBlur={commitEdit}
            className="history-header__input text-lg font-semibold flex-1 min-w-0 rounded px-2 py-0.5 focus:outline-none"
          />
        ) : (
          <h2
            onClick={startEdit}
            className="history-header__title text-lg font-semibold flex-1 min-w-0 truncate cursor-pointer group"
            title="クリックで会議名を編集"
          >
            {sessionName}
            <svg
              className="history-header__edit-icon inline-block ml-2 w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
              />
            </svg>
          </h2>
        )}
        <div className="flex gap-1 shrink-0">
          {EXPORT_OPTIONS.map(({ format, label }) => (
            <button
              key={format}
              onClick={() => onExport(format)}
              className="history-header__button px-2 py-1 text-xs"
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={onDelete}
          className="history-header__button history-header__button--danger px-3 py-1.5 text-sm shrink-0"
        >
          削除
        </button>
      </div>

      {error && (
        <div className="inline-alert inline-alert--error flex items-center justify-between" role="alert">
          <span>{error}</span>
          <button onClick={onClearError} className="inline-alert__dismiss ml-2 shrink-0">&#x2715;</button>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => onSubTabChange("transcript")}
          className={`history-header__tab px-3 py-1 text-sm ${subTab === "transcript" ? "history-header__tab--active" : ""}`}
        >
          文字起こし
        </button>
        <button
          onClick={() => onSubTabChange("summary")}
          className={`history-header__tab px-3 py-1 text-sm ${subTab === "summary" ? "history-header__tab--active" : ""}`}
        >
          要約
        </button>
        {hasTopics && (
          <button
            onClick={() => onSubTabChange("topics")}
            className={`history-header__tab px-3 py-1 text-sm ${subTab === "topics" ? "history-header__tab--active" : ""}`}
          >
            論点
          </button>
        )}
      </div>
    </div>
  );
}
