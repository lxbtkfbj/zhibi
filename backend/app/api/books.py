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
from app.book_meta import DEFAULT_CHAPTER_WORDS, channel_of
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
    UnitCreate,
    UnitOrder,
    UnitOut,
    UnitPatch,
    VolumeCreate,
    VolumeOut,
    VolumePatch,
    WriteRequest,
)
from app.services import jobs, outline_structure, writing_store
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
    if not body.start_setup:
        return await create_blank_book(body, session)
    book = Book(idea=body.idea.strip(), style_reference=body.style_reference.strip(), source="new", status="setting_up")
    book.settings = await new_book_defaults(session)
    mode = body.mode or book.settings.get("setup_mode", "puzzle")
    book.settings = {**book.settings, "setup_mode": mode}
    session.add(book)
    await session.flush()
    job = jobs.new_setup_job(book, ask=body.ask, mode=mode, prefill=body.prefill)
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


async def create_blank_book(body: BookCreate, session: AsyncSession) -> BookCreated:
    """新建页：只存作者填了的几项，编辑部等作者叫了再动。简介先放在定调的一段话里。"""
    filled = {
        "title": body.title,
        "story": body.blurb,
        "channel": body.channel or channel_of(body.genre),
        "genre": body.genre,
        "tags": body.tags,
        "target_length": body.target_length,
    }
    settings = await new_book_defaults(session)
    book = Book(
        title=body.title or "未命名",
        idea=body.blurb,
        genre=body.genre,
        source="new",
        status="setting_up",
        concept={key: value for key, value in filled.items() if value},
    )
    # 新建页按这个字数给作者算章数，没在设置里定每章字数时记进定调，后面规划和写作都照它
    book.concept["chapter_words"] = settings.get("chapter_words") or DEFAULT_CHAPTER_WORDS
    book.settings = settings
    session.add(book)
    await session.commit()
    await session.refresh(book)
    return BookCreated(book=await detail(session, book), job=None)


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
        if "genre" in body.concept:
            if not isinstance(book.concept["genre"], str) or len(book.concept["genre"]) > 100:
                raise HTTPException(422, "类型须为不超过 100 字的文字")
            book.genre = book.concept["genre"]
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
    if body.concept is not None and "story" in body.concept and body.review_changes:
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
    state = None
    if body.chapter_count is not None and body.chapter_count != volume.chapter_count:
        state = await outline_structure.load_structure(session, volume.book_id)
        await outline_structure.resize_target(session, state, volume, body.chapter_count)
    await validate_node(session, volume.book_id, body.target_node_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "techniques":
            value = clean_techniques(value)
        setattr(volume, key, value)
    if state is not None:
        await outline_structure.finish_structure(session, volume.book_id, state, "调整卷章数", affected={volume.id})
    else:
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
    state = None
    if body.chapter_count is not None and body.chapter_count != unit.chapter_count:
        state = await outline_structure.load_structure(session, unit.book_id)
        await outline_structure.resize_target(session, state, unit, body.chapter_count)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "techniques":
            value = clean_techniques(value)
        setattr(unit, key, value)
    if state is not None:
        await outline_structure.finish_structure(
            session, unit.book_id, state, "调整单元章数", affected={unit.id, unit.volume_id}
        )
    else:
        await record_version(session, unit.book_id, "unit", unit, "author", before=before)
    await session.commit()
    await session.refresh(unit)
    return UnitOut.model_validate(unit)


async def _structure_target(session: AsyncSession, model, row_id: uuid.UUID):
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "卷不存在" if model is Volume else "剧情单元不存在")
    await lock_book(session, row.book_id)
    await ensure_idle(session, row.book_id)
    state = await outline_structure.load_structure(session, row.book_id)
    rows = state.volumes if model is Volume else state.units
    target = next((item for item in rows if item.id == row_id), None)
    if target is None:
        raise HTTPException(404, "记录不存在")
    return target, state


def _insert_after(rows: list, row, after_id: uuid.UUID | None, message: str) -> list:
    if after_id is None:
        return [row, *rows]
    index = next((index for index, item in enumerate(rows) if item.id == after_id), None)
    if index is None:
        raise HTTPException(422, message)
    return [*rows[: index + 1], row, *rows[index + 1 :]]


