"""第三包任务 6：不误记、不误改、范围与聊天上下文的回归合同。"""

import ast
import asyncio
import hashlib
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.agents.context import format_requirements
from app.api import jobs as jobs_api
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import (
    AuthorRequirement,
    Book,
    Chapter,
    Character,
    ChatThread,
    Foreshadowing,
    Job,
    MeetingMessage,
    PlotUnit,
    Secret,
    SettingSuggestion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.services import chat, group_notes
from app.services.chat_context import (
    dialogue,
    dialogue_text,
    extras_of,
    load_context,
    pending_of,
    progress_of,
    references,
    related_of,
)
from app.services.requirements import active_requirements, add_requirement, requirement_text
from app.services.writing_context import requirements_of
from tests.later_changes import with_later_changes


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await app.state.redis.aclose()


async def final_message(client, bid, mid):
    return next(m for m in (await client.get(f"/api/books/{bid}/meeting?limit=2000")).json() if m["id"] == mid)


async def seed(sm, state="idle", kind="write_book"):
    async with sm() as session:
        book = Book(
            title="聊天测试",
            status="ready",
            concept={"story": "楚风找回青灯。", "target_length": 30, "chapter_words": 3000},
        )
        session.add(book)
        await session.flush()
        session.add_all(
            [
                Character(book_id=book.id, name="楚风", role_type="主角", abilities="凝气境", aliases=["小风"]),
                WorldEntry(book_id=book.id, name="境界", category="等级体系", content="灵海纳百川。", style="ladder"),
            ]
        )
        if state != "idle":
            session.add(
                Job(
                    book_id=book.id,
                    thread_id=str(uuid.uuid4()),
                    kind=kind,
                    status=state,
                    params={"flow": 3},
                    pending={"kind": "volume_review", "volume": 1} if state == "waiting_author" else None,
                )
            )
        await session.commit()
        return book.id


@pytest.mark.parametrize("state", ["idle", "running", "queued", "waiting_author"])
@pytest.mark.parametrize("role", ["chief", "lorekeeper", "writer", "reviewer"])
async def test_private_is_read_only_in_every_state(client, sessionmaker, state, role):
    bid = await seed(sessionmaker, state)
    r = await client.post(f"/api/books/{bid}/notes", json={"content": "把境界名称重想一下，下一章快一点", "to": role})
    assert r.status_code == 201, r.text
    assert r.json()["job_id"] is None and r.json()["payload"]["outcome"] == {"kind": "chat"}
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(AuthorRequirement)))
        assert (await session.scalar(select(WorldEntry))).name == "境界"
        reply = await session.scalar(select(MeetingMessage).where(MeetingMessage.speaker == role))
        assert reply.payload["reply_to"] == [r.json()["id"]]
        assert reply.job_id is None


@pytest.mark.parametrize(
    "state,kind",
    [
        ("idle", "write_book"),
        ("running", "book_setup"),
        ("running", "write_book"),
        ("running", "rewrite_chapter"),
        ("waiting_author", "write_book"),
    ],
)
async def test_group_questions_never_become_feedback(client, sessionmaker, state, kind):
    bid = await seed(sessionmaker, state, kind)
    r = await client.post(f"/api/books/{bid}/notes", json={"content": "楚风现在什么境界？"})
    assert r.status_code == 201, r.text
    assert r.json()["payload"]["outcome"]["kind"] == "chat" and r.json()["job_id"] is None
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(AuthorRequirement)))
        reply = await session.scalar(select(MeetingMessage).where(MeetingMessage.speaker == "lorekeeper"))
        assert "楚风" in reply.content
        assert not (reply.payload or {}).get("thread")
        job = await session.scalar(select(Job))
        if job:
            assert job.status == state


@pytest.mark.parametrize("text", ["把境界名称重想一下", "下一章节奏快一点"])
async def test_waiting_changes_use_feedback_and_do_not_store(client, sessionmaker, text):
    bid = await seed(sessionmaker, "waiting_author")
    r = await client.post(f"/api/books/{bid}/notes", json={"content": text})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "use_feedback"
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(MeetingMessage)))
        assert not list(await session.scalars(select(AuthorRequirement)))


