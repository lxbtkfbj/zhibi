"""一起发的：按发送位置分段记录，详情用当前目录名解释新旧调用。"""

import httpx
import pytest
from sqlalchemy import select

from app import prompts
from app.agents import editorial, playbook
from app.llm import demo
from app.llm.router import LLMRouter
from app.main import app
from app.models import LlmCall
from app.prompts import prompt_names_for, prompt_parts_for, track_rendered
from app.prompts.catalog import variables
from app.services import chat_prompts


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


def values(name: str, **overrides: str) -> dict[str, str]:
    return {**{item["name"]: "" for item in variables(name)}, **overrides}


async def calls(sessionmaker) -> list[LlmCall]:
    async with sessionmaker() as session:
        result = list(await session.scalars(select(LlmCall).order_by(LlmCall.id)))
    assert result and all(row.model == "demo" and row.ok for row in result)
    return result


def test_parts_sort_by_first_content_position_and_deduplicate_not_render_order():
    token = prompts._rendered.set(())
    try:
        track_rendered("voice_chief", "声音")
        track_rendered("chat_voice", "口吻：声音")
        track_rendered("rules", "规则")
        track_rendered("rules", "另一份规则")
        track_rendered("chat_material", "资料")
        track_rendered("setup_story", "没发送过的模板")
        system = "口吻：声音\n另一份规则\n规则\n口吻：声音"
        user = "资料\n规则\n资料"
        assert prompt_parts_for(system, user) == {
            "system": ["chat_voice", "voice_chief", "rules"],
            "user": ["chat_material", "rules"],
        }
        # 保持旧的 prompt_names 合同：仍按渲染顺序，不改变目录的最近一次查找。
        assert prompt_names_for(system, user) == ["voice_chief", "chat_voice", "rules", "chat_material"]
        assert prompt_parts_for("", "") == {"system": [], "user": []}
    finally:
        prompts._rendered.reset(token)


async def test_demo_writing_structured_records_task_and_nested_playbook(sessionmaker):
    style = playbook.load("general").text("chapters")
    blocks = values("setup_story", idea="陆远提着青灯进入旧城", style=style)
    async with LLMRouter(sessionmaker) as llm:
        result = await editorial.draft_story(llm, blocks)
    assert result.story
    call = (await calls(sessionmaker))[0]
    assert call.request["method"] == "demo"
    assert call.request["prompt_parts"] == {
        "system": ["persona_chief", "rules"],
        "user": ["setup_story", "playbooks.general"],
    }


async def test_demo_direct_writing_records_system_and_user_separately(sessionmaker):
    blocks = values("write_chapter", chapter_index="1", chapter_title="灯火", chapter_words="100")
    async with LLMRouter(sessionmaker) as llm:
        output = "".join([chunk async for chunk in editorial.write_chapter(llm, blocks)])
    assert output
    call = (await calls(sessionmaker))[0]
    assert call.request["method"] == "demo_stream"
    assert call.request["prompt_parts"] == {
        "system": ["persona_writer", "rules"],
        "user": ["write_chapter"],
    }


