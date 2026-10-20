"""第三批与任务入口、收尾和重跑脚本的集成边界。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.graphs.deps import JobCancelled, cancel_key
from app.main import create_app
from app.models import Book, Chapter, Job, MeetingMessage
from app.prompts import default_content
from app.services import jobs
from app.services.teardown_rerun import plan, prepare, run_rerun
from app.services.teardown_runner import Runner
from tests.test_teardown_jobs import seed
from tests.test_teardown_runner import DemoRouter, create_book


@pytest.fixture
async def redis():
    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def client(redis, monkeypatch):
    app = create_app()
    app.state.redis = redis
    monkeypatch.setattr(jobs, "enqueue_teardown", lambda _: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("stage,read", [("stopped", 3), ("done", 5)])
async def test_settings_only_start_when_old_book_has_no_settings(client, sessionmaker, stage, read):
    bid = await seed(sessionmaker, stage=stage, read=read)
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": read})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(response.json()["id"]))
        assert job.params["settings_only"] is True
        assert not job.params["retry_failed_only"]


async def test_settings_only_does_not_read_and_groups_before_collecting(sessionmaker, redis, monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr("app.llm.demo.DELAY_S", 0)
    bid, jid = await create_book(sessionmaker, count=8, upto=5, read=True)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.params = {**job.params, "settings_only": True}
        for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == bid, Chapter.index > 5)):
            chapter.teardown = {
                key: value for key, value in chapter.teardown.items() if key not in ("read_version", "read")
            }
        await session.commit()
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    grouping = AsyncMock(wraps=runner.grouping)
    read_chapters = AsyncMock(side_effect=AssertionError("不许重读"))
    monkeypatch.setattr(runner, "grouping", grouping)
    monkeypatch.setattr(runner, "read_chapters", read_chapters)

    async def after_grouping(current):
        grouping.assert_awaited_once()
        assert current.reading_done is True
        _, chapters, _, _ = await current.snapshot()
        assert all(c.unit_id for c in chapters if c.index <= 5)
        return {"characters": 2, "entries": 3, "skipped": ["小甲"]}

    collect = AsyncMock(side_effect=after_grouping)
    monkeypatch.setattr("app.services.teardown_settings.collect_settings", collect)
    await runner.run()
    collect.assert_awaited_once()
    grouping.assert_awaited_once()
    read_chapters.assert_not_awaited()
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        book = await session.get(Book, bid)
        assert job.status == "succeeded" and book.teardown["stop_reason"] == "upto"
        messages = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.job_id == jid)))
        assert "设定也整理好了：2 张角色卡、3 条设定。小甲 有新内容，你改过的没动。" in messages[-1].content
        assert "读者在等的事整理到第 5 章：一共 0 件，还吊着 0 件。整理了精髓：" in messages[-1].content
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid, Chapter.index > 5)))
        assert all("read_version" not in chapter.teardown for chapter in chapters)


async def test_finish_settings_failure_is_nonfatal_and_can_retry(sessionmaker, redis, monkeypatch):
    bid, jid = await create_book(sessionmaker, count=8, upto=5, read=True)
    monkeypatch.setattr(
        "app.services.teardown_settings.collect_settings", AsyncMock(side_effect=ValueError("测试失败"))
    )
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.finish()
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        book = await session.get(Book, bid)
        assert job.status == "succeeded" and book.teardown["stage"] == "stopped"
        assert book.teardown["stop_note"].endswith("整理设定没做完（测试失败），点「接着拆」再试一次。")


async def test_author_stop_does_not_collect_settings(sessionmaker, redis, monkeypatch):
    bid, jid = await create_book(sessionmaker, count=8, upto=5, read=True)
    collect = AsyncMock(side_effect=AssertionError("点停下不整理"))
    monkeypatch.setattr("app.services.teardown_settings.collect_settings", collect)
    await redis.set(cancel_key(jid), "1")
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.finish()
    collect.assert_not_awaited()
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stop_reason"] == "author"
        assert book.teardown["stop_note"] == "已手动停下，停在第 8 章。"


async def test_author_stop_during_settings_uses_formal_stop_note(sessionmaker, redis, monkeypatch):
    bid, jid = await create_book(sessionmaker, count=8, upto=5, read=True)
    monkeypatch.setattr("app.services.teardown_settings.collect_settings", AsyncMock(side_effect=JobCancelled()))
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.finish()
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stop_reason"] == "author"
        assert book.teardown["stop_note"] == "已手动停下，停在第 8 章。"


@pytest.mark.parametrize("step", ["settings"])
async def test_rerun_new_steps_estimate_force_checkpoint(sessionmaker, redis, monkeypatch, step):
    bid = await seed(sessionmaker, stage="stopped", read=3)
    estimate = AsyncMock(return_value=7 if step == "settings" else 1)
    collect = AsyncMock(return_value={})
    monkeypatch.setattr("app.services.teardown_settings.estimate_calls", estimate)
    monkeypatch.setattr("app.services.teardown_settings.collect_settings", collect)
    async with sessionmaker() as session:
        info = await plan(session, bid, step, None, None)
        assert info["calls"] == (7 if step == "settings" else 1)
        job = await prepare(session, bid, step, None, None, force=True)
        jid = job.id
    await run_rerun(jid, sessionmaker, redis, DemoRouter())
    assert collect.await_args.kwargs == {"force": True}
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "succeeded"
        with pytest.raises(Exception) as exc:
            await plan(session, bid, step, 1, None)
        assert getattr(exc.value, "status_code", None) == 422


@pytest.mark.parametrize("step", ["settings"])
@pytest.mark.parametrize("stage", ["stopped", "done"])
async def test_cancelled_settings_rerun_keeps_committed_metadata_and_original_stage(
    sessionmaker, redis, monkeypatch, step, stage
):
    bid = await seed(sessionmaker, stage=stage, read=3)
    monkeypatch.setattr("app.services.teardown_settings.estimate_calls", AsyncMock(return_value=1))
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stop_note": "原有说明"}
        await session.commit()
        job = await prepare(session, bid, step, None, None, force=True)
        jid = job.id
    marker = {
        "settings": {
            "upto": 2,
            "inputs": {"card:旧名": "新调用的SHA1"},
            "rows": {"character:旧名": {"id": str(uuid.uuid4()), "hash": "新行的SHA1"}},
            "pending_ties": {"刚落盘的角色": []},
        },
        "names": {"旧名": "卡上新名"},
        "merits": {"upto": 3, "points": [{"topic": "开头", "text": "第 1 章的已落盘结果"}], "missing": []},
    }

    async def partial_collect(runner, *, force):
        assert force is True
        async with sessionmaker() as session:
            book = await session.get(Book, bid)
            book.teardown = {**book.teardown, **marker}
            await session.commit()
        await redis.set(cancel_key(jid), "1")
        raise JobCancelled()

    monkeypatch.setattr("app.services.teardown_settings.collect_settings", partial_collect)
    await run_rerun(jid, sessionmaker, redis, DemoRouter())
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        book = await session.get(Book, bid)
        assert job.status == "cancelled"
        assert book.teardown["stage"] == stage and book.teardown["stop_note"] == "原有说明"
        assert {key: book.teardown[key] for key in marker} == marker
    assert not await redis.exists(cancel_key(jid))
