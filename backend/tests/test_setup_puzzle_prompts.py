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
from app.prompts.catalog import BY_NAME, CATALOG, VARIABLE_LABELS, variables
from tests.later_changes import with_later_changes

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def default_prompts(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


def test_task3_schema_fields_descriptions_and_order_match_verbatim():
    task = ROOT / "docs/codex任务/第三包/3-开书新三步.md"
    for block in re.findall(r"```python\n(.*?)\n```", with_later_changes(task.read_text(encoding="utf-8")), re.S):
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
                updated = {
                    ("Pitch", "text"): "故事方向：一百字左右，一段话说清主角是谁、凭什么、想要什么、读者爽在哪",
                    ("PitchSet", "pitches"): "三个故事方向，彼此在读者享受的东西上有实质差别；作者定下的东西三个都保留",
                }
                assert actual.model_fields[name].description == updated.get((item.name, name), field.description), (
                    item.name,
                    name,
                )
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
    "setup_pitches": "b93adc4c08d74ed755f97f4e620c8d5afea595c0d6706e7bdfd9f14610d416b6",
    "setup_story": "b1bc94d476a379e0c5485b4ec5d5d81af479ad668e87b7196b30f14f43a407b2",
    # 2026-10-18 新书页第二步：金手指单独成一类，第 5、7 条改了
    "library_build_focus": "c2472b40bf248d7c17f456bb8b04b142b5224146a8b0f0260c347904c5e5dd32",
    "library_build_rest": "4a97372a5144f59718def6ab894df35e82de3b8703191a38795225a8b2548df4",
    "setup_outline": "c63dbda748ff87e91737c1294b24c20b8e400ad67fb60c0cdf91fecb249fb147",
}


def test_handbook_prompt_moves_are_byte_exact():
    for name, digest in {
        "chat_agent": "1356887042072904dbbe934055e1ed8e6bba28cc4c74bc6ddfa696dac6c87a43",
        "skills/opening": "4aa306890d634f444d43c4da71c0faea4ca303c6a05aa96d6936867918f6ef67",
    }.items():
        assert hashlib.sha256((ROOT / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == digest
        assert not (ROOT / f"docs/codex任务/主编手册/提示词/{name}.md").exists()


def test_chat_layer_catalog_order_metadata_and_variable_labels_match_task():
    assert BY_NAME["persona_chief"] == (
        "persona_chief",
        "主编人设",
        "角色与规矩",
        "chief",
        "主编的专业底子：写书、聊天都带",
    )
    for row in (
        (
            "voice_chief",
            "主编口吻",
            "角色与规矩",
            "chief",
            "主编在聊天里跟你说话时的身份、称呼和口吻；只用在聊天，写书不带",
        ),
        (
            "chat_voice",
            "口吻怎么用",
            "聊天",
            "chief",
            "跟主编聊天时接在主编口吻后面：口吻只管怎么说、不改判断，写进书里和记忆里的字不带口吻",
        ),
        (
            "chat_manner",
            "聊天的做法",
            "聊天",
            "chief",
            "自己的书里群聊、私聊共用：回答时想着的四件事和另外几件事；实际用接话的人的角色",
        ),
        (
            "chat_material",
            "聊天带的资料",
            "聊天",
            "chief",
            "所有聊天的用户提示：书的资料、之前聊过的、最近的对话和作者这次说的；实际用接话的人的角色",
        ),
    ):
        assert BY_NAME[row[0]] == row
        assert all(item["label"] for item in variables(row[0]))
    names = [row[0] for row in CATALOG]
    chief = names.index("persona_chief")
    agent = names.index("chat_agent")
    assert names[chief : chief + 2] == ["persona_chief", "voice_chief"]
    assert names[agent : agent + 5] == ["chat_agent", "chat_reply", "chat_voice", "chat_manner", "chat_material"]
    assert VARIABLE_LABELS["voice"] == "主编口吻"
    assert VARIABLE_LABELS["book"] == "简介或原书信息"


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
