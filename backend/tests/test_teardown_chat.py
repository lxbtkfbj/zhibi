"""拆书第一批：群聊、私聊和工具降级都只读，模板文字和原文资料有证据。"""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import event, select

from app.config import get_settings
from app.llm import demo
from app.llm.router import LLMRouter, ToolCall, ToolsUnsupported
from app.main import create_app
from app.models import (
    Book,
    BookSave,
    Chapter,
    Character,
    LlmCall,
    MeetingMessage,
    Memory,
    SettingSuggestion,
    Volume,
)
from app.prompts import catalog, default_content
from app.services import chat_agent, chat_tools, group_notes, teardown_chat
from app.services.chat import stop_key
from app.services.chat_context import reply_values


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


async def seed(sessionmaker, *, source="teardown", settings=True):
    async with sessionmaker() as session:
        book = Book(
            title="原书",
            source=source,
            status="ready",
            teardown={"stage": "imported", "author": "原作者", "original_volumes": True, "split": {"chars": 15000}}
            if source == "teardown"
            else {},
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="原书第一卷", status="done", chapter_count=2)
        session.add(volume)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=1,
                    title="出场",
                    content="茉莉在这里第一次出现。\n天毒珠闪了一下。",
                    word_count=20,
                    status="final",
                    source="imported",
                ),
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=2,
                    title="再见",
                    content="茉莉再一次看见天毒珠，茉莉说话了。",
                    word_count=18,
                    status="final",
                    source="imported",
                ),
            ]
        )
        if settings:
            session.add(Character(book_id=book.id, name="茉莉", personality="谨慎", aliases=[]))
        await session.commit()
        return book.id


async def snapshot(sessionmaker, bid):
    async with sessionmaker() as session:
        return {
            model.__tablename__: [
                dict(row)
                for row in (
                    await session.execute(
                        select(model.__table__).where((model.id if model is Book else model.book_id) == bid)
                    )
                ).mappings()
            ]
            for model in (Book, Volume, Chapter, Character, Memory, SettingSuggestion, BookSave)
        }


async def say(client, bid, text, **extra):
    response = await client.post(f"/api/books/{bid}/notes", json={"content": text, **extra})
    assert response.status_code == 201, response.text
    rows = (await client.get(f"/api/books/{bid}/meeting?limit=2000")).json()
    note = next(row for row in rows if row["id"] == response.json()["id"])
    reply = next(row for row in rows if row["payload"].get("reply_to") == [note["id"]])
    assert reply["kind"] == "speech" and reply["content"] and "state" not in reply["payload"], reply
    assert not any(row["kind"] == "plan" for row in rows)
    assert not note["payload"].get("steps")
    assert note["payload"]["outcome"]["kind"] == "chat"
    return note, reply


def forbidden(*args, **kwargs):
    pytest.fail("拆的书不许分流、改书或自动存档")


@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("text", ["把茉莉的性格改成勇敢，记住以后多写对话", "总结一下", "按这个来", "存个档"])
async def test_every_group_message_is_read_only(client, sessionmaker, monkeypatch, tools, text):
    monkeypatch.setattr(demo, "FAKE_TOOLS", tools)
    monkeypatch.setattr(group_notes, "classify", forbidden)
    monkeypatch.setattr(group_notes, "apply_with_change", forbidden)
    monkeypatch.setattr("app.services.book_saves.before_ai", forbidden)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    note, reply = await say(client, bid, text)
    assert note["payload"]["ask_only"] is True
    assert (note["payload"].get("turn") == "tools") is tools
    assert "拆的书里编辑部只回答问题" in reply["content"]
    assert await snapshot(sessionmaker, bid) == before
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))
    assert calls
    for call in calls:
        assert "chat_teardown" in call.request["prompt_names"]
        assert "chat_agent" not in call.request["prompt_names"] and "chat_reply" not in call.request["prompt_names"]
        assert teardown_chat.PROGRESS in call.request["user"]
        lookup = teardown_chat.LOOKUP_TOOLS if tools else teardown_chat.LOOKUP_PLAIN
        assert lookup in call.request["system"] and lookup not in call.request["user"]
        assert "已定稿" not in call.request["user"] and "正在写：" not in call.request["user"]
        if tools:
            assert not {"make_changes", "read_skill"} & {tool["function"]["name"] for tool in call.request["schema"]}


