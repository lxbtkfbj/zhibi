import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Job

ACTIVE_STATUSES = ("queued", "running", "waiting_author")
BUSY_STATUSES = ("queued", "running")


def new_setup_job(book: Book, ask: bool = False) -> Job:
    return Job(
        book_id=book.id,
        kind="book_setup",
        thread_id=f"setup-{book.id}-{uuid.uuid4().hex[:8]}",
        params={"idea": book.idea, "style_reference": book.style_reference, "ask": ask},
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
