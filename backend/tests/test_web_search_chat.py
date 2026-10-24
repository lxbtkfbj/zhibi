"""联网搜索的群聊接线合同；模型和 HTTP 都用假的，不访问外网。"""

import json
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.crypto import encrypt
from app.llm import demo, web_search
from app.llm.router import LLMRouter, ToolCall
from app.models import Book, LlmCall, LlmProfile, MeetingMessage, RoleAssignment
from app.services import chat_agent, chat_tools
from tests import test_handbooks
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed

client = test_handbooks.client


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("联网搜索接线测试禁止创建真实模型客户端")

    monkeypatch.setattr(LLMRouter, "_chat_model", forbidden)


async def official(sm):
    async with sm() as session:
        model = LlmProfile(name="只用演示模型", provider="demo", model="demo")
        session.add(model)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=model.id))
        row = LlmProfile(
            name="假官方DeepSeek",
            provider="openai_compatible",
            base_url="https://api.deepseek.com/v1",
            model="never-call",
            api_key_encrypted=encrypt("fake-key"),
        )
        session.add(row)
        await session.commit()
        return row.id


@pytest.fixture
async def fake_search(monkeypatch):
    requests, turns, clients = [], [], []
    original = web_search.WebSearchTurn

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("fetch"):
            if "blocked" in json.loads(request.content)["url"]:
                return httpx.Response(403)
            return httpx.Response(200, json={"title": "异火榜", "content": r"\# 网页原文" + "字" * 6100})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "异火榜",
                        "site_name": "假百科",
                        "url": "https://example.com/fire",
                        "summary": "假搜索摘要原文。",
                    }
                ]
            },
        )

    def make_turn(key):
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        clients.append(client)
        turn = original(key, client=client, today=date(2026, 10, 24), base_url="http://127.0.0.1:18075")
        turns.append(turn)
        return turn

    monkeypatch.setattr(web_search, "WebSearchTurn", make_turn)
    yield requests, turns
    for client in clients:
        await client.aclose()


@pytest.mark.parametrize("mode", ["new", "ask", "teardown"])
async def test_group_tools_appended_for_all_group_routes(client, sessionmaker, monkeypatch, fake_search, mode):
    await official(sessionmaker)
    bid = await seed(sessionmaker)
    if mode == "teardown":
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            book.source = "teardown"
            await session.commit()

    def tool_turn(system, user, available, done):
        assert list(available)[-2:] == ["search_web", "read_webpage"]
        if mode != "new":
            assert "make_changes" not in available
        if not done:
            return [("search_web", {"query": "斗破苍穹 异火"})], ""
        return [], "（演示）网上查到了。"

    monkeypatch.setattr(demo, "tool_turn", tool_turn)
    note = await say(client, bid, "请上网搜 斗破苍穹 异火" + ("？" if mode == "ask" else ""))
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["tools"] == [
        {"kind": "query", "label": "网上搜「斗破苍穹 异火」", "text": reply["payload"]["tools"][0]["text"]}
    ]
    assert "假搜索摘要原文。" in reply["payload"]["tools"][0]["text"]
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id))
        assert call.request["schema"][-2:] == web_search.tool_specs(date(2026, 10, 24))
    assert len(fake_search[0]) == 1


@pytest.mark.parametrize("mode", ["missing", "private", "legacy"])
async def test_excluded_routes_never_get_online_tools(client, sessionmaker, monkeypatch, fake_search, mode):
    if mode != "missing":
        await official(sessionmaker)
    bid = await seed(sessionmaker)
    if mode == "legacy":
        monkeypatch.setattr(demo, "FAKE_TOOLS", False)
    await say(client, bid, "上网搜 斗破苍穹 异火？", **({"to": "chief"} if mode == "private" else {}))
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid)))
        assert calls
        for call in calls:
            names = (
                [s["function"]["name"] for s in call.request.get("schema") or []]
                if call.request["method"] == "tools"
                else []
            )
            assert "search_web" not in names and "read_webpage" not in names
    assert not fake_search[0] and not fake_search[1]


