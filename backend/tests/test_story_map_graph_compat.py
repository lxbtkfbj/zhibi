"""新节点产出的 ref 合同、铁钉保护、旧检查点和共用编号空间。"""

import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import prompts
from app.agents import schemas as s
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


def isolate(monkeypatch):
    monkeypatch.setattr(prompts, "_load", prompts.default_content)
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda current, _: current))
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())


def draft_node(kind, title, event, *, ref=0, volume=1):
    return s.StoryNodeDraft(
        kind=kind, title=title, event=event, ref=ref, volume=volume, prerequisite="新的前提", consequence="新的结果"
    )


def content(node):
    return {key: value for key, value in node.items() if not key.startswith("_")}


async def generate(monkeypatch, state, ai_nodes):
    isolate(monkeypatch)
    draft = s.StorySpine(
        core_conflict="归家", theme="承担", protagonist_arc="主动守护", nodes=ai_nodes, remark="已经调整主线"
    )
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
    ai_nodes = [
        draft_node("开篇", "开篇", "进城", ref=1),
        draft_node("节点", "新增准备", "寻找证据"),
        draft_node("节点", "当众救母", "AI 改成放弃母亲", ref=2, volume=2),
        draft_node("节点", "旧转折", "离城", ref=3, volume=3),
        draft_node("结局", "结局", "AI 改成独自远游", ref=4, volume=4),
    ]
    update, deps = await generate(monkeypatch, state, ai_nodes)
    nodes = update["spine"]["nodes"]
    by_id = {item["id"]: item for item in nodes if item.get("id")}
    assert content(by_id[before["spine"]["nodes"][1]["id"]]) == before["spine"]["nodes"][1]
    assert content(by_id[before["spine"]["nodes"][3]["id"]]) == before["spine"]["nodes"][3]
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
    ai_nodes = [draft_node("开篇", "开篇", "进城", ref=1), draft_node("节点", "旧转折", "离城", ref=3, volume=3)]
    # 模型连铁钉结局都漏报了，程序也必须补回，不能让新稿删除它。
    update, _ = await generate(monkeypatch, state, ai_nodes)
    nodes = update["spine"]["nodes"]
    assert content(nodes[1]) == before["spine"]["nodes"][1]
    assert content(nodes[-1]) == before["spine"]["nodes"][-1]
    assert nodes[update["lore"]["anchors"][0]["node"] - 1]["id"] == before["spine"]["nodes"][1]["id"]
    assert state == before


@pytest.mark.parametrize("previous", [{}, {"opening": "旧开篇", "milestones": [], "ending": "旧结局"}])
async def test_first_draft_and_legacy_checkpoint_accept_new_model_output(monkeypatch, previous):
    state = {"concept": {}, "lore": {"characters": []}, "spine": previous, "queue": ["spine", "threads"]}
    draft = [draft_node("开篇", "开篇", "新的开篇"), draft_node("结局", "结局", "新的结局")]
    update, _ = await generate(monkeypatch, state, draft)
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


@pytest.mark.parametrize("with_entries", [True, False])
async def test_lore_new_schema_normalizes_and_can_explicitly_clear_entries(monkeypatch, with_entries):
    isolate(monkeypatch)
    state = graph_state()
    before = deepcopy(state)
    draft = s.LoreDraft(
        world_entries=[],
        characters=[
            s.CharacterDraft(name="林岚", role_type="主角", personality="谨慎", background="寒原少年", goal="回家")
        ],
        relationships=[],
        anchors=[s.NodeAnchorDraft(character="林岚", node=2, kind="高光", note="救母")] if with_entries else [],
        secrets=[
            s.SecretDraft(
                title="身份", truth="皇族", knowers=["林岚"], reader_knows="知道", reveal_plan="当面对质", node=3
            )
        ]
        if with_entries
        else [],
        remark="改好人物",
    )
    monkeypatch.setattr(book_setup.editorial, "draft_lore", AsyncMock(return_value=draft))
    update = await book_setup.lore_node(state, runtime())
    if with_entries:
        assert update["lore"]["anchors"][0]["node"] == 2
        assert update["lore"]["secrets"][0]["seq"] == 1
        assert update["lore"]["secrets"][0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
    else:
        assert update["lore"]["anchors"] == [] and update["lore"]["secrets"] == []
    assert "secrets" not in update["lore"]["characters"][0]
    assert state == before


async def test_outline_and_first_volume_allocate_new_schema_expectations_without_collision(monkeypatch):
    isolate(monkeypatch)
    state = graph_state()
    state["outline"]["expectations"][0]["seq"] = 9
    state["first_volume"]["new_expectations"][0]["seq"] = 11
    before = deepcopy(state)
    outline = s.OutlineDraft(
        volumes=[
            s.VolumeDraft(index=1, title="新的总纲", summary="调查", goal="找到线索", chapter_count=6, target_node=2)
        ],
        foreshadowings=[s.ForeshadowingDraft(description="新增长伏笔", plant_plan="留下旧信", payoff_plan="查明来历")],
        expectations=[
            s.ExpectationDraft(description="母子团聚", plant_plan="立下承诺", payoff_plan="接回母亲", node=4)
        ],
        remark="改好总纲",
    )
    first = s.VolumePlanDraft(
        units=[
            s.PlotUnitDraft(
                index=1,
                title="新单元",
                chapter_count=6,
                goal="调查",
                conflict="封锁",
                climax="夺回旧信",
                outcome="新线索",
                key_events=["进城", "对质"],
                reveals=[s.RevealStep(ref="S1", to="林岚", how="读信")],
            )
        ],
        new_foreshadowings=[
            s.NewForeshadowing(
                description="新增短伏笔", plant_plan="看见痕迹", payoff_plan="证实推断", plant_unit=1, payoff_unit=1
            )
        ],
        new_expectations=[
            s.NewExpectation(
                description="找到家人", plant_plan="立下承诺", payoff_plan="找到全家", plant_unit=1, payoff_unit=1
            )
        ],
        remark="改好第一卷",
    )
    monkeypatch.setattr(book_setup.editorial, "draft_outline", AsyncMock(return_value=outline))
    monkeypatch.setattr(book_setup.editorial, "plan_volume", AsyncMock(return_value=first))
    monkeypatch.setattr(book_setup, "first_volume_blocks", lambda _: {"chapter_count": "6"})
    outline_update = await book_setup.outline_node(state, runtime())
    first_update = await book_setup.first_volume_node({**state, **outline_update}, runtime())
    assert outline_update["outline"]["expectations"][0]["seq"] == 9
    assert first_update["first_volume"]["new_expectations"][0]["seq"] == 11
    assert outline_update["outline"]["foreshadowings"][0]["seq"] == 12
    assert first_update["first_volume"]["new_foreshadowings"][0]["seq"] == 13
    assert {a["ref"] for a in first_update["first_volume"]["units"][0]["foreshadow_actions"]} == {"F13", "E11"}
    assert first_update["first_volume"]["units"][0]["reveals"][0]["ref"] == "S1"
    assert state == before
