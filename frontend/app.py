"""Gradio frontend application."""

from __future__ import annotations

import gradio as gr

from frontend.tabs import tab_transcription, tab_speakers, tab_dictionary, tab_history, tab_settings


def create_app() -> gr.Blocks:
    with gr.Blocks(title="Transcriber") as app:
        gr.Markdown(
            "# Transcriber\n"
            "リアルタイム会議文字起こしツール"
        )

        with gr.Tabs() as tabs:
            with gr.Tab("文字起こし", id="transcription"):
                load_transcription, out_transcription, stop_event, stopped_session_id = (
                    tab_transcription.build_tab()
                )

            with gr.Tab("話者管理", id="speakers"):
                load_speakers, out_speakers = tab_speakers.build_tab()

            with gr.Tab("辞書設定", id="dictionary"):
                load_dict, out_dict = tab_dictionary.build_tab()

            with gr.Tab("履歴", id="history") as history_tab:
                load_history, out_history, auto_summarize, auto_summarize_outputs = (
                    tab_history.build_tab()
                )

            with gr.Tab("設定", id="settings"):
                load_settings, out_settings = tab_settings.build_tab()

        # Auto-refresh history when switching to the tab
        history_tab.select(fn=load_history, outputs=out_history)

        # Stop → switch to history tab → auto-summarize
        stop_event.then(
            fn=lambda: gr.Tabs(selected="history"),
            outputs=[tabs],
        ).then(
            fn=auto_summarize,
            inputs=[stopped_session_id],
            outputs=auto_summarize_outputs,
        )

        # Single load event that initializes everything
        all_outputs = out_transcription + out_speakers + out_dict + out_history + out_settings

        def init_all():
            results = []
            results.extend(_safe(load_transcription, len(out_transcription)))
            results.extend(_safe(load_speakers, len(out_speakers)))
            results.extend(_safe(load_dict, len(out_dict)))
            results.extend(_safe(load_history, len(out_history)))
            results.extend(_safe(load_settings, len(out_settings)))
            return results

        app.load(fn=init_all, outputs=all_outputs)

    return app


def _safe(fn, n_outputs):
    """Call fn and return its results, or defaults on error."""
    try:
        result = fn()
        if isinstance(result, tuple):
            return list(result)
        return [result]
    except Exception:
        return [None] * n_outputs


def main():
    app = create_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        inbrowser=True,
    )


if __name__ == "__main__":
    main()
