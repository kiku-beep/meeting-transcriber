# Transcriber 最終仕上げ 実装プラン

## 概要
全28項目（Critical 8, Important 12, Feature 8）を5フェーズに分けて実装する。
各フェーズ内の変更は独立性が高く、並列作業可能。

---

## Phase 1: セキュリティ・データ保全（最優先）

### 1-1. Path Traversal 脆弱性修正
**ファイル**: `backend/storage/file_store.py`
**変更内容**:
- `_validate_session_id()` ヘルパー関数を追加
- 正規表現 `^[\w-]+$` でバリデーション（英数字・ハイフン・アンダースコアのみ許可）
- `load_transcript`, `load_transcript_text`, `load_summary`, `save_summary`, `update_session_name`, `save_entries`, `delete_session` の全関数冒頭でバリデーション呼び出し
- resolve後のパスが `sessions_dir` 配下であることも確認（二重チェック）
```python
import re

def _validate_session_id(session_id: str) -> None:
    if not re.match(r'^[\w-]+$', session_id):
        raise ValueError(f"Invalid session_id: {session_id}")
    resolved = (settings.sessions_dir / session_id).resolve()
    if not str(resolved).startswith(str(settings.sessions_dir.resolve())):
        raise ValueError(f"Path traversal detected: {session_id}")
```

### 1-2. JSON アトミック書き込み
**ファイル**: `backend/storage/file_store.py`, `backend/storage/dictionary_store.py`, `backend/storage/correction_store.py`
**変更内容**:
- 共通ユーティリティ `_atomic_write_json(path, data)` を `file_store.py` に追加
- tmpファイルに書き込み → `os.replace()` でアトミックリネーム
- `dictionary_store._save()`, `correction_store._save()`, `file_store` の各書き込み箇所で使用
```python
import tempfile, os

def _atomic_write_json(path: Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_suffix('.tmp')
    tmp_path.write_text(text, encoding='utf-8')
    os.replace(str(tmp_path), str(path))
```

### 1-3. `_preload_models()` 例外ハンドリング
**ファイル**: `backend/main.py`
**変更内容**:
- `_preload_models()` の全体を try/except でラップ
- 例外時にログ出力（`logger.exception`）
- `startup()` で task の done_callback を設定して例外を拾う
- `session._mic_buffer.load_model()` も `run_in_executor` 経由に変更
```python
async def _preload_models():
    try:
        ...
        loop = asyncio.get_event_loop()
        await asyncio.gather(
            loop.run_in_executor(None, session._mic_buffer.load_model),
            loop.run_in_executor(None, session._transcriber.load_model),
            loop.run_in_executor(None, session._diarizer.load_model),
        )
        logger.info("All models pre-loaded")
    except Exception:
        logger.exception("CRITICAL: Model preload failed")
```

### 1-4. NVML try/finally
**ファイル**: `backend/api/routes_health.py`, `backend/core/vram_manager.py`
**変更内容**:
- `routes_health.gpu_status()`: `nvmlInit()` → try/finally → `nvmlShutdown()`
- `vram_manager._get_temperature()`: 同様に try/finally

---

## Phase 2: バックエンド安定性修正

### 2-1. Diarizer 二重ロード解消
**ファイル**: `backend/api/routes_speaker.py`
**変更内容**:
- `_get_diarizer()` を削除
- `get_session()._diarizer` を直接使用するように変更
- ただしセッションの diarizer がまだロードされていない場合のフォールバックを追加
```python
def _get_diarizer() -> Diarizer:
    from backend.models.session import get_session
    d = get_session()._diarizer
    if not d.is_loaded:
        d.load_model()
    return d
```

