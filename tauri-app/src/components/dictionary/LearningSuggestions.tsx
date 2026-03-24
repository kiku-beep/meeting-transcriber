import { useState } from "react";
import { getSuggestions, acceptSuggestion } from "../../lib/apiDictionary";
import type { LearningSuggestion } from "../../lib/types";

interface Props {
  onRefresh: () => void;
}

export default function LearningSuggestions({ onRefresh }: Props) {
  const [suggestions, setSuggestions] = useState<LearningSuggestion[]>([]);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [error, setError] = useState("");

  const handleLoadSuggestions = async () => {
    setLoadingSuggestions(true);
    setError("");
    try {
      const data = await getSuggestions();
      setSuggestions(data.suggestions);
      setSuggestionsOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const handleAcceptSuggestion = async (from: string, to: string) => {
    try {
      await acceptSuggestion(from, to);
      setSuggestions((prev) => prev.filter((s) => !(s.from_text === from && s.to_text === to)));
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDismissSuggestion = (from: string, to: string) => {
    setSuggestions((prev) => prev.filter((s) => !(s.from_text === from && s.to_text === to)));
  };

  const confidenceColor = (c: number) => {
    if (c >= 0.9) return "text-emerald-400";
    if (c >= 0.7) return "text-amber-400";
    return "text-orange-400";
  };

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-medium text-slate-300">学習候補</h3>
        <button
          onClick={handleLoadSuggestions}
          disabled={loadingSuggestions}
          className="px-3 py-1 bg-violet-600 hover:bg-violet-700 disabled:bg-slate-600 rounded text-xs transition-colors"
        >
          {loadingSuggestions ? "分析中..." : "訂正履歴を分析"}
        </button>
        {suggestions.length > 0 && (
          <span className="text-xs text-slate-400">{suggestions.length}件の候補</span>
        )}
      </div>

      {error && (
        <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs">
          {error}
        </div>
      )}

      {suggestionsOpen && suggestions.length > 0 && (
        <div className="border border-violet-700/50 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-violet-900/30">
              <tr>
                <th className="px-3 py-2 text-left text-slate-400">変換元</th>
                <th className="px-3 py-2 text-left text-slate-400 w-8"></th>
                <th className="px-3 py-2 text-left text-slate-400">変換先</th>
                <th className="px-3 py-2 text-left text-slate-400">回数</th>
                <th className="px-3 py-2 text-left text-slate-400">信頼度</th>
                <th className="px-3 py-2 w-24"></th>
              </tr>
            </thead>
            <tbody>
              {suggestions.map((s, i) => (
                <tr key={i} className="border-t border-violet-800/30 hover:bg-violet-900/20">
                  <td className="px-3 py-2 font-mono">{s.from_text}</td>
                  <td className="px-3 py-2 text-slate-500">→</td>
                  <td className="px-3 py-2 font-mono">{s.to_text}</td>
                  <td className="px-3 py-2 text-slate-400">{s.count}回</td>
                  <td className={`px-3 py-2 font-medium ${confidenceColor(s.confidence)}`}>
                    {Math.round(s.confidence * 100)}%
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleAcceptSuggestion(s.from_text, s.to_text)}
                        className="px-2 py-0.5 bg-emerald-700 hover:bg-emerald-600 rounded text-xs transition-colors"
                      >
                        採用
                      </button>
                      <button
                        onClick={() => handleDismissSuggestion(s.from_text, s.to_text)}
                        className="px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-xs transition-colors"
                      >
                        却下
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {suggestionsOpen && suggestions.length === 0 && !loadingSuggestions && (
        <p className="text-xs text-slate-500">候補がありません。文字起こしを訂正すると学習候補が生成されます。</p>
      )}
    </section>
  );
}
