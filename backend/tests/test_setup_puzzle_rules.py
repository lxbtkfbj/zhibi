"""第一包任务 2：开书拼图的快照规则、校验与中文上下文。"""

from copy import deepcopy

import pytest

from app.agents.context import format_direction_choice, format_locked, format_target_node
from app.agents.setup_puzzle import clean_reveals, merge_nodes, normalize_secrets, normalize_volumes, piece_checks
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


def test_merge_nodes_ref_preserves_pin_position_and_origin():
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
    assert [item["id"] for item in merged] == ["a", "b", "c", None, "d"]
    assert {key: value for key, value in merged[1].items() if key != "_snapshot_ref"} == current[1]
    assert merged[2]["status"] == "pencil" and merged[2]["origin"] == "author"
    assert merged[2]["event"] == "填好空位" and merged[2]["techniques"] == ["信息差"]
    assert merged[3]["status"] == "pencil" and merged[3]["origin"] == "ai"


def test_merge_nodes_restores_omitted_pin_at_its_snapshot_position():
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
    assert [item["id"] for item in merged] == ["a", None, "c", "b", "e"]
    assert merged[2]["_snapshot_ref"] == 3
    assert {key: value for key, value in merged[2].items() if key != "_snapshot_ref"} == current[2]


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
    assert [item["kind"] for item in merged] == ["opening", "milestone", "ending"]
    assert [item["id"] for item in merged] == [item["id"] for item in current]
    assert {key: value for key, value in merged[0].items() if key != "_snapshot_ref"} == current[0]
    assert {key: value for key, value in merged[-1].items() if key != "_snapshot_ref"} == current[-1]
    assert merged[0]["_snapshot_ref"] == 1 and merged[-1]["_snapshot_ref"] == 3
    assert [item["title"] for item in merged[1:-1]] == ["保留中间节点"]


def test_unpersisted_node_refs_follow_snapshot_not_none_ids():
    current = [node(None, "opening"), node(None), node(None, "ending")]
    merged = merge_nodes(
        [{"ref": 1, "kind": "开篇"}, {"kind": "节点"}, {"ref": 2, "kind": "节点"}, {"ref": 3, "kind": "结局"}], current
    )
    setup = {"volumes": {"anchors": [{"node": 2}], "volumes": [{"target_node": 3}]}}
    remapped = remap_node_refs(setup, current, merged)
    assert all(item["id"] is None for item in merged)
    assert remapped["volumes"]["anchors"][0]["node"] == 3
    assert remapped["volumes"]["volumes"][0]["target_node"] == 4
    assert setup["volumes"]["anchors"][0]["node"] == 2


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
    nodes = [node("开篇", "opening"), node("高光")]
    secrets, dropped = normalize_secrets(
        raw["secrets"], raw["characters"], nodes, [{"seq": 7, "title": "身份", "status": "public"}]
    )
    volumes, _, notes = normalize_volumes({"anchors": raw["anchors"]}, {"nodes": nodes}, raw["characters"], 1)
    assert raw == original
    assert dropped == 1
    assert notes == [{"question": "cast", "text": "已丢弃 2 条不合法的人物锚点。"}]
    assert volumes["anchors"] == [{"character": "林岚", "node": 2, "kind": "高光", "node_title": "高光"}]
    assert [item["seq"] for item in secrets] == [7, 8]
    assert secrets[0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
    assert secrets[0]["status"] == "public" and secrets[1]["node"] == 0


def test_volumes_normalization_never_changes_pin():
    nodes = [node("a", "opening"), node("b", status="pinned", volume=2), node("c", "ending", volume=5)]
    segment = {"nodes": nodes, "expectations": [{"node": 2, "plant_volume": 99, "payoff_volume": 99}]}
    part = {
        "volumes": [
            {"index": 4, "target_node": 3, "chapter_count": -1},
            {"index": 1, "target_node": 99},
            {"index": 3, "target_node": 2},
        ]
    }
    before = deepcopy(segment)
    cleaned, changed, notes = normalize_volumes(part, segment, [], 1)
    assert segment == before and changed["nodes"][1] == before["nodes"][1]
    assert changed["nodes"][2]["volume"] == 5
    assert [v["index"] for v in cleaned["volumes"]] == [1, 2, 3]
    assert [v["target_node"] for v in cleaned["volumes"]] == [2, 2, 2]
    assert [v["reaches_node"] for v in cleaned["volumes"]] == [False, False, True]
    assert all(v["chapter_count"] == 0 for v in cleaned["volumes"])
    assert any("铁钉" in item["text"] for item in notes)
    assert changed["expectations"][0]["plant_volume"] == changed["expectations"][0]["payoff_volume"] == 3


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
    from app.agents.setup_puzzle import normalize_segment, normalize_world
    from app.llm import demo

    concept = demo._concept("").model_dump()
    protagonist = demo._protagonist("").model_dump()
    world, _ = normalize_world(demo._world("").model_dump(), protagonist)
    segment, _ = normalize_segment(demo._segment("").model_dump(), [], world["characters"], {}, world=world)
    volumes, segment, _ = normalize_volumes(demo._segment_volumes("").model_dump(), segment, world["characters"], 1)
    return {
        "concept": concept,
        "protagonist": protagonist,
        "world": world,
        "segment": segment,
        "volumes": volumes,
        "first_volume": {
            "want": "拿到药田证据",
            "pressure": "管事追债",
            "units": [{"index": 1, "loop": "找线索拿证据", "foreshadow_actions": [{"ref": "E1", "action": "埋下"}]}],
        },
    }


def test_valid_pieces_have_no_program_warnings():
    from app.agents.setup_puzzle import PIECE_ORDER

    for piece in PIECE_ORDER:
        assert piece_checks(piece, valid_setup()) == []


def test_program_checks_cover_new_required_questions_without_remote_scope_requirements():
    setup = valid_setup()
    setup["segment"]["nodes"][1]["status"] = "empty"
    checks = piece_checks("segment", setup)
    assert any("留空" in item["text"] for item in checks)
    assert not any("6–12" in item["text"] or "全书" in item["text"] for item in checks)
    setup["volumes"] = {"volumes": [{"index": 1}], "anchors": []}
    checks = piece_checks("segment", setup)
    assert {"volumes", "cast"} <= {item["question"] for item in checks}
    assert all(any(keyword in item["text"] for item in checks) for keyword in ("章数", "想做成", "线索", "登场"))
    setup["first_volume"]["units"][0]["foreshadow_actions"] = [{"ref": "F1"}]
    assert any("没有安排期待动作" in item["text"] for item in piece_checks("first_volume", setup))


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
    state = {"mode": "puzzle", "pieces": {"concept": "confirmed", "segment": "confirmed"}, "segment": {"nodes": nodes}}
    assert format_locked(state) == "【作者已确认（锁定）的部分】定调、第一段\n其中铁钉节点：节点 2「飞升」"
    assert format_locked({**state, "mode": "oneshot"}) == (
        "【作者钉死的节点】节点 2「飞升」（铁钉，不能擅自改；仅本轮作者明确点名时可按要求改，改完仍是铁钉）"
    )
    assert format_locked({}) == ""
