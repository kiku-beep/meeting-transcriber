"""Pure helpers for incrementally updating a meeting topic tree."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


MAX_LABEL_LEN = 15
VALID_STATUSES = ("open", "decided", "parked")


class TopicNode(BaseModel):
    """A single node in the meeting topic tree."""

    id: str
    parent: str | None = None
    label: str
    status: str = "open"
    start_sec: float = 0.0
    end_sec: float = 0.0


class TopicTree(BaseModel):
    """The ordered topic tree and its active node."""

    nodes: list[TopicNode] = []
    active: str | None = None


class TopicPatch(BaseModel):
    """A proposed incremental change to a topic tree."""

    add: list[TopicNode] = []
    update: list[dict] = []
    active: str | None = None


def format_entries(entries: list[dict]) -> str:
    """Format transcript entries for a topic-tree prompt."""

    lines: list[str] = []
    for entry in entries:
        seconds = int(float(entry.get("timestamp_start", 0)))
        minutes, remainder = divmod(seconds, 60)
        speaker = entry.get("speaker_name") or "不明"
        text = entry.get("text") or ""
        lines.append(f"[{minutes:02d}:{remainder:02d}] {speaker}: {text}")
    return "\n".join(lines)


def build_patch_prompt(tree: TopicTree, entries: list[dict]) -> str:
    """Build the Japanese prompt for generating a topic-tree patch."""

    schema = (
        '{"add":[{"id":"","parent":"","label":"論点(15字以内)",'
        '"status":"open|decided|parked","start_sec":0,"end_sec":0}], '
        '"update":[{"id":"","status":"","end_sec":0}], '
        '"active":"現在話している論点のid"}'
    )
    return f"""会議の文字起こしから、論点の階層ツリーを増分更新してください。

現在のツリーJSON:
{tree.model_dump_json()}

新しい発話:
{format_entries(entries)}

次のJSONスキーマだけを出力してください。
{schema}

前置き、説明文、コードフェンスは禁止です。JSON以外の文字を出力しないでください。
新規idは既存のidと衝突しない連番にしてください。
既存論点の続きなら add せず update してください。
label は {MAX_LABEL_LEN} 字以内にしてください。
status は open / decided / parked のいずれかにしてください。
文字起こしにない内容を補わないでください。"""


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text

    first_newline = text.find("\n")
    if first_newline == -1:
        text = text[3:]
    else:
        text = text[first_newline + 1 :]

    text = text.rstrip()
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _extract_json_object(text: str) -> str:
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : index + 1]

    raise ValueError("JSONオブジェクトを抽出できません")


def _parse_add_node(data: dict[str, Any]) -> TopicNode | None:
    node_id = data.get("id")
    label = data.get("label")
    if not isinstance(node_id, str) or not node_id:
        return None
    if not isinstance(label, str) or not label.strip():
        return None

    payload = dict(data)
    for key in ("start_sec", "end_sec"):
        if key in payload:
            try:
                payload[key] = float(payload[key])
            except (TypeError, ValueError, OverflowError):
                payload[key] = 0.0

    try:
        return TopicNode.model_validate(payload)
    except (TypeError, ValueError):
        return None


def parse_patch(raw: str) -> TopicPatch:
    """Parse a tolerant LLM response into a topic-tree patch."""

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("LLM出力が空です")

    candidate = _extract_json_object(_strip_code_fence(raw.strip()))
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("LLM出力をJSONとして解釈できません") from exc

    if not isinstance(data, dict):
        raise ValueError("LLM出力のトップレベルはオブジェクトである必要があります")

    raw_add = data.get("add")
    add_items = raw_add if isinstance(raw_add, list) else []
    add: list[TopicNode] = []
    for item in add_items:
        if isinstance(item, dict):
            node = _parse_add_node(item)
            if node is not None:
                add.append(node)

    raw_update = data.get("update")
    update = (
        [item for item in raw_update if isinstance(item, dict)]
        if isinstance(raw_update, list)
        else []
    )
    active = data.get("active") if isinstance(data.get("active"), str) else None
    return TopicPatch(add=add, update=update, active=active)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _normalize_node(node: TopicNode) -> TopicNode | None:
    if not isinstance(node.id, str) or not node.id:
        return None
    if not isinstance(node.label, str) or not node.label.strip():
        return None

    start_sec = _as_float(node.start_sec)
    end_sec = _as_float(node.end_sec)
    if end_sec < start_sec:
        end_sec = start_sec

    return TopicNode(
        id=node.id,
        parent=node.parent,
        label=node.label[:MAX_LABEL_LEN],
        status=node.status if node.status in VALID_STATUSES else "open",
        start_sec=start_sec,
        end_sec=end_sec,
    )


def apply_patch(tree: TopicTree, patch: TopicPatch) -> TopicTree:
    """Return a new tree after safely applying a topic-tree patch."""

    existing_nodes = [node.model_copy(deep=True) for node in tree.nodes]
    existing_ids = {node.id for node in existing_nodes}

    candidates: list[TopicNode] = []
    reserved_ids = set(existing_ids)
    for node in patch.add:
        normalized = _normalize_node(node)
        if normalized is None:
            continue
        if normalized.id in reserved_ids or normalized.id == normalized.parent:
            continue
        reserved_ids.add(normalized.id)
        candidates.append(normalized)

    known_ids = set(existing_ids)
    pending = list(candidates)
    added_by_id: dict[str, TopicNode] = {}
    while pending:
        next_pending: list[TopicNode] = []
        progress = False
        for node in pending:
            if node.parent is None or node.parent in known_ids:
                added_by_id[node.id] = node
                known_ids.add(node.id)
                progress = True
            else:
                next_pending.append(node)
        if not progress:
            break
        pending = next_pending

    nodes = existing_nodes + [node for node in candidates if node.id in added_by_id]
    nodes_by_id = {node.id: node for node in nodes}
    for change in patch.update:
        if not isinstance(change, dict):
            continue
        change_id = change.get("id")
        if not isinstance(change_id, str):
            continue
        node = nodes_by_id.get(change_id)
        if node is None:
            continue

        status = change.get("status")
        if status in VALID_STATUSES:
            node.status = status

        if "end_sec" in change:
            try:
                new_end = float(change["end_sec"])
            except (TypeError, ValueError, OverflowError):
                continue
            if new_end > _as_float(node.end_sec):
                node.end_sec = new_end

    active = patch.active if patch.active in nodes_by_id else None
    return TopicTree(nodes=nodes, active=active)


def tree_to_dict(tree: TopicTree) -> dict:
    """Convert a topic tree into a JSON-compatible payload."""

    return {
        "nodes": [node.model_dump() for node in tree.nodes],
        "active": tree.active,
    }


def tree_from_dict(data: dict) -> TopicTree:
    """Load a topic tree defensively from a JSON-compatible payload."""

    if not isinstance(data, dict) or "nodes" not in data or "active" not in data:
        return TopicTree()
    if not isinstance(data["nodes"], list):
        return TopicTree()

    nodes: list[TopicNode] = []
    for item in data["nodes"]:
        if isinstance(item, TopicNode):
            nodes.append(item.model_copy(deep=True))
            continue
        if not isinstance(item, dict):
            continue
        try:
            nodes.append(TopicNode.model_validate(item))
        except (TypeError, ValueError):
            continue

    active = data["active"] if isinstance(data["active"], str) else None
    return TopicTree(nodes=nodes, active=active)