@pytest.mark.parametrize("role", ["chief", "lorekeeper", "writer", "reviewer"])
async def test_private_plan_and_change_requests_only_answer(client, sessionmaker, monkeypatch, role):
    monkeypatch.setattr(group_notes, "classify", forbidden)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    _, reply = await say(client, bid, "总结一下，把茉莉的性格改成勇敢", to=role)
    assert reply["speaker"] == role and reply["payload"]["thread"] == role
    assert await snapshot(sessionmaker, bid) == before
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid))
    assert "chat_teardown" in call.request["prompt_names"]
    if role == "chief":
        assert "照你的角色说话：" not in call.request["system"]
    else:
        focus = "照你的角色说话：" + teardown_chat.ROLE_FOCUS[role]
        assert focus in call.request["system"] and focus not in call.request["user"]


async def test_unsupported_tools_never_fall_back_to_classification(client, sessionmaker, monkeypatch):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr(group_notes, "classify", forbidden)
    monkeypatch.setattr(group_notes, "apply_with_change", forbidden)

    async def refuse(self, *args, **kwargs):
        raise ToolsUnsupported("演示拒绝工具")
        yield  # pragma: no cover

    monkeypatch.setattr(LLMRouter, "tool_rounds", refuse)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    await say(client, bid, "把茉莉的性格改成勇敢")
    assert await snapshot(sessionmaker, bid) == before
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid))
    assert "chat_teardown" in call.request["prompt_names"] and teardown_chat.LOOKUP_PLAIN in call.request["system"]


@pytest.mark.parametrize("tools", [False, True])
async def test_demo_searches_original_and_again_stays_read_only(client, sessionmaker, monkeypatch, tools):
    monkeypatch.setattr(demo, "FAKE_TOOLS", tools)
    monkeypatch.setattr(group_notes, "classify", forbidden)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    _, reply = await say(client, bid, "「茉莉」第一次出场在第几章")
    assert "第一次在第 1 章" in reply["content"]
    if tools:
        assert all(item["kind"] == "query" for item in reply["payload"]["tools"])
    response = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
    assert response.status_code == 202, response.text
    assert await snapshot(sessionmaker, bid) == before
    async with sessionmaker() as session:
        again = await session.get(MeetingMessage, reply["id"])
        assert again.content and "state" not in again.payload
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid)))
    assert all("chat_teardown" in call.request["prompt_names"] for call in calls)


async def test_forced_mutating_tool_is_rejected_even_if_model_ignores_schema(client, sessionmaker, monkeypatch):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr(chat_agent, "act", forbidden)

    async def malicious(self, role, system, user, specs, run, **kwargs):
        assert "make_changes" not in [spec["function"]["name"] for spec in specs]
        result = await run(ToolCall("bad", "make_changes", {"items": [{"kind": "改简介", "instruction": "多写对话"}]}))
        assert "不能动手" in result
        yield "text", "只回答，没有改书。"

    monkeypatch.setattr(LLMRouter, "tool_rounds", malicious)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    await say(client, bid, "多写对话")
    assert await snapshot(sessionmaker, bid) == before


@pytest.mark.parametrize("tools", [False, True])
async def test_stopping_either_path_keeps_partial_reply_and_never_changes_book(
    client, sessionmaker, monkeypatch, tools
):
    monkeypatch.setattr(demo, "FAKE_TOOLS", tools)
    bid = await seed(sessionmaker)
    before = await snapshot(sessionmaker, bid)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)

    async def pause():
        async with sessionmaker() as session:
            reply = await session.scalar(
                select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "chief")
            )
        await redis.set(stop_key(reply.id), "1", ex=60)
        await asyncio.sleep(1)

    async def stream(self, *args, **kwargs):
        yield "先核对原文。"
        await pause()

    async def rounds(self, *args, **kwargs):
        yield "text", "先核对原文。"
        await pause()

    monkeypatch.setattr(LLMRouter, "tool_rounds" if tools else "stream_text", rounds if tools else stream)
    try:
        response = await client.post(f"/api/books/{bid}/notes", json={"content": "聊聊剧情"})
        assert response.status_code == 201, response.text
        async with sessionmaker() as session:
            reply = await session.scalar(
                select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "chief")
            )
        # 工具路径现有 stop_text 在保留的回答后加空行；展示文字和停止语义不受影响。
        assert reply.content.strip() == "先核对原文。" and reply.payload["state"] == "stopped"
        assert not await redis.exists(stop_key(reply.id))
        assert await snapshot(sessionmaker, bid) == before
    finally:
        await redis.aclose()