async def test_demo_and_reanswer_reuse_original_search_material(client, sessionmaker, fake_search):
    await official(sessionmaker)
    bid = await seed(sessionmaker)
    note = await say(client, bid, "上网搜 斗破苍穹 异火")
    reply = await reply_of(client, bid, note["id"])
    assert "上网搜了「斗破苍穹 异火」。" in reply["content"]
    text = reply["payload"]["tools"][0]["text"]
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 202
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id.desc()))
        assert call.request["method"] == "demo_stream" and not call.request.get("schema")
        assert text in call.request["user"]
    assert len(fake_search[0]) == 1


async def test_progress_labels_limits_errors_and_cached_pages(client, sessionmaker, monkeypatch, fake_search):
    await official(sessionmaker)
    bid = await seed(sessionmaker)
    seen, returned = [], []
    original_doing, original_run = chat_agent.set_doing, chat_agent.run_tool

    async def capture(turn, text, **kwargs):
        await original_doing(turn, text, **kwargs)
        async with sessionmaker() as session:
            reply = await session.get(MeetingMessage, turn.reply_id)
            seen.append(reply.payload["doing"])

    async def capture_run(turn, call):
        text = await original_run(turn, call)
        returned.append(text)
        return text

    def tool_turn(system, user, available, done):
        if done:
            return [], "（演示）查完。"
        return [
            ("search_web", {"query": "  "}),
            ("read_webpage", {"url": "file:///not-web"}),
            *[("search_web", {"query": "  " + "长" * 40 + "  "}) for _ in range(6)],
            ("read_webpage", {"url": "https://example.com/fire"}),
            ("read_webpage", {"url": "https://example.com/fire", "start": "6000"}),
            ("read_webpage", {"url": "https://example.com/blocked"}),
            ("read_webpage", {"url": "https://example.com/third"}),
            ("read_webpage", {"url": "https://example.com/fourth"}),
        ], ""

    monkeypatch.setattr(chat_agent, "set_doing", capture)
    monkeypatch.setattr(chat_agent, "run_tool", capture_run)
    monkeypatch.setattr(demo, "tool_turn", tool_turn)
    note = await say(client, bid, "请查资料？")
    reply = await reply_of(client, bid, note["id"])
    records = reply["payload"]["tools"]
    assert seen == [f"在上网搜「{'长' * 30}」……"] * 5 + ["在读网页 example.com……"] * 4
    assert [r["label"] for r in records] == [f"网上搜「{'长' * 30}」"] * 5 + [
        "网页《异火榜》",
        "网页《异火榜》",
        "网页 example.com",
        "网页《异火榜》",
    ]
    assert len(fake_search[0]) == 8 and len(records) == 9
    assert returned[0] == "没说要搜什么。"
    assert returned[7] == web_search.SEARCH_LIMIT and returned[-1] == web_search.PAGE_LIMIT
    assert "start 填 6000" in records[5]["text"]
    assert "第 6001～" in records[6]["text"]
    assert records[7]["text"] == web_search.cannot_read("https://example.com/blocked")


async def test_key_is_frozen_per_answer_and_refreshed_next_turn(client, sessionmaker, monkeypatch, fake_search):
    pid = await official(sessionmaker)
    bid = await seed(sessionmaker)
    original = chat_agent.run_tool
    mutated = False

    async def mutate(turn, call):
        nonlocal mutated
        if not mutated:
            mutated = True
            async with sessionmaker() as session:
                profile = await session.get(LlmProfile, pid)
                profile.name = "换名后的配置"
                profile.api_key_encrypted = encrypt("next-key")
                await session.commit()
        return await original(turn, call)

    monkeypatch.setattr(chat_agent, "run_tool", mutate)
    await say(client, bid, "上网搜 斗破苍穹 异火")
    await say(client, bid, "上网搜 斗破苍穹 异火")
    assert [r.headers["Authorization"] for r in fake_search[0]] == ["Bearer fake-key", "Bearer next-key"]
    assert [t.key.name for t in fake_search[1]] == ["假官方DeepSeek", "换名后的配置"]


async def test_no_key_rejects_unadvertised_call_without_progress_or_record():
    turn = chat_agent.Turn(None, None, 0, 0, "chief", True, None)
    assert await chat_agent.run_tool(turn, ToolCall("x", "search_web", {"query": "test"})) == "这句话不能联网搜索。"
    assert not turn.tools
    assert isinstance(
        chat_tools.tool_args("read_webpage", {"url": " https://example.com ", "start": "bad"}), web_search.ReadWebpage
    )
