"""任务 2 经作者授权的接口补齐：轻量目录、完整记录与停后只补失败章。"""

import re
import uuid
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
from app.prompts import default_content
from app.services import jobs
from app.services.teardown_runner import Runner


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(monkeypatch, redis):
    app = create_app()
    app.state.redis = redis
    monkeypatch.setattr(jobs, "enqueue_teardown", lambda _: None)
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def seed(sm, *, source="teardown", upto=6, read=6, failed=(2,), reason="upto", stage="stopped"):
    async with sm() as session:
        book = Book(
            title="补丁验收原书",
            source=source,
            status="writing",
            teardown={
                "stage": stage,
                "upto": upto,
                "original_volumes": False,
                "stop_reason": reason,
                "stop_note": f"原先因为 {reason} 停下的说明。",
            },
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="还没收尾", chapter_count=8, status="done")
        session.add(volume)
        await session.flush()
        book.teardown = {**book.teardown, "open_volume_id": str(volume.id)}
        for index in range(1, 9):
            record = {"raw_title": f"第{index}章 原题", "number": index, "flags": []}
            if index <= read and index not in failed:
                record.update(
                    read_version=1,
                    read_at="2026-10-20T01:00:00+00:00",
                    read={"people": [{"name": "旧人物", "shown": "原记录"}], "tropes": ["原桥段"]},
                )
            if index in failed:
                record["read_failed"] = {"at": "2026-10-20T01:00:00+00:00", "error": "没有读成"}
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=index,
                    title=f"原章{index}",
                    content=f"人物在第 {index} 章继续前行。",
                    outline={"goal": f"原章纲{index}"},
                    summary=f"原摘要{index}",
                    source="imported" if source == "teardown" else "generated",
                    status="final",
                    teardown=record,
                )
            )
        await session.commit()
        return book.id


class DemoRouter:
    def __init__(self, *, fail=False):
        self.read_indices = []
        self.fail = fail

    async def structured(self, role, schema, system, user, *, purpose, teardown_policy):
        if schema is s.TeardownRead:
            self.read_indices.extend(int(index) for index in re.findall(r"^「第 (\d+) 章", user, re.M))
            if self.fail:
                raise ValueError("这次仍然没读成")
        return await demo.respond(schema, system, user)


@pytest.mark.parametrize("query", ["", "?with_outline=true", "?volume=1"])
async def test_directory_projects_only_read_flags_without_loading_full_records(client, sessionmaker, query):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        first = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 1))
        first.teardown = {**first.teardown, "read_version": 0}
        second = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 2))
        second.teardown = {**second.teardown, "read_failed": {}}
        await session.commit()
        engine = session.bind.sync_engine
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM chapters" in statement:
            statements.append(statement.split("FROM")[0])

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await client.get(f"/api/books/{bid}/chapters{query}")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows[0]["teardown"] == {"read": True, "failed": False}
    assert rows[1]["teardown"] == {"read": False, "failed": True}
    assert rows[-1]["teardown"] == {"read": False, "failed": False}
    assert all("content" not in row and set(row["teardown"]) == {"read", "failed"} for row in rows)
    assert (rows[0]["outline"] == {"goal": "原章纲1"}) if query else rows[0]["outline"] is None
    assert "原记录" not in response.text and "read_at" not in response.text and "raw_title" not in response.text
    assert statements and all("chapters.content" not in statement for statement in statements)
    assert all(not re.search(r"chapters\.teardown\s*(?:,|$)", statement) for statement in statements)


@pytest.mark.parametrize("index", [1, 2, 8])
async def test_single_chapter_returns_complete_raw_teardown(client, sessionmaker, index):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == index))
        original = chapter.teardown
    response = await client.get(f"/api/books/{bid}/chapters/{index}")
    assert response.status_code == 200
    assert response.json()["teardown"] == original
    changed = await client.patch(f"/api/books/{bid}/chapters/{index}", json={"title": "作者手改章名"})
    assert changed.status_code == 200 and changed.json()["teardown"] == original


async def test_author_book_directory_and_detail_keep_original_contract(client, sessionmaker):
    bid = await seed(sessionmaker, source="new")
    for query in ("", "?with_outline=true", "?volume=1"):
        response = await client.get(f"/api/books/{bid}/chapters{query}")
        assert response.status_code == 200
        assert all(row.get("teardown") is None for row in response.json())
    response = await client.get(f"/api/books/{bid}/chapters/1")
    assert response.status_code == 200
    assert "teardown" not in response.json() and response.json()["content"] == "人物在第 1 章继续前行。"
    changed = await client.patch(f"/api/books/{bid}/chapters/1", json={"content": "作者自己的新正文"})
    assert changed.status_code == 200 and "teardown" not in changed.json()
    assert changed.json()["content"] == "作者自己的新正文"


@pytest.mark.parametrize("reason", ["author", "upto", "model", "error"])
@pytest.mark.parametrize("read", [5, 6])
async def test_same_target_retries_only_failed_and_restores_original_stop(client, sessionmaker, redis, reason, read):
    bid = await seed(sessionmaker, reason=reason, read=read, failed=(2, 7))
    async with sessionmaker() as session:
        before = {
            c.index: (c.teardown, c.outline, c.summary)
            for c in await session.scalars(select(Chapter).where(Chapter.book_id == bid))
        }
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": 6})
    assert response.status_code == 200, response.text
    jid = uuid.UUID(response.json()["id"])
    assert response.json()["pending"]["teardown"]["failed"] == [2]
    router = DemoRouter()
    await Runner(jid, sessionmaker, redis, router).run()
    assert router.read_indices == [2]
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == reason
        assert book.teardown["stop_note"] == f"原先因为 {reason} 停下的说明。"
        assert book.teardown["upto"] == 6
        assert (await session.get(Job, jid)).params["retry_failed_only"] is True
        for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == bid)):
            if chapter.index != 2:
                assert (chapter.teardown, chapter.outline, chapter.summary) == before[chapter.index]
            else:
                assert chapter.teardown["read_version"] == 1 and "read_failed" not in chapter.teardown


