import { test, expect } from "@playwright/test";

/**
 * Tauri plugin:http mock — emulates the multi-step invoke protocol.
 *
 * plugin:http flow:
 *   invoke('plugin:http|fetch')      → rid
 *   invoke('plugin:http|fetch_send') → { status, headers, rid: responseRid }
 *   invoke('plugin:http|fetch_read_body') → Uint8Array with trailing byte: 0=more, 1=close
 */
function installTauriMock(page: import("@playwright/test").Page) {
  return page.addInitScript(() => {
    const idleSessionStatus = { status: "idle", session_id: "", started_at: null, segment_count: 0, entry_count: 0, elapsed_seconds: 0 };
    const remainingFailures = (key: string) => {
      try {
        const current = Number(localStorage.getItem(key) || "0");
        if (current > 0) {
          localStorage.setItem(key, String(current - 1));
          return current;
        }
      } catch {
        // ignore
      }
      return 0;
    };
    const getMockSessionStatus = () => {
      try {
        const raw = localStorage.getItem("mock_session_status");
        return raw ? JSON.parse(raw) : idleSessionStatus;
      } catch {
        return idleSessionStatus;
      }
    };
    const getMockSessionEntries = () => {
      try {
        const raw = localStorage.getItem("mock_session_entries");
        return raw ? JSON.parse(raw) : { entries: [] };
      } catch {
        return { entries: [] };
      }
    };
    const getMockSpeakers = () => {
      try {
        const raw = localStorage.getItem("mock_speakers");
        return raw ? JSON.parse(raw) : { speakers: [] };
      } catch {
        return { speakers: [] };
      }
    };

    const MOCK: Record<string, unknown> = {
      "/api/health": { status: "ok" },
      "/api/health/gpu": { available: false },
      "/api/config/status": { gemini_api_key_set: false, gemini_api_key_masked: null, screenshot_enabled: true, screenshot_interval: 10, screenshot_quality: 80 },
      "/api/config/meeting": { call_notification_enabled: true, screenshot_enabled: true, audio_saving_enabled: true },
      "/api/config/screenshots": { screenshot_enabled: true, screenshot_interval: 10, screenshot_quality: 80 },
      "/api/devices": { devices: [], default_mic_index: null, default_loopback_index: null, default_microphone: null, default_loopback: null },
      "/api/model/status": { current_model: "large-v3", is_loaded: false, available_models: [] },
      "/api/model/loading-status": { stage: "", progress: 0 },
      "/api/summary/models": { current_model: "gemini-2.5-flash", models: [] },
      "/api/speakers": { speakers: [] },
      "/api/call-detection/pending": { calls: [] },
      "/api/session/info": idleSessionStatus,
      "/api/session/start": { status: "running", session_id: "mock-session", started_at: "2026-06-12T11:00:00", segment_count: 0, entry_count: 0, elapsed_seconds: 0 },
      "/api/session/entries": { entries: [] },
    };

    const _p: Record<number, any> = {};
    let _r = 1;

    (window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (cmd: string, args: any) => {
        if (cmd === "plugin:http|fetch") {
          const rid = _r++;
          const c = args?.clientConfig || {};
          _p[rid] = { url: c.url, method: c.method, data: c.data };
          return rid;
        }
        if (cmd === "plugin:http|fetch_send") {
          const req = _p[args?.rid] || {};
          const path = (req.url || "").replace(/^https?:\/\/[^/]+/, "").split("?")[0];
          if (path === "/api/health" && remainingFailures("mock_health_failures") > 0) {
            throw new Error("backend not ready");
          }
          if (path === "/api/session/start" && remainingFailures("mock_start_failures") > 0) {
            throw new Error("backend not ready");
          }
          if (path === "/api/speakers" && remainingFailures("mock_speakers_failures") > 0) {
            throw new Error("backend not ready");
          }
          let data: unknown;
          if (path === "/api/session/status") {
            data = getMockSessionStatus();
          } else if (path === "/api/session/entries") {
            data = getMockSessionEntries();
          } else if (path === "/api/speakers") {
            data = getMockSpeakers();
          } else if (req.method === "PUT" && /^\/api\/speakers\/[^/]+$/.test(path)) {
            const speakerId = path.split("/").pop();
            const body = JSON.parse(new TextDecoder().decode(new Uint8Array(req.data || [])));
            const current = getMockSpeakers();
            const speakers = current.speakers.map((speaker: Record<string, unknown>) => (
              speaker.id === speakerId ? { ...speaker, name: body.name } : speaker
            ));
            localStorage.setItem("mock_speakers", JSON.stringify({ speakers }));
            data = { speaker: speakers.find((speaker: Record<string, unknown>) => speaker.id === speakerId) };
          } else {
            data = MOCK[path];
          }
          const bytes = Array.from(new TextEncoder().encode(JSON.stringify(data || { detail: "not found" })));
          bytes.push(0); // continuation byte
          const rrid = _r++;
          _p[rrid] = { b: bytes, done: false };
          return { status: data ? 200 : 500, statusText: data ? "OK" : "Error", url: req.url, headers: [["content-type", "application/json"]], rid: rrid };
        }
        if (cmd === "plugin:http|fetch_read_body") {
          const e = _p[args?.rid];
          if (e && !e.done) { e.done = true; return e.b || [1]; }
          return [1]; // close signal
        }
        if (cmd.startsWith("plugin:http|fetch_cancel")) return null;
        if (cmd === "plugin:notification|is_permission_granted") return true;
        if (cmd === "plugin:notification|notify") return null;
        throw new Error("Tauri mock: " + cmd);
      },
      transformCallback: (cb: any) => { const id = Math.random(); (window as any)["_" + id] = cb; return id; },
      convertFileSrc: (p: string) => p,
    };
  });
}

