"""Pass 2 text refinement using Gemini Flash API."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.config import Settings
    from backend.storage.dictionary_store import DictionaryStore
    from backend.models.schemas import TranscriptEntry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """あなたは建材メーカー（モノクローム株式会社）の会議文字起こし校正者です。
音声認識の誤変換を修正してください。

ルール:
- 漢字の誤変換を文脈から判断して修正
- 以下の専門用語辞書に従って固有名詞を正しく表記
- 文意は絶対に変えない。誤変換の修正のみ行う
- 句読点の追加・削除はしない
- 出力はJSON配列のみ（説明不要）"""


class TextRefiner:
    """Background task that refines transcript entries via Gemini API."""

    def __init__(self, settings: Settings, dictionary_store: DictionaryStore):
        self.enabled = settings.text_refine_enabled and bool(settings.gemini_api_key)
        self.batch_size = settings.text_refine_batch_size
        self.delay_s = settings.text_refine_delay_s
        self.api_key = settings.gemini_api_key
        self.model = settings.text_refine_model
        self._dictionary_store = dictionary_store
        self._dict_prompt: str = ""
        self._task: asyncio.Task | None = None
        self._entries: list[TranscriptEntry] = []
        self._refined_queue: asyncio.Queue[list[dict]] = asyncio.Queue()
        self._last_refined_index: int = 0
        self._consecutive_failures: int = 0
        self._backoff_s: float = 0.0

        if not self.enabled:
            if not settings.gemini_api_key:
                logger.warning("TextRefiner disabled: GEMINI_API_KEY not set")
            else:
                logger.info("TextRefiner disabled by config")

    def start(self, entries: list[TranscriptEntry]) -> None:
        """Start the background refinement loop."""
        if not self.enabled:
            return
        self._entries = entries
        self._last_refined_index = 0
        self._dict_prompt = self._build_dictionary_prompt()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("TextRefiner started (model=%s, batch=%d)", self.model, self.batch_size)

    async def stop(self) -> None:
        """Stop the refinement loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("TextRefiner stopped")

    def _build_dictionary_prompt(self) -> str:
        """Build dictionary section for the prompt from dictionary_store."""
        replacements = self._dictionary_store.get_replacements()
        lines = []
        for r in replacements:
            if r.get("enabled", True) and not r.get("is_regex", False):
                lines.append(f"- {r['from']} → {r['to']}")
        if not lines:
            return "（辞書なし）"
        return "\n".join(lines)

    async def _run_loop(self) -> None:
        """Main loop: wait for unrefined entries, batch and refine."""
        try:
            while True:
                await self._wait_for_batch()

                batch = self._collect_batch()
                if not batch:
                    continue

                if self._backoff_s > 0:
                    await asyncio.sleep(self._backoff_s)

                refined = await self._refine_batch(batch)
                if refined:
                    self._apply_refinements(batch, refined)
                    self._consecutive_failures = 0
                    self._backoff_s = 0.0

        except asyncio.CancelledError:
            logger.debug("TextRefiner loop cancelled")
            raise

    async def _wait_for_batch(self) -> None:
        """Wait until batch_size unrefined entries exist or delay_s elapses."""
        while True:
            unrefined_count = len(self._entries) - self._last_refined_index
            if unrefined_count >= self.batch_size:
                return
            if unrefined_count > 0:
                await asyncio.sleep(self.delay_s)
                return
            await asyncio.sleep(0.5)

    def _collect_batch(self) -> list[TranscriptEntry]:
        """Collect next batch of unrefined entries."""
        start = self._last_refined_index
        end = min(start + self.batch_size, len(self._entries))
        if start >= end:
            return []
        return self._entries[start:end]

    def _build_context(self, batch_start: int) -> str:
        """Build context from previous refined entries."""
        context_start = max(0, batch_start - 5)
        context_entries = self._entries[context_start:batch_start]
        if not context_entries:
            return "（なし）"
        lines = []
        for e in context_entries:
            lines.append(f"{e.speaker_name}: {e.text}")
        return "\n".join(lines)

    async def _refine_batch(self, batch: list[TranscriptEntry]) -> list[dict] | None:
        """Call Gemini API to refine a batch of entries."""
        context = self._build_context(self._last_refined_index)
        target = json.dumps(
            [{"id": e.id, "text": e.text} for e in batch],
            ensure_ascii=False,
        )

        user_prompt = f"""【専門用語辞書】
{self._dict_prompt}

【直前の文脈（補正済み）】
{context}

【補正対象】
{target}

出力形式: [{{"id": "xxx", "text": "補正後テキスト"}}]"""

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]}
            ],
            "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self.api_key}"
        )

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._call_api, url, payload
            )
            return result
        except Exception as e:
            self._handle_failure(e)
            return None

    def _call_api(self, url: str, payload: dict) -> list[dict] | None:
        """Synchronous API call (run in executor)."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = e.code
            if status == 429:
                retry_after = e.headers.get("Retry-After", "5")
                self._backoff_s = float(retry_after)
                logger.warning("Gemini rate limited, backoff %.1fs", self._backoff_s)
            elif 400 <= status < 500:
                logger.error("Gemini client error %d, not retrying", status)
                self._backoff_s = 0
            else:
                raise
            return None

        # Parse response
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            if not isinstance(result, list):
                logger.warning("Gemini returned non-list: %s", type(result))
                return None
            return result
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse Gemini response: %s", e)
            return None

    def _apply_refinements(
        self, batch: list[TranscriptEntry], refined: list[dict]
    ) -> None:
        """Apply refined texts to entries and queue for WS notification."""
        batch_ids = {e.id for e in batch}
        updates = []

        for item in refined:
            entry_id = item.get("id")
            new_text = item.get("text")
            if not entry_id or not new_text or entry_id not in batch_ids:
                continue

            for entry in batch:
                if entry.id == entry_id:
                    if entry.text != new_text:
                        entry.text = new_text
                    entry.refined = True
                    updates.append({"id": entry.id, "text": entry.text, "refined": True})
                    break

        # Mark entries not in response as refined too (no change needed)
        for entry in batch:
            if not entry.refined:
                entry.refined = True

        self._last_refined_index += len(batch)

        if updates:
            self._refined_queue.put_nowait(updates)
            logger.debug("Refined %d entries, %d changed", len(batch), len(updates))

    def _handle_failure(self, error: Exception) -> None:
        """Handle API call failure with exponential backoff."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._backoff_s = min(10 * (2 ** (self._consecutive_failures - 3)), 60)
            logger.warning(
                "TextRefiner: %d consecutive failures, backoff %.1fs: %s",
                self._consecutive_failures, self._backoff_s, error,
            )
        else:
            logger.warning("TextRefiner API error: %s", error)
