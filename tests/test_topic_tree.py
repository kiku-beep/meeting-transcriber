"""Tests for the pure topic-tree helpers."""

from __future__ import annotations

import json

import pytest


def _entry(start: float, text: str = "発言", speaker: str | None = "話者A") -> dict:
    entry = {
        "id": f"entry-{start}",
        "text": text,
        "timestamp_start": start,
        "timestamp_end": start + 1,
    }
    if speaker is not None:
        entry["speaker_name"] = speaker
    return entry


def _node(
    node_id: str,
    label: str = "論点",
    parent: str | None = None,
    status: str = "open",
    start_sec: float = 0.0,
    end_sec: float = 0.0,
) -> dict:
    return {
        "id": node_id,
        "parent": parent,
        "label": label,
        "status": status,
        "start_sec": start_sec,
        "end_sec": end_sec,
    }


def test_format_entries_formats_minutes_and_unknown_speaker():
    from backend.core.topic_tree import format_entries

    entries = [_entry(5, "最初の発言"), _entry(65, "次の発言", None)]

    assert format_entries(entries) == (
        "[00:05] 話者A: 最初の発言\n[01:05] 不明: 次の発言"
    )


def test_build_patch_prompt_includes_tree_transcript_and_fence_prohibition():
    from backend.core.topic_tree import TopicNode, TopicTree, build_patch_prompt

    tree = TopicTree(nodes=[TopicNode(id="n1", label="予算の論点")], active="n1")

    prompt = build_patch_prompt(tree, [_entry(12, "来月の予算を決めます")])

    assert "予算の論点" in prompt
    assert "来月の予算を決めます" in prompt
    assert "コードフェンス" in prompt
    assert "前置き" in prompt


def test_parse_patch_accepts_json_fences_explanations_and_braces_in_strings():
    from backend.core.topic_tree import parse_patch

    payload = {
        "add": [_node("n1", 'A } B')],
        "update": [{"id": "n1", "end_sec": 4}],
        "active": "n1",
    }
    raw_json = json.dumps(payload, ensure_ascii=False)

    parsed_plain = parse_patch(raw_json)
    parsed_fenced = parse_patch(f"```json\n{raw_json}\n```")
    parsed_explained = parse_patch(f"結果です。\n{raw_json}\n以上です。")

    assert parsed_plain == parsed_fenced == parsed_explained
    assert parsed_plain.add[0].label == "A } B"
    assert parsed_plain.active == "n1"


def test_parse_patch_rejects_empty_invalid_and_non_object_json():
    from backend.core.topic_tree import parse_patch

    for raw in ("", "これはJSONではありません", "[]"):
        with pytest.raises(ValueError):
            parse_patch(raw)


def test_parse_patch_discards_invalid_add_items_only():
    from backend.core.topic_tree import parse_patch

    parsed = parse_patch(
        json.dumps(
            {
                "add": [
                    "not a node",
                    {"label": "idなし"},
                    {"id": "n2", "label": "   "},
                    {"id": "n3", "label": "有効"},
                ]
            },
            ensure_ascii=False,
        )
    )

    assert [node.id for node in parsed.add] == ["n3"]


def test_apply_patch_adds_nodes_while_preserving_parent_relationships():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="root", label="根")])
    patch = TopicPatch(
        add=[
            TopicNode(id="child", parent="root", label="子"),
            TopicNode(id="grandchild", parent="child", label="孫"),
        ]
    )

    result = apply_patch(tree, patch)

    assert [node.id for node in result.nodes] == ["root", "child", "grandchild"]
    assert result.nodes[1].parent == "root"
    assert result.nodes[2].parent == "child"


def test_apply_patch_ignores_add_for_existing_id():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="n1", label="元のラベル", status="decided")])
    result = apply_patch(
        tree,
        TopicPatch(add=[TopicNode(id="n1", label="上書き", status="parked")]),
    )

    assert len(result.nodes) == 1
    assert result.nodes[0].label == "元のラベル"
    assert result.nodes[0].status == "decided"


def test_apply_patch_discards_orphan_nodes():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    result = apply_patch(
        TopicTree(),
        TopicPatch(add=[TopicNode(id="orphan", parent="missing", label="孤児")]),
    )

    assert result.nodes == []


def test_apply_patch_discards_circular_nodes():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    result = apply_patch(
        TopicTree(),
        TopicPatch(
            add=[
                TopicNode(id="a", parent="b", label="A"),
                TopicNode(id="b", parent="a", label="B"),
            ]
        ),
    )

    assert result.nodes == []


def test_apply_patch_resolves_forward_parent_references():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    result = apply_patch(
        TopicTree(),
        TopicPatch(
            add=[
                TopicNode(id="child", parent="parent", label="子"),
                TopicNode(id="parent", label="親"),
            ]
        ),
    )

    assert [node.id for node in result.nodes] == ["child", "parent"]
    assert result.nodes[0].parent == "parent"


