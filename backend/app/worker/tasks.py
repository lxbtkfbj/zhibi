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
from app.services.job_runner import GRAPHS, LOCK_TIMEOUT_S, execute_job, lock_key
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


@celery_app.task(name="zhibi.run_teardown", queue="teardown")
def run_teardown(job_id: str) -> None:
    _get_worker_loop().run_until_complete(execute_job(uuid.UUID(job_id)))


async def _orphaned_jobs(kinds: tuple[str, ...] | None = None) -> list[str]:
    """找出状态是「运行中」但任务锁已过期的任务（上次 worker 崩溃或被强制关闭）。"""
    settings = get_settings()
    engine = make_engine()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with make_sessionmaker(engine)() as session:
            rows = (
                await session.scalars(
                    select(Job.id).where(Job.status == "running", Job.kind.in_(kinds or tuple(GRAPHS)))
                )
            ).all()
        orphaned = RecoveryJobs()
        for job_id in rows:
            if await redis.exists(lock_key(job_id)):
                continue
            if kinds != ("teardown",):
                orphaned.append(str(job_id))
                continue
            # 同时启动的两个 worker 不能各自投递同一个断活；执行仍由带心跳的任务锁互斥。
            # claim 有界过期，投递前崩溃不会留下永久不能恢复的标记。
            token = uuid.uuid4().hex
            if await redis.set(f"zhibi:recover:{job_id}", token, nx=True, ex=LOCK_TIMEOUT_S):
                orphaned.append(str(job_id))
                orphaned.claims[str(job_id)] = token
            else:
                orphaned.retry = True
        return orphaned
    finally:
        await redis.aclose()
        await engine.dispose()


class RecoveryJobs(list):
    """保持列表接口，同时带回本进程的恢复租约及需要延后重扫的标记。"""

    def __init__(self):
        super().__init__()
        self.claims: dict[str, str] = {}
        self.retry = False


async def _release_recovery_claim(job_id: str, token: str) -> None:
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            f"zhibi:recover:{job_id}",
            token,
        )
    finally:
        await redis.aclose()


async def _dispatch_orphaned_teardowns() -> bool:
    jobs = await _orphaned_jobs(("teardown",))
    retry = getattr(jobs, "retry", False)
    for job_id in jobs:
        try:
            log.info("恢复中断的拆书任务 %s（按章记录继续）", job_id)
            run_teardown.apply_async(args=[job_id], queue="teardown")
        except Exception:
            token = getattr(jobs, "claims", {}).get(job_id)
            if token:
                await _release_recovery_claim(job_id, token)
            retry = True
            log.exception("投递恢复的拆书任务 %s 失败，稍后再试", job_id)
    return retry


def _recover_teardown_jobs(sender) -> None:
    # Consumer timer 可能在自己的线程回调；不能跨线程借正在跑任务的 worker loop。
    retry = asyncio.run(_dispatch_orphaned_teardowns())
    timer = getattr(sender, "timer", None)
    if retry and timer is not None:
        # A 进程领取后、投递前崩溃，B 会在租约过期后重扫，而非等作者重启。
        timer.call_after(LOCK_TIMEOUT_S + 1, _recover_teardown_jobs, args=(sender,))


@worker_ready.connect
def recover_orphaned_jobs(sender=None, **_: object) -> None:
    # worker_ready 的 sender 是 Consumer；按它实际订阅的队列恢复，不能把网页
    # 后端独自运行、没有任务锁的 outline_expand 捡给 LangGraph worker。
    consumer = getattr(sender, "task_consumer", None)
    queues = {queue.name for queue in getattr(consumer, "queues", ())}
    if not queues:
        queues = {"zhibi"}
    if "zhibi" in queues:
        for job_id in _get_worker_loop().run_until_complete(_orphaned_jobs()):
            log.info("恢复中断的写作任务 %s（从检查点继续）", job_id)
            run_job.delay(job_id, None)
    if "teardown" in queues:
        _recover_teardown_jobs(sender)
