"""第五步第三批：群聊里接话的人自己查、自己动手（工具调用）。演示模型打开「假装调工具」：先查话里提到的设定，
再照演示分流列清单动手，最后说一段话。"""

import asyncio

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.llm.router import LLMRouter, ToolsUnsupported, _tool_calls, _truncated
from app.main import create_app
from app.models import Book, Character, LlmCall, MeetingMessage, WorldEntry
from app.services import chat_tools
from app.services.chat import stop_key
from app.services.chat_agent import pick_role
from tests.test_chat_task6 import final_message, seed


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def say(client, book, text, **extra) -> dict:
    res = await client.post(f"/api/books/{book}/notes", json={"content": text, **extra})
    assert res.status_code == 201, res.text
    return await final_message(client, book, res.json()["id"])


async def messages(client, book) -> list[dict]:
    return (await client.get(f"/api/books/{book}/meeting?limit=2000")).json()


async def reply_of(client, book, mid) -> dict:
    return next(m for m in await messages(client, book) if (m["payload"] or {}).get("reply_to") == [mid])


async def titles(client, book) -> list[str]:
    return [row["title"] for row in (await client.get(f"/api/books/{book}/saves")).json()["items"]]


async def test_looks_up_then_changes_one_place(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风的性格改成冷静沉稳")
    assert note["payload"]["turn"] == "tools" and note["payload"]["chat_role"] == "chief"
    steps = note["payload"]["steps"]
    assert [s["kind"] for s in steps] == ["edit"], steps
    assert steps[0]["diff"][0]["label"] == "楚风 · 性格与说话方式" and steps[0]["diff"][0]["after"]
    reply = await reply_of(client, bid, note["id"])
    assert reply["speaker"] == "chief" and "state" not in reply["payload"] and reply["content"].startswith("（演示）")
    tools = reply["payload"]["tools"]
    assert tools[0] == {"kind": "query", "label": "楚风", "text": tools[0]["text"]} and "凝气境" in tools[0]["text"]
    assert tools[1]["kind"] == "act" and "做成了" in tools[1]["text"]
    # 编辑部动完存一档；改动挂在作者那句话下面，换回原来的照常能用
    assert (await titles(client, bid))[0] == "主编照你的话改了楚风（性格与说话方式）"
    assert (await client.get(f"/api/books/{bid}/note-changes")).json() == {f"{note['id']}:0": True}
    res = await client.post(f"/api/books/{bid}/notes/{note['id']}/revert", json={"step": 0})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.personality == ""
    # 每个来回记一条调用记录，看得清发了什么、工具回了什么
    async with sessionmaker() as session:
        calls = list(
            await session.scalars(select(LlmCall).where(LlmCall.book_id == bid, LlmCall.purpose == "聊天·主编"))
        )
    assert [c.request["round"] for c in calls] == [1, 2, 3]
    assert "工具回：" in calls[-1].request["user"] and calls[0].request["method"] == "tools"


async def test_question_only_looks_up(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风现在什么境界？")
    assert note["payload"]["ask_only"] is True and note["payload"]["chat_role"] == "lorekeeper"
    assert note["payload"]["outcome"] == {"kind": "chat", "handled": True} and not note["payload"].get("steps")
    reply = await reply_of(client, bid, note["id"])
    assert reply["speaker"] == "lorekeeper" and [t["kind"] for t in reply["payload"]["tools"]] == ["query"]
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid, LlmCall.purpose == "聊天·设定师"))
    names = [tool["function"]["name"] for tool in call.request["schema"]]
    assert "make_changes" not in names and "look_up_settings" in names


