# Transcriber リファクタリング計画

**作成日**: 2026-02-12
**対象**: Dictionary.tsx と Transcription.tsx の UI コンポーネント分割

## 背景

### 現状の問題点
- **Dictionary.tsx**: 381行 - 5つの異なる機能（学習候補、ルール追加、一覧、フィラー、テスト）が混在
- **Transcription.tsx**: 327行 - 録音制御、エントリ表示、検索、話者登録が単一ファイルに集約

### 改善目標
- 単一責任原則に従ったコンポーネント分割
- 各コンポーネントのテスタビリティ向上
- 再利用性とメンテナンス性の改善

---

## Phase 1: Dictionary.tsx の分割

### 新規作成ファイル (5件)

#### 1. `components/dictionary/LearningSuggestions.tsx`
- **責務**: 訂正履歴の分析と学習候補の表示
- **Props**:
  ```typescript
  interface Props {
    onRefresh: () => void;
  }
  ```
- **内部状態**:
  - `suggestions: LearningSuggestion[]`
  - `suggestionsOpen: boolean`
  - `loadingSuggestions: boolean`
- **主要機能**:
  - 「訂正履歴を分析」ボタン
  - 候補テーブル（変換元、変換先、回数、信頼度）
  - 採用/却下ボタン

#### 2. `components/dictionary/RuleForm.tsx`
- **責務**: 辞書ルールの追加フォーム
- **Props**:
  ```typescript
  interface Props {
    onAdd: () => void;
  }
  ```
- **内部状態**:
  - `fromText: string`
  - `toText: string`
  - `isRegex: boolean`
  - `note: string`
- **主要機能**:
  - 変換元/変換先入力
  - 正規表現チェックボックス
  - 追加ボタン

#### 3. `components/dictionary/RuleList.tsx`
- **責務**: 登録済みルールの一覧表示
- **Props**:
  ```typescript
  interface Props {
    replacements: DictionaryReplacement[];
    onDelete: (index: number) => void;
  }
  ```
- **主要機能**:
  - ルール一覧テーブル
  - 削除ボタン
  - 自動学習ラベル表示

#### 4. `components/dictionary/FillerSettings.tsx`
- **責務**: フィラー除去設定
- **Props**:
  ```typescript
  interface Props {
    initialFillers: string[];
    initialEnabled: boolean;
    onSave: (fillers: string[], enabled: boolean) => void;
  }
  ```
- **内部状態**:
  - `fillerText: string`
  - `fillerEnabled: boolean`
- **主要機能**:
  - フィラー除去トグル
  - フィラー単語入力（カンマ区切り）
  - 保存ボタン

#### 5. `components/dictionary/DictionaryTester.tsx`
- **責務**: 辞書ルールのテスト機能
- **Props**: なし（独立）
- **内部状態**:
  - `testInput: string`
  - `testResult: string`
- **主要機能**:
  - テスト入力フィールド
  - テスト実行ボタン
  - 結果表示（JSON）

### 変更ファイル

#### `components/Dictionary.tsx` (簡素化: 381行 → 約80行)
- **責務**: サブコンポーネントの統合、API呼び出し、エラーハンドリング
- **構成**:
  ```tsx
  export default function Dictionary() {
    const [dict, setDict] = useState<DictionaryConfig | null>(null);
    const [error, setError] = useState("");

    const refresh = async () => { /* ... */ };

    return (
      <div className="p-6 space-y-6 overflow-y-auto h-full">
        <h2>辞書設定</h2>
        {error && <ErrorAlert />}

        <LearningSuggestions onRefresh={refresh} />
        <RuleForm onAdd={refresh} />
        <RuleList replacements={dict?.replacements || []} onDelete={handleDelete} />
        <FillerSettings
          initialFillers={dict?.fillers || []}
          initialEnabled={dict?.filler_removal_enabled || false}
          onSave={handleFillerSave}
        />
        <DictionaryTester />
      </div>
    );
  }
  ```

---

## Phase 2: Transcription.tsx の分割

### 新規作成ファイル (4件)

#### 1. `components/transcription/RecordingControls.tsx`
- **責務**: 録音セッションの開始/停止/一時停止コントロール
- **Props**:
  ```typescript
  interface Props {
    isRunning: boolean;
    isPaused: boolean;
    loading: boolean;
    devices: AudioDevice[];
    selectedLoopback: number | undefined;
    sessionName: string;
    onLoopbackChange: (index: number | undefined) => void;
    onSessionNameChange: (name: string) => void;
    onStart: () => void;
    onPause: () => void;
    onStop: () => void;
  }
  ```
- **UI要素**:
  - ループバックデバイス選択ドロップダウン
  - セッション名入力
  - 録音開始 / 一時停止 / 停止 ボタン

#### 2. `components/transcription/SpeakerRegistration.tsx`
- **責務**: 話者登録フォーム（アコーディオン式）
- **Props**:
  ```typescript
  interface Props {
    visible: boolean;
    entryCount: number;
    onRegister: (entryIndex: number, name: string) => void;
  }
  ```
- **内部状態**:
  - `regEntryIndex: string`
  - `regName: string`
  - `regOpen: boolean`
- **UI要素**:
  - アコーディオントグル
  - エントリ番号入力
  - 話者名入力
  - 登録ボタン

