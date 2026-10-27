"""聊天记性：编辑部回答时看到整段原话，太长了才把最早的缩进摘要；分流只看摘要以后的原话，不缩不存。"""

import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from alembic import command
from app.agents import schemas as s
from app.config import get_settings
from app.graphs import book_setup
from app.graphs.book_setup import _library_feedback
from app.llm import demo
from app.llm.router import LLMRouter, ToolsUnsupported
from app.main import create_app
from app.models import Book, ChatConversation, ChatThread, LlmCall, MeetingMessage
from app.services import chat, chat_agent, chat_context, chat_plans, group_notes
from app.services.chat_context import dialogue, dialogue_text, split_for_limit
from tests.test_chat_agent import messages, reply_of, say
from tests.test_chat_task6 import seed
from tests.test_teardown_chat import seed as seed_teardown

LONG = "旧回答开头" + "长" * 1500 + "旧回答结尾"


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


def line(speaker, content):
    return SimpleNamespace(speaker=speaker, content=content)


async def seed_private(sessionmaker, bid, pairs, summary=""):
    """主编私聊里已有的来回：pairs 是 [(作者的话, 主编的回答)]；返回按先后的消息 id"""
    ids = []
    async with sessionmaker() as session:
        if summary:
            session.add(ChatThread(book_id=bid, thread="chief", summary=summary))
        for ask, answer in pairs:
            note = MeetingMessage(
                book_id=bid,
                speaker="author",
                kind="note",
                content=ask,
                payload={"thread": "chief", "outcome": {"kind": "chat"}},
            )
            session.add(note)
            await session.flush()
            reply = MeetingMessage(
                book_id=bid,
                speaker="chief",
                kind="speech",
                content=answer,
                payload={"thread": "chief", "reply_to": [note.id]},
            )
            session.add(reply)
            await session.flush()
            ids += [note.id, reply.id]
        await session.commit()
    return ids


def ninety_four(label, i, char):
    """作者和主编的每一条正好 94 个字，加上「作者：」「主编：」是 97 个字一行"""
    return f"{label}{i:02d}" + char * 91


@pytest.fixture
def seen(monkeypatch):
    """记下每次真要发给主编的资料，回答固定说一句"""
    values = []

    async def stream(book_id, role, template, **given):
        values.append(given)
        yield "接着说。"

    monkeypatch.setattr(chat, "stream_model", stream)
    return values


@pytest.fixture
def summaries(monkeypatch):
    """记下每次叫设定师缩摘要时给了什么；fail 为真就让它失败"""
    calls = SimpleNamespace(given=[], fail=False)
    original = chat.model

    async def model(book_id, role, schema, template, **values):
        if schema is s.ChatSummary:
            calls.given.append(values)
            if calls.fail:
                raise ValueError("摘要失败")
            return s.ChatSummary(summary="新摘要")
        return await original(book_id, role, schema, template, **values)

    monkeypatch.setattr(chat, "model", model)
    return calls


async def ask_chief(client, bid, text):
    res = await client.post(f"/api/books/{bid}/notes", json={"content": text, "to": "chief"})
    assert res.status_code == 201, res.text


def test_dialogue_text_keeps_every_word():
    reply = "回" * 5000
    text = dialogue_text([line("author", "问"), line("chief", reply)])
    assert text == f"作者：问\n主编：{reply}" and "……" not in text
    assert dialogue_text([]) == "（没有）"


def test_split_for_limit_moves_whole_lines_and_keeps_the_last():
    rows = [line("author", "一" * 97) for _ in range(5)]  # 每行 100 个字
    assert len(dialogue_text(rows)) == 5 * 100 + 4
    moved, rest = split_for_limit(rows, 504)  # 正好等于上限，一条也不挪
    assert (len(moved), len(rest)) == (0, 5)
    moved, rest = split_for_limit(rows, 403)  # 挪一条，剩下的 4 条正好等于上限
    assert (len(moved), len(rest)) == (1, 4) and len(dialogue_text(rest)) == 403
    moved, rest = split_for_limit(rows, 402)  # 差一个字，再挪一条
    assert (len(moved), len(rest)) == (2, 3)
    # 最后一条比上限还长：也留着
    moved, rest = split_for_limit(rows, 10)
    assert (len(moved), len(rest)) == (4, 1) and rest == rows[-1:]
    assert split_for_limit([], 10) == ([], [])


