import { test, expect } from "@playwright/test";

test.describe("Live AI panel", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("http://127.0.0.1:8000/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === "/api/health") {
        return route.fulfill({ json: { status: "ok" } });
      }
      if (url.pathname === "/api/session/status") {
        return route.fulfill({ json: {
          status: "running",
          session_id: "live-test",
          started_at: new Date().toISOString(),
          segment_count: 2,
          entry_count: 2,
          elapsed_seconds: 120,
          mic_device: "Test mic",
          loopback_device: "Test loopback",
        }});
      }
      if (url.pathname === "/api/session/entries") {
        return route.fulfill({ json: { entries: [
          { id: "1", text: "進捗を確認します", raw_text: "進捗を確認します", speaker_name: "話者A", speaker_id: "a", speaker_confidence: 1, timestamp_start: 0, timestamp_end: 2 },
          { id: "2", text: "次回は火曜日です", raw_text: "次回は火曜日です", speaker_name: "話者B", speaker_id: "b", speaker_confidence: 1, timestamp_start: 60, timestamp_end: 62 },
        ] }});
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
      if (url.pathname === "/api/summary/live") {
        return route.fulfill({ json: {
          content: "## ここまでの要点\n進捗を確認した。",
          mode: "summary",
          range_minutes: 15,
          range_start_seconds: 0,
          range_end_seconds: 62,
          generated_at: new Date().toISOString(),
          entry_count: 2,
          usage: {
            model: "gemini-test",
            billing: "api",
            fallback_from: "claude-code",
            fallback_reason: "claude-error",
            fallback_detail: "Claude Code CLI failed",
          },
        }});
      }
      return route.fulfill({ json: {} });
    });
    await page.goto("/");
    await expect(page.getByRole("button", { name: "AIアシスト" })).toBeVisible();
    await expect(page.getByText("Transcriber", { exact: true })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "会議AI" })).toBeVisible();
  });

  test("opens the panel and submits a ranged summary", async ({ page }) => {
    let requestBody: Record<string, unknown> | null = null;
    await page.route("http://127.0.0.1:8000/api/summary/live", async (route) => {
      requestBody = route.request().postDataJSON();
      await route.fulfill({ json: {
        content: "## ここまでの要点\n進捗を確認した。",
        mode: "summary",
        range_minutes: 15,
        range_start_seconds: 0,
        range_end_seconds: 62,
        generated_at: new Date().toISOString(),
        entry_count: 2,
        usage: {
          model: "gemini-test",
          billing: "api",
          fallback_from: "claude-code",
          fallback_reason: "claude-error",
          fallback_detail: "Claude Code CLI failed",
        },
      }});
    });

    await expect(page.locator(".app-shell")).toHaveCSS("background-color", "rgb(247, 247, 248)");
    await expect(page.locator(".recording-bar")).toBeVisible();
    await expect(page.locator(".transcript-entry").first()).toHaveCSS("display", "grid");
    await page.getByLabel("対象範囲").selectOption("15");
    await page.getByRole("button", { name: "現在までを要約" }).click();

    await expect(page.getByText("進捗を確認した。")).toBeVisible();
    await expect(page.getByText(/Claude Code CLI failed/)).toBeVisible();
    expect(requestBody).toMatchObject({ mode: "summary", range_minutes: 15 });
  });

  test("shows Codex subscription usage for an interim summary", async ({ page }) => {
    await page.route("http://127.0.0.1:8000/api/summary/live", route =>
      route.fulfill({ json: {
        content: "## ここまでの要点\nCodexで要約した。",
        mode: "summary",
        range_minutes: 15,
        range_start_seconds: 0,
        range_end_seconds: 62,
        generated_at: new Date().toISOString(),
        entry_count: 2,
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
      }})
    );

    await page.getByRole("button", { name: "現在までを要約" }).click();

    await expect(page.getByText("Codex CLI", { exact: true })).toBeVisible();
    await expect(page.getByText("Codexサブスク枠", { exact: true })).toBeVisible();
    await expect(page.getByText(/Claudeエラー: Claude limit reached/)).toBeVisible();
  });

  test("shows both failures after a two-step fallback to Gemini", async ({ page }) => {
    await page.route("http://127.0.0.1:8000/api/summary/live", route =>
      route.fulfill({ json: {
        content: "## ここまでの要点\nGeminiで要約した。",
        mode: "summary",
        range_minutes: 15,
        range_start_seconds: 0,
        range_end_seconds: 62,
        generated_at: new Date().toISOString(),
        entry_count: 2,
        usage: {
          model: "gemini-test",
          billing: "api",
          fallback_from: "codex-cli",
          fallback_detail: "Codex limit reached",
          fallback_chain: ["claude-code", "codex-cli"],
          fallback_details: {
            "claude-code": "Claude limit reached",
            "codex-cli": "Codex limit reached",
          },
          fallback_reason: "provider-error",
        },
      }})
    );

    await page.getByRole("button", { name: "現在までを要約" }).click();

    await expect(page.getByText("Gemini", { exact: true })).toBeVisible();
    await expect(page.getByText(/Claudeエラー: Claude limit reached/)).toBeVisible();
    await expect(page.getByText(/Codexエラー: Codex limit reached/)).toBeVisible();
  });

  test("uses compact transcript rows", async ({ page }) => {
    const row = page.locator(".transcript-entry").first();
    const metrics = await row.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        minHeight: Number.parseFloat(style.minHeight),
        paddingTop: Number.parseFloat(style.paddingTop),
        paddingBottom: Number.parseFloat(style.paddingBottom),
      };
    });

    expect(metrics.minHeight).toBeLessThanOrEqual(50);
    expect(metrics.paddingTop).toBeLessThanOrEqual(9);
    expect(metrics.paddingBottom).toBeLessThanOrEqual(8);
  });

  test("allows naming a running session and saves the name when stopped", async ({ page }) => {
    let renamedSession: { sessionId: string; sessionName: string } | null = null;

    await page.route("http://127.0.0.1:8000/api/session/stop**", route =>
      route.fulfill({ json: { status: "idle", session_id: "live-test" } })
    );
    await page.route("http://127.0.0.1:8000/api/transcripts/*/name", async (route) => {
      const url = new URL(route.request().url());
      const body = route.request().postDataJSON() as { session_name: string };
      renamedSession = {
        sessionId: url.pathname.split("/").at(-2) ?? "",
        sessionName: body.session_name,
      };
      await route.fulfill({ json: { session_id: renamedSession.sessionId, session_name: body.session_name } });
    });

    const sessionName = page.getByPlaceholder("セッション名（省略可）");
    await expect(sessionName).toBeEnabled();
    await sessionName.fill("録音中に入力した会議名");
    await page.getByRole("button", { name: "停止", exact: true }).click();

    await expect.poll(() => renamedSession).toEqual({
      sessionId: "live-test",
      sessionName: "録音中に入力した会議名",
    });
  });

  test("shows call detection with readable semantic colors", async ({ page }) => {
    await page.evaluate(() => {
      const banner = document.createElement("div");
      banner.className = "call-notification";
      banner.innerHTML = '<div class="call-notification__title">Google Meet を検出しました</div>';
      document.body.appendChild(banner);
    });
    const banner = page.locator(".call-notification");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveCSS("background-color", "rgb(237, 247, 246)");
    await expect(banner.locator(".call-notification__title")).toHaveCSS("color", "rgb(23, 63, 61)");
  });

  test("keeps the question after a failed request", async ({ page }) => {
    await page.getByRole("tab", { name: "質問" }).click();
    await page.getByLabel("会議への質問").fill("次回はいつ？");
    await page.route("http://127.0.0.1:8000/api/summary/live", route =>
      route.fulfill({ status: 500, json: { detail: "AI failed" } })
    );
    await page.getByRole("button", { name: "質問する" }).click();

    await expect(page.getByLabel("会議への質問")).toHaveValue("次回はいつ？");
    await expect(page.getByText("AI failed")).toBeVisible();
  });

  test("can discard a running recording without saving", async ({ page }) => {
    let discarded = false;
    await page.route("http://127.0.0.1:8000/api/session/discard**", async (route) => {
      discarded = true;
      await route.fulfill({ json: { status: "idle" } });
    });
    page.once("dialog", (dialog) => dialog.accept());

    await page.getByRole("button", { name: "録音を破棄" }).click();

    await expect.poll(() => discarded).toBe(true);
  });

  test("speaker management retries a transient backend failure", async ({ page }) => {
    let attempts = 0;
    await page.route("http://127.0.0.1:8000/api/speakers", async (route) => {
      attempts += 1;
      if (attempts <= 3) {
        await route.fulfill({ status: 503, json: { detail: "restarting" } });
        return;
      }
      await route.fulfill({ json: { speakers: [
        { id: "speaker-1", name: "長岡", sample_count: 2, has_embedding: true },
      ] } });
    });

    await page.reload();
    await expect(page.getByText("話者A", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "話者" }).click();

    await expect(page.getByText("長岡", { exact: true })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(attempts).toBeGreaterThanOrEqual(2);
  });

  test("speaker list requests are shared across mounted screens", async ({ page }) => {
    let requests = 0;
    await page.route("http://127.0.0.1:8000/api/speakers", async (route) => {
      requests += 1;
      await route.fulfill({ json: { speakers: [
        { id: "speaker-1", name: "長岡", sample_count: 2, has_embedding: true },
      ] } });
    });

    await page.reload();
    await expect(page.getByText("話者A", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "話者" }).click();
    await expect(page.getByText("長岡", { exact: true })).toBeVisible();

    expect(requests).toBe(1);
  });

  test("speaker list does not retry permanent client errors", async ({ page }) => {
    let attempts = 0;
    await page.route("http://127.0.0.1:8000/api/speakers", async (route) => {
      attempts += 1;
      await route.fulfill({ status: 401, json: { detail: "invalid token" } });
    });

    await page.reload();
    await page.waitForTimeout(2_000);

    expect(attempts).toBe(1);
  });

  test("speaker menu does not expose color customization", async ({ page }) => {
    await page.getByText("話者A", { exact: true }).click();

    await expect(page.getByText("色を変更...", { exact: true })).toHaveCount(0);
  });
});
