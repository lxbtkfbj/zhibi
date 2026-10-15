"""任务可以复用循环，但网络客户端属于单次任务；所有退出路径都必须收尾。"""

import asyncio
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import job_runner
from app.worker import tasks


async def test_worker_reuses_loop_for_recovery_and_successive_tasks(monkeypatch):
    loops = []
    queued = []
    job_id = str(uuid.uuid4())

    async def orphaned():
        loops.append(asyncio.get_running_loop())
        return [job_id]

    async def execute(_job_id, resume=None):
        loops.append(asyncio.get_running_loop())
        if resume == {"fail": True}:
            raise RuntimeError("task failed")

    monkeypatch.setattr(tasks, "_worker_loop", None)
    monkeypatch.setattr(tasks, "_worker_loop_pid", None)
    monkeypatch.setattr(tasks, "_orphaned_jobs", orphaned)
    monkeypatch.setattr(tasks, "execute_job", execute)
    monkeypatch.setattr(tasks.run_job, "delay", lambda *args: queued.append(args))

    def run():
        try:
            tasks.recover_orphaned_jobs()
            tasks.run_job(job_id)
            with pytest.raises(RuntimeError, match="task failed"):
                tasks.run_job(job_id, {"fail": True})
            tasks.run_job(job_id, {"action": "approve"})
            assert len(loops) == 4
            assert all(loop is loops[0] for loop in loops)
            assert not loops[0].is_closed()
            if sys.platform == "win32":
                assert isinstance(loops[0], asyncio.SelectorEventLoop)
        finally:
            tasks.close_worker_loop()
        assert loops[0].is_closed()
        tasks.close_worker_loop()  # 两个 Celery shutdown 信号不会重复关闭出错。
        assert tasks._worker_loop is None

    # pytest 的数据库 fixture 使用自己的长寿命循环，不能把它设为 worker 的循环。
    await asyncio.to_thread(run)
    assert queued == [(job_id, None)]


async def test_worker_replaces_closed_or_inherited_loop(monkeypatch):
    monkeypatch.setattr(tasks, "_worker_loop", None)
    monkeypatch.setattr(tasks, "_worker_loop_pid", None)

    def run():
        inherited = None
        try:
            first = tasks._get_worker_loop()
            first.close()
            inherited = tasks._get_worker_loop()
            assert inherited is not first
            tasks._worker_loop_pid = -1  # 模拟 fork 后继承父进程的全局变量。
            child = tasks._get_worker_loop()
            assert child is not inherited
            assert not child.is_closed()
        finally:
            tasks.close_worker_loop()
            if inherited is not None:
                inherited.close()

    await asyncio.to_thread(run)


async def test_worker_shutdown_finishes_pending_tasks_and_async_generators(monkeypatch):
    monkeypatch.setattr(tasks, "_worker_loop", None)
    monkeypatch.setattr(tasks, "_worker_loop_pid", None)
    finished = []

    async def pending():
        try:
            await asyncio.Event().wait()
        finally:
            finished.append("task")

    async def generate():
        try:
            yield 1
        finally:
            finished.append("generator")

    def run():
        loop = tasks._get_worker_loop()
        generator = generate()

        async def start():
            return await anext(generator)

        try:
            loop.create_task(pending())
            assert loop.run_until_complete(start()) == 1
        finally:
            tasks.close_worker_loop()
        assert loop.is_closed()

    await asyncio.to_thread(run)
    assert finished == ["task", "generator"]


def runner_fakes(monkeypatch, *, acquired=True, close_error=None):
    routers = []
    lock = SimpleNamespace(acquire=AsyncMock(return_value=acquired), release=AsyncMock(), reacquire=AsyncMock())
    redis = SimpleNamespace(lock=lambda *args, **kwargs: lock, aclose=AsyncMock())
    engine = SimpleNamespace(dispose=AsyncMock())
    sm = object()

    class FakeRouter:
        def __init__(self, sessionmaker, *, job_id):
            assert sessionmaker is sm
            self.job_id = job_id
            self.aclose = AsyncMock(side_effect=close_error)
            routers.append(self)

    monkeypatch.setattr(job_runner, "make_engine", lambda: engine)
    monkeypatch.setattr(job_runner, "make_sessionmaker", lambda _: sm)
    monkeypatch.setattr(job_runner, "Redis", SimpleNamespace(from_url=lambda *args, **kwargs: redis))
    monkeypatch.setattr(job_runner, "LLMRouter", FakeRouter)
    return routers, lock, redis, engine


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "duplicate"])
async def test_execute_job_closes_router_on_every_exit(monkeypatch, outcome):
    routers, lock, redis, engine = runner_fakes(monkeypatch, acquired=outcome != "duplicate")
    error = {"failure": RuntimeError("run failed"), "cancelled": asyncio.CancelledError()}.get(outcome)
    run = AsyncMock(side_effect=error)
    monkeypatch.setattr(job_runner, "_run", run)
    job_id = uuid.uuid4()

    if error is not None:
        with pytest.raises(type(error)):
            await job_runner.execute_job(job_id)
    else:
        await job_runner.execute_job(job_id)

    assert len(routers) == 1
    assert routers[0].job_id == job_id
    routers[0].aclose.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    if outcome == "duplicate":
        run.assert_not_awaited()
        lock.release.assert_not_awaited()
    else:
        assert run.await_args.args[-1] is routers[0]
        lock.release.assert_awaited_once()


async def test_execute_job_creates_separate_router_for_each_task(monkeypatch):
    routers, _, _, _ = runner_fakes(monkeypatch)
    monkeypatch.setattr(job_runner, "_run", AsyncMock())
    job_id = uuid.uuid4()
    await job_runner.execute_job(job_id)
    await job_runner.execute_job(job_id, {"action": "approve"})
    assert len(routers) == 2
    assert routers[0] is not routers[1]
    for router in routers:
        router.aclose.assert_awaited_once()


async def test_execute_job_still_closes_redis_and_engine_if_router_close_fails(monkeypatch):
    routers, lock, redis, engine = runner_fakes(monkeypatch, close_error=RuntimeError("close failed"))
    monkeypatch.setattr(job_runner, "_run", AsyncMock())
    with pytest.raises(RuntimeError, match="close failed"):
        await job_runner.execute_job(uuid.uuid4())
    routers[0].aclose.assert_awaited_once()
    lock.release.assert_awaited_once()
    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("error", [ValueError("original error"), asyncio.CancelledError()])
async def test_cleanup_failure_does_not_mask_original_error_or_cancellation(monkeypatch, error):
    _, _, redis, engine = runner_fakes(monkeypatch, close_error=RuntimeError("close failed"))
    monkeypatch.setattr(job_runner, "_run", AsyncMock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        await job_runner.execute_job(uuid.uuid4())
    assert caught.value is error
    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