async def test_demo_tool_rounds_record_seven_layers_in_send_order_and_expose_details(sessionmaker, client):
    system = chat_prompts.system_prompt("chief", "chat_agent", **values("chat_agent", role_focus=""))
    user = prompts.render(
        "chat_material",
        **values(
            "chat_material",
            library="<设定库>\n- 楚风：主角\n</设定库>",
            note="<作者这次说的>\n楚风怎么样？\n</作者这次说的>",
        ),
    )
    tools = [{"type": "function", "function": {"name": "look_up_settings", "parameters": {"type": "object"}}}]
    ran = []

    async def run_tool(call):
        ran.append(call)
        return "楚风：谨慎的少年。"

    async with LLMRouter(sessionmaker) as llm:
        output = [event async for event in llm.tool_rounds("chief", system, user, tools, run_tool, purpose="聊天·主编")]
    recorded = await calls(sessionmaker)
    expected = {
        "system": ["persona_chief", "chat_voice", "voice_chief", "chat_agent", "chat_manner", "rules"],
        "user": ["chat_material"],
    }
    assert ran and ran[0].name == "look_up_settings"
    assert len(recorded) == 2 and any(kind == "text" for kind, _ in output)
    assert [row.request["round"] for row in recorded] == [1, 2]
    assert all(row.request["prompt_parts"] == expected for row in recorded)
    prompt = (await client.get("/api/prompts/chat_manner")).json()
    last = prompt["last_call"]
    assert last["id"] == recorded[-1].id and last["created_at"] and last["purpose"] == "聊天·主编"
    assert {key: [ref["name"] for ref in refs] for key, refs in last["used_prompts"]["parts"].items()} == expected
    assert [ref["title"] for ref in last["used_prompts"]["parts"]["system"]] == [
        "主编人设",
        "口吻怎么用",
        "主编口吻",
        "群聊：自己查、自己动手",
        "聊天的做法",
        "通用规则",
    ]
    detail = (await client.get(f"/api/llm-calls/{recorded[-1].id}")).json()
    assert detail["used_prompts"] == last["used_prompts"]
    assert [ref["name"] for ref in detail["used_prompts"]["names"]] == recorded[-1].request["prompt_names"]
    # 整份目录维持旧响应，不为每份附上调用原文或 used_prompts。
    catalog = (await client.get("/api/prompts")).json()
    summary = next(row for row in catalog if row["name"] == "chat_manner")["last_call"]
    assert set(summary) == {"id", "created_at"}
    assert (await client.get("/api/prompts/essence_check")).json()["last_call"] is None


@pytest.mark.parametrize("parts", [None, {"system": ["chat_manner", "removed_prompt"], "user": ["skills.opening"]}])
async def test_new_and_old_record_titles_keep_removed_handbook_name(sessionmaker, client, parts):
    original = (await client.get("/api/handbooks/opening")).json()
    response = await client.put(
        "/api/handbooks/opening",
        json={"name": "作者改过的开书手册", "when": original["when"], "body": original["body"]},
    )
    assert response.status_code == 200, response.text
    names = ["skills.opening", "chat_manner", "removed_prompt"]
    request = {"prompt_names": names}
    if parts is not None:
        request["prompt_parts"] = parts
    async with sessionmaker() as session:
        old = LlmCall(role="chief", purpose="旧的用途", request={"prompt_names": ["chat_manner"]})
        latest = LlmCall(role="chief", purpose="最近的用途", request=request)
        session.add_all([old, latest])
        await session.commit()
        call_id = latest.id
    expected_refs = [
        {"name": "skills.opening", "title": "skills.opening"},
        {"name": "chat_manner", "title": "聊天的做法"},
        {"name": "removed_prompt", "title": "removed_prompt"},
    ]
    detail = (await client.get(f"/api/llm-calls/{call_id}")).json()
    used = detail["used_prompts"]
    assert used["names"] == expected_refs
    if parts is None:
        assert used["parts"] is None
    else:
        assert used["parts"] == {"system": [expected_refs[1], expected_refs[2]], "user": [expected_refs[0]]}
    prompt = (await client.get("/api/prompts/chat_manner")).json()
    assert prompt["last_call"]["id"] == call_id
    assert prompt["last_call"]["purpose"] == "最近的用途"
    assert prompt["last_call"]["used_prompts"] == used
    assert (await client.get("/api/prompts/skills.opening")).status_code == 404
    assert (await client.get("/api/handbooks/opening")).json()["name"] == "作者改过的开书手册"
    # 不补写历史行，也不根据当前提示词正文推断旧记录的两段。
    async with sessionmaker() as session:
        assert (await session.get(LlmCall, call_id)).request == request


@pytest.mark.parametrize("stored_request", [None, {}, {"system": "很早的原文", "user": "没记模板名"}])
async def test_earliest_records_have_no_used_prompt_names_or_parts(sessionmaker, client, stored_request):
    async with sessionmaker() as session:
        call = LlmCall(role="chief", request=stored_request)
        session.add(call)
        await session.commit()
        call_id = call.id
    detail = (await client.get(f"/api/llm-calls/{call_id}")).json()
    assert detail["used_prompts"] == {"parts": None, "names": []}
    assert (await client.get("/api/prompts/chat_manner")).json()["last_call"] is None
