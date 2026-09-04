import { test, expect } from "@playwright/test";

type TopicNode = {
  id: string;
  parent: string | null;
  label: string;
  detail?: string;
  status: "open" | "decided" | "parked";
  start_sec: number;
  end_sec: number;
};

type TopicTree = { nodes: TopicNode[]; active: string | null };

const runningStatus = {
  status: "running",
  session_id: "live-topics",
  started_at: "2026-09-02T10:00:00Z",
  segment_count: 2,
  entry_count: 2,
  elapsed_seconds: 120,
};

const initialTree: TopicTree = {
  nodes: [
    { id: "root", parent: null, label: "プロジェクト計画", detail: "予算と人員のどちらを優先するか。責任者が決まれば決着します。", status: "open", start_sec: 0, end_sec: 60 },
    { id: "child", parent: "root", label: "納期を決める", status: "decided", start_sec: 30, end_sec: 55 },
    { id: "parked", parent: "root", label: "保留事項", status: "parked", start_sec: 70, end_sec: 75 },
  ],
  active: "child",
};

async function installApiRoutes(page: import("@playwright/test").Page, options?: {
  tree?: TopicTree;
  status?: typeof runningStatus;
}) {
  let tree = options?.tree ?? initialTree;
  let refreshStatus = 200;
  let refreshRequests = 0;

  // page.route はWebSocketを傍受しない。127.0.0.1:8000 に本物のbackendが
  // 起動していると、WSが status:"idle" を push してモックしたRESTの状態を
  // 上書きし、テストがマシンの状態次第で落ちる。WSも必ず握る。
  await page.routeWebSocket(/\/ws\/transcript/, (ws) => {
    ws.send(JSON.stringify({ type: "status", data: options?.status ?? runningStatus }));
  });

  await page.route("http://127.0.0.1:8000/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/health") {
      return route.fulfill({ json: { status: "ok" } });
    }
    if (url.pathname === "/api/session/status") {
      return route.fulfill({ json: options?.status ?? runningStatus });
    }
    if (url.pathname === "/api/session/entries") {
      return route.fulfill({ json: { entries: [] } });
    }
    if (url.pathname === "/api/speakers") {
      return route.fulfill({ json: { speakers: [] } });
    }
    if (url.pathname === "/api/transcripts") {
      return route.fulfill({ json: { sessions: [] } });
    }
    if (url.pathname === "/api/transcripts/folders") {
      return route.fulfill({ json: { folders: [] } });
    }
    if (url.pathname === "/api/topics" && route.request().method() === "GET") {
      return route.fulfill({ json: tree });
    }
    if (url.pathname === "/api/topics/refresh") {
      refreshRequests += 1;
      if (refreshStatus !== 200) {
        return route.fulfill({ status: refreshStatus, json: { detail: "論点ツリー更新を実行中です" } });
      }
      tree = {
        ...tree,
        nodes: [...tree.nodes, {
          id: "refreshed",
          parent: null,
          label: "更新された論点",
          status: "open",
          start_sec: 100,
          end_sec: 110,
        }],
      };
      return route.fulfill({ json: { updated: true, status: "updated", tree } });
    }
    return route.fulfill({ json: {} });
  });

  return {
    setRefreshStatus: (status: number) => { refreshStatus = status; },
    getRefreshRequests: () => refreshRequests,
  };
}

