"""Real-time transcription tab."""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import threading
import time

import gradio as gr
import websocket  # websocket-client

from frontend import api_client

logger = logging.getLogger(__name__)

# Speaker colors for visual distinction
SPEAKER_COLORS = [
    "#4FC3F7", "#81C784", "#FFB74D", "#F06292",
    "#BA68C8", "#4DB6AC", "#FFD54F", "#E57373",
]


def _speaker_color(name: str, _cache: dict = {}) -> str:
    """Assign a consistent color based on speaker name hash."""
    if name not in _cache:
        # Use hash for cross-session consistency
        idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(SPEAKER_COLORS)
        _cache[name] = SPEAKER_COLORS[idx]
    return _cache[name]


def _esc(s: str) -> str:
    return html_mod.escape(s)


def _format_entry(entry: dict, index: int) -> str:
    speaker = _esc(entry.get("speaker_name", "Unknown"))
    text = _esc(entry.get("text", ""))
    color = _speaker_color(entry.get("speaker_name", "Unknown"))
    t_start = entry.get("timestamp_start", 0)
    mins, secs = divmod(int(t_start), 60)
    return (
        f'<div style="margin:4px 0;padding:6px 10px;border-left:3px solid {color};'
        f'background:rgba(255,255,255,0.03);border-radius:4px;">'
        f'<span style="color:#666;font-size:0.7em;margin-right:6px;">#{index}</span>'
        f'<span style="color:{color};font-weight:600;font-size:0.85em;">'
        f'{speaker}</span>'
        f'<span style="color:#888;font-size:0.75em;margin-left:8px;">'
        f'{mins:02d}:{secs:02d}</span><br/>'
        f'<span style="color:#e0e0e0;">{text}</span></div>'
    )


def _format_all_entries(entries: list[dict]) -> str:
    if not entries:
        return '<div style="color:#888;padding:20px;text-align:center;">録音を開始してください…</div>'
    return "".join(_format_entry(e, i) for i, e in enumerate(entries))


def _call_notification_html(call: dict) -> str:
    """Render a call detection notification banner."""
    display_name = _esc(call.get("display_name", "通話"))
    window_title = _esc(call.get("window_title", ""))
    return (
        f'<div style="padding:12px 16px;margin:8px 0;border-radius:8px;'
        f'background:linear-gradient(135deg,#1a237e,#283593);'
        f'border:2px solid #5c6bc0;animation:pulse 2s infinite;">'
        f'<div style="display:flex;align-items:center;gap:10px;">'
        f'<span style="font-size:1.5em;">📞</span>'
        f'<div style="flex:1;">'
        f'<div style="color:#e8eaf6;font-weight:700;font-size:1.1em;">'
        f'{display_name} を検知しました</div>'
        f'<div style="color:#9fa8da;font-size:0.85em;margin-top:2px;">'
        f'{window_title}</div>'
        f'</div>'
        f'</div>'
        f'<style>@keyframes pulse{{0%,100%{{border-color:#5c6bc0}}'
        f'50%{{border-color:#7986cb}}}}</style>'
        f'</div>'
    )


def _no_notification_html() -> str:
    return '<div></div>'