@pytest.mark.parametrize(
    "state,kind,outcome",
    [
        ("idle", "write_book", "requirement"),
        ("running", "book_setup", "to_job"),
        ("running", "write_book", "to_job"),
        ("running", "rewrite_chapter", "to_job"),
    ],
)
async def test_group_requirement_saved_once(client, sessionmaker, state, kind, outcome):
    bid = await seed(sessionmaker, state, kind)
    r = await client.post(f"/api/books/{bid}/notes", json={"content": "下一章节奏快一点"})
    assert r.status_code == 201, r.text
    assert r.json()["payload"]["outcome"]["kind"] == "pending"
    assert (await final_message(client, bid, r.json()["id"]))["payload"]["outcome"]["kind"] == outcome
    async with sessionmaker() as session:
        row = await session.scalar(select(AuthorRequirement))
        assert row.scope == "chapter" and row.chapter_index == 1 and row.message_id == r.json()["id"]


async def test_working_setting_suggestion_and_run(client, sessionmaker):
    bid = await seed(sessionmaker, "running")
    r = await client.post(f"/api/books/{bid}/notes", json={"content": "把境界名称重想一下"})
    final = await final_message(client, bid, r.json()["id"])
    assert final["payload"]["outcome"]["kind"] == "later"
    sid = final["payload"]["outcome"]["suggestion_id"]
    assert (await client.post(f"/api/suggestions/{sid}/run-chat")).status_code == 409
    async with sessionmaker() as session:
        job = await session.scalar(select(Job))
        job.status = "succeeded"
        await session.commit()
    result = await client.post(f"/api/suggestions/{sid}/run-chat")
    assert result.status_code == 200, result.text
    assert (await final_message(client, bid, result.json()["id"]))["payload"]["outcome"]["kind"] == "edit"
    async with sessionmaker() as session:
        assert (await session.scalar(select(SettingSuggestion))).status == "accepted"


