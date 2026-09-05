import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes_summary import router
from backend.config import Settings, settings
from backend.core import summarizer
from backend.core.summarizer import generate_summary


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_codex_settings_defaults_and_auto_engine_label():
    assert Settings.model_fields["codex_cli_command"].default == "codex"
    assert Settings.model_fields["codex_cli_profile"].default == "gen"
    assert Settings.model_fields["codex_cli_timeout_s"].default == 300.0
    assert "Codex CLI" in summarizer.SUMMARY_ENGINES["auto"]["label"]


def test_codex_cli_uses_chatgpt_subscription_profile_and_temp_directory(monkeypatch):
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    resolved_command = r"C:\Users\faker\AppData\Roaming\npm\codex.CMD"
    monkeypatch.setattr(summarizer.shutil, "which", lambda command: resolved_command)

    calls = []
    temporary_cwds = []

    class FakeProcess:
        def __init__(self, cmd, cwd):
            self.cmd = cmd
            self.cwd = Path(cwd)
            self.returncode = 0

        async def communicate(self, input=None):
            calls.append((self.cmd, input))
            if self.cmd[1:3] == ("login", "status"):
                return b"", b"Logged in using ChatGPT\n"

            output_path = Path(
                self.cmd[self.cmd.index("--output-last-message") + 1]
            )
            output_path.write_text("Codexで生成した要約", encoding="utf-8")
            return b"diagnostic output that must not be returned", b""

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        cwd = Path(kwargs["cwd"])
        temporary_cwds.append(cwd)
        assert cwd.exists()
        if cmd[1:3] == ("login", "status"):
            assert list(cwd.iterdir()) == []
        return FakeProcess(cmd, cwd)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(summarizer._generate_text_with_codex_cli("会議を要約"))

    assert result["content"] == "Codexで生成した要約"
    assert result["usage"] == {
        "model": "codex-cli",
        "billing": "codex-subscription",
    }
    login_cmd = calls[0][0]
    generation_cmd, generation_input = calls[1]
    assert login_cmd[:3] == (resolved_command, "login", "status")
    assert generation_cmd[:4] == (resolved_command, "exec", "-p", "gen")
    assert "--ephemeral" in generation_cmd
    assert "--ignore-user-config" in generation_cmd
    assert ("--sandbox", "read-only") == (
        generation_cmd[generation_cmd.index("--sandbox")],
        generation_cmd[generation_cmd.index("--sandbox") + 1],
    )
    assert "--ignore-rules" in generation_cmd
    assert "--skip-git-repo-check" in generation_cmd
    assert generation_cmd[-1] == "-"
    assert generation_input == "会議を要約".encode("utf-8")
    assert temporary_cwds[0] == temporary_cwds[1]
    assert not temporary_cwds[0].exists()


def test_auto_summary_uses_codex_before_gemini(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)
    calls = []

    async def fake_claude(prompt):
        calls.append("claude-code")
        raise RuntimeError("Claude unavailable")

    async def fake_codex(prompt):
        calls.append("codex-cli")
        return {
            "content": "## タイトル\nCodex代替\n\n## 概要\nCodexで生成。",
            "usage": {"model": "codex-cli", "billing": "codex-subscription"},
        }

    async def fake_gemini(prompt):
        calls.append("gemini")
        raise AssertionError("Gemini must not run when Codex succeeds")

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(generate_summary([{"text": "要約対象"}]))

    assert calls == ["claude-code", "codex-cli"]
    assert result["title"] == "Codex代替"
    assert result["usage"]["fallback_chain"] == ["claude-code"]
    assert result["usage"]["fallback_from"] == "claude-code"
    assert result["usage"]["fallback_reason"] == "provider-error"


