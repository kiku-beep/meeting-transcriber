"""Pure helpers for incrementally updating a meeting topic tree."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from pydantic import BaseModel


MAX_LABEL_LEN = 15
MAX_DETAIL_LEN = 120
VALID_STATUSES = ("open", "decided", "parked")
VALID_KINDS = ("question", "claim", "constraint", "decision")
VALID_LINK_TYPES = ("supports", "objects", "constrains", "depends")
# 実機（PIVOT 動画 2:00-8:56）で LLM が話の順に前の論点の子へ次々つなげ、
# 深さ5の一本鎖になった。プロンプトで抑えつつ、超えた分はここで親を繰り上げる。
MAX_DEPTH = 3


class TopicNode(BaseModel):
    """A single node in the meeting topic tree."""

    id: str
    parent: str | None = None
    label: str
    detail: str = ""
    kind: str = "question"
    status: str = "open"
    start_sec: float = 0.0
    end_sec: float = 0.0


class TopicLink(BaseModel):
    """A typed relation between two topic nodes."""

    source: str
    target: str
    type: str = "objects"


class TopicTree(BaseModel):
    """The ordered topic tree and its active node."""

    nodes: list[TopicNode] = []
    links: list[TopicLink] = []
    active: str | None = None


class TopicPatch(BaseModel):
    """A proposed incremental change to a topic tree."""

    add: list[TopicNode] = []
    add_links: list[TopicLink] = []
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

    # parent は必ず null か既存id。空文字を例示すると LLM が root に "" を返し、
    # 孤児として全部捨てられてツリーが永久に空になる（実測で確認済み）。
    schema = (
        '{"add":[{"id":"t1","parent":null,"label":"論点(15字以内)",'
        '"detail":"補足(120字以内)",'
        '"kind":"question|claim|constraint|decision",'
        '"status":"open|decided|parked","start_sec":0,"end_sec":0}], '
        '"add_links":[{"source":"t1","target":"t2",'
        '"type":"supports|objects|constrains|depends"}], '
        '"update":[{"id":"t1","status":"open|decided|parked",'
        '"detail":"補足(120字以内)","end_sec":0}], '
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
最上位の論点は parent を null にしてください（空文字は不可）。
子の論点は parent に親のidを入れてください。
階層は最大{MAX_DEPTH}段（最上位・子・孫）です。それより深くしないでください。
新しい大きなテーマに移ったら parent を null にして最上位に置いてください。
直前の論点の子にするのは、その論点を具体的に掘り下げている場合だけです。
話の順番に沿って前の論点の下へ次々つなげないでください。
新規idは既存のidと衝突しない連番にしてください。
既存論点の続きなら add せず update してください。
label は {MAX_LABEL_LEN} 字以内にしてください。
status は open / decided / parked のいずれかにしてください。
「〜すべきか」という問いは kind を question、案・立場は claim、動かせない条件・コスト・仕様・人員の話は constraint、合意・保留は decision にしてください。
反論・制約は必ず別ノードにして add_links で繋いでください。claim の label に「〜だが難しい」と押し込まないでください。
add_links の source / target は既存idか同じパッチ内の新規idだけにしてください。
リンクの type は supports / objects / constrains / depends のいずれかにしてください。
リンクが1本も無い更新では add_links を [] にしてください。
detail には label に入り切らない中身を1〜2文で書いてください。
status が open の detail は、何が対立点かと、何が決まれば決着するかを書いてください。
status が decided の detail は、何にどう決めたかと、その理由を書いてください。
status が parked の detail は、なぜ保留かと、再開の条件を書いてください。
status を open から decided へ update するときは、detail も決定内容へ書き換えてください。
detail は120字以内にしてください。文字起こしから読み取れないなら空文字にしてください。
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


def _parse_link(data: Any) -> TopicLink | None:
    if not isinstance(data, dict):
        return None

    source = data.get("source")
    target = data.get("target")
    link_type = data.get("type")
    if (
        not isinstance(source, str)
        or not source.strip()
        or not isinstance(target, str)
        or not target.strip()
        or link_type not in VALID_LINK_TYPES
    ):
        return None

    try:
        return TopicLink(source=source, target=target, type=link_type)
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

    raw_add_links = data.get("add_links")
    add_links: list[TopicLink] = []
    if isinstance(raw_add_links, list):
        for item in raw_add_links:
            link = _parse_link(item)
            if link is not None:
                add_links.append(link)

    raw_update = data.get("update")
    update = (
        [item for item in raw_update if isinstance(item, dict)]
        if isinstance(raw_update, list)
        else []
    )
    active = data.get("active") if isinstance(data.get("active"), str) else None
    return TopicPatch(add=add, add_links=add_links, update=update, active=active)


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

    # LLMは最上位論点の parent に空文字を返すことがある。None に寄せないと
    # 未知の親として孤児判定され、rootが1つも入らずツリーが永久に空になる。
    parent = node.parent
    if isinstance(parent, str) and not parent.strip():
        parent = None
    detail = node.detail if isinstance(node.detail, str) else ""
    detail = detail.strip()[:MAX_DETAIL_LEN]

    return TopicNode(
        id=node.id,
        parent=parent,
        label=node.label[:MAX_LABEL_LEN],
        detail=detail,
        kind=node.kind if node.kind in VALID_KINDS else "question",
        status=node.status if node.status in VALID_STATUSES else "open",
        start_sec=start_sec,
        end_sec=end_sec,
    )


def _depth(node_id: str, lookup: dict[str, TopicNode]) -> int:
    """Return 1 for a root, 2 for its child, ... (cycle-safe)."""
    depth = 0
    seen: set[str] = set()
    current: str | None = node_id
    while current is not None and current in lookup and current not in seen:
        seen.add(current)
        depth += 1
        current = lookup[current].parent
    return depth


def _clamp_parent_depth(parent: str | None, lookup: dict[str, TopicNode]) -> str | None:
    """Re-parent so the new node never exceeds MAX_DEPTH.

    LLMは話の順に直前の論点の子へ次々つなぎ、一本鎖を作る。子として置く
    深さが MAX_DEPTH を超える場合は、収まる祖先まで繰り上げる。
    """
    while parent is not None and parent in lookup and _depth(parent, lookup) >= MAX_DEPTH:
        parent = lookup[parent].parent
    return parent


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

    accepted: dict[str, TopicNode] = {node.id: node for node in existing_nodes}
    pending = list(candidates)
    added_by_id: dict[str, TopicNode] = {}
    while pending:
        next_pending: list[TopicNode] = []
        progress = False
        for node in pending:
            if node.parent is None or node.parent in accepted:
                node.parent = _clamp_parent_depth(node.parent, accepted)
                accepted[node.id] = node
                added_by_id[node.id] = node
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

        if isinstance(change.get("detail"), str):
            detail = change["detail"].strip()
            if detail:
                node.detail = detail[:MAX_DETAIL_LEN]

        if "end_sec" in change:
            try:
                new_end = float(change["end_sec"])
            except (TypeError, ValueError, OverflowError):
                continue
            if new_end > _as_float(node.end_sec):
                node.end_sec = new_end

    final_node_ids = set(nodes_by_id)
    existing_links: list[TopicLink] = []
    accepted_links: list[TopicLink] = []
    seen_links: set[tuple[str, str, str]] = set()

    def accept_link(raw_link: Any, destination: list[TopicLink]) -> None:
        if not isinstance(raw_link, TopicLink):
            return
        link = raw_link.model_copy(deep=True)
        if (
            not isinstance(link.source, str)
            or not isinstance(link.target, str)
            or not link.source
            or not link.target
            or link.source == link.target
            or link.source not in final_node_ids
            or link.target not in final_node_ids
            or link.type not in VALID_LINK_TYPES
        ):
            return
        key = (link.source, link.target, link.type)
        if key in seen_links:
            return
        seen_links.add(key)
        destination.append(link)

    for link in tree.links:
        accept_link(link, existing_links)
    for link in patch.add_links:
        accept_link(link, accepted_links)

    active = patch.active if patch.active in nodes_by_id else None
    return TopicTree(
        nodes=nodes,
        links=existing_links + accepted_links,
        active=active,
    )


def reserve_ids(tree: TopicTree, patch: TopicPatch) -> TopicPatch:
    """Reserve collision-free ids for added nodes without mutating inputs."""

    existing_ids = {node.id for node in tree.nodes}
    used_ids = set(existing_ids)
    assigned_ids: list[str] = []
    remapped_ids: dict[str, str] = {}
    next_number = 1

    for node in patch.add:
        node_id = node.id
        if node_id in used_ids:
            while f"t{next_number}" in used_ids:
                next_number += 1
            assigned_id = f"t{next_number}"
            next_number += 1
        else:
            assigned_id = node_id
        used_ids.add(assigned_id)
        assigned_ids.append(assigned_id)
        remapped_ids.setdefault(node_id, assigned_id)

    add: list[TopicNode] = []
    for node, assigned_id in zip(patch.add, assigned_ids):
        add.append(
            node.model_copy(
                deep=True,
                update={
                    "id": assigned_id,
                    "parent": remapped_ids.get(node.parent, node.parent),
                },
            )
        )

    active = remapped_ids.get(patch.active, patch.active)
    add_links = [
        link.model_copy(
            deep=True,
            update={
                "source": remapped_ids.get(link.source, link.source),
                "target": remapped_ids.get(link.target, link.target),
            },
        )
        for link in patch.add_links
    ]
    return TopicPatch(
        add=add,
        add_links=add_links,
        update=[deepcopy(change) for change in patch.update],
        active=active,
    )


def select_tree_for_prompt(
    tree: TopicTree,
    *,
    max_nodes: int,
    recent_window_sec: float,
    now_sec: float,
) -> TopicTree:
    """Return a bounded, structurally complete copy of a topic tree."""

    copied_nodes = [node.model_copy(deep=True) for node in tree.nodes]
    if len(copied_nodes) <= max_nodes:
        selected_ids = {node.id for node in copied_nodes}
        links = [
            link.model_copy(deep=True)
            for link in tree.links
            if link.source in selected_ids
            and link.target in selected_ids
            and link.type in VALID_LINK_TYPES
        ]
        return TopicTree(nodes=copied_nodes, links=links, active=tree.active)

    nodes_by_id = {node.id: node for node in copied_nodes}
    top_level_ids = {node.id for node in copied_nodes if node.parent is None}

    def ancestor_chain(node_id: str) -> list[str] | None:
        chain: list[str] = []
        seen: set[str] = set()
        current_id: str | None = node_id
        while current_id is not None:
            if current_id in seen or current_id not in nodes_by_id:
                return None
            seen.add(current_id)
            chain.append(current_id)
            current_id = nodes_by_id[current_id].parent
        return chain

    selected_ids = set(top_level_ids)
    recent_cutoff = now_sec - recent_window_sec
    for node in copied_nodes:
        if node.end_sec >= recent_cutoff:
            chain = ancestor_chain(node.id)
            if chain is not None:
                selected_ids.update(chain)

    if len(selected_ids) > max_nodes:
        selected_ids = set(top_level_ids)
        optional_added = False
        candidates = sorted(
            (node for node in copied_nodes if node.id not in top_level_ids),
            key=lambda node: node.end_sec,
            reverse=True,
        )
        for node in candidates:
            chain = ancestor_chain(node.id)
            if chain is None:
                continue
            chain_ids = set(chain)
            if len(selected_ids | chain_ids) <= max_nodes:
                selected_ids.update(chain_ids)
                optional_added = True
            elif len(selected_ids) <= max_nodes and not optional_added:
                # Keep the newest complete branch even when its ancestors
                # make the soft node target unavoidable.
                selected_ids.update(chain_ids)
                optional_added = True

    selected_nodes = [node for node in copied_nodes if node.id in selected_ids]
    active = tree.active if tree.active in selected_ids else None
    links = [
        link.model_copy(deep=True)
        for link in tree.links
        if link.source in selected_ids
        and link.target in selected_ids
        and link.type in VALID_LINK_TYPES
    ]
    return TopicTree(nodes=selected_nodes, links=links, active=active)


def tree_to_dict(tree: TopicTree) -> dict:
    """Convert a topic tree into a JSON-compatible payload."""

    return {
        "nodes": [node.model_dump() for node in tree.nodes],
        "links": [link.model_dump() for link in tree.links],
        "active": tree.active,
    }


def tree_from_dict(data: dict) -> TopicTree:
    """Load a topic tree defensively from a JSON-compatible payload."""

    if not isinstance(data, dict) or "nodes" not in data:
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

    links: list[TopicLink] = []
    raw_links = data.get("links")
    if isinstance(raw_links, list):
        for item in raw_links:
            link = _parse_link(item)
            if link is not None:
                links.append(link)

    active = data.get("active") if isinstance(data.get("active"), str) else None
    return TopicTree(nodes=nodes, links=links, active=active)