async def test_scopes_expiry_and_no_prompt_leak(client, sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        volume = Volume(book_id=bid, index=1, title="一卷", status="planned")
        session.add(volume)
        await session.flush()
        session.add_all(
            [Chapter(book_id=bid, index=1, status="final"), Chapter(book_id=bid, index=2, status="planned")]
        )
        await session.flush()
        for text, scope in [
            ("永远", "always"),
            ("下一章", "next_chapter"),
            ("这卷", "this_volume"),
            ("下卷", "next_volume"),
        ]:
            await add_requirement(session, bid, text, scope=scope)
        await session.commit()
        rows = await active_requirements(session, bid)
        assert [(r.scope, r.chapter_index, r.volume_index) for r in rows] == [
            ("always", None, None),
            ("chapter", 2, None),
            ("volume", None, 1),
            ("volume", None, 2),
        ]
        assert "- （只管第 2 章）下一章" in format_requirements([requirement_text(r) for r in rows], [])
        chapter = await session.scalar(select(Chapter).where(Chapter.index == 2))
        chapter.status = "final"
        volume.status = "done"
        await session.commit()
        assert [r.text for r in await active_requirements(session, bid)] == ["永远", "下卷"]
        prompt = await requirements_of(await session.get(Book, bid), session)
        assert "下一章" not in prompt and "这卷" not in prompt
        await add_requirement(session, bid, "下一章", scope="next_chapter")
        await session.commit()
        assert next(r for r in await active_requirements(session, bid) if r.text == "下一章").chapter_index == 3
    rows = (await client.get(f"/api/books/{bid}/requirements")).json()
    assert len(rows) == 4 and any(r["label"] == "已过期 · 只管第 1 卷" for r in rows)


async def test_promote_chat_tidy_apply_and_conclusion(client, sessionmaker):
    bid = await seed(sessionmaker)
    msg = (await client.post(f"/api/books/{bid}/notes", json={"content": "楚风现在什么境界？"})).json()
    added = await client.post(
        f"/api/books/{bid}/requirements", json={"text": "主角是不是太弱了？", "message_id": msg["id"]}
    )
    assert added.status_code == 201, added.text
    await client.post(f"/api/books/{bid}/requirements", json={"text": "对主编：节奏快一点"})
    tidy = (await client.post(f"/api/books/{bid}/requirements/tidy")).json()["items"]
    assert [r["action"] for r in tidy] == ["删掉", "改写"]
    rows = (await client.get(f"/api/books/{bid}/requirements")).json()
    assert len(rows) == 2
    result = await client.post(
        f"/api/books/{bid}/requirements/apply",
        json={"delete": [tidy[0]["id"]], "rewrite": [{"id": tidy[1]["id"], "text": tidy[1]["rewrite"]}]},
    )
    assert [r["text"] for r in result.json()] == ["节奏快一点"]
    history = (await client.get(f"/api/books/{bid}/meeting")).json()
    assert history[0]["payload"]["outcome"]["kind"] == "requirement"
    await client.post(f"/api/books/{bid}/notes", json={"content": "就用这个写法", "to": "chief"})
    result = await client.post(f"/api/books/{bid}/chat/chief/conclude", json={"mode": "requirement"})
    assert result.status_code == 404  # 补丁 1 退役旧结论入口，统一走方案卡。


async def test_summary_reset_and_typing(client, sessionmaker):
    bid = await seed(sessionmaker)
    for i in range(17):
        r = await client.post(f"/api/books/{bid}/notes", json={"content": f"旧话题{i}", "to": "chief"})
        assert r.status_code == 201
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert "之前聊了 11 条" in state.summary
    await client.post(f"/api/books/{bid}/chat/chief/reset")
    await client.post(f"/api/books/{bid}/notes", json={"content": "新话题", "to": "chief"})
    async with sessionmaker() as session:
        state = await session.scalar(select(ChatThread))
        assert not state.summary
        rows = await dialogue(session, bid, "chief", state.reset_after)
        assert len(rows) == 2
        assert "旧话题" not in dialogue_text(rows)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    events = await redis.xrange(f"zhibi:events:{bid}")
    await redis.aclose()
    typing = [json.loads(e[1]["data"]) for e in events if e[1]["event"] == "chat_typing"]
    assert typing[0]["on"] and not typing[-1]["on"]


async def test_context_blocks_and_limits(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        ctx = await load_context(session, book)
        assert await progress_of(session, ctx, [], None) == "还没开写。"
        job = Job(kind="book_setup", status="running", pending={"piece": "settings"})
        assert "开书正在做：设定库" in await progress_of(session, ctx, [], job)
        c = Chapter(
            book_id=bid, index=2, title="青灯", status="final", summary="楚风拿到灯", content="楚风向前走。" * 100
        )
        session.add(c)
        await session.flush()
        assert "已定稿 1 章，全书计划约 100 章。" in await progress_of(session, ctx, [c], None)
        related = await related_of(session, ctx, [c], "小风的境界，第 二 章")
        assert "设定：" in related and "楚风" in related and "原文片段：" in related
        assert "【人物现在的状态】" in await extras_of(session, ctx, [c], "lorekeeper", "")
        assert "【最近定稿一章的结尾】" in await extras_of(session, ctx, [c], "writer", "")
        assert "【最近定稿的一章】" in await extras_of(session, ctx, [c], "reviewer", "")
        assert "【等你确认的内容】" in pending_of(
            Job(status="waiting_author", pending={"kind": "volume_review", "volume": 1}), ctx
        )
    assert references("第十一章 第 21 章 第两百零三章 第五章", "章", 3) == [11, 21, 203]
    rows = [SimpleNamespace(speaker="author", content=str(i) * 900) for i in range(20)]
    recent = dialogue_text(rows)
    assert len(recent) <= 6000 and "……" in recent


async def test_classification_failure_not_feedback(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker, "waiting_author")

    async def fail(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(502, "模型出错了：演示错误")

    monkeypatch.setattr(group_notes, "call_model", fail)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "下一章快一点"})
    assert result.status_code == 502
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(MeetingMessage)))
        assert not list(await session.scalars(select(AuthorRequirement)))


async def test_reply_error_and_summary_failure_dont_write_requirements(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)

    async def fail(book_id, role, template, **values):
        raise ValueError("演示错误")
        yield ""

    # 第五步起回答边写边显示：没答上来记在这条回答上，给「重试」
    monkeypatch.setattr(chat, "stream_model", fail)
    await client.post(f"/api/books/{bid}/notes", json={"content": "为什么？", "to": "writer"})
    messages = (await client.get(f"/api/books/{bid}/meeting")).json()
    assert messages[-1]["speaker"] == "writer" and messages[-1]["content"] == ""
    assert messages[-1]["payload"]["state"] == "failed" and messages[-1]["payload"]["error"] == "演示错误"


