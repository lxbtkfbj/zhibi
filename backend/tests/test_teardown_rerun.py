import uuid

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.graphs.deps import JobCancelled
from app.models import Book, BookSave, Chapter, Job, Volume
from app.services import teardown_jobs, teardown_rerun


async def seed(sm):
    async with sm() as session:
        book = Book(
            title="重跑测试",
            source="teardown",
            status="writing",
            teardown={"stage": "stopped", "original_volumes": True},
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="原卷", status="done", chapter_count=3)
        session.add(volume)
        await session.flush()
        for index in range(1, 4):
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=index,
                    title=f"章{index}",
                    status="final",
                    content="原文",
                    summary="摘要",
                    outline={"goal": "作者改的章纲"},
                    teardown={"read_version": 1, "read": {"people": []}},
                )
            )
        await session.commit()
        return book.id


async def test_plan_is_readonly_validates_and_refuses_active(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        info = await teardown_rerun.plan(session, bid, "read", 1, 3)
        assert info["calls"] == 1
        assert (await session.get(Book, bid)).teardown["stage"] == "stopped"
        for step, first, last in [
            ("read", None, None),
            ("read", 3, 1),
            ("read", 1, 4),
            ("units", 1, 2),
            ("volumes", 1, None),
        ]:
            with pytest.raises(HTTPException) as caught:
                await teardown_rerun.plan(session, bid, step, first, last)
            assert caught.value.status_code == 422
        job = await teardown_rerun.prepare(session, bid, "units", None, None)
        assert job.kind == "teardown" and job.params["rerun"] == "units"
        with pytest.raises(HTTPException) as caught:
            await teardown_rerun.plan(session, bid, "volumes", None, None)
        assert caught.value.status_code == 409


async def test_rerun_only_selected_step_saves_and_preserves_stage_and_outline(sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    seen = []

    class FakeRunner:
        def __init__(self, *args):
            pass

        async def initialize(self, book_id):
            assert book_id == bid

        async def regroup_units(self, first):
            seen.append(("units", first))

    monkeypatch.setattr("app.services.teardown_runner.Runner", FakeRunner)
    async with sessionmaker() as session:
        job = await teardown_rerun.prepare(session, bid, "units", 2, None)
        jid = job.id
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:

        class Router:
            book_id = None

        await teardown_rerun.run_rerun(jid, sessionmaker, redis, Router())
    finally:
        await redis.aclose()
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "succeeded"
        assert (await session.get(Book, bid)).teardown["stage"] == "stopped"
        assert await session.scalar(select(BookSave.title).where(BookSave.book_id == bid)) == "重跑：units"
        assert all(c.outline == {"goal": "作者改的章纲"} for c in await session.scalars(select(Chapter)))
    assert seen == [("units", 2)]


async def test_rerun_missing_or_wrong_book(sessionmaker):
    async with sessionmaker() as session:
        with pytest.raises(HTTPException) as caught:
            await teardown_rerun.plan(session, uuid.uuid4(), "units", None, None)
        assert caught.value.status_code == 404


async def test_queued_rerun_cancel_restores_exact_stage(sessionmaker):
    bid = await seed(sessionmaker)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            book.teardown = {**book.teardown, "stage": "done", "stop_note": "原有提示"}
            await session.commit()
            before = dict(book.teardown)
            job = await teardown_rerun.prepare(session, bid, "units", None, None)
            await teardown_jobs.stop(session, redis, book)
            await session.refresh(book)
            assert book.teardown == before
            assert job.status == "cancelled"
    finally:
        await redis.aclose()


async def test_running_rerun_cancel_is_cancelled_not_failed(sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)

    class CancelledRunner:
        def __init__(self, *args):
            pass

        async def initialize(self, book_id):
            pass

        async def regroup_units(self, first):
            raise JobCancelled()

    monkeypatch.setattr("app.services.teardown_runner.Runner", CancelledRunner)
    async with sessionmaker() as session:
        jid = (await teardown_rerun.prepare(session, bid, "units", None, None)).id
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:

        class Router:
            book_id = None

        await teardown_rerun.run_rerun(jid, sessionmaker, redis, Router())
    finally:
        await redis.aclose()
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "cancelled"
        assert (await session.get(Book, bid)).teardown["stage"] == "stopped"
