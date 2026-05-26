from backend.models import pipeline as pipeline_mod


class FakeDictionaryStore:
    def __init__(self, data):
        self._data = data

    def get_all(self):
        return self._data


def make_pipeline():
    return object.__new__(pipeline_mod.TranscriptionPipeline)


def test_strict_standalone_thanks_phrase_is_filtered_even_when_rescue_metrics_are_good(monkeypatch):
    monkeypatch.setattr(
        pipeline_mod,
        "get_dictionary_store",
        lambda: FakeDictionaryStore(
            {
                "hallucination_filter_enabled": True,
                "hallucination_phrases": ["ありがとうございました"],
            }
        ),
    )

    pipeline = make_pipeline()

    assert pipeline._is_hallucination_phrase(
        "ありがとうございました",
        duration=12.0,
        no_speech_prob=0.01,
        avg_logprob=-0.1,
        speech_ratio=0.95,
    )


def test_embedded_thanks_phrase_is_allowed(monkeypatch):
    monkeypatch.setattr(
        pipeline_mod,
        "get_dictionary_store",
        lambda: FakeDictionaryStore(
            {
                "hallucination_filter_enabled": True,
                "hallucination_phrases": ["ありがとうございました"],
            }
        ),
    )

    pipeline = make_pipeline()

    assert not pipeline._is_hallucination_phrase(
        "それではありがとうございました",
        duration=12.0,
        no_speech_prob=0.01,
        avg_logprob=-0.1,
        speech_ratio=0.95,
    )