@router.post("/volumes/{volume_id}/units", response_model=UnitOut, status_code=201)
async def create_unit(volume_id: uuid.UUID, body: UnitCreate, session: AsyncSession = SessionDep) -> UnitOut:
    volume, state = await _structure_target(session, Volume, volume_id)
    units = state.own_units(volume.id)
    # 还没拆单元的卷：没写过的可以加第一个单元，从此按单元算章数
    if not units and state.own_chapters(volume):
        raise HTTPException(409, "这一卷已经有章节了，先拆成单元再加")
    unit = PlotUnit(
        book_id=volume.book_id,
        volume_id=volume.id,
        index=max((u.index for u in units), default=0) + 1,
        **body.model_dump(exclude={"after_unit_id"}),
    )
    # 卷上定过章数、这是第一个单元：章数先给它，免得作者定的数一拆就没了
    if not units and not unit.chapter_count and 0 < volume.chapter_count <= 50:
        unit.chapter_count = volume.chapter_count
    ordered = _insert_after(units, unit, body.after_unit_id, "指定单元不属于这一卷")
    session.add(unit)
    await session.flush()
    state.units.append(unit)
    await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
    volume.chapter_count = sum(u.chapter_count for u in ordered)
    await outline_structure.finish_structure(session, volume.book_id, state, "新增单元", affected={volume.id})
    await session.commit()
    await session.refresh(unit)
    return UnitOut.model_validate(unit)


@router.delete("/units/{unit_id}", status_code=204)
async def delete_unit(unit_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    unit, state = await _structure_target(session, PlotUnit, unit_id)
    state.ensure_unwritten(unit, "这个单元已经开写了，不能删")
    for chapter in state.own_chapters(unit):
        state.chapters.remove(chapter)
        await session.delete(chapter)
    state.units.remove(unit)
    # 被删行暂移到空闲序号，记录最后一版后再删，避免后面的行重排时撞号。
    unit.index = -max((u.index for u in state.units), default=0) - 1
    await session.flush()
    units = state.own_units(unit.volume_id)
    await outline_structure.assign_indices(session, units, list(range(1, len(units) + 1)))
    volume = next(v for v in state.volumes if v.id == unit.volume_id)
    volume.chapter_count = sum(u.chapter_count for u in units)
    if not units:
        volume.status = "planned"
    await outline_structure.finish_structure(
        session, unit.book_id, state, "删除单元", affected={unit.id, volume.id}, deleted=[unit]
    )
    await session.delete(unit)
    await session.commit()


@router.post("/volumes/{volume_id}/units/order", response_model=list[UnitOut])
async def order_units(volume_id: uuid.UUID, body: UnitOrder, session: AsyncSession = SessionDep) -> list[UnitOut]:
    volume, state = await _structure_target(session, Volume, volume_id)
    units = state.own_units(volume.id)
    if len(body.ids) != len(units) or set(body.ids) != {u.id for u in units}:
        raise HTTPException(422, "请完整列出这一卷的单元，每个单元只能出现一次")
    lookup = {u.id: u for u in units}
    ordered = [lookup[row_id] for row_id in body.ids]
    seen_unwritten = False
    for unit in ordered:
        has_started = any(outline_structure.started(c) for c in state.own_chapters(unit))
        if has_started and seen_unwritten:
            raise HTTPException(409, "已经开写的单元不能挪到没开写的单元后面")
        seen_unwritten = seen_unwritten or not has_started
    await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
    await outline_structure.finish_structure(session, volume.book_id, state, "调整单元顺序", affected={volume.id})
    await session.commit()
    return [UnitOut.model_validate(unit) for unit in ordered]


@router.post("/books/{book_id}/volumes", response_model=VolumeOut, status_code=201)
async def create_volume(
    body: VolumeCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep
) -> VolumeOut:
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    await validate_node(session, book.id, body.target_node_id)
    if body.target_node_id is not None:
        await outline_structure.plan_arc_for_volume(session, book.id, body.target_node_id)
    state = await outline_structure.load_structure(session, book.id)
    volume = Volume(
        book_id=book.id,
        index=max((v.index for v in state.volumes), default=0) + 1,
        **body.model_dump(exclude={"after_volume_id"}),
    )
    ordered = _insert_after(state.volumes, volume, body.after_volume_id, "指定卷不属于这本书")
    session.add(volume)
    await session.flush()
    state.volumes = ordered
    await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
    await outline_structure.finish_structure(session, book.id, state, "新增卷")
    await session.commit()
    await session.refresh(volume, attribute_names=["units", "updated_at"])
    return VolumeOut.model_validate(volume)


@router.delete("/volumes/{volume_id}", status_code=204)
async def delete_volume(volume_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    volume, state = await _structure_target(session, Volume, volume_id)
    state.ensure_unwritten(volume, "这一卷已经开写了，不能删")
    units = state.own_units(volume.id)
    for chapter in state.own_chapters(volume):
        state.chapters.remove(chapter)
        await session.delete(chapter)
    state.volumes.remove(volume)
    state.units = [u for u in state.units if u.volume_id != volume.id]
    volume.index = -max((v.index for v in state.volumes), default=0) - 1
    await session.flush()
    await outline_structure.assign_indices(session, state.volumes, list(range(1, len(state.volumes) + 1)))
    await outline_structure.finish_structure(
        session,
        volume.book_id,
        state,
        "删除卷",
        affected={volume.id, *(u.id for u in units)},
        deleted=[volume, *units],
    )
    await session.delete(volume)
    await session.commit()


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
    book: Book = Depends(get_book),
    volume: int | None = None,
    with_outline: bool = False,
    session: AsyncSession = SessionDep,
) -> list[ChapterBrief]:
    """全书章节目录；指定 volume 时只列这一卷，并带上章纲；with_outline 时全书都带章纲（新书页用）。"""
    stmt = select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)
    if volume is not None:
        stmt = stmt.join(Volume, Chapter.volume_id == Volume.id).where(Volume.index == volume)
    rows = (await session.execute(stmt)).scalars().all()
    out = []
    for c in rows:
        brief = ChapterBrief.model_validate(c)
        brief.outline = c.outline if volume is not None or with_outline else None
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
    if body.outline is not None:
        if outline_structure.started(chapter):
            raise HTTPException(409, "这一章已经开写了，章纲不能改")
        changes = body.outline.model_dump(exclude_unset=True)
        if "scenes" in changes:
            changes["scenes"] = [scene.strip() for scene in changes["scenes"] or [] if scene.strip()]
        chapter.outline = {**(chapter.outline or {}), **{key: value for key, value in changes.items() if value is not None}}
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


