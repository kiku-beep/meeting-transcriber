import json

from backend.storage.dictionary_store import DictionaryStore


def test_existing_dictionary_gets_missing_hallucination_defaults(tmp_path):
    dictionary_path = tmp_path / "dictionary.json"
    dictionary_path.write_text(
        json.dumps(
            {
                "version": 1,
                "replacements": [],
                "fillers": ["えー"],
                "filler_removal_enabled": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = DictionaryStore(dictionary_path)
    data = store.get_all()

    assert data["hallucination_filter_enabled"] is True
    assert "ありがとうございました" in data["hallucination_phrases"]

    persisted = json.loads(dictionary_path.read_text(encoding="utf-8"))
    assert persisted["hallucination_filter_enabled"] is True
    assert "ありがとうございました" in persisted["hallucination_phrases"]