### 2-2. NVML キャッシュ化
**ファイル**: `backend/core/vram_manager.py`
**変更内容**:
- `_cache` dict と `_cache_time` をモジュールレベルで保持
- `get_vram_status()` でキャッシュが2秒以内なら再利用
- NVML init/shutdown を1回にまとめる
```python
import time as _time
_cache: VRAMStatus | None = None
_cache_time: float = 0

def get_vram_status() -> VRAMStatus | None:
    global _cache, _cache_time
    now = _time.monotonic()
    if _cache and (now - _cache_time) < 2.0:
        return _cache
    # ... actual NVML query ...
    _cache = result
    _cache_time = now
    return result
```

### 2-3. correction_learner 挿入検出修正
**ファイル**: `backend/core/correction_learner.py`
**変更内容**:
- `_extract_changes()` の line 104 の条件 `from_text and to_text` を `from_text or to_text` に変更
- 挿入（from_text 空）と削除（to_text 空）も変更として記録する
- ただし `from_text` が空の場合は辞書ルール候補にはしない（`analyze_corrections` 側でフィルタ済み）

### 2-4. WebSocket ポーリング間隔最適化
**ファイル**: `backend/api/ws_transcription.py`
**変更内容**:
- status 送信をイベント駆動に変更: status が前回と異なる場合のみ送信
- タイムアウトを 0.1s → 0.5s に変更（status変化がない場合のアイドルポーリング）
- `broadcast_entry()` デッドコードを削除
```python
last_status = None
...
current_status = session.info
if current_status != last_status:
    await ws.send_json({"type": "status", "data": current_status})
    last_status = current_status
...
await asyncio.wait_for(session._new_entry_event.wait(), timeout=0.5)
```

### 2-5. `on_event` → `lifespan` マイグレーション
**ファイル**: `backend/main.py`
**変更内容**:
- `@app.on_event("startup")` / `@app.on_event("shutdown")` を `lifespan` コンテキストマネージャに統合
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    ...
    task = asyncio.create_task(_preload_models())
    task.add_done_callback(lambda t: t.result() if not t.cancelled() and t.exception() is None else None)
    yield
    # shutdown
    session = get_session()
    await session.stop()
    session.terminate_pyaudio()
    logger.info("Transcriber backend shutting down")

app = FastAPI(title="Transcriber", version="0.1.0", lifespan=lifespan)
```

### 2-6. 音声リサンプリング共通化
**ファイル**: 新規 `backend/core/audio_utils.py`, 変更 `backend/api/routes_speaker.py`, `backend/models/session.py`
**変更内容**:
- `audio_utils.py` に `resample_to_16k_mono(audio, sr)` を定義
- `routes_speaker.py` の4箇所のリサンプリングコードを置き換え
- `session.py` の `_resample_to_16k` は channels 引数があるので内部メソッドのまま残す（ただし route_speaker 側は mono 前提なので統一可能）

---

## Phase 3: フロントエンド バグ修正

### 3-1. TranscriptEntry 二重保存防止
**ファイル**: `tauri-app/src/components/TranscriptEntry.tsx`
**変更内容**:
- `savingRef = useRef(false)` を追加
- `handleTextSave` の冒頭で `if (savingRef.current) return;` ガード
- try/finally で `savingRef.current` をリセット
```tsx
const savingRef = useRef(false);

const handleTextSave = async () => {
  if (savingRef.current) return;
  if (!onEditText || editText === entry.text) {
    setEditingText(false);
    return;
  }
  savingRef.current = true;
  setSaving(true);
  try {
    await onEditText(entry.id, editText);
  } finally {
    savingRef.current = false;
    setSaving(false);
    setEditingText(false);
  }
};
```

### 3-2. スマート自動スクロール
**ファイル**: `tauri-app/src/components/Transcription.tsx`
**変更内容**:
- `containerRef` を entries コンテナ div に付与
- `isNearBottom` ref を追加、スクロールイベントで更新
- 新エントリ追加時、ユーザーが底部付近（100px以内）の場合のみ自動スクロール
```tsx
const containerRef = useRef<HTMLDivElement>(null);
const isNearBottom = useRef(true);

const handleScroll = () => {
  const el = containerRef.current;
  if (!el) return;
  isNearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
};

