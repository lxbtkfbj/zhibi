import asyncio
import logging
import os
import uuid

from celery.signals import worker_process_shutdown, worker_ready, worker_shutdown
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.models import Job
from app.services.job_runner import execute_job, lock_key
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)

_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_loop_pid: int | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """solo worker 的任务顺序执行，共用进程内的循环；不复用 fork 前的循环。"""
    global _worker_loop, _worker_loop_pid
    pid = os.getpid()
    if _worker_loop is None or _worker_loop.is_closed() or _worker_loop_pid != pid:
        # 遵循 app.__init__ 安装的策略，Windows 下仍是 psycopg 需要的 SelectorEventLoop。
        _worker_loop = asyncio.new_event_loop()
        _worker_loop_pid = pid
    asyncio.set_event_loop(_worker_loop)
    return _worker_loop


@worker_shutdown.connect
@worker_process_shutdown.connect
def close_worker_loop(**_: object) -> None:
    """正常停止时先收尾异步任务和生成器，再关闭循环（两个 shutdown 信号可重复调用）。"""
    global _worker_loop, _worker_loop_pid
    loop = _worker_loop
    if loop is None or _worker_loop_pid != os.getpid():
        return
    if loop.is_running():
        log.warning("worker 的事件循环仍在运行，暂不关闭")
        return
    try:
        if not loop.is_closed():
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor(timeout=5))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        _worker_loop = None
        _worker_loop_pid = None


@celery_app.task(name="zhibi.run_job")
def run_job(job_id: str, resume: dict | None = None) -> None:
    _get_worker_loop().run_until_complete(execute_job(uuid.UUID(job_id), resume))


async def _orphaned_jobs() -> list[str]:
    """找出状态是「运行中」但任务锁已过期的任务（上次 worker 崩溃或被强制关闭）。"""
    settings = get_settings()
    engine = make_engine()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with make_sessionmaker(engine)() as session:
            rows = (await session.execute(select(Job.id).where(Job.status == "running"))).scalars().all()
        return [str(job_id) for job_id in rows if not await redis.exists(lock_key(job_id))]
    finally:
        await redis.aclose()
        await engine.dispose()


@worker_ready.connect
def recover_orphaned_jobs(**_: object) -> None:
    for job_id in _get_worker_loop().run_until_complete(_orphaned_jobs()):
        log.info("恢复中断的任务 %s（从检查点继续）", job_id)
        run_job.delay(job_id, None)
