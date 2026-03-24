import { useState, useRef, useEffect, useMemo } from "react";
import type { TranscriptSession } from "../../lib/types";
import {
  setSessionFavorite,
  setSessionFolder,
  getSessionFolders,
  createFolder,
  renameFolder,
  deleteFolderApi,
} from "../../lib/apiTranscripts";

interface Props {
  sessions: TranscriptSession[];
  onSelectSession: (id: string) => void;
  onRenameSession: (id: string, newName: string) => Promise<void>;
  onDeleteSession: (id: string) => Promise<void>;
  onDeleteSessions: (ids: string[]) => Promise<void>;
  onRefresh: () => void;
}

const DAY_NAMES = ["日", "月", "火", "水", "木", "金", "土"];

function formatSessionDate(startedAt?: string, savedAt?: string): { date: string; time: string } {
  if (!startedAt && !savedAt) return { date: "---", time: "" };

  const ref = startedAt || savedAt!;
  const start = new Date(ref);
  const mm = String(start.getMonth() + 1).padStart(2, "0");
  const dd = String(start.getDate()).padStart(2, "0");
  const day = DAY_NAMES[start.getDay()];
  const date = `${mm}/${dd}(${day})`;

  const hh = String(start.getHours()).padStart(2, "0");
  const min = String(start.getMinutes()).padStart(2, "0");
  let time = `${hh}:${min}`;

  if (startedAt && savedAt) {
    const end = new Date(savedAt);
    const ehh = String(end.getHours()).padStart(2, "0");
    const emin = String(end.getMinutes()).padStart(2, "0");
    time += `-${ehh}:${emin}`;
  }

  return { date, time };
}