async def test_under_the_limit_nothing_is_folded_and_every_word_is_given(client, sessionmaker, seen, summaries):
    bid = await seed(sessionmaker)
    pairs = [(f"问{i:02d}" + "问" * 900, f"答{i:02d}" + "答" * 1500) for i in range(20)]
    await seed_private(sessionmaker, bid, pairs)
    await ask_chief(client, bid, "接着聊")
    assert summaries.given == []
    assert len(seen) == 1 and seen[0]["summary"] == "（没有）"
    expected = "\n".join(f"{who}：{text}" for pair in pairs for who, text in zip(("作者", "主编"), pair, strict=True))
    assert seen[0]["recent"] == expected and "……" not in seen[0]["recent"]
    assert len(seen[0]["recent"]) > 40_000
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert not state.summary and state.summarized_until == 0


async def test_over_the_limit_folds_the_oldest_once_then_stops(client, sessionmaker, monkeypatch, seen, summaries):
    monkeypatch.setattr(chat_context, "HISTORY_LIMIT", 2000)
    monkeypatch.setattr(chat_context, "HISTORY_KEEP", 1000)
    bid = await seed(sessionmaker)
    pairs = [(ninety_four("问", i, "问"), ninety_four("答", i, "答")) for i in range(12)]
    ids = await seed_private(sessionmaker, bid, pairs, summary="旧摘要")
    flat = [text for pair in pairs for text in pair]
    lines = [f"{who}：{text}" for who, text in zip(["作者", "主编"] * 12, flat, strict=True)]
    assert {len(x) for x in lines} == {97} and len("\n".join(lines)) == 24 * 97 + 23 > 2000

    await ask_chief(client, bid, "新问题")
    # 只缩一次，给设定师的是挪出来那 14 条（7 个来回）的全文，旧摘要也一起给
    assert len(summaries.given) == 1
    assert summaries.given[0]["messages"] == "\n".join(lines[:14]) and summaries.given[0]["summary"] == "旧摘要"
    # 这一次：新摘要加剩下的 10 条原话，从挪完以后那一条开始，不超过 HISTORY_KEEP
    assert seen[0]["summary"] == "新摘要" and seen[0]["recent"] == "\n".join(lines[14:])
    assert len(seen[0]["recent"]) <= chat_context.HISTORY_KEEP
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert (state.summary, state.summarized_until) == ("新摘要", ids[13])

    # 下一次回答原话没再超过上限：不再缩，摘要照旧
    await ask_chief(client, bid, "再问一句")
    assert len(summaries.given) == 1
    assert seen[1]["summary"] == "新摘要" and seen[1]["recent"].startswith("\n".join(lines[14:]))
    assert "新问题" in seen[1]["recent"] and "接着说。" in seen[1]["recent"]


async def test_failed_fold_keeps_the_old_summary_and_asks_again_next_time(
    client, sessionmaker, monkeypatch, seen, summaries
):
    monkeypatch.setattr(chat_context, "HISTORY_LIMIT", 2000)
    monkeypatch.setattr(chat_context, "HISTORY_KEEP", 1000)
    summaries.fail = True
    bid = await seed(sessionmaker)
    pairs = [(ninety_four("问", i, "问"), ninety_four("答", i, "答")) for i in range(12)]
    await seed_private(sessionmaker, bid, pairs, summary="旧摘要")
    flat = [text for pair in pairs for text in pair]
    lines = [f"{who}：{text}" for who, text in zip(["作者", "主编"] * 12, flat, strict=True)]

    await ask_chief(client, bid, "新问题")
    reply = (await messages(client, bid))[-1]
    assert reply["speaker"] == "chief" and reply["content"] == "接着说。" and "state" not in reply["payload"]
    # 缩失败了：沿用旧摘要，这一次只给剩下的 10 条，库里什么也没存
    assert len(summaries.given) == 1
    assert seen[0]["summary"] == "旧摘要" and seen[0]["recent"] == "\n".join(lines[14:])
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert (state.summary, state.summarized_until) == ("旧摘要", 0)

    # 下一次回答再缩一次，这回成了
    summaries.fail = False
    await ask_chief(client, bid, "再问一句")
    assert len(summaries.given) == 2
    assert summaries.given[1]["messages"].startswith(lines[0]) and summaries.given[1]["summary"] == "旧摘要"
    assert seen[1]["summary"] == "新摘要"
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert state.summary == "新摘要" and state.summarized_until > 0


