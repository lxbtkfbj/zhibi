"""拆书的开始与停止；所有入口共用书锁，排队取消还原开拆前的状态。"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.graphs.deps import cancel_key
from app.models import Book, Chapter, Job
from app.services import book_saves, jobs
from app.services.library import lock_book
from app.services.meeting import job_dict, post_message, publish


async def active(session, book_id):
    return await session.scalar(
        select(Job)
        .where(Job.book_id == book_id, Job.kind == "teardown", Job.status.in_(jobs.BUSY_STATUSES))
        .order_by(Job.created_at.desc())
        .limit(1)
        .with_for_update()
    )


async def _validate_start(session, book, upto):
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    chapters = (await session.execute(select(Chapter.index, Chapter.teardown).where(Chapter.book_id == book.id))).all()
    meta = book.teardown or {}
    retry = meta.get("stage") == "done" and any(record.get("read_failed") for _, record in chapters)
    if meta.get("stage") not in {"imported", "stopped"} and not retry:
        raise HTTPException(409, "这本书现在不能开始拆")
    if await active(session, book.id):
        raise HTTPException(409, "这本书正在拆，请先停下")
    total = len(chapters)
    if not total:
        raise HTTPException(422, "这本书还没有原文")
    last = max((index for index, record in chapters if record.get("read_version") is not None), default=0)
    if upto is not None and upto <= last and not retry:
        raise HTTPException(422, f"已经拆到第 {last} 章了，要拆得更多才能接着拆")
    return total, upto if not retry and upto is not None and upto < total else None


async def start(session, redis, book: Book, upto: int | None = None):
    await lock_book(session, book.id)
    await session.refresh(book, with_for_update=True)
    await _validate_start(session, book, upto)
    # 即使刚导入、和上一档内容相同，也保留明确的开拆前边界。
    await book_saves.safe_checkpoint(session, book.id, title="开始拆书前", force=True)
    # 存档会提交；重新持书锁并校验，不能让双击开始造出两个任务。
    await lock_book(session, book.id)
    await session.refresh(book, with_for_update=True)
    total, upto = await _validate_start(session, book, upto)
    before = dict(book.teardown or {})
    target = upto or total
    chapters = (
        await session.execute(
            select(Chapter.index, Chapter.teardown, Chapter.unit_id).where(
                Chapter.book_id == book.id, Chapter.index <= target
            )
        )
    ).all()
    read = sum(meta.get("read_version") is not None for _, meta, _ in chapters)
    job = Job(
        book_id=book.id,
        kind="teardown",
        thread_id=f"teardown-{book.id}-{uuid.uuid4().hex[:8]}",
        params={"upto": upto, "previous_stage": before["stage"], "previous_teardown": before},
        pending={
            "teardown": {
                "doing": "queued",
                "reading": [],
                "read": read,
                "target": target,
                "total": total,
                "units_upto": max((index for index, _, unit_id in chapters if unit_id), default=0),
                "parallel": 4,
                "eta_seconds": None,
                "failed": sorted(index for index, meta, _ in chapters if meta.get("read_failed")),
            }
        },
    )
    session.add(job)
    book.teardown = {**before, "stage": "queued", "upto": upto}
    book.teardown.pop("stop_reason", None)
    book.teardown.pop("stop_note", None)
    await session.commit()
    await session.refresh(job)
    await publish(redis, book.id, "job", job_dict(job))
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=job.id,
        speaker="lorekeeper",
        kind="speech",
        content=f"开始拆了：读到第 {target} 章{'，读到最后' if upto is None else ''}。读好的章纲随时出现在大纲和正文里。",
    )
    jobs.enqueue_teardown(job.id)
    return job


async def stop(session, redis, book: Book):
    await lock_book(session, book.id)
    await session.refresh(book, with_for_update=True)
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    job = await active(session, book.id)
    if job is None:
        raise HTTPException(409, "这本书没有正在拆的任务")
    await redis.set(cancel_key(job.id), "1", ex=24 * 3600)
    if job.status == "queued":
        previous = (job.params or {}).get("previous_teardown")
        book.teardown = (
            dict(previous)
            if previous
            else {**(book.teardown or {}), "stage": (job.params or {}).get("previous_stage", "imported")}
        )
        job.status = "cancelled"
        job.pending = None
        job.finished_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(job)
        await publish(redis, book.id, "job", job_dict(job))
    else:
        # 保持 running：worker 把已经在手上的几批写完以后才落 stopped 和存档。
        await session.commit()
    return job
