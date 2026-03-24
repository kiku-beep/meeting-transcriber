import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { setGeminiModel } from "../../lib/apiSummary";
import type { GeminiModelInfo, SummaryResult } from "../../lib/types";

interface Props {
  geminiModels: GeminiModelInfo[];
  geminiCurrent: string;
  onGeminiCurrentChange: (id: string) => void;
  onGenerate: () => void;
  generating: boolean;
  summary: string;
  summaryResult: SummaryResult | null;
  onError: (msg: string) => void;
}

export default function SummaryView({
  geminiModels,
  geminiCurrent,
  onGeminiCurrentChange,
  onGenerate,
  generating,
  summary,
  summaryResult,
  onError,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [copiedSlack, setCopiedSlack] = useState(false);

  return (
    <div className="space-y-4">
      {/* Model selector + Generate button */}
      <div className="flex items-center gap-3 flex-wrap">
        {geminiModels.length > 0 && (
          <select
            value={geminiCurrent}
            onChange={async (e) => {
              const id = e.target.value;
              try {
                await setGeminiModel(id);
                onGeminiCurrentChange(id);
              } catch (err) {
                onError(err instanceof Error ? err.message : String(err));
              }
            }}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm"
          >
            {geminiModels.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        )}
        <button
          onClick={onGenerate}
          disabled={generating}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 disabled:bg-slate-600 rounded text-sm transition-colors"
        >
          {generating ? "生成中..." : "要約を生成"}
        </button>
      </div>

      {/* Model info badges */}
      {geminiModels.length > 0 && (() => {
        const cur = geminiModels.find((m) => m.id === geminiCurrent);
        if (!cur) return null;
        const speedLabel: Record<string, string> = { very_fast: "最速", fast: "速い", slow: "遅め" };
        const accuracyLabel: Record<string, string> = { low: "低", medium: "中", high: "高", very_high: "最高" };
        const speedColor: Record<string, string> = { very_fast: "bg-emerald-800 text-emerald-200", fast: "bg-emerald-900 text-emerald-300", slow: "bg-amber-900 text-amber-300" };
        const accuracyColor: Record<string, string> = { low: "bg-slate-700 text-slate-300", medium: "bg-blue-900 text-blue-300", high: "bg-blue-800 text-blue-200", very_high: "bg-violet-800 text-violet-200" };
        return (
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <span className={`px-2 py-0.5 rounded ${speedColor[cur.speed] || ""}`}>
              速度: {speedLabel[cur.speed] || cur.speed}
            </span>
            <span className={`px-2 py-0.5 rounded ${accuracyColor[cur.accuracy] || ""}`}>
              精度: {accuracyLabel[cur.accuracy] || cur.accuracy}
            </span>
            <span className="px-2 py-0.5 rounded bg-slate-700 text-slate-300">
              ${cur.input_price} / ${cur.output_price} per 1M tokens
            </span>
            {summaryResult?.usage && (
              <span className="text-slate-400">
                {summaryResult.usage.total_tokens?.toLocaleString()} tokens
                {" "}(${summaryResult.usage.cost_usd?.toFixed(4)})
              </span>
            )}
          </div>
        );
      })()}

      {summary ? (
        <div className="space-y-2">
          <div className="flex gap-2">
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(summary);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs transition-colors"
            >
              {copied ? "コピー済み" : "コピー"}
            </button>
            <button
              onClick={async () => {
                const html = markdownToSlackHtml(summary);
                const htmlBlob = new Blob([html], { type: "text/html" });
                const textBlob = new Blob([summary], { type: "text/plain" });
                await navigator.clipboard.write([
                  new ClipboardItem({ "text/html": htmlBlob, "text/plain": textBlob }),
                ]);
                setCopiedSlack(true);
                setTimeout(() => setCopiedSlack(false), 2000);
              }}
              className="px-3 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs transition-colors"
            >
              {copiedSlack ? "コピー済み" : "Slack用コピー"}
            </button>
          </div>
          <div className="summary-markdown">
            <ReactMarkdown>{summary}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <p className="text-slate-500">要約がありません。「要約を生成」で作成できます。</p>
      )}
    </div>
  );
}

/**
 * Markdown → HTML 変換（Slackペースト用）
 * Slackはネストした<ul>を無視するため、<b>太字ヘッダー + フラット<ul>で構造化する
 */
function markdownToSlackHtml(md: string): string {
  const lines = md.split("\n");
  let started = false;

  interface Section {
    title: string;
    items: { text: string; sub?: string }[];
  }
  const sections: Section[] = [];
  let current: Section | null = null;

  for (const line of lines) {
    const headerMatch = line.match(/^## (.+)/);
    if (headerMatch) {
      started = true;
      current = { title: headerMatch[1], items: [] };
      sections.push(current);
      continue;
    }
    if (!started || !current || line.trim() === "") continue;

    const topBullet = line.match(/^- (.+)/);
    if (topBullet) {
      current.items.push({ text: topBullet[1] });
      continue;
    }
    const nestedBullet = line.match(/^\s+- (.+)/);
    if (nestedBullet && current.items.length > 0) {
      const last = current.items[current.items.length - 1];
      last.sub = (last.sub ? last.sub + "\n" : "") + nestedBullet[1];
      continue;
    }
    current.items.push({ text: line });
  }

  let html = "";
  for (const sec of sections) {
    html += `<b>${sec.title}</b><br>`;
    if (sec.items.length > 0) {
      html += "<ul>";
      for (const item of sec.items) {
        if (item.sub) {
          const subLines = item.sub.split("\n").map((s) => `　→ ${s}`).join("<br>");
          html += `<li>${item.text}<br>${subLines}</li>`;
        } else {
          html += `<li>${item.text}</li>`;
        }
      }
      html += "</ul>";
    }
  }
  return html;
}
