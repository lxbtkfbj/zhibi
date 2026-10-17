import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.glossary import clean_techniques
from app.api.book_settings import new_book_defaults
from app.api.deps import SessionDep, ensure_idle, get_book, get_redis
from app.api.story_map import validate_node
from app.models import Book, Chapter, Job, PlotUnit, StoryNode, StoryThread, Volume
from app.schemas import (
    BookCreate,
    BookCreated,
    BookDetail,
    BookPatch,
    BookSummary,
    ChapterBrief,
    ChapterOut,
    ChapterPatch,
    JobOut,
    OutlineOut,
    RewriteRequest,
    ThreadOut,
    ThreadPatch,
    UnitOut,
    UnitPatch,
    VolumeOut,
    VolumePatch,
    WriteRequest,
)
from app.services import jobs, writing_store
from app.services.library import lock_book
from app.services.meeting import post_message
from app.services.versions import record_version, snapshot_of

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
    count, words = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Chapter.word_count), 0)).where(
                Chapter.book_id == book.id, Chapter.status == "final"
            )
        )
    ).one()
    out.chapters_final, out.words_final = int(count), int(words)
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
    book.settings = await new_book_defaults(session)
    mode = body.mode or book.settings.get("setup_mode", "puzzle")
    book.settings = {**book.settings, "setup_mode": mode}
    session.add(book)
    await session.flush()
    job = jobs.new_setup_job(book, ask=body.ask, mode=mode)
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
    body: BookPatch,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> BookDetail:
    await lock_book(session, book.id)
    await session.refresh(book, with_for_update=True)
    await ensure_idle(session, book.id)
    before = snapshot_of(book)
    if body.title is not None:
        book.title = body.title
        book.concept = {**(book.concept or {}), "title": body.title}
    if body.style_reference is not None:
        book.style_reference = body.style_reference
    if body.concept is not None:
        book.concept = {**(book.concept or {}), **body.concept}
        book.title = book.concept.get("title") or book.title
    if body.spine is not None:
        if set(body.spine) - {"core_conflict", "theme", "protagonist_arc"}:
            raise HTTPException(422, "主线骨架只保存核心矛盾、主题和主角成长弧；请通过节点接口编辑关键节点")
        book.spine = {**(book.spine or {}), **body.spine}
    for field in ("protagonist", "world"):
        card = getattr(body, field)
        if card is not None:
            setattr(book, field, {**(getattr(book, field) or {}), **card.model_dump(exclude_unset=True)})
    if body.concept is not None or body.title is not None:
        await record_version(session, book.id, "concept", book, "author", before=before)
    if body.concept is not None and "story" in body.concept:
        from app.api.library_ai import review_concept_change

        await review_concept_change(session, redis, book.id, before.get("story", ""))
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
    await lock_book(session, volume.book_id)
    await ensure_idle(session, volume.book_id)
    volume = await session.scalar(
        select(Volume)
        .where(Volume.id == volume_id)
        .with_for_update()
        .execution_options(populate_existing=True)
        .options(selectinload(Volume.units))
    )
    if volume is None:
        raise HTTPException(404, "卷不存在")
    before = snapshot_of(volume)
    await validate_node(session, volume.book_id, body.target_node_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "techniques":
            value = clean_techniques(value)
        setattr(volume, key, value)
    await record_version(session, volume.book_id, "volume", volume, "author", before=before)
    await session.commit()
    await session.refresh(volume, attribute_names=["units", "updated_at"])
    return VolumeOut.model_validate(volume)


@router.patch("/units/{unit_id}", response_model=UnitOut)
async def update_unit(unit_id: uuid.UUID, body: UnitPatch, session: AsyncSession = SessionDep) -> UnitOut:
    unit = await session.get(PlotUnit, unit_id)
    if unit is None:
        raise HTTPException(404, "剧情单元不存在")
    await lock_book(session, unit.book_id)
    await ensure_idle(session, unit.book_id)
    unit = await session.scalar(
        select(PlotUnit).where(PlotUnit.id == unit_id).with_for_update().execution_options(populate_existing=True)
    )
    if unit is None:
        raise HTTPException(404, "剧情单元不存在")
    before = snapshot_of(unit)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "techniques":
            value = clean_techniques(value)
        setattr(unit, key, value)
    await record_version(session, unit.book_id, "unit", unit, "author", before=before)
    await session.commit()
    await session.refresh(unit)
    return UnitOut.model_validate(unit)


# ---------- 线索 ----------


@router.get("/books/{book_id}/threads", response_model=list[ThreadOut])
async def list_threads(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> list[ThreadOut]:
    rows = (
        (await session.execute(select(StoryThread).where(StoryThread.book_id == book.id).order_by(StoryThread.index)))
        .scalars()
        .all()
    )
    return [ThreadOut.model_validate(t) for t in rows]


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(thread_id: uuid.UUID, body: ThreadPatch, session: AsyncSession = SessionDep) -> ThreadOut:
    thread = await session.get(StoryThread, thread_id)
    if thread is None:
        raise HTTPException(404, "线索不存在")
    await ensure_idle(session, thread.book_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(thread, key, value)
    await session.commit()
    await session.refresh(thread)
    return ThreadOut.model_validate(thread)


# ---------- 章节 ----------


@router.get("/books/{book_id}/chapters", response_model=list[ChapterBrief])
async def list_chapters(
    book: Book = Depends(get_book), volume: int | None = None, session: AsyncSession = SessionDep
) -> list[ChapterBrief]:
    """全书章节目录；指定 volume 时只列这一卷，并带上章纲。"""
    stmt = select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)
    if volume is not None:
        stmt = stmt.join(Volume, Chapter.volume_id == Volume.id).where(Volume.index == volume)
    rows = (await session.execute(stmt)).scalars().all()
    out = []
    for c in rows:
        brief = ChapterBrief.model_validate(c)
        brief.outline = c.outline if volume is not None else None
        out.append(brief)
    return out


async def _chapter(session: AsyncSession, book_id: uuid.UUID, index: int) -> Chapter:
    chapter = (
        await session.execute(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == index))
    ).scalar()
    if chapter is None:
        raise HTTPException(404, "这一章还不存在")
    return chapter


@router.get("/books/{book_id}/chapters/{index}", response_model=ChapterOut)
async def get_chapter(index: int, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> ChapterOut:
    return ChapterOut.model_validate(await _chapter(session, book.id, index))


@router.patch("/books/{book_id}/chapters/{index}", response_model=ChapterOut)
async def update_chapter(
    index: int, body: ChapterPatch, book: Book = Depends(get_book), session: AsyncSession = SessionDep
) -> ChapterOut:
    await ensure_idle(session, book.id)
    chapter = await _chapter(session, book.id, index)
    if body.title is not None:
        chapter.title = body.title
    if body.content is not None:
        chapter.content = body.content
        chapter.word_count = len("".join(body.content.split()))
    await session.commit()
    await session.refresh(chapter)
    return ChapterOut.model_validate(chapter)


@router.post("/books/{book_id}/chapters/{index}/rewrite", response_model=JobOut, status_code=201)
async def rewrite_chapter(
    index: int,
    body: RewriteRequest,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    """按作者的意见重写一章已定稿的章节：撤销它原来记进设定库和伏笔台账的变化，重写后重新提取。

    后面还有已定稿的章节时，后面的章节不会跟着改，需要作者确认（confirm）。
    """
    book = await session.scalar(
        select(Book).where(Book.id == book.id).with_for_update().execution_options(populate_existing=True)
    )
    chapter = await _chapter(session, book.id, index)
    if chapter.status != "final":
        raise HTTPException(409, "只有已定稿的章节可以按意见重写；还没定稿的章节会在写到时按流程处理")
    current = await jobs.active_job(session, book.id)
    if current is not None and current.status in jobs.ACTIVE_STATUSES:
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再重写")
    later = await writing_store.later_finals(session, book.id, index)
    if later and not body.confirm:
        raise HTTPException(
            409,
            f"第{index}章后面已经定稿了 {later} 章。重写这一章后，后面的章节不会跟着改，可能接不上；确认后再重写。",
        )
    feedback = body.feedback.strip()
    job = jobs.new_rewrite_job(book, chapter, feedback)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=job.id,
        speaker="author",
        kind="speech",
        content=f"第{index}章《{chapter.title}》按我的意见重写：{feedback}",
    )
    jobs.enqueue(job.id)
    return JobOut.model_validate(job)


VOLUME_PREFIX = re.compile(r"^第[一二三四五六七八九十百\d]+卷\s*[：:、.．\s]\s*")


def export_text(book: Book, volumes: list[Volume], chapters: list[Chapter]) -> str:
    """全书 TXT：书名，然后按卷、按章排，每章带标题，段首空两格。"""
    lines = [book.title or "未命名", ""]
    logline = (book.concept or {}).get("logline", "")
    if logline:
        lines += [logline, ""]

    def add(chapter: Chapter) -> None:
        lines.extend([f"第{chapter.index}章 {chapter.title}".rstrip(), ""])
        lines.extend(f"　　{p.strip()}" for p in chapter.content.split("\n") if p.strip())
        lines.append("")

    placed: set[uuid.UUID] = set()
    for volume in volumes:
        rows = [c for c in chapters if c.volume_id == volume.id]
        if not rows:
            continue
        title = VOLUME_PREFIX.sub("", volume.title).strip() or volume.title
        lines.extend(["", f"第{volume.index}卷 {title}".rstrip(), ""])
        for chapter in rows:
            add(chapter)
            placed.add(chapter.id)
    rest = [c for c in chapters if c.id not in placed]
    if rest:
        lines.append("")
        for chapter in rest:
            add(chapter)
    return "\n".join(lines).rstrip() + "\n"


@router.get("/books/{book_id}/export.txt")
async def export_book(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> Response:
    """一键导出全书已定稿的章节（按卷、按章，带标题）。"""
    chapters = list(
        (
            await session.execute(
                select(Chapter).where(Chapter.book_id == book.id, Chapter.status == "final").order_by(Chapter.index)
            )
        )
        .scalars()
        .all()
    )
    if not chapters:
        raise HTTPException(409, "还没有定稿的章节可以导出")
    volumes = list(
        (await session.execute(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index))).scalars().all()
    )
    # 带 BOM：Windows 上的老阅读器也能认出是 UTF-8
    body = "﻿" + export_text(book, volumes, chapters)
    name = quote(f"{book.title or '未命名'}.txt")
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"book.txt\"; filename*=UTF-8''{name}"},
    )


