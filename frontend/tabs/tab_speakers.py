"""Speaker management tab."""

from __future__ import annotations

import gradio as gr

from frontend import api_client


def _speakers_table(speakers: list[dict]) -> str:
    if not speakers:
        return '<div style="color:#888;padding:12px;">登録された話者はありません。</div>'
    rows = ""
    for s in speakers:
        sid = s["id"]
        name = s["name"]
        samples = s.get("sample_count", 0)
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;'>{name}</td>"
            f"<td style='padding:6px 12px;'>{samples} 件</td>"
            f"<td style='padding:6px 12px;font-size:0.8em;color:#888;'>{sid[:8]}…</td>"
            f"</tr>"
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        "<thead><tr>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>名前</th>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>サンプル数</th>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>ID</th>"
        "</tr></thead><tbody>"
        f"{rows}</tbody></table>"
    )


def build_tab():
    def refresh_speakers():
        try:
            speakers = api_client.list_speakers()
            table_html = _speakers_table(speakers)
            choices = [(s["name"], s["id"]) for s in speakers]
            return table_html, gr.Dropdown(choices=choices, value=choices[0][1] if choices else None)
        except Exception as e:
            return f"<div style='color:red;'>エラー: {e}</div>", gr.Dropdown(choices=[], value=None)

    def register_speaker(name: str, files):
        if not name or not name.strip():
            return "⚠ 名前を入力してください。"
        if not files:
            return "⚠ 音声ファイルをアップロードしてください。"
        try:
            opened = []
            for f in files:
                path = f if isinstance(f, str) else f.name
                opened.append(open(path, "rb"))
            result = api_client.register_speaker(name.strip(), opened)
            for fh in opened:
                fh.close()
            return f"✔ 話者「{name}」を登録しました (ID: {result.get('speaker_id', '')[:8]}…)"
        except Exception as e:
            return f"✘ 登録エラー: {e}"

    def delete_speaker(speaker_id: str):
        if not speaker_id:
            return "⚠ 削除する話者を選択してください。"
        try:
            api_client.delete_speaker(speaker_id)
            return f"✔ 話者を削除しました。"
        except Exception as e:
            return f"✘ 削除エラー: {e}"

    with gr.Column():
        gr.Markdown("## 👤 話者管理")

        with gr.Accordion("話者を登録", open=True):
            name_input = gr.Textbox(label="話者名", placeholder="例: 田中太郎")
            audio_files = gr.File(
                label="音声サンプル (WAVファイル, 複数可)",
                file_count="multiple",
                file_types=[".wav", ".mp3", ".flac"],
            )
            register_btn = gr.Button("📝 登録", variant="primary")
            register_msg = gr.Textbox(label="結果", interactive=False)

        gr.Markdown("### 登録済み話者")
        refresh_btn = gr.Button("🔄 更新")
        speakers_html = gr.HTML(value='<div style="color:#888;">読み込み中…</div>')

        with gr.Row():
            delete_dd = gr.Dropdown(label="削除する話者", choices=[], interactive=True, scale=3)
            delete_btn = gr.Button("🗑 削除", variant="stop", scale=1)
        delete_msg = gr.Textbox(label="結果", interactive=False)

    # Events
    register_btn.click(
        fn=register_speaker,
        inputs=[name_input, audio_files],
        outputs=[register_msg],
    ).then(fn=refresh_speakers, outputs=[speakers_html, delete_dd])

    delete_btn.click(
        fn=delete_speaker,
        inputs=[delete_dd],
        outputs=[delete_msg],
    ).then(fn=refresh_speakers, outputs=[speakers_html, delete_dd])

    refresh_btn.click(fn=refresh_speakers, outputs=[speakers_html, delete_dd])

    return refresh_speakers, [speakers_html, delete_dd]
