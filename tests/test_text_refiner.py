import asyncio
from types import SimpleNamespace

from backend.config import Settings
from backend.core.text_refiner import TextRefiner
from backend.models.schemas import TranscriptEntry


class FakeDictionaryStore:
    def get_replacements(self):
        return []


class RecordingTextRefiner(TextRefiner):
    def __init__(self, settings):
        super().__init__(settings, FakeDictionaryStore())
        self.calls: list[list[str]] = []

    async def _refine_batch(self, batch):
        self.calls.append([entry.id for entry in batch])
        return [
            {"id": entry.id, "text": f"{entry.text} refined"}
            for entry in batch
        ]


def make_settings(**overrides):
    values = {
        "text_refine_enabled": True,
        "text_refine_batch_size": 5,
        "text_refine_delay_s": 3.0,
        "text_refine_model": "gemini-test",
        "gemini_api_key": "test-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_text_refinement_defaults_to_off(monkeypatch):
    monkeypatch.delenv("TEXT_REFINE_ENABLED", raising=False)

    cfg = Settings(_env_file=None)

    assert cfg.text_refine_enabled is False


def test_start_defers_ai_refinement_until_stop():
    async def scenario():
        entries = [
            TranscriptEntry(id="a", text="屋根材"),
            TranscriptEntry(id="b", text="外壁材"),
        ]
        refiner = RecordingTextRefiner(make_settings())

        refiner.start(entries)

        assert refiner._task is None
        assert refiner.calls == []
        assert [entry.refined for entry in entries] == [False, False]

        await refiner.stop()

        assert refiner.calls == [["a", "b"]]
        assert [entry.text for entry in entries] == [
            "屋根材 refined",
            "外壁材 refined",
        ]
        assert [entry.refined for entry in entries] == [True, True]
        assert refiner._refined_queue.get_nowait() == [
            {"id": "a", "text": "屋根材 refined", "refined": True},
            {"id": "b", "text": "外壁材 refined", "refined": True},
        ]

    asyncio.run(scenario())


def test_stop_can_skip_final_refinement_for_discard():
    async def scenario():
        entries = [TranscriptEntry(id="a", text="屋根材")]
        refiner = RecordingTextRefiner(make_settings())

        refiner.start(entries)
        await refiner.stop(refine_pending=False)

        assert refiner.calls == []
        assert entries[0].text == "屋根材"
        assert entries[0].refined is False

    asyncio.run(scenario())
