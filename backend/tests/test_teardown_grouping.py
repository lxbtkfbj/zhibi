"""读完原文时的归并竞态：用事件固定 await 窗口，不靠模型耗时碰运气。"""

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.main import create_app
from app.models import Book, Chapter, Job, MeetingMessage, PlotUnit, Volume
from app.services import jobs
from app.services import teardown_closing as closing
from app.services.teardown_runner import Runner
from tests.test_teardown_runner import DemoRouter, create_book, fast_prompts_and_demo  # noqa: F401


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


async def assert_completed(runner):
    book, chapters, units, volumes = await runner.snapshot()
    assert chapters and all(c.unit_id and c.teardown.get("read_version") == 1 for c in chapters)
    assert units and volumes and all(v.summary and v.title != "还没收尾" for v in volumes)
    assert book.teardown["open_volume_id"] is None
    assert book.teardown["stage"] == "done"
    assert book.teardown["stop_reason"] is None and book.teardown["stop_note"] == ""
    assert runner.stop is None
    async with runner.sm() as session:
        job = await session.get(Job, runner.job_id)
        assert job.status == "succeeded" and job.error == ""


@pytest.mark.parametrize("window", ["collect_waits", "inner_group", "inner_volumes"])
async def test_reading_finishes_during_grouping_await_still_runs_final_pass(sessionmaker, redis, monkeypatch, window):
    _, jid = await create_book(sessionmaker, count=12)
    entered, release, reading_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def read_after_grouping_paused(call):
        if call["schema"] is s.TeardownRead:
            await asyncio.wait_for(entered.wait(), timeout=10)

    router = DemoRouter(read_after_grouping_paused)
    runner = Runner(jid, sessionmaker, redis, router)
    changed_set = runner.changed.set

    def signal_reading_finished():
        changed_set()
        if runner.reading_done:
            reading_finished.set()

    monkeypatch.setattr(runner.changed, "set", signal_reading_finished)
    phases = []
    group_once, volumes_once, collect_waits = runner.group_once, runner.volumes_once, closing.collect_waits

    async def controlled_group_once(*, final=False):
        phases.append(("units", final))
        result = await group_once(final=final)
        if window == "inner_group" and not entered.is_set():
            assert not final and not result and not runner.reading_done
            entered.set()
            await release.wait()
        return result

    async def tracked_volumes_once(*, final=False):
        phases.append(("volumes", final))
        result = await volumes_once(final=final)
        if window == "inner_volumes" and not entered.is_set():
            assert not final and not result and not runner.reading_done
            entered.set()
            await release.wait()
        return result

    async def controlled_collect_waits(*args, full_only=False, **kwargs):
        if full_only:
            assert not runner.reading_done
            entered.set()
            await release.wait()
            return None
        return await collect_waits(*args, **kwargs)

    monkeypatch.setattr(runner, "group_once", controlled_group_once)
    monkeypatch.setattr(runner, "volumes_once", tracked_volumes_once)
    if window == "collect_waits":
        monkeypatch.setattr(closing, "collect_waits", controlled_collect_waits)
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        await asyncio.wait_for(reading_finished.wait(), timeout=10)
        assert runner.reading_done and not release.is_set() and not task.done()
        book, chapters, units, _ = await runner.snapshot()
        assert all(c.teardown.get("read_version") == 1 and c.unit_id is None for c in chapters)
        assert not units and book.teardown["open_volume_id"]
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=30)
    assert phases[:2] == [("volumes", False), ("units", False)]
    assert ("units", True) in phases and ("volumes", True) in phases
    first_final = next(index for index, (_, final) in enumerate(phases) if final)
    assert all(final for _, final in phases[first_final:])
    await assert_completed(runner)


