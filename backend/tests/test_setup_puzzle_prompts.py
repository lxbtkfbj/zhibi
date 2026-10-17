"""第三包 schema 原文、提示词搬运和旧作者模板保护。"""

import ast
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.agents import editorial
from app.agents import schemas as s
from app.llm import demo, demo_setup
from app.main import app
from app.models import PromptOverride
from app.prompts.catalog import BY_NAME, variables

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def default_prompts(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


def test_task3_schema_fields_descriptions_and_order_match_verbatim():
    task = ROOT / "docs/codex任务/第三包/3-开书新三步.md"
    for block in re.findall(r"```python\n(.*?)\n```", task.read_text(encoding="utf-8"), re.S):
        if not block.startswith("class "):
            continue
        namespace = vars(s).copy()
        exec(compile(block, str(task), "exec"), namespace)
        for item in ast.parse(block).body:
            if not isinstance(item, ast.ClassDef):
                continue
            actual, expected = getattr(s, item.name), namespace[item.name]
            assert list(actual.model_fields) == list(expected.model_fields), item.name
            for name, field in expected.model_fields.items():
                assert actual.model_fields[name].description == field.description, (item.name, name)
                assert actual.model_fields[name].default == field.default, (item.name, name)


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


PROMPT_HASHES = {
    "setup_notes": "6decc9266e64f6a871b8352e0aaa73db7c9a31b8c0b40149561fa853ea9fd7e0",
    "setup_pitches": "68c32b42c7930ff630d9d33e11d30198afecd89842ce4abec9cbbbce39c05310",
    "setup_story": "cd41168529586828a8acbaa525d0f0855e8332debb890a31d319f8e4ed2bb8e3",
    "library_build_focus": "190c93ea4773ff77ff9815624b3f1ef367e11425ae7f0f4997488b8c69aa29af",
    "library_build_rest": "1f7aa88a56589f3683ed43369fecb62adc3cc8f355c7426d12366de61e54ac94",
    "setup_outline": "c63dbda748ff87e91737c1294b24c20b8e400ad67fb60c0cdf91fecb249fb147",
}


def test_prompt_moves_are_byte_exact_and_retired_hidden():
    for name, digest in PROMPT_HASHES.items():
        path = ROOT / f"backend/app/prompts/{name}.md"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert not (ROOT / f"docs/codex任务/第三包/提示词/{name}.md").exists()
        assert name in BY_NAME
        assert all(row["label"] for row in variables(name))
    for name in (
        "setup_directions",
        "setup_interview",
        "setup_concept",
        "setup_protagonist",
        "setup_world",
        "setup_segment",
        "setup_critique",
        "setup_triage",
        "setup_node_slot",
    ):
        assert name not in BY_NAME
        assert not (ROOT / f"backend/app/prompts/{name}.md").exists()


async def test_all_new_demo_schemas_and_length_conversion():
    for schema in (s.PitchSet, s.StoryConcept, s.LibraryFocus, s.LibraryRest, s.OutlineDraft, s.SetupNotePlan):
        result = await demo.respond(schema, "", "测试自建类别")
        assert isinstance(result, schema)
    assert len(demo_setup.pitches("").pitches) == 3
    assert demo_setup.pitches("").recommended == 1
    concept = demo_setup.concept("")
    assert 150 <= len(concept.story) <= 500
    assert s.StoryConcept.model_validate({**concept.model_dump(), "target_length": 2000000}).target_length == 200
    assert s.StoryConcept.model_validate({**concept.model_dump(), "target_length": "200万"}).target_length == 200
    rest = demo_setup.rest("测试自建类别")
    assert rest.categories[0].name == "厉鬼"
    assert next(e for e in rest.entries if e.name == "末班车司机").category == "厉鬼"
    assert len(rest.entries[0].levels) == 6
    outline = demo_setup.outline("")
    assert len(outline.units) == 4
    assert sum(u.chapter_count for u in outline.units) == outline.volumes[0].chapter_count == 60
