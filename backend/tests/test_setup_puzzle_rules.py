"""第一包任务 2：开书拼图的快照规则、校验与中文上下文。"""

from copy import deepcopy

import pytest

from app.agents.context import format_direction_choice, format_locked, format_target_node
from app.agents.setup_puzzle import clean_reveals, merge_nodes, normalize_lore, normalize_outline, piece_warnings
from app.services.setup_store import remap_node_refs


@pytest.fixture(autouse=True)
def glossary_names(monkeypatch):
    monkeypatch.setattr(
        "app.agents.glossary.terms", lambda: [(name, "解释") for name in ("欲扬先抑", "打脸三拍", "信息差", "伏笔回收")]
    )


def node(id_, kind="milestone", status="pencil", volume=1):
    return {
        "id": id_,
        "kind": kind,
        "title": str(id_ or "新增"),
        "event": "原事件",
        "prerequisite": "原前提",
        "consequence": "原后果",
        "volume": volume,
        "status": status,
        "origin": "author",
        "editor_note": "作者批注",
        "techniques": ["欲扬先抑"],
    }


def test_merge_nodes_ref_preserves_pin_and_origin_but_accepts_referenced_position():
    current = [node("a", "opening"), node("b", status="pinned"), node("c", status="empty"), node("d", "ending")]
    original = deepcopy(current)
    merged = merge_nodes(
        [
            {"ref": 1, "kind": "开篇", "title": "开篇新名"},
            {"ref": 3, "kind": "节点", "event": "填好空位", "techniques": ["表外", "信息差", "信息差"]},
            {"ref": 2, "kind": "节点", "event": "不准覆盖", "volume": 99},
            {"ref": 0, "kind": "节点", "title": "新增节点"},
            {"ref": 4, "kind": "结局"},
        ],
        current,
    )
    assert current == original
    assert [item["id"] for item in merged] == ["a", "c", "b", None, "d"]
    assert {key: value for key, value in merged[2].items() if key != "_snapshot_ref"} == current[1]
    assert merged[1]["status"] == "pencil" and merged[1]["origin"] == "author"
    assert merged[1]["event"] == "填好空位" and merged[1]["techniques"] == ["信息差"]
    assert merged[3]["status"] == "pencil" and merged[3]["origin"] == "ai"


def test_merge_nodes_restores_omitted_pin_after_surviving_predecessor():
    current = [node("a", "opening"), node("b"), node("c", status="pinned"), node("d"), node("e", "ending")]
    merged = merge_nodes(
        [
            {"ref": 1, "kind": "开篇"},
            {"ref": 0, "kind": "节点"},
            {"ref": 2, "kind": "节点"},
            {"ref": 5, "kind": "结局"},
        ],
        current,
    )
    assert [item["id"] for item in merged] == ["a", None, "b", "c", "e"]
    assert merged[3]["_snapshot_ref"] == 3


def test_merge_deduplicates_refs_and_corrects_boundary_kinds():
    current = [node("a", "opening"), node("b", "ending")]
    merged = merge_nodes(
        [
            {"ref": 1, "kind": "开篇"},
            {"ref": 1, "kind": "开篇"},
            {"kind": "开篇"},
            {"kind": "结局"},
            {"ref": 2, "kind": "结局"},
        ],
        current,
    )
    assert [item["kind"] for item in merged] == ["opening", "milestone", "milestone", "ending"]
    assert [item["id"] for item in merged].count("a") == 1
    assert merge_nodes([], []) == []


@pytest.mark.parametrize("reference_pins", [True, False])
def test_pinned_boundaries_win_over_extra_ai_boundaries(reference_pins):
    current = [node("opening", "opening", status="pinned"), node("middle"), node("ending", "ending", status="pinned")]
    original = deepcopy(current)
    drafts = [{"ref": 0, "kind": "开篇", "title": "多余的新开篇"}]
    if reference_pins:
        drafts.append({"ref": 1, "kind": "节点", "title": "不能改铁钉开篇", "event": "不能覆盖"})
    drafts.append({"ref": 2, "kind": "节点", "title": "保留中间节点"})
    if reference_pins:
        drafts.append({"ref": 3, "kind": "节点", "title": "不能改铁钉结局", "event": "不能覆盖"})
    drafts.append({"ref": 0, "kind": "结局", "title": "多余的新结局"})
    merged = merge_nodes(drafts, current)
    assert current == original
    assert [item["kind"] for item in merged] == ["opening", "milestone", "milestone", "milestone", "ending"]
    assert {key: value for key, value in merged[0].items() if key != "_snapshot_ref"} == current[0]
    assert {key: value for key, value in merged[-1].items() if key != "_snapshot_ref"} == current[-1]
    assert merged[0]["_snapshot_ref"] == 1 and merged[-1]["_snapshot_ref"] == 3
    assert [item["title"] for item in merged[1:-1]] == ["多余的新开篇", "保留中间节点", "多余的新结局"]