test.describe("会議設定機能", () => {
  test.beforeEach(async ({ page }) => {
    await installTauriMock(page);
    await page.goto("/");
    // Wait for BackendLoader to pass
    await page.waitForSelector("text=設定", { timeout: 15000 });
  });

  test("会議設定セクションに2つのトグルが表示される", async ({ page }) => {
    // 設定タブをクリック
    await page.locator("button", { hasText: "設定" }).click();
    await page.waitForTimeout(1500);

    // 「会議設定」セクション見出し
    const heading = page.locator("h3", { hasText: "会議設定" });
    await expect(heading).toBeVisible();

    // 2つのトグルボタン（screenshot_enabledはスクリーンキャプチャ設定セクションに集約）
    const section = page.locator("section", { has: heading });
    await expect(section.locator("button.rounded-full")).toHaveCount(2);

    // ラベル確認
    await expect(section.locator("text=ポップアップ通知")).toBeVisible();
    await expect(section.locator("text=音声ファイル保存")).toBeVisible();
  });

  test("録音開始ボタンがcircular structureエラーなく動作する", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    // デフォルト録音ボタンをクリック
    const btn = page.locator("button", { hasText: "録音開始" }).first();
    await expect(btn).toBeVisible();
    await btn.click();
    await page.waitForTimeout(2000);

    // circular structure エラーがないこと
    const circular = errors.filter((e) => e.includes("circular"));
    expect(circular).toEqual([]);
  });

  test("バックエンドが録音中なら開始ボタンを出さず停止操作を表示する", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_session_status", JSON.stringify({
        status: "running",
        session_id: "running-session",
        started_at: "2026-06-11T09:00:00",
        segment_count: 3,
        entry_count: 12,
        elapsed_seconds: 45,
      }));
    });

    await expect(page.getByRole("button", { name: "停止", exact: true })).toBeVisible({ timeout: 6000 });
    await expect(page.locator("button", { hasText: "録音開始" })).toHaveCount(0);
  });

  test("WebSocketで取り逃した文字起こしをREST同期で表示する", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_session_status", JSON.stringify({
        status: "running",
        session_id: "mock-session",
        started_at: "2026-06-12T11:00:00",
        segment_count: 1,
        entry_count: 1,
        elapsed_seconds: 8,
      }));
      localStorage.setItem("mock_session_entries", JSON.stringify({
        entries: [{
          id: "entry-rest-sync",
          text: "REST同期で表示された文字起こし",
          raw_text: "REST同期で表示された文字起こし",
          speaker_name: "菊地",
          speaker_id: "speaker-kiku",
          speaker_confidence: 0.9,
          timestamp_start: 1,
          timestamp_end: 4,
          refined: false,
        }],
      }));
    });

    await page.reload();
    await page.waitForSelector("text=設定", { timeout: 15000 });

    await expect(page.locator("text=REST同期で表示された文字起こし")).toBeVisible({ timeout: 6000 });
  });

  test("起動直後の一時的な接続失敗では録音開始前にヘルスチェックを待つ", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_health_failures", "2");
    });

    const btn = page.locator("button", { hasText: "録音開始" }).first();
    await expect(btn).toBeVisible();
    await btn.click();
    await page.waitForTimeout(500);

    await expect(page.locator("text=backend not ready")).toHaveCount(0);
  });

  test("スクリーンキャプチャの表記が統一されている", async ({ page }) => {
    // 設定タブをクリック
    await page.locator("button", { hasText: "設定" }).click();
    await page.waitForTimeout(1500);

    // 「スクリーンキャプチャ」存在確認
    await expect(page.locator("text=スクリーンキャプチャ").first()).toBeVisible();

    // 「スクリーンショット」が含まれないこと
    const text = await page.locator(".settings-page").innerText();
    expect(text).not.toContain("スクリーンショット");
  });
});

test.describe("話者管理", () => {
  test.beforeEach(async ({ page }) => {
    await installTauriMock(page);
    await page.goto("/");
    await page.waitForSelector("text=設定", { timeout: 15000 });
  });

  test("一時的な一覧取得失敗から自動で復旧する", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_speakers_failures", "4");
      localStorage.setItem("mock_speakers", JSON.stringify({
        speakers: [{
          id: "speaker-mayu",
          speaker_id: "speaker-mayu",
          name: "Mayu",
          sample_count: 15,
          has_embedding: true,
          created_at: "2026-07-24T10:02:33",
        }],
      }));
    });
    await page.reload();
    await page.waitForSelector("text=設定", { timeout: 15000 });

    await page.getByRole("button", { name: "話者", exact: true }).click();

    await expect(page.getByRole("alert")).toContainText("backend not ready", { timeout: 5000 });
    await expect(page.getByText("Mayu", { exact: true })).toBeVisible({ timeout: 7000 });
    await expect(page.getByRole("alert")).toHaveCount(0);
  });

  test("登録済み話者を明示ボタンから改名できる", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_speakers", JSON.stringify({
        speakers: [{
          id: "speaker-mayu",
          speaker_id: "speaker-mayu",
          name: "Mayu",
          sample_count: 15,
          has_embedding: true,
          created_at: "2026-07-24T10:02:33",
        }],
      }));
    });
    await page.reload();
    await page.waitForSelector("text=設定", { timeout: 15000 });

    await page.getByRole("button", { name: "話者", exact: true }).click();
    await expect(page.getByText("Mayu", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Mayuの名前を変更" }).click();
    const input = page.getByLabel("Mayuの新しい名前");
    await input.fill("まゆ");
    await page.getByRole("button", { name: "保存" }).click();

    await expect(page.getByText("まゆ", { exact: true })).toBeVisible();
    await expect(page.getByText("サンプル: 15個", { exact: true })).toBeVisible();
  });
});
