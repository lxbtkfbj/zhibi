import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Chapter, Job

ACTIVE_STATUSES = ("queued", "running", "waiting_author")
BUSY_STATUSES = ("queued", "running")
LEGACY_SETUP_MESSAGE = (
    "这个开书任务是按旧流程开的，开书流程已经更新。请点「按新流程重开」："
    "保留你的点子、作者要求、已选的方向和已确认的定调，其余按新步骤重做。"
)


def is_legacy_setup(job: Job) -> bool:
    return job.kind == "book_setup" and (job.params or {}).get("flow") != 3


def new_setup_job(book: Book, ask: bool = False, mode: str | None = None) -> Job:
    return Job(
        book_id=book.id,
        kind="book_setup",
        thread_id=f"setup-{book.id}-{uuid.uuid4().hex[:8]}",
        params={
            "flow": 3,
            "idea": book.idea,
            "style_reference": book.style_reference,
            "mode": mode or (book.settings or {}).get("setup_mode", "oneshot"),
        },
    )


def new_write_job(book: Book, until: str, count: int) -> Job:
    return Job(
        book_id=book.id,
        kind="write_book",
        thread_id=f"write-{book.id}-{uuid.uuid4().hex[:8]}",
        params={"until": until, "count": count},
    )


def new_rewrite_job(book: Book, chapter: Chapter, feedback: str) -> Job:
    """作者按自己的意见重写一章已定稿的章节。"""
    return Job(
        book_id=book.id,
        kind="rewrite_chapter",
        thread_id=f"rewrite-{book.id}-{chapter.index}-{uuid.uuid4().hex[:8]}",
        params={
            "chapter_id": str(chapter.id),
            "index": chapter.index,
            "title": chapter.title,
            "unit_id": str(chapter.unit_id) if chapter.unit_id else "",
            "volume_id": str(chapter.volume_id) if chapter.volume_id else "",
            "feedback": feedback,
        },
    )


# 等作者拍板、可以用「批准 / 提意见」回应的内容
DECISION_KINDS = (
    "setup_review",
    "volume_review",
    "trial_read",
    "chapter_stuck",
    "setup_pitches",
    "setup_piece",
    "segment_review",
)


def pending_kind(job: Job) -> str:
    return (job.pending or {}).get("kind", "") if job.status == "waiting_author" else ""


async def active_job(session: AsyncSession, book_id: uuid.UUID) -> Job | None:
    """当前进行中（含等待拍板）的任务；没有则返回最近一个失败的任务，方便作者点「继续」。"""
    rows = (
        (await session.execute(select(Job).where(Job.book_id == book_id).order_by(Job.created_at.desc()).limit(5)))
        .scalars()
        .all()
    )
    for job in rows:
        if job.status in ACTIVE_STATUSES:
            return job
    return rows[0] if rows and rows[0].status == "failed" else None


async def is_busy(session: AsyncSession, book_id: uuid.UUID) -> bool:
    found = await session.scalar(select(Job.id).where(Job.book_id == book_id, Job.status.in_(BUSY_STATUSES)).limit(1))
    return found is not None


def enqueue(job_id: uuid.UUID, resume: dict | None = None) -> None:
    """投递给 Celery worker。测试中会被替换。"""
    from app.worker.tasks import run_job

    run_job.delay(str(job_id), resume)
