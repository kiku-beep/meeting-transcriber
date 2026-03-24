import type { GeminiModelInfo } from "../../lib/types";

interface Props {
  geminiModels: GeminiModelInfo[];
  geminiCurrent: string;
  selectedGemini: string;
  switchingGemini: boolean;
  onSelectedGeminiChange: (value: string) => void;
  onSwitch: () => void;
}

export default function SettingsGeminiModel({ geminiModels, geminiCurrent, selectedGemini, switchingGemini, onSelectedGeminiChange, onSwitch }: Props) {
  if (geminiModels.length === 0) return null;

  const speedLabel: Record<string, string> = { very_fast: "最速", fast: "速い", slow: "遅め" };
  const accuracyLabel: Record<string, string> = { low: "低", medium: "中", high: "高", very_high: "最高" };

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">Gemini モデル (要約用)</h3>
      <div className="flex items-center gap-3 flex-wrap">
        <select
          value={selectedGemini}
          onChange={(e) => onSelectedGeminiChange(e.target.value)}
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm"
        >
          {geminiModels.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
        <button
          onClick={onSwitch}
          disabled={switchingGemini || selectedGemini === geminiCurrent}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-600 rounded text-sm transition-colors"
        >
          {switchingGemini ? "切替中..." : "切替"}
        </button>
        <span className="text-sm text-slate-400">
          現在: <span className="text-cyan-400">{geminiModels.find(m => m.id === geminiCurrent)?.label || geminiCurrent}</span>
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 gap-y-1 text-xs">
        <span className="text-slate-500 font-medium">モデル</span>
        <span className="text-slate-500 font-medium">速度</span>
        <span className="text-slate-500 font-medium">精度</span>
        <span className="text-slate-500 font-medium">コスト (入/出 per 1M)</span>
        {geminiModels.map((m) => {
          const isCurrent = m.id === geminiCurrent;
          return [
            <span key={`${m.id}-n`} className={isCurrent ? "text-cyan-400" : "text-slate-300"}>{m.label}</span>,
            <span key={`${m.id}-s`} className="text-slate-400">{speedLabel[m.speed]}</span>,
            <span key={`${m.id}-a`} className="text-slate-400">{accuracyLabel[m.accuracy]}</span>,
            <span key={`${m.id}-c`} className="text-slate-400">${m.input_price} / ${m.output_price}</span>,
          ];
        })}
      </div>
    </section>
  );
}
