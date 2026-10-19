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
from app.services import book_saves
from app.services.jobs import LEGACY_SETUP_MESSAGE
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
            p.get("idea", ""),
            p.get("style_reference", ""),
            bool(p.get("ask")),
            mode=p.get("mode", "oneshot"),
            prefill=bool(p.get("prefill")),
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
    "setup_pitches": "setting_up",
    "setup_prefill": "setting_up",
    "setup_piece": "setting_up",
    "volume_review": "writing",
    "chapters_review": "writing",
    "segment_review": "writing",
    "trial_read": "writing",
    "chapter_stuck": "writing",
}
# 存档：这几步做完动了书，各存一档（谁、开头怎么说；开头是空的就只说改了什么，比如「写完第 12 章」）
WRITE_SAVES = {
    "plan_segment": ("chief", "主编定下了下一篇："),
    "split_segment": ("chief", "主编给这一篇分了卷："),
    "fill_segment": ("chief", "主编补齐了这一篇："),
    "fill_volume": ("chief", "主编补齐了这一卷："),
    "save_volume": ("chief", "主编拆好了这一卷的单元："),
    "volume_gate": ("chief", "卷纲定了："),
    "plan_chapters": ("chief", "主编出了章纲："),
    "revise_chapters": ("chief", "主编改了章纲："),
    "finalize": ("writer", ""),
    "reopen": ("lorekeeper", "重写之前，设定师撤掉了这一章记进设定的变化："),
    "recap_unit": ("lorekeeper", "设定师写了单元回顾："),
    "recap_volume": ("lorekeeper", "设定师写了卷回顾："),
}
SAVES_AFTER = {
    "write_book": WRITE_SAVES,
    "rewrite_chapter": WRITE_SAVES,
    "book_setup": {
        "concept": ("chief", "开书 · 定调："),
        "settings_focus": ("lorekeeper", "开书 · 重点设定："),
        "settings_rest": ("lorekeeper", "开书 · 其余设定："),
        "outline": ("chief", "开书 · 大纲："),
        "outline_chapters": ("chief", "开书 · 章纲："),
        "piece_persist": ("chief", "开书："),
        "finalize": ("chief", "开书定好了："),
    },
}


async def save_book(sm: async_sessionmaker[AsyncSession], book_id: uuid.UUID, actor: str, lead: str | None) -> None:
    async with sm() as session:
        await book_saves.safe_checkpoint(session, book_id, actor, lead=lead)


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

    emitter = Emitter(sm, redis, book_id, job_id)
    if kind == "book_setup" and params.get("flow") != 3:
        await emitter.say("system", LEGACY_SETUP_MESSAGE, kind="error")
        await _update_job(sm, redis, job_id, status="failed", error=LEGACY_SETUP_MESSAGE, finished_at=datetime.now(UTC))
        return
    build_graph, make_initial = GRAPHS[kind]
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
    # 编辑部动书之前：作者自己改过还没存的，先存一档
    async with sm() as session:
        await book_saves.before_ai(session, book_id)
    saves_after = SAVES_AFTER.get(kind, {})

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
                if kind == "book_setup" and params.get("restart_from"):
                    async with sm() as session:
                        old = await session.get(Job, uuid.UUID(params["restart_from"]))
                        book = await session.get(Book, book_id)
                        concept = dict(book.concept or {}) if book else {}
                    previous = (
                        await saver.aget_tuple({"configurable": {"thread_id": old.thread_id}})
                        if old is not None and old.book_id == book_id
                        else None
                    )
                    old_values = previous.checkpoint.get("channel_values", {}) if previous else {}
                    graph_input = book_setup.restart_state(params, old_values, concept)
                else:
                    graph_input = make_initial(params)
            async for update in graph.astream(graph_input, config, context=deps, stream_mode="updates"):
                for node in update if isinstance(update, dict) else ():
                    if node in saves_after:
                        await save_book(sm, book_id, *saves_after[node])
            snapshot = await graph.aget_state(config)
    except JobCancelled:
        await redis.delete(cancel_key(job_id))
        await save_book(sm, book_id, "system", "编辑部停下时：")
        await emitter.status("system", "任务已停止。")
        await _update_job(sm, redis, job_id, status="cancelled", finished_at=datetime.now(UTC))
        return
    except Exception as exc:  # noqa: BLE001  任务失败要记录原因，供作者「继续」
        log.exception("任务 %s 失败", job_id)
        message = str(exc) if isinstance(exc, LLMError) else f"{type(exc).__name__}: {exc}"
        await emitter.say("system", f"出错了：{message}", kind="error")
        await save_book(sm, book_id, "system", "编辑部出错停下时：")
        await _update_job(sm, redis, job_id, status="failed", error=message[:4000])
        return

    # 兜底：上面几步以外动过的书，停下来时存一档
    await save_book(sm, book_id, "system", "等你拍板时：" if snapshot.interrupts else "编辑部做完这一轮：")
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
