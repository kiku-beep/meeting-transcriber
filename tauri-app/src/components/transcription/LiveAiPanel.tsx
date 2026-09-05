import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { generateLiveAi } from "../../lib/apiSummary";
import type { LiveAiMode, LiveAiResult } from "../../lib/types";
import { getUsagePresentation } from "../../lib/summaryUsage";

interface Props {
  open: boolean;
  sessionId: string | null;
  hasEntries: boolean;
  onClose: () => void;
}

const RANGE_OPTIONS = [
  { value: "all", label: "会議全体" },
  { value: "5", label: "過去5分" },
  { value: "15", label: "過去15分" },
  { value: "30", label: "過去30分" },
  { value: "60", label: "過去60分" },
  { value: "custom", label: "任意の時間" },
];

function formatClock(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export default function LiveAiPanel({ open, sessionId, hasEntries, onClose }: Props) {
  const [mode, setMode] = useState<LiveAiMode>("summary");
  const [range, setRange] = useState("15");
  const [customMinutes, setCustomMinutes] = useState(20);
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<LiveAiResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setHistory([]);
    setError("");
  }, [sessionId]);

  const rangeMinutes = range === "all" ? null : range === "custom" ? customMinutes : Number(range);

  const submit = async () => {
    if (loading || !hasEntries) return;
    if (mode === "question" && !question.trim()) {
      setError("質問を入力してください");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await generateLiveAi(mode, rangeMinutes, question.trim());
      setHistory((previous) => [result, ...previous]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  };

  return (
    <aside
      aria-label="会議AI"
      aria-hidden={!open}
      className={`live-ai-panel ${open ? "live-ai-panel--open" : ""}`}
    >
      <header className="live-ai-panel__header">
        <h2>会議AI</h2>
        <button type="button" className="icon-button" aria-label="AIパネルを閉じる" onClick={onClose}>×</button>
      </header>

      <div className="segmented-tabs" role="tablist" aria-label="AI機能">
        <button role="tab" aria-selected={mode === "summary"} onClick={() => setMode("summary")}>途中要約</button>
        <button role="tab" aria-selected={mode === "question"} onClick={() => setMode("question")}>質問</button>
      </div>

      <div className="live-ai-panel__body">
        <div className="live-ai-panel__controls">
          <label className="field-label" htmlFor="live-ai-range">対象範囲</label>
          <select id="live-ai-range" aria-label="対象範囲" value={range} onChange={(event) => setRange(event.target.value)}>
            {RANGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          {range === "custom" && (
            <label className="custom-minutes">
              <input
                type="number"
                min={1}
                max={120}
                value={customMinutes}
                onChange={(event) => setCustomMinutes(Math.min(120, Math.max(1, Number(event.target.value) || 1)))}
              />
              分前まで
            </label>
          )}
        </div>

        <div className="live-ai-panel__composer">
          {mode === "question" && (
            <textarea
              aria-label="会議への質問"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="ここまでの会話について質問"
              rows={3}
            />
          )}
          <button type="button" className="button-primary" disabled={loading || !hasEntries} onClick={submit}>
            {loading ? "処理中..." : mode === "summary" ? "↻ 現在までを要約" : "質問する"}
          </button>
          {!hasEntries && <p className="field-hint">文字起こしが届くと利用できます</p>}
          {error && <div className="inline-alert inline-alert--error" role="alert">{error}</div>}
        </div>

        <div className="live-ai-panel__history" aria-live="polite">
          {history.length === 0 ? (
            <div className="panel-empty">実行結果がここに残ります</div>
          ) : history.map((item) => {
            const { provider, diagnostics: fallbackDiagnostics } = getUsagePresentation(item.usage, "live");
            return (
              <article className="ai-result" key={`${item.generated_at}-${item.mode}`}>
                <div className="ai-result__meta">
                  <span className="range-badge">{item.range_minutes ? `直近${item.range_minutes}分` : "会議全体"}</span>
                  <span>{formatClock(item.range_end_seconds)}時点</span>
                  {provider === "claude-code" && (
                    <>
                      <span className="summary-view__badge summary-view__badge--accent">Claude Code</span>
                      <span className="summary-view__badge summary-view__badge--muted">Claudeサブスク枠</span>
                    </>
                  )}
                  {provider === "codex-cli" && (
                    <>
                      <span className="summary-view__badge summary-view__badge--accent">Codex CLI</span>
                      <span className="summary-view__badge summary-view__badge--muted">Codexサブスク枠</span>
                    </>
                  )}
                  {provider === "gemini" && (
                    <span className="summary-view__badge summary-view__badge--warning">Gemini</span>
                  )}
                </div>
                {fallbackDiagnostics.length > 0 && (
                <div className="inline-alert inline-alert--warning" role="status">
                    {fallbackDiagnostics.map((diagnostic) => (
                      <div key={diagnostic.provider}>
                        {diagnostic.label}エラー: {diagnostic.detail}
                      </div>
                    ))}
                </div>
                )}
                <div className="summary-markdown"><ReactMarkdown>{item.content}</ReactMarkdown></div>
              </article>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
