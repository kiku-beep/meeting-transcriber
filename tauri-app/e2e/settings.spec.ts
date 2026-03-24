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
      "/api/session/info": { status: "idle", session_id: "", started_at: null, segment_count: 0, entry_count: 0, elapsed_seconds: 0 },
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
          _p[rid] = { url: c.url };
          return rid;
        }
        if (cmd === "plugin:http|fetch_send") {
          const req = _p[args?.rid] || {};
          const path = (req.url || "").replace(/^https?:\/\/[^/]+/, "");
          const data = MOCK[path];
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

  test("スクリーンキャプチャの表記が統一されている", async ({ page }) => {
    // 設定タブをクリック
    await page.locator("button", { hasText: "設定" }).click();
    await page.waitForTimeout(1500);

    // 「スクリーンキャプチャ」存在確認
    await expect(page.locator("text=スクリーンキャプチャ").first()).toBeVisible();

    // 「スクリーンショット」が含まれないこと
    const text = await page.locator(".space-y-6").first().innerText();
    expect(text).not.toContain("スクリーンショット");
  });
});