def test_auto_summary_records_two_failures_before_gemini(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise RuntimeError("Claude unavailable")

    async def fake_codex(prompt):
        raise RuntimeError("Codex unavailable")

    async def fake_gemini(prompt):
        return {
            "content": "## タイトル\nGemini代替",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(generate_summary([{"text": "要約対象"}]))

    assert result["usage"]["fallback_chain"] == ["claude-code", "codex-cli"]
    assert result["usage"]["fallback_details"] == {
        "claude-code": "Claude unavailable",
        "codex-cli": "Codex unavailable",
    }
    assert result["usage"]["fallback_from"] == "codex-cli"
    assert result["usage"]["fallback_detail"] == "Codex unavailable"
    assert result["usage"]["fallback_reason"] == "provider-error"


def test_generic_gemini_uses_one_attempt_and_reports_optional_total_usage(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.0-flash", raising=False)
    calls = 0

    class UsageMetadata:
        total_token_count = 13

    class Response:
        text = "Gemini回答"
        usage_metadata = UsageMetadata()

    class Models:
        def generate_content(self, **kwargs):
            nonlocal calls
            calls += 1
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(summarizer, "get_gemini_client", lambda: Client())

    result = asyncio.run(summarizer._generate_text_with_gemini("質問"))

    assert calls == 1
    assert result == {
        "content": "Gemini回答",
        "usage": {
            "model": "gemini-2.0-flash",
            "billing": "api",
            "total_tokens": 13,
        },
    }


def test_gemini_usage_keeps_generic_total_and_sums_direct_summary_tokens(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.0-flash", raising=False)

    class UsageMetadata:
        prompt_token_count = 10
        candidates_token_count = 20
        total_token_count = None

    class Response:
        text = "## タイトル\nGemini議事録"
        usage_metadata = UsageMetadata()

    class Models:
        def generate_content(self, **kwargs):
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(summarizer, "get_gemini_client", lambda: Client())

    generic = asyncio.run(summarizer._generate_text_with_gemini("質問"))
    direct = asyncio.run(summarizer.generate_summary_with_gemini([{"text": "要約対象"}]))

    assert generic["usage"] == {
        "model": "gemini-2.0-flash",
        "billing": "api",
        "total_tokens": 0,
    }
    assert direct["usage"]["input_tokens"] == 10
    assert direct["usage"]["output_tokens"] == 20
    assert direct["usage"]["total_tokens"] == 30


def test_direct_gemini_summary_raises_contract_error_for_empty_response(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)

    class Models:
        def generate_content(self, **kwargs):
            return None

    class Client:
        models = Models()

    monkeypatch.setattr(summarizer, "get_gemini_client", lambda: Client())

    with pytest.raises(RuntimeError, match="Gemini API呼び出しに失敗しました"):
        asyncio.run(summarizer.generate_summary_with_gemini([{"text": "要約対象"}]))


def test_direct_gemini_summary_retries_and_reports_detailed_usage(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "gemini_model", "gemini-2.0-flash", raising=False)
    calls = 0
    waits = []

    class UsageMetadata:
        prompt_token_count = 5
        candidates_token_count = 7
        total_token_count = 12

    class Response:
        text = "## タイトル\nGemini議事録"
        usage_metadata = UsageMetadata()

    class Models:
        def generate_content(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("503 temporarily unavailable")
            return Response()

    class Client:
        models = Models()

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(summarizer, "get_gemini_client", lambda: Client())
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = asyncio.run(summarizer.generate_summary_with_gemini([{"text": "要約対象"}]))

    assert calls == 3
    assert waits == [1, 2]
    assert result == {
        "summary": "## タイトル\nGemini議事録",
        "title": "Gemini議事録",
        "usage": {
            "input_tokens": 5,
            "output_tokens": 7,
            "total_tokens": 12,
            "model": "gemini-2.0-flash",
            "billing": "api",
            "cost_usd": 3e-06,
        },
    }


def test_codex_cli_blocks_api_credentials_before_launch(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    launched = False

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("Codex must not launch with API credentials")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        asyncio.run(summarizer._generate_text_with_codex_cli("要約"))

    assert launched is False


def test_codex_login_timeout_cleans_temp_directory(monkeypatch):
    monkeypatch.setattr(settings, "codex_cli_timeout_s", 0.01)
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(summarizer.shutil, "which", lambda command: "codex.cmd")
    temporary_cwd = None

    class HangingProcess:
        returncode = None
        killed = False

        async def communicate(self, input=None):
            await asyncio.sleep(1)

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -1

    process = HangingProcess()

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal temporary_cwd
        temporary_cwd = Path(kwargs["cwd"])
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="認証確認がタイムアウト"):
        asyncio.run(summarizer._generate_text_with_codex_cli("要約"))

    assert process.killed is True
    assert temporary_cwd is not None
    assert not temporary_cwd.exists()


def test_codex_generation_failure_cleans_temp_directory(monkeypatch):
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(summarizer.shutil, "which", lambda command: "codex.cmd")
    temporary_cwd = None
    process_count = 0

    class CompletedProcess:
        def __init__(self, returncode, stdout=b"", stderr=b""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

        async def communicate(self, input=None):
            return self.stdout, self.stderr

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal process_count, temporary_cwd
        process_count += 1
        temporary_cwd = Path(kwargs["cwd"])
        if process_count == 1:
            return CompletedProcess(0, b"Logged in using ChatGPT")
        return CompletedProcess(1, stderr=b"generation failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="generation failed"):
        asyncio.run(summarizer._generate_text_with_codex_cli("要約"))

    assert temporary_cwd is not None
    assert not temporary_cwd.exists()


def test_codex_generation_timeout_cleans_temp_directory(monkeypatch):
    monkeypatch.setattr(settings, "codex_cli_timeout_s", 0.01)
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(summarizer.shutil, "which", lambda command: "codex.cmd")
    temporary_cwd = None
    process_count = 0

    class LoginProcess:
        returncode = 0

        async def communicate(self, input=None):
            return b"Logged in using ChatGPT", b""

    class HangingProcess:
        returncode = None
        killed = False

        async def communicate(self, input=None):
            await asyncio.sleep(1)

        def kill(self):
            self.killed = True

        async def wait(self):
            self.returncode = -1

    generation_process = HangingProcess()

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        nonlocal process_count, temporary_cwd
        process_count += 1
        temporary_cwd = Path(kwargs["cwd"])
        return LoginProcess() if process_count == 1 else generation_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(RuntimeError, match="Codex CLI要約がタイムアウト"):
        asyncio.run(summarizer._generate_text_with_codex_cli("要約"))

    assert generation_process.killed is True
    assert temporary_cwd is not None
    assert not temporary_cwd.exists()


def test_codex_api_credential_failure_falls_back_to_gemini(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_claude(prompt):
        raise RuntimeError("Claude unavailable")

    async def fake_gemini(prompt):
        return {
            "content": "Gemini fallback",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(summarizer.generate_summary_text("要約"))

    assert result["content"] == "Gemini fallback"
    assert result["usage"]["fallback_chain"] == ["claude-code", "codex-cli"]
    assert "OPENAI_API_KEY" in result["usage"]["fallback_details"]["codex-cli"]


def test_all_summary_providers_fail_with_combined_diagnostics(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise RuntimeError("Claude failed")

    async def fake_codex(prompt):
        raise RuntimeError("Codex failed")

    async def fake_gemini(prompt):
        raise RuntimeError("Gemini failed")

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(summarizer.generate_summary_text("要約"))

    message = str(exc_info.value)
    assert "claude-code: Claude failed" in message
    assert "codex-cli: Codex failed" in message
    assert "gemini: Gemini failed" in message


@pytest.mark.parametrize("engine", ["claude-code", "gemini"])
def test_explicit_text_engine_never_falls_back(monkeypatch, engine):
    monkeypatch.setattr(settings, "summary_engine", engine, raising=False)
    calls = []

    async def fake_claude(prompt):
        calls.append("claude-code")
        return {
            "content": "Claude",
            "usage": {"model": "claude-code", "billing": "claude-subscription"},
        }

    async def fake_codex(prompt):
        calls.append("codex-cli")
        raise AssertionError("Codex is not an explicit engine")

    async def fake_gemini(prompt):
        calls.append("gemini")
        return {
            "content": "Gemini",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(summarizer.generate_summary_text("要約"))

    assert calls == [engine]
    assert result["content"] == ("Claude" if engine == "claude-code" else "Gemini")


def test_claude_code_summary_engine_uses_cli_without_gemini_key(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "claude-code", raising=False)
    monkeypatch.setattr(settings, "claude_code_command", "claude", raising=False)
    monkeypatch.setattr(settings, "claude_code_model", "", raising=False)
    monkeypatch.setattr(settings, "claude_code_timeout_s", 30.0, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)

    resolved_command = r"C:\Users\faker\AppData\Roaming\npm\claude.CMD"
    monkeypatch.setattr(summarizer.shutil, "which", lambda command: resolved_command)

    calls = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self, input=None):
            calls["input"] = input.decode("utf-8")
            return (
                "## タイトル\nClaude議事録\n\n## 概要\nClaude Codeで生成しました。".encode("utf-8"),
                b"",
            )

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    result = asyncio.run(
        generate_summary(
            [
                {
                    "timestamp_start": 10,
                    "speaker_name": "菊地",
                    "text": "来週の予定調整をお願いします。",
                }
            ]
        )
    )

    assert result["summary"].startswith("## タイトル")
    assert result["title"] == "Claude議事録"
    assert result["usage"]["model"] == "claude-code"
    assert result["usage"]["billing"] == "claude-subscription"
    assert calls["cmd"][0] == resolved_command
    assert "-p" in calls["cmd"]
    assert "--safe-mode" in calls["cmd"]
    assert "--no-session-persistence" in calls["cmd"]
    assert "--tools" in calls["cmd"]
    assert "来週の予定調整" in calls["input"]
    assert calls["kwargs"]["stdin"] == asyncio.subprocess.PIPE


def test_auto_summary_engine_prefers_claude_code(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        return {
            "content": "## タイトル\nClaude優先\n\n## 概要\nClaudeで生成。",
            "usage": {"model": "claude-code", "billing": "claude-subscription"},
        }

    async def fake_codex(prompt):
        raise AssertionError("Codex should not be called when Claude Code succeeds")

    async def fake_gemini(prompt):
        raise AssertionError("Gemini should not be called when Claude Code succeeds")

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(
        generate_summary(
            [
                {
                    "timestamp_start": 10,
                    "speaker_name": "菊地",
                    "text": "Claudeを標準で使う。",
                }
            ]
        )
    )

    assert result["title"] == "Claude優先"
    assert result["usage"]["model"] == "claude-code"


def test_auto_summary_engine_falls_back_to_gemini_on_subscription_limit(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise RuntimeError("Claude Code usage limit reached. Please try again later.")

    async def fake_codex(prompt):
        raise RuntimeError("Codex CLI usage limit reached.")

    async def fake_gemini(prompt):
        return {
            "content": "## タイトル\nGemini代替\n\n## 概要\nGeminiで代替生成。",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(
        generate_summary(
            [
                {
                    "timestamp_start": 20,
                    "speaker_name": "菊地",
                    "text": "Claudeの枠が切れた場合だけGeminiに落とす。",
                }
            ]
        )
    )

    assert result["title"] == "Gemini代替"
    assert result["usage"]["model"] == "gemini-test"
    assert result["usage"]["fallback_from"] == "codex-cli"
    assert result["usage"]["fallback_reason"] == "provider-error"
    assert result["usage"]["fallback_chain"] == ["claude-code", "codex-cli"]
    assert "usage limit reached" in result["usage"]["fallback_details"]["claude-code"]


def test_auto_summary_engine_falls_back_on_monthly_spend_limit(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise RuntimeError(
            "You've hit your org's monthly spend limit · ask your admin to raise it"
        )

    async def fake_codex(prompt):
        raise RuntimeError("Codex unavailable")

    async def fake_gemini(prompt):
        return {
            "content": "## タイトル\nGemini代替\n\n## 概要\nGeminiで代替生成。",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(generate_summary([{"text": "月間上限時の代替を確認する。"}]))

    assert result["title"] == "Gemini代替"
    assert result["usage"]["fallback_chain"] == ["claude-code", "codex-cli"]


def test_auto_summary_engine_falls_back_on_any_claude_error(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise RuntimeError("unexpected local CLI failure")

    async def fake_codex(prompt):
        raise RuntimeError("unexpected Codex CLI failure")

    async def fake_gemini(prompt):
        return {
            "content": "Geminiで生成",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_codex_cli", fake_codex)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(generate_summary([{"text": "フォールバック対象"}]))

    assert result["summary"] == "Geminiで生成"
    assert result["usage"]["fallback_reason"] == "provider-error"
    assert result["usage"]["fallback_details"]["claude-code"] == "unexpected local CLI failure"
    assert result["usage"]["fallback_detail"] == "unexpected Codex CLI failure"


def test_auto_summary_engine_does_not_fallback_for_empty_input(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)
    gemini_calls = 0

    async def fake_gemini(entries):
        nonlocal gemini_calls
        gemini_calls += 1

    monkeypatch.setattr(summarizer, "generate_summary_with_gemini", fake_gemini)

    try:
        asyncio.run(generate_summary([]))
    except RuntimeError as exc:
        assert "文字起こしが空" in str(exc)
    else:
        raise AssertionError("Expected empty transcript error")

    assert gemini_calls == 0


def test_live_ai_auto_engine_falls_back_on_any_claude_error(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "auto", raising=False)

    async def fake_claude(prompt):
        raise OSError("claude process could not start")

    async def fake_gemini(prompt):
        return {
            "content": "Gemini回答",
            "usage": {"model": "gemini-test", "billing": "api"},
        }

    monkeypatch.setattr(summarizer, "_generate_text_with_claude_code", fake_claude)
    monkeypatch.setattr(summarizer, "_generate_text_with_gemini", fake_gemini)

    result = asyncio.run(summarizer.generate_text_with_summary_engine("質問"))

    assert result["content"] == "Gemini回答"
    assert result["usage"]["fallback_reason"] == "provider-error"
    assert result["usage"]["fallback_detail"] == "claude process could not start"


def test_claude_code_summary_engine_blocks_api_key_env(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "claude-code", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    try:
        asyncio.run(
            generate_summary(
                [
                    {
                        "timestamp_start": 0,
                        "speaker_name": "菊地",
                        "text": "APIキー環境変数がある場合は止める。",
                    }
                ]
            )
        )
    except RuntimeError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for ANTHROPIC_API_KEY")


def test_summary_engine_route_switches_current_engine(monkeypatch):
    monkeypatch.setattr(settings, "summary_engine", "gemini", raising=False)
    saved = {}

    def fake_update_env_file(key: str, value: str) -> None:
        saved[key] = value

    monkeypatch.setattr(
        "backend.api.routes_summary.update_env_file",
        fake_update_env_file,
        raising=False,
    )

    client = TestClient(make_app())

    response = client.get("/api/summary/engines")
    assert response.status_code == 200
    assert response.json()["current_engine"] == "gemini"
    assert {engine["id"] for engine in response.json()["engines"]} >= {
        "gemini",
        "claude-code",
    }

    response = client.put("/api/summary/engine", json={"engine_id": "claude-code"})

    assert response.status_code == 200
    assert response.json()["current_engine"] == "claude-code"
    assert settings.summary_engine == "claude-code"
    assert saved == {"SUMMARY_ENGINE": "claude-code"}
