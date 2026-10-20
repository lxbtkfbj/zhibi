"""调拆书提示词的单步重跑；仍用普通任务锁，重启也能恢复这一步。"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select

from app.graphs.deps import JobCancelled, cancel_key
from app.models import Book, Chapter, Job, PlotUnit, Volume
from app.services import book_saves, jobs
from app.services.library import lock_book
from app.services.meeting import job_dict, publish


async def plan(session, book_id: uuid.UUID, step: str, first: int | None, last: int | None) -> dict:
    """只查询，不改书；调用次数是首轮预计值，修复和悬挂尾部可能增加。"""
    from app.services.teardown_runner import make_batches

    book = await session.get(Book, book_id)
    if book is None or book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    if (book.teardown or {}).get("stage") == "confirming":
        raise HTTPException(409, "请先导入原文")
    busy = await session.scalar(
        select(Job.id).where(Job.book_id == book_id, Job.status.in_(jobs.ACTIVE_STATUSES)).limit(1)
    )
    if busy:
        raise HTTPException(409, "正在拆，点「停下」才能改")
    total = await session.scalar(select(func.max(Chapter.index)).where(Chapter.book_id == book_id)) or 0
    if step not in ("read", "units", "volumes", "settings", "merits", "arcs", "ending", "waits"):
        raise HTTPException(422, "步骤只能是 read、units、volumes、settings、merits、arcs、ending 或 waits")
    if step == "read" and (first is None or last is None):
        raise HTTPException(422, "重读要同时给 --from 和 --to")
    if step == "volumes" and (first is not None or last is not None):
        raise HTTPException(422, "归卷不接受 --from 或 --to")
    if step in ("settings", "merits") and (first is not None or last is not None):
        raise HTTPException(422, "整理设定和好在哪不接受 --from 或 --to")
    if step in ("arcs", "ending", "waits") and (first is not None or last is not None):
        raise HTTPException(422, "归篇、全书结局和读者在等的事不接受 --from 或 --to")
    if step == "units" and last is not None:
        raise HTTPException(422, "归单元不接受 --to")
    if (first is not None and not 1 <= first <= total) or (last is not None and not (first or 1) <= last <= total):
        raise HTTPException(422, f"章号必须在第 1–{total} 章以内，且起点不能大于终点")
    if step in ("arcs", "ending", "waits"):
        from app.services.teardown_closing import closed_volumes, wait_batches

        chapters = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index))
        )
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index)))
        if step == "arcs" and len(closed_volumes(book, volumes)) < 3:
            raise HTTPException(422, "收住的卷不到 3 卷，不用归篇")
        if step == "ending" and (
            not chapters
            or any(
                not c.unit_id
                or ((c.teardown or {}).get("read_version") is None and "read_failed" not in (c.teardown or {}))
                for c in chapters
            )
            or (book.teardown or {}).get("open_volume_id")
            or any(not v.summary for v in volumes)
        ):
            raise HTTPException(422, "还没拆到最后一章，写不了结局")
        calls = len(wait_batches(chapters)) if step == "waits" else 1
    elif step in ("settings", "merits"):
        from app.services.teardown_settings import estimate_calls

        calls = await estimate_calls(session, book, merits_only=step == "merits")
    elif step == "read":
        rows = list(
            await session.scalars(
                select(Chapter)
                .where(Chapter.book_id == book_id, Chapter.index >= first, Chapter.index <= last)
                .order_by(Chapter.index)
            )
        )
        calls = len(make_batches(rows))
    elif step == "units":
        count = (
            await session.scalar(
                select(func.count())
                .select_from(Chapter)
                .where(
                    Chapter.book_id == book_id,
                    Chapter.index >= (first or 1),
                    Chapter.teardown["read_version"].astext.is_not(None),
                )
            )
            or 0
        )
        calls = (count + 39) // 40
    elif (book.teardown or {}).get("original_volumes"):
        calls = await session.scalar(select(func.count()).select_from(Volume).where(Volume.book_id == book_id)) or 0
    else:
        chapters = (
            await session.scalar(select(func.sum(PlotUnit.chapter_count)).where(PlotUnit.book_id == book_id)) or 0
        )
        calls = (chapters + 99) // 100
    return {"book": str(book_id), "title": book.title, "step": step, "from": first, "to": last, "calls": calls}


async def prepare(session, book_id, step, first, last, *, force=False) -> Job:
    await lock_book(session, book_id)
    await plan(session, book_id, step, first, last)
    book = await session.get(Book, book_id, populate_existing=True)
    previous = dict(book.teardown or {})
    job = Job(
        book_id=book_id,
        kind="teardown",
        status="queued",
        thread_id=f"teardown-rerun-{uuid.uuid4()}",
        params={"rerun": step, "from": first, "to": last, "previous_teardown": previous, "force": force},
    )
    session.add(job)
    await session.commit()
    return job


async def run_rerun(job_id, sm, redis, router):
    from app.services.teardown_runner import Runner

    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status in ("succeeded", "cancelled"):
            return
        book_id, params = job.book_id, dict(job.params)
        job.status, job.error = "running", ""
        await session.commit()
        await session.refresh(job)
        await publish(redis, book_id, "job", job_dict(job))
    router.book_id = book_id
    try:
        runner = Runner(job_id, sm, redis, router)
        await runner.initialize(book_id)
        step = params["rerun"]
        if step == "read":
            await runner.read_range(params["from"], params["to"])
        elif step == "units":
            await runner.regroup_units(params.get("from"))
        elif step == "volumes":
            await runner.regroup_volumes()
        elif step in ("arcs", "ending", "waits"):
            from app.services.teardown_closing import collect_arcs, collect_ending, collect_waits

            if step == "arcs":
                book, chapters, _, volumes = await runner.snapshot()
                final = (
                    bool(chapters)
                    and all(
                        c.unit_id
                        and ((c.teardown or {}).get("read_version") is not None or "read_failed" in (c.teardown or {}))
                        for c in chapters
                    )
                    and not (book.teardown or {}).get("open_volume_id")
                    and all(v.summary for v in volumes)
                )
                await collect_arcs(runner, final=final, force=params.get("force", False))
            elif step == "ending":
                await collect_ending(runner, force=params.get("force", False))
            else:
                await collect_waits(runner, force=True)
        else:
            from app.services.teardown_settings import collect_settings

            await collect_settings(runner, force=True, merits_only=step == "merits")
        async with sm() as session:
            await book_saves.checkpoint(session, book_id, "system", f"重跑：{step}", force=True)
        status, error = "succeeded", ""
    except JobCancelled:
        status, error = "cancelled", ""
        async with sm() as session:
            if await session.get(Book, book_id) is not None:
                await book_saves.checkpoint(session, book_id, "system", "停下拆书", force=True)
        await redis.delete(cancel_key(job_id))
    except Exception as exc:  # noqa: BLE001 重跑也要保留失败状态和已成功的记录
        status, error = "failed", str(exc)[:4000]
    async with sm() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        job.status, job.error, job.finished_at = status, error, datetime.now(UTC)
        await session.commit()
        await session.refresh(job)
        await publish(redis, book_id, "job", job_dict(job))