#### 3. `components/transcription/TranscriptSearch.tsx`
- **責務**: エントリ検索バー
- **Props**:
  ```typescript
  interface Props {
    value: string;
    onChange: (query: string) => void;
  }
  ```
- **UI要素**:
  - 検索入力フィールド

#### 4. `components/transcription/TranscriptList.tsx`
- **責務**: エントリ一覧表示と自動スクロール
- **Props**:
  ```typescript
  interface Props {
    entries: TranscriptEntry[];
    filteredEntries: TranscriptEntry[];
    speakers: Speaker[];
    searchQuery: string;
    isRunning: boolean;
    onEditText: (entryId: string, newText: string) => void;
    onEditSpeaker: (entryId: string, speakerName: string, speakerId: string) => void;
  }
  ```
- **内部状態**:
  - `entriesEndRef: RefObject<HTMLDivElement>`
  - `containerRef: RefObject<HTMLDivElement>`
  - `isNearBottom: RefObject<boolean>`
- **主要機能**:
  - スクロール検知（`handleScroll`）
  - 新規エントリ時の自動スクロール
  - 空状態メッセージ表示

### 変更ファイル

#### `components/Transcription.tsx` (簡素化: 327行 → 約150行)
- **責務**: WebSocket管理、状態管理、API呼び出し、ビジネスロジック
- **保持する状態**:
  - `status`, `entries`, `devices`, `speakers`
  - `selectedLoopback`, `sessionName`
  - `error`, `loading`, `searchQuery`
- **構成**:
  ```tsx
  export default function Transcription({ onSessionStop }: Props) {
    // WebSocket, 状態管理, API呼び出しロジック
    const { connected, reconnecting } = useWebSocket({ ... });

    return (
      <div className="flex flex-col h-full">
        <div className="p-4 border-b border-slate-700 space-y-3 shrink-0">
          <RecordingControls {...controlProps} />
          {error && <ErrorAlert />}
          <SpeakerRegistration {...speakerRegProps} />
        </div>

        <TranscriptSearch value={searchQuery} onChange={setSearchQuery} />
        <TranscriptList {...listProps} />
        <StatusBar status={status} wsConnected={connected} wsReconnecting={reconnecting} />
      </div>
    );
  }
  ```

---

## ディレクトリ構造 (変更後)

```
/mnt/e/transcriber/tauri-app/src/components/
├── dictionary/
│   ├── LearningSuggestions.tsx  (新規)
│   ├── RuleForm.tsx             (新規)
│   ├── RuleList.tsx             (新規)
│   ├── FillerSettings.tsx       (新規)
│   └── DictionaryTester.tsx     (新規)
├── transcription/
│   ├── RecordingControls.tsx    (新規)
│   ├── SpeakerRegistration.tsx  (新規)
│   ├── TranscriptSearch.tsx     (新規)
│   └── TranscriptList.tsx       (新規)
├── Dictionary.tsx               (変更: 381行 → 80行)
├── Transcription.tsx            (変更: 327行 → 150行)
├── TranscriptEntry.tsx          (変更なし)
├── StatusBar.tsx                (変更なし)
└── (その他既存ファイル)
```

---

## 実装順序

1. **Phase 1-1**: `components/dictionary/` ディレクトリ作成
2. **Phase 1-2**: 5つのサブコンポーネント作成（並列可）
3. **Phase 1-3**: `Dictionary.tsx` をリファクタリング
4. **Phase 1-4**: ビルド確認 (`npm run build`)
5. **Phase 2-1**: `components/transcription/` ディレクトリ作成
6. **Phase 2-2**: 4つのサブコンポーネント作成（並列可）
7. **Phase 2-3**: `Transcription.tsx` をリファクタリング
8. **Phase 2-4**: ビルド確認 (`npm run build`)
9. **最終確認**: 開発モードで動作確認 (`npx tauri dev`)

---

## 検証コマンド

### ビルド確認
```powershell
cd E:\transcriber\tauri-app
npm run build
```

### 開発モード起動
```powershell
# Terminal 1: Backend
cd E:\transcriber
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Tauri dev
cd E:\transcriber\tauri-app
npx tauri dev
```

---

## 注意事項

- **既存の動作を変更しない**: リファクタリングは振る舞い保存が原則
- **import パスの一貫性**: 既存のインポートスタイルに合わせる
- **Tailwind CSS クラス**: 既存のダークテーマ（slate-900, cyan アクセント）を維持
- **エラーハンドリング**: 親コンポーネント（Dictionary.tsx, Transcription.tsx）で一括管理
- **Props の最小化**: 必要最小限のデータのみ渡す

---

## 完了条件

- [ ] 全9ファイルが作成され、2ファイルが変更されている
- [ ] `npm run build` がエラーなく完了する
- [ ] 開発モードで全機能が正常動作する（録音、辞書、学習候補、話者登録）
- [ ] コンソールに新規エラー/警告が出ていない
- [ ] 既存の機能が全て動作する（インライン編集、WebSocket、自動スクロールなど）

---

## 次のステップ（このリファクタリング後）

1. session.py の責務分離（AudioDeviceManager, AudioStreamManager 抽出）
2. デバッグログの整理（設定ベースのロギングに統合）
3. correction_learner.py の diff アルゴリズム改善
