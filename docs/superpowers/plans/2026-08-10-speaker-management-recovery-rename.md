# Speaker Management Recovery And Rename Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development (if subagents available) or executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 話者管理画面を接続失敗から自動復旧させ、登録プロフィール名を明示的に変更できるようにする。

**Architecture:** 既存の話者PUT APIとインライン編集状態を再利用する。取得APIの負のキャッシュを除去し、画面コンポーネントが失敗時だけ再取得を予約する。過去履歴や話者埋め込みは変更しない。

**Tech Stack:** React 19, TypeScript, Tauri HTTP plugin, Playwright

---

### Task 1: 話者一覧の復旧テスト

**Files:**
- Modify: `tauri-app/e2e/settings.spec.ts`
- Modify: `tauri-app/src/lib/apiSpeakers.ts`
- Modify: `tauri-app/src/components/Speakers.tsx`

- [ ] 一時的に`GET /api/speakers`が失敗し、その後成功するE2Eテストを追加する。
- [ ] テストを実行し、自動復旧が未実装のため失敗することを確認する。
- [ ] 失敗キャッシュを除去し、失敗時の自動再取得と手動再読み込みを実装する。
- [ ] 対象テストを再実行して成功を確認する。

### Task 2: 明示的な名前変更操作

**Files:**
- Modify: `tauri-app/e2e/settings.spec.ts`
- Modify: `tauri-app/src/components/Speakers.tsx`
- Modify: `tauri-app/src/App.css`

- [ ] 各行の「名前変更」から保存できるE2Eテストを追加する。
- [ ] テストを実行し、ボタンがないため失敗することを確認する。
- [ ] 保存・キャンセル・空欄エラー・保存中状態を実装する。
- [ ] 対象テスト、TypeScript build、関連回帰テストを実行する。

### Task 3: 配布版への反映

**Files:**
- Build: `tauri-app/dist/`
- Deploy: `dist/Transcriber/`

- [ ] 録音セッションが`idle`であることを確認する。
- [ ] Tauri配布物をビルドする。
- [ ] ユーザー承認後に既存配布版を退避して差し替える。
- [ ] 再起動後に`/api/health`と`/api/speakers`を確認する。
