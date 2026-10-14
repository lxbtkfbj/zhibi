import asyncio
import logging
import uuid

from celery.signals import worker_ready
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.models import Job
from app.services.job_runner import execute_job, lock_key
from app.worker.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="zhibi.run_job")
def run_job(job_id: str, resume: dict | None = None) -> None:
    asyncio.run(execute_job(uuid.UUID(job_id), resume))


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
    for job_id in asyncio.run(_orphaned_jobs()):
        log.info("恢复中断的任务 %s（从检查点继续）", job_id)
        run_job.delay(job_id, None)
