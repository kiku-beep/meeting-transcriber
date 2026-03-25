# Remote Frontend Setup Report (2026-03-25)

## Summary
自宅PC（GPU無し）でTauriフロントエンドのみ起動し、会社PC（GPU搭載、Tailscale IP: 100.116.182.31）のバックエンドに接続する構成をセットアップした。

## Status: WS Audio 403で要バックエンド側調査

### 成功した部分
- Tauri + React フロントエンドのビルド・起動 OK
- Tailscale接続 OK（monochrome.so tailnet、デバイス承認済み）
- HTTP通信 OK（ヘルスチェック `GET /api/health` → 200 OK）
- React側WebSocket（`/ws/transcript`）接続 OK
- Settings画面でリモートURL設定・永続化 OK
- Python audio sidecar の依存関係インストール OK
- Audio sidecar の起動・ログ出力 OK

### 未解決: WebSocket `/ws/audio/{client_id}` が 403 Forbidden

#### 症状
- audio sidecar が `ws://100.116.182.31:8000/ws/audio/{client_id}?source=mic` に接続しようとすると **403 Forbidden** が返る
- mic / loopback 両方とも同じ403
- Pythonから直接 `websocket.create_connection()` で試しても同じ403
- HTTPのヘルスチェックは正常に通る

#### 403レスポンスの詳細
```
HTTP/1.1 403 Forbidden
Date: Wed, 25 Mar 2026 10:35:08 GMT
Content-Length: 0
Content-Type: text/plain
Connection: close
```

#### 除外した原因
1. **CORS設定**: `allow_origins=["*"]` で全許可済み → 問題なし
2. **auth_token**: `settings.auth_token` は空（未設定）→ 認証チェックはスキップされる
3. **deployment_mode**: `/ws/audio` ルートは `deployment_mode` に関係なく登録される
4. **Originヘッダー**: 明示的にOriginを設定しても変わらず403
5. **Tauri HTTP scope**: これはHTTP plugin用の制限で、Python sidecarには無関係

#### 可能性のある原因
1. **バックエンドが `127.0.0.1` でリッスン** → Tailscale経由のリクエストがリバースプロキシ等を経由している場合、WebSocketアップグレードが正しく転送されていない可能性
2. **Tailscale ACL/Funnel設定** → WebSocketのUpgradeリクエストをブロックしている可能性（HTTPは通るがWSは通らない）
3. **バックエンド側のミドルウェア** → Starlette/FastAPIレベルでWebSocket接続を拒否している何か
4. **バックエンドの`host`設定** → `backend_host: "127.0.0.1"` の場合、`0.0.0.0` に変更が必要かもしれない

#### 検証手順（バックエンドPC側で実施）
```bash
# 1. バックエンドのリッスンアドレス確認
# config.py の backend_host が "0.0.0.0" になっているか確認
# "127.0.0.1" だとリモートからアクセスできないはず（ただしHTTPは通っている）

# 2. バックエンドログでWS接続のリクエストが届いているか確認
# 403がバックエンドから返っているなら、uvicornログに記録があるはず

# 3. ローカルからWebSocket接続テスト（バックエンドPC上で）
python -c "
import websocket
ws = websocket.create_connection('ws://127.0.0.1:8000/ws/audio/test?source=mic', timeout=10)
print('Connected!')
ws.close()
"

# 4. deployment_mode を "server" に変更して起動
# config.py or 環境変数: TRANSCRIBER_DEPLOYMENT_MODE=server

# 5. 0.0.0.0 でリッスンさせる
# 環境変数: TRANSCRIBER_BACKEND_HOST=0.0.0.0
```

## 変更したファイル

### フロントエンド（このPC側）
| ファイル | 変更内容 |
|---------|---------|
| `tauri-app/src-tauri/tauri.conf.json` | `resources: ["sidecar/*"]` → `resources: []`（sidecar未ビルド時のエラー回避） |
| `tauri-app/src-tauri/capabilities/default.json` | Tailscale IP `100.116.182.31:8000` をHTTP許可リストに追加 |
| `tauri-app/src/components/BackendLoader.tsx` | 「スキップして設定画面へ」ボタン追加（バックエンド未接続時にSettings画面へ遷移可能に） |
| `tauri-app/src-tauri/src/audio_sidecar.rs` | dev modeのスクリプトパス解決修正（`.parent()` 4階層）+ stderr/stdoutログ出力強化 |
| `audio_sidecar/main.py` | WebSocket接続時にOriginヘッダーを明示的に設定（403対策、未解決） |

### バックエンド（リモートPC側・未テスト）
上記の変更はpush済み。バックエンド側で以下の確認が必要：
- `deployment_mode` を `"server"` に設定
- `backend_host` を `"0.0.0.0"` に設定
- `/ws/audio` エンドポイントへのWebSocket接続テスト

## 環境情報
- **フロントエンドPC**: Windows 11 Home, Python 3.12, Node.js, Rust (Cargo)
- **バックエンドPC**: Tailscale IP 100.116.182.31, RTX 4070 Ti
- **Tailscale**: monochrome.so tailnet、デバイス承認済み
