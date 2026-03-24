# Transcriber プロジェクト引き継ぎ

## プロジェクト概要
リアルタイム会議文字起こしツール。FastAPI バックエンド + Gradio フロントエンド。

- **場所**: `E:\transcriber\`
- **Python**: 3.11.9 (`E:\transcriber\.venv\`)
- **計画書**: `C:\Users\faker\.claude\plans\magical-noodling-babbage.md`

## 実装状況

| Phase | 内容 | 状態 |
|-------|------|------|
| 1 | Foundation (FastAPI, config, health) | 完了 |
| 2 | Transcription Pipeline (Whisper, VAD, audio) | 完了 |
| 3 | Speaker Identification (pyannote embedding) | 完了 |
| 4 | Post-processing + Storage (辞書, 保存) | 完了 |
| 5 | Gradio Frontend (全タブ, WebSocket) | 完了 |
| 6 | Summary + Finishing (Gemini要約, ループバック等) | **完了** |
| 7 | Tauri デスクトップアプリ化 | **未着手** |

## 起動方法
```powershell
cd E:\transcriber
.venv\Scripts\python.exe scripts\start.py
```
- `start.py` がバックエンド→ヘルスチェック→フロントエンドの順で自動起動
- Backend: http://127.0.0.1:8000
- Frontend: http://127.0.0.1:7860
- Ctrl+C で両方停止

## アーキテクチャ

### バックエンド (`backend/`)
```
backend/
  main.py              — FastAPI app, CORS(credentials=False), 全ルーター登録
  config.py            — pydantic-settings, .env読み込み (whisper_model=kotoba-v2.0)
  api/
    routes_health.py   — GET /api/health, /api/health/gpu
    routes_audio.py    — GET /api/audio/devices (default_mic_index/default_loopback_index追加)
    routes_session.py  — POST start/stop/pause, GET status, GET/POST /api/session/model
    routes_speaker.py  — CRUD /api/speakers + test identification
    routes_dictionary.py — CRUD /api/dictionary + /fillers + /test
    routes_transcript.py — GET /api/transcripts, export (txt/json/md)
    routes_summary.py  — POST /api/summary/generate, GET /api/summary/{id}
    ws_transcription.py — WebSocket /ws/transcript (リアルタイムentry配信)
  core/
    audio_capture.py   — PyAudioWPatch WASAPI デバイス列挙
    audio_buffer.py    — Silero VAD, 音声セグメント分割
    transcriber.py     — Faster-Whisper (kotoba-v2.0推奨, 全6モデル切替可, GPU float16)
    diarizer.py        — pyannote embedding, cosine similarity話者識別
    post_processor.py  — フィラー除去 → 辞書置換(テキスト/正規表現+ひらがな境界チェック) → 正規化
    summarizer.py      — Gemini API 議事録生成
    vram_manager.py    — torch.cuda VRAM + nvidia_ml_py 温度監視
  models/
    schemas.py         — Pydantic データモデル
    session.py         — TranscriptionSession 状態マシン (マイク/ループバック独立VAD)
  storage/
    speaker_store.py   — data/speakers/{id}/ に profile.json, embedding.npz, samples/
    dictionary_store.py — data/dictionary.json
    file_store.py      — data/sessions/{id}/ に transcript.json, .txt, metadata.json, summary.md
```

### フロントエンド (`frontend/`)
```
frontend/
  app.py              — Gradio Blocks メインUI, 5タブ, 単一app.load
  api_client.py       — httpx ベースHTTPクライアント (summary/model API追加)
  tabs/
    tab_transcription.py — リアルタイム文字起こし (マイク+ループバック選択, WebSocket + 1秒Timer)
    tab_speakers.py      — 話者登録/削除
    tab_dictionary.py    — 辞書ルール管理 (テキスト/正規表現/メモ対応)
    tab_history.py       — セッション履歴閲覧/エクスポート + 要約タブ + Gemini要約生成
    tab_settings.py      — Whisperモデル切替 (kotoba-v2.0先頭), ヘルスチェック, GPU, デバイス一覧
```

### データ (`data/`)
```
data/
  dictionary.json     — 辞書ルール + フィラー設定
  speakers/           — 話者プロファイル
  sessions/           — 保存済みトランスクリプト + summary.md + recording.wav