def test_unpersisted_node_refs_follow_snapshot_not_none_ids():
    current = [node(None, "opening"), node(None), node(None, "ending")]
    merged = merge_nodes(
        [{"ref": 1, "kind": "开篇"}, {"kind": "节点"}, {"ref": 2, "kind": "节点"}, {"ref": 3, "kind": "结局"}], current
    )
    setup = {"lore": {"anchors": [{"node": 2}]}, "outline": {"volumes": [{"target_node": 3}]}}
    remapped = remap_node_refs(setup, current, merged)
    assert all(item["id"] is None for item in merged)
    assert remapped["lore"]["anchors"][0]["node"] == 3
    assert remapped["outline"]["volumes"][0]["target_node"] == 4
    assert setup["lore"]["anchors"][0]["node"] == 2


def test_lore_validates_names_nodes_and_preserves_secret_number():
    raw = {
        "characters": [{"name": "林岚"}],
        "anchors": [
            {"character": "林岚", "node": 2, "kind": "高光"},
            {"character": "路人", "node": 1},
            {"character": "林岚", "node": 99},
        ],
        "secrets": [
            {"title": "身份", "truth": "皇族", "knowers": ["林岚", "不存在", "林岚"], "node": 2},
            {"title": "往事", "truth": "逃亡", "knowers": [], "node": 99},
        ],
    }
    original = deepcopy(raw)
    lore, dropped = normalize_lore(
        raw, [node("开篇", "opening"), node("高光")], [{"seq": 7, "title": "身份", "status": "public"}]
    )
    assert raw == original
    assert dropped == {"dropped_anchors": 2, "dropped_knowers": 1}
    assert lore["anchors"] == [{"character": "林岚", "node": 2, "kind": "高光", "node_title": "高光"}]
    assert [item["seq"] for item in lore["secrets"]] == [7, 8]
    assert lore["secrets"][0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
    assert lore["secrets"][0]["status"] == "public" and lore["secrets"][1]["node"] == 0


def test_outline_normalization_never_changes_pin():
    nodes = [node("a", "opening"), node("b", status="pinned", volume=2), node("c", "ending", volume=5)]
    outline = {
        "volumes": [
            {"index": 1, "target_node": 99, "reaches_node": True},
            {"index": 3, "target_node": 2, "reaches_node": True},
            {"index": 4, "target_node": 3, "reaches_node": True},
        ],
        "foreshadowings": [{"description": "伏笔", "node": 90}],
        "expectations": [{"description": "期待"}],
    }
    before = deepcopy(nodes)
    cleaned, changed, warnings = normalize_outline(outline, nodes)
    assert nodes == before and changed[1] == before[1]
    assert changed[2]["volume"] == 4
    assert cleaned["volumes"][0]["target_node"] == 0 and not cleaned["volumes"][0]["reaches_node"]
    assert any("铁钉" in item for item in warnings) and any("不存在" in item for item in warnings)
    assert cleaned["foreshadowings"][0]["kind"] == "伏笔" and cleaned["foreshadowings"][0]["node"] == 0
    assert cleaned["expectations"][0]["kind"] == "期待" and cleaned["expectations"][0]["span"] == "长"


def test_reveals_are_filtered_against_actual_secret_codes():
    units = [
        {
            "index": 1,
            "techniques": ["表外", "信息差"],
            "reveals": [
                {"ref": "S1", "to": "读者", "how": "揭晓"},
                {"ref": "s2", "to": "林岚"},
                {"ref": "S9", "to": "众人"},
                {"ref": "F1"},
                {"ref": "前文S1"},
            ],
        }
    ]
    original = deepcopy(units)
    clean = clean_reveals(units, [{"seq": 1}, {"seq": 2}])
    assert units == original
    assert [item["ref"] for item in clean[0]["reveals"]] == ["S1", "S2"]
    assert clean[0]["techniques"] == ["信息差"]
    assert clean_reveals([{"index": 1}], []) == [{"index": 1}]


def valid_setup():
    nodes = [
        node(str(index), "opening" if index == 1 else "ending" if index == 9 else "milestone", volume=index)
        for index in range(1, 10)
    ]
    return {
        "concept": {"target_length": 9, "chapter_words": 1000, "target_volumes": 9},
        "spine": {"nodes": nodes},
        "lore": {
            "characters": [
                {"name": name, "role_type": role} for name, role in (("甲", "主角"), ("乙", "女主"), ("丙", "反派"))
            ],
            "anchors": [{"character": name, "node": 2} for name in ("甲", "乙", "丙")],
            "secrets": [{"seq": index} for index in range(1, 5)],
        },
        "outline": {
            "volumes": [
                {"index": index, "target_node": index, "reaches_node": True, "chapter_count": 10}
                for index in range(1, 10)
            ],
            "expectations": [
                {"seq": 1, "plant_volume": 1, "payoff_volume": 3},
                {"seq": 2, "plant_volume": 3, "payoff_volume": 9},
            ],
        },
        "first_volume": {"units": [{"index": 1, "foreshadow_actions": [{"ref": "E1", "action": "埋下"}]}]},
    }


def test_valid_pieces_have_no_program_warnings():
    for piece in ("nodes", "cast", "fill", "first_volume"):
        assert piece_warnings(piece, valid_setup()) == []


def test_program_warnings_cover_boundaries_gaps_empty_lore_and_schedule():
    setup = valid_setup()
    setup["spine"]["nodes"] = [
        node("a", "opening", volume=1),
        node("b", status="empty", volume=6),
        node("c", "ending", volume=3),
    ]
    warnings = piece_warnings("nodes", setup)
    assert any("6–12" in text for text in warnings)
    assert (
        any("连续" in text for text in warnings)
        and any("更早" in text for text in warnings)
        and any("留空" in text for text in warnings)
    )
    setup["lore"].update(anchors=[], secrets=[])
    assert any("已丢弃 2" in text for text in piece_warnings("cast", setup, {"dropped_anchors": 2}))
    setup["outline"] = {
        "volumes": [{"index": 1, "target_node": 3}, {"index": 2, "target_node": 2}],
        "expectations": [{"description": "倒序", "plant_volume": 5, "payoff_volume": 2}],
    }
    warnings = piece_warnings("fill", setup)
    assert all(any(keyword in text for text in warnings) for keyword in ("章数", "倒退", "少于 2", "晚于"))
    setup["first_volume"]["units"][0]["foreshadow_actions"] = [{"ref": "F1"}]
    assert "没有安排期待动作" in piece_warnings("first_volume", setup)[0]


def test_context_direction_target_and_locked():
    assert format_direction_choice(None) == ""
    text = format_direction_choice(
        {"name": "逆袭", "logline": "少年归来", "selling_points": ["成长", "悬念"], "mix": "加入群像"}
    )
    assert "方向「逆袭」：少年归来" in text and "卖点：成长；悬念" in text and "【作者的混搭要求】\n加入群像" in text
    nodes = [node("开篇", "opening"), node("飞升", status="pinned", volume=2), node("结局", "ending", volume=3)]
    text = format_target_node({"target_node": 2, "reaches_node": True}, nodes)
    assert "节点 2「飞升」［铁钉］——本卷就要写到它" in text
    assert "再下一个节点：节点 3「结局」：原事件" in text
    assert "更进一步" in format_target_node({"target_node": 2}, nodes)
    assert "没有标走向" in format_target_node({"target_node": 99}, nodes)
    state = {"mode": "puzzle", "pieces": {"concept": "confirmed", "nodes": "confirmed"}, "spine": {"nodes": nodes}}
    assert format_locked(state) == "【作者已确认（锁定）的部分】定调、关键节点\n其中铁钉节点：节点 2「飞升」"
    assert format_locked({**state, "mode": "oneshot"}) == (
        "【作者钉死的节点】节点 2「飞升」（铁钉，不能擅自改；仅本轮作者明确点名时可按要求改，改完仍是铁钉）"
    )
    assert format_locked({}) == ""
