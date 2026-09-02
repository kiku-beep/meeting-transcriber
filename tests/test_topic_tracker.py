"""Tests for the meeting-time topic-tree tracker and Codex options."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def _settings(**overrides):
    from backend.config import Settings

    values = {
        "topic_tree_enabled": True,
        "topic_tree_interval_s": 0.01,
        "topic_tree_min_new_entries": 1,
        "topic_tree_max_nodes": 80,
        "topic_tree_recent_window_sec": 900.0,
        "topic_tree_engine": "codex-cli",
        "topic_tree_codex_profile": "gen",
        "topic_tree_codex_reasoning_effort": "low",
    }
    values.update(overrides)
    return Settings(**values)


def _entry(start: float, text: str = "発言") -> dict:
    return {
        "id": f"entry-{start}",
        "speaker_name": "話者A",
        "text": text,
        "timestamp_start": start,
        "timestamp_end": start + 1,
    }


def test_disabled_start_does_not_create_a_task():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        async def fail_generate(prompt: str) -> dict:
            raise AssertionError("disabled tracker must not call the LLM")

        tracker = TopicTracker(_settings(topic_tree_enabled=False), fail_generate)
        tracker.start([_entry(0)])

        assert tracker._task is None
        await tracker.stop()

    asyncio.run(scenario())


def test_topic_tree_settings_have_requested_defaults():
    from backend.config import Settings

    fields = Settings.model_fields

    assert fields["topic_tree_enabled"].default is False
    assert fields["topic_tree_interval_s"].default == 90.0
    assert fields["topic_tree_min_new_entries"].default == 5
    assert fields["topic_tree_max_nodes"].default == 80
    assert fields["topic_tree_recent_window_sec"].default == 900.0
    assert fields["topic_tree_engine"].default == "codex-cli"
    assert fields["topic_tree_codex_profile"].default == "gen"
    assert fields["topic_tree_codex_reasoning_effort"].default == "low"


def test_one_period_applies_fake_patch_and_enqueues_tree():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        calls = []

        async def fake_generate(prompt: str) -> dict:
            calls.append(prompt)
            return {
                "content": '{"add":[{"id":"n1","label":"予算","start_sec":0,"end_sec":1}],"active":"n1"}',
                "usage": {"model": "fake"},
            }

        tracker = TopicTracker(_settings(), fake_generate)
        tracker.start([_entry(0, "予算を議論する")])
        payload = await asyncio.wait_for(tracker.topic_queue.get(), timeout=1)

        assert calls
        assert [node["id"] for node in payload["nodes"]] == ["n1"]
        assert tracker.tree.active == "n1"
        await tracker.stop()

    asyncio.run(scenario())


def test_insufficient_new_entries_skips_llm():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        calls = 0

        async def fake_generate(prompt: str) -> dict:
            nonlocal calls
            calls += 1
            return {"content": "{}", "usage": {}}

        tracker = TopicTracker(
            _settings(topic_tree_min_new_entries=2),
            fake_generate,
        )
        tracker.start([_entry(0)])
        await asyncio.sleep(0.04)

        assert calls == 0
        await tracker.stop()

    asyncio.run(scenario())


def test_invalid_json_keeps_cursor_and_retries_same_entries():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        prompts = []
        second_call = asyncio.Event()

        async def fake_generate(prompt: str) -> dict:
            prompts.append(prompt)
            if len(prompts) == 1:
                return {"content": "not json", "usage": {}}
            second_call.set()
            return {"content": "{}", "usage": {}}

        tracker = TopicTracker(_settings(), fake_generate)
        tracker.start([_entry(0, "同じ発話を再試行")])
        await asyncio.wait_for(second_call.wait(), timeout=1)

        assert len(prompts) >= 2
        assert prompts[0] == prompts[1]
        assert tracker._cursor == 1
        await tracker.stop()

    asyncio.run(scenario())


def test_generator_exception_does_not_kill_loop_and_increases_backoff():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        calls = 0
        second_call = asyncio.Event()

        async def fake_generate(prompt: str) -> dict:
            nonlocal calls
            calls += 1
            if calls >= 2:
                second_call.set()
            raise RuntimeError("fake provider failure")

        tracker = TopicTracker(_settings(), fake_generate)
        tracker.start([_entry(0)])
        await asyncio.wait_for(second_call.wait(), timeout=1)

        assert not tracker._task.done()
        assert tracker._backoff_s > tracker.interval_s
        assert tracker._cursor == 0
        await tracker.stop()

    asyncio.run(scenario())


def test_stop_cancels_task_and_clears_task_reference():
    from backend.core.topic_tracker import TopicTracker

    async def scenario():
        tracker = TopicTracker(_settings(topic_tree_interval_s=10), None)
        tracker.start([_entry(0)])
        assert tracker._task is not None

        await tracker.stop()

        assert tracker._task is None

    asyncio.run(scenario())


def test_refresh_now_runs_without_waiting_and_guards_concurrent_calls():
    from backend.core.topic_tracker import REFRESH_BUSY, REFRESH_UPDATED, TopicTracker

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_generate(prompt: str) -> dict:
            started.set()
            await release.wait()
            return {"content": "{}", "usage": {}}

        tracker = TopicTracker(_settings(topic_tree_interval_s=100), fake_generate)
        tracker.start([_entry(0)])
        first = asyncio.create_task(tracker.refresh_now())
        await asyncio.wait_for(started.wait(), timeout=1)

        assert await tracker.refresh_now() == REFRESH_BUSY
        release.set()
        assert await first == REFRESH_UPDATED
        await tracker.stop()

    asyncio.run(scenario())


def test_transcript_entry_and_dict_are_both_supported():
    from backend.core.topic_tracker import REFRESH_UPDATED, TopicTracker
    from backend.models.schemas import TranscriptEntry

    async def scenario():
        calls = 0

        async def fake_generate(prompt: str) -> dict:
            nonlocal calls
            calls += 1
            return {"content": "{}", "usage": {}}

        tracker = TopicTracker(_settings(topic_tree_interval_s=100), fake_generate)
        tracker.start([TranscriptEntry(text="モデル発話", timestamp_start=0, timestamp_end=1)])
        assert await tracker.refresh_now() == REFRESH_UPDATED
        await tracker.stop()

        tracker = TopicTracker(_settings(topic_tree_interval_s=100), fake_generate)
        tracker.start([_entry(2, "辞書発話")])
        assert await tracker.refresh_now() == REFRESH_UPDATED
        await tracker.stop()

        assert calls == 2

    asyncio.run(scenario())


def test_colliding_llm_id_is_reserved_instead_of_lost():
    from backend.core.topic_tracker import REFRESH_UPDATED, TopicTracker

    async def scenario():
        calls = 0

        async def fake_generate(prompt: str) -> dict:
            nonlocal calls
            calls += 1
            return {
                "content": '{"add":[{"id":"n1","label":"論点"}]}',
                "usage": {},
            }

        entries = [_entry(0, "一つ目")]
        tracker = TopicTracker(_settings(topic_tree_interval_s=100), fake_generate)
        tracker.start(entries)

        assert await tracker.refresh_now() == REFRESH_UPDATED
        entries.append(_entry(2, "二つ目"))
        assert await tracker.refresh_now() == REFRESH_UPDATED
        assert calls == 2
        assert [node.id for node in tracker.tree.nodes] == ["n1", "t1"]
        await tracker.stop()

    asyncio.run(scenario())


def test_codex_effort_is_added_to_generation_command(monkeypatch):
    from backend.core import summarizer

    async def scenario():
        commands = []

        class FakeProcess:
            returncode = 0

            async def communicate(self, input=None):
                output_path = Path(commands[-1][commands[-1].index("--output-last-message") + 1])
                output_path.write_text("応答", encoding="utf-8")
                return b"", b""

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            commands.append(cmd)
            return FakeProcess()

        monkeypatch.setattr(summarizer, "_resolve_codex_subscription_command", lambda: "codex")
        async def skip_login(command: str, cwd: str) -> None:
            return None
        monkeypatch.setattr(summarizer, "_verify_codex_chatgpt_login", skip_login)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        result = await summarizer._generate_text_with_codex_cli(
            "プロンプト",
            profile="topic-profile",
            reasoning_effort="low",
        )

        generation_command = commands[0]
        assert "-c" in generation_command
        assert generation_command[
            generation_command.index("-c") + 1
        ] == 'model_reasoning_effort="low"'
        assert result["usage"]["profile"] == "topic-profile"
        assert result["usage"]["reasoning_effort"] == "low"

    asyncio.run(scenario())


def test_codex_effort_must_be_in_allowlist(monkeypatch):
    from backend.core import summarizer

    async def scenario():
        with_exception = None
        try:
            await summarizer._generate_text_with_codex_cli(
                "プロンプト",
                reasoning_effort="unsafe",
            )
        except ValueError as exc:
            with_exception = exc

        assert with_exception is not None

    monkeypatch.setattr(summarizer, "_resolve_codex_subscription_command", lambda: "codex")
    asyncio.run(scenario())


def test_codex_login_status_is_cached_until_reset(monkeypatch):
    from backend.core import summarizer

    async def scenario():
        calls = 0

        class FakeProcess:
            returncode = 0

            async def communicate(self, input=None):
                return b"", b"Logged in using ChatGPT"

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            nonlocal calls
            calls += 1
            return FakeProcess()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        summarizer.reset_codex_login_cache()

        await summarizer._verify_codex_chatgpt_login("codex", "C:\\")
        await summarizer._verify_codex_chatgpt_login("codex", "C:\\")
        assert calls == 1

        summarizer.reset_codex_login_cache()
        await summarizer._verify_codex_chatgpt_login("codex", "C:\\")
        assert calls == 2

    asyncio.run(scenario())


def test_failed_codex_login_status_is_not_cached(monkeypatch):
    from backend.core import summarizer

    async def scenario():
        calls = 0

        class FakeProcess:
            def __init__(self, logged_in: bool):
                self.returncode = 0
                self.logged_in = logged_in

            async def communicate(self, input=None):
                return b"", b"Logged in using ChatGPT" if self.logged_in else b"not logged in"

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            nonlocal calls
            calls += 1
            return FakeProcess(calls > 1)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        summarizer.reset_codex_login_cache()

        with pytest.raises(RuntimeError):
            await summarizer._verify_codex_chatgpt_login("codex", "C:\\")
        await summarizer._verify_codex_chatgpt_login("codex", "C:\\")
        assert calls == 2

    asyncio.run(scenario())


def test_malformed_entry_does_not_stall_the_tracker():
    """壊れたエントリ1件でトラッカーが永久停止しないこと。

    修正前は _collect_new_entries がバッチ全体を捨てて cursor が進まず、
    以降すべての発話が例外もログも無いまま処理されなくなっていた。
    """
    import asyncio

    from backend.config import Settings
    from backend.core.topic_tracker import TopicTracker

    settings = Settings()
    settings.topic_tree_enabled = True
    settings.topic_tree_interval_s = 0.01
    settings.topic_tree_min_new_entries = 1

    calls: list[str] = []
    patch = (
        '{"add":[{"id":"t1","parent":null,"label":"論点",'
        '"status":"open","start_sec":0,"end_sec":5}],"update":[],"active":"t1"}'
    )

    async def fake_generate(prompt: str) -> dict:
        calls.append(prompt)
        return {"content": patch, "usage": {}}

    def entry(start: float, end: float) -> dict:
        return {
            "id": f"e{start}",
            "text": "発言",
            "speaker_name": "話者A",
            "timestamp_start": start,
            "timestamp_end": end,
        }

    async def scenario() -> tuple[int, int]:
        tracker = TopicTracker(settings, generate=fake_generate)
        entries = [entry(0, 5), entry(5, 10)]
        tracker.start(entries)
        await asyncio.sleep(0.2)
        calls_before = len(calls)

        # NaN の timestamp を1件混ぜる（WS側の _sanitize_entry が
        # speaker_confidence でNaNを丸めている実績があり、起こり得る）
        entries.append(entry(10, float("nan")))
        entries.append(entry(15, 20))
        await asyncio.sleep(0.3)
        calls_after = len(calls)
        await tracker.stop()
        return calls_before, calls_after

    before, after = asyncio.run(scenario())

    assert before >= 1, "正常系で1回も更新されていない"
    assert after > before, "NaN混入後に更新が止まっている（永久停止）"


def test_refresh_now_distinguishes_disabled_insufficient_and_failure():
    """refresh_now は「更新なし」の理由を潰さず、LLM失敗は例外で返す。

    以前は4状態すべてが False に潰れていたため、UIが「更新なし」と表示している
    裏でプロバイダが壊れていても誰も気づけなかった。
    """
    from backend.core.topic_tracker import (
        REFRESH_DISABLED,
        REFRESH_NO_NEW_ENTRIES,
        REFRESH_UPDATED,
        TopicTracker,
    )

    async def scenario():
        async def ok_generate(prompt: str) -> dict:
            return {"content": "{}", "usage": {}}

        async def broken_generate(prompt: str) -> dict:
            raise RuntimeError("provider failed")

        # 機能OFF
        off = TopicTracker(_settings(topic_tree_enabled=False), ok_generate)
        off.start([_entry(0)])
        assert await off.refresh_now() == REFRESH_DISABLED

        # 新規発話が最小件数に届かない
        thin = TopicTracker(
            _settings(topic_tree_interval_s=100, topic_tree_min_new_entries=5),
            ok_generate,
        )
        thin.start([_entry(0)])
        assert await thin.refresh_now() == REFRESH_NO_NEW_ENTRIES
        await thin.stop()

        # LLM失敗は状態ではなく例外。バックオフは投げる前に進む
        broken = TopicTracker(_settings(topic_tree_interval_s=100), broken_generate)
        broken.start([_entry(0)])
        with pytest.raises(RuntimeError):
            await broken.refresh_now()
        assert broken._consecutive_failures == 1
        assert broken._backoff_s > 0
        # 失敗してもロックは解放され、次の呼び出しが busy にならない
        broken._generate_override = ok_generate
        assert await broken.refresh_now() == REFRESH_UPDATED
        await broken.stop()

    asyncio.run(scenario())
