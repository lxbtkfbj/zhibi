"""手册按文件发现、作者覆盖、群聊工具与独立的能力记忆；不调用真实模型。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis

from alembic import command
from app.api import llm_settings
from app.config import get_settings
from app.llm import demo
from app.llm import router as router_module
from app.llm.router import DEMO_PROFILE, LLMRouter, ResolvedProfile, ToolsUnsupported
from app.main import create_app
from app.models import LlmCall, LlmProfile, PromptOverride
from app.prompts import canonical_name, default_content, handbooks
from app.schemas import ProfilePatch
from app.services import chat_agent, chat_tools
from tests.test_author_requirement_sequence import insert_legacy_row, legacy_database
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed
from tests.test_structured_method_memory import Answer, bad_request
from tests.test_structured_method_memory import seed as seed_profile


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


def fake_books(monkeypatch, tmp_path):
    folder = tmp_path / "prompts" / "skills"
    folder.mkdir(parents=True)
    for key, content in {
        "z_last": "# 打斗\n什么时候翻：写打斗时。\n全文打斗",
        "a_first": "# 开书\n什么时候翻：开书时。\n全文开书",
        "BAD": "bad",
        "1_bad": "bad",
    }.items():
        (folder / f"{key}.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(handbooks.resources, "files", lambda _: folder.parent)
    default_content.cache_clear()
    return folder


def test_directory_and_enum_follow_sorted_files(monkeypatch, tmp_path):
    fake_books(monkeypatch, tmp_path)
    try:
        assert handbooks.keys() == ["a_first", "z_last"]
        spec = handbooks.tool_spec()["function"]
        assert (
            spec["description"] == "翻编辑部的专业手册，拿到全文再答。手册目录：\n- 开书：开书时。\n- 打斗：写打斗时。"
        )
        assert spec["parameters"]["properties"]["name"] == {
            "type": "string",
            "enum": ["开书", "打斗"],
            "description": "手册的名称，照目录写",
        }
        assert handbooks.read("没有") == "没有这本手册：没有。目录里有：开书、打斗"
    finally:
        default_content.cache_clear()


async def test_prompt_page_override_updates_directory_and_full_text(client):
    assert canonical_name("skills/opening") == "skills.opening"
    rows = (await client.get("/api/prompts")).json()
    row = next(row for row in rows if row["name"] == "skills.opening")
    assert row["title"] == "开书" and row["group"] == "手册"
    assert row["role"] == "chief,lorekeeper,writer,reviewer"
    assert row["when"].startswith("群聊里编辑部自己翻：聊到怎么开一本书")
    content = "# 新书根基\n什么时候翻：问根基时。\n" + "完整正文" * 1000
    response = await client.put("/api/prompts/skills.opening", json={"content": content})
    assert response.status_code == 200, response.text
    row = next(row for row in (await client.get("/api/prompts")).json() if row["name"] == "skills.opening")
    assert row["title"] == "新书根基" and row["when"] == "群聊里编辑部自己翻：问根基时。"
    assert handbooks.tool_spec()["function"]["parameters"]["properties"]["name"]["enum"] == ["新书根基"]
    label, full = await chat_tools.look_up(None, None, "read_skill", chat_tools.ReadSkill(name="新书根基"), None)
    assert label == "手册《新书根基》" and full == content
    assert handbooks.read("错名") == "没有这本手册：错名。目录里有：新书根基"
    assert (await client.delete("/api/prompts/skills.opening")).status_code == 200
    assert handbooks.read("开书") == default_content("skills.opening")


@pytest.mark.parametrize(
    "content,missing",
    [
        ("名称\n什么时候翻：问时", "第一行必须是 # 名称"),
        ("# 名称\n正文", "什么时候翻："),
        ("# 名称\n什么时候翻：\n正文", "什么时候翻："),
        ("# 名称\n什么时候翻：问时\n{{变量}}", "手册不能有 {{变量}}"),
    ],
)
async def test_invalid_handbook_save_is_rejected(client, sessionmaker, content, missing):
    response = await client.put("/api/prompts/skills.opening", json={"content": content})
    assert response.status_code == 422 and missing in response.json()["detail"]
    async with sessionmaker() as session:
        assert await session.get(PromptOverride, "skills.opening") is None


async def test_duplicate_name_uses_current_other_handbook(client, monkeypatch, tmp_path):
    fake_books(monkeypatch, tmp_path)
    try:
        assert (
            await client.put("/api/prompts/skills.z_last", json={"content": "# 格斗\n什么时候翻：问时"})
        ).status_code == 200
        response = await client.put("/api/prompts/skills.a_first", json={"content": "# 格斗\n什么时候翻：问时"})
        assert response.status_code == 422 and "不能重名" in response.json()["detail"]
        assert (
            await client.put("/api/prompts/skills.a_first", json={"content": "# 改名\n什么时候翻：问时"})
        ).status_code == 200
        assert (
            await client.put("/api/prompts/skills.z_last", json={"content": "# 开书\n什么时候翻：问时"})
        ).status_code == 200
        assert (await client.delete("/api/prompts/skills.a_first")).status_code == 422
    finally:
        default_content.cache_clear()


def test_tools_absent_when_no_handbooks_and_in_teardown(monkeypatch):
    assert chat_tools.doing_of("read_skill", chat_tools.ReadSkill(name="开书")) == "在翻《开书》"
    assert "read_skill" in [t["function"]["name"] for t in chat_tools.tool_specs(True)]
    assert "read_skill" not in [t["function"]["name"] for t in chat_tools.tool_specs(True, skills=False)]
    monkeypatch.setattr(handbooks, "keys", lambda: [])
    assert "read_skill" not in [t["function"]["name"] for t in chat_tools.tool_specs(False)]


@pytest.mark.parametrize("question", ["开书先定什么", "开书先定什么？"])
async def test_demo_asks_reads_full_handbook_and_again_keeps_material(client, sessionmaker, question, monkeypatch):
    doing = []
    original = chat_agent.set_doing

    async def capture(turn, text, **kwargs):
        doing.append((text, kwargs))
        return await original(turn, text, **kwargs)

    monkeypatch.setattr(chat_agent, "set_doing", capture)
    bid = await seed(sessionmaker)
    note = await say(client, bid, question)
    reply = await reply_of(client, bid, note["id"])
    full = default_content("skills.opening")
    assert reply["payload"]["tools"][0] == {"kind": "query", "label": "手册《开书》", "text": full}
    assert "翻了开书手册。" in reply["content"]
    assert ("在翻《开书》", {"ellipsis": False}) in doing
    async with sessionmaker() as session:
        calls = list(await session.scalars(sa.select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))
        assert '"name": "开书"' in calls[0].response
        assert full in calls[1].request["user"]
        if question.endswith("？"):
            assert note["payload"]["ask_only"] is True
            assert "make_changes" not in [tool["function"]["name"] for tool in calls[0].request["schema"]]
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 202
    async with sessionmaker() as session:
        last = await session.scalar(sa.select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id.desc()))
        assert full in last.request["user"] and last.request["method"] == "demo_stream"


async def test_private_chat_does_not_get_handbook_tools(client, sessionmaker):
    bid = await seed(sessionmaker)
    await say(client, bid, "开书先定什么", to="chief")
    async with sessionmaker() as session:
        calls = list(await session.scalars(sa.select(LlmCall).where(LlmCall.book_id == bid)))
        assert calls and all(call.request["method"] != "tools" for call in calls)


async def test_demo_reads_handbook_before_lookup_and_continues_normally(client):
    from app.llm.router import ToolCall

    user = "<作者这次说的>\n开书时楚风的性格怎么样？\n</作者这次说的>\n<设定库>\n- 楚风：主角\n</设定库>"
    tools = ["read_skill", "look_up_settings"]
    planned, _ = demo.tool_turn("主编", user, tools, [])
    assert planned == [("read_skill", {"name": "开书"})]
    done = [(ToolCall("s", "read_skill", {"name": "开书"}), "手册全文")]
    planned, _ = demo.tool_turn("主编", user, tools, done)
    assert planned == [("look_up_settings", {"names": ["楚风"]})]
    done.append((ToolCall("q", "look_up_settings", {"names": ["楚风"]}), "性格全文"))
    planned, text = demo.tool_turn("主编", user, tools, done)
    assert planned == [] and "查了楚风。" in text and "翻了开书手册。" in text


@pytest.mark.parametrize(
    "method,capability,expected",
    [
        ("json_mode", None, True),
        ("json_mode", True, True),
        ("function_calling", False, False),
        ("json_mode", False, False),
    ],
)
async def test_supports_tools_only_uses_chat_capability(monkeypatch, method, capability, expected):
    profile = ResolvedProfile(
        name="fake",
        provider="openai_compatible",
        base_url="https://fake.example/v1",
        structured_method=method,
        chat_tools=capability,
    )
    monkeypatch.setattr(LLMRouter, "resolve", AsyncMock(return_value=profile))
    assert await chat_agent.supports_tools("chief") is expected
    monkeypatch.setattr(
        LLMRouter, "resolve", AsyncMock(return_value=replace(profile, base_url="http://localhost:11434/v1"))
    )
    assert await chat_agent.supports_tools("chief") is False
    monkeypatch.setattr(LLMRouter, "resolve", AsyncMock(return_value=DEMO_PROFILE))
    monkeypatch.setattr(demo, "FAKE_TOOLS", False)
    assert await chat_agent.supports_tools("chief") is False
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    assert await chat_agent.supports_tools("chief") is True


@pytest.mark.parametrize("method", ["json_mode", "function_calling"])
async def test_rejected_chat_tools_do_not_change_structured_method(sessionmaker, monkeypatch, method):
    pid = await seed_profile(sessionmaker, method)

    async def refuse(*args, **kwargs):
        raise bad_request("tools are not supported")
        yield

    model = Mock()
    model.bind_tools.return_value.astream = refuse
    async with LLMRouter(sessionmaker) as llm:
        monkeypatch.setattr(llm, "_chat_model", Mock(return_value=model))
        with pytest.raises(ToolsUnsupported):
            _ = [
                value
                async for value in llm.tool_rounds(
                    "chief", "system", "user", [router_module.PROBE_TOOL], AsyncMock(), purpose="fake"
                )
            ]
    async with sessionmaker() as session:
        row = await session.get(LlmProfile, pid)
        assert row.chat_tools is False and row.structured_method == method and not row.structured_method_auto


async def test_structured_fallback_does_not_change_chat_tools(sessionmaker, monkeypatch):
    from app.llm.router import Outcome

    pid = await seed_profile(sessionmaker)
    async with sessionmaker() as session:
        row = await session.get(LlmProfile, pid)
        row.chat_tools = True
        await session.commit()
    async with LLMRouter(sessionmaker) as llm:
        monkeypatch.setattr(
            llm,
            "_invoke_structured",
            AsyncMock(
                side_effect=[
                    bad_request("tools unsupported"),
                    Outcome(usage=(1, 1), parsed=Answer(answer="ok"), response='{"answer":"ok"}'),
                ]
            ),
        )
        await llm.structured("chief", Answer, "system", "user", purpose="fake")
    async with sessionmaker() as session:
        row = await session.get(LlmProfile, pid)
        assert row.chat_tools is True and row.structured_method == "json_mode" and row.structured_method_auto


@pytest.mark.parametrize(
    "change,cleared",
    [
        ({"provider": "demo"}, True),
        ({"base_url": "https://new.example/v1"}, True),
        ({"model": "new"}, True),
        ({"api_key": "fake-key"}, True),
        ({"name": "renamed"}, False),
        ({"temperature": 0.5}, False),
        ({"structured_method": "json_schema"}, False),
        ({"model": "chat", "api_key": ""}, False),
    ],
)
async def test_profile_changes_only_clear_chat_capability_for_connection_changes(sessionmaker, change, cleared):
    pid = await seed_profile(sessionmaker)
    async with sessionmaker() as session:
        row = await session.get(LlmProfile, pid)
        row.chat_tools = False
        await session.commit()
        out = await llm_settings.update_profile(pid, ProfilePatch(**change), session)
        assert out.chat_tools is (None if cleared else False)


async def test_capability_remember_waits_for_author_and_does_not_overwrite(sessionmaker):
    pid = await seed_profile(sessionmaker)
    async with LLMRouter(sessionmaker) as llm:
        original = await llm.resolve("chief")
        async with sessionmaker() as author:
            await llm_settings._get(author, pid, for_update=True)
            pending = asyncio.create_task(llm._remember_chat_tools(original, False))
            try:
                await asyncio.sleep(0.05)
                assert not pending.done()
                await llm_settings.update_profile(pid, ProfilePatch(api_key="new-fake-key"), author)
                await asyncio.wait_for(pending, 5)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    async with sessionmaker() as session:
        assert (await session.get(LlmProfile, pid)).chat_tools is None


@pytest.mark.parametrize("result", ["called", "not_called", "error"])
async def test_json_mode_test_button_probes_and_writes_back(client, sessionmaker, monkeypatch, result):
    pid = await seed_profile(sessionmaker, "json_mode")
    monkeypatch.setattr(llm_settings, "ping", AsyncMock(return_value="假的接口连上了"))
    invoke = AsyncMock(return_value=SimpleNamespace(tool_calls=[{"name": "look_up"}] if result == "called" else []))
    if result == "error":
        invoke.side_effect = RuntimeError("fake refusal")
    model = Mock()
    model.bind_tools.return_value.ainvoke = invoke
    monkeypatch.setattr(router_module, "build_chat_model", Mock(return_value=model))
    response = await client.post(f"/api/llm/profiles/{pid}/test")
    assert response.status_code == 200 and response.json()["tools"] is (result == "called")
    invoke.assert_awaited_once()
    model.bind_tools.assert_called_once_with([router_module.PROBE_TOOL])
    async with sessionmaker() as session:
        row = await session.get(LlmProfile, pid)
        assert row.chat_tools is (result == "called") and row.structured_method == "json_mode"
    assert (await client.get("/api/llm/profiles")).json()[0]["chat_tools"] is (result == "called")


def test_0027_upgrade_downgrade_preserves_old_profiles(migration_database_urls):
    with legacy_database(migration_database_urls) as (config, engine, metadata):
        command.upgrade(config, "0026")
        with engine.begin() as conn:
            insert_legacy_row(
                conn, metadata.tables["llm_profiles"], name="old", structured_method="json_mode", temperature=0.8
            )
            before = dict(conn.execute(sa.text("SELECT * FROM llm_profiles")).mappings().one())
        for _ in range(2):
            command.upgrade(config, "0027")
            with engine.connect() as conn:
                after = dict(conn.execute(sa.text("SELECT * FROM llm_profiles")).mappings().one())
                assert after.pop("chat_tools") is None and after == before
            command.downgrade(config, "0026")
            assert "chat_tools" not in {c["name"] for c in sa.inspect(engine).get_columns("llm_profiles")}
            with engine.connect() as conn:
                assert dict(conn.execute(sa.text("SELECT * FROM llm_profiles")).mappings().one()) == before
