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
    if (c >= 0.9) return "learning-confidence--high";
    if (c >= 0.7) return "learning-confidence--medium";
    return "learning-confidence--low";
  };

  return (
    <section className="learning-suggestions space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="learning-suggestions__title text-sm font-medium">学習候補</h3>
        <button
          onClick={handleLoadSuggestions}
          disabled={loadingSuggestions}
          className="learning-suggestions__action px-3 py-1 rounded text-xs"
        >
          {loadingSuggestions ? "分析中..." : "訂正履歴を分析"}
        </button>
        {suggestions.length > 0 && (
          <span className="learning-suggestions__count text-xs">{suggestions.length}件の候補</span>
        )}
      </div>

      {error && (
        <div className="inline-alert inline-alert--error text-xs" role="alert">
          {error}
        </div>
      )}

      {suggestionsOpen && suggestions.length > 0 && (
        <div className="learning-suggestions__table border rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="learning-suggestions__head">
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
                <tr key={i} className="learning-suggestions__row border-t">
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
                        className="learning-suggestions__accept px-2 py-0.5 rounded text-xs"
                      >
                        採用
                      </button>
                      <button
                        onClick={() => handleDismissSuggestion(s.from_text, s.to_text)}
                        className="learning-suggestions__dismiss px-2 py-0.5 rounded text-xs"
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
