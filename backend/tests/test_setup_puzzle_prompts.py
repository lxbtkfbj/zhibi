"""任务 2 的 schema 原文、提示词变量、演示产出与覆盖提醒。"""

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import Field

from app import prompts
from app.agents import editorial, glossary
from app.agents import schemas as s
from app.agents.context import format_concept, format_ledger, format_locked, format_secrets, format_spine
from app.agents.planning import attach_new_foreshadowings
from app.agents.setup_puzzle import merge_nodes, normalize_lore, normalize_outline, piece_warnings
from app.llm import demo
from app.main import app
from app.models import PromptOverride
from app.prompts import default_content
from app.prompts.catalog import variables
from app.services.setup_store import assign_seqs


@pytest.fixture
def default_prompts(monkeypatch):
    monkeypatch.setattr(prompts, "_load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)


def test_task_schema_descriptions_match_verbatim():
    task = Path(__file__).resolve().parents[2] / "docs/codex任务/第一包/2-开书拼图流程.md"
    block = re.search(r"```python\n(.*?)\n```", task.read_text(encoding="utf-8"), re.S).group(1)
    namespace = {
        "Lenient": s.Lenient,
        "Field": Field,
        "Any": Any,
        "Literal": Literal,
        "remark_field": s.remark_field,
        "SetupTarget": s.SetupTarget,
    }
    exec(compile(block, str(task), "exec"), namespace)
    # 任务 6 明确替换的描述由独立原文回归覆盖，任务 2 的其余描述仍逐字保持。
    superseded = {
        "BookDirection": {"name", "titles", "golden_finger", "stage_ladder"},
        "BookDirections": {"reference", "directions", "remark"},
    }
    for item in ast.parse(block).body:
        if isinstance(item, ast.ClassDef):
            actual, expected = getattr(s, item.name), namespace[item.name]
            replaced = superseded.get(item.name, set())
            assert {name: field.description for name, field in actual.model_fields.items() if name not in replaced} == {
                name: field.description for name, field in expected.model_fields.items() if name not in replaced
            }, item.name
    assert namespace["TECHNIQUES_DESC"] == s.TECHNIQUES_DESC
    assert namespace["EDITOR_NOTE_DESC"] == s.EDITOR_NOTE_DESC
    assert "secrets" not in s.CharacterDraft.model_fields
    assert "thread_beats" not in s.VolumeDraft.model_fields
    assert not hasattr(s, "Milestone")
    assert s.SETUP_PARTS == ("concept", "spine", "lore", "outline", "threads", "first_volume")
    expected = {
        ("BookConcept", "stage_ladder"): s.STAGE_LADDER_DESC,
        ("BookConcept", "target_reader"): "目标读者：男频还是女频、爱看什么、最讨厌什么，一句话",
        ("LoreDraft", "world_entries"): "世界观条目，6-12 条，必须包含力量体系（境界从低到高写清名称）和核心规则",
        ("LoreDraft", "characters"): "主要人物，6-12 人，至少包含主角和一个主要反派",
        ("ForeshadowStep", "ref"): "台账编号：伏笔如 F3，期待如 E2（必须是台账里已有的编号）",
        ("ForeshadowStep", "action"): "埋下 / 提醒（让读者再想起来）/ 回收；对期待来说，埋下就是立下，回收就是兑现",
        (
            "RevisionTriage",
            "spine_instructions",
        ): "对关键节点的修改要求：写明改第几个节点、怎么改，不能改铁钉节点；不需要改则留空",
    }
    for (model, name), description in expected.items():
        assert getattr(s, model).model_fields[name].description == description


VARIABLES = {
    "setup_directions": "idea style requirements previous glossary",
    "setup_concept": "idea chosen_direction requirements style revision",
    "setup_spine": "concept playbook requirements glossary revision",
    "setup_node_slot": "concept spine slot requirements glossary",
    "setup_lore": "concept spine requirements revision",
    "setup_outline": "concept lore spine playbook requirements glossary revision chapter_hint",
    "setup_threads": "concept lore spine outline playbook requirements revision",
    "setup_critique": "idea requirements playbook locked concept spine lore outline threads first_volume",
    "setup_triage": "concept spine lore outline threads first_volume locked requirements feedback",
    "setup_notes": "done todo locked requirements notes",
}


@pytest.mark.parametrize("name,expected", VARIABLES.items())
def test_template_variables_and_labels(name, expected, default_prompts):
    assert {item["name"] for item in variables(name)} == set(expected.split())
    assert all(item["label"] for item in variables(name))
    assert "{{" not in prompts.render(name, **dict.fromkeys(expected.split(), "测试"))


async def test_all_editorial_calls_render_new_templates(default_prompts):
    llm = SimpleNamespace(structured=AsyncMock(return_value=object()))
    await editorial.draft_directions(llm, "作者点子", "文风", "要求")
    await editorial.draft_node_slot(llm, {}, {}, "节点 2，补成 1 个节点", "要求")
    await editorial.draft_concept(llm, "点子", "文风", "要求", {}, "", chosen_direction="已选方向")
    await editorial.draft_spine(llm, {}, "要求", {}, "", playbook="打法", glossary="术语")
    await editorial.draft_lore(llm, {}, {}, "要求", {}, "")
    await editorial.draft_outline(llm, {}, {}, {}, "要求", {}, "")
    await editorial.draft_threads(llm, {}, {}, {}, {}, "要求", {}, "")
    await editorial.critique_setup(llm, "点子", "要求", {"concept": {"title": "书名"}}, locked="锁定概念")
    assert "（还没做）" in llm.structured.await_args.args[3]
    await editorial.triage_feedback(llm, {}, "要求", "意见", locked="锁定概念")
    await editorial.absorb_notes(llm, {"concept": {}}, ["spine"], "要求", ["插话"], locked="锁定概念")
    plan_blocks = {item["name"]: "内容" for item in variables("plan_volume") if item["name"] != "revision"}
    for purpose in ("开书·第一卷卷纲", "写作·第2卷"):
        await editorial.plan_volume(llm, plan_blocks, {}, "", purpose=purpose)
    assert llm.structured.await_count == 12
    assert all("{{" not in call.args[3] for call in llm.structured.await_args_list)


@pytest.mark.parametrize(
    "piece,note,target",
    [("concept", "把概念改成轻松喜剧", "concept"), ("cast", "把主角名字改成林安", "lore")],
)
def test_demo_notes_request_unlock_for_inline_locked_blocks(piece, note, target):
    locked = format_locked({"mode": "puzzle", "pieces": {piece: "confirmed"}})
    result = demo._absorb(f"{locked}\n\n【作者刚才的插话】\n- {note}\n\n请按要求安排。")
    assert result.instructions() == {}
    assert [item.target for item in result.unlock_requests] == [target]
    assert note in result.unlock_requests[0].reason


async def test_demo_new_outputs_and_partial_review(default_prompts):
    directions = await demo.respond(s.BookDirections, "", "作者点子")
    assert len(directions.directions) == 3
    assert len({d.protagonist for d in directions.directions}) == 3
    assert len({d.golden_finger for d in directions.directions}) == 3
    assert all(set(d.techniques) <= {name for name, _ in glossary.terms()} for d in directions.directions)
    for slot, count in [("替换节点 4，给出 3 个候选。", 3), ("节点 4，补成 1 个节点。", 1)]:
        result = await demo.respond(s.NodeCandidates, "", "【要补的位置】\n" + slot)
        assert len(result.nodes) == count and all(node.ref == 0 for node in result.nodes)
    review = await demo.respond(s.SetupCritique, "", "【第一卷卷纲】\n（还没做）\n\n要求：不要审没做的部分")
    assert review.verdict == "pass" and not review.issues
    assert demo._concept("这本书打算写多长？——约 30 万字").target_length == 30


def test_demo_normal_pieces_have_no_program_warnings(default_prompts):
    concept = demo._concept("").model_dump(exclude={"remark", "decisions"})
    spine = demo._spine().model_dump(exclude={"remark", "decisions"})
    spine["nodes"] = merge_nodes(spine["nodes"], [])
    assert len(spine["nodes"]) == 9
    lore, dropped = normalize_lore(demo._lore().model_dump(exclude={"remark", "decisions"}), spine["nodes"])
    outline, nodes, warnings = normalize_outline(
        demo._outline().model_dump(exclude={"remark", "decisions"}), spine["nodes"]
    )
    assert not warnings
    spine["nodes"] = nodes
    ledger = assign_seqs(
        [
            *({**f, "kind": "伏笔"} for f in outline["foreshadowings"]),
            *({**f, "kind": "期待"} for f in outline["expectations"]),
        ],
        [],
    )
    outline["foreshadowings"] = [f for f in ledger if f["kind"] == "伏笔"]
    outline["expectations"] = [f for f in ledger if f["kind"] == "期待"]
    plan = demo._volume_plan(format_ledger(ledger) + "\n" + format_secrets(lore["secrets"]))
    fresh = assign_seqs(
        [
            *({**f.model_dump(), "kind": "伏笔"} for f in plan.new_foreshadowings),
            *({**f.model_dump(), "kind": "期待"} for f in plan.new_expectations),
        ],
        ledger,
    )
    units, fresh = attach_new_foreshadowings([unit.model_dump() for unit in plan.units], fresh, 1)
    setup = {
        "concept": concept,
        "spine": spine,
        "lore": lore,
        "outline": outline,
        "first_volume": {
            "units": units,
            "new_foreshadowings": [f for f in fresh if f["kind"] == "伏笔"],
            "new_expectations": [f for f in fresh if f["kind"] == "期待"],
        },
    }
    for piece in ("nodes", "cast", "fill", "first_volume"):
        assert piece_warnings(piece, setup, dropped=dropped) == [], piece
    assert any(unit["reveals"] for unit in units)
    assert len({f["seq"] for f in [*ledger, *fresh]}) == len(ledger) + len(fresh)
    current = format_spine(spine)
    revised = demo._spine("【当前主线骨架】\n" + current)
    assert [node.ref for node in revised.nodes] == list(range(1, 10))
    bad = demo._spine("测试提醒").model_dump(exclude={"remark", "decisions"})
    bad["nodes"] = merge_nodes(bad["nodes"], [])
    assert piece_warnings("nodes", {"concept": concept, "spine": bad})
    assert format_concept(concept)


async def test_prompt_metadata_marks_old_overrides_and_preserves_rendering(sessionmaker):
    old_spine = "旧主线 {{concept}}\n{{lore}}\n{{requirements}}\n{{revision}}"
    old_outline = "旧总纲 {{concept}}\n{{threads}}"
    async with sessionmaker() as session:
        session.add_all(
            [
                PromptOverride(name="setup_spine", content=old_spine),
                PromptOverride(name="setup_outline", content=old_outline),
            ]
        )
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = (await client.get("/api/prompts")).json()
        spine = next(item for item in listed if item["name"] == "setup_spine")
        assert spine["default_changed"]
        assert {item["name"] for item in spine["new_variables"]} == {"playbook", "glossary"}
        assert (await client.get("/api/prompts/setup_spine")).json()["content"] == old_spine
        llm = SimpleNamespace(structured=AsyncMock(return_value=None))
        await editorial.draft_spine(
            llm,
            {},
            "作者要求",
            {},
            "",
            playbook="打法",
            glossary="术语",
            legacy_lore={"characters": [{"name": "旧人物"}]},
        )
        assert "旧人物" in llm.structured.await_args.args[3]
        await editorial.draft_outline(llm, {}, {}, {}, "", {}, "", legacy_threads={"threads": [{"name": "旧线索"}]})
        assert "旧线索" in llm.structured.await_args.args[3]
        await client.delete("/api/prompts/setup_spine")
        restored = (await client.get("/api/prompts/setup_spine")).json()
        assert not restored["default_changed"] and restored["new_variables"] == []