useEffect(() => {
  if (isNearBottom.current) {
    entriesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }
}, [entries]);

// JSX:
<div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto p-2">
```

### 3-3. auto-summarize 無限再発火修正
**ファイル**: `tauri-app/src/App.tsx`
**変更内容**:
- `handleSessionStop` と `handleAutoSummarizeComplete` を `useCallback` でラップ
```tsx
const handleSessionStop = useCallback((sessionId: string) => {
  setAutoSummarizeSessionId(sessionId);
  setActiveTab(3);
}, []);

const handleAutoSummarizeComplete = useCallback(() => {
  setAutoSummarizeSessionId(null);
}, []);
```

### 3-4. WebSocket ping/keepalive
**ファイル**: `tauri-app/src/lib/useWebSocket.ts`
**変更内容**:
- 30秒間隔で `{"type": "ping"}` を送信する `setInterval` を追加
- cleanup で `clearInterval`
- WS接続切れ検知: 2回連続pingに応答がない場合、明示的に `ws.close()` して再接続トリガー
```tsx
// connect() 内:
ws.onopen = () => {
  setConnected(true);
  pingTimer = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "ping" }));
    }
  }, 30000);
};
ws.onclose = () => {
  clearInterval(pingTimer);
  ...
};
```
**バックエンド側**: `ws_transcription.py` で受信した `ping` に `pong` を返す処理を追加
```python
# WebSocket受信ループ内（別タスクか、既存ループに追加）
try:
    data = await asyncio.wait_for(ws.receive_text(), timeout=0.01)
    msg = json.loads(data)
    if msg.get("type") == "ping":
        await ws.send_json({"type": "pong"})
except asyncio.TimeoutError:
    pass
```

### 3-5. エラー表示の自動クリア＆閉じるボタン
**ファイル**: 全コンポーネント（`Transcription.tsx`, `History.tsx`, `Dictionary.tsx`, `Settings.tsx`, `Speakers.tsx`）
**変更内容**:
- エラー表示に × ボタンを追加
- 成功した操作後に `setError("")` を呼び出す（既に多くの箇所で実行済みだが、漏れを修正）
- 共通パターン:
```tsx
{error && (
  <div className="p-2 bg-red-900/50 border border-red-700 rounded text-red-300 text-xs flex items-center justify-between">
    <span>{error}</span>
    <button onClick={() => setError("")} className="text-red-400 hover:text-red-300 ml-2 shrink-0">✕</button>
  </div>
)}
```

### 3-6. `apiFetch` Content-Type 条件付き設定
**ファイル**: `tauri-app/src/lib/api.ts`
**変更内容**:
- body がある場合のみ `Content-Type: application/json` を設定
```ts
headers: {
  ...(options?.body ? { "Content-Type": "application/json" } : {}),
  ...options?.headers,
},
```

### 3-7. `summaryResult.usage` 安全なアクセス
**ファイル**: `tauri-app/src/components/History.tsx`
**変更内容**:
- `SummaryUsage` 型を `types.ts` に追加
- オプショナルチェインで安全にアクセス
```tsx
// types.ts に追加:
export interface SummaryUsage {
  total_tokens?: number;
  cost_usd?: number;
}

// History.tsx:
const usage = summaryResult?.usage as SummaryUsage | undefined;
{usage?.total_tokens != null && (
  <span className="text-slate-400">
    {usage.total_tokens.toLocaleString()} tokens
    {usage.cost_usd != null && ` ($${usage.cost_usd.toFixed(4)})`}
  </span>
)}
```

---

## Phase 4: UX・ポリッシュ

### 4-1. 辞書ルール削除の確認ダイアログ
**ファイル**: `tauri-app/src/components/Dictionary.tsx`
**変更内容**:
- `handleDelete` の冒頭に `if (!confirm("このルールを削除しますか？")) return;` を追加
- 話者削除（`Speakers.tsx`）にも同様の確認を追加

### 4-2. 全タブ常時マウント → 遅延マウント
**ファイル**: `tauri-app/src/App.tsx`
**変更内容**:
- Transcription タブ（index 0）は常時マウント（WebSocket 維持のため）
- 他タブは初回表示時にマウント、以降は hidden で維持（unmount はしない＝stateを保持）
```tsx
const [visitedTabs, setVisitedTabs] = useState<Set<number>>(new Set([0]));