async def test_failed_fold_in_the_agent_route_still_answers(client, sessionmaker, monkeypatch, summaries):
    monkeypatch.setattr(chat_context, "HISTORY_LIMIT", 100)
    monkeypatch.setattr(chat_context, "HISTORY_KEEP", 50)
    summaries.fail = True
    bid = await seed(sessionmaker)
    for i in range(6):
        note = await say(client, bid, f"第{i}个问题是什么？")
        reply = await reply_of(client, bid, note["id"])
        assert reply["content"].startswith("（演示）") and "state" not in reply["payload"]
    assert summaries.given


async def test_one_giant_line_is_never_folded_away(client, sessionmaker, monkeypatch, seen, summaries):
    monkeypatch.setattr(chat_context, "HISTORY_LIMIT", 500)
    monkeypatch.setattr(chat_context, "HISTORY_KEEP", 300)
    bid = await seed(sessionmaker)
    await seed_private(sessionmaker, bid, [("问一句", "答" * 2000)])
    await ask_chief(client, bid, "新问题")
    # 缩完剩下的只有最后一条，它比 HISTORY_KEEP 还长，也整条留着
    assert len(summaries.given) == 1 and summaries.given[0]["messages"] == "作者：问一句"
    assert seen[0]["recent"] == "主编：" + "答" * 2000


# 第 1.2 节的六条路用的是同一套：每条路造一段对话，里面有一条超过 800 字的旧回答，调用记录里要有它的全文
ROUTES = ["agent", "fall_back", "private", "again", "teardown", "plan"]


async def lengthen_first_reply(sessionmaker, bid):
    async with sessionmaker() as session:
        reply = await session.scalar(
            select(MeetingMessage)
            .where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "chief", MeetingMessage.kind == "speech")
            .order_by(MeetingMessage.id)
        )
        reply.content = LONG
        await session.commit()


@pytest.mark.parametrize("route", ROUTES)
async def test_every_route_gives_the_whole_old_reply(client, sessionmaker, monkeypatch, route):
    folded = []
    for module in (chat, chat_agent, chat_plans):
        original = module.fold_history

        async def spy(*args, _original=original, **kwargs):
            folded.append(1)
            return await _original(*args, **kwargs)

        monkeypatch.setattr(module, "fold_history", spy)

    if route == "fall_back":

        async def refuse(self, *args, **kwargs):
            raise ToolsUnsupported("演示拒绝工具")
            yield  # pragma: no cover

        monkeypatch.setattr(LLMRouter, "tool_rounds", refuse)
    if route == "teardown":
        monkeypatch.setattr(demo, "FAKE_TOOLS", False)
        bid = await seed_teardown(sessionmaker)
    else:
        bid = await seed(sessionmaker)

    private = {"to": "chief"} if route in ("private", "again") else {}
    await say(client, bid, "楚风现在什么境界？", **private)
    await lengthen_first_reply(sessionmaker, bid)
    folded.clear()
    if route == "plan":
        await say(client, bid, "总结一下")
        purpose = "总结方案"
    else:
        second = await say(client, bid, "他的性格呢？", **private)
        purpose = "聊天·主编"
        if route == "again":
            folded.clear()
            reply = await reply_of(client, bid, second["id"])
            assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 202
    # 每条路都走了那一个函数（fall_back 先试自己动手一次，改走只说话的再来一次）
    assert len(folded) == (2 if route == "fall_back" else 1)
    async with sessionmaker() as session:
        calls = list(
            await session.scalars(
                select(LlmCall).where(LlmCall.book_id == bid, LlmCall.purpose == purpose).order_by(LlmCall.id)
            )
        )
        assert not [c for c in await session.scalars(select(LlmCall)) if "chat_summary" in c.request["prompt_names"]]
    assert calls and LONG in calls[-1].request["user"]
    assert "……" not in calls[-1].request["user"]


