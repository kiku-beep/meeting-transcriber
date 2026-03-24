"""Settings and system status tab."""

from __future__ import annotations

import gradio as gr

from frontend import api_client


def build_tab():
    def check_health():
        try:
            h = api_client.health()
            return f"✔ バックエンド: {h.get('status', 'unknown')}"
        except Exception as e:
            return f"✘ バックエンド未接続: {e}"

    def check_gpu():
        try:
            g = api_client.gpu_status()
            name = g.get("gpu_name", "N/A")
            vram_used = g.get("vram_used_mb", 0)
            vram_total = g.get("vram_total_mb", 0)
            temp = g.get("temperature_c", "N/A")
            pct = (vram_used / vram_total * 100) if vram_total > 0 else 0
            return (
                f"GPU: {name}\n"
                f"VRAM: {vram_used:.0f} / {vram_total:.0f} MB ({pct:.1f}%)\n"
                f"温度: {temp}°C"
            )
        except Exception as e:
            return f"GPU情報取得エラー: {e}"

    def list_devices():
        try:
            data = api_client.audio_devices()
            devices = data.get("devices", [])
            default_mic = data.get("default_mic_index")
            default_loopback = data.get("default_loopback_index")
            lines = []
            for d in devices:
                idx = d["index"]
                label = ""
                if idx == default_mic:
                    label = " [デフォルトマイク]"
                elif idx == default_loopback:
                    label = " [デフォルトループバック]"
                lines.append(
                    f"  [{idx}] {d['name']} "
                    f"(入力ch={d.get('max_input_channels', 0)}, "
                    f"出力ch={d.get('max_output_channels', 0)}, "
                    f"{d.get('default_sample_rate', 0):.0f}Hz){label}"
                )
            return "\n".join(lines) if lines else "デバイスが見つかりません。"
        except Exception as e:
            return f"デバイス取得エラー: {e}"

    def get_model_info():
        try:
            data = api_client.get_model()
            current = data.get("current_model", "?")
            loaded = "ロード済み" if data.get("is_loaded") else "未ロード"
            models = data.get("available_models", [])
            choices = [(f"{m['name']} ({m['vram_mb']}MB)", m["name"]) for m in models]
            return (
                gr.Dropdown(choices=choices, value=current),
                f"現在のモデル: {current} ({loaded})",
            )
        except Exception as e:
            return (
                gr.Dropdown(choices=[
                    ("tiny (150MB)", "tiny"),
                    ("base (300MB)", "base"),
                    ("small (1000MB)", "small"),
                    ("medium (2500MB)", "medium"),
                    ("large-v3 (4500MB)", "large-v3"),
                    ("kotoba-v2.0 日本語特化 (2500MB)", "kotoba-v2.0"),
                ], value="kotoba-v2.0"),
                f"モデル情報取得エラー: {e}",
            )

    def do_switch_model(model_size):
        if not model_size:
            return "モデルを選択してください。"
        try:
            result = api_client.switch_model(model_size)
            loaded = "ロード済み" if result.get("is_loaded") else "未ロード"
            return f"✔ モデル切替完了: {result.get('model_size')} ({loaded})"
        except Exception as e:
            return f"✘ モデル切替エラー: {e}"

    def toggle_call_detection(enabled):
        try:
            api_client.call_detection_config(enabled=enabled)
            label = "有効" if enabled else "無効"
            return f"✔ 通話自動検知: {label}"
        except Exception as e:
            return f"✘ エラー: {e}"

    def get_call_detection_status():
        try:
            data = api_client.call_detection_config()
            return data.get("enabled", True)
        except Exception:
            return True

    with gr.Column():
        gr.Markdown("## ⚙ 設定・システム情報")

        with gr.Accordion("通話自動検知", open=True):
            gr.Markdown("Google Meet / Slack ハドルのウィンドウを検知して録音開始を提案します。")
            call_detect_toggle = gr.Checkbox(
                label="通話自動検知を有効にする",
                value=True,
                interactive=True,
            )
            call_detect_status = gr.Textbox(label="状態", interactive=False)

        with gr.Accordion("Whisper モデル", open=True):
            with gr.Row():
                model_dd = gr.Dropdown(
                    label="モデルサイズ",
                    choices=[
                        ("kotoba-v2.0 日本語特化 (2500MB)", "kotoba-v2.0"),
                        ("tiny (150MB)", "tiny"),
                        ("base (300MB)", "base"),
                        ("small (1000MB)", "small"),
                        ("medium (2500MB)", "medium"),
                        ("large-v3 (4500MB)", "large-v3"),
                    ],
                    value="kotoba-v2.0",
                    interactive=True,
                    scale=3,
                )
                switch_btn = gr.Button("🔄 切替", scale=1)
            model_status_txt = gr.Textbox(label="モデル状態", interactive=False)

        with gr.Accordion("バックエンド接続", open=True):
            health_txt = gr.Textbox(label="ヘルスチェック", interactive=False)
            health_btn = gr.Button("🔍 チェック")

        with gr.Accordion("GPU ステータス", open=True):
            gpu_txt = gr.Textbox(label="GPU情報", interactive=False, lines=3)
            gpu_btn = gr.Button("🔄 更新")

        with gr.Accordion("オーディオデバイス", open=True):
            devices_txt = gr.Textbox(label="検出デバイス一覧", interactive=False, lines=8)
            devices_btn = gr.Button("🔄 更新")

    # Events
    call_detect_toggle.change(
        fn=toggle_call_detection,
        inputs=[call_detect_toggle],
        outputs=[call_detect_status],
    )
    switch_btn.click(fn=do_switch_model, inputs=[model_dd], outputs=[model_status_txt])
    health_btn.click(fn=check_health, outputs=[health_txt])
    gpu_btn.click(fn=check_gpu, outputs=[gpu_txt])
    devices_btn.click(fn=list_devices, outputs=[devices_txt])

    def load_all():
        cd = get_call_detection_status()
        h = check_health()
        g = check_gpu()
        d = list_devices()
        md, ms = get_model_info()
        return cd, h, g, d, md, ms

    return load_all, [call_detect_toggle, health_txt, gpu_txt, devices_txt, model_dd, model_status_txt]