def test_exact_templates_and_schema_contracts():
    root = Path(__file__).parents[2]
    hashes = json.loads(Path(__file__).with_name("chat_task6_prompt_hashes.json").read_text(encoding="utf-8"))
    for name, sha in hashes.items():
        if name == "chat_conclude":
            assert not (root / f"backend/app/prompts/{name}.md").exists()
            continue
        assert hashlib.sha256((root / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == sha
    task = with_later_changes((root / "docs/codex任务/第三包/6-和编辑部聊天.md").read_text(encoding="utf-8"))
    actual = ast.parse((root / "backend/app/agents/schemas.py").read_text(encoding="utf-8"))
    for block in re.findall(r"```python\n(.*?)```", task, re.S):
        if not block.startswith("class "):
            continue
        for cls in ast.parse(block).body:
            if cls.name == "ChatConclusion":
                assert not hasattr(s, cls.name)
                continue
            same = next(c for c in actual.body if isinstance(c, ast.ClassDef) and c.name == cls.name)
            assert ast.dump(same) == ast.dump(cls)


async def test_scope_no_rows_all_done_and_duplicate_scope(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        a = await add_requirement(session, bid, "只此一条", scope="next_volume")
        assert a.volume_index == 2
        b = await add_requirement(session, bid, "只此一条", scope="next_chapter")
        assert b.id == a.id and b.chapter_index == 1 and b.volume_index is None
        session.add_all(
            [Chapter(book_id=bid, index=5, status="final"), Volume(book_id=bid, index=3, title="第三卷", status="done")]
        )
        await session.flush()
        await add_requirement(session, bid, "新章", scope="next_chapter")
        await add_requirement(session, bid, "当前卷", scope="this_volume")
        await add_requirement(session, bid, "后卷", scope="next_volume")
        states = {r.text: r for r in await active_requirements(session, bid)}
        assert states["新章"].chapter_index == 6
        assert states["当前卷"].volume_index == 4 and states["后卷"].volume_index == 5


async def test_idle_edit_instruction_revert_and_not_found(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)

    async def intent(*args, **kwargs):
        return s.LibraryIntent(
            kind="改设定", target_name="境界", part="一段话", mode="照作者的意思改", instruction="加一条代价"
        )

    monkeypatch.setattr(group_notes, "call_model", intent)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "境界加代价"})
    outcome = (await final_message(client, bid, result.json()["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "edit" and outcome["revert_version_id"]
    for _ in range(2):
        response = await client.post(f"/api/versions/{outcome['revert_version_id']}/revert")
        assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        assert (await session.scalar(select(WorldEntry))).content == "灵海纳百川。"

    async def missing(*args, **kwargs):
        return s.LibraryIntent(kind="改设定", target_name="不存在")

    monkeypatch.setattr(group_notes, "call_model", missing)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "不存在换一个"})
    assert (await final_message(client, bid, result.json()["id"]))["payload"]["outcome"]["kind"] == "not_found"


async def test_background_batches_unanswered_with_serial_lock(client, sessionmaker, monkeypatch):
    from fastapi import BackgroundTasks

    from app.schemas import NoteIn

    bid = await seed(sessionmaker)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    tasks = []
    for text in ("先问境界", "再问楚风"):
        async with sessionmaker() as session:
            background = BackgroundTasks()
            data = await jobs_api.add_note(
                NoteIn(content=text, to="lorekeeper"), background, await session.get(Book, bid), session, redis
            )
            assert data.job_id is None
            tasks.append(background)
    await asyncio.gather(*(task() for task in tasks))
    async with sessionmaker() as session:
        replies = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.speaker == "lorekeeper")))
        assert len(replies) == 1 and len(replies[0].payload["reply_to"]) == 2
    await redis.aclose()


