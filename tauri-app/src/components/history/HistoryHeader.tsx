import { useState, useRef, useEffect } from "react";

interface Props {
  sessionName: string;
  onBack: () => void;
  onExport: (format: "txt" | "json" | "md") => void;
  onDelete: () => void;
  onRename: (newName: string) => Promise<void>;
  error: string;
  onClearError: () => void;
  subTab: "transcript" | "summary";
  onSubTabChange: (tab: "transcript" | "summary") => void;
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
    <div className="p-4 border-b border-slate-700 space-y-3 shrink-0">
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-2 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-sm transition-colors shrink-0"
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
            className="text-lg font-semibold flex-1 min-w-0 bg-slate-700 border border-cyan-500 rounded px-2 py-0.5 focus:outline-none"
          />
        ) : (
          <h2
            onClick={startEdit}
            className="text-lg font-semibold flex-1 min-w-0 truncate cursor-pointer hover:text-cyan-300 transition-colors group"
            title="クリックで会議名を編集"
          >
            {sessionName}
            <svg
              className="inline-block ml-2 w-4 h-4 text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity"
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
          {(["txt", "json", "md"] as const).map((fmt) => (
            <button
              key={fmt}
              onClick={() => onExport(fmt)}
              className="px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs transition-colors"
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
        <button
          onClick={onDelete}
          className="px-3 py-1.5 bg-red-800 hover:bg-red-700 rounded text-sm transition-colors shrink-0"
        >
          削除
        </button>
      </div>

      {error && (
        <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={onClearError} className="text-red-400 hover:text-red-300 ml-2 shrink-0">&#x2715;</button>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => onSubTabChange("transcript")}
          className={`px-3 py-1 rounded text-sm ${
            subTab === "transcript"
              ? "bg-cyan-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          }`}
        >
          文字起こし
        </button>
        <button
          onClick={() => onSubTabChange("summary")}
          className={`px-3 py-1 rounded text-sm ${
            subTab === "summary"
              ? "bg-cyan-600 text-white"
              : "bg-slate-700 text-slate-300 hover:bg-slate-600"
          }`}
        >
          要約
        </button>
      </div>
    </div>
  );
}
