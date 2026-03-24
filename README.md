# Transcriber — リアルタイム会議文字起こし

NVIDIA GPU搭載のWindows PCで動作するリアルタイム会議文字起こしツール。
マイク＋PC音声（ループバック）を同時キャプチャし、話者分離・辞書置換・AI要約まで自動で行います。

## 主な機能

- **リアルタイム文字起こし** — Faster-Whisper (kotoba-v2.0) による日本語特化STT
- **話者分離** — pyannote embedding + cosine similarity による自動話者識別
- **辞書置換** — 固有名詞・専門用語の読みベース自動補正（正規表現対応）
- **AI議事録生成** — Gemini APIによるセッション要約・議事録自動生成
- **デュアル音声キャプチャ** — マイク＋WASAPI ループバック同時録音
- **スクリーンショット** — 定期的に画面キャプチャしセッションに保存

## 必要環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11（WASAPI必須） |
| GPU | NVIDIA GPU + CUDA 12.x（RTX 3060以上推奨、VRAM 8GB+） |
| Python | 3.10〜3.12 |
| Node.js | 18以上（Tauriフロントエンド用） |
| Rust | stable（Tauriビルド用） |

> **注意**: `PyAudioWPatch`（WASAPIループバック）はWindows専用です。Mac/Linuxでは音声キャプチャ部分の書き換えが必要です。

## セットアップ

### 1. リポジトリクローン

```bash
git clone https://github.com/kiku-beep/meeting-transcriber.git
cd meeting-transcriber
```

### 2. Python仮想環境 + 依存インストール

```powershell
python -m venv .venv
.venv\Scripts\activate

# CUDA版PyTorchを先にインストール（必須）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# プロジェクト依存
pip install -e .
```

> **重要**: `pip install -e .` だけだとCPU版PyTorchが入る場合があります。必ずCUDA版を先にインストールしてください。

### 3. HuggingFaceモデルアクセス承認

pyannote話者分離モデルを使うため、以下のHuggingFaceモデルページでライセンスに同意してください：

- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
- [pyannote/wespeaker-voxceleb-resnet34-LM](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM)

### 4. .env ファイル作成

プロジェクトルートに `.env` を作成：

```ini
# 必須: HuggingFaceトークン（話者分離モデルDL用）
HF_TOKEN=hf_your_token_here

# 任意: Gemini API（AI要約機能を使う場合）
GEMINI_API_KEY=your_gemini_api_key

# Whisperモデル（デフォルト: kotoba-v2.0）
WHISPER_MODEL=kotoba-v2.0

# Geminiモデル
GEMINI_MODEL=gemini-2.5-flash
```

> `.env` がない場合も文字起こし機能は動作します（要約機能のみ無効）。
> 本番環境では `%APPDATA%\transcriber\.env` にも配置可能です。

### 5. フロントエンド依存（Tauriアプリの場合）

```powershell
cd tauri-app
npm install
cd ..
```

## 起動方法

### Gradioフロントエンド（シンプル起動）

```powershell
.venv\Scripts\python.exe scripts\start.py
```

- Backend: http://127.0.0.1:8000
- Frontend: http://127.0.0.1:7860
- Ctrl+C で停止

### Tauriデスクトップアプリ

```powershell
cd tauri-app
npm run tauri dev
```

## Whisperモデル一覧

| モデル | VRAM | 特徴 |
|--------|------|------|
| `kotoba-v2.0` | ~2.5GB | **推奨**: 日本語特化、large-v3比6.3倍高速・同等精度 |
| `tiny` | ~150MB | 最軽量、精度低 |
| `base` | ~300MB | |
| `small` | ~1GB | |
| `medium` | ~2.5GB | |
| `large-v3` | ~4.5GB | 多言語高精度、低速 |

初回起動時にモデルが自動ダウンロードされます（kotoba-v2.0: 約1.5GB）。

## プロジェクト構成

```
├── backend/              # FastAPI バックエンド
│   ├── api/              #   REST API + WebSocket エンドポイント
│   ├── core/             #   音声処理・STT・話者分離・要約
│   ├── models/           #   Pydantic スキーマ・セッション管理
│   ├── services/         #   通話検出等
│   └── storage/          #   ファイルベースストレージ
├── frontend/             # Gradio フロントエンド
├── tauri-app/            # Tauri デスクトップアプリ (React + Rust)
│   ├── src/              #   React UI コンポーネント
│   └── src-tauri/        #   Rust バックエンド (sidecar管理等)
├── scripts/start.py      # 統合起動スクリプト
├── pyproject.toml        # Python依存定義
└── .env                  # 環境変数（Git管理外）
```

## データ保存先

ランタイムデータは `%APPDATA%\transcriber\` に保存されます：

```
%APPDATA%\transcriber\
├── sessions/       # セッションごとの文字起こし・要約・録音
├── speakers/       # 話者プロファイル（embedding + サンプル）
└── dictionary.json # 辞書ルール
```

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `torch.cuda.is_available()` が False | CUDA版PyTorchを再インストール |
| pyannoteモデルDLで403 | HuggingFaceでモデルライセンスに同意 + HF_TOKEN確認 |
| cuDNN crash | `torch.backends.cudnn.enabled = False` が設定済み（config参照） |
| ループバック音声が取れない | WASAPIデバイスが有効か確認。仮想オーディオは非対応の場合あり |
| 初回起動が遅い | モデルDL中。2回目以降はキャッシュから即座にロード |
