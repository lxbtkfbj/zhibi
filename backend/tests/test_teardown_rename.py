"""拆书中的书名是作者资料：单独改名可放行，后台保存不能覆盖。"""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import event, select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, Chapter, Job, Volume
from app.prompts import VARIABLE, default_content
from app.prompts import render as render_plain
from app.services import teardown_prompts
from app.services.teardown_runner import Runner


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


async def seed(sm, *, job_status="queued", stage="queued", count=8):
    async with sm() as session:
        book = Book(
            title="原书",
            source="teardown",
            status="writing",
            concept={"title": "原书"},
            teardown={"stage": stage, "original_volumes": False},
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="还没分卷", chapter_count=count, status="done")
        session.add(volume)
        await session.flush()
        book.teardown = {**book.teardown, "open_volume_id": str(volume.id)}
        for index in range(1, count + 1):
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=index,
                    title=f"原章{index}",
                    content=f"人物在第 {index} 章向前走。原书这两个字是正文，不能替换。",
                    status="final",
                    source="imported",
                )
            )
        job = Job(book_id=book.id, kind="teardown", status=job_status, thread_id=str(uuid.uuid4()))
        session.add(job)
        await session.commit()
        return book.id, job.id


@pytest.mark.parametrize(("job_status", "stage"), [("queued", "queued"), ("running", "running"), ("failed", "stopped")])
@pytest.mark.parametrize("controls", [{}, {"review_changes": False}])
async def test_title_only_allowed_in_queue_running_and_error(client, sessionmaker, job_status, stage, controls):
    bid, _ = await seed(sessionmaker, job_status=job_status, stage=stage)
    response = await client.patch(f"/api/books/{bid}", json={"title": "作者改的新名字", **controls})
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "作者改的新名字"
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == book.concept["title"] == "作者改的新名字"
        assert book.teardown["title_edited"] is True and book.teardown["stage"] == stage


@pytest.mark.parametrize(
    "change",
    [
        {"author": "原作者"},
        {"intro": "新简介"},
        {"style_reference": "文风"},
        {"concept": {"title": "不能绕过单独改名接口"}},
        {"title": "新名", "author": "原作者"},
        {"title": "新名", "intro": "新简介"},
        {"title": "新名", "style_reference": "文风"},
    ],
)
async def test_other_fields_still_require_idle(client, sessionmaker, change):
    bid, _ = await seed(sessionmaker, job_status="running", stage="running")
    response = await client.patch(f"/api/books/{bid}", json=change)
    assert response.status_code == 409 and response.json()["detail"] == "正在拆，点「停下」才能改"
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == "原书" and not book.teardown.get("title_edited")


@pytest.mark.parametrize("title", ["", " ", "\t\n"])
async def test_empty_title_is_not_saved_while_running(client, sessionmaker, title):
    bid, _ = await seed(sessionmaker, job_status="running", stage="running")
    response = await client.patch(f"/api/books/{bid}", json={"title": title})
    assert response.status_code == 422
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == "原书" and not book.teardown.get("title_edited")


async def test_rename_halfway_survives_all_worker_saves_and_later_context_uses_new_title(client, sessionmaker):
    bid, jid = await seed(sessionmaker)
    entered, resume = asyncio.Event(), asyncio.Event()
    calls = []

    class DemoRouter:
        async def structured(self, role, schema, system, user, *, purpose, teardown_policy):
            calls.append((schema, user))
            if schema is s.TeardownRead and not entered.is_set():
                entered.set()
                await asyncio.wait_for(resume.wait(), 10)
            return await demo.respond(schema, system, user)

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    task = asyncio.create_task(Runner(jid, sessionmaker, redis, DemoRouter()).run())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        response = await client.patch(f"/api/books/{bid}", json={"title": "作者的拆书副本", "review_changes": False})
        assert response.status_code == 200, response.text
        resume.set()
        await asyncio.wait_for(task, 30)
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            job = await session.get(Job, jid)
            assert book.title == book.concept["title"] == "作者的拆书副本"
            assert book.teardown["title_edited"] is True and book.teardown["stage"] == "done"
            assert job.status == "succeeded"
            chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid)))
            assert all("原书这两个字是正文，不能替换。" in chapter.content for chapter in chapters)
        reads = [user for schema, user in calls if schema is s.TeardownRead]
        assert len(reads) == 2 and "小说《原书》" in reads[0] and "小说《作者的拆书副本》" in reads[1]
        assert all("小说《原书》" not in user for _, user in calls[1:])
    finally:
        resume.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await redis.aclose()


async def test_cancel_queued_job_keeps_title_edited(client, sessionmaker):
    bid, jid = await seed(sessionmaker)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.params = {"previous_teardown": {"stage": "imported", "original_volumes": False}}
        await session.commit()
    assert (await client.patch(f"/api/books/{bid}", json={"title": "排队时的新书名"})).status_code == 200
    response = await client.post(f"/api/teardown/{bid}/stop")
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == "排队时的新书名"
        assert book.teardown["title_edited"] is True and book.teardown["stage"] == "imported"