async def _has_outline(session: AsyncSession, book_id) -> bool:
    """大纲上有没有东西可写：有卷，或者有作者写了一段话的篇。"""
    if await session.scalar(select(Volume.id).where(Volume.book_id == book_id).limit(1)):
        return True
    nodes = await session.scalars(
        select(StoryNode).where(StoryNode.book_id == book_id, StoryNode.segment.is_not(None))
    )
    return any(str((node.segment or {}).get("text") or "").strip() for node in nodes)


WRITE_LABEL = {"count": "写 {count} 章", "unit": "写完这个单元", "volume": "写完这一卷", "book": "一直写到完本"}


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
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再规划下一篇")
    last = await session.scalar(
        select(StoryNode)
        .where(StoryNode.book_id == book.id, StoryNode.segment.is_not(None))
        .order_by(StoryNode.position.desc())
        .limit(1)
    )
    if last is None:
        raise HTTPException(409, "这本书开书时没有分篇规划，不需要定下一篇")
    if last.kind == "ending":
        raise HTTPException(409, "全书已经规划到结局了")
    job = jobs.new_write_job(book, "segment", 1)
    session.add(job)
    book.status = "writing"
    await session.flush()
    await post_message(
        session, redis, book_id=book.id, job_id=job.id, speaker="author", kind="speech", content="现在就规划下一篇。"
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
    current = await jobs.active_job(session, book.id)
    if current is not None and current.status in jobs.ACTIVE_STATUSES:
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再开写")
    # 新书页建的书不走开书流程，状态一直是「设定中」：大纲里有篇或卷就能开写
    if book.status == "setting_up" and book.source == "new":
        if not await _has_outline(session, book.id):
            raise HTTPException(409, "大纲还空着：先在大纲里写好第一篇那段话，编辑部照它一层层往下拆")
    elif book.status not in ("ready", "writing"):
        raise HTTPException(409, "全书已经写完了" if book.status == "completed" else "开书方案还没定稿")
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
