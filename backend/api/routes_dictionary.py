from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.post_processor import test_post_process
from backend.storage.dictionary_store import get_dictionary_store

router = APIRouter(prefix="/api/dictionary", tags=["dictionary"])


class ReplacementRule(BaseModel):
    from_text: str
    to_text: str
    case_sensitive: bool = False
    enabled: bool = True
    is_regex: bool = False
    note: str = ""


class FillerConfig(BaseModel):
    fillers: list[str] | None = None
    filler_removal_enabled: bool | None = None


class HallucinationConfig(BaseModel):
    hallucination_phrases: list[str] | None = None
    hallucination_filter_enabled: bool | None = None


class TestInput(BaseModel):
    text: str


@router.get("")
async def get_dictionary():
    store = get_dictionary_store()
    return store.get_all()


@router.post("/reload")
async def reload_dictionary():
    store = get_dictionary_store()
    store.reload()
    return store.get_all()


@router.post("")
async def add_replacement(rule: ReplacementRule):
    store = get_dictionary_store()
    try:
        result = store.add_replacement(
            rule.from_text, rule.to_text, rule.case_sensitive, rule.enabled,
            rule.is_regex, rule.note,
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    return result


# IMPORTANT: /suggestions, /corrections, /fillers must be declared before /{index}
# to avoid route conflict (FastAPI would treat them as an index parameter otherwise)

@router.get("/suggestions")
async def get_suggestions():
    """Get dictionary rule suggestions from correction analysis."""
    from backend.core.correction_learner import analyze_corrections
    return {"suggestions": analyze_corrections()}


@router.post("/suggestions/accept")
async def accept_suggestion(req: ReplacementRule):
    """Accept a learning suggestion and add it to dictionary."""
    from backend.core.correction_learner import accept_suggestion as _accept
    try:
        rule = _accept(req.from_text, req.to_text)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return rule


@router.get("/corrections")
async def get_corrections():
    """Get all recorded corrections."""
    from backend.storage.correction_store import get_correction_store
    store = get_correction_store()
    return {"corrections": store.get_all()}


@router.put("/hallucination-phrases")
async def update_hallucination_phrases(config: HallucinationConfig):
    store = get_dictionary_store()
    if config.hallucination_phrases is not None:
        store.set_hallucination_phrases(config.hallucination_phrases)
    if config.hallucination_filter_enabled is not None:
        store.set_hallucination_filter_enabled(config.hallucination_filter_enabled)
    return store.get_all()


@router.put("/fillers")
async def update_fillers(config: FillerConfig):
    store = get_dictionary_store()
    if config.fillers is not None:
        store.set_fillers(config.fillers)
    if config.filler_removal_enabled is not None:
        store.set_filler_removal_enabled(config.filler_removal_enabled)
    return store.get_all()


@router.put("/{index}")
async def update_replacement(index: int, rule: ReplacementRule):
    store = get_dictionary_store()
    try:
        result = store.update_replacement(index, {
            "from": rule.from_text,
            "to": rule.to_text,
            "case_sensitive": rule.case_sensitive,
            "enabled": rule.enabled,
            "is_regex": rule.is_regex,
            "note": rule.note,
        })
        return result
    except IndexError:
        raise HTTPException(404, "Replacement rule not found")


@router.delete("/{index}")
async def delete_replacement(index: int):
    store = get_dictionary_store()
    if not store.delete_replacement(index):
        raise HTTPException(404, "Replacement rule not found")
    return {"deleted": True}


@router.post("/test")
async def test_dictionary(input: TestInput):
    return test_post_process(input.text)