@pytest.mark.parametrize("title", ["原书", " 《书》 {{title}} \n\n\n尾 ", " "])
def test_bound_title_prompt_matches_existing_render_byte_for_byte_including_retry_suffix(monkeypatch, title):
    monkeypatch.setattr("app.prompts._load", default_content)
    prompts = Path(__file__).resolve().parents[1] / "app/prompts"
    checked = []
    for path in prompts.glob("*.md"):
        template = path.read_text(encoding="utf-8")
        if "{{title}}" not in template:
            continue
        values = {key: "原书 {{title}}\n保留字面内容" for key in VARIABLE.findall(template)}
        values["title"] = title
        original = render_plain(path.stem, **values)
        bound = teardown_prompts.render(path.stem, **values)
        assert bound.encode() == original.encode()
        suffix = "\n\n【上次归得不对】原书 {{title}}。请照要求重新归。"
        retry = bound + suffix
        assert retry.with_title(title).encode() == (original + suffix).encode()
        rebound = render_plain(path.stem, **{**values, "title": "新的书名"})
        assert retry.with_title("新的书名").encode() == (rebound + suffix).encode()
        assert ("重试前缀\n" + retry).with_title("新的书名").encode() == ("重试前缀\n" + rebound + suffix).encode()
        checked.append(path.stem)
    assert {"persona_essence", "teardown_read", "teardown_card", "teardown_units", "essence_check"} <= set(checked)


async def test_prepared_parallel_calls_rebind_only_title_before_they_start(client, sessionmaker):
    bid, _ = await seed(sessionmaker)
    runner = Runner(None, sessionmaker, None, SimpleNamespace())
    await runner.initialize(bid)
    raw = "原书这个名字是正文，{{title}} 是原文里的记号，不得替换。"
    prepared = teardown_prompts.render(
        "teardown_read", title="原书", first="1", last="1", chapters=raw, roster="（还没有）"
    )
    system = teardown_prompts.render("persona_essence", title="原书", upto="1", total="8", rules="规则")
    suffix = "\n\n【上次写得不对】原书是原样的提示后缀。"
    captured = []
    first_started, release = asyncio.Event(), asyncio.Event()

    class Router:
        async def structured(self, role, schema, system, user, *, purpose, teardown_policy):
            captured.append((str(user), str(system)))
            if len(captured) == 1:
                first_started.set()
                await release.wait()
            return object()

    runner.router = Router()
    first = asyncio.create_task(runner.call_user(object, prepared, "测试", system=system))
    try:
        await asyncio.wait_for(first_started.wait(), 5)
        response = await client.patch(f"/api/books/{bid}", json={"title": "并发前改的新书名"})
        assert response.status_code == 200, response.text
        await asyncio.gather(*(runner.call_user(object, prepared + suffix, "测试", system=system) for _ in range(3)))
        assert "小说《原书》" in captured[0][0] and "小说《原书》" in captured[0][1]
        for user, used_system in captured[1:]:
            assert "小说《并发前改的新书名》" in user and "小说《并发前改的新书名》" in used_system
            assert raw in user and user.endswith(suffix)
    finally:
        release.set()
        await first


async def test_finish_waits_for_concurrent_rename_before_merging_teardown(client, sessionmaker):
    """故意让收尾读到旧快照；保存前必须等改名提交，再合并 title_edited。"""
    bid, jid = await seed(sessionmaker, count=0)
    redis = AsyncMock()
    redis.exists.return_value = 0
    runner = Runner(jid, sessionmaker, redis, SimpleNamespace())
    await runner.initialize()
    runner.progress = AsyncMock()
    runner.refresh = AsyncMock()
    writer_reached = asyncio.Event()
    engine = sessionmaker.kw["bind"].sync_engine

    def watch(conn, cursor, statement, parameters, context, executemany):
        if ("FROM books" in statement and "FOR UPDATE" in statement) or statement.startswith("UPDATE books"):
            writer_reached.set()

    async with sessionmaker() as editing:
        book = await editing.scalar(select(Book).where(Book.id == bid).with_for_update())
        book.title = "收尾并发时的新书名"
        book.concept = {"title": book.title}
        book.teardown = {**book.teardown, "title_edited": True}
        await editing.flush()
        event.listen(engine, "before_cursor_execute", watch)
        task = asyncio.create_task(runner.finish())
        try:
            await asyncio.wait_for(writer_reached.wait(), 5)
            assert not task.done()
            await editing.commit()
            await asyncio.wait_for(task, 10)
        finally:
            event.remove(engine, "before_cursor_execute", watch)
            await editing.rollback()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == book.concept["title"] == "收尾并发时的新书名"
        assert book.teardown["title_edited"] is True and book.teardown["stage"] == "stopped"