async def test_values_exact_copy_and_fallback_materials(sessionmaker):
    bid = await seed(sessionmaker, settings=False)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        message = SimpleNamespace(content='第二章，「茉莉」、“天毒珠”、『不存在』、"第四个"', payload={})
        plain = await teardown_chat.values(session, book, "chief", message, [], "", tools=False)
        assert (
            plain["book_info"]
            == "书名：《原书》（原作者：原作者）\n导入了 2 章，共 2 万字；原书分了 1 卷。\n还没开拆：只有原文，章纲、单元、设定都还没有。"
        )
        assert plain["outline"] == "第 1 卷「原书第一卷」：第 1 到 2 章，还没拆出章纲。"
        assert plain["library"] == "（还没拆出设定）"
        assert plain["related"].startswith("<和这次的话有关的资料>\n第 2 章《再见》")
        assert "原文片段：茉莉再一次看见" in plain["related"]
        assert "原文里没有「不存在」。" in plain["related"] and "第四个" not in plain["related"]
        assert "「茉莉」在 2 章里出现过" in plain["related"]
        tools = await teardown_chat.values(session, book, "chief", message, [], "", tools=True)
        assert tools["related"] == "" and tools["lookup"] == teardown_chat.LOOKUP_TOOLS
        plain = await teardown_chat.values(
            session, book, "chief", SimpleNamespace(content="随便聊聊", payload={}), [], "", tools=False
        )
        assert plain["related"] == "<和这次的话有关的资料>\n（没找到）\n</和这次的话有关的资料>"


async def test_context_defers_whole_book_but_explicit_chapter_reads_work(sessionmaker):
    bid = await seed(sessionmaker, source="new")
    statements = []
    async with sessionmaker() as session:
        engine = session.bind.sync_engine

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            book = await session.get(Book, bid)
            note = SimpleNamespace(id=1, content="第二章说了什么", payload={}, speaker="author")
            result = await reply_values(session, book, "group", "writer", [note], [note], "")
        finally:
            event.remove(engine, "before_cursor_execute", record)
    assert "原文片段：茉莉再一次看见" in result["related"]
    assert "<最近定稿一章的结尾>\n茉莉再一次看见" in result["extras"]
    chapter_lists = [sql for sql in statements if "SELECT chapters.book_id" in sql or "SELECT chapters.id," in sql]
    assert chapter_lists and all("chapters.content" not in sql for sql in chapter_lists)
    assert any("SELECT chapters.content" in sql for sql in statements)


def test_prompt_bytes_catalog_and_program_text_match_task():
    # 主编口吻和分层 §1：锁定作者认可的拆书聊天系统提示。
    assert (
        hashlib.sha256(default_content("chat_teardown").encode()).hexdigest()
        == "59ad3604d01a6f5aa5df625e070c922432dcdc1c09362093c0148399b5b9f38b"
    )
    assert catalog.entry("chat_teardown")[-1] == "拆的书里的群聊，这一路的开场和规矩：只答不改、怎么查资料"
    assert [item["name"] for item in catalog.variables("chat_teardown")] == [
        "lookup",
        "role_focus",
    ]
    task = (Path(__file__).resolve().parents[2] / "docs/codex任务/拆书第一批/1-后台-导入和只读.md").read_text(
        encoding="utf-8"
    )
    for text in [teardown_chat.PROGRESS, *teardown_chat.ROLE_FOCUS.values()]:
        assert text in task
    layering_task = (
        Path(__file__).resolve().parents[2] / "docs/codex任务/主编口吻和分层/1-主编口吻和聊天分层.md"
    ).read_text(encoding="utf-8")
    for text in [teardown_chat.LOOKUP_TOOLS, teardown_chat.LOOKUP_PLAIN]:
        assert text in layering_task
    assert teardown_chat.quoted_words('「一」“二”『三』"四"') == ["一", "二", "三"]
    assert teardown_chat.quoted_words("「」“" + "长" * 31 + '”『一』"一"') == ["一"]


