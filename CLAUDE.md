# Transcriber - リアルタイム会議文字起こしツール

## Architecture
- Backend: FastAPI (Python 3.11.9) at localhost:8000
  - Whisper (kotoba-v2.0), Silero VAD, pyannote speaker ID, Gemini summary
  - GPU: RTX 4070 Ti (12GB VRAM)
  - venv: `E:\transcriber\.venv\`
- Frontend: Tauri 2.0 + React 19 + TypeScript + Vite 7 + Tailwind CSS 4
  - Location: `E:\transcriber\tauri-app\`
- Data: `E:\transcriber\data\` (dictionary, speakers, sessions, corrections)
- 通信: React → FastAPI 直接 (fetch/WebSocket)、Tauri IPC 経由ではない

## Build & Verify Commands
```bash
# Backendテスト
powershell.exe -Command "cd E:\transcriber; .venv\Scripts\python.exe -m pytest tests/ -v"

# Backend起動
powershell.exe -Command "cd E:\transcriber; .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"

# フロントエンド型チェック
powershell.exe -Command "cd E:\transcriber\tauri-app; npx tsc --noEmit"

# フルビルド
powershell.exe -Command "cd E:\transcriber; .\build_sidecar.ps1"
powershell.exe -Command "cd E:\transcriber\tauri-app; npx tauri build"
powershell.exe -Command "cd E:\transcriber; .\deploy.ps1"
```

## Key Patterns
- 常時接続WebSocketでステートフルな`last_index`を使う場合、サーバー側でセッションリセットを検知する仕組みが必須
- PyAudio (PortAudio) の初期化はWindows WASAPIで遅い → セッション間で再利用すべき
- asyncハンドラー内の同期I/OはイベントループブロックのMOTO凶 → `run_in_executor` 必須
- npm install は必ずWindows側から: `powershell.exe -Command "cd E:\transcriber\tauri-app; npm install"`
- NSIS 2GB制限のためsidecarは deploy.ps1 でアセンブル

## Key APIs
- REST: /api/health, /session, /speakers, /dictionary, /transcripts, /summary
- WebSocket: ws://localhost:8000/ws/transcript
- PATCH /api/session/entries/{entry_id} — ライブセッション編集
- PATCH /api/transcripts/{session_id}/entries/{entry_id} — 保存済み編集

## Rules
- Python変更後は pytest を通すこと
- フロントエンド変更後は tsc --noEmit を通すこと
- git author未設定のためコミット時は設定が必要