async def test_summary_failure_uses_old_summary(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add(ChatThread(book_id=bid, thread="chief", summary="旧摘要"))
        for i in range(32):
            session.add(
                MeetingMessage(
                    book_id=bid,
                    speaker="author" if i % 2 == 0 else "chief",
                    kind="note" if i % 2 == 0 else "speech",
                    content=f"前话{i}",
                    payload={"thread": "chief", "reply_to": [i]}
                    if i % 2
                    else {"thread": "chief", "outcome": {"kind": "chat"}},
                )
            )
        await session.commit()
    original = chat.model
    seen = []

    async def model(book_id, role, schema, template, **values):
        if schema is s.ChatSummary:
            raise ValueError("摘要失败")
        return await original(book_id, role, schema, template, **values)

    async def stream(book_id, role, template, **values):
        seen.append(values["summary"])
        yield "接着说。"

    monkeypatch.setattr(chat, "model", model)
    monkeypatch.setattr(chat, "stream_model", stream)
    await client.post(f"/api/books/{bid}/notes", json={"content": "接着聊", "to": "chief"})
    messages = (await client.get(f"/api/books/{bid}/meeting")).json()
    assert messages[-1]["speaker"] == "chief" and messages[-1]["content"] == "接着说。"
    assert seen == ["旧摘要"]


async def test_tidy_missing_items_keep_and_false_conclusion(client, sessionmaker, monkeypatch):
    from app.services import chat_plans

    bid = await seed(sessionmaker)
    await client.post(f"/api/books/{bid}/requirements", json={"text": "不能删"})

    async def missing(*args, **kwargs):
        return s.RequirementsTidy(items=[])

    monkeypatch.setattr(chat, "model", missing)
    response = await client.post(f"/api/books/{bid}/requirements/tidy")
    assert response.json()["items"][0]["action"] == "保留"

    async def no_plan(*args, **kwargs):
        return s.ChatPlan(title="空方案", summary="没有结论")

    monkeypatch.setattr(chat_plans, "model", no_plan)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "总结一下", "to": "chief"})
    assert result.status_code == 201
    rows = (await client.get(f"/api/books/{bid}/meeting")).json()
    assert not any(m["kind"] == "plan" for m in rows)
    assert any(m["content"] == "前面还没聊出要落实的东西。想好了再叫我总结。" for m in rows)


def test_migration_roundtrip_and_unique_thread():
    import psycopg
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.downgrade(cfg, "0014")
    bid = uuid.uuid4()
    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO books(id,title,source,idea,style_reference,genre,concept,world,spine,status,trial_read_done) VALUES(%s,'旧书','imported','','','', '{}','{}','{}','ready',false)",
            [bid],
        )
        conn.execute(
            "INSERT INTO author_requirements(id,book_id,text,source) VALUES(%s,%s,'旧要求','private:chief')",
            [uuid.uuid4(), bid],
        )
    command.upgrade(cfg, "0015")
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute(
            "SELECT scope,chapter_index,volume_index,message_id FROM author_requirements"
        ).fetchone() == ("always", None, None, None)
        conn.execute("INSERT INTO chat_threads(id,book_id,thread) VALUES(%s,%s,'chief')", [uuid.uuid4(), bid])
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO chat_threads(id,book_id,thread) VALUES(%s,%s,'chief')", [uuid.uuid4(), bid])
    command.downgrade(cfg, "0014")
    command.upgrade(cfg, "0015")
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT text,scope FROM author_requirements").fetchone() == ("旧要求", "always")
    # 后面的测试要用最新的表
    command.upgrade(cfg, "head")


