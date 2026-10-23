"""确认、试读继续前等看稿记忆；改稿不等，失败和超时不挡写作。"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents.schemas import FeedbackMemory
from app.config import get_settings
from app.graphs.deps import JobCancelled, cancel_key
from app.llm import demo
from app.main import create_app
from app.models import Book, Chapter, Job, LlmCall, MeetingMessage, Memory, PlotUnit, Volume
from app.services import feedback_memory, jobs
from app.services.job_runner import execute_job
from tests.test_write_book import job_state

WAITING = "主编正在看你写的意见…"


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
            yield client
    finally:
        await application.state.redis.aclose()


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr(feedback_memory, "WAIT_POLL_S", 0.01)


@pytest.fixture
async def worker_queue(monkeypatch):
    queued, workers = [], []

    def enqueue(job_id, resume=None):
        queued.append((job_id, resume))
        workers.append(asyncio.create_task(execute_job(job_id, resume)))

    monkeypatch.setattr(jobs, "enqueue", enqueue)
    try:
        yield queued, workers
    finally:
        for worker in workers:
            if not worker.done():
                worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


async def seed_gate(sm, *, trial):
    """合成库进入真实图的拍板检查点；造数据本身和首次运行都不调模型。"""
    async with sm() as session:
        book = Book(
            title="看稿等待边界合成书",
            idea="少年在雨夜守住一盏灯，寻找失散同伴。",
            concept={"story": "少年在雨夜守灯寻人。"},
            status="writing",
            trial_read_done=not trial,
            settings={
                "volume_approval": True,
                "trial_read": True,
                "chapter_words": 600,
                "review_strictness": "lenient",
            },
        )
        session.add(book)
        await session.flush()
        volume = Volume(
            book_id=book.id,
            index=1,
            title="雨夜寻灯",
            summary="少年守住灯火，在天明前找到同伴。",
            chapter_count=4 if trial else 1,
            status="approved" if trial else "detailed",
        )
        session.add(volume)
        await session.flush()
        unit = PlotUnit(
            book_id=book.id,
            volume_id=volume.id,
            index=1,
            title="第一盏灯",
            summary="冒雨守灯，循着线索找回同伴。",
            chapter_count=4 if trial else 1,
            key_events=["守灯", "寻人", "归来"],
            goal="找到同伴",
            status="outlined" if trial else "planned",
        )
        session.add(unit)
        await session.flush()
        if trial:
            for index in range(1, 5):
                session.add(
                    Chapter(
                        book_id=book.id,
                        volume_id=volume.id,
                        unit_id=unit.id,
                        index=index,
                        title=f"雨灯{index}",
                        status="final" if index <= 3 else "planned",
                        content="少年提着灯走进雨里。" if index <= 3 else "",
                        word_count=11 if index <= 3 else 0,
                        summary="少年守住灯火，寻找同伴。" if index <= 3 else "",
                        outline={"goal": "找到同伴", "cool_point": "护住灯火", "hook": "雨夜里有人归来"},
                    )
                )
        job = Job(
            book_id=book.id,
            kind="write_book",
            status="queued",
            thread_id=f"feedback-wait-{uuid.uuid4()}",
            params={"until": "count", "count": 1},
        )
        session.add(job)
        await session.commit()
        book_id, job_id = book.id, job.id
    await execute_job(job_id)
    status, pending, error = await job_state(sm, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == ("trial_read" if trial else "volume_review")
    async with sm() as session:
        assert not await session.scalar(select(LlmCall.id).where(LlmCall.book_id == book_id))
    return book_id, job_id


async def rows(sm, model, book_id):
    async with sm() as session:
        return list(await session.scalars(select(model).where(model.book_id == book_id).order_by(model.id)))


async def eventually(check):
    async with asyncio.timeout(20):
        for _ in range(2000):
            if await check():
                return
            await asyncio.sleep(0.01)
    pytest.fail("没有观察到等待主编的状态")


async def saw_wait(sm, book_id):
    return any(
        message.kind == "status" and message.content == WAITING for message in await rows(sm, MeetingMessage, book_id)
    )


def delayed_judgment(monkeypatch, *, result="remember"):
    started, release = asyncio.Event(), asyncio.Event()
    prompts, judgments = [], []
    respond, stream = demo.respond, demo.stream_text

    async def capture(schema, system, user):
        if schema is FeedbackMemory:
            judgments.append(user)
            started.set()
            await release.wait()
            if result == "failed":
                raise RuntimeError("合成判断失败")
            if result == "empty":
                return FeedbackMemory(items=[], reply="这段意见不需要记成长期规矩。")
        else:
            prompts.append((schema.__name__, user))
        return await respond(schema, system, user)

    async def capture_stream(system, user):
        prompts.append(("stream", user))
        async for chunk in stream(system, user):
            yield chunk

    monkeypatch.setattr(demo, "respond", capture)
    monkeypatch.setattr(demo, "stream_text", capture_stream)
    return started, release, prompts, judgments


async def finish(request, workers, release):
    # 所有阻塞的模型都释放并等待收尾；断言失败也不把任务留给下一项测试。
    release.set()
    await asyncio.wait_for(asyncio.gather(request, *workers, return_exceptions=True), 60)


def test_wait_limit_is_two_minutes():
    assert feedback_memory.WAIT_TIMEOUT_S == 120


@pytest.mark.parametrize("trial", [True, False], ids=["trial-chapter-four", "approved-volume"])
async def test_first_requirements_after_feedback_already_include_judged_memory(
    client, sessionmaker, monkeypatch, worker_queue, trial
):
    book_id, job_id = await seed_gate(sessionmaker, trial=trial)
    text = "以后每章少写点对话" if trial else "以后每章打斗都多一点"
    started, release, prompts, judgments = delayed_judgment(monkeypatch)
    queued, workers = worker_queue
    request = asyncio.create_task(
        client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve", "feedback": text})
    )
    try:
        await asyncio.wait_for(started.wait(), 20)
        await eventually(lambda: saw_wait(sessionmaker, book_id))
        assert queued[0][1]["feedback_memory_id"]
        assert not prompts, "连备资料也不能在主编判断结束前先跑"
        assert not workers[0].done()
        release.set()
        response = await asyncio.wait_for(request, 30)
        assert response.status_code == 200, response.text
        await asyncio.wait_for(workers[0], 60)
        status, _, error = await job_state(sessionmaker, job_id)
        assert status == "succeeded", error
        first = next(user for _, user in prompts if "【作者的要求（" in user)
        assert text in demo._section(first, "作者的要求（必须落实；后面的要求与前面冲突时以后面的为准）")
        if trial:
            assert prompts[0][0] == "ChapterMaterials"
            assert "请写第 4 章" in first
        else:
            assert prompts[0][0] == "ChapterPlanDraft"
            assert "第 1-1 章" in first
        memories = await rows(sessionmaker, Memory, book_id)
        assert len(memories) == 1 and memories[0].detail == text
        messages = await rows(sessionmaker, MeetingMessage, book_id)
        author = next(message for message in messages if message.payload.get("feedback_memory"))
        assert author.id == queued[0][1]["feedback_memory_id"]
        assert author.payload["feedback_memory"]["state"] == "done"
        assert author.payload["feedback_memory"]["what_happens"] == (
            feedback_memory.TRIAL if trial else feedback_memory.CONFIRM
        )
        chief = next(message for message in messages if message.payload.get("feedback_to") == author.id)
        assert chief.payload["memories"][0]["memory"]["id"] == memories[0].id
        # 真正经过 LLMRouter 的调用记录，而不是只检查给 model helper 的参数。
        calls = await rows(sessionmaker, LlmCall, book_id)
        judgment_call = [call for call in calls if call.purpose == "看稿意见要不要记"]
        assert len(judgment_call) == 1 and judgment_call[0].ok
        assert all(call.purpose != "feedback_memory" for call in calls)
        await feedback_memory.judge(author.id, client._transport.app.state.redis)
        assert len(judgments) == 1, "等待或重复派送不能把同一段意见判断两次"
    finally:
        await finish(request, workers, release)


@pytest.mark.parametrize("result", ["empty", "failed", "timeout"])
async def test_trial_keeps_writing_when_nothing_to_remember_failed_or_timed_out(
    client, sessionmaker, monkeypatch, worker_queue, result
):
    book_id, job_id = await seed_gate(sessionmaker, trial=True)
    started, release, prompts, judgments = delayed_judgment(monkeypatch, result=result)
    if result == "timeout":
        monkeypatch.setattr(feedback_memory, "WAIT_TIMEOUT_S", 0.1)
    queued, workers = worker_queue
    text = "以后每章少写点对话"
    request = asyncio.create_task(
        client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve", "feedback": text})
    )
    try:
        await asyncio.wait_for(started.wait(), 20)
        await eventually(lambda: saw_wait(sessionmaker, book_id))
        if result != "timeout":
            assert not prompts
            release.set()
        await asyncio.wait_for(workers[0], 60)
        status, _, error = await job_state(sessionmaker, job_id)
        assert status == "succeeded", error
        assert any("请写第 4 章" in user for _, user in prompts)
        assert not await rows(sessionmaker, Memory, book_id)
        messages = await rows(sessionmaker, MeetingMessage, book_id)
        author = next(message for message in messages if message.id == queued[0][1]["feedback_memory_id"])
        assert author.payload["feedback_memory"]["state"] == (
            "running" if result == "timeout" else "failed" if result == "failed" else "done"
        )
        if result == "timeout":
            assert not request.done(), "超时只是放行写作，不取消后台主编"
            assert not any(message.payload.get("feedback_to") == author.id for message in messages)
        release.set()
        assert (await asyncio.wait_for(request, 30)).status_code == 200
        messages = await rows(sessionmaker, MeetingMessage, book_id)
        author = next(message for message in messages if message.id == author.id)
        chief = next(message for message in messages if message.payload.get("feedback_to") == author.id)
        assert len(judgments) == 1
        if result == "timeout":
            assert author.payload["feedback_memory"]["state"] == "done"
            memories = await rows(sessionmaker, Memory, book_id)
            assert len(memories) == 1 and memories[0].detail == text
            assert chief.payload["memories"][0]["memory"]["id"] == memories[0].id
        elif result == "failed":
            assert "这段意见没来得及判断要不要记" in chief.content
        else:
            assert chief.content == "这段意见不需要记成长期规矩。"
    finally:
        await finish(request, workers, release)


async def test_volume_revision_still_finishes_before_slow_judgment(client, sessionmaker, monkeypatch, worker_queue):
    book_id, job_id = await seed_gate(sessionmaker, trial=False)
    started, release, prompts, judgments = delayed_judgment(monkeypatch)
    queued, workers = worker_queue
    request = asyncio.create_task(
        client.post(f"/api/jobs/{job_id}/decision", json={"action": "revise", "feedback": "以后每章打斗都多一点"})
    )
    try:
        await asyncio.wait_for(started.wait(), 20)
        assert "feedback_memory_id" not in queued[0][1]
        await asyncio.wait_for(workers[0], 60)
        status, pending, error = await job_state(sessionmaker, job_id)
        assert status == "waiting_author" and pending["kind"] == "volume_review", error
        assert any(name == "VolumePlanDraft" for name, _ in prompts)
        assert not await saw_wait(sessionmaker, book_id)
        assert not await rows(sessionmaker, Memory, book_id)
        assert not request.done()
        release.set()
        assert (await asyncio.wait_for(request, 30)).status_code == 200
        assert len(judgments) == 1 and len(await rows(sessionmaker, Memory, book_id)) == 1
    finally:
        await finish(request, workers, release)


async def test_cancel_while_waiting_stops_worker_but_not_judgment(client, sessionmaker, monkeypatch, worker_queue):
    book_id, job_id = await seed_gate(sessionmaker, trial=True)
    started, release, prompts, _ = delayed_judgment(monkeypatch)
    _, workers = worker_queue
    request = asyncio.create_task(
        client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve", "feedback": "以后每章少写点对话"})
    )
    try:
        await asyncio.wait_for(started.wait(), 20)
        await eventually(lambda: saw_wait(sessionmaker, book_id))
        redis = client._transport.app.state.redis
        await redis.set(cancel_key(job_id), "1", ex=30)
        await asyncio.wait_for(workers[0], 20)
        assert (await job_state(sessionmaker, job_id))[0] == "cancelled"
        assert not prompts
        assert not await redis.exists(cancel_key(job_id))
        release.set()
        assert (await asyncio.wait_for(request, 30)).status_code == 200
        assert len(await rows(sessionmaker, Memory, book_id)) == 1
    finally:
        await finish(request, workers, release)


@pytest.mark.parametrize("boundary", ["none", "missing", "other-book", "other-job", "revise", "done", "failed"])
async def test_wait_ignores_absent_unrelated_revision_or_finished_judgment(sessionmaker, boundary):
    book_id, job_id = await seed_gate(sessionmaker, trial=False)
    async with sessionmaker() as session:
        author = MeetingMessage(
            book_id=book_id,
            job_id=job_id,
            speaker="author",
            kind="decision",
            content="以后每章多写打斗",
            payload={
                "feedback_memory": {
                    "state": boundary if boundary in ("done", "failed") else "running",
                    "where": "第 1 卷的卷纲",
                    "what_happens": feedback_memory.REVISE if boundary == "revise" else feedback_memory.CONFIRM,
                    "feedback": "以后每章多写打斗",
                }
            },
        )
        session.add(author)
        await session.commit()
        message_id = None if boundary == "none" else author.id + 10000 if boundary == "missing" else author.id
    emit, check_cancel = AsyncMock(), AsyncMock()
    await asyncio.wait_for(
        feedback_memory.wait_for_result(
            message_id,
            sessionmaker,
            emit,
            check_cancel,
            book_id=uuid.uuid4() if boundary == "other-book" else book_id,
            job_id=uuid.uuid4() if boundary == "other-job" else job_id,
        ),
        2,
    )
    emit.status.assert_not_awaited()


async def test_wait_checks_cancellation_before_polling_again(sessionmaker):
    book_id, job_id = await seed_gate(sessionmaker, trial=False)
    async with sessionmaker() as session:
        message = MeetingMessage(
            book_id=book_id,
            job_id=job_id,
            speaker="author",
            kind="decision",
            content="以后多写打斗",
            payload={"feedback_memory": {"state": "pending", "what_happens": feedback_memory.CONFIRM}},
        )
        session.add(message)
        await session.commit()
        mid = message.id
    with pytest.raises(JobCancelled):
        await asyncio.wait_for(
            feedback_memory.wait_for_result(
                mid,
                sessionmaker,
                AsyncMock(),
                AsyncMock(side_effect=JobCancelled),
                book_id=book_id,
                job_id=job_id,
            ),
            2,
        )
