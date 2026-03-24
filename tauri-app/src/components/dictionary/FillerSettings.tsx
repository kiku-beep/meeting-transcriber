import { useState } from "react";
import { updateFillers } from "../../lib/apiDictionary";

interface Props {
  initialFillers: string[];
  initialEnabled: boolean;
  onSave: () => void;
}

export default function FillerSettings({ initialFillers, initialEnabled, onSave }: Props) {
  const [fillerText, setFillerText] = useState(initialFillers.join("、"));
  const [fillerEnabled, setFillerEnabled] = useState(initialEnabled);
  const [error, setError] = useState("");

  const handleFillerSave = async () => {
    setError("");
    try {
      const fillers = fillerText
        .split(/[、,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      await updateFillers({ fillers, filler_removal_enabled: fillerEnabled });
      onSave();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">フィラー設定</h3>

      {error && (
        <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs">
          {error}
        </div>
      )}

      <label className="flex items-center gap-1.5 text-sm">
        <input
          type="checkbox"
          checked={fillerEnabled}
          onChange={(e) => setFillerEnabled(e.target.checked)}
          className="accent-cyan-500"
        />
        フィラー除去を有効にする
      </label>
      <div className="flex gap-2">
        <input
          value={fillerText}
          onChange={(e) => setFillerText(e.target.value)}
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="えーと、あのー、えー"
        />
        <button
          onClick={handleFillerSave}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 rounded text-sm transition-colors"
        >
          保存
        </button>
      </div>
    </section>
  );
}
