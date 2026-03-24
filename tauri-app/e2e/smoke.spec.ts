import { test, expect } from "@playwright/test";

// Tauri API モック — Vite dev server 単体で動かすために __TAURI_INTERNALS__ をスタブ化
const TAURI_MOCK_SCRIPT = `
  if (!window.__TAURI_INTERNALS__) {
    window.__TAURI_INTERNALS__ = {
      metadata: {
        currentWindow: { label: 'main' },
        currentWebview: { label: 'main' },
      },
      invoke: (cmd, args) => {
        return new Promise((_, reject) => reject(new Error('Tauri mock: ' + cmd)));
      },
      transformCallback: (cb) => {
        const id = Math.random();
        window['_' + id] = cb;
        return id;
      },
      convertFileSrc: (path) => path,
    };
  }
`;

test.describe("Smoke Tests", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(TAURI_MOCK_SCRIPT);
  });

  test("page loads without console errors", async ({ page }) => {
    const errors: string[] = [];

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        errors.push(msg.text());
      }
    });

    page.on("pageerror", (err) => {
      errors.push(err.message);
    });

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Tauri mock 経由のエラーと既知の無害エラーをフィルタ
    const realErrors = errors.filter(
      (e) =>
        !e.includes("Tauri mock:") &&
        !e.includes("__TAURI__") &&
        !e.includes("__TAURI_INTERNALS__") &&
        !e.includes("Could not resolve") &&
        !e.includes("Failed to fetch") &&
        !e.includes("ipc://localhost") &&
        !e.includes("tauri") &&
        !e.includes("Tauri") &&
        !e.includes("Network error") &&
        !e.includes("127.0.0.1:8000")
    );

    expect(realErrors).toEqual([]);
  });

  test("root element renders content", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2000);

    const root = page.locator("#root");
    await expect(root).not.toBeEmpty();

    const text = await page.locator("body").innerText();
    expect(text.trim().length).toBeGreaterThan(0);
  });
});
