import { test, expect } from "@playwright/test";

// Tauri API モック（smoke.spec.ts と同じものを使う）
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

test.describe("Interaction Tests", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(TAURI_MOCK_SCRIPT);
    await page.goto("/");
    await page.waitForTimeout(2000);
  });

  test("BackendLoaderが表示される", async ({ page }) => {
    // バックエンド未起動時、BackendLoaderが表示されるはず
    const title = page.locator("text=Transcriber");
    await expect(title).toBeVisible();
  });

  test("ローディングメッセージが表示される", async ({ page }) => {
    const loading = page.locator("text=バックエンド起動中");
    await expect(loading).toBeVisible();
  });

  test("ローディングインジケーターが存在する", async ({ page }) => {
    // プログレスバーのアニメーション要素
    const indicator = page.locator(".animate-pulse");
    await expect(indicator).toBeVisible();
  });

  test("BackendLoaderにクラッシュなし", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => {
      errors.push(err.message);
    });

    // 5秒間待機してクラッシュがないことを確認
    await page.waitForTimeout(5000);

    const realErrors = errors.filter(
      (e) =>
        !e.includes("Tauri mock:") &&
        !e.includes("tauri") &&
        !e.includes("Tauri") &&
        !e.includes("Network error") &&
        !e.includes("127.0.0.1:8000")
    );

    expect(realErrors).toEqual([]);
  });
});