function formatSize(bytes?: number): string {
  if (bytes == null) return "---";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}GB`;
}

export default function SessionList({ sessions, onSelectSession, onRenameSession, onDeleteSession, onDeleteSessions, onRefresh }: Props) {
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const editRef = useRef<HTMLInputElement>(null);

  // Folders & favorites
  const [folders, setFolders] = useState<{ name: string; count: number }[]>([]);
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [movingSessionId, setMovingSessionId] = useState<string | null>(null);
  const [renamingFolder, setRenamingFolder] = useState<string | null>(null);
  const [renamingFolderName, setRenamingFolderName] = useState("");
  const renameFolderRef = useRef<HTMLInputElement>(null);

  const refreshFolders = async () => {
    try {
      const data = await getSessionFolders();
      setFolders(data.folders);
    } catch { /* ignore */ }
  };

  useEffect(() => { refreshFolders(); }, []);

  useEffect(() => {
    if (editingId && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editingId]);

  const filtered = useMemo(() => {
    let result = sessions;
    if (activeFilter === "favorites") {
      result = result.filter((s) => s.is_favorite);
    } else if (activeFilter === "all") {
      result = result.filter((s) => !s.folder);
    } else {
      result = result.filter((s) => s.folder === activeFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (s) => s.session_name?.toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q),
      );
    }
    return result;
  }, [sessions, activeFilter, search]);

  const handleToggleFavorite = async (e: React.MouseEvent, sessionId: string, current: boolean) => {
    e.stopPropagation();
    await setSessionFavorite(sessionId, !current);
    onRefresh();
  };

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await createFolder(newFolderName.trim());
      setNewFolderName("");
      setShowNewFolder(false);
      await refreshFolders();
    } catch { /* ignore */ }
  };

  const handleRenameFolder = async () => {
    if (!renamingFolder || !renamingFolderName.trim()) { setRenamingFolder(null); return; }
    const newName = renamingFolderName.trim();
    if (newName === renamingFolder) { setRenamingFolder(null); return; }
    try {
      await renameFolder(renamingFolder, newName);
      if (activeFilter === renamingFolder) setActiveFilter(newName);
      await refreshFolders();
      onRefresh();
    } catch { /* ignore */ }
    setRenamingFolder(null);
  };

  const handleDeleteFolder = async (name: string) => {
    if (!confirm(`フォルダ「${name}」とその中の全セッションを削除しますか？\nこの操作は元に戻せません。`)) return;
    try {
      await deleteFolderApi(name);
      if (activeFilter === name) setActiveFilter("all");
      await refreshFolders();
      onRefresh();
    } catch { /* ignore */ }
  };

  const handleMoveToFolder = async (e: React.MouseEvent, sessionId: string, folderName: string) => {
    e.stopPropagation();
    await setSessionFolder(sessionId, folderName);
    setMovingSessionId(null);
    onRefresh();
    refreshFolders();
  };

  const startEdit = (s: TranscriptSession) => {
    setEditingId(s.session_id);
    setEditingName(s.session_name || "");
  };

  const commitEdit = async () => {
    if (!editingId) return;
    const name = editingName.trim();
    if (name) {
      await onRenameSession(editingId, name);
    }
    setEditingId(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const allFilteredSelected = filtered.length > 0 && filtered.every((s) => selectedIds.has(s.session_id));

  const toggleSelectAll = () => {
    if (allFilteredSelected) {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        filtered.forEach((s) => next.delete(s.session_id));
        return next;
      });
    } else {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        filtered.forEach((s) => next.add(s.session_id));
        return next;
      });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    const count = selectedIds.size;
    if (!confirm(`${count}件のセッションを削除しますか？`)) return;
    await onDeleteSessions(Array.from(selectedIds));
    setSelectedIds(new Set());
  };

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="p-4 border-b border-slate-700 shrink-0 flex items-center gap-3">
        <h2 className="text-lg font-semibold shrink-0">履歴</h2>
        <div className="relative flex-1">
          <svg
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="セッション検索..."
            className="w-full bg-slate-700 border border-slate-600 rounded pl-10 pr-3 py-1.5 text-sm placeholder-slate-400 focus:outline-none focus:border-cyan-500"
          />
        </div>
        {selectedIds.size > 0 && (
          <button
            onClick={handleBulkDelete}
            className="shrink-0 px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded text-xs font-medium transition-colors"
          >
            {selectedIds.size}件を削除
          </button>
        )}
      </div>

      {/* Folder tabs */}
      <div className="px-4 py-2 border-b border-slate-700 shrink-0 flex items-center gap-1 flex-wrap">
        <button
          onClick={() => setActiveFilter("favorites")}
          className={`px-3 py-1 rounded text-sm transition-colors ${activeFilter === "favorites" ? "bg-yellow-600 text-white" : "bg-slate-700 hover:bg-slate-600 text-slate-300"}`}
        >
          ★
        </button>
        <button
          onClick={() => setActiveFilter("all")}
          className={`px-3 py-1 rounded text-sm transition-colors ${activeFilter === "all" ? "bg-cyan-600 text-white" : "bg-slate-700 hover:bg-slate-600 text-slate-300"}`}
        >
          すべて
        </button>
        {folders.map((f) => (
          renamingFolder === f.name ? (
            <div key={f.name} className="flex items-center gap-1">
              <input
                ref={renameFolderRef}
                value={renamingFolderName}
                onChange={(e) => setRenamingFolderName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleRenameFolder(); if (e.key === "Escape") setRenamingFolder(null); }}
                onBlur={handleRenameFolder}
                autoFocus
                className="bg-slate-700 border border-cyan-500 rounded px-2 py-0.5 text-sm w-28"
              />
            </div>
          ) : (
            <button
              key={f.name}
              onClick={() => setActiveFilter(f.name)}
              onDoubleClick={(e) => { e.stopPropagation(); setRenamingFolder(f.name); setRenamingFolderName(f.name); }}
              onContextMenu={(e) => { e.preventDefault(); handleDeleteFolder(f.name); }}
              className={`px-3 py-1 rounded text-sm transition-colors ${activeFilter === f.name ? "bg-cyan-600 text-white" : "bg-slate-700 hover:bg-slate-600 text-slate-300"}`}
              title="ダブルクリックで名前変更 / 右クリックで削除"
            >
              {f.name} ({f.count})
            </button>
          )
        ))}
        {showNewFolder ? (
          <div className="flex items-center gap-1">
            <input
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreateFolder(); if (e.key === "Escape") { setShowNewFolder(false); setNewFolderName(""); } }}
              autoFocus
              className="bg-slate-700 border border-cyan-500 rounded px-2 py-0.5 text-sm w-28"
              placeholder="フォルダ名"
            />
            <button onClick={handleCreateFolder} className="text-emerald-400 hover:text-emerald-300 text-sm">&#x2713;</button>
            <button onClick={() => { setShowNewFolder(false); setNewFolderName(""); }} className="text-slate-400 hover:text-slate-300 text-sm">&#x2715;</button>
          </div>
        ) : (
          <button
            onClick={() => setShowNewFolder(true)}
            className="px-3 py-1 rounded text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
          >
            +
          </button>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-slate-800 z-10">
            <tr className="text-left text-xs text-slate-400 border-b border-slate-600">
              <th className="pl-3 pr-1 py-2.5 w-8">
                <input
                  type="checkbox"
                  checked={allFilteredSelected}
                  onChange={toggleSelectAll}
                  className="w-3.5 h-3.5 accent-cyan-500 cursor-pointer"
                />
              </th>
              <th className="py-2.5 w-8"></th>
              <th className="px-4 py-2.5 font-medium w-36">日付</th>
              <th className="px-4 py-2.5 font-medium">会議名</th>
              <th className="px-4 py-2.5 font-medium text-right w-24">容量</th>
              <th className="py-2.5 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-slate-500 py-12">
                  {sessions.length === 0
                    ? "セッションがありません"
                    : "検索結果がありません"}
                </td>
              </tr>
            ) : (
              filtered.map((s) => {
                const { date, time } = formatSessionDate(s.started_at, s.saved_at);
                const isEditing = editingId === s.session_id;
                const isSelected = selectedIds.has(s.session_id);

                return (
                  <tr
                    key={s.session_id}
                    onClick={() => {
                      if (!isEditing) onSelectSession(s.session_id);
                    }}
                    className={`group border-b border-slate-700/50 hover:bg-slate-700/40 cursor-pointer transition-colors ${isSelected ? "bg-slate-700/30" : ""}`}
                  >
                    {/* Checkbox */}
                    <td className="pl-3 pr-1 py-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSelect(s.session_id)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-3.5 h-3.5 accent-cyan-500 cursor-pointer"
                      />
                    </td>

                    {/* Favorite */}
                    <td className="py-3">
                      <button
                        onClick={(e) => handleToggleFavorite(e, s.session_id, !!s.is_favorite)}
                        className={`text-base leading-none px-0.5 hover:scale-110 transition-transform ${s.is_favorite ? "text-yellow-400" : "text-slate-600 hover:text-slate-400"}`}
                        title={s.is_favorite ? "お気に入り解除" : "お気に入りに追加"}
                      >
                        {s.is_favorite ? "\u2605" : "\u2606"}
                      </button>
                    </td>

                    {/* Date */}
                    <td className="px-4 py-3">
                      <div className="text-sm text-slate-200">{date}</div>
                      <div className="text-xs text-slate-400">{time}</div>
                    </td>

                    {/* Session name */}
                    <td className="px-4 py-3">
                      {isEditing ? (
                        <input
                          ref={editRef}
                          value={editingName}
                          onChange={(e) => setEditingName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitEdit();
                            if (e.key === "Escape") cancelEdit();
                          }}
                          onBlur={commitEdit}
                          onClick={(e) => e.stopPropagation()}
                          className="bg-slate-600 border border-cyan-500 rounded px-2 py-0.5 text-sm w-full max-w-md focus:outline-none"
                        />
                      ) : (
                        <div className="flex items-center gap-2 group/name">
                          <span className="text-sm text-slate-200">
                            {s.session_name || s.session_id}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              startEdit(s);
                            }}
                            className="opacity-0 group-hover/name:opacity-100 text-slate-400 hover:text-slate-200 transition-opacity p-0.5"
                            title="名前を変更"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                              />
                            </svg>
                          </button>
                        </div>
                      )}
                    </td>

                    {/* Size */}
                    <td className="px-4 py-3 text-right">
                      <span className="text-sm text-slate-300">{formatSize(s.total_size_bytes)}</span>
                    </td>

                    {/* Actions: folder move + delete */}
                    <td className="py-3 pr-3">
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {/* Folder move */}
                        <div className="relative">
                          <button
                            onClick={(e) => { e.stopPropagation(); setMovingSessionId(movingSessionId === s.session_id ? null : s.session_id); }}
                            className="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-600/50"
                            title="フォルダに移動"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                            </svg>
                          </button>
                          {movingSessionId === s.session_id && (
                            <div className="absolute right-0 top-full mt-1 bg-slate-700 border border-slate-600 rounded shadow-lg z-20 min-w-[120px]">
                              <button
                                onClick={(e) => handleMoveToFolder(e, s.session_id, "")}
                                className={`w-full text-left px-3 py-1.5 text-sm hover:bg-slate-600 ${!s.folder ? "text-cyan-400" : "text-slate-200"}`}
                              >
                                未分類
                              </button>
                              {folders.map((f) => (
                                <button
                                  key={f.name}
                                  onClick={(e) => handleMoveToFolder(e, s.session_id, f.name)}
                                  className={`w-full text-left px-3 py-1.5 text-sm hover:bg-slate-600 ${s.folder === f.name ? "text-cyan-400" : "text-slate-200"}`}
                                >
                                  {f.name}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                        {/* Delete */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            if (confirm(`「${s.session_name || s.session_id}」を削除しますか？`)) {
                              onDeleteSession(s.session_id);
                            }
                          }}
                          className="text-slate-500 hover:text-red-400 p-1 rounded hover:bg-slate-600/50"
                          title="セッションを削除"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