def build_tab():
    entries: list[dict] = []
    ws_thread: threading.Thread | None = None
    ws_conn: websocket.WebSocketApp | None = None
    is_connected = threading.Event()
    # Call detection state
    _pending_call: dict = {}  # current pending call notification
    _pending_lock = threading.Lock()
    # Shared session status cache (refreshed by get_status, used by poll_call_detection)
    _last_session_status: dict = {}

    def _on_message(wsapp, message):
        data = json.loads(message)
        if data.get("type") == "entry":
            entries.append(data["data"])

    def _on_open(wsapp):
        is_connected.set()

    def _on_close(wsapp, close_status, close_msg):
        is_connected.clear()

    def _on_error(wsapp, error):
        is_connected.clear()

    def connect_ws():
        nonlocal ws_conn, ws_thread
        # If old thread is still alive, force-close and wait for it to die
        if ws_thread and ws_thread.is_alive():
            if ws_conn:
                ws_conn.close()
            ws_thread.join(timeout=3.0)
            if ws_thread.is_alive():
                logger.warning("Old WebSocket thread did not terminate in time")
        entries.clear()
        ws_conn = websocket.WebSocketApp(
            "ws://127.0.0.1:8000/ws/transcript",
            on_message=_on_message,
            on_open=_on_open,
            on_close=_on_close,
            on_error=_on_error,
        )
        ws_thread = threading.Thread(target=ws_conn.run_forever, daemon=True)
        ws_thread.start()

    def disconnect_ws():
        nonlocal ws_conn, ws_thread
        if ws_conn:
            ws_conn.close()
            is_connected.clear()
        if ws_thread:
            ws_thread.join(timeout=3.0)
            ws_thread = None

    def start_recording(loopback_idx, session_name):
        try:
            lb_idx = int(loopback_idx) if loopback_idx not in (None, "", "None") else None
        except (ValueError, TypeError):
            lb_idx = None
        name = session_name.strip() if session_name else ""
        try:
            result = api_client.session_start(None, lb_idx, session_name=name)
            connect_ws()
            display = name or result.get('session_id', '')
            return f"✔ セッション開始: {display}"
        except Exception as e:
            return f"✘ エラー: {e}"

    def stop_recording():
        try:
            result = api_client.session_stop()
            disconnect_ws()
            sid = result.get("session_id", "")
            return f"✔ セッション停止: {sid}", sid
        except Exception as e:
            return f"✘ エラー: {e}", ""

    def pause_recording():
        try:
            result = api_client.session_pause()
            status = result.get("status", "")
            label = "一時停止" if status == "paused" else "再開"
            return f"✔ {label}"
        except Exception as e:
            return f"✘ エラー: {e}"

    def refresh_transcript():
        return _format_all_entries(entries)

    def get_status():
        try:
            info = api_client.session_status()
            _last_session_status.clear()
            _last_session_status.update(info)
            status = info.get("status", "idle")
            labels = {
                "idle": "⏹ 停止中",
                "starting": "⏳ 起動中…",
                "running": "🔴 録音中",
                "paused": "⏸ 一時停止",
                "stopping": "⏳ 停止中…",
            }
            count = info.get("entry_count", 0)
            name = info.get("session_name", "")
            name_part = f" [{name}]" if name else ""
            # VAD activity indicators
            vad_parts = []
            if info.get("mic_speaking"):
                vad_parts.append("🎙️MIC")
            if info.get("loopback_speaking"):
                vad_parts.append("🔊PC")
            vad_str = f" | 🟢 {' + '.join(vad_parts)}" if vad_parts else ""
            return f"{labels.get(status, status)}{name_part} | {count} 件{vad_str}"
        except Exception:
            return "⚠ バックエンド未接続"

    def get_devices():
        try:
            data = api_client.audio_devices()
            devices = data.get("devices", [])
            loopback_choices = [("なし", "")] + [
                (f"{d['name']} (idx={d['index']})", str(d["index"]))
                for d in devices if d.get("is_loopback")
            ]
            default_lb = data.get("default_loopback_index")
            lb_val = str(default_lb) if default_lb is not None else ""
            return gr.Dropdown(choices=loopback_choices, value=lb_val)
        except Exception:
            return gr.Dropdown(choices=[("なし", "")], value="")

    def poll_call_detection():
        """Poll backend for call detection notifications (runs every second via timer)."""
        # Use cached session status from get_status() to avoid duplicate API call
        if _last_session_status.get("status", "idle") != "idle":
            with _pending_lock:
                _pending_call.clear()
            return _no_notification_html()

        try:
            data = api_client.call_detection_pending()
            calls = data.get("calls", [])
            if calls:
                with _pending_lock:
                    _pending_call.clear()
                    _pending_call.update(calls[0])  # show latest
                return _call_notification_html(calls[0])
        except Exception:
            pass

        with _pending_lock:
            if _pending_call:
                return _call_notification_html(_pending_call)
        return _no_notification_html()

    def accept_call(loopback_idx):
        """Accept detected call and start recording with suggested session name."""
        with _pending_lock:
            call = dict(_pending_call)
            _pending_call.clear()

        if not call:
            return "⚠ 通知がありません", _no_notification_html()

        suggestion = call.get("session_name_suggestion", "")
        try:
            lb_idx = int(loopback_idx) if loopback_idx not in (None, "", "None") else None
        except (ValueError, TypeError):
            lb_idx = None

        try:
            result = api_client.session_start(None, lb_idx, session_name=suggestion)
            connect_ws()
            display = suggestion or result.get('session_id', '')
            return f"✔ セッション開始: {display}", _no_notification_html()
        except Exception as e:
            return f"✘ エラー: {e}", _no_notification_html()

    def dismiss_call():
        """Dismiss the current call notification."""
        with _pending_lock:
            window_title = _pending_call.get("window_title", "")
            _pending_call.clear()
        try:
            api_client.call_detection_dismiss(window_title)
        except Exception:
            pass
        return _no_notification_html()

    with gr.Column():
        gr.Markdown("## リアルタイム文字起こし")

        # Call detection notification banner
        call_notification_html = gr.HTML(value=_no_notification_html())
        with gr.Row(visible=True) as call_action_row:
            accept_call_btn = gr.Button("🔴 録音開始", variant="primary", scale=1, visible=True)
            dismiss_call_btn = gr.Button("✕ 無視", scale=1, visible=True)

        with gr.Row():
            loopback_dd = gr.Dropdown(
                label="ループバック (PC音声)",
                choices=[],
                interactive=True,
                scale=5,
            )
            refresh_dev_btn = gr.Button("🔄", scale=0, min_width=50)

        session_name_input = gr.Textbox(
            label="MTG名",
            placeholder="例: 週次定例、顧客A打ち合わせ",
            scale=1,
        )

        with gr.Row():
            start_btn = gr.Button("▶ 開始", variant="primary", scale=1)
            pause_btn = gr.Button("⏸ 一時停止", scale=1)
            stop_btn = gr.Button("⏹ 停止", variant="stop", scale=1)

        status_txt = gr.Textbox(label="ステータス", value="⏹ 停止中", interactive=False)

        transcript_html = gr.HTML(
            value='<div style="color:#888;padding:20px;text-align:center;">録音を開始してください…</div>',
            label="トランスクリプト",
        )

        with gr.Accordion("話者登録", open=False):
            gr.Markdown("文字起こし中のエントリ番号(#)を指定して、話者を登録できます。")
            with gr.Row():
                reg_index = gr.Number(label="エントリ #", precision=0, scale=1)
                reg_name = gr.Textbox(label="話者名", placeholder="例: 田中", scale=2)
                reg_btn = gr.Button("登録", variant="primary", scale=1)
            reg_msg = gr.Textbox(label="結果", interactive=False)

        msg_txt = gr.Textbox(label="メッセージ", interactive=False, visible=False)
        stopped_session_id = gr.State(value="")

    def do_register_speaker(entry_idx, name):
        if not name or not name.strip():
            return "⚠ 話者名を入力してください。", gr.skip()
        try:
            idx = int(entry_idx)
        except (ValueError, TypeError):
            return "⚠ エントリ番号を入力してください。", gr.skip()
        try:
            result = api_client.register_speaker_from_entry(idx, name.strip())
            # Update local entries from backend response
            updated = result.get("entries", [])
            if updated:
                entries.clear()
                entries.extend(updated)
            speaker = result.get("speaker", {})
            return (
                f"✔ 話者「{speaker.get('name', name)}」を登録しました。",
                _format_all_entries(entries),
            )
        except Exception as e:
            return f"✘ エラー: {e}", gr.skip()

    # Event bindings
    start_btn.click(fn=start_recording, inputs=[loopback_dd, session_name_input], outputs=[msg_txt])
    stop_event = stop_btn.click(fn=stop_recording, outputs=[msg_txt, stopped_session_id])
    pause_btn.click(fn=pause_recording, outputs=[msg_txt])
    refresh_dev_btn.click(fn=get_devices, outputs=[loopback_dd])
    reg_btn.click(fn=do_register_speaker, inputs=[reg_index, reg_name], outputs=[reg_msg, transcript_html])

    # Call detection buttons
    accept_call_btn.click(
        fn=accept_call,
        inputs=[loopback_dd],
        outputs=[msg_txt, call_notification_html],
    )
    dismiss_call_btn.click(
        fn=dismiss_call,
        outputs=[call_notification_html],
    )

    # Auto-refresh transcript, status, and call detection via timer
    timer = gr.Timer(value=1.0)
    timer.tick(fn=refresh_transcript, outputs=[transcript_html])
    timer.tick(fn=get_status, outputs=[status_txt])
    timer.tick(fn=poll_call_detection, outputs=[call_notification_html])

    return get_devices, [loopback_dd], stop_event, stopped_session_id
