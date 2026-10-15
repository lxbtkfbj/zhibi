"""在 worker 里执行一个后台任务：驱动对应的 LangGraph 图，处理拍板暂停、断点续跑、取消与失败。"""

import asyncio
import contextlib
import logging
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph
from langgraph.types import Command
from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.graphs import book_setup, write_book
from app.graphs.deps import GraphDeps, JobCancelled, cancel_key
from app.llm.router import LLMError, LLMRouter
from app.models import Book, Job
from app.services.meeting import Emitter, job_dict, publish

log = logging.getLogger(__name__)

# 任务锁带心跳：worker 活着就不断续期；worker 崩溃后锁很快过期，任务可以被恢复
LOCK_TIMEOUT_S = 60
LOCK_RENEW_S = 20

# 任务类型 → (建图函数, 根据任务参数生成初始状态)
GRAPHS: dict[str, tuple[Callable[[], StateGraph], Callable[[dict], dict]]] = {
    "book_setup": (
        book_setup.build_setup_graph,
        lambda p: book_setup.initial_state(
            p.get("idea", ""), p.get("style_reference", ""), bool(p.get("ask")), mode=p.get("mode", "oneshot")
        ),
    ),
    "write_book": (write_book.build_write_graph, write_book.initial_state),
    "rewrite_chapter": (write_book.build_rewrite_graph, write_book.rewrite_initial_state),
}

BOOK_STATUS_WHILE_RUNNING = {"book_setup": "setting_up", "write_book": "writing"}
# 按等待作者处理的内容决定书的状态：回答动笔前的提问时，方案还没出来
BOOK_STATUS_WHILE_WAITING = {
    "setup_review": "awaiting_approval",
    "setup_questions": "setting_up",
    "setup_directions": "setting_up",
    "setup_piece": "setting_up",
    "volume_review": "writing",
    "trial_read": "writing",
    "chapter_stuck": "writing",
}
# 写书循环一章要走好几步，整本书远超 LangGraph 默认的 25 步上限
RECURSION_LIMIT = 200_000


def lock_key(job_id: uuid.UUID | str) -> str:
    return f"zhibi:joblock:{job_id}"


async def _update_job(
    sm: async_sessionmaker[AsyncSession], redis: Redis, job_id: uuid.UUID, book_status: str | None = None, **fields: Any
) -> None:
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        if book_status:
            book = await session.get(Book, job.book_id)
            if book is not None:
                book.status = book_status
        await session.commit()
        await session.refresh(job)
        await publish(redis, job.book_id, "job", job_dict(job))


async def execute_job(job_id: uuid.UUID, resume: dict | None = None, *, checkpoint_dsn: str | None = None) -> None:
    settings = get_settings()
    engine = make_engine()
    sm = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    router = LLMRouter(sm, job_id=job_id)
    lock = redis.lock(lock_key(job_id), timeout=LOCK_TIMEOUT_S, blocking=False)
    try:
        if not await lock.acquire():
            log.info("任务 %s 已有 worker 在执行，跳过", job_id)
            return
        renew = asyncio.create_task(_keep_lock(lock))
        try:
            await _run(job_id, resume, sm, redis, checkpoint_dsn or settings.checkpoint_dsn, router)
        finally:
            renew.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew
            with contextlib.suppress(LockError):
                await lock.release()
    finally:
        active_error = sys.exception()
        try:
            try:
                await router.aclose()
            finally:
                try:
                    await redis.aclose()
                finally:
                    await engine.dispose()
        except Exception:
            if active_error is None:
                raise
            # 清理错误不能覆盖真正的任务失败，尤其不能把任务取消变成另一种异常。
            log.exception("任务 %s 释放资源时出错，保留原始异常", job_id)


async def _keep_lock(lock) -> None:
    while True:
        await asyncio.sleep(LOCK_RENEW_S)
        with contextlib.suppress(LockError):
            await lock.reacquire()


async def _run(
    job_id: uuid.UUID,
    resume: dict | None,
    sm: async_sessionmaker[AsyncSession],
    redis: Redis,
    dsn: str,
    router: LLMRouter,
) -> None:
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status in ("succeeded", "cancelled"):
            return
        if resume is None and job.status == "waiting_author":
            # 正在等作者拍板，没有新的决定就无事可做（例如重复投递的消息）
            return
        kind, book_id, thread_id, params = job.kind, job.book_id, job.thread_id, dict(job.params or {})

    build_graph, make_initial = GRAPHS[kind]
    emitter = Emitter(sm, redis, book_id, job_id)
    router.book_id = book_id
    deps = GraphDeps(
        sessionmaker=sm,
        redis=redis,
        llm=router,
        emit=emitter,
        book_id=book_id,
        job_id=job_id,
    )
    await _update_job(sm, redis, job_id, BOOK_STATUS_WHILE_RUNNING.get(kind), status="running", pending=None, error="")

    try:
        async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
            await saver.setup()
            graph = build_graph().compile(checkpointer=saver)
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
            snapshot = await graph.aget_state(config)
            if resume is not None:
                graph_input: Any = Command(resume=resume)
            elif snapshot.next:
                # 上次中断在半路（worker 重启、失败后点「继续」）：从检查点接着跑
                await emitter.status("system", "从上次中断的地方继续…")
                graph_input = None
            else:
                graph_input = make_initial(params)
            async for _ in graph.astream(graph_input, config, context=deps, stream_mode="updates"):
                pass
            snapshot = await graph.aget_state(config)
    except JobCancelled:
        await redis.delete(cancel_key(job_id))
        await emitter.status("system", "任务已停止。")
        await _update_job(sm, redis, job_id, status="cancelled", finished_at=datetime.now(UTC))
        return
    except Exception as exc:  # noqa: BLE001  任务失败要记录原因，供作者「继续」
        log.exception("任务 %s 失败", job_id)
        message = str(exc) if isinstance(exc, LLMError) else f"{type(exc).__name__}: {exc}"
        await emitter.say("system", f"出错了：{message}", kind="error")
        await _update_job(sm, redis, job_id, status="failed", error=message[:4000])
        return

    if snapshot.interrupts:
        pending = snapshot.interrupts[0].value
        await _update_job(
            sm,
            redis,
            job_id,
            BOOK_STATUS_WHILE_WAITING.get(pending.get("kind", "")),
            status="waiting_author",
            pending=pending,
        )
    else:
        await _update_job(sm, redis, job_id, status="succeeded", pending=None, finished_at=datetime.now(UTC))
