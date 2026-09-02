import { test, expect } from "@playwright/test";

test.describe("ライトテーマの意味色", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("#root")).toBeVisible();
    await page.evaluate(() => {
      const fixture = document.createElement("div");
      fixture.id = "ui-color-fixture";
      fixture.innerHTML = `
        <div class="app-statusbar">
          <span class="app-statusbar__connection status-connected">接続</span>
        </div>
        <div class="history-header">履歴</div>
        <div data-testid="color-test-player-bar" class="player-bar">再生</div>
        <div class="inline-alert inline-alert--error">エラー</div>
        <div class="inline-alert inline-alert--warning">警告</div>
        <button class="entry-speaker__suggestion">候補</button>
        <div class="transcript-surface">
          <span data-testid="selection-text">選択対象の文字起こし</span>
          <textarea data-testid="selection-editor" class="entry-editor__input">編集中の文字起こし</textarea>
        </div>
      `;
      document.body.appendChild(fixture);
    });
  });

  test("StatusBarの3状態が別の意味色になる", async ({ page }) => {
    const connection = page.locator("#ui-color-fixture .app-statusbar__connection");
    await expect(connection).toHaveCSS("color", "rgb(15, 107, 104)");

    await connection.evaluate((node) => {
      node.className = "app-statusbar__connection status-reconnecting";
    });
    await expect(connection).toHaveCSS("color", "rgb(161, 92, 0)");

    await connection.evaluate((node) => {
      node.className = "app-statusbar__connection status-disconnected";
    });
    await expect(connection).toHaveCSS("color", "rgb(223, 77, 11)");
  });

  test("履歴ヘッダーと再生バーがライト面になる", async ({ page }) => {
    await expect(page.locator("#ui-color-fixture .history-header"))
      .toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(page.getByTestId("color-test-player-bar"))
      .toHaveCSS("background-color", "rgb(255, 255, 255)");
  });

  test("エラー・警告・話者候補が読みやすい意味色になる", async ({ page }) => {
    const fixture = page.locator("#ui-color-fixture");
    await expect(fixture.locator(".inline-alert--error"))
      .toHaveCSS("color", "rgb(166, 36, 36)");
    await expect(fixture.locator(".inline-alert--warning"))
      .toHaveCSS("color", "rgb(111, 71, 0)");
    await expect(fixture.locator(".entry-speaker__suggestion"))
      .toHaveCSS("color", "rgb(15, 107, 104)");
  });

  test("文字選択と編集フォーカスがライトテーマの選択色になる", async ({ page }) => {
    const text = page.getByTestId("selection-text");
    const editor = page.getByTestId("selection-editor");

    const textSelection = await text.evaluate((node) => {
      const style = getComputedStyle(node, "::selection");
      return { backgroundColor: style.backgroundColor, color: style.color };
    });
    expect(textSelection).toEqual({
      backgroundColor: "rgb(216, 238, 235)",
      color: "rgb(23, 63, 61)",
    });

    await expect(editor).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(editor).toHaveCSS("color", "rgb(31, 37, 38)");
    await expect(editor).toHaveCSS("caret-color", "rgb(15, 107, 104)");
    await editor.focus();
    await expect(editor).toHaveCSS("border-color", "rgb(15, 107, 104)");
    await expect(editor).toHaveCSS("outline-color", "rgb(156, 203, 197)");
    await expect(editor).toHaveCSS("outline-width", "2px");

    const editorSelection = await editor.evaluate((node) => {
      const style = getComputedStyle(node, "::selection");
      return { backgroundColor: style.backgroundColor, color: style.color };
    });
    expect(editorSelection).toEqual(textSelection);
  });
});