test.describe("論点ツリー", () => {
  test("初期ツリーを取得し、親子・active・statusを描画する", async ({ page }) => {
    await installApiRoutes(page);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "論点", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "論点", exact: true }).click();

    await expect(page.getByText("プロジェクト計画", { exact: true })).toBeVisible();
    await expect(page.getByText("納期を決める", { exact: true })).toBeVisible();
    await expect(page.getByText("保留事項", { exact: true })).toBeVisible();
    await expect(page.locator("[data-topic-node-id='root'] [data-topic-node-id='child']")).toHaveCount(1);
    await expect(page.locator("[data-topic-node-id='child']")).toHaveClass(/topic-node--active/);
    await expect(page.getByText("未決", { exact: true })).toBeVisible();
    await expect(page.getByText("決定", { exact: true })).toBeVisible();
    await expect(page.getByText("保留", { exact: true })).toBeVisible();
  });

  test("四角をクリックすると詳細が出る", async ({ page }) => {
    await installApiRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();

    const panel = page.getByRole("complementary", { name: "論点の詳細" });
    await page.getByText("プロジェクト計画", { exact: true }).click();
    await expect(panel).toBeVisible();
    await expect(panel.getByText("予算と人員のどちらを優先するか。責任者が決まれば決着します。", { exact: true })).toBeVisible();

    await page.getByText("納期を決める", { exact: true }).click();
    await expect(panel.getByText("決定の理由をまだ抽出できていません。", { exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "閉じる", exact: true }).click();
    await expect(panel).toBeHidden();
  });

  test("録音中の空ツリーは抽出中と表示する", async ({ page }) => {
    await installApiRoutes(page, { tree: { nodes: [], active: null } });
    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();

    await expect(page.getByText("論点を抽出中…", { exact: true })).toBeVisible();
  });

  test("録音していない空ツリーは開始案内を表示する", async ({ page }) => {
    await installApiRoutes(page, {
      tree: { nodes: [], active: null },
      status: { ...runningStatus, status: "idle", session_id: "" },
    });
    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();

    await expect(page.getByText("録音を開始すると論点が表示されます", { exact: true })).toBeVisible();
  });

  test("更新ボタンを押すとrefresh APIを呼び、409は実行中表示にする", async ({ page }) => {
    const api = await installApiRoutes(page);
    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();
    await page.getByRole("button", { name: "更新", exact: true }).click();

    await expect(page.getByText("更新された論点", { exact: true })).toBeVisible();
    expect(api.getRefreshRequests()).toBe(1);

    api.setRefreshStatus(409);
    await page.getByRole("button", { name: "更新", exact: true }).click();
    await expect(page.getByText("他で実行中", { exact: true })).toBeVisible();
  });

  test("循環参照を含むツリーでもページが生きている", async ({ page }) => {
    await installApiRoutes(page, {
      tree: {
        nodes: [
          { id: "cycle-a", parent: "cycle-b", label: "循環A", status: "open", start_sec: 0, end_sec: 1 },
          { id: "cycle-b", parent: "cycle-a", label: "循環B", status: "parked", start_sec: 1, end_sec: 2 },
        ],
        active: "cycle-a",
      },
    });
    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();

    await expect(page.getByText("循環A", { exact: true })).toBeVisible();
    await expect(page.getByText("循環B", { exact: true })).toBeVisible();
    await expect(page.getByText("循環を検出しました", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "論点", exact: true })).toBeVisible();
  });

  // WSのtopic配信が止まっても図が進むこと。以前はWSだけが更新経路で、
  // セッション取り違え1か所で「手動で更新を押すまで変わらない」に落ちた。
  test("更新を押さなくても録音中は図が進む", async ({ page }) => {
    // StrictModeの二重マウントで初回GETは複数回走る。呼び出し回数で切り替えると
    // 最初から新ラベルを返してしまうため、経過時間で切り替える。
    const startedAt = Date.now();
    const SWITCH_AFTER_MS = 5_000;
    // WSは接続するがtopicは一切流さない（配信が壊れた状況を再現する）。
    await page.routeWebSocket(/\/ws\/transcript/, (ws) => {
      ws.send(JSON.stringify({ type: "status", data: runningStatus }));
    });
    await page.route("http://127.0.0.1:8000/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/health") return route.fulfill({ json: { status: "ok" } });
      if (url.pathname === "/api/session/status") return route.fulfill({ json: runningStatus });
      if (url.pathname === "/api/session/entries") return route.fulfill({ json: { entries: [] } });
      if (url.pathname === "/api/speakers") return route.fulfill({ json: { speakers: [] } });
      if (url.pathname === "/api/transcripts") return route.fulfill({ json: { sessions: [] } });
      if (url.pathname === "/api/transcripts/folders") return route.fulfill({ json: { folders: [] } });
      if (url.pathname === "/api/topics" && route.request().method() === "GET") {
        const label = Date.now() - startedAt < SWITCH_AFTER_MS ? "最初の論点" : "あとから出た論点";
        return route.fulfill({
          json: {
            nodes: [{ id: "t1", parent: null, kind: "question", label, status: "open", start_sec: 0, end_sec: 5 }],
            links: [],
            active: "t1",
          },
        });
      }
      return route.fulfill({ json: {} });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "論点", exact: true }).click();
    await expect(page.getByText("最初の論点", { exact: true })).toBeVisible();

    // 更新ボタンには触れない。ポーリングだけで置き換わること。
    await expect(page.getByText("あとから出た論点", { exact: true })).toBeVisible({ timeout: 20_000 });
  });
});
