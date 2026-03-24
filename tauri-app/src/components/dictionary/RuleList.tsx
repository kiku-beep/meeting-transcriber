import { useState } from "react";
import { updateReplacement } from "../../lib/apiDictionary";
import type { DictionaryConfig, ReplacementRule } from "../../lib/types";

interface Props {
  replacements: DictionaryConfig["replacements"];
  onDelete: (index: number) => void;
  onRefresh: () => void;
}

function EditableCell({
  value,
  editing,
  onChange,
  mono,
}: {
  value: string;
  editing: boolean;
  onChange: (v: string) => void;
  mono?: boolean;
}) {
  if (!editing) {
    return <span className={mono ? "font-mono" : ""}>{value}</span>;
  }
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`w-full bg-slate-900 border border-cyan-600 rounded px-1.5 py-0.5 text-sm focus:outline-none ${mono ? "font-mono" : ""}`}
      autoFocus
    />
  );
}

export default function RuleList({ replacements, onDelete, onRefresh }: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editFrom, setEditFrom] = useState("");
  const [editTo, setEditTo] = useState("");
  const [editNote, setEditNote] = useState("");
  const [saving, setSaving] = useState(false);

  if (replacements.length === 0) return null;

  const handleDelete = (index: number) => {
    if (confirm("このルールを削除しますか?")) {
      onDelete(index);
    }
  };

  const startEdit = (index: number, rule: ReplacementRule) => {
    setEditingIndex(index);
    setEditFrom(rule.from);
    setEditTo(rule.to);
    setEditNote(rule.note);
  };

  const cancelEdit = () => {
    setEditingIndex(null);
  };

  const saveEdit = async (index: number, rule: ReplacementRule) => {
    if (!editFrom.trim()) return;
    setSaving(true);
    try {
      await updateReplacement(index, {
        from_text: editFrom,
        to_text: editTo,
        case_sensitive: rule.case_sensitive,
        enabled: rule.enabled,
        is_regex: rule.is_regex,
        note: editNote,
      });
      setEditingIndex(null);
      onRefresh();
    } catch {
      /* error handled by parent */
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent, index: number, rule: ReplacementRule) => {
    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      saveEdit(index, rule);
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  };

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">
        ルール一覧 ({replacements.length}件)
      </h3>
      <div className="border border-slate-700 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-800">
            <tr>
              <th className="px-3 py-2 text-left text-slate-400 w-10">#</th>
              <th className="px-3 py-2 text-left text-slate-400">変換元</th>
              <th className="px-3 py-2 text-left text-slate-400 w-8"></th>
              <th className="px-3 py-2 text-left text-slate-400">変換先</th>
              <th className="px-3 py-2 text-left text-slate-400">種別</th>
              <th className="px-3 py-2 text-left text-slate-400">メモ</th>
              <th className="px-3 py-2 w-24"></th>
            </tr>
          </thead>
          <tbody>
            {replacements.map((r, i) => {
              const isEditing = editingIndex === i;
              return (
                <tr
                  key={i}
                  className={`border-t border-slate-700 ${isEditing ? "bg-slate-800" : "hover:bg-slate-800/50"}`}
                  onKeyDown={isEditing ? (e) => handleKeyDown(e, i, r) : undefined}
                >
                  <td className="px-3 py-2 text-slate-500">{i}</td>
                  <td className="px-3 py-2">
                    <EditableCell value={isEditing ? editFrom : r.from} editing={isEditing} onChange={setEditFrom} mono />
                  </td>
                  <td className="px-3 py-2 text-slate-500">→</td>
                  <td className="px-3 py-2">
                    <EditableCell value={isEditing ? editTo : r.to} editing={isEditing} onChange={setEditTo} mono />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1">
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs ${
                          r.is_regex ? "bg-violet-800 text-violet-200" : "bg-slate-700 text-slate-300"
                        }`}
                      >
                        {r.is_regex ? "正規表現" : "テキスト"}
                      </span>
                      {r.auto_learned && (
                        <span className="px-1.5 py-0.5 rounded text-xs bg-emerald-800 text-emerald-200">
                          自動学習
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <EditableCell value={isEditing ? editNote : r.note} editing={isEditing} onChange={setEditNote} />
                  </td>
                  <td className="px-3 py-2">
                    {isEditing ? (
                      <div className="flex gap-1">
                        <button
                          onClick={() => saveEdit(i, r)}
                          disabled={saving}
                          className="text-emerald-400 hover:text-emerald-300 text-xs disabled:opacity-40"
                        >
                          保存
                        </button>
                        <button
                          onClick={cancelEdit}
                          className="text-slate-400 hover:text-slate-300 text-xs"
                        >
                          取消
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-1">
                        <button
                          onClick={() => startEdit(i, r)}
                          className="text-cyan-400 hover:text-cyan-300 text-xs"
                        >
                          編集
                        </button>
                        <button
                          onClick={() => handleDelete(i)}
                          className="text-red-400 hover:text-red-300 text-xs"
                        >
                          削除
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