async def test_shared_search_preserves_author_book_no_hit_wording(sessionmaker):
    bid = await seed(sessionmaker, source="new")
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert await chat_tools.search_text(session, book, "没有的词") == "写出来的正文里没有「没有的词」。"


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("imported", "还没开拆：只有原文，章纲、单元、设定都还没有。"),
        ("queued", "正在拆：前 2 章有章纲，归成了 1 个单元、1 卷；后面的还没拆，设定还没整理。"),
        ("running", "正在拆：前 2 章有章纲，归成了 1 个单元、1 卷；后面的还没拆，设定还没整理。"),
        ("stopped", "拆到第 3 章停下了：前 2 章有章纲，归成了 1 个单元、1 卷；后面的还没拆，设定还没整理。"),
        ("done", "拆完了：每章都有章纲，归成了 1 个单元、1 卷；设定还没整理。"),
    ],
)
def test_second_batch_book_info_exact_progress(stage, expected):
    book = SimpleNamespace(title="原书", teardown={"stage": stage, "original_volumes": False, "open_volume_id": "v2"})
    chapters = [
        SimpleNamespace(index=i, word_count=10, teardown={"read_version": 1} if i in (1, 3) else {})
        for i in range(1, 4)
    ]
    volumes = [
        SimpleNamespace(id="v1", title="已经收尾"),
        SimpleNamespace(id="v2", title="旧占位名"),
        SimpleNamespace(id="v3", title=""),
    ]
    text = teardown_chat.book_info(book, chapters, volumes, [object()])
    assert text.splitlines()[-1] == expected
    assert "原书没有分卷" in text
    book.teardown.update(original_volumes=True, open_volume_id=None)
    assert "原书分了 3 卷" in teardown_chat.book_info(book, chapters, volumes)


def test_second_batch_outline_adds_ungrouped_range_in_each_volume():
    ctx = SimpleNamespace(
        volumes=[
            SimpleNamespace(id="v1", index=1, title="第一卷", summary="已经完成。"),
            SimpleNamespace(id="v2", index=2, title="旧占位名", summary=""),
        ],
        units=[SimpleNamespace(volume_id="v1", index=1, title="初来乍到", summary="原文事件。")],
    )
    chapters = [
        SimpleNamespace(volume_id="v1", index=1, unit_id="u1"),
        SimpleNamespace(volume_id="v1", index=2, unit_id=None),
        SimpleNamespace(volume_id="v2", index=3, unit_id=None),
        SimpleNamespace(volume_id="v2", index=4, unit_id=None),
    ]
    text = teardown_chat.outline_of(ctx, chapters, full=True, open_volume_id="v2")
    assert (
        text
        == "第 1 卷「第一卷」：已经完成。\n  单元 1「初来乍到」：原文事件。\n第 2 到 2 章还没归单元。\n第 2 卷「还没收尾」：\n第 3 到 4 章还没归单元。"
    )


async def test_read_chapter_tool_includes_teardown_outline_and_summary(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 1))
        chapter.outline = {
            "goal": "茉莉出现",
            "scenes": ["天毒珠闪光"],
            "cool_point": "揭秘：人物出现",
            "hook": "期待：茉莉是谁",
        }
        chapter.summary = "茉莉在这里第一次出现，天毒珠闪光。"
        await session.flush()
        text = await chat_tools.chapter_text(session, book, chat_tools.ReadChapter(index=1, original=True))
        assert "发生什么：茉莉出现\n天毒珠闪光" in text
        assert "看点：揭秘：人物出现" in text and "结尾钩子：期待：茉莉是谁" in text
        assert "摘要：茉莉在这里第一次出现，天毒珠闪光。" in text
        assert "原文（" in text