@pytest.mark.parametrize("requested", [None, 8, 99])
@pytest.mark.parametrize("read,expected_stage", [(5, "stopped"), (8, "done")])
async def test_full_target_normalization_retry_does_not_fill_unattempted_gaps(
    client, sessionmaker, redis, requested, read, expected_stage
):
    bid = await seed(sessionmaker, upto=None, read=read, reason="author")
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": requested})
    assert response.status_code == 200, response.text
    jid = uuid.UUID(response.json()["id"])
    router = DemoRouter()
    await Runner(jid, sessionmaker, redis, router).run()
    assert router.read_indices == [2]
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["upto"] is None and book.teardown["stage"] == expected_stage
        assert book.teardown["stop_reason"] == ("author" if expected_stage == "stopped" else None)
        if read == 5:
            for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == bid, Chapter.index > 5)):
                assert "read_version" not in chapter.teardown and "read_failed" not in chapter.teardown


@pytest.mark.parametrize(
    "upto,read,failed,requested,status,retry,closing_only",
    [
        (6, 6, (), 6, 422, None, None),
        (6, 6, (7,), 6, 422, None, None),
        (6, 6, (2,), 5, 422, None, None),
        (None, 8, (), None, 200, False, True),
        (None, 8, (), 8, 200, False, True),
        (6, 6, (2,), 7, 200, False, False),
        (6, 7, (2,), 7, 422, None, None),
        (6, 5, (), 6, 200, False, False),
    ],
)
async def test_failed_retry_does_not_bypass_target_rules(
    client, sessionmaker, redis, monkeypatch, upto, read, failed, requested, status, retry, closing_only
):
    bid = await seed(sessionmaker, upto=upto, read=read, failed=failed)
    # 部分范围的设定、读者账和精髓都已整理时，仍遵守原目标约束；但全书已读、
    # stage 仍 stopped 时，第五批 §6 要允许只整理，补上未归完的单元和卷。
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {
            **book.teardown,
            "settings": {"upto": read},
            "waits": {"upto": read, "total": 0, "open": 0},
            "essence": {"upto": read},
        }
        before = {
            c.index: (c.content, c.teardown, c.outline, c.summary)
            for c in await session.scalars(select(Chapter).where(Chapter.book_id == bid))
        }
        await session.commit()
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": requested})
    assert response.status_code == status, response.text
    async with sessionmaker() as session:
        job = await session.scalar(select(Job).where(Job.book_id == bid))
        if status == 422:
            assert job is None
            assert response.json()["detail"] == f"已经拆到第 {read} 章了，要拆得更多才能接着拆"
        else:
            assert job.params["retry_failed_only"] is retry
            assert job.params["settings_only"] is closing_only
    if closing_only:
        no_read = AsyncMock(side_effect=AssertionError("只整理不许重读或扩读原文"))
        monkeypatch.setattr(Runner, "read_chapters", no_read)
        router = DemoRouter()
        jid = uuid.UUID(response.json()["id"])
        await Runner(jid, sessionmaker, redis, router).run()
        no_read.assert_not_awaited()
        assert router.read_indices == []
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            assert book.teardown["stage"] == "done"
            assert (await session.get(Job, jid)).status == "succeeded"
            after = {
                c.index: (c.content, c.teardown, c.outline, c.summary)
                for c in await session.scalars(select(Chapter).where(Chapter.book_id == bid))
            }
            assert after == before and set(after) == set(range(1, 9))


async def test_increasing_target_keeps_normal_resume_and_failed_retry(client, sessionmaker, redis):
    bid = await seed(sessionmaker)
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": 7})
    assert response.status_code == 200
    router = DemoRouter()
    await Runner(uuid.UUID(response.json()["id"]), sessionmaker, redis, router).run()
    assert sorted(router.read_indices) == [2, 7]
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["upto"] == 7 and book.teardown["stop_reason"] == "upto"


async def test_empty_failure_record_is_retryable_and_failed_retry_keeps_stop(client, sessionmaker, redis):
    bid = await seed(sessionmaker, read=5, reason="author")
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 2))
        chapter.teardown = {**chapter.teardown, "read_failed": {}}
        await session.commit()
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": 6})
    assert response.status_code == 200 and response.json()["pending"]["teardown"]["failed"] == [2]
    router = DemoRouter(fail=True)
    await Runner(uuid.UUID(response.json()["id"]), sessionmaker, redis, router).run()
    assert router.read_indices == [2, 2]
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == "author"
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 2))
        assert chapter.teardown["read_failed"]["error"] == "这次仍然没读成"


async def test_queued_retry_cancel_restores_original_metadata(client, sessionmaker):
    bid = await seed(sessionmaker, reason="model")
    async with sessionmaker() as session:
        original = (await session.get(Book, bid)).teardown
    started = await client.post(f"/api/teardown/{bid}/start", json={"upto": 6})
    assert started.status_code == 200
    assert (await client.post(f"/api/teardown/{bid}/stop")).status_code == 200
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).teardown == original


async def test_done_failure_retry_keeps_existing_entry_and_only_rereads_failure(client, sessionmaker, redis):
    bid = await seed(sessionmaker, stage="done", upto=None, read=8)
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": None})
    assert response.status_code == 200
    router = DemoRouter()
    await Runner(uuid.UUID(response.json()["id"]), sessionmaker, redis, router).run()
    assert router.read_indices == [2]
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).teardown["stage"] == "done"