```

## Whisper モデル

### 利用可能モデル
| モデル名 | VRAM | 特徴 |
|----------|------|------|
| kotoba-v2.0 | ~2500MB | **推奨**: 日本語特化 distil-whisper, large-v3比6.3x高速, 同等精度 |
| tiny | ~150MB | 最軽量, 精度低 |
| base | ~300MB | |
| small | ~1000MB | |
| medium | ~2500MB | |
| large-v3 | ~4500MB | 多言語高精度, 低速 |

### kotoba-whisper 実装詳細
- **HuggingFace ID**: `kotoba-tech/kotoba-whisper-v2.0-faster` (CTranslate2形式)
- **transcriber.py**: `MODEL_HF_IDS` で短縮名→HF IDマッピング, `KOTOBA_MODELS` セット
- **推奨パラメータ**: `chunk_length=15`, `condition_on_previous_text=False`
- **initial_prompt/hotwords非使用**: kotoba は日本語特化済みのため両方スキップ。長い hotwords (473文字等) を渡すと空テキストを返すバグあり
- **音声正規化**: `transcribe()` でピーク正規化 (peak→1.0) を実施。ループバック経由の低音量音声でもWhisperが認識可能
- **デフォルト**: `.env` の `WHISPER_MODEL=kotoba-v2.0`, config.py のデフォルトも `kotoba-v2.0`

### 辞書→Whisper語彙ヒント (non-kotobaモデル専用)
- `build_vocab_hints()`: 辞書の "to" 値から `initial_prompt` (先頭400文字) と `hotwords` (全語彙) を構築
- **kotobaモデルでは使用しない**: hotwords を渡すと空テキストを返す問題があるため
- セッション開始時に自動実行
- `initial_prompt`: Whisper の "previous context" として語彙認識を改善
- `hotwords`: CTranslate2 のデコード時 logit バイアスで特定語を優先

## デュアルVADバッファ (マイク+ループバック独立)

### 問題と解決
マイクとループバックの音声が1つのVADに交互に入ると、Silero VAD (stateful RNN) の内部状態が壊れて発話検出に失敗する。

### 実装
- `session.py`: `_mic_buffer` と `_loopback_buffer` の2つの `AudioBuffer` インスタンス
- 各コールバックが対応するバッファにのみ feed
- パイプラインループが両方の `process_pending()` と `segment_queue` をチェック
- `_collect_segments()` で全バッファからセグメントを収集
- `_process_segment()` で個別にtranscribe+diarize (エラー耐性あり)

## 辞書システム

### 設計思想
Whisperは固有名詞をひらがなや誤った漢字で出力しがち。辞書は**読み(音)ベース**で置換する：
- `かなめ → カナメ` (人名: ひらがな出力を正しい表記に)
- `ふせず → 伏図` (専門用語)
- NG例: `要 → カナメ` は「必要」を壊すのでやらない

### ルール形式 (dictionary.json)
```json
{
  "from": "かなめ",
  "to": "カナメ",
  "case_sensitive": false,
  "enabled": true,
  "is_regex": false,
  "note": "人名"
}
```

### ひらがな自動境界チェック
- `post_processor.py` の `_apply_replacements()` が短いひらがなパターン (≤4文字, 非regex) に自動で lookbehind/lookahead を追加
- 例: `てい→邸` で `している` が `し邸る` にならない (`(?<![ぁ-んー])てい(?![ぁ-んー])`)
- 漢字の後の `てい` (`田中てい`) はマッチする

### 正規表現ショートハンド
`{漢字}`, `{ひらがな}`, `{カタカナ}`, `{数字}`, `{英字}` が Unicode 範囲に展開される

### 処理パイプライン
音声 → Whisper → 生テキスト → フィラー除去 → 辞書置換 → 正規化 → 最終テキスト

## Phase 6 実装内容

### 1. Gemini要約生成
- `backend/core/summarizer.py`: google-genai クライアントで議事録要約を生成
- `backend/api/routes_summary.py`: POST /api/summary/generate, GET /api/summary/{id}
- **タイトル自動抽出**: 要約から「## タイトル」を正規表現で抽出、セッション名がない場合に自動設定
- **トークン使用量・コスト計算**: response.usage_metadata から取得、料金表で USD/JPY 算出

### 2. WASAPIループバック (マイク+PC音声同時)
- `session.py`: `_open_loopback_stream()` メソッド、2ストリーム同時キャプチャ
- **デュアルVADバッファ**: マイクとループバックは独立した `AudioBuffer` で処理 (VAD RNN状態の混線防止)
- `_resample_to_16k()` 共通メソッドで両ストリームを16kHzモノラルに変換 (ステレオは片チャンネル取得、逆位相キャンセル防止)
- **マイクは常にシステムデフォルト使用**: `device_index=None` 固定、ループバックのみ選択可能
- **音声保存**: 録音データは16kHz WAV でセッションディレクトリに保存

### 3. Whisperモデル切替
- `transcriber.py`: `AVAILABLE_MODELS` = [tiny, base, small, medium, large-v3, kotoba-v2.0], `switch_model()` メソッド
- `routes_session.py`: GET/POST `/api/session/model` (セッション中は変更不可)
- `tab_settings.py`: モデルドロップダウン + VRAM表示 + 切替ボタン
- **デフォルトモデル**: `WHISPER_MODEL=kotoba-v2.0` (.env)

### 4. 履歴タブ改良
- `tab_history.py`: トランスクリプト/要約の2タブ構成
- **自動要約フロー**: 停止ボタン → 履歴タブ切替 → 要約自動生成 → タイトル自動設定
- **セッション削除**: 🗑️ボタンで選択中のセッションディレクトリを削除

### 5. 話者登録 (文字起こし中のエントリから)
- **エントリ番号**: 文字起こし画面に #0, #1, ... の連番を表示
- **登録UI**: 「話者登録」アコーディオンでエントリ番号+名前を入力
- **即時反映 + 同声エントリ自動更新**: cosine similarity (threshold=0.55) で同一話者判定
- `session.py`: `_entry_embeddings` キャッシュ、`register_speaker_from_entry()` メソッド

### 6. モデルプリロード
- `main.py`: startup イベントで `asyncio.create_task(_preload_models())` 実行
- Whisper, pyannote, VAD を並列ロード (非ブロック、API 即応答)

## 修正済みの問題

| 問題 | 原因 | 修正 |
|------|------|------|
| WebSocket 403 Forbidden | CORSMiddleware `allow_credentials=True` | `False` に変更 |
| Gradio Error(11) | `app.load` 5回呼び出し | 1回に統合 (`init_all`) |
| `gr.update()` 互換性 | Gradio 6.x | `gr.Dropdown()` に置換 |
| 辞書テーブル `from_text` KeyError | バックエンドは `from`/`to` | キー名修正 |
| pyannote-audio CPU torch上書き | pip依存関係 | CUDA torch再インストール |
| cuDNN `cudnnGetLibConfig` crash | cuDNN 9.1 DLLシンボル欠損 | `torch.backends.cudnn.enabled = False` |
| 話者リスト KeyError: 'id' | to_dict() が "speaker_id" のみ | "id" と "sample_count" を追加 |
| フィラー保存できない | /fillers ルートが /{index} より後 | ルート順序修正 |
| 辞書「てい→邸」で「している→し邸る」 | 部分一致 | ひらがな自動境界チェック実装 |
| 話者登録しても同声エントリ更新されない | threshold=0.75 が厳しすぎ | 0.55 に変更 + debug ログ追加 |
| Whisper が固有名詞を認識できない | 語彙ヒントなし | `build_vocab_hints()` で initial_prompt + hotwords 実装 |
| kotoba-whisper position encoding エラー | initial_prompt がデコーダ448トークン上限を圧迫 | kotoba では initial_prompt スキップ |
| VAD がマイク+ループバック同時で発話検知失敗 | 1つのVADに2ソースの音声が交互に入り RNN 状態混線 | デュアル AudioBuffer (独立VAD) |
| パイプライン1セグメントのエラーで全体停止 | try/except なし | segment 単位で例外キャッチ、skip して継続 |

## 環境メモ

- **GPU**: RTX 4070 Ti (12GB VRAM)
- **HuggingFace Token**: `.env` に `HF_TOKEN` 設定済み
- **Gradio**: 6.5.1 (パラメータが4.x/5.xと異なる)
- **オーディオ**: INZONE H3 (マイク+ループバック), Anker PowerConf S330
- **venv activation**: Git Bashでは `source .venv/Scripts/activate` が壊れるため、常にフルパス `.venv/Scripts/python.exe` を使う

## Phase 7 TODO (未着手)

1. **Tauri デスクトップアプリ化**: Gradio → Tauri (Rust + Web UI) に差し替え、配布可能な `.exe` に
   - FastAPIバックエンドはそのまま流用

## 既知の問題・注意事項

- **pynvml FutureWarning**: `nvidia-ml-py` を推奨する警告が出るが動作に影響なし
- **要約は停止時に自動生成**: 停止ボタン → 履歴タブ切替 → 要約自動生成 + トークン使用量表示
- **セッション名**: 入力しなかった場合、要約タイトルから自動設定
- **GEMINI_API_KEY**: `.env` に設定済み。なくても文字起こし機能は正常動作
- **マイク設定**: 常にシステムデフォルトマイクを使用 (変更不可)
- **デフォルトフィラー**: えー、あー、まあ、そう、うーん、えっと、あの、その、んー

## 初回起動前の確認事項

1. `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124` (CUDA版Torch)
2. HuggingFace Token の承認 (pyannote モデルアクセス用)
3. kotoba-whisper は初回起動時に自動ダウンロード (~数分)