async def test_route_sees_only_what_comes_after_the_summary_and_never_folds(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "第一句话是什么？")
    conv_id = first["payload"]["conv"]
    for text in ("第二句话是什么？", "第三句话是什么？"):
        await say(client, bid, text, conv=conv_id)
    async with sessionmaker() as session:
        rows = await dialogue(session, bid, "group", conv=conv_id)
        # 假装前两个来回已经缩进摘要了（演示的回答会把问题抄一遍，所以连回答一起算）
        cut = rows[next(i for i, m in enumerate(rows) if m.content == "第二句话是什么？") + 1].id
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        conv.summary, conv.summarized_until = "已有的摘要", cut
        await session.commit()

    async def summary_forbidden(*args, **kwargs):
        raise AssertionError("分流不缩摘要")

    seen_recent = []

    async def route(book_id, role, schema, template, **values):
        seen_recent.append(values["recent"])
        return s.LibraryIntent(kind="提问闲聊")

    monkeypatch.setattr(chat, "model", summary_forbidden)
    monkeypatch.setattr(group_notes, "call_model", route)
    async with sessionmaker() as session:
        await group_notes.classify(session, bid, "新的话", None, conv_id)
        after = [m for m in rows if m.id > cut]
        assert seen_recent[0] == dialogue_text(after) and "第三句话是什么？" in seen_recent[0]
        assert "第一句话" not in seen_recent[0] and "第二句话" not in seen_recent[0]
        # 超过 HISTORY_KEEP：从最早的整条往后丢，只管这一次
        monkeypatch.setattr(chat_context, "HISTORY_KEEP", len(dialogue_text(after[-1:])) + 2)
        await group_notes.classify(session, bid, "新的话", None, conv_id)
        assert seen_recent[1] == dialogue_text(after[-1:])
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        assert (conv.summary, conv.summarized_until) == ("已有的摘要", cut)
        # 「before」：这句话已经存进对话了，只看它前面的
        await group_notes.classify(session, bid, "新的话", None, conv_id, before=after[-1].id)
        assert after[-1].content not in seen_recent[2]


async def test_setup_feedback_route_sees_only_what_comes_after_the_summary(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "第一句话是什么？")
    conv_id = first["payload"]["conv"]
    await say(client, bid, "第二句话是什么？", conv=conv_id)
    async with sessionmaker() as session:
        rows = await dialogue(session, bid, "group", conv=conv_id)
        cut = rows[next(i for i, m in enumerate(rows) if m.content == "第一句话是什么？") + 1].id
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        conv.summary, conv.summarized_until = "已有的摘要", cut
        await session.commit()

    async def summary_forbidden(*args, **kwargs):
        raise AssertionError("分流不缩摘要")

    monkeypatch.setattr(chat, "model", summary_forbidden)
    users = []

    async def structured(role, schema, system, user, **kwargs):
        users.append(user)
        return s.LibraryIntent(kind="提问闲聊")

    async def reviewed(*args, **kwargs):
        return None

    monkeypatch.setattr(book_setup, "_review", reviewed)
    d = SimpleNamespace(sessionmaker=sessionmaker, book_id=bid, llm=SimpleNamespace(structured=structured))
    await _library_feedback(d, "把境界改一改")
    assert len(users) == 1
    assert "第二句话是什么？" in users[0] and "第一句话是什么？" not in users[0]
    async with sessionmaker() as session:
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        assert (conv.summary, conv.summarized_until) == ("已有的摘要", cut)


@contextmanager
def database_at_0029(migration_database_urls):
    name = f"zhibi_chat_history_test_{uuid.uuid4().hex}"
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0029")
        yield config, engine
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_migration_0030_clears_old_summaries(migration_database_urls):
    with database_at_0029(migration_database_urls) as (config, engine):
        with Session(engine) as session:
            book = Book(title="旧书")
            session.add(book)
            session.flush()
            session.add_all(
                [
                    ChatConversation(book_id=book.id, title="第一段", summary="旧摘要一", summarized_until=57),
                    ChatConversation(book_id=book.id, title="第二段", summary="旧摘要二", summarized_until=90),
                    ChatThread(
                        book_id=book.id, thread="chief", summary="私聊摘要", summarized_until=40, reset_after=25
                    ),
                    ChatThread(book_id=book.id, thread="writer", summary="", summarized_until=0, reset_after=0),
                    ChatThread(
                        book_id=book.id, thread="reviewer", summary="审稿摘要", summarized_until=70, reset_after=70
                    ),
                ]
            )
            session.commit()
        command.upgrade(config, "0030")
        with engine.connect() as connection:
            convs = connection.execute(
                sa.text("SELECT title, summary, summarized_until FROM chat_conversations ORDER BY title")
            ).all()
            threads = connection.execute(
                sa.text("SELECT thread, summary, summarized_until, reset_after FROM chat_threads ORDER BY thread")
            ).all()
        assert [tuple(r) for r in convs] == [("第一段", "", 0), ("第二段", "", 0)]
        # 「换个话题」的分界不动，摘要从分界起重新算
        assert [tuple(r) for r in threads] == [
            ("chief", "", 25, 25),
            ("reviewer", "", 70, 70),
            ("writer", "", 0, 0),
        ]
        # 降级什么也不做，也不报错
        command.downgrade(config, "0029")
        command.upgrade(config, "0030")
