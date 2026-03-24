"""Session history and transcript viewer tab."""

from __future__ import annotations

import gradio as gr

from frontend import api_client


def build_tab():
    def refresh_sessions():
        try:
            sessions = api_client.list_sessions()
            if not sessions:
                return gr.Dropdown(choices=[], value=None), "セッション履歴はありません。"
            choices = []
            for s in sessions:
                sid = s.get("session_id", "")
                started = s.get("started_at", "")[:19]
                count = s.get("entry_count", 0)
                name = s.get("session_name", "")
                if name:
                    label = f"{name} - {started} ({count}件)"
                else:
                    label = f"{started} ({count}件) [{sid[:8]}…]"
                choices.append((label, sid))
            return gr.Dropdown(choices=choices, value=choices[0][1] if choices else None), ""
        except Exception as e:
            return gr.Dropdown(choices=[], value=None), f"エラー: {e}"

    def view_transcript(session_id: str):
        if not session_id:
            return "セッションを選択してください。"
        try:
            data = api_client.get_transcript(session_id)
            entries = data.get("entries", [])
            if not entries:
                return "エントリーがありません。"
            lines = []
            for e in entries:
                speaker = e.get("speaker_name", "Unknown")
                text = e.get("text", "")
                t = e.get("timestamp_start", 0)
                mins, secs = divmod(int(t), 60)
                lines.append(f"[{mins:02d}:{secs:02d}] {speaker}: {text}")
            return "\n".join(lines)
        except Exception as e:
            return f"エラー: {e}"

    def view_summary(session_id: str):
        if not session_id:
            return "セッションを選択してください。"
        try:
            data = api_client.get_summary(session_id)
            return data.get("summary", "要約がありません。")
        except Exception:
            return "要約がありません。「要約生成」ボタンで生成できます。"

    def _format_usage(usage: dict) -> str:
        if not usage:
            return ""
        input_t = usage.get("input_tokens", 0)
        output_t = usage.get("output_tokens", 0)
        total_t = usage.get("total_tokens", 0)
        cost = usage.get("cost_usd", 0)
        model = usage.get("model", "")
        # 1 USD ≈ 150 JPY
        cost_jpy = cost * 150
        return (
            f"\n\n---\n"
            f"*{model} | "
            f"入力: {input_t:,} tokens, 出力: {output_t:,} tokens, "
            f"合計: {total_t:,} tokens | "
            f"${cost:.4f} (約{cost_jpy:.2f}円)*"
        )

    def do_generate_summary(session_id: str):
        if not session_id:
            return "セッションを選択してください。", gr.skip(), gr.skip()
        try:
            data = api_client.generate_summary(session_id)
            summary = data.get("summary", "要約の生成に失敗しました。")
            usage = data.get("usage", {})
            summary_with_usage = summary + _format_usage(usage)
            # Refresh session list (name may have been auto-set)
            dd_update, _ = refresh_sessions()
            return summary_with_usage, dd_update, gr.skip()
        except Exception as e:
            return f"エラー: {e}", gr.skip(), gr.skip()

    def auto_load_and_summarize(session_id: str):
        """Called after stop: refresh list, select session, generate summary."""
        if not session_id:
            return gr.skip(), gr.skip(), gr.skip(), gr.skip()
        try:
            # Refresh session list
            sessions = api_client.list_sessions()
            choices = []
            for s in sessions:
                sid = s.get("session_id", "")
                started = s.get("started_at", "")[:19]
                count = s.get("entry_count", 0)
                name = s.get("session_name", "")
                if name:
                    label = f"{name} - {started} ({count}件)"
                else:
                    label = f"{started} ({count}件) [{sid[:8]}…]"
                choices.append((label, sid))
            dd_update = gr.Dropdown(choices=choices, value=session_id)

            # Load transcript
            transcript = view_transcript(session_id)

            # Skip summary generation if no entries
            entry_count = next(
                (s.get("entry_count", 0) for s in sessions if s.get("session_id") == session_id), 0
            )
            if not entry_count:
                return dd_update, "", transcript, "エントリーがないため要約は生成できません。"

            # Generate summary
            data = api_client.generate_summary(session_id)
            summary = data.get("summary", "要約の生成に失敗しました。")
            usage = data.get("usage", {})
            summary_with_usage = summary + _format_usage(usage)

            # Re-refresh list (name may have been auto-set by summary)
            sessions2 = api_client.list_sessions()
            choices2 = []
            for s in sessions2:
                sid = s.get("session_id", "")
                started = s.get("started_at", "")[:19]
                count = s.get("entry_count", 0)
                name = s.get("session_name", "")
                if name:
                    label = f"{name} - {started} ({count}件)"
                else:
                    label = f"{started} ({count}件) [{sid[:8]}…]"
                choices2.append((label, sid))
            dd_final = gr.Dropdown(choices=choices2, value=session_id)

            return dd_final, "", transcript, summary_with_usage
        except Exception as e:
            # At minimum refresh the list and show transcript
            try:
                dd_update, _ = refresh_sessions()
                transcript = view_transcript(session_id)
                return dd_update, "", transcript, f"要約生成エラー: {e}"
            except Exception:
                return gr.skip(), gr.skip(), gr.skip(), f"エラー: {e}"

    def export_transcript(session_id: str, fmt: str):
        if not session_id:
            return "セッションを選択してください。"
        try:
            text = api_client.export_transcript(session_id, fmt)
            return text
        except Exception as e:
            return f"エラー: {e}"

    def do_delete_session(session_id: str):
        if not session_id:
            return "セッションを選択してください。", gr.skip(), gr.skip()
        try:
            api_client.delete_session(session_id)
            # Refresh the list after deletion
            dd_update, msg = refresh_sessions()
            return f"✔ セッション {session_id} を削除しました。", dd_update, msg
        except Exception as e:
            return f"✘ エラー: {e}", gr.skip(), gr.skip()

    with gr.Column():
        gr.Markdown("## セッション履歴")

        with gr.Row():
            session_dd = gr.Dropdown(label="セッション", choices=[], interactive=True, scale=4)
            refresh_btn = gr.Button("🔄", scale=0, min_width=50)
            delete_btn = gr.Button("🗑 削除", variant="stop", scale=0, min_width=80)

        session_msg = gr.Textbox(interactive=False, visible=False)
        delete_msg = gr.Textbox(label="削除結果", interactive=False, visible=False)

        with gr.Tabs():
            with gr.Tab("トランスクリプト"):
                transcript_txt = gr.Textbox(
                    label="トランスクリプト",
                    interactive=False,
                    lines=20,
                    max_lines=50,
                )

            with gr.Tab("要約"):
                summary_txt = gr.Markdown(
                    value="要約がありません。",
                    label="要約",
                )
                generate_btn = gr.Button("要約を生成 (Gemini)")

        with gr.Row():
            fmt_dd = gr.Dropdown(
                label="エクスポート形式",
                choices=[("テキスト", "txt"), ("JSON", "json"), ("Markdown (要約)", "md")],
                value="txt",
                interactive=True,
                scale=2,
            )
            export_btn = gr.Button("エクスポート", scale=1)
        export_txt = gr.Textbox(label="エクスポート結果", interactive=False, lines=10)

    # Events
    refresh_btn.click(fn=refresh_sessions, outputs=[session_dd, session_msg])
    delete_btn.click(fn=do_delete_session, inputs=[session_dd], outputs=[delete_msg, session_dd, session_msg])
    session_dd.change(fn=view_transcript, inputs=[session_dd], outputs=[transcript_txt])
    session_dd.change(fn=view_summary, inputs=[session_dd], outputs=[summary_txt])
    generate_btn.click(fn=do_generate_summary, inputs=[session_dd], outputs=[summary_txt, session_dd, session_msg])
    export_btn.click(fn=export_transcript, inputs=[session_dd, fmt_dd], outputs=[export_txt])

    # Components for cross-tab wiring
    auto_summarize_outputs = [session_dd, session_msg, transcript_txt, summary_txt]

    return (
        refresh_sessions, [session_dd, session_msg],
        auto_load_and_summarize, auto_summarize_outputs,
    )
