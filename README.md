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

## 構成パターン

本プロジェクトは2つの構成で利用できます。

| 構成 | 説明 |
|------|------|
| **ローカル** | 1台のGPU PCでバックエンド＋フロントエンドを動かす |
| **リモート** | GPUサーバーでバックエンドを常時起動し、他PCからフロントエンドのみ接続（Tailscale VPN経由） |

## セットアップ（バックエンド / GPUサーバー）

### 1. リポジトリクローン

```bash
git clone https://github.com/kiku-beep/meeting-transcriber.git
cd meeting-transcriber
```

### 2. Python仮想環境 + 依存インストール

```powershell
# 通常版Python必須（Microsoft Store版は不可）
python -m venv .venv
.venv\Scripts\activate

# CUDA版PyTorchを先にインストール（必須）
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124

# プロジェクト依存
pip install -e .

# ctranslate2 は 3.24.0 に固定（4.x は segfault する）
pip install ctranslate2==3.24.0 --no-deps
```

> **重要**:
> - `pip install -e .` だけだとCPU版PyTorchが入る場合があります。必ずCUDA版を先にインストールしてください。
> - ctranslate2 は他パッケージが 4.x に戻すことがあるため、`pip install ctranslate2==3.24.0 --no-deps` で再固定が必要な場合があります。

### 3. HuggingFaceモデルアクセス承認

pyannote話者分離モデルを使うため、以下のHuggingFaceモデルページでライセンスに同意してください：

- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
- [pyannote/wespeaker-voxceleb-resnet34-LM](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM)

### 4. .env ファイル作成

`%APPDATA%\transcriber\.env` を作成：

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

### 5. フロントエンド依存（Tauriアプリの場合）

```powershell
cd tauri-app
npm install
cd ..
```

## 起動方法

### ローカル構成

#### Gradioフロントエンド（シンプル起動）

```powershell
.venv\Scripts\python.exe scripts\start.py
```

- Backend: http://127.0.0.1:8000
- Frontend: http://127.0.0.1:7860
- Ctrl+C で停止

#### Tauriデスクトップアプリ

```powershell
cd tauri-app
npm run tauri dev
```

### リモート構成

#### GPUサーバー側（バックエンド）

```powershell
# Tailscale IP にバインドしてサーバー起動
scripts\start_server.ps1
```

`start_server.ps1` は以下を自動設定します：
- Tailscale IP (`100.116.182.31`) へのバインド
- `KMP_DUPLICATE_LIB_OK=TRUE`（OpenMP重複ライブラリ回避）
- サーバーモード（`DEPLOYMENT_MODE=server`）

検証版はTailscale VPN内のみの利用を前提に、デフォルトではアプリ側の共有認証トークンを設定しません。
追加でトークン認証を使う場合のみ `scripts\start_server.ps1 -AuthToken "任意のトークン"` で起動します。

> PC再起動後は `start_server.ps1` を再度実行する必要があります。

#### クライアント側（フロントエンドのみ）

GPU不要。Node.js + Rust + Tailscale があれば動作します。

```bash
# 1. Tailscale をインストールし、同じ tailnet にログイン
# 2. リポジトリをクローン
git clone https://github.com/kiku-beep/meeting-transcriber.git
cd meeting-transcriber/tauri-app
npm install

# 3. 接続先を設定（.env.remote をコピー）
cp .env.remote .env.local

# 4. 起動
npm run tauri dev
```

> `.env.remote` にサーバーの Tailscale URL がプリセットされています。
> 環境変数 `VITE_BACKEND_URL` でバックエンドの接続先を変更できます。
> 未設定時は `http://127.0.0.1:8000`（ローカル）に接続します。

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
├── scripts/start.py      # 統合起動スクリプト（ローカル用）
├── scripts/start_server.ps1  # サーバーモード起動（Tailscale VPN用）
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

## 技術的な注意事項

### Windows + PyTorch 2.6 での既知の問題

以下の問題は `backend/main.py` と `backend/core/diarizer.py` で対処済みです：

- **cuDNN クラッシュ**: Windows + cuDNN 9.x で `cudnnGetLibConfig` がスタックバッファオーバーランを起こす。`torch.backends.cudnn.enabled = False` で無効化済み。
- **weights_only エラー**: PyTorch 2.6 で `torch.load` の `weights_only` デフォルトが `True` に変更され、pyannote のチェックポイント読み込みが失敗する。`diarizer.py` で `torch.load` をモンキーパッチして回避済み。
- **CUDA 初期化レース**: 複数モデルを並行ロードすると CUDA 初期化でクラッシュする場合がある。`main.py` で起動時に CUDA コンテキストを先行初期化し、モデルは順次ロードに変更済み。
- **ctranslate2 バージョン**: 4.x は segfault するため `3.24.0` に固定必須。`--no-deps` で他の依存に引きずられないようにする。
- **Python バージョン**: Microsoft Store 版 Python ではパスやサンドボックスの問題が発生する。通常版（python.org）を使用すること。

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `torch.cuda.is_available()` が False | CUDA版PyTorchを再インストール |
| pyannoteモデルDLで403 | HuggingFaceでモデルライセンスに同意 + HF_TOKEN確認 |
| cuDNN crash（0xC0000409） | `torch.backends.cudnn.enabled = False` が設定済み（main.py参照） |
| `weights_only` / `UnpicklingError` | diarizer.py の torch.load パッチが適用されているか確認 |
| ctranslate2 で segfault | `pip install ctranslate2==3.24.0 --no-deps` で再固定 |
| ループバック音声が取れない | WASAPIデバイスが有効か確認。仮想オーディオは非対応の場合あり |
| 初回起動が遅い | モデルDL中。2回目以降はキャッシュから即座にロード |
| リモート接続できない | Tailscale が両端で接続済みか確認。`tailscale status` で確認可能 |