async def test_three_places_become_a_plan_card_and_apply_with_diffs(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风的性格改成冷静，然后境界的名称改成灵海，然后简介改成一个少年找灯的故事")
    steps = note["payload"]["steps"]
    assert [s["kind"] for s in steps] == ["plan_made"] and steps[0]["count"] == 3
    plan = next(m for m in await messages(client, bid) if m["id"] == steps[0]["plan_id"])
    items = plan["payload"]["plan"]["items"]
    assert [i["where"] for i in items] == ["设定库", "设定库", "定调"] and all(i["tool"] for i in items)
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.personality == ""  # 没直接改
    # 作者划掉第二条、改了第一条的字，再「按这个来」
    items[0]["change"] = "冷静，话少"
    res = await client.post(f"/api/plans/{plan['id']}/apply", json={"items": [items[0], items[2]]})
    assert res.status_code == 202, res.text
    plan = next(m for m in await messages(client, bid) if m["id"] == plan["id"])
    results = plan["payload"]["results"]
    assert [r["kind"] for r in results] == ["edit", "edit"] and all(r["diff"] for r in results)
    assert results[1]["target_label"] == "简介" and "outcome" not in plan["payload"]
    assert plan["payload"]["status"] == "applied"
    said = [m["content"] for m in await messages(client, bid) if (m["payload"] or {}).get("reply_to") == [plan["id"]]]
    assert said == ["方案「演示改动」照办了：改了 2 处。"]
    # 方案卡照办的每一条也能换回原来的
    assert (await client.get(f"/api/books/{bid}/note-changes")).json()[f"{plan['id']}:0"] is True
    res = await client.post(f"/api/books/{bid}/notes/{plan['id']}/revert", json={"step": 0})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.personality == ""
        book = await session.get(Book, bid)
        assert book.concept["story"] != "楚风找回青灯。"


async def test_delete_only_after_the_card_and_can_be_put_back(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "把境界删掉")
    step = note["payload"]["steps"][0]
    assert step["kind"] == "plan_made" and step["deleting"] is True
    plan = next(m for m in await messages(client, bid) if m["id"] == step["plan_id"])
    item = plan["payload"]["plan"]["items"][0]
    assert item["where"] == "删除" and item["target"] == "境界"
    async with sessionmaker() as session:
        assert await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid)) is not None
    res = await client.post(f"/api/plans/{plan['id']}/apply", json={"items": [item]})
    assert res.status_code == 202, res.text
    plan = next(m for m in await messages(client, bid) if m["id"] == plan["id"])
    result = plan["payload"]["results"][0]
    assert result["kind"] == "deleted" and result["diff"][0]["label"] == "删掉 · 境界"
    async with sessionmaker() as session:
        assert await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid)) is None
    res = await client.post(f"/api/books/{bid}/notes/{plan['id']}/revert", json={"step": 0})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        assert (await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid))).name == "境界"


async def test_retry_goes_on_without_doing_the_same_place_twice(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风的性格改成冷静，演示中途出错")
    assert [s["kind"] for s in note["payload"]["steps"]] == ["edit"]
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["state"] == "failed" and "演示中途出错" in reply["payload"]["error"]
    res = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
    assert res.status_code == 202, res.text
    reply = await reply_of(client, bid, note["id"])
    assert "state" not in reply["payload"] and reply["content"].startswith("（演示）")
    assert "之前已经做过了" in reply["payload"]["tools"][-1]["text"] or "之前已经做过了" in reply["content"]
    note = await final_message(client, bid, note["id"])
    assert [s["kind"] for s in note["payload"]["steps"]] == ["edit"]


async def test_again_only_rewrites_the_words(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风的性格改成冷静沉稳")
    reply = await reply_of(client, bid, note["id"])
    async with sessionmaker() as session:
        before = len(list(await session.scalars(select(LlmCall.id).where(LlmCall.book_id == bid))))
    res = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
    assert res.status_code == 202, res.text
    again = await reply_of(client, bid, note["id"])
    assert again["id"] == reply["id"] and again["content"]
    assert [s["kind"] for s in (await final_message(client, bid, note["id"]))["payload"]["steps"]] == ["edit"]
    async with sessionmaker() as session:
        new = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))[before:]
    assert new and all(c.request["method"] == "demo_stream" for c in new)
    assert all(not c.request.get("schema") for c in new)
    assert "做成了：" in new[-1].request["user"] and "楚风" in new[-1].request["user"]


async def test_stop_finishes_the_place_being_changed(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    real = chat_tools.run_change
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)

    async def slow(session, r, message, item):
        # 改第一处的时候作者点了「停」：这一处改完，第二处不做
        reply = await session.scalar(
            select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker != "author")
        )
        await redis.set(stop_key(reply.id), "1", ex=60)
        await asyncio.sleep(0.6)
        return await real(session, r, message, item)

    monkeypatch.setattr(chat_tools, "run_change", slow)
    note = await say(client, bid, "楚风的性格改成冷静，然后境界的名称改成灵海")
    await redis.aclose()
    assert [s["kind"] for s in note["payload"]["steps"]] == ["edit"]
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["state"] == "stopped"
    assert "停之前做完了：改了「" in reply["content"] and "没做：改境界的名称" in reply["content"]