WRITE_LABEL = {"count": "写 {count} 章", "volume": "写完这一卷", "book": "一直写到完本"}


@router.post("/books/{book_id}/plan-segment", response_model=JobOut, status_code=201)
async def plan_segment(
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    # 与同入口的重复请求串行；保留等待作者的任务，不能从旁再开规划任务。
    book = await session.scalar(
        select(Book).where(Book.id == book.id).with_for_update().execution_options(populate_existing=True)
    )
    if book.status not in ("ready", "writing"):
        raise HTTPException(409, "全书已经写完了" if book.status == "completed" else "开书方案还没定稿")
    current = await session.scalar(
        select(Job.id).where(Job.book_id == book.id, Job.status.in_(jobs.ACTIVE_STATUSES)).limit(1)
    )
    if current is not None:
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再规划下一段")
    last = await session.scalar(
        select(StoryNode)
        .where(StoryNode.book_id == book.id, StoryNode.segment.is_not(None))
        .order_by(StoryNode.position.desc())
        .limit(1)
    )
    if last is None:
        raise HTTPException(409, "这本书开书时没有分段规划，不需要定下一段")
    if last.kind == "ending":
        raise HTTPException(409, "全书已经规划到结局了")
    job = jobs.new_write_job(book, "segment", 1)
    session.add(job)
    book.status = "writing"
    await session.flush()
    await post_message(
        session, redis, book_id=book.id, job_id=job.id, speaker="author", kind="speech", content="现在就规划下一段。"
    )
    await session.refresh(job)
    jobs.enqueue(job.id)
    return JobOut.model_validate(job)


@router.post("/books/{book_id}/write", response_model=JobOut, status_code=201)
async def start_writing(
    body: WriteRequest,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    """开写：编辑部按卷纲和章纲逐章写作，写够这一轮就停。"""
    book = await session.scalar(
        select(Book).where(Book.id == book.id).with_for_update().execution_options(populate_existing=True)
    )
    if book.status not in ("ready", "writing"):
        raise HTTPException(409, "全书已经写完了" if book.status == "completed" else "开书方案还没定稿")
    current = await jobs.active_job(session, book.id)
    if current is not None and current.status in jobs.ACTIVE_STATUSES:
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再开写")
    job = jobs.new_write_job(book, body.until, body.count)
    session.add(job)
    book.status = "writing"
    await session.commit()
    await session.refresh(job)
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=job.id,
        speaker="author",
        kind="speech",
        content=f"开写：{WRITE_LABEL[body.until].format(count=body.count)}。",
    )
    jobs.enqueue(job.id)
    return JobOut.model_validate(job)