async def test_resume_all_read_book_repairs_unassigned_tail_and_closes_without_rereading(
    sessionmaker, redis, monkeypatch
):
    bid, old_jid = await create_book(sessionmaker, count=12, read=True)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        old_job = await session.get(Job, old_jid)
        old_job.status = "failed"
        book.teardown = {
            **book.teardown,
            "stage": "stopped",
            "stop_reason": "error",
            "stop_note": "拆的时候出错了（还有章或卷没有归完），停下了。点「接着拆」从停的地方往下拆，读过的不重读。",
        }
        volume = await session.scalar(select(Volume).where(Volume.book_id == bid))
        volume.title = "还没收尾"
        existing = PlotUnit(
            book_id=bid, volume_id=volume.id, index=1, title="已经归好的单元", summary="原有单元不重拆", chapter_count=4
        )
        session.add(existing)
        await session.flush()
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid).order_by(Chapter.index)))
        for chapter in chapters[:4]:
            chapter.unit_id = existing.id
        before = {c.index: (c.content, c.summary, c.outline, c.teardown) for c in chapters}
        existing_id = existing.id
        await session.commit()

    queued = []
    monkeypatch.setattr(jobs, "enqueue_teardown", queued.append)
    app = create_app()
    app.state.redis = redis
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/teardown/{bid}/start", json={})
    assert response.status_code == 200, response.text
    jid = uuid.UUID(response.json()["id"])
    assert queued == [jid]
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.params["settings_only"] is True and job.params["retry_failed_only"] is False
    router = DemoRouter()
    runner = Runner(jid, sessionmaker, redis, router)
    await runner.run()
    await assert_completed(runner)
    assert not any(call["schema"] is s.TeardownRead for call in router.calls)
    assert any(call["schema"] is s.TeardownUnits for call in router.calls)
    assert any(call["schema"] is s.TeardownVolumes for call in router.calls)
    _, chapters, units, _ = await runner.snapshot()
    for chapter in chapters:
        content, summary, outline, record = before[chapter.index]
        assert (chapter.content, chapter.summary, chapter.outline) == (content, summary, outline)
        # 收尾可以增补 tags，但不得改掉原文、章纲和已经读好的记录。
        assert all(chapter.teardown.get(key) == value for key, value in record.items())
    assert all(c.unit_id == existing_id for c in chapters[:4])
    existing = next(unit for unit in units if unit.id == existing_id)
    assert existing.title == "已经归好的单元" and existing.summary == "原有单元不重拆"


@pytest.mark.parametrize(
    "missing_units,open_volume,missing_text,detail",
    [
        (True, False, False, "第 3–6 章还没归进单元"),
        (False, True, False, "最后一卷还没收尾"),
        (False, False, True, "有卷还没写那段话"),
        (True, True, False, "第 3–6 章还没归进单元；最后一卷还没收尾"),
        (True, False, True, "第 3–6 章还没归进单元；有卷还没写那段话"),
        (False, True, True, "最后一卷还没收尾；有卷还没写那段话"),
        (True, True, True, "第 3–6 章还没归进单元；最后一卷还没收尾；有卷还没写那段话"),
    ],
)
async def test_finish_identifies_every_unfinished_grouping_reason(
    sessionmaker, redis, missing_units, open_volume, missing_text, detail
):
    bid, jid = await create_book(sessionmaker, count=6, read=True)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        volume = await session.scalar(select(Volume).where(Volume.book_id == bid))
        volume.title = "已归好的一卷"
        volume.summary = "" if missing_text else "已经写好的卷总结"
        book.teardown = {**book.teardown, "open_volume_id": str(volume.id) if open_volume else None}
        unit = PlotUnit(
            book_id=bid, volume_id=volume.id, index=1, title="单元", chapter_count=2 if missing_units else 6
        )
        session.add(unit)
        await session.flush()
        for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == bid)):
            if not missing_units or chapter.index <= 2:
                chapter.unit_id = unit.id
        await session.commit()
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.finish()
    expected = f"拆的时候出错了（{detail}），停下了。点「接着拆」从停的地方往下拆，读过的不重读。"
    book = (await runner.snapshot())[0]
    assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == "error"
    assert book.teardown["stop_note"] == expected
    assert not runner.router.calls
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "failed" and job.error == expected
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.job_id == jid))
        assert message.content == expected


@pytest.mark.parametrize(
    "ungrouped,unread,detail",
    [
        ((2, 3, 5, 6), False, "（第 2–3 章还没归进单元；第 5–6 章还没归进单元）"),
        ((), True, ""),
    ],
)
async def test_finish_does_not_misreport_grouped_chapters_as_missing(sessionmaker, redis, ungrouped, unread, detail):
    bid, jid = await create_book(sessionmaker, count=6, read=True)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "open_volume_id": None}
        volume = await session.scalar(select(Volume).where(Volume.book_id == bid))
        volume.title, volume.summary = "已经收尾的一卷", "已经写好的卷总结"
        unit = PlotUnit(book_id=bid, volume_id=volume.id, index=1, title="保留的单元", chapter_count=6)
        session.add(unit)
        await session.flush()
        for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == bid)):
            if chapter.index not in ungrouped:
                chapter.unit_id = unit.id
            if unread and chapter.index == 1:
                chapter.teardown = {}
        await session.commit()
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.finish()
    expected = f"拆的时候出错了{detail}，停下了。点「接着拆」从停的地方往下拆，读过的不重读。"
    book = (await runner.snapshot())[0]
    assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == "error"
    assert book.teardown["stop_note"] == expected
    assert not runner.router.calls
