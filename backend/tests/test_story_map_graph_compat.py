"""旧主线产出进入下游之前保护铁钉，并保持未重做块的节点引用。"""

import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.graphs import book_setup


def node(kind, title, event, *, status="pencil", volume=None):
    return {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "title": title,
        "event": event,
        "prerequisite": "作者保留的前提",
        "consequence": "作者保留的结果",
        "volume": volume,
        "status": status,
        "origin": "author" if status == "pinned" else "ai",
        "editor_note": "作者保留的批注",
        "techniques": ["欲扬先抑"],
    }


def graph_state():
    nodes = [
        node("opening", "开篇", "进城", volume=1),
        node("milestone", "当众救母", "先救母亲再谈胜负", status="pinned", volume=2),
        node("milestone", "旧转折", "离城", volume=3),
        node("ending", "结局", "母子回乡", status="pinned"),
    ]
    return {
        "idea": "寻找母亲的少年",
        "concept": {"title": "归途"},
        "spine": {"core_conflict": "归家", "nodes": nodes},
        "lore": {
            "characters": [{"name": "林岚"}],
            "anchors": [{"character": "林岚", "node": 2, "kind": "高光", "note": "救母"}],
            "secrets": [{"seq": 1, "title": "身份", "truth": "皇族", "node": 3}],
        },
        "outline": {
            "volumes": [{"index": 1, "title": "入城", "target_node": 2}],
            "foreshadowings": [{"seq": 1, "description": "信物", "node": 3}],
            "expectations": [{"seq": 2, "description": "母子团聚", "node": 4}],
        },
        "first_volume": {
            "units": [{"index": 1, "title": "相遇"}],
            "new_foreshadowings": [{"seq": 3, "description": "旧信", "node": 2}],
            "new_expectations": [{"seq": 4, "description": "找到家人", "node": 4}],
        },
        "queue": ["spine", "threads", "outline", "first_volume"],
        "instructions": {"spine": "增加一个准备阶段，铁钉不变", "threads": "按新主线检查"},
        "instruction_sources": {"spine": ["增加准备"], "threads": ["增加准备"]},
        "instruction_fallbacks": {},
        "live_requirements": [],
    }


async def generate(monkeypatch, state, legacy):
    draft = SimpleNamespace(remark="已经调整主线", model_dump=lambda **_: deepcopy(legacy))
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda current, _: current))
    monkeypatch.setattr(book_setup.editorial, "draft_spine", AsyncMock(return_value=draft))
    deps = SimpleNamespace(
        check_cancel=AsyncMock(),
        llm=object(),
        emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
    )
    update = await book_setup.spine_node(state, SimpleNamespace(context=deps))
    return update, deps


async def test_spine_protects_pins_before_downstream_and_remaps_references(monkeypatch):
    state = graph_state()
    before = deepcopy(state)
    legacy = {
        "core_conflict": "归家",
        "opening": "进城",
        "ending": "AI 改成独自远游",
        "milestones": [
            {"index": 1, "title": "新增准备", "event": "寻找证据", "change": "拿到地图", "volume": 1},
            {"index": 2, "title": "当众救母", "event": "AI 改成放弃母亲", "change": "母亲身亡", "volume": 2},
            {"index": 3, "title": "旧转折", "event": "离城", "change": "去上界", "volume": 3},
        ],
    }
    update, deps = await generate(monkeypatch, state, legacy)
    nodes = update["spine"]["nodes"]
    by_id = {item["id"]: item for item in nodes if item.get("id")}
    assert by_id[before["spine"]["nodes"][1]["id"]] == before["spine"]["nodes"][1]
    assert by_id[before["spine"]["nodes"][3]["id"]] == before["spine"]["nodes"][3]
    assert any(item["title"] == "新增准备" for item in nodes)
    assert "milestones" not in update["spine"]
    # 旧序号即便移动，仍引用同一个节点，而不是插进来的新节点。
    index = {item["id"]: i for i, item in enumerate(nodes, 1) if item.get("id")}
    pinned = index[before["spine"]["nodes"][1]["id"]]
    milestone = index[before["spine"]["nodes"][2]["id"]]
    ending = index[before["spine"]["nodes"][3]["id"]]
    assert update["lore"]["anchors"][0]["node"] == pinned
    assert update["lore"]["secrets"][0]["node"] == milestone
    assert update["outline"]["volumes"][0]["target_node"] == pinned
    assert update["outline"]["foreshadowings"][0]["node"] == milestone
    assert update["outline"]["expectations"][0]["node"] == ending
    assert update["first_volume"]["new_foreshadowings"][0]["node"] == pinned
    assert update["first_volume"]["new_expectations"][0]["node"] == ending
    assert update["queue"] == ["threads", "outline", "first_volume"]
    assert update["instructions"] == {"threads": "按新主线检查"}
    assert update["instruction_sources"] == {"threads": ["增加准备"]}
    assert state == before  # 不能原地改写旧检查点里的嵌套对象。
    assert deps.emit.artifact.await_args.args[2]["data"] == update["spine"]


