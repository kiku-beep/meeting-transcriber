import { test } from "@playwright/test";

/**
 * 議論マップの見た目を実物のコンポーネントで確認するためのスクリーンショット取得。
 * アサーションは持たない（レイアウトの目視確認用）。実行:
 *   npx playwright test --project=topics-visual
 */

const runningStatus = {
  status: "running",
  session_id: "live-argmap",
  started_at: "2026-09-03T10:00:00Z",
  segment_count: 12,
  entry_count: 40,
  elapsed_seconds: 560,
};

const tree = {
  nodes: [
    { id: "t1", parent: null, kind: "question", label: "見積PDFの経路", status: "open", start_sec: 30, end_sec: 90 },
    { id: "t2", parent: "t1", kind: "claim", label: "楽楽ネイティブ", status: "open", start_sec: 95, end_sec: 140 },
    { id: "t3", parent: "t1", kind: "claim", label: "現行GASを改修", status: "parked", start_sec: 150, end_sec: 200 },
    { id: "t4", parent: "t1", kind: "constraint", label: "処理用addr未配送", status: "open", start_sec: 210, end_sec: 260 },
    { id: "t5", parent: "t1", kind: "constraint", label: "再保存で印刷落ち", status: "open", start_sec: 265, end_sec: 310 },
    { id: "t6", parent: "t1", kind: "decision", label: "楽楽採用/addr前提", status: "decided", start_sec: 320, end_sec: 380 },
    { id: "t7", parent: null, kind: "question", label: "周知のタイミング", status: "open", start_sec: 400, end_sec: 420 },
    { id: "t8", parent: "t7", kind: "claim", label: "今週中に全社", status: "open", start_sec: 430, end_sec: 460 },
    { id: "t9", parent: "t7", kind: "constraint", label: "営業は月末で多忙", status: "open", start_sec: 470, end_sec: 500 },
    { id: "t10", parent: "t7", kind: "claim", label: "来月頭に部門別", status: "open", start_sec: 510, end_sec: 545 },
  ],
  links: [
    { source: "t5", target: "t3", type: "constrains" },
    { source: "t4", target: "t2", type: "constrains" },
    { source: "t3", target: "t2", type: "objects" },
    { source: "t2", target: "t6", type: "supports" },
    { source: "t6", target: "t4", type: "depends" },
    { source: "t9", target: "t8", type: "objects" },
    { source: "t10", target: "t8", type: "objects" },
  ],
  active: "t10",
};

test("議論マップのスクリーンショットを撮る", async ({ page }) => {
  await page.routeWebSocket(/\/ws\/transcript/, (ws) => {
    ws.send(JSON.stringify({ type: "status", data: runningStatus }));
  });
  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/session/status") return route.fulfill({ json: runningStatus });
    if (url.pathname === "/api/topics") return route.fulfill({ json: tree });
    if (url.pathname === "/api/health") return route.fulfill({ json: { status: "ok" } });
    if (url.pathname === "/api/session/entries") return route.fulfill({ json: { entries: [] } });
    if (url.pathname === "/api/speakers") return route.fulfill({ json: { speakers: [] } });
    if (url.pathname === "/api/transcripts") return route.fulfill({ json: { sessions: [] } });
    if (url.pathname === "/api/transcripts/folders") return route.fulfill({ json: { folders: [] } });
    return route.fulfill({ json: {} });
  });

  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "論点", exact: true }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: "test-results/argmap-live.png", fullPage: true });
});
