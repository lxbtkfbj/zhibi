"""第二包任务 2：逐字 schema、模板迁入、演示检查与作者覆盖保护。"""

import ast
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app import prompts
from app.agents import editorial, glossary
from app.agents import schemas as s
from app.agents.context import format_concept, format_ledger, format_locked, format_secrets, format_segment_part
from app.agents.planning import attach_new_foreshadowings
from app.agents.setup_puzzle import normalize_segment, normalize_volumes, normalize_world, piece_checks
from app.llm import demo
from app.main import app
from app.models import PromptOverride
from app.prompts import default_content
from app.prompts.catalog import BY_NAME, variables
from app.services.setup_store import assign_seqs

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def default_prompts(monkeypatch):
    monkeypatch.setattr(prompts, "_load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)


def test_task_schema_descriptions_and_order_match_verbatim():
    task = ROOT / "docs/codex任务/第二包/2-开书新五步.md"
    block = re.search(r"```python\n(.*?)\n```", task.read_text(encoding="utf-8"), re.S).group(1)
    namespace = vars(s).copy()
    exec(compile(block, str(task), "exec"), namespace)
    for item in ast.parse(block).body:
        if not isinstance(item, ast.ClassDef):
            continue
        actual, expected = getattr(s, item.name), namespace[item.name]
        names = list(expected.model_fields)
        assert [name for name in actual.model_fields if name in names] == names, item.name
        for name, field in expected.model_fields.items():
            assert actual.model_fields[name].description == field.description, (item.name, name)
    # 注释形式的新字段和修改描述也必须逐字保持。
    section = ""
    class_alias = {"方向卡": "BookDirection"}
    for line in block.splitlines():
        if "方向卡：" in line:
            section = class_alias["方向卡"]
        match = re.match(r"# (\w+)(?:：|\.)", line)
        if match:
            section = match.group(1)
        field = re.search(r'#\s+(\w+): .*?description="([^"]+)"', line)
        if field:
            name, description = field.groups()
            assert getattr(s, section).model_fields[name].description == description
        changed = re.search(r'#\s+(\w+): "([^"]+)"', line)
        if changed:
            name, description = changed.groups()
            assert getattr(s, section).model_fields[name].description == description
    assert (
        s.StoryNodeDraft.model_fields["event"].description
        == "发生什么：这件大事本身，具体到人和场面，50-120 字；远景节点和结局只写方向，一两句即可"
    )
    assert s.ThreadDraft.model_fields["summary"].description == "这条线讲什么、大概往哪收；远处写到再定，50-120 字"
    for model, after, added in (
        (s.BookDirection, "protagonist", "drive"),
        (s.BookDirection, "golden_finger", "core_loop"),
        (s.CharacterDraft, "goal", "want"),
        (s.VolumeDraft, "summary", "want"),
        (s.PlotUnitDraft, "outcome", "loop"),
    ):
        names = list(model.model_fields)
        assert names[names.index(after) + 1] == added
    names = list(s.VolumePlanDraft.model_fields)
    assert names[names.index("units") - 2 : names.index("units")] == ["want", "pressure"]
    assert s.SETUP_PARTS == ("concept", "protagonist", "world", "segment", "volumes", "first_volume")
    assert "protagonist_hook" not in s.BookConcept.model_fields
    assert all(not hasattr(s, name) for name in ("StorySpine", "LoreDraft", "OutlineDraft", "ThreadsDraft"))
    assert (
        s.BookConcept.model_validate({**demo._concept("").model_dump(), "target_length": 2000000}).target_length == 200
    )


VARIABLES = {
    "setup_directions": "idea style requirements previous glossary",
    "setup_concept": "idea chosen_direction requirements style revision",
    "setup_protagonist": "idea concept chosen_direction requirements revision",
    "setup_world": "concept protagonist requirements revision",
    "setup_segment": "concept protagonist world playbook requirements glossary revision",
    "split_segment": "concept protagonist world segment threads playbook requirements glossary volume_hint revision",
    "setup_node_slot": "concept spine slot requirements glossary",
    "setup_critique": "idea requirements playbook locked focus concept protagonist world segment volumes first_volume",
    "setup_triage": "concept protagonist world segment volumes first_volume locked requirements feedback",
    "setup_notes": "done todo locked requirements notes",
}


@pytest.mark.parametrize("name,expected", VARIABLES.items())
def test_template_variables_and_labels(name, expected, default_prompts):
    assert {item["name"] for item in variables(name)} == set(expected.split())
    assert all(item["label"] for item in variables(name))
    assert "{{" not in prompts.render(name, **dict.fromkeys(expected.split(), "测试"))


def test_moved_prompts_unchanged_retired_hidden_and_task4_now_moved():
    evidence = json.loads((ROOT / "docs/第二包验收/任务2-提示词原文校验.json").read_text(encoding="utf-8"))
    assert len(evidence) == 14
    for record in evidence:
        assert not (ROOT / record["source"]).exists()
        assert (
            hashlib.sha256((ROOT / record["target"]).read_bytes()).hexdigest()
            == record["source_sha256"]
            == record["target_sha256"]
        )
    for name in ("setup_spine", "setup_lore", "setup_outline", "setup_threads"):
        assert name not in BY_NAME
        assert not (ROOT / f"backend/app/prompts/{name}.md").exists()
    # 第二包任务4已原文迁入剩余六份；其逐字合同在test_next_segment_prompts_demo单独校验。
    assert not list((ROOT / "docs/codex任务/第二包/提示词").glob("*.md"))


async def test_all_editorial_calls_render_new_templates(default_prompts):
    llm = SimpleNamespace(structured=AsyncMock(return_value=object()))
    await editorial.draft_directions(llm, "作者点子", "文风", "要求")
    await editorial.draft_node_slot(llm, {}, {}, "节点 2，补成 1 个节点", "要求")
    await editorial.draft_concept(llm, "点子", "文风", "要求", {}, "", chosen_direction="已选方向")
    await editorial.draft_protagonist(llm, "点子", {}, "要求", {}, "")
    await editorial.draft_world(llm, {}, {}, "要求", {}, "")
    await editorial.draft_segment(llm, {}, {}, {}, "要求", {}, "", playbook="打法", glossary="术语")
    await editorial.split_segment(
        llm, {}, {}, {}, {}, "要求", {}, "", playbook="打法", glossary="术语", volume_hint="分卷提示"
    )
    await editorial.critique_setup(
        llm, "点子", "要求", {"concept": {"title": "书名"}}, locked="锁定概念", focus="【这次审什么】只审主角卡"
    )
    assert "（还没做）" in llm.structured.await_args.args[3]
    assert "【这次审什么】只审主角卡" in llm.structured.await_args.args[3]
    await editorial.triage_feedback(llm, {}, "要求", "意见", locked="锁定概念")
    await editorial.absorb_notes(llm, {"concept": {}}, ["protagonist"], "要求", ["插话"], locked="锁定概念")
    plan_blocks = {item["name"]: "内容" for item in variables("plan_volume") if item["name"] != "revision"}
    for purpose in ("开书·第一卷卷纲", "写作·第2卷"):
        await editorial.plan_volume(llm, plan_blocks, {}, "", purpose=purpose)
    assert llm.structured.await_count == 12
    assert all("{{" not in call.args[3] for call in llm.structured.await_args_list)


@pytest.mark.parametrize("piece,note", [("concept", "把概念改成轻松喜剧"), ("protagonist", "把主角名字改成林安")])
def test_demo_notes_request_unlock_for_inline_locked_blocks(piece, note):
    locked = format_locked({"mode": "puzzle", "pieces": {piece: "confirmed"}})
    result = demo._absorb(f"{locked}\n\n【作者刚才的插话】\n- {note}\n\n请按要求安排。")
    assert result.instructions() == {}
    assert [item.target for item in result.unlock_requests] == [piece]
    assert note in result.unlock_requests[0].reason


async def test_demo_new_outputs_and_partial_review(default_prompts):
    directions = await demo.respond(s.BookDirections, "", "作者点子")
    assert len(directions.directions) == 3
    assert len({d.protagonist for d in directions.directions}) == 3
    assert len({d.golden_finger for d in directions.directions}) == 3
    assert all(d.drive and d.core_loop for d in directions.directions)
    assert all(set(d.techniques) <= {name for name, _ in glossary.terms()} for d in directions.directions)
    for slot, count in [("替换节点 4，给出 3 个候选。", 3), ("节点 4，补成 1 个节点。", 1)]:
        result = await demo.respond(s.NodeCandidates, "", "【要补的位置】\n" + slot)
        assert len(result.nodes) == count and all(node.ref == 0 for node in result.nodes)
    review = await demo.respond(s.SetupCritique, "", "【这次审什么】只审「主角卡」\n【第一卷卷纲】\n（还没做）")
    assert review.verdict == "pass" and not review.issues
    assert demo._concept("这本书打算写多长？——约 30 万字").target_length == 30


def demo_setup(marker=""):
    concept = demo._concept(marker).model_dump(exclude={"remark", "decisions"})
    protagonist = demo._protagonist(marker).model_dump(exclude={"remark", "decisions"})
    world, _ = normalize_world(demo._world(marker).model_dump(), protagonist)
    segment, _ = normalize_segment(demo._segment(marker).model_dump(), [], world["characters"], {}, world=world)
    volumes, segment, _ = normalize_volumes(demo._segment_volumes(marker).model_dump(), segment, world["characters"], 1)
    ledger = segment["expectations"]
    plan = demo._volume_plan(format_ledger(ledger) + "\n" + format_secrets(segment["secrets"]) + marker)
    fresh = assign_seqs(
        [
            *({**f.model_dump(), "kind": "伏笔"} for f in plan.new_foreshadowings),
            *({**f.model_dump(), "kind": "期待"} for f in plan.new_expectations),
        ],
        ledger,
    )
    units, fresh = attach_new_foreshadowings([unit.model_dump() for unit in plan.units], fresh, 1)
    return {
        "concept": concept,
        "protagonist": protagonist,
        "world": world,
        "segment": segment,
        "volumes": volumes,
        "first_volume": {
            "want": plan.want,
            "pressure": plan.pressure,
            "units": units,
            "new_foreshadowings": [f for f in fresh if f["kind"] == "伏笔"],
            "new_expectations": [f for f in fresh if f["kind"] == "期待"],
        },
    }


def test_demo_normal_pieces_have_no_program_warnings(default_prompts):
    setup = demo_setup()
    for piece in ("concept", "protagonist", "world", "segment", "first_volume"):
        assert piece_checks(piece, setup) == [], piece
        assert piece_checks(piece, demo_setup("测试提醒")), piece
    assert len(setup["segment"]["nodes"]) == 3
    assert [v["chapter_count"] for v in setup["volumes"]["volumes"]] == [31, 30]
    assert any(unit["reveals"] for unit in setup["first_volume"]["units"])
    all_ledger = [
        *setup["segment"]["expectations"],
        *setup["first_volume"]["new_foreshadowings"],
        *setup["first_volume"]["new_expectations"],
    ]
    assert len({f["seq"] for f in all_ledger}) == len(all_ledger)
    current = format_segment_part(setup["segment"], setup["world"])
    revised = demo._segment("【当前第一段的走向】\n" + current)
    assert [node.ref for node in revised.nodes] == [1, 2, 3]
    assert "开篇：" in current and "第 3 章结尾的钩子" in current
    assert len(demo._segment("远景：踏上北境查清旧案").nodes) == 4
    assert "主角钩子" not in format_concept(setup["concept"])
    assert "主角钩子：旧钩子" in format_concept({"protagonist_hook": "旧钩子"})


async def test_prompt_metadata_marks_old_overrides_and_preserves_rendering(sessionmaker):
    old_plan = "作者的旧卷纲 {{concept}}\n{{volume}}\n{{requirements}}"
    old_spine = "作者的旧主线 {{concept}}\n{{lore}}"
    async with sessionmaker() as session:
        session.add_all(
            [
                PromptOverride(name="plan_volume", content=old_plan),
                PromptOverride(name="setup_spine", content=old_spine),
            ]
        )
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        listed = (await client.get("/api/prompts")).json()
        assert not any(item["name"] == "setup_spine" for item in listed)
        plan = next(item for item in listed if item["name"] == "plan_volume")
        assert plan["default_changed"]
        assert {"segment", "protagonist", "opening"} <= {item["name"] for item in plan["new_variables"]}
        assert (await client.get("/api/prompts/plan_volume")).json()["content"] == old_plan
        llm = SimpleNamespace(structured=AsyncMock(return_value=None))
        await editorial.plan_volume(
            llm, {"concept": "定调", "volume": "卷卡", "requirements": "要求"}, {}, "", purpose="演示"
        )
        assert llm.structured.await_args.args[3] == "作者的旧卷纲 定调\n卷卡\n要求"
        await client.delete("/api/prompts/plan_volume")
        restored = (await client.get("/api/prompts/plan_volume")).json()
        assert not restored["default_changed"] and restored["new_variables"] == []
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(PromptOverride).where(PromptOverride.name == "setup_spine"))
        ).content == old_spine


async def test_old_custom_review_and_triage_placeholders_still_render(sessionmaker):
    custom = "作者保存的模板\n{{concept}}\n{{spine}}\n{{lore}}\n{{outline}}\n{{threads}}\n{{first_volume}}"
    async with sessionmaker() as session:
        session.add_all([PromptOverride(name=name, content=custom) for name in ("setup_critique", "setup_triage")])
        await session.commit()
    setup = {
        "concept": {"title": "作者书名"},
        "world": {"characters": [{"name": "作者人物"}]},
        "segment": {"nodes": [{"title": "作者节点", "kind": "opening"}]},
        "volumes": {"volumes": [{"index": 1, "title": "作者卷"}], "threads": [{"name": "作者线索"}]},
    }
    llm = SimpleNamespace(structured=AsyncMock(return_value=None))
    await editorial.critique_setup(llm, "点子", "要求", setup, focus="全套")
    await editorial.triage_feedback(llm, setup, "要求", "意见")
    for call in llm.structured.await_args_list:
        assert all(text in call.args[3] for text in ("作者保存的模板", "作者人物", "作者节点", "作者卷", "作者线索"))