async def test_related_all_blocks_role_extras_pending_and_dialogue_filters(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        arc = StoryNode(
            book_id=bid,
            position=1,
            kind="milestone",
            title="起步终点",
            event="赢下大比",
            segment={"title": "青灯起步", "text": "这一篇追查旧案"},
        )
        session.add(arc)
        await session.flush()
        for i in range(1, 5):
            v = Volume(
                book_id=bid, index=i, title=f"卷{i}", summary=f"卷概要{i}", target_node_id=arc.id, status="approved"
            )
            session.add(v)
            await session.flush()
            session.add(
                PlotUnit(
                    book_id=bid, volume_id=v.id, index=1, title=f"试炼{i}", summary=f"单元概要{i}", status="outlined"
                )
            )
        for i in range(1, 11):
            session.add(
                WorldEntry(
                    book_id=bid, name=f"甲物{i}号", aliases=[f"别称{i}号"], category="物品与功法", content=f"资料{i}"
                )
            )
        session.add_all(
            [
                Foreshadowing(book_id=bid, seq=3, kind="伏笔", description="灯的来历", status="planted"),
                Foreshadowing(book_id=bid, seq=2, kind="期待", description="旧案的答案", status="planted"),
                Secret(book_id=bid, seq=2, title="灯灵", truth="有人藏在灯里"),
            ]
        )
        for i in range(1, 5):
            session.add(
                Chapter(
                    book_id=bid,
                    index=i,
                    title=f"章{i}",
                    status="final",
                    summary=f"定稿摘要{i}",
                    content="青灯闪动，楚风握紧灯盏。",
                    review={
                        "review": {
                            "highlights": ["好看"],
                            "issues": [{"severity": "high", "problem": "问题", "suggestion": "改法"}],
                        }
                    },
                )
            )
        await session.flush()
        ctx = await load_context(session, await session.get(Book, bid))
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid).order_by(Chapter.index)))
        text = " ".join(
            [
                *(f"别称{i}号" for i in range(1, 11)),
                "第一章 第二章 第三章 第四章 第一卷 第二卷 第三卷 青灯起步 试炼1 看看F3和E2与S2",
            ]
        )
        related = await related_of(session, ctx, chapters, text)
        assert "资料8" in related and "资料9" not in related
        assert "第 3 章《章3》" in related and "第 4 章《章4》" not in related
        assert "卷概要2" in related and "卷概要3" not in related
        assert "第 1 篇「青灯起步」：这一篇追查旧案" in related
        assert "单元「试炼1」：单元概要1" in related
        assert "台账：" in related and "信息差：" in related and "S2" in related
        chief = await extras_of(session, ctx, chapters, "chief", "")
        assert all(h in chief for h in ["【正在写的这一篇】", "【正在写的这一卷】", "【还开着的期待】"])
        assert "（正在写）" in chief
        keeper = await extras_of(session, ctx, chapters, "lorekeeper", "")
        assert "【还藏着的信息差】" in keeper and "【还没收的伏笔】" in keeper
        review = await extras_of(session, ctx, chapters, "reviewer", "第一章")
        assert "第 1 章《章1》" in review and "审稿时的问题：" in review
        pitches = pending_of(
            Job(
                status="waiting_author",
                pending={
                    "kind": "setup_pitches",
                    "pitches": [{"name": "短版", "text": "故事", "titles": ["甲", "乙"]}],
                },
            ),
            ctx,
        )
        assert "1. 短版：故事（书名候选：甲、乙）" in pitches
        segment = pending_of(
            Job(
                status="waiting_author",
                pending={
                    "kind": "segment_review",
                    "flow": 3,
                    "plan": {"title": "下一篇", "text": "新故事"},
                    "split": {},
                },
            ),
            ctx,
        )
        assert "篇名：下一篇" in segment and "一段话：新故事" in segment
        session.add_all(
            [
                MeetingMessage(book_id=bid, speaker="chief", kind="speech", content="工作发言"),
                MeetingMessage(
                    book_id=bid, speaker="chief", kind="speech", content="聊天回答", payload={"reply_to": [1]}
                ),
                MeetingMessage(
                    book_id=bid, speaker="author", kind="note", content="私聊话", payload={"thread": "chief"}
                ),
                MeetingMessage(book_id=bid, speaker="system", kind="error", content="出错"),
                MeetingMessage(book_id=bid, speaker="author", kind="note", content="群聊话"),
            ]
        )
        await session.flush()
        assert [m.content for m in await dialogue(session, bid, "group")] == ["聊天回答", "群聊话"]
        assert [m.content for m in await dialogue(session, bid, "chief")] == ["私聊话"]


async def test_private_receipt_after_long_history_and_scope_only_patch(client, sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            MeetingMessage(book_id=bid, speaker="system", kind="status", content="旧消息") for _ in range(505)
        )
        await session.commit()
    message = (await client.post(f"/api/books/{bid}/notes", json={"content": "第一个单元换个对手"})).json()
    response = await client.post(f"/api/books/{bid}/chat/chief/receipt", json={"content": "第一个单元换个对手"})
    assert response.status_code == 200, response.text
    row = (await final_message(client, bid, message["id"]))["payload"]["outcome"]["requirement_id"]
    response = await client.patch(f"/api/requirements/{row}", json={"scope": "next_chapter"})
    assert response.status_code == 200 and response.json()["chapter_index"] == 1


async def test_setting_rewrite_rechecks_waiting_state_after_model(client, sessionmaker, monkeypatch):
    from app.api import library_ai

    bid = await seed(sessionmaker)
    original = library_ai.call_model

    async def started(book_id, role, schema, template, **values):
        result = await original(book_id, role, schema, template, **values)
        async with sessionmaker() as session:
            session.add(
                Job(
                    book_id=bid,
                    kind="write_book",
                    status="waiting_author",
                    thread_id="race-waiting",
                    pending={"kind": "volume_review", "volume": 1},
                )
            )
            await session.commit()
        return result

    monkeypatch.setattr(library_ai, "call_model", started)
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "把境界名称重想一下"})
    assert response.status_code == 201
    assert (await final_message(client, bid, response.json()["id"]))["payload"]["outcome"]["kind"] == "failed"
    async with sessionmaker() as session:
        assert (await session.scalar(select(WorldEntry))).name == "境界"
