import { expect, test } from "@playwright/test";

function installTauriMock(page: import("@playwright/test").Page) {
  return page.addInitScript(() => {
    const entries = Array.from({ length: 90 }, (_, index) => ({
      id: `entry-${index}`,
      text: `発話 ${index}`,
      raw_text: `発話 ${index}`,
      speaker_name: "話者A",
      speaker_id: "speaker-a",
      speaker_confidence: 1,
      timestamp_start: index * 10,
      timestamp_end: index * 10 + 5,
      bookmarked: false,
      refined: false,
    }));
    const screenshots = Array.from({ length: 90 }, (_, index) => ({
      filename: `shot-${index}.jpg`,
      relative_seconds: index * 10,
      size_bytes: 1024,
    }));

    (window as any).__historyRequestLog = [];
    (window as any).__historyRequestQueryLog = [];
    (window as any).__historySaveLog = [];
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

    const mock: Record<string, unknown> = {
      "/api/health": { status: "ok" },
      "/api/health/gpu": { available: false },
      "/api/config/status": {
        gemini_api_key_set: false,
        gemini_api_key_masked: null,
        screenshot_enabled: true,
        screenshot_interval: 10,
        screenshot_quality: 80,
      },
      "/api/config/meeting": {
        call_notification_enabled: true,
        screenshot_enabled: true,
        audio_saving_enabled: true,
      },
      "/api/config/screenshots": {
        screenshot_enabled: true,
        screenshot_interval: 10,
        screenshot_quality: 80,
      },
      "/api/devices": {
        devices: [],
        default_mic_index: null,
        default_loopback_index: null,
        default_microphone: null,
        default_loopback: null,
      },
      "/api/model/status": {
        current_model: "kotoba-v2.0",
        is_loaded: false,
        available_models: [],
      },
      "/api/model/loading-status": { stage: "", progress: 0 },
      "/api/summary/models": { current_model: "gemini-2.5-flash", models: [] },
      "/api/speakers": { speakers: [] },
      "/api/call-detection/pending": { calls: [] },
      "/api/session/info": {
        status: "idle",
        session_id: "",
        started_at: null,
        segment_count: 0,
        entry_count: 0,
        elapsed_seconds: 0,
      },
      "/api/session/entries": { entries: [] },
      "/api/transcripts": {
        sessions: [
          {
            session_id: "session-sync",
            session_name: "同期テスト",
            started_at: "2026-05-01T10:00:00",
            saved_at: "2026-05-01T10:20:00",
            entry_count: entries.length,
            screenshot_count: screenshots.length,
            is_favorite: false,
          },
        ],
      },
      "/api/transcripts/session-sync": { session_id: "session-sync", entries },
      "/api/transcripts/session-sync/favorite": { session_id: "session-sync", is_favorite: true },
      "/api/summary/session-sync": { session_id: "session-sync", summary: "## 要点\n本文" },
      "/api/summary/generate": {
        session_id: "session-sync",
        summary: "## 要点\nCodex生成本文",
        usage: {
          model: "codex-cli",
          billing: "codex-subscription",
          fallback_from: "claude-code",
          fallback_detail: "Claude limit reached",
          fallback_chain: ["claude-code"],
          fallback_details: {
            "claude-code": "Claude limit reached",
          },
          fallback_reason: "provider-error",
        },
      },
      "/api/playback/session-sync/audio/info": {
        has_audio: false,
        format: null,
        duration_seconds: null,
        file_size_bytes: null,
      },
      "/api/screenshots/session-sync": { session_id: "session-sync", screenshots },
    };

    const pending: Record<number, { url?: string; body?: number[]; done?: boolean }> = {};
    let rid = 1;

    (window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      invoke: async (cmd: string, args: any) => {
        if (cmd === "plugin:http|fetch") {
          const requestId = rid++;
          pending[requestId] = { url: args?.clientConfig?.url };
          return requestId;
        }
        if (cmd === "plugin:http|fetch_send") {
          const req = pending[args?.rid] || {};
          const url = req.url || "";
          const pathWithQuery = url.replace(/^https?:\/\/[^/]+/, "");
          const path = pathWithQuery.split("?")[0];
          (window as any).__historyRequestLog.push(path);
          (window as any).__historyRequestQueryLog.push(pathWithQuery);
          if (path === "/api/transcripts" && remainingFailures("mock_transcripts_failures") > 0) {
            throw new Error("backend not ready");
          }
          const data = mock[path];
          let status = data ? 200 : 500;
          let body = JSON.stringify(data || { detail: "not found" });
          let contentType = "application/json";
          if (path === "/api/transcripts/session-sync/export") {
            status = 200;
            contentType = "text/plain";
            const format = new URL(url).searchParams.get("format");
            body = format === "action-md" ? "# Meeting Action Brief\n\n本文" : format === "md" ? "# AI用Markdown\n\n本文" : "TXT本文";
          }
          const encoded = Array.from(new TextEncoder().encode(body));
          encoded.push(0);
          const responseId = rid++;
          pending[responseId] = { body: encoded, done: false };
          return {
            status,
            statusText: status === 200 ? "OK" : "Error",
            url,
            headers: [["content-type", contentType]],
            rid: responseId,
          };
        }
        if (cmd === "plugin:http|fetch_read_body") {
          const response = pending[args?.rid];
          if (response && !response.done) {
            response.done = true;
            return response.body || [1];
          }
          return [1];
        }
        if (cmd.startsWith("plugin:http|fetch_cancel")) return null;
        if (cmd === "plugin:dialog|save") {
          const defaultPath = args?.options?.defaultPath || "export.txt";
          (window as any).__historySaveLog.push({ cmd, defaultPath });
          return `C:\\tmp\\${defaultPath}`;
        }
        if (cmd === "plugin:fs|write_text_file") {
          (window as any).__historySaveLog.push({ cmd });
          return null;
        }
        if (cmd === "plugin:notification|is_permission_granted") return true;
        if (cmd === "plugin:notification|notify") return null;
        throw new Error(`Tauri mock: ${cmd}`);
      },
      transformCallback: (cb: any) => {
        const id = Math.random();
        (window as any)[`_${id}`] = cb;
        return id;
      },
      convertFileSrc: (path: string) => path,
    };
  });
}

