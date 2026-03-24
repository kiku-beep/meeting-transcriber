import { useState } from "react";
import { setGeminiApiKey } from "../../lib/apiConfig";

interface Props {
  apiKeySet: boolean;
  apiKeyMasked: string | null;
  onSaved: () => void;
}

export default function SettingsApiKey({ apiKeySet, apiKeyMasked, onSaved }: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    if (!value.trim()) return;
    setSaving(true);
    setError("");
    try {
      await setGeminiApiKey(value.trim());
      setValue("");
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const showInput = !apiKeySet || editing;

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">API キー</h3>

      {!showInput ? (
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400" />
          <span className="text-sm text-slate-300 font-mono">{apiKeyMasked}</span>
          <button
            onClick={() => setEditing(true)}
            className="text-xs text-cyan-400 hover:text-cyan-300 ml-2"
          >
            変更
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {!apiKeySet && (
            <p className="text-xs text-red-400">Gemini API キーが設定されていません</p>
          )}
          <div className="flex items-center gap-2">
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="GEMINI_API_KEY を入力"
              className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm flex-1 font-mono"
              onKeyDown={(e) => { if (!e.nativeEvent.isComposing && e.keyCode !== 229 && e.key === "Enter") handleSave(); }}
            />
            <button
              onClick={handleSave}
              disabled={saving || !value.trim()}
              className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-600 rounded text-sm transition-colors"
            >
              {saving ? "保存中..." : "保存"}
            </button>
            {apiKeySet && (
              <button
                onClick={() => { setEditing(false); setValue(""); setError(""); }}
                className="text-xs text-slate-400 hover:text-slate-200"
              >
                キャンセル
              </button>
            )}
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      )}
    </section>
  );
}
