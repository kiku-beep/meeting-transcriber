"""Dictionary / post-processing settings tab."""

from __future__ import annotations

import gradio as gr

from frontend import api_client


def _replacements_table(replacements: list[dict]) -> str:
    if not replacements:
        return '<div style="color:#888;padding:12px;">置換ルールはありません。</div>'
    rows = ""
    for i, r in enumerate(replacements):
        mode = "正規表現" if r.get("is_regex") else "テキスト"
        note = r.get("note", "")
        note_html = f'<span style="color:#888;font-size:0.85em;"> ({note})</span>' if note else ""
        rows += (
            f"<tr>"
            f"<td style='padding:6px 12px;'>{i}</td>"
            f"<td style='padding:6px 12px;font-family:monospace;'>{r['from']}</td>"
            f"<td style='padding:6px 12px;'>→</td>"
            f"<td style='padding:6px 12px;'>{r['to']}{note_html}</td>"
            f"<td style='padding:6px 12px;font-size:0.8em;color:#888;'>{mode}</td>"
            f"</tr>"
        )
    return (
        '<table style="width:100%;border-collapse:collapse;">'
        "<thead><tr>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>#</th>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>パターン</th>"
        "<th style='padding:6px 12px;border-bottom:1px solid #444;'></th>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>変換先</th>"
        "<th style='text-align:left;padding:6px 12px;border-bottom:1px solid #444;'>種別</th>"
        "</tr></thead><tbody>"
        f"{rows}</tbody></table>"
    )


def _status_html(msg: str, ok: bool = True) -> str:
    color = "#4FC3F7" if ok else "#F06292"
    return f'<div style="color:{color};padding:4px 8px;font-size:0.9em;">{msg}</div>'


def build_tab():
    def reload_dict():
        """Reload dictionary from disk, then refresh UI."""
        try:
            data = api_client.reload_dictionary()
            replacements = data.get("replacements", [])
            fillers = data.get("fillers", [])
            filler_enabled = data.get("filler_removal_enabled", True)
            table = _replacements_table(replacements)
            filler_str = ", ".join(fillers)
            return table, filler_str, filler_enabled, _status_html("辞書を再読み込みしました。")
        except Exception as e:
            return f"<div style='color:red;'>エラー: {e}</div>", "", True, _status_html(f"エラー: {e}", False)

    def refresh_dict():
        try:
            data = api_client.get_dictionary()
            replacements = data.get("replacements", [])
            fillers = data.get("fillers", [])
            filler_enabled = data.get("filler_removal_enabled", True)
            table = _replacements_table(replacements)
            filler_str = ", ".join(fillers)
            return table, filler_str, filler_enabled
        except Exception as e:
            return f"<div style='color:red;'>エラー: {e}</div>", "", True

    def add_replacement(from_text: str, to_text: str, is_regex: bool, note: str):
        if not from_text.strip():
            return _status_html("パターンを入力してください。", False), gr.skip(), gr.skip(), gr.skip(), gr.skip()
        try:
            api_client.add_replacement(
                from_text.strip(), to_text.strip(), is_regex, note.strip()
            )
            mode = "正規表現" if is_regex else "テキスト"
            return _status_html(f"追加 [{mode}]: 「{from_text}」→「{to_text}」"), "", "", False, ""
        except Exception as e:
            return _status_html(f"エラー: {e}", False), gr.skip(), gr.skip(), gr.skip(), gr.skip()

    def delete_replacement(index_str: str):
        try:
            idx = int(index_str)
            api_client.delete_replacement(idx)
            return _status_html(f"ルール #{idx} を削除しました。")
        except (ValueError, TypeError):
            return _status_html("有効なインデックスを入力してください。", False)
        except Exception as e:
            return _status_html(f"エラー: {e}", False)

    def update_fillers(filler_str: str, enabled: bool):
        try:
            fillers = [f.strip() for f in filler_str.split(",") if f.strip()]
            api_client.update_fillers(fillers=fillers, enabled=enabled)
            return _status_html(f"フィラー設定を保存しました。({len(fillers)}件)")
        except Exception as e:
            return _status_html(f"エラー: {e}", False)

    def test_dict(text: str):
        if not text.strip():
            return ""
        try:
            result = api_client.test_dictionary(text.strip())
            original = result.get("original", text)
            processed = result.get("processed", text)
            return f"入力: {original}\n結果: {processed}"
        except Exception as e:
            return f"エラー: {e}"

    with gr.Column():
        gr.Markdown("## 辞書・後処理設定")

        status_html = gr.HTML(value="")

        with gr.Accordion("ルール追加・削除", open=True):
            gr.Markdown(
                "**テキスト**: 文字列そのままマッチ / "
                "**正規表現**: パターンでマッチ。"
                "ショートハンド: `{漢字}` `{ひらがな}` `{カタカナ}` `{数字}` `{英字}` が使えます\n\n"
                "例: `(?<!{漢字})要` → 熟語内の「要」は残し、単独の「要」だけマッチ",
            )
            with gr.Row():
                from_input = gr.Textbox(label="パターン (読み or 正規表現)", placeholder="例: かなめ", scale=2)
                to_input = gr.Textbox(label="変換先", placeholder="例: カナメ", scale=2)
            with gr.Row():
                is_regex_cb = gr.Checkbox(label="正規表現", value=False, scale=1)
                note_input = gr.Textbox(label="メモ", placeholder="例: 人名", scale=2)
                add_btn = gr.Button("追加", variant="primary", scale=1)

            with gr.Row():
                del_index = gr.Textbox(label="削除するルール番号", placeholder="0", scale=2)
                del_btn = gr.Button("削除", variant="stop", scale=1)

        with gr.Accordion("ルール一覧", open=False):
            replacements_html = gr.HTML(value="読み込み中…")

        with gr.Accordion("フィラー除去", open=True):
            filler_input = gr.Textbox(
                label="フィラー一覧 (カンマ区切り)",
            )
            filler_enabled = gr.Checkbox(label="フィラー除去を有効にする", value=True)
            filler_btn = gr.Button("保存")

        with gr.Accordion("テスト", open=False):
            test_input = gr.Textbox(label="テスト文", placeholder="えーと かなめさんの確認が必要です")
            test_btn = gr.Button("テスト")
            test_output = gr.Textbox(label="結果", interactive=False)

        refresh_btn = gr.Button("辞書を再読み込み")

    # Events
    add_btn.click(
        fn=add_replacement,
        inputs=[from_input, to_input, is_regex_cb, note_input],
        outputs=[status_html, from_input, to_input, is_regex_cb, note_input],
    ).then(fn=refresh_dict, outputs=[replacements_html, filler_input, filler_enabled])

    del_btn.click(
        fn=delete_replacement,
        inputs=[del_index],
        outputs=[status_html],
    ).then(fn=refresh_dict, outputs=[replacements_html, filler_input, filler_enabled])

    filler_btn.click(
        fn=update_fillers,
        inputs=[filler_input, filler_enabled],
        outputs=[status_html],
    ).then(fn=refresh_dict, outputs=[replacements_html, filler_input, filler_enabled])

    test_btn.click(fn=test_dict, inputs=[test_input], outputs=[test_output])

    refresh_btn.click(fn=reload_dict, outputs=[replacements_html, filler_input, filler_enabled, status_html])

    return refresh_dict, [replacements_html, filler_input, filler_enabled]
