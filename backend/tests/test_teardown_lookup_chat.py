"""查拆书只接新书群聊；演示、逐字回执、快照和重新回答的端到端合同。"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app.llm import demo
from app.llm.router import ToolCall
from app.models import Book, Chapter, Character, LlmCall, MeetingMessage
from app.services import chat_agent, chat_tools, teardown_lookup
from tests import test_handbooks
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed

client = test_handbooks.client

ESSENCE = {
    "upto": 1,
    "overview": {
        "genre": "玄幻复仇爽文。",
        "engine": "旧账推动下一场。",
        "points": [
            {
                "title": "因果接力：旧账引出新局",
                "steps": ["立下旧账", "兑现前立新因"],
                "evidence": "第一章旧账重提。",
                "note": "不搬人名。",
                "chapters": [1],
            }
        ],
    },
    "sections": {"setting": {"points": [], "missing": ["没有等级记录"]}},
}


async def reference(sm):
    async with sm() as session:
        book = Book(
            title="逆天邪神",
            source="teardown",
            status="ready",
            teardown={"essence": deepcopy(ESSENCE), "waits": {"upto": 1, "total": 0}},
        )
        session.add(book)
        await session.flush()
        session.add_all(
            [
                Chapter(book_id=book.id, index=1, title="开局", content="茉莉出场。", status="final"),
                Character(book_id=book.id, name="茉莉", aliases=["小茉莉"], personality="毒舌"),
            ]
        )
        await session.commit()
        return book.id


@pytest.mark.parametrize("question", ["《逆天邪神》开局怎么写的", "《逆天邪神》开局怎么写的？"])
async def test_group_demo_and_again_keep_the_exact_material(client, sessionmaker, question):
    await reference(sessionmaker)
    bid = await seed(sessionmaker)
    note = await say(client, bid, question)
    reply = await reply_of(client, bid, note["id"])
    record = reply["payload"]["tools"][0]
    assert record["kind"] == "query" and record["label"] == "《逆天邪神》精髓「核心要点」"
    assert record["text"].startswith("《逆天邪神》精髓：拆书时从前 1 章整理的，章号是原书的。")
    assert "第一章旧账重提。" in record["text"]
    assert "翻了《逆天邪神》的精髓。" in reply["content"]
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))
        specs = {item["function"]["name"]: item["function"] for item in calls[0].request["schema"]}
        assert specs["look_up_teardown"]["parameters"]["properties"]["book"]["enum"] == ["逆天邪神"]
        assert record["text"] in calls[1].request["user"]
        if question.endswith("？"):
            assert note["payload"]["ask_only"] is True and "make_changes" not in specs
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 202
    async with sessionmaker() as session:
        last = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id.desc()))
        assert last.request["method"] == "demo_stream" and not last.request.get("schema")
        assert record["text"] in last.request["user"]


@pytest.mark.parametrize(
    "book,look,words,doing,label",
    [
        ("《逆 天邪神》", "精髓", ["设定设计"], "在翻《逆天邪神》的精髓……", "《逆天邪神》精髓「设定设计」"),
        ("逆天邪神", "设定", ["小茉莉"], "在查《逆天邪神》的设定……", "《逆天邪神》设定「茉莉」"),
        (
            "逆天邪神",
            "读者在等的事",
            ["下毒"],
            "在查《逆天邪神》读者在等的事……",
            "《逆天邪神》读者在等的事「下毒」",
        ),
        ("逆天邪神", "原文", ["茉莉", "第 1 章"], "在翻《逆天邪神》的原文……", "《逆天邪神》原文「茉莉」「第 1 章」"),
        ("没拆过", "精髓", [], "在查拆过的书……", "拆过的书「没拆过」"),
    ],
)
async def test_progress_and_query_record_are_verbatim(
    client, sessionmaker, monkeypatch, book, look, words, doing, label
):
    await reference(sessionmaker)
    bid = await seed(sessionmaker)
    original_doing, seen = chat_agent.set_doing, []

    async def capture(turn, text, **kwargs):
        await original_doing(turn, text, **kwargs)
        async with sessionmaker() as session:
            reply = await session.get(MeetingMessage, turn.reply_id)
            seen.append(reply.payload["doing"])

    def fake_turn(system, user, available, done):
        if not done:
            assert "look_up_teardown" in available
            return [("look_up_teardown", {"book": book, "look": look, "words": words})], ""
        return [], "（演示）查过了。"

    monkeypatch.setattr(chat_agent, "set_doing", capture)
    monkeypatch.setattr(demo, "tool_turn", fake_turn)
    note = await say(client, bid, "怎么写开局？")
    reply = await reply_of(client, bid, note["id"])
    assert seen == [doing]
    assert reply["payload"]["tools"][0]["label"] == label


@pytest.mark.parametrize("mode", ["teardown", "private", "legacy", "empty"])
async def test_excluded_routes_do_not_offer_the_tool(client, sessionmaker, monkeypatch, mode):
    if mode != "empty":
        await reference(sessionmaker)
    bid = await seed(sessionmaker)
    if mode == "teardown":
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            book.source = "teardown"
            await session.commit()
    if mode == "legacy":
        monkeypatch.setattr(demo, "FAKE_TOOLS", False)
    original_load, loads = teardown_lookup.load_catalog, []

    async def capture(session):
        loads.append(True)
        return await original_load(session)

    monkeypatch.setattr(teardown_lookup, "load_catalog", capture)
    await say(client, bid, "《逆天邪神》开局怎么写的？", **({"to": "chief"} if mode == "private" else {}))
    assert len(loads) == (1 if mode == "empty" else 0)
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid)))
        assert calls
        for call in calls:
            if call.request["method"] == "tools":
                assert "look_up_teardown" not in [spec["function"]["name"] for spec in call.request["schema"]]
            else:
                assert "《逆天邪神》精髓：" not in call.request["user"]


async def test_teardown_switch_rejects_even_malformed_calls(sessionmaker):
    bid = await seed(sessionmaker)
    turn = chat_agent.Turn(None, bid, 0, 0, "chief", True, None, allow_teardowns=False)
    assert await chat_agent.run_tool(turn, ToolCall("blocked", "look_up_teardown", {})) == (
        "拆的书群聊不能查别的拆过的书。"
    )
    assert not turn.tools


async def test_each_answer_freezes_catalog_and_mapping_until_next_answer(client, sessionmaker, monkeypatch):
    rid = await reference(sessionmaker)
    bid = await seed(sessionmaker)
    original_load, original_run = teardown_lookup.load_catalog, chat_agent.run_tool
    loads = []

    async def capture(session):
        result = await original_load(session)
        loads.append(result)
        return result

    async def mutate_before_lookup(turn, call):
        if call.name == "look_up_teardown" and len(loads) == 1:
            async with sessionmaker() as session:
                row = await session.get(Book, rid)
                row.title = "已经改名"
                row.teardown = {"essence": {**deepcopy(ESSENCE), "overview": {"points": []}}}
                await session.commit()
        return await original_run(turn, call)

    monkeypatch.setattr(teardown_lookup, "load_catalog", capture)
    monkeypatch.setattr(chat_agent, "run_tool", mutate_before_lookup)
    note = await say(client, bid, "《逆天邪神》开局怎么写的？")
    reply = await reply_of(client, bid, note["id"])
    assert len(loads) == 1
    assert reply["payload"]["tools"][0]["label"] == "《逆天邪神》精髓「核心要点」"
    assert "第一章旧账重提。" in reply["payload"]["tools"][0]["text"]
    await say(client, bid, "《已经改名》开局怎么写的？")
    assert len(loads) == 2 and not loads[-1]


def test_no_catalog_means_no_static_tool():
    assert all(spec["function"]["name"] != "look_up_teardown" for spec in chat_tools.tool_specs(True))
    assert isinstance(
        chat_tools.tool_args("look_up_teardown", {"book": "逆天邪神", "look": "精髓", "words": "开篇"}),
        teardown_lookup.LookUpTeardown,
    )