def test_apply_patch_truncates_long_labels_and_discards_blank_labels():
    from backend.core.topic_tree import MAX_LABEL_LEN, TopicNode, TopicPatch, TopicTree, apply_patch

    result = apply_patch(
        TopicTree(),
        TopicPatch(
            add=[
                TopicNode(id="long", label="あいうえおかきくけこさしすせそた"),
                TopicNode(id="blank", label=" \t"),
            ]
        ),
    )

    assert [node.id for node in result.nodes] == ["long"]
    assert result.nodes[0].label == "あいうえおかきくけこさしすせそ"
    assert len(result.nodes[0].label) == MAX_LABEL_LEN


def test_apply_patch_normalizes_invalid_status_and_reversed_times():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    result = apply_patch(
        TopicTree(),
        TopicPatch(
            add=[
                TopicNode(
                    id="n1",
                    label="論点",
                    status="invalid",
                    start_sec=12,
                    end_sec=4,
                )
            ]
        ),
    )

    assert result.nodes[0].status == "open"
    assert result.nodes[0].start_sec == 12
    assert result.nodes[0].end_sec == 12


def test_apply_patch_ignores_unknown_updates_and_prevents_end_time_regression():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="n1", label="論点", end_sec=10)])
    result = apply_patch(
        tree,
        TopicPatch(
            update=[
                {"id": "missing", "end_sec": 99},
                {"id": "n1", "end_sec": 3},
            ]
        ),
    )

    assert len(result.nodes) == 1
    assert result.nodes[0].end_sec == 10


def test_apply_patch_ignores_update_attempts_to_change_label_and_parent():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="n1", label="元", parent="root")])
    result = apply_patch(
        tree,
        TopicPatch(
            update=[
                {"id": "n1", "label": "変更", "parent": "別", "status": "decided"}
            ]
        ),
    )

    assert result.nodes[0].label == "元"
    assert result.nodes[0].parent == "root"
    assert result.nodes[0].status == "decided"


def test_apply_patch_accepts_existing_active_and_clears_unknown_active():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="n1", label="論点")])

    assert apply_patch(tree, TopicPatch(active="n1")).active == "n1"
    assert apply_patch(tree, TopicPatch(active="missing")).active is None


def test_apply_patch_does_not_mutate_input_tree():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, apply_patch

    tree = TopicTree(nodes=[TopicNode(id="n1", label="元", end_sec=5)])
    before = tree.model_dump()

    result = apply_patch(
        tree,
        TopicPatch(
            add=[TopicNode(id="n2", label="追加")],
            update=[{"id": "n1", "status": "decided", "end_sec": 10}],
        ),
    )

    assert tree.model_dump() == before
    assert result is not tree
    assert result.nodes[0] is not tree.nodes[0]


def test_tree_from_dict_returns_empty_tree_for_invalid_inputs():
    from backend.core.topic_tree import tree_from_dict, tree_to_dict

    for data in (None, [], {}, {"nodes": "not a list"}):
        tree = tree_from_dict(data)
        assert tree_to_dict(tree) == {"nodes": [], "active": None}


def test_tree_to_dict_and_tree_from_dict_round_trip():
    from backend.core.topic_tree import TopicNode, TopicTree, tree_from_dict, tree_to_dict

    tree = TopicTree(
        nodes=[
            TopicNode(id="root", label="根", start_sec=1, end_sec=4),
            TopicNode(id="child", parent="root", label="子", status="parked"),
        ],
        active="child",
    )
    serialized = tree_to_dict(tree)

    assert tree_to_dict(tree_from_dict(serialized)) == serialized


def test_apply_patch_ignores_updates_with_non_string_id():
    from backend.core.topic_tree import (
        TopicNode,
        TopicPatch,
        TopicTree,
        apply_patch,
        parse_patch,
    )

    tree = TopicTree(nodes=[TopicNode(id="t1", label="論点A", end_sec=10)])

    # LLM が id に文字列以外を返しても落ちず、その update だけ無視する
    for bad_id in (["t1"], {"id": "t1"}, 1, None):
        patched = apply_patch(
            tree,
            TopicPatch(update=[{"id": bad_id, "status": "decided", "end_sec": 99}]),
        )
        assert patched.nodes[0].status == "open"
        assert patched.nodes[0].end_sec == 10

    # 生の LLM 出力からの経路でも落ちない
    raw = '{"add":[],"update":[{"id":["t1"],"status":"decided"}],"active":null}'
    patched = apply_patch(tree, parse_patch(raw))
    assert patched.nodes[0].status == "open"


def test_reserve_ids_reassigns_add_id_that_collides_with_existing_tree():
    from backend.core.topic_tree import (
        TopicNode,
        TopicPatch,
        TopicTree,
        reserve_ids,
    )

    tree = TopicTree(nodes=[TopicNode(id="t1", label="既存")])
    reserved = reserve_ids(
        tree,
        TopicPatch(add=[TopicNode(id="t1", label="新規")]),
    )

    assert reserved.add[0].id == "t2"


def test_reserve_ids_follows_reassigned_parent_and_active_references():
    from backend.core.topic_tree import (
        TopicNode,
        TopicPatch,
        TopicTree,
        reserve_ids,
    )

    tree = TopicTree(nodes=[TopicNode(id="t1", label="既存")])
    patch = TopicPatch(
        add=[
            TopicNode(id="t1", label="親"),
            TopicNode(id="child", parent="t1", label="子"),
        ],
        active="t1",
    )

    reserved = reserve_ids(tree, patch)

    assert [node.id for node in reserved.add] == ["t2", "child"]
    assert reserved.add[1].parent == "t2"
    assert reserved.active == "t2"


