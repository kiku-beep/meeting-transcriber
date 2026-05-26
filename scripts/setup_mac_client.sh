#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR_DIR="$ROOT_DIR/audio_sidecar"
TAURI_DIR="$ROOT_DIR/tauri-app"

python3 -m venv "$SIDECAR_DIR/.venv"
"$SIDECAR_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SIDECAR_DIR/.venv/bin/python" -m pip install -r "$SIDECAR_DIR/requirements.txt"

cd "$TAURI_DIR"
npm install

if [[ ! -f "$TAURI_DIR/.env.local" && -f "$TAURI_DIR/.env.remote" ]]; then
  cp "$TAURI_DIR/.env.remote" "$TAURI_DIR/.env.local"
fi

echo "Mac client setup complete."
if ! command -v cargo >/dev/null 2>&1; then
  echo "Warning: Rust/Cargo is not installed. Install Rust before running the Tauri app."
fi
echo "Run: cd $TAURI_DIR && npm run tauri dev"