useEffect(() => {
  setVisitedTabs(prev => new Set(prev).add(activeTab));
}, [activeTab]);

// JSX:
{TABS.map((tab, i) => {
  const shouldMount = i === 0 || visitedTabs.has(i);
  if (!shouldMount) return <div key={tab} className="hidden" />;
  return (
    <div key={tab} className={activeTab === i ? "h-full" : "hidden"}>
      {/* component */}
    </div>
  );
})}
```

### 4-3. React Error Boundary
**ファイル**: 新規 `tauri-app/src/components/ErrorBoundary.tsx`, 変更 `tauri-app/src/main.tsx`
**変更内容**:
- class component で ErrorBoundary を作成
- 白画面ではなく「エラーが発生しました。再読み込みしてください」を表示
- `main.tsx` で `<App />` をラップ

### 4-4. 履歴セッション一覧に日時表示
**ファイル**: `tauri-app/src/components/History.tsx`
**変更内容**:
- `<option>` に `saved_at` をフォーマットして表示
```tsx
{sessions.map((s) => (
  <option key={s.session_id} value={s.session_id}>
    {s.session_name || s.session_id}
    {s.entry_count != null ? ` (${s.entry_count}件)` : ""}
    {s.saved_at ? ` — ${new Date(s.saved_at).toLocaleDateString('ja-JP')}` : ""}
  </option>
))}
```

### 4-5. ファイルエクスポートの Tauri 対応
**ファイル**: `tauri-app/src/components/History.tsx`
**変更内容**:
- Tauri 環境判定を追加（`window.__TAURI__` の存在チェック）
- Tauri 環境: `@tauri-apps/plugin-dialog` の `save()` + `@tauri-apps/plugin-fs` の `writeTextFile()` を使用
- 非 Tauri 環境（dev 中のブラウザ）: 既存の `<a>.click()` をフォールバックとして残す
```tsx
const handleExport = async (format: "txt" | "json" | "md") => {
  const content = await exportTranscript(selectedId, format);
  if (window.__TAURI__) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const { writeTextFile } = await import("@tauri-apps/plugin-fs");
    const path = await save({ defaultPath: `${selectedId}.${format}`, filters: [{ name: format, extensions: [format] }] });
    if (path) await writeTextFile(path, content);
  } else {
    // fallback for browser dev
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${selectedId}.${format}`; a.click();
    URL.revokeObjectURL(url);
  }
};
```
**注意**: `@tauri-apps/plugin-dialog` と `@tauri-apps/plugin-fs` が `package.json` に未追加なら追加する。また `src-tauri/tauri.conf.json` の plugins に設定追加が必要になる可能性あり。

### 4-6. 要約コピーボタン
**ファイル**: `tauri-app/src/components/History.tsx`
**変更内容**:
- 要約表示エリアの上部に「コピー」ボタンを追加
- `navigator.clipboard.writeText(summary)` で実装
- コピー成功時に一時的に「コピー済み」表示
```tsx
const [copied, setCopied] = useState(false);
const handleCopy = async () => {
  await navigator.clipboard.writeText(summary);
  setCopied(true);
  setTimeout(() => setCopied(false), 2000);
};
// JSX: 要約を生成ボタンの横に
<button onClick={handleCopy} disabled={!summary} className="...">
  {copied ? "コピー済み" : "コピー"}
</button>
```

### 4-7. WS再接続インジケーター改善
**ファイル**: `tauri-app/src/components/StatusBar.tsx`, `tauri-app/src/lib/useWebSocket.ts`
**変更内容**:
- `useWebSocket` の戻り値に `reconnecting: boolean` を追加
- `onclose` で `setReconnecting(true)`, `onopen` で `setReconnecting(false)`
- StatusBar で 3 状態表示: 「WS接続中」「WS再接続中...」「WS切断」

---

## Phase 5: 機能追加

### 5-1. セッション自動保存（クラッシュリカバリ）
**ファイル**: `backend/models/session.py`
**変更内容**:
- `_pipeline_loop` 内で、50エントリごとまたは5分ごとに中間保存
- `file_store.save_session()` を呼ぶ（既存セッションは上書き）
- 自動保存のフラグ `_autosave_count` で制御
```python
_last_autosave = 0
AUTOSAVE_INTERVAL_ENTRIES = 50

# _pipeline_loop 内:
if len(self.entries) - self._last_autosave >= AUTOSAVE_INTERVAL_ENTRIES:
    save_session(self.session_id, self.entries, {"session_name": self.session_name, "started_at": ...})
    self._last_autosave = len(self.entries)
    logger.info("Auto-saved session %s (%d entries)", self.session_id, len(self.entries))
```

### 5-2. 文字起こし検索
**ファイル**: `tauri-app/src/components/Transcription.tsx`, `tauri-app/src/components/History.tsx`, `tauri-app/src/components/TranscriptEntry.tsx`
**変更内容**:
- 検索バーを entries 一覧の上に追加（Ctrl+F でフォーカス）
- `searchQuery` state を追加
- entries を `searchQuery` でフィルタリング
- TranscriptEntry にハイライト表示: マッチ部分を `<mark>` で囲む
```tsx
// Transcription.tsx:
const [searchQuery, setSearchQuery] = useState("");
const filteredEntries = searchQuery
  ? entries.filter(e => e.text.includes(searchQuery) || e.speaker_name.includes(searchQuery))
  : entries;

// JSX:
<input
  value={searchQuery}
  onChange={e => setSearchQuery(e.target.value)}
  placeholder="検索..."
  className="bg-slate-700 border border-slate-600 rounded px-3 py-1 text-sm w-full"
/>
```

### 5-3. pyinstaller_entry.py ログファイル安全化
**ファイル**: `pyinstaller_entry.py`
**変更内容**:
- `atexit.register(log_file.flush)` を追加
- `buffering=1`（行バッファ）に変更

---

## 実行順序と依存関係

```
Phase 1 (データ保全) ←── 最優先、他に依存なし
  ├── 1-1 path traversal      (file_store.py)
  ├── 1-2 atomic write         (file_store.py, dictionary_store.py, correction_store.py)
  ├── 1-3 preload error        (main.py)
  └── 1-4 nvml try/finally     (routes_health.py, vram_manager.py)

Phase 2 (BE安定性) ←── Phase 1 完了後
  ├── 2-1 diarizer dedup       (routes_speaker.py)
  ├── 2-2 nvml cache           (vram_manager.py) ← 1-4 に依存
  ├── 2-3 correction_learner   (correction_learner.py)
  ├── 2-4 ws polling           (ws_transcription.py)
  ├── 2-5 lifespan migration   (main.py) ← 1-3 に依存
  └── 2-6 audio utils          (新規 audio_utils.py, routes_speaker.py)

Phase 3 (FEバグ修正) ←── Phase 2 と並列可能
  ├── 3-1 double save          (TranscriptEntry.tsx)
  ├── 3-2 smart scroll         (Transcription.tsx)
  ├── 3-3 auto-summarize fix   (App.tsx)
  ├── 3-4 ws ping              (useWebSocket.ts + ws_transcription.py) ← 2-4 と同時実施推奨
  ├── 3-5 error dismiss        (全コンポーネント)
  ├── 3-6 content-type         (api.ts)
  └── 3-7 usage safe access    (History.tsx, types.ts)

Phase 4 (UXポリッシュ) ←── Phase 3 完了後
  ├── 4-1 delete confirm       (Dictionary.tsx, Speakers.tsx)
  ├── 4-2 lazy mount tabs      (App.tsx) ← 3-3 に依存
  ├── 4-3 error boundary       (新規 ErrorBoundary.tsx, main.tsx)
  ├── 4-4 session datetime     (History.tsx)
  ├── 4-5 tauri export         (History.tsx) ← npm install 必要な可能性
  ├── 4-6 copy summary         (History.tsx)
  └── 4-7 ws reconnect indicator (StatusBar.tsx, useWebSocket.ts)

Phase 5 (機能追加) ←── Phase 4 完了後
  ├── 5-1 autosave             (session.py)
  ├── 5-2 search               (Transcription.tsx, History.tsx, TranscriptEntry.tsx)
  └── 5-3 log safety           (pyinstaller_entry.py)
```

## 変更ファイル一覧（全体）

| ファイル | Phase | 変更種別 |
|---------|-------|---------|
| `backend/storage/file_store.py` | 1-1, 1-2 | バリデーション追加, アトミック書き込み |
| `backend/storage/dictionary_store.py` | 1-2 | アトミック書き込み |
| `backend/storage/correction_store.py` | 1-2 | アトミック書き込み |
| `backend/main.py` | 1-3, 2-5 | エラーハンドリング, lifespan 移行 |
| `backend/api/routes_health.py` | 1-4 | try/finally |
| `backend/core/vram_manager.py` | 1-4, 2-2 | try/finally, キャッシュ |
| `backend/api/routes_speaker.py` | 2-1, 2-6 | diarizer 共有, リサンプル統一 |
| `backend/core/correction_learner.py` | 2-3 | 挿入検出修正 |
| `backend/api/ws_transcription.py` | 2-4, 3-4 | ポーリング最適化, ping/pong |
| `backend/core/audio_utils.py` | 2-6 | **新規** リサンプルユーティリティ |
| `backend/models/session.py` | 5-1 | 自動保存 |
| `tauri-app/src/components/TranscriptEntry.tsx` | 3-1, 5-2 | 二重保存防止, 検索ハイライト |
| `tauri-app/src/components/Transcription.tsx` | 3-2, 5-2 | スマートスクロール, 検索バー |
| `tauri-app/src/App.tsx` | 3-3, 4-2 | useCallback, 遅延マウント |
| `tauri-app/src/lib/useWebSocket.ts` | 3-4, 4-7 | ping, reconnecting state |
| `tauri-app/src/lib/api.ts` | 3-6 | Content-Type 条件化 |
| `tauri-app/src/lib/types.ts` | 3-7 | SummaryUsage 型追加 |
| `tauri-app/src/components/History.tsx` | 3-7, 4-4, 4-5, 4-6, 5-2 | 安全アクセス, 日時, エクスポート, コピー, 検索 |
| `tauri-app/src/components/Dictionary.tsx` | 3-5, 4-1 | エラー閉じ, 削除確認 |
| `tauri-app/src/components/Settings.tsx` | 3-5 | エラー閉じ |
| `tauri-app/src/components/Speakers.tsx` | 3-5, 4-1 | エラー閉じ, 削除確認 |
| `tauri-app/src/components/StatusBar.tsx` | 4-7 | 再接続表示 |
| `tauri-app/src/components/ErrorBoundary.tsx` | 4-3 | **新規** |
| `tauri-app/src/main.tsx` | 4-3 | ErrorBoundary ラップ |
| `pyinstaller_entry.py` | 5-3 | ログ安全化 |

## 見送り項目（今回は非対応）
- CSP 設定（ローカルアプリのため影響小）
- ARIA アクセシビリティ（将来対応）
- react-virtual 仮想スクロール（検索でのフィルタで十分、長時間会議はまれ）
- 辞書インポート/エクスポート（既存機能で十分）
- ESLint 導入（別タスク）