def test_reserve_ids_does_not_reassign_update_ids():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, reserve_ids

    tree = TopicTree(nodes=[TopicNode(id="t1", label="既存")])
    reserved = reserve_ids(
        tree,
        TopicPatch(
            add=[TopicNode(id="t1", label="新規")],
            update=[{"id": "t1", "status": "decided"}],
        ),
    )

    assert reserved.update == [{"id": "t1", "status": "decided"}]


def test_reserve_ids_preserves_non_colliding_patch_content():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, reserve_ids

    tree = TopicTree(nodes=[TopicNode(id="root", label="根")])
    patch = TopicPatch(
        add=[TopicNode(id="child", parent="root", label="子")],
        update=[{"id": "root", "end_sec": 5}],
        active="child",
    )

    reserved = reserve_ids(tree, patch)

    assert reserved == patch
    assert reserved is not patch


def test_reserve_ids_does_not_mutate_tree_or_patch():
    from backend.core.topic_tree import TopicNode, TopicPatch, TopicTree, reserve_ids

    tree = TopicTree(nodes=[TopicNode(id="t1", label="既存")])
    patch = TopicPatch(
        add=[TopicNode(id="t1", parent=None, label="新規")],
        update=[{"id": "t1", "status": "decided"}],
        active="t1",
    )
    tree_before = tree.model_dump()
    patch_before = patch.model_dump()

    reserve_ids(tree, patch)

    assert tree.model_dump() == tree_before
    assert patch.model_dump() == patch_before


def test_select_tree_for_prompt_returns_equivalent_new_tree_within_limit():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[TopicNode(id="root", label="根"), TopicNode(id="child", parent="root", label="子")],
        active="child",
    )

    selected = select_tree_for_prompt(
        tree,
        max_nodes=2,
        recent_window_sec=10,
        now_sec=100,
    )

    assert selected == tree
    assert selected is not tree
    assert selected.nodes[0] is not tree.nodes[0]


def test_select_tree_for_prompt_keeps_all_top_level_nodes_when_over_limit():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[
            TopicNode(id="root-a", label="A"),
            TopicNode(id="root-b", label="B"),
            TopicNode(id="root-c", label="C"),
            TopicNode(id="old", parent="root-a", label="古い", end_sec=1),
        ]
    )

    selected = select_tree_for_prompt(
        tree,
        max_nodes=2,
        recent_window_sec=10,
        now_sec=100,
    )

    assert [node.id for node in selected.nodes[:3]] == ["root-a", "root-b", "root-c"]


def test_select_tree_for_prompt_keeps_recent_nodes_and_all_ancestors():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[
            TopicNode(id="root", label="根", end_sec=10),
            TopicNode(id="middle", parent="root", label="中", end_sec=20),
            TopicNode(id="recent", parent="middle", label="最近", end_sec=95),
            TopicNode(id="old-leaf", parent="root", label="古い", end_sec=5),
        ],
        active="recent",
    )

    selected = select_tree_for_prompt(
        tree,
        max_nodes=3,
        recent_window_sec=10,
        now_sec=100,
    )
    selected_ids = {node.id for node in selected.nodes}

    assert {"root", "middle", "recent"} <= selected_ids
    assert all(node.parent is None or node.parent in selected_ids for node in selected.nodes)


def test_select_tree_for_prompt_drops_old_leaf_when_recent_selection_fits():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[
            TopicNode(id="root", label="根", end_sec=100),
            TopicNode(id="recent", parent="root", label="最近", end_sec=98),
            TopicNode(id="old-leaf", parent="root", label="古い", end_sec=1),
        ]
    )

    selected = select_tree_for_prompt(
        tree,
        max_nodes=2,
        recent_window_sec=10,
        now_sec=100,
    )

    assert [node.id for node in selected.nodes] == ["root", "recent"]


def test_select_tree_for_prompt_clears_active_when_active_node_is_dropped():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[
            TopicNode(id="root", label="根", end_sec=100),
            TopicNode(id="old-leaf", parent="root", label="古い", end_sec=1),
            TopicNode(id="new-leaf", parent="root", label="新しい", end_sec=99),
        ],
        active="old-leaf",
    )

    selected = select_tree_for_prompt(
        tree,
        max_nodes=2,
        recent_window_sec=10,
        now_sec=100,
    )

    assert selected.active is None


def test_select_tree_for_prompt_does_not_mutate_tree():
    from backend.core.topic_tree import TopicNode, TopicTree, select_tree_for_prompt

    tree = TopicTree(
        nodes=[
            TopicNode(id="root", label="根"),
            TopicNode(id="leaf", parent="root", label="葉", end_sec=1),
        ],
        active="leaf",
    )
    before = tree.model_dump()

    select_tree_for_prompt(tree, max_nodes=1, recent_window_sec=0, now_sec=100)

    assert tree.model_dump() == before