async def test_model_without_tools_falls_back_to_routing(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)

    async def refuse(self, *args, **kwargs):
        raise ToolsUnsupported("不支持工具调用")
        yield  # pragma: no cover

    monkeypatch.setattr(LLMRouter, "tool_rounds", refuse)
    note = await say(client, bid, "楚风的性格改成冷静沉稳")
    outcome = note["payload"]["outcome"]
    assert outcome["kind"] == "edit" and outcome["diff"]
    reply = await reply_of(client, bid, note["id"])
    assert "state" not in reply["payload"] and reply["content"] == "好，已经按你的意思改了「楚风」。"
    # 演示模式默认不调工具：照旧先分流
    monkeypatch.setattr(demo, "FAKE_TOOLS", False)
    note = await say(client, bid, "境界的名称改成灵海")
    assert "turn" not in note["payload"] and note["payload"]["outcome"]["kind"] == "edit"


def test_pick_role_and_router_helpers():
    assert pick_role("这段剧情哪里不对") == "reviewer"
    assert pick_role("主角的金手指再强一点") == "lorekeeper"
    assert pick_role("帮我写一下第二篇") == "chief"

    class Message:
        tool_calls = [{"id": "", "name": "look_up_settings", "args": {"names": ["楚风"]}}]
        invalid_tool_calls = [{"id": "x", "name": "make_changes", "args": "{坏"}]
        response_metadata = {"finish_reason": "tool_callstool_calls"}

    calls = _tool_calls(Message(), 4)
    assert [(c.id, c.name, c.args) for c in calls] == [
        ("call_4_0", "look_up_settings", {"names": ["楚风"]}),
        ("x", "make_changes", None),
    ]
    assert not _truncated(Message())
    Message.response_metadata = {"finish_reason": "lengthlength"}
    assert _truncated(Message())
    assert {t["function"]["name"] for t in chat_tools.tool_specs(read_only=True)} == {
        *chat_tools.QUERY_TOOLS,
        *chat_tools.MEMORY_TOOLS,
        "read_skill",
    }


async def test_writing_tool_arguments_counts_as_activity(sessionmaker, monkeypatch):
    """模型写工具参数时不出字：也要吐 tick，看守才知道它还在动，不会按「没动静」掐掉（真模型试出来的）。"""
    from types import SimpleNamespace

    from langchain_core.messages import AIMessageChunk

    rounds = []

    class Fake:
        def bind_tools(self, tools, **kwargs):
            return self

        async def astream(self, history):
            rounds.append(len(history))
            if len(rounds) == 1:
                # 真的流里，工具名和 id 只在第一块
                for name, args, cid in (("look_up_settings", '{"names": ', "c1"), (None, '["楚风"]}', None)):
                    yield AIMessageChunk(
                        content="", tool_call_chunks=[{"name": name, "args": args, "id": cid, "index": 0}]
                    )
            else:
                yield AIMessageChunk(content="查过了")

    async def resolve(self, role):
        return SimpleNamespace(provider="openai", name="假", model="假", structured_method="function_calling")

    async def record(self, *args, **kwargs):
        return None

    monkeypatch.setattr(LLMRouter, "resolve", resolve)
    monkeypatch.setattr(LLMRouter, "_chat_model", lambda self, profile, streaming=False: Fake())
    monkeypatch.setattr(LLMRouter, "_record", record)
    llm = LLMRouter(sessionmaker)
    seen = []

    async def run_tool(call):
        seen.append((call.name, call.args))
        return "楚风：凝气境"

    events = [
        e async for e in llm.tool_rounds("chief", "系统", "问", chat_tools.tool_specs(True), run_tool, purpose="试")
    ]
    await llm.aclose()
    assert seen == [("look_up_settings", {"names": ["楚风"]})]
    assert events == [("tick", ""), ("tick", ""), ("text", "查过了")]
