"""Periodic LLM-backed tracking of a meeting's incremental topic tree."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from backend.core.topic_tree import (
    TopicTree,
    apply_patch,
    build_patch_prompt,
    parse_patch,
    reserve_ids,
    select_tree_for_prompt,
    tree_to_dict,
)

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)

GenerateFunction = Callable[[str], Awaitable[dict]]
_VALID_ENGINES = {"codex-cli", "gemini", "claude-code"}


class TopicTracker:
    """Maintain a topic tree by periodically processing new transcript entries."""

    def __init__(
        self,
        settings: Settings,
        generate: GenerateFunction | None = None,
    ):
        self._settings = settings
        self._generate_override = generate
        self.enabled = False
        self.interval_s = 90.0
        self.min_new_entries = 5
        self.max_nodes = 80
        self.recent_window_sec = 900.0
        self.engine = "codex-cli"
        self.codex_profile = "gen"
        self.codex_reasoning_effort = "low"

        self._task: asyncio.Task | None = None
        self._entries: list[Any] = []
        self._cursor = 0
        self._tree = TopicTree()
        self._topic_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._refresh_lock = asyncio.Lock()
        self._consecutive_failures = 0
        self._backoff_s = 0.0

        self._refresh_config()

    @property
    def tree(self) -> TopicTree:
        """Return the current topic tree."""
        return self._tree

    @property
    def topic_queue(self) -> asyncio.Queue[dict]:
        """Return the queue used for later WebSocket distribution."""
        return self._topic_queue

    def _refresh_config(self) -> None:
        """Refresh tracker settings before arming a session."""
        self.interval_s = max(0.0, float(self._settings.topic_tree_interval_s))
        self.min_new_entries = max(0, int(self._settings.topic_tree_min_new_entries))
        self.max_nodes = int(self._settings.topic_tree_max_nodes)
        self.recent_window_sec = float(self._settings.topic_tree_recent_window_sec)
        self.engine = self._settings.topic_tree_engine
        self.codex_profile = self._settings.topic_tree_codex_profile
        self.codex_reasoning_effort = self._settings.topic_tree_codex_reasoning_effort
        self.enabled = bool(self._settings.topic_tree_enabled)
        if self.engine not in _VALID_ENGINES:
            self.enabled = False
            logger.warning("TopicTracker disabled: unknown engine %s", self.engine)

    def start(self, entries: list[Any]) -> None:
        """Register session entries and start the periodic update task."""
        self._refresh_config()
        self._entries = entries if isinstance(entries, list) else []
        self._cursor = 0
        self._tree = TopicTree()
        self._consecutive_failures = 0
        self._backoff_s = 0.0
        self._drain_queue()

        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        if not self.enabled:
            return

        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "TopicTracker started (engine=%s, interval=%.1fs, min_entries=%d)",
            self.engine,
            self.interval_s,
            self.min_new_entries,
        )

    async def stop(self) -> None:
        """Cancel the periodic task without performing a final update."""
        task = self._task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("TopicTracker task stopped with an error", exc_info=True)
        self._task = None
        logger.info("TopicTracker stopped")

    async def refresh_now(self) -> bool:
        """Run one immediate update, returning whether it was applied."""
        if not self.enabled or self._refresh_lock.locked():
            return False

        async with self._refresh_lock:
            try:
                return await self._refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._handle_failure()
                logger.warning("TopicTracker immediate refresh failed", exc_info=True)
                return False

    async def _run_loop(self) -> None:
        """Wait between updates and keep retrying after provider failures."""
        try:
            while True:
                delay_s = self._backoff_s or self.interval_s
                await asyncio.sleep(delay_s)
                try:
                    async with self._refresh_lock:
                        await self._refresh_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._handle_failure()
                    logger.warning("TopicTracker refresh failed", exc_info=True)
        except asyncio.CancelledError:
            raise

    async def _refresh_once(self) -> bool:
        batch, end_cursor = self._collect_new_entries()
        if batch is None or not batch or len(batch) < self.min_new_entries:
            return False

        now_sec = max(self._timestamp_end(entry) for entry in batch)
        prompt_tree = select_tree_for_prompt(
            self._tree,
            max_nodes=self.max_nodes,
            recent_window_sec=self.recent_window_sec,
            now_sec=now_sec,
        )
        prompt = build_patch_prompt(prompt_tree, batch)
        result = await self._get_generator()(prompt)
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            raise ValueError("topic-tree provider result must contain string content")

        patch = parse_patch(result["content"])
        reserved_patch = reserve_ids(self._tree, patch)
        self._tree = apply_patch(self._tree, reserved_patch)
        self._topic_queue.put_nowait(tree_to_dict(self._tree))
        self._cursor = end_cursor
        self._consecutive_failures = 0
        self._backoff_s = 0.0
        return True

    def _collect_new_entries(self) -> tuple[list[dict] | None, int]:
        """Snapshot and normalize entries without advancing the cursor.

        壊れたエントリ（NaNのtimestamp等）はバッチ全体を捨てずに個別にスキップする。
        全体を捨てるとcursorが永久に進まず、以降の発話が例外もログも無いまま
        失われる（機能が静かに死ぬ）ため。
        """
        if not isinstance(self._entries, list) or self._cursor > len(self._entries):
            return None, self._cursor

        end_cursor = len(self._entries)
        raw_entries = self._entries[self._cursor:end_cursor]
        normalized: list[dict] = []
        skipped = 0
        for entry in raw_entries:
            try:
                model_dump = getattr(entry, "model_dump", None)
                data = model_dump() if callable(model_dump) else dict(entry)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if not isinstance(data, dict):
                skipped += 1
                continue
            try:
                self._timestamp_end(data)
                float(data.get("timestamp_start", 0))
            except (TypeError, ValueError, OverflowError):
                skipped += 1
                continue
            normalized.append(data)
        if skipped:
            logger.warning(
                "TopicTracker skipped %d malformed entries (kept %d)",
                skipped,
                len(normalized),
            )
        return normalized, end_cursor

    @staticmethod
    def _timestamp_end(entry: dict) -> float:
        value = entry.get("timestamp_end", entry.get("timestamp_start", 0))
        timestamp = float(value)
        if not math.isfinite(timestamp):
            raise ValueError("entry timestamp must be finite")
        return timestamp

    def _get_generator(self) -> GenerateFunction:
        if self._generate_override is not None:
            return self._generate_override

        from backend.core import summarizer

        if self.engine == "codex-cli":
            async def generate(prompt: str) -> dict:
                return await summarizer._generate_text_with_codex_cli(
                    prompt,
                    profile=self.codex_profile,
                    reasoning_effort=self.codex_reasoning_effort,
                )

            return generate
        if self.engine == "gemini":
            return summarizer._generate_text_with_gemini
        if self.engine == "claude-code":
            return summarizer._generate_text_with_claude_code
        raise ValueError(f"unknown topic-tree engine: {self.engine}")

    def _handle_failure(self) -> None:
        self._consecutive_failures += 1
        if self.interval_s <= 0:
            self._backoff_s = 0.0
            return
        self._backoff_s = min(
            self.interval_s * 4,
            self.interval_s * (2 ** min(self._consecutive_failures, 2)),
        )

    def _drain_queue(self) -> None:
        while not self._topic_queue.empty():
            try:
                self._topic_queue.get_nowait()
            except asyncio.QueueEmpty:
                return
