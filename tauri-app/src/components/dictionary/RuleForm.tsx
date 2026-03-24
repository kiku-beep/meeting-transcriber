import { useState } from "react";
import { addReplacement } from "../../lib/apiDictionary";

interface Props {
  onAdd: () => void;
}

export default function RuleForm({ onAdd }: Props) {
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [isRegex, setIsRegex] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const handleAdd = async () => {
    if (!fromText || !toText) return;
    setError("");
    try {
      await addReplacement({
        from_text: fromText,
        to_text: toText,
        case_sensitive: false,
        enabled: true,
        is_regex: isRegex,
        note,
      });
      setFromText("");
      setToText("");
      setIsRegex(false);
      setNote("");
      onAdd();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">ルール追加</h3>

      {error && (
        <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs">
          {error}
        </div>
      )}

      <div className="flex items-end gap-2 flex-wrap">
        <div>
          <label className="block text-xs text-slate-400 mb-1">変換元</label>
          <input
            value={fromText}
            onChange={(e) => setFromText(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm w-40"
            placeholder="かなめ"
          />
        </div>
        <span className="text-slate-500 pb-1.5">→</span>
        <div>
          <label className="block text-xs text-slate-400 mb-1">変換先</label>
          <input
            value={toText}
            onChange={(e) => setToText(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm w-40"
            placeholder="カナメ"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">メモ</label>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm w-32"
            placeholder="人名"
          />
        </div>
        <label className="flex items-center gap-1.5 pb-1.5 text-sm">
          <input
            type="checkbox"
            checked={isRegex}
            onChange={(e) => setIsRegex(e.target.checked)}
            className="accent-cyan-500"
          />
          正規表現
        </label>
        <button
          onClick={handleAdd}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 rounded text-sm transition-colors"
        >
          追加
        </button>
      </div>
    </section>
  );
}
