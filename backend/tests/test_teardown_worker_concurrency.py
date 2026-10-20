"""两个拆书进程启动恢复只投一次，同任务互斥、不同书可并行。"""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from redis.asyncio import Redis

from app.config import get_settings
from app.models import Book, Job
from app.services import job_runner
from app.worker import tasks


async def test_two_workers_claim_orphan_once_and_running_job_is_not_recovered(sessionmaker):
    async with sessionmaker() as session:
        books = [Book(title=f"独立测试书{i}", source="teardown") for i in range(3)]
        session.add_all(books)
        await session.flush()
        jobs = [Job(book_id=book.id, kind="teardown", status="running", thread_id=str(uuid.uuid4())) for book in books]
        session.add_all(jobs)
        await session.commit()
        ids = [job.id for job in jobs]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.set(job_runner.lock_key(ids[2]), "live-worker", ex=60)
        first, second = await asyncio.gather(tasks._orphaned_jobs(("teardown",)), tasks._orphaned_jobs(("teardown",)))
        assert set(first).isdisjoint(second)
        assert set(first + second) == {str(ids[0]), str(ids[1])}
        assert await tasks._orphaned_jobs(("teardown",)) == []
        assert 0 < await redis.ttl(f"zhibi:recover:{ids[0]}") <= job_runner.LOCK_TIMEOUT_S
    finally:
        await redis.aclose()


async def test_execute_same_job_once_while_two_different_jobs_overlap(monkeypatch):
    """用真实独立 Redis 锁和 execute_job，不以假的 acquire 结果代替互斥证据。"""
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    entered = []
    running = 0
    maximum = 0

    async def run(job_id, *_):
        nonlocal running, maximum
        entered.append(job_id)
        running += 1
        maximum = max(maximum, running)
        started.set()
        try:
            await release.wait()
        finally:
            running -= 1

    monkeypatch.setattr(job_runner, "make_engine", lambda: SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(job_runner, "make_sessionmaker", lambda _: object())
    monkeypatch.setattr(job_runner, "LLMRouter", lambda *args, **kwargs: SimpleNamespace(aclose=AsyncMock()))
    monkeypatch.setattr(job_runner, "_run", run)
    first = asyncio.create_task(job_runner.execute_job(first_id))
    await asyncio.wait_for(started.wait(), 3)
    # 第二个进程收到同一任务时立即跳过；另一本书不必等第一个完成。
    await asyncio.wait_for(job_runner.execute_job(first_id), 3)
    second = asyncio.create_task(job_runner.execute_job(second_id))
    for _ in range(100):
        if len(entered) == 2:
            break
        await asyncio.sleep(0.01)
    try:
        assert entered == [first_id, second_id] and maximum == 2
    finally:
        release.set()
        await asyncio.gather(first, second)


async def test_recovery_enqueue_failure_releases_own_claim_and_live_worker_retries(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book = Book(title="投递失败恢复验收", source="teardown")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="teardown", status="running", thread_id="recovery-failure")
        session.add(job)
        await session.commit()
        job_id = str(job.id)
    callbacks, deliveries = [], []
    sender = SimpleNamespace(timer=SimpleNamespace(call_after=lambda *args, **kwargs: callbacks.append((args, kwargs))))

    def enqueue(**kwargs):
        deliveries.append(kwargs)
        if len(deliveries) == 1:
            raise ConnectionError("独立测试模拟 broker 投递失败")

    monkeypatch.setattr(tasks.run_teardown, "apply_async", enqueue)
    await asyncio.to_thread(tasks._recover_teardown_jobs, sender)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        assert await redis.get(f"zhibi:recover:{job_id}") is None
        args, kwargs = callbacks.pop()
        assert args[0] == job_runner.LOCK_TIMEOUT_S + 1
        await asyncio.to_thread(args[1], *kwargs["args"])
        assert deliveries == [{"args": [job_id], "queue": "teardown"}] * 2
    finally:
        await redis.aclose()


async def test_surviving_worker_rescans_claimed_but_never_enqueued_orphan(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book = Book(title="领取后崩溃验收", source="teardown")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="teardown", status="running", thread_id="recovery-crash")
        session.add(job)
        await session.commit()
        job_id = str(job.id)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    callbacks, deliveries = [], []
    sender = SimpleNamespace(timer=SimpleNamespace(call_after=lambda *args, **kwargs: callbacks.append((args, kwargs))))
    monkeypatch.setattr(tasks.run_teardown, "apply_async", lambda **kwargs: deliveries.append(kwargs))
    try:
        key = f"zhibi:recover:{job_id}"
        await redis.set(key, "crashed-owner", ex=60)
        await asyncio.to_thread(tasks._recover_teardown_jobs, sender)
        assert deliveries == [] and len(callbacks) == 1
        # 旧进程不能因自己投递超时而删掉新进程的 claim。
        await tasks._release_recovery_claim(job_id, "not-the-owner")
        assert await redis.get(key) == "crashed-owner"
        await redis.pexpire(key, 1)
        await asyncio.sleep(0.02)
        args, kwargs = callbacks.pop()
        assert args[0] == job_runner.LOCK_TIMEOUT_S + 1
        await asyncio.to_thread(args[1], *kwargs["args"])
        assert deliveries == [{"args": [job_id], "queue": "teardown"}]
    finally:
        await redis.aclose()


def test_start_declares_two_solo_teardown_workers_and_stop_uses_pid_inventory():
    root = Path(__file__).resolve().parents[2]
    start = (root / "scripts/start.ps1").read_text(encoding="utf-8")
    stop = (root / "scripts/stop.ps1").read_text(encoding="utf-8")
    assert "'-Q', 'teardown', '-n', 'teardown@%h'" in start
    assert "'-Q', 'teardown', '-n', 'teardown2@%h'" in start
    assert '"$logDir\\teardown2.log"' in start and '"$logDir\\teardown2.err.log"' in start
    assert "foreach ($entry in (Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json))" in stop
