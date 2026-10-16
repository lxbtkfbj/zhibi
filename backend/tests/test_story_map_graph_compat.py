"""新节点产出的 ref 合同、铁钉保护、新第一段和共用编号空间。"""

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
    old = {
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

    return {
        "idea": old["idea"],
        "concept": old["concept"],
        "protagonist": {"name": "林岚"},
        "world": {"characters": old["lore"]["characters"]},
        "segment": {
            **old["spine"],
            "secrets": old["lore"]["secrets"],
            "foreshadowings": old["outline"]["foreshadowings"],
            "expectations": old["outline"]["expectations"],
        },
        "volumes": {"volumes": old["outline"]["volumes"], "anchors": old["lore"]["anchors"], "threads": []},
        "first_volume": old["first_volume"],
        "queue": ["segment", "volumes", "first_volume"],
        "instructions": {"segment": "增加一个准备阶段，铁钉不变", "volumes": "按新主线检查"},
        "instruction_sources": {"segment": ["增加准备"], "volumes": ["增加准备"]},
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
    return {key: value for key, value in node.items() if not key.startswith("_") and key != "segment"}


async def generate(monkeypatch, state, ai_nodes):
    isolate(monkeypatch)
    draft = s.SegmentDraft(
        opening=s.OpeningPlan(
            scene="进城受阻", pressure="城门封锁", first_win="找到暗门", finger="读出旧信", hook="母亲失踪线索"
        ),
        goal="救回母亲",
        goal_link="走近亲人",
        wait=s.ExpectationDraft(description="母子团聚", plant_plan="承诺", payoff_plan="团聚"),
        reveal="身世疑云",
        secrets=[
            s.SecretDraft(
                title="身份", truth="皇族", knowers=["林岚"], reader_knows="知道", reveal_plan="当众揭晓", node=3
            )
        ],
        core_conflict="归家",
        theme="承担",
        protagonist_arc="主动守护",
        nodes=ai_nodes,
        remark="已经调整主线",
    )
    monkeypatch.setattr(book_setup.editorial, "draft_segment", AsyncMock(return_value=draft))
    deps = SimpleNamespace(
        check_cancel=AsyncMock(),
        llm=object(),
        emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
    )
    update = await book_setup.segment_node(state, SimpleNamespace(context=deps))
    return update, deps


@pytest.mark.parametrize("pinned_ending", [True, False])
async def test_spine_protects_pins_before_downstream_and_remaps_references(monkeypatch, pinned_ending):
    state = graph_state()
    if not pinned_ending:
        state["segment"]["nodes"][-1].update(status="pencil", origin="ai")
    before = deepcopy(state)
    ai_nodes = [
        draft_node("开篇", "开篇", "进城", ref=1),
        draft_node("节点", "新增准备", "寻找证据"),
        draft_node("节点", "当众救母", "AI 改成放弃母亲", ref=2, volume=2),
        draft_node("节点", "旧转折", "离城", ref=3, volume=3),
        draft_node("结局", "结局", "AI 改成独自远游", ref=4, volume=4),
    ]
    update, deps = await generate(monkeypatch, state, ai_nodes)
    nodes = update["segment"]["nodes"]
    by_id = {item["id"]: item for item in nodes if item.get("id")}
    assert content(by_id[before["segment"]["nodes"][1]["id"]]) == before["segment"]["nodes"][1]
    assert nodes[1]["id"] == before["segment"]["nodes"][1]["id"]
    if pinned_ending:
        assert content(by_id[before["segment"]["nodes"][3]["id"]]) == before["segment"]["nodes"][3]
        # 结局同样钉在原位时，AI 顺带新增会把结局后移，必须退回原拓扑。
        assert [item["id"] for item in nodes] == [item["id"] for item in before["segment"]["nodes"]]
    else:
        # 没有铁钉结局约束时仍可新增，且所有下游序号须继续引用原来的节点。
        assert any(item["title"] == "新增准备" for item in nodes)
    assert "milestones" not in update["segment"]
    # 旧序号即便移动，仍引用同一个节点，而不是插进来的新节点。
    index = {item["id"]: i for i, item in enumerate(nodes, 1) if item.get("id")}
    pinned = index[before["segment"]["nodes"][1]["id"]]
    milestone = index[before["segment"]["nodes"][2]["id"]]
    ending = index[before["segment"]["nodes"][3]["id"]]
    assert update["volumes"]["anchors"][0]["node"] == pinned
    assert update["segment"]["secrets"][0]["node"] == 3
    assert update["volumes"]["volumes"][0]["target_node"] == pinned
    assert update["segment"]["foreshadowings"][0]["node"] == milestone
    assert update["segment"]["expectations"][0]["node"] == 2
    assert update["first_volume"]["new_foreshadowings"][0]["node"] == pinned
    assert update["first_volume"]["new_expectations"][0]["node"] == ending
    assert update["queue"] == ["volumes", "first_volume"]
    assert update["instructions"] == {"volumes": "按新主线检查"}
    assert update["instruction_sources"] == {"volumes": ["增加准备"]}
    assert state == before  # 不能原地改写新第一段里的嵌套对象。
    assert deps.emit.artifact.await_args.args[2]["data"] == update["segment"]


async def test_spine_restores_omitted_pinned_node(monkeypatch):
    state = graph_state()
    before = deepcopy(state)
    ai_nodes = [draft_node("开篇", "开篇", "进城", ref=1), draft_node("节点", "旧转折", "离城", ref=3, volume=3)]
    # 模型连铁钉结局都漏报了，程序也必须补回，不能让新稿删除它。
    update, _ = await generate(monkeypatch, state, ai_nodes)
    nodes = update["segment"]["nodes"]
    assert content(nodes[1]) == before["segment"]["nodes"][1]
    assert content(nodes[-1]) == before["segment"]["nodes"][-1]
    assert nodes[update["volumes"]["anchors"][0]["node"] - 1]["id"] == before["segment"]["nodes"][1]["id"]
    assert state == before


async def test_first_segment_without_previous_checkpoint_uses_new_three_node_contract(monkeypatch):
    state = {"concept": {}, "world": {"characters": []}, "segment": {}, "queue": ["segment", "volumes"]}
    draft = [
        draft_node("开篇", "开篇", "新的开篇"),
        draft_node("节点", "段终点", "救回母亲"),
        draft_node("结局", "结局", "新的结局"),
    ]
    update, _ = await generate(monkeypatch, state, draft)
    assert [item["kind"] for item in update["segment"]["nodes"]] == ["opening", "milestone", "ending"]
    assert update["segment"]["nodes"][1]["segment"]["number"] == 1
    assert update["queue"] == ["volumes"]


async def test_first_volume_allocates_shared_ledger_numbers_and_persists_new_questions(monkeypatch):
    isolate(monkeypatch)
    state = graph_state()
    state["segment"]["expectations"][0]["seq"] = 9
    state["first_volume"]["new_expectations"][0]["seq"] = 11
    state["queue"] = ["first_volume"]
    before = deepcopy(state)
    first = s.VolumePlanDraft(
        want="找到母亲的线人",
        pressure="城门封锁",
        units=[
            s.PlotUnitDraft(
                index=1,
                title="新单元",
                chapter_count=6,
                goal="调查",
                conflict="封锁",
                climax="夺回旧信",
                outcome="新线索",
                loop="接案查旧信，母亲的踪迹更清楚",
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
    monkeypatch.setattr(book_setup.editorial, "plan_volume", AsyncMock(return_value=first))
    monkeypatch.setattr(book_setup, "first_volume_blocks", lambda _: {"chapter_count": "6"})
    deps = SimpleNamespace(
        check_cancel=AsyncMock(),
        llm=object(),
        emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
    )
    update = await book_setup.first_volume_node(state, SimpleNamespace(context=deps))
    assert update["first_volume"]["new_expectations"][0]["seq"] == 11
    assert update["first_volume"]["new_foreshadowings"][0]["seq"] == 12
    assert {a["ref"] for a in update["first_volume"]["units"][0]["foreshadow_actions"]} == {"F12", "E11"}
    assert update["first_volume"]["units"][0]["reveals"][0]["ref"] == "S1"
    assert update["first_volume"]["want"] == "找到母亲的线人"
    assert update["first_volume"]["pressure"] == "城门封锁"
    assert state == before
