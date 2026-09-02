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
    const loader = page.getByTestId("backend-loader");
    await expect(loader).toBeVisible();
    await expect(loader).toHaveCSS("background-color", "rgb(247, 247, 248)");
  });

  test("接続中メッセージが表示される", async ({ page }) => {
    await expect(page.getByRole("status")).toContainText("バックエンドに接続しています");
  });

  test("接続設定は必要なときだけ展開できる", async ({ page }) => {
    await expect(page.getByLabel("バックエンドURL")).not.toBeVisible();
    await page.getByText("接続設定", { exact: true }).click();
    await expect(page.getByLabel("バックエンドURL")).toBeVisible();
    await expect(page.getByRole("button", { name: "接続", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "接続せずに開く" })).toBeVisible();
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
