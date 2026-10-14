import uuid

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, ensure_idle, get_book, get_redis
from app.models import Book, Job, PlotUnit, Volume
from app.schemas import (
    BookCreate,
    BookCreated,
    BookDetail,
    BookPatch,
    BookSummary,
    JobOut,
    OutlineOut,
    UnitOut,
    UnitPatch,
    VolumeOut,
    VolumePatch,
)
from app.services import jobs
from app.services.meeting import post_message

router = APIRouter(tags=["books"])


def summary(book: Book, job_status: str | None = None) -> BookSummary:
    out = BookSummary.model_validate(book)
    out.logline = (book.concept or {}).get("logline", "")
    out.job_status = job_status
    return out


async def detail(session: AsyncSession, book: Book) -> BookDetail:
    out = BookDetail.model_validate(book)
    out.logline = (book.concept or {}).get("logline", "")
    job = await jobs.active_job(session, book.id)
    out.active_job = JobOut.model_validate(job) if job else None
    out.job_status = job.status if job else None
    return out


@router.get("/books", response_model=list[BookSummary])
async def list_books(session: AsyncSession = SessionDep) -> list[BookSummary]:
    rows = (await session.execute(select(Book).order_by(Book.updated_at.desc()))).scalars().all()
    latest = (
        await session.execute(
            select(Job.book_id, Job.status).distinct(Job.book_id).order_by(Job.book_id, Job.created_at.desc())
        )
    ).all()
    status_by_book = {book_id: status for book_id, status in latest}
    return [summary(b, status_by_book.get(b.id)) for b in rows]


@router.post("/books", response_model=BookCreated, status_code=201)
async def create_book(
    body: BookCreate, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> BookCreated:
    book = Book(idea=body.idea.strip(), style_reference=body.style_reference.strip(), source="new", status="setting_up")
    session.add(book)
    await session.flush()
    job = jobs.new_setup_job(book, ask=body.ask)
    session.add(job)
    await session.commit()
    await session.refresh(book)
    await session.refresh(job)
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=job.id,
        speaker="author",
        kind="speech",
        content=f"我想写这样一本书：{book.idea}",
    )
    jobs.enqueue(job.id)
    return BookCreated(book=await detail(session, book), job=JobOut.model_validate(job))


@router.get("/books/{book_id}", response_model=BookDetail)
async def get_book_detail(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> BookDetail:
    return await detail(session, book)


@router.patch("/books/{book_id}", response_model=BookDetail)
async def update_book(
    body: BookPatch, book: Book = Depends(get_book), session: AsyncSession = SessionDep
) -> BookDetail:
    await ensure_idle(session, book.id)
    if body.title is not None:
        book.title = body.title
        book.concept = {**(book.concept or {}), "title": body.title}
    if body.style_reference is not None:
        book.style_reference = body.style_reference
    if body.concept is not None:
        book.concept = {**(book.concept or {}), **body.concept}
        book.title = book.concept.get("title") or book.title
    if body.spine is not None:
        book.spine = {**(book.spine or {}), **body.spine}
    await session.commit()
    await session.refresh(book)
    return await detail(session, book)


@router.delete("/books/{book_id}", status_code=204)
async def delete_book(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> None:
    if await jobs.is_busy(session, book.id):
        raise HTTPException(409, "编辑部正在工作，请先停止任务再删除")
    await session.delete(book)
    await session.commit()


# ---------- 大纲 ----------


@router.get("/books/{book_id}/outline", response_model=OutlineOut)
async def get_outline(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> OutlineOut:
    volumes = (
        (
            await session.execute(
                select(Volume)
                .where(Volume.book_id == book.id)
                .order_by(Volume.index)
                .options(selectinload(Volume.units))
            )
        )
        .scalars()
        .all()
    )
    return OutlineOut(concept=book.concept or {}, volumes=[VolumeOut.model_validate(v) for v in volumes])


@router.patch("/volumes/{volume_id}", response_model=VolumeOut)
async def update_volume(volume_id: uuid.UUID, body: VolumePatch, session: AsyncSession = SessionDep) -> VolumeOut:
    volume = await session.get(Volume, volume_id, options=[selectinload(Volume.units)])
    if volume is None:
        raise HTTPException(404, "卷不存在")
    await ensure_idle(session, volume.book_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(volume, key, value)
    await session.commit()
    await session.refresh(volume, attribute_names=["units", "updated_at"])
    return VolumeOut.model_validate(volume)


@router.patch("/units/{unit_id}", response_model=UnitOut)
async def update_unit(unit_id: uuid.UUID, body: UnitPatch, session: AsyncSession = SessionDep) -> UnitOut:
    unit = await session.get(PlotUnit, unit_id)
    if unit is None:
        raise HTTPException(404, "剧情单元不存在")
    await ensure_idle(session, unit.book_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(unit, key, value)
    await session.commit()
    await session.refresh(unit)
    return UnitOut.model_validate(unit)
