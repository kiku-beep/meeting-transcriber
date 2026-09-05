import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { SummaryResult } from "../../lib/types";
import { getUsagePresentation } from "../../lib/summaryUsage";

interface Props {
  onGenerate: () => void;
  generating: boolean;
  summary: string;
  summaryResult: SummaryResult | null;
}

export default function SummaryView({
  onGenerate,
  generating,
  summary,
  summaryResult,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [copiedSlack, setCopiedSlack] = useState(false);
  const usage = summaryResult?.usage;
  const { provider, diagnostics: fallbackDiagnostics } = getUsagePresentation(usage, "history");

  return (
    <div className="summary-view space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={onGenerate}
          disabled={generating}
          className="summary-view__button summary-view__button--primary px-4 py-1.5 text-sm"
        >
          {generating ? "生成中..." : "要約を生成"}
        </button>
      </div>

      {provider && (
        <div className="flex items-center gap-2 text-xs flex-wrap">
          {provider === "claude-code" && (
            <>
              <span className="summary-view__badge summary-view__badge--accent">
                Claude Code
              </span>
              <span className="summary-view__badge summary-view__badge--muted">
                Claudeサブスク枠
              </span>
            </>
          )}
          {provider === "codex-cli" && (
            <>
              <span className="summary-view__badge summary-view__badge--accent">
                Codex CLI
              </span>
              <span className="summary-view__badge summary-view__badge--muted">
                Codexサブスク枠
              </span>
            </>
          )}
          {provider === "gemini" && (
            <>
              <span className="summary-view__badge summary-view__badge--warning">
                Gemini
              </span>
              {fallbackDiagnostics.length > 0 && (
                <span className="summary-view__badge summary-view__badge--muted">
                  前段プロバイダ失敗のためGeminiを使用
                </span>
              )}
              {usage?.total_tokens !== undefined && usage?.cost_usd !== undefined && (
                <span className="summary-view__meta">
                  {usage.total_tokens.toLocaleString()} tokens
                  {" "}(${usage.cost_usd.toFixed(4)})
                </span>
              )}
            </>
          )}
        </div>
      )}

      {fallbackDiagnostics.length > 0 && (
        <div className="inline-alert inline-alert--warning" role="status">
          {fallbackDiagnostics.map((diagnostic) => (
            <div key={diagnostic.provider}>
              {diagnostic.label}エラー: {diagnostic.detail}
            </div>
          ))}
        </div>
      )}

      {summary ? (
        <div className="space-y-2">
          <div className="flex gap-2">
            <button
              onClick={async () => {
                await navigator.clipboard.writeText(summary);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}
              className="summary-view__button px-3 py-1 text-xs"
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
              className="summary-view__button px-3 py-1 text-xs"
            >
              {copiedSlack ? "コピー済み" : "Slack用コピー"}
            </button>
          </div>
          <div className="summary-markdown">
            <ReactMarkdown>{summary}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <p className="summary-view__empty">要約がありません。「要約を生成」で作成できます。</p>
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
