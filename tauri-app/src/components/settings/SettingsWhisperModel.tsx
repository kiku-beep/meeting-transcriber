import type { ModelStatus } from "../../lib/types";

interface Props {
  model: ModelStatus | null;
  selectedModel: string;
  switching: boolean;
  switchStage: string; // "" | "unloading" | "warming" | "loading" | "ready"
  switchProgress: number; // 0.0 - 1.0
  cacheWarming: boolean;
  onSelectedModelChange: (value: string) => void;
  onSwitch: () => void;
}

const STAGE_LABELS: Record<string, string> = {
  unloading: "旧モデル解放中...",
  warming: "キャッシュ読込中...",
  loading: "GPU転送中...",
  ready: "完了",
};

export default function SettingsWhisperModel({
  model,
  selectedModel,
  switching,
  switchStage,
  switchProgress,
  cacheWarming,
  onSelectedModelChange,
  onSwitch,
}: Props) {
  if (!model) return null;

  const stageLabel = STAGE_LABELS[switchStage] || "";

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">Whisper モデル</h3>
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={selectedModel}
          onChange={(e) => onSelectedModelChange(e.target.value)}
          disabled={switching}
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm"
        >
          {model.available_models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} ({m.vram_mb}MB)
            </option>
          ))}
        </select>
        <button
          onClick={onSwitch}
          disabled={switching || selectedModel === model.current_model}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-600 rounded text-sm transition-colors"
        >
          {switching ? stageLabel || "切替中..." : "切替"}
        </button>
        <span className="text-sm text-slate-400">
          現在: <span className="text-cyan-400">{model.current_model}</span>
          {model.is_loaded ? " (ロード済み)" : " (未ロード)"}
          {cacheWarming && selectedModel !== model.current_model && (
            <span className="text-amber-400 ml-2">先読み中...</span>
          )}
        </span>
      </div>
      {switching && (
        <div className="space-y-1">
          <div className="w-full bg-slate-700 rounded-full h-2 overflow-hidden">
            <div
              className="bg-cyan-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${Math.max(switchProgress * 100, 5)}%` }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