test.describe("履歴スクリーンショット同期", () => {
  test.beforeEach(async ({ page }) => {
    await installTauriMock(page);
    await page.route("**/api/screenshots/session-sync/*.jpg", async (route) => {
      const label = route.request().url().match(/shot-(\d+)\.jpg/)?.[1] || "";
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><rect width="160" height="90" fill="#1e293b"/><text x="80" y="50" fill="#67e8f9" text-anchor="middle" font-size="18">${label}</text></svg>`,
      });
    });
    await page.setViewportSize({ width: 1000, height: 700 });
    await page.goto("/");
    await page.waitForSelector("text=履歴", { timeout: 15000 });
  });

  test("アプリ起動時に履歴一覧を裏で読み込む", async ({ page }) => {
    await expect
      .poll(async () =>
        page.evaluate(() => (window as any).__historyRequestLog.includes("/api/transcripts")),
      )
      .toBe(true);
  });

  test("起動時の履歴一覧一時接続失敗は再試行して表示する", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_transcripts_failures", "3");
    });
    await page.reload();
    await page.waitForSelector("text=履歴", { timeout: 15000 });

    await page.locator("button", { hasText: "履歴" }).click();

    await expect(page.locator("text=同期テスト")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("text=backend not ready")).toHaveCount(0);
  });

  test("初回リトライ後も履歴一覧が空なら自動再取得して表示する", async ({ page }) => {
    await page.evaluate(() => {
      localStorage.setItem("mock_transcripts_failures", "20");
    });
    await page.reload();
    await page.waitForSelector("text=履歴", { timeout: 15000 });

    await page.locator("button", { hasText: "履歴" }).click();

    await expect(page.locator("text=同期テスト")).toBeVisible({ timeout: 30000 });
  });

  test("チェック列の上下余白クリックは詳細を開かずに行選択を切り替える", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    const row = page.locator("tr", { hasText: "同期テスト" });
    await expect(row).toBeVisible();

    const checkbox = row.locator('input[type="checkbox"]');
    const rowBox = await row.boundingBox();
    const checkboxBox = await checkbox.boundingBox();
    expect(rowBox).not.toBeNull();
    expect(checkboxBox).not.toBeNull();

    const clickX = checkboxBox!.x + checkboxBox!.width / 2;
    await page.mouse.click(clickX, checkboxBox!.y - 8);
    await expect(page.locator("button", { hasText: "1件を削除" })).toBeVisible();
    await expect(page.locator("text=発話 0")).toHaveCount(0);

    await page.mouse.click(clickX, checkboxBox!.y + checkboxBox!.height + 8);
    await expect(page.locator("button", { hasText: "1件を削除" })).toHaveCount(0);
    await expect(page.locator("text=発話 0")).toHaveCount(0);
  });

  test("履歴一覧の文字は明るい背景で読み取れるコントラストを保つ", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();

    const row = page.locator("tr", { hasText: "同期テスト" });
    await expect(row.getByText("同期テスト", { exact: true })).toHaveCSS("color", "rgb(32, 33, 36)");
    await expect(row.getByText("05/01(金)", { exact: true })).toHaveCSS("color", "rgb(32, 33, 36)");
    await expect(row.getByText("10:00-10:20", { exact: true })).toHaveCSS("color", "rgb(102, 102, 109)");
  });

  test("履歴の要約本文は明るい背景で読み取れるコントラストを保つ", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    await page.getByText("同期テスト", { exact: true }).click();
    await page.getByRole("button", { name: "要約", exact: true }).click();

    await expect(page.getByText("本文", { exact: true })).toHaveCSS("color", "rgb(38, 38, 42)");
    await page.getByRole("button", { name: "要約を生成", exact: true }).click();
    await expect(page.getByText("Codex生成本文", { exact: true })).toBeVisible();
    await expect(page.getByText("Codex CLI", { exact: true })).toBeVisible();
    await expect(page.getByText("Codexサブスク枠", { exact: true })).toBeVisible();
    await expect(page.getByText(/Claudeエラー: Claude limit reached/)).toBeVisible();
  });

  test("星列の上下余白クリックは詳細を開かずにお気に入りを切り替える", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    const row = page.locator("tr", { hasText: "同期テスト" });
    await expect(row).toBeVisible();

    const favorite = row.locator("button", { hasText: "☆" });
    const favoriteBox = await favorite.boundingBox();
    expect(favoriteBox).not.toBeNull();

    const clickX = favoriteBox!.x + favoriteBox!.width / 2;
    await page.mouse.click(clickX, favoriteBox!.y - 8);

    await expect
      .poll(async () =>
        page.evaluate(() => (window as any).__historyRequestLog.includes("/api/transcripts/session-sync/favorite")),
      )
      .toBe(true);
    await expect(page.locator("text=発話 0")).toHaveCount(0);
  });

  test("本文をスクロールすると同じ時刻付近のスクリーンショットまで右ペインが追従する", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    await page.locator("text=同期テスト").click();
    await expect(page.locator("text=発話 0")).toBeVisible({ timeout: 15000 });

    const screenshotScroller = page
      .locator("h3", { hasText: "スクリーンショット" })
      .evaluateHandle((heading) => {
        const panel = heading.closest(".flex.flex-col.h-full");
        return panel?.querySelector(".overflow-y-auto");
      });

    const initialScrollTop = await screenshotScroller.then((handle) =>
      handle.evaluate((node) => (node as HTMLElement | null)?.scrollTop ?? -1),
    );
    expect(initialScrollTop).toBeGreaterThanOrEqual(0);

    await page.locator("text=発話 70").scrollIntoViewIfNeeded();
    await expect.poll(async () => {
      const handle = await screenshotScroller;
      return handle.evaluate((node) => (node as HTMLElement | null)?.scrollTop ?? -1);
    }).toBeGreaterThan(initialScrollTop + 300);

    const activeScreenshot = page.locator('button[aria-current="time"]');
    await expect(activeScreenshot).toBeInViewport();
    await expect(activeScreenshot).toContainText(/^11:/);
  });

  test("本文の小さなスクロールにも右ペインが連続して追従する", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    await page.locator("text=同期テスト").click();
    await expect(page.locator("text=発話 0")).toBeVisible({ timeout: 15000 });

    const transcriptScroller = page.locator("text=発話 0").evaluateHandle((entryText) => {
      return entryText.closest(".overflow-y-auto");
    });
    const screenshotScroller = page
      .locator("h3", { hasText: "スクリーンショット" })
      .evaluateHandle((heading) => {
        const panel = heading.closest(".flex.flex-col.h-full");
        return panel?.querySelector(".overflow-y-auto");
      });

    await transcriptScroller.then((handle) =>
      handle.evaluate((node) => {
        const scroller = node as HTMLElement | null;
        if (!scroller) return;
        const entries = Array.from(
          scroller.querySelectorAll<HTMLElement>("[data-transcript-entry-start]"),
        );
        const entry = entries[30];
        if (!entry) return;
        const anchorOffset = Math.min(scroller.clientHeight * 0.35, 160);
        scroller.scrollTop = entry.offsetTop + entry.offsetHeight / 2 - anchorOffset;
        scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
      }),
    );

    await page.waitForTimeout(300);
    const before = await screenshotScroller.then((handle) =>
      handle.evaluate((node) => (node as HTMLElement | null)?.scrollTop ?? -1),
    );
    expect(before).toBeGreaterThan(0);

    await transcriptScroller.then((handle) =>
      handle.evaluate((node) => {
        const scroller = node as HTMLElement | null;
        if (!scroller) return;
        scroller.scrollTop += 4;
        scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
      }),
    );

    await expect
      .poll(async () => {
        const handle = await screenshotScroller;
        return handle.evaluate((node) => (node as HTMLElement | null)?.scrollTop ?? -1);
      })
      .toBeGreaterThan(before + 0.5);
  });

  test("TXTとMDのエクスポートはTauri保存ダイアログ経由でファイルを書き出す", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    await page.locator("text=同期テスト").click();
    await expect(page.locator("text=発話 0")).toBeVisible({ timeout: 15000 });

    await page.getByRole("button", { name: "TXT" }).click();
    await expect
      .poll(async () =>
        page.evaluate(() =>
          (window as any).__historySaveLog
            .filter((item: { cmd: string }) => item.cmd === "plugin:dialog|save")
            .map((item: { defaultPath: string }) => item.defaultPath),
        ),
      )
      .toEqual(["session-sync.txt"]);

    await page.getByRole("button", { name: "MD" }).click();
    await expect
      .poll(async () =>
        page.evaluate(() =>
          (window as any).__historySaveLog
            .filter((item: { cmd: string }) => item.cmd === "plugin:dialog|save")
            .map((item: { defaultPath: string }) => item.defaultPath),
        ),
      )
      .toEqual(["session-sync.txt", "session-sync.md"]);

    await expect
      .poll(async () =>
        page.evaluate(() =>
          (window as any).__historySaveLog.filter(
            (item: { cmd: string }) => item.cmd === "plugin:fs|write_text_file",
          ).length,
        ),
      )
      .toBe(2);
  });

  test("AIアクションは専用Markdownを保存する", async ({ page }) => {
    await page.locator("button", { hasText: "履歴" }).click();
    await page.locator("text=同期テスト").click();
    await expect(page.locator("text=発話 0")).toBeVisible({ timeout: 15000 });

    await page.getByRole("button", { name: "AIアクション" }).click();

    await expect
      .poll(async () =>
        page.evaluate(() =>
          (window as any).__historyRequestQueryLog.includes(
            "/api/transcripts/session-sync/export?format=action-md",
          ),
        ),
      )
      .toBe(true);

    await expect
      .poll(async () =>
        page.evaluate(() =>
          (window as any).__historySaveLog
            .filter((item: { cmd: string }) => item.cmd === "plugin:dialog|save")
            .map((item: { defaultPath: string }) => item.defaultPath),
        ),
      )
      .toEqual(["session-sync-action.md"]);
  });
});