async def test_spine_restores_omitted_pinned_node(monkeypatch):
    state = graph_state()
    before = deepcopy(state)
    legacy = {
        "opening": "进城",
        "ending": "AI 修改结局",
        "milestones": [{"index": 1, "title": "旧转折", "event": "离城", "change": "去上界", "volume": 3}],
    }
    update, _ = await generate(monkeypatch, state, legacy)
    nodes = update["spine"]["nodes"]
    assert nodes[1] == before["spine"]["nodes"][1]
    assert nodes[-1] == before["spine"]["nodes"][-1]
    assert nodes[update["lore"]["anchors"][0]["node"] - 1]["id"] == before["spine"]["nodes"][1]["id"]
    assert state == before


@pytest.mark.parametrize("previous", [{}, {"opening": "旧开篇", "milestones": [], "ending": "旧结局"}])
async def test_first_draft_and_legacy_checkpoint_still_accept_old_schema(monkeypatch, previous):
    state = {"concept": {}, "lore": {"characters": []}, "spine": previous, "queue": ["spine", "threads"]}
    legacy = {"opening": "新的开篇", "milestones": [], "ending": "新的结局"}
    update, _ = await generate(monkeypatch, state, legacy)
    assert [item["kind"] for item in update["spine"]["nodes"]] == ["opening", "ending"]
    assert [item["event"] for item in update["spine"]["nodes"]] == ["新的开篇", "新的结局"]
    assert update["queue"] == ["threads"]


def runtime():
    return SimpleNamespace(
        context=SimpleNamespace(
            check_cancel=AsyncMock(),
            llm=object(),
            emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
        )
    )


@pytest.mark.parametrize("keep_fields", [True, False])
async def test_lore_legacy_output_carries_only_existing_new_fields(monkeypatch, keep_fields):
    state = graph_state()
    if not keep_fields:
        for key in ("anchors", "secrets"):
            state["lore"].pop(key)
    before = deepcopy(state)
    draft = {"world_entries": [], "characters": [{"name": "林岚", "secrets": ["旧schema新秘密"]}], "relationships": []}
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda current, _: current))
    monkeypatch.setattr(
        book_setup.editorial,
        "draft_lore",
        AsyncMock(return_value=SimpleNamespace(remark="改好人物", model_dump=lambda **_: deepcopy(draft))),
    )
    update = await book_setup.lore_node(state, runtime())
    for key in ("anchors", "secrets"):
        if keep_fields:
            assert update["lore"][key] == before["lore"][key]
            assert update["lore"][key] is not state["lore"][key]
        else:
            assert key not in update["lore"]  # 缺失不是显式清空，交由存储兼容层判断。
    assert update["lore"]["characters"] == draft["characters"]
    assert state == before


@pytest.mark.parametrize("keep_expectations", [True, False])
async def test_outline_and_first_volume_carry_expectations_without_number_collision(monkeypatch, keep_expectations):
    state = graph_state()
    if keep_expectations:
        state["outline"]["expectations"][0]["seq"] = 9
        state["first_volume"]["new_expectations"][0]["seq"] = 11
    else:
        state["outline"].pop("expectations")
        state["first_volume"].pop("new_expectations")
    before = deepcopy(state)
    outline = {
        "volumes": [{"index": 1, "title": "新的总纲", "chapter_count": 6}],
        "foreshadowings": [{"description": "新增长伏笔"}],
    }
    first = {
        "units": [{"index": 1, "title": "新单元", "chapter_count": 6}],
        "new_foreshadowings": [{"description": "新增短伏笔", "plant_unit": 1, "payoff_unit": 1}],
    }
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda current, _: current))
    monkeypatch.setattr(
        book_setup.editorial,
        "draft_outline",
        AsyncMock(return_value=SimpleNamespace(remark="改好总纲", model_dump=lambda **_: deepcopy(outline))),
    )
    monkeypatch.setattr(
        book_setup.editorial,
        "plan_volume",
        AsyncMock(return_value=SimpleNamespace(remark="改好第一卷", model_dump=lambda **_: deepcopy(first))),
    )
    monkeypatch.setattr(book_setup, "first_volume_blocks", lambda _: {"chapter_count": "6"})
    outline_update = await book_setup.outline_node(state, runtime())
    next_state = {**state, **outline_update}
    first_update = await book_setup.first_volume_node(next_state, runtime())
    if keep_expectations:
        assert outline_update["outline"]["expectations"] == before["outline"]["expectations"]
        assert first_update["first_volume"]["new_expectations"] == before["first_volume"]["new_expectations"]
        assert outline_update["outline"]["foreshadowings"][0]["seq"] == 12
        assert first_update["first_volume"]["new_foreshadowings"][0]["seq"] == 13
        action = first_update["first_volume"]["units"][0]["foreshadow_actions"][0]
        assert action["ref"] == "F13"
        assert outline_update["outline"]["expectations"] is not state["outline"]["expectations"]
        assert first_update["first_volume"]["new_expectations"] is not state["first_volume"]["new_expectations"]
    else:
        assert "expectations" not in outline_update["outline"]
        assert "new_expectations" not in first_update["first_volume"]
    assert state == before
