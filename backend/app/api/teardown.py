"""拆书第一批：上传、确认、换编码和一次事务导入；不调用模型。"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import delete, insert, select
from starlette.concurrency import run_in_threadpool

from app.api.books import detail
from app.api.deps import SessionDep, get_book, get_redis
from app.models import Book, Chapter, PlotUnit, StoryNode, TeardownSource, Volume
from app.schemas import JobOut
from app.services import book_saves, jobs, teardown_append, teardown_jobs, teardown_split
from app.services.library import lock_book

router = APIRouter(tags=["teardown"])
MAX_BYTES = 52_428_800
ENCODINGS = {"auto": "自动", "utf-8": "UTF-8", "gb18030": "GB18030", "utf-16": "UTF-16", "big5": "BIG5"}


class EncodingIn(BaseModel):
    encoding: str
    t2s: bool | None = None


class StartIn(BaseModel):
    upto: int | None = Field(None, ge=1)


class ImportIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    author: str | None = Field(None, max_length=200)
    include: list[int] = Field(default_factory=list)
    start: StartIn | None = None
    volume_mode: Literal["original", "editor"] | None = None


class AppendIn(BaseModel):
    include: list[int] = Field(default_factory=list)
    start: StartIn | None = None


def append_source_signature(source):
    return source.filename, source.size, source.encoding, hashlib.sha256(source.data).digest()


def check_confirming(book):
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    if (book.teardown or {}).get("stage") != "confirming":
        raise HTTPException(409, "这本书已经导入了")


async def split_file(data, encoding=None, *, append=False, t2s=None):
    try:
        result = await run_in_threadpool(teardown_split.split, data, encoding=encoding or None, append=append, t2s=t2s)
    except UnicodeError as exc:
        label = ENCODINGS.get(encoding, "自动编码")
        raise HTTPException(422, f"用 {label} 读不出来，换一种试试") from exc
    if not any(piece.text.strip() for piece in result["chapters"]):
        raise HTTPException(422, "文件里没有文字")
    return result


def preview_out(book, preview):
    return {
        **preview,
        "book_id": str(book.id),
        "title": book.title,
        "author": (book.teardown or {}).get("author", ""),
        "intro": (book.teardown or {}).get("intro", ""),
    }


async def locked_source(session, book):
    await lock_book(session, book.id)
    await session.refresh(book)
    check_confirming(book)
    source = await session.scalar(select(TeardownSource).where(TeardownSource.book_id == book.id).with_for_update())
    if source is None:
        raise HTTPException(409, "原文件已经不在了，请重新上传")
    return source


@router.post("/teardown", status_code=201)
async def upload(file: UploadFile, session=SessionDep):
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".txt"):
        raise HTTPException(422, "只能导入 TXT 文件")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "文件超过 50MB")
    result = await split_file(data)
    preview = teardown_split.make_preview(result, filename, len(data))
    book = Book(
        title=preview["title"][:200],
        source="teardown",
        status="writing",
        teardown={
            "stage": "confirming",
            "author": preview["author"],
            "intro": preview["intro"],
            "file": {"name": filename, "size": len(data), "encoding": result["encoding"]},
        },
    )
    session.add(book)
    await session.flush()
    session.add(
        TeardownSource(book_id=book.id, filename=filename, size=len(data), data=data, encoding="", preview=preview)
    )
    await session.commit()
    return preview_out(book, preview)


@router.get("/teardown/{book_id}/preview")
async def preview(book: Book = Depends(get_book), session=SessionDep):
    check_confirming(book)
    saved = await session.scalar(select(TeardownSource.preview).where(TeardownSource.book_id == book.id))
    if saved is None:
        raise HTTPException(409, "原文件已经不在了，请重新上传")
    return preview_out(book, saved)


@router.post("/teardown/{book_id}/encoding")
async def encoding(body: EncodingIn, book: Book = Depends(get_book), session=SessionDep):
    check_confirming(book)
    if body.encoding not in ENCODINGS:
        raise HTTPException(422, "请选择自动、UTF-8、GB18030、UTF-16 或 BIG5")
    source = await locked_source(session, book)
    chosen = "" if body.encoding == "auto" else body.encoding
    previous_preview = source.preview or {}
    conversion = (
        body.t2s
        if body.t2s is not None
        else previous_preview.get("t2s")
        if previous_preview.get("traditional")
        else None
    )
    result = await split_file(source.data, chosen, t2s=conversion)
    saved = teardown_split.make_preview(result, source.filename, source.size, encoding_auto=not chosen)
    meta = dict(book.teardown)
    if not meta.get("title_edited"):
        book.title = saved["title"][:200]
    for name in ("author", "intro"):
        if not meta.get(f"{name}_edited"):
            meta[name] = saved[name]
    meta["file"] = {**meta["file"], "encoding": result["encoding"]}
    book.teardown = meta
    source.encoding, source.preview = chosen, saved
    await session.commit()
    return preview_out(book, saved)


@router.post("/teardown/{book_id}/import")
async def import_book(
    body: ImportIn, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    source = await locked_source(session, book)
    result = await split_file(source.data, source.encoding, t2s=(source.preview or {}).get("t2s"))
    excluded_orders = {
        i for i, piece in enumerate(result["chapters"]) if set(piece.flags) & set(teardown_split.EXCLUDED_FLAGS)
    }
    if set(body.include) - excluded_orders:
        raise HTTPException(422, "勾回的章节不在排除列表里，请刷新确认页")
    selected = teardown_split.selected_chapters(result, body.include)
    if not selected:
        raise HTTPException(422, "没有要导入的章节，请勾选后再导入")
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(422, "书名不能为空")
        book.title = body.title.strip()
    book.concept = {**(book.concept or {}), "title": book.title}
    meta = dict(book.teardown)
    if body.author is not None:
        meta["author"] = body.author
    volume_mode = body.volume_mode or (source.preview or {}).get("volume_mode", "original")
    original_volumes = bool(result["volumes"]) and volume_mode == "original"
    names = result["volumes"] if original_volumes else ["还没分卷"]
    volumes = [
        Volume(
            id=uuid.uuid4(),
            book_id=book.id,
            index=i,
            title=name,
            status="done",
            chapter_count=sum(1 for piece in selected if not original_volumes or (piece.volume or 1) == i),
        )
        for i, name in enumerate(names, 1)
    ]
    session.add_all(volumes)
    await session.flush()
    rows = [
        {
            "book_id": book.id,
            "volume_id": volumes[(piece.volume or 1) - 1 if original_volumes else 0].id,
            "index": i,
            "title": piece.title,
            "content": piece.text,
            "word_count": len("".join(piece.text.split())),
            "status": "final",
            "source": "imported",
            "outline": {},
            "teardown": {"raw_title": piece.raw, "number": piece.number, "flags": piece.flags},
        }
        for i, piece in enumerate(selected, 1)
    ]
    for start in range(0, len(rows), 200):
        await session.execute(insert(Chapter), rows[start : start + 200])
    issues, total = teardown_split.number_issues(selected)
    meta.update(
        stage="imported",
        imported_at=datetime.now(UTC).isoformat(),
        original_volumes=original_volumes,
        open_volume_id=None if original_volumes else str(volumes[0].id),
        t2s=result["t2s"],
        split={
            "chapters": len(rows),
            "volumes": len(volumes),
            "chars": sum(row["word_count"] for row in rows),
            "ads_removed": result["ads_removed"],
            "duplicates_removed": result["duplicates_removed"],
            "by_length": result["by_length"],
            "number_issue_total": total,
        },
        excluded=[
            {
                "title": piece.title,
                "chars": len("".join(piece.text.split())),
                "reason": next(flag for flag in teardown_split.EXCLUDED_FLAGS if flag in piece.flags),
            }
            for i, piece in enumerate(result["chapters"])
            if i in excluded_orders - set(body.include)
        ],
        number_issues=issues,
    )
    book.teardown = meta
    await session.delete(source)
    await session.commit()
    await book_saves.safe_checkpoint(session, book.id, title="导入原文")
    if body.start is not None:
        await teardown_jobs.start(session, redis, book, body.start.upto)
    await session.refresh(book)
    return await detail(session, book)


async def locked_append(session, book, *, require_source=False):
    await lock_book(session, book.id)
    await session.refresh(book, with_for_update=True)
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    if (book.teardown or {}).get("stage") == "confirming":
        raise HTTPException(409, "这本书还没导入，先在确认页导入")
    if await jobs.is_busy(session, book.id):
        raise HTTPException(409, "这本书正在拆，先停下再补")
    source = await session.scalar(
        select(TeardownSource)
        .where(TeardownSource.book_id == book.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if require_source and (source is None or (source.preview or {}).get("mode") != "append"):
        raise HTTPException(404, "没有待确认的补章节")
    return source


async def append_plan(session, book, data, filename, size, *, encoding=None, include=()):
    result = await split_file(data, encoding, append=True, t2s=bool((book.teardown or {}).get("t2s")))
    chapters = list(
        await session.scalars(
            select(Chapter)
            .where(Chapter.book_id == book.id)
            .order_by(Chapter.index)
            .execution_options(populate_existing=True)
        )
    )
    volumes = list(
        await session.scalars(
            select(Volume)
            .where(Volume.book_id == book.id)
            .order_by(Volume.index)
            .execution_options(populate_existing=True)
        )
    )
    units = list(
        await session.scalars(
            select(PlotUnit).where(PlotUnit.book_id == book.id).execution_options(populate_existing=True)
        )
    )
    if not chapters or not volumes:
        raise HTTPException(422, "这本书还没有原文")
    plan = teardown_append.plan(
        book,
        chapters,
        volumes,
        units,
        result,
        filename,
        size,
        include=include,
        encoding_auto=not encoding,
        nodes=list(await session.scalars(select(StoryNode).where(StoryNode.book_id == book.id))),
    )
    return result, plan, chapters, volumes, units


@router.post("/teardown/{book_id}/append", status_code=201)
async def upload_append(file: UploadFile, book: Book = Depends(get_book), session=SessionDep):
    source = await locked_append(session, book)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".txt"):
        raise HTTPException(422, "只能导入 TXT 文件")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "文件超过 50MB")
    _, plan, *_ = await append_plan(session, book, data, filename, len(data))
    if source is None:
        source = TeardownSource(book_id=book.id)
        session.add(source)
    source.filename, source.size, source.data = filename, len(data), data
    source.encoding, source.preview = "", plan.preview
    await session.commit()
    return preview_out(book, plan.preview)


@router.get("/teardown/{book_id}/append")
async def preview_append(book: Book = Depends(get_book), session=SessionDep):
    source = await locked_append(session, book, require_source=True)
    return preview_out(book, source.preview)


@router.post("/teardown/{book_id}/append/encoding")
async def encoding_append(body: EncodingIn, book: Book = Depends(get_book), session=SessionDep):
    source = await locked_append(session, book, require_source=True)
    if body.encoding not in ENCODINGS:
        raise HTTPException(422, "请选择自动、UTF-8、GB18030、UTF-16 或 BIG5")
    chosen = "" if body.encoding == "auto" else body.encoding
    _, plan, *_ = await append_plan(session, book, source.data, source.filename, source.size, encoding=chosen)
    source.encoding, source.preview = chosen, plan.preview
    await session.commit()
    return preview_out(book, plan.preview)


@router.delete("/teardown/{book_id}/append", status_code=204)
async def cancel_append(book: Book = Depends(get_book), session=SessionDep):
    source = await locked_append(session, book, require_source=True)
    await session.delete(source)
    await session.commit()
    return Response(status_code=204)


@router.post("/teardown/{book_id}/append/import")
async def import_append(
    body: AppendIn, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    source = await locked_append(session, book, require_source=True)
    confirmed_source = append_source_signature(source)
    # 先验证再存档；存档会提交，因此之后必须重新持锁、重新读取原书并重新分章。
    await append_plan(
        session, book, source.data, source.filename, source.size, encoding=source.encoding, include=body.include
    )
    await book_saves.checkpoint(session, book.id, title="补章节前", force=True)
    source = await locked_append(session, book, require_source=True)
    if append_source_signature(source) != confirmed_source:
        raise HTTPException(409, "待确认的文件已经换了，请刷新确认页")
    result, plan, chapters, volumes, units = await append_plan(
        session, book, source.data, source.filename, source.size, encoding=source.encoding, include=body.include
    )
    meta = dict(book.teardown or {})
    before_total = len(chapters)
    first, last = before_total + 1, before_total + len(plan.selected)
    by_index = {volume.index: volume for volume in volumes}
    for entry in plan.volumes:
        if not entry["continued"]:
            volume = Volume(
                id=uuid.uuid4(),
                book_id=book.id,
                index=entry["index"],
                title=entry["title"],
                status="done",
                chapter_count=0,
            )
            session.add(volume)
            by_index[volume.index] = volume
    await session.flush()
    for entry in plan.reopen:
        if entry["kind"] == "unit":
            unit = next(unit for unit in units if str(unit.id) == entry["id"])
            for chapter in chapters:
                if chapter.unit_id == unit.id:
                    chapter.unit_id = None
            await session.flush()
            await session.delete(unit)
        elif entry["kind"] == "ending":
            await session.execute(delete(StoryNode).where(StoryNode.book_id == book.id, StoryNode.kind == "ending"))
            meta.pop("ending", None)
        else:
            volume = next(volume for volume in volumes if str(volume.id) == entry["id"])
            volume.summary = ""
            volume.target_node_id = None
            if entry["kind"] == "volume":
                volume.title, volume.status = "还没收尾", "planned"
                meta["open_volume_id"] = str(volume.id)
    rows = []
    for index, piece in enumerate(plan.selected, first):
        volume = by_index[plan.destinations[piece.volume]]
        volume.chapter_count += 1
        rows.append(
            {
                "book_id": book.id,
                "volume_id": volume.id,
                "index": index,
                "title": piece.title,
                "content": piece.text,
                "word_count": piece.chars,
                "status": "final",
                "source": "imported",
                "outline": {},
                "teardown": {"raw_title": piece.raw, "number": piece.number, "flags": piece.flags},
            }
        )
    for start in range(0, len(rows), 200):
        await session.execute(insert(Chapter), rows[start : start + 200])
    meta["split"] = {
        **(meta.get("split") or {}),
        "chapters": last,
        "chars": sum(chapter.word_count for chapter in chapters) + sum(piece.chars for piece in plan.selected),
        "volumes": len(by_index),
        "number_issue_total": (meta.get("split") or {}).get("number_issue_total", 0) + plan.issue_total,
    }
    meta["number_issues"] = [*(meta.get("number_issues") or []), *plan.issues][:50]
    meta["excluded"] = [*(meta.get("excluded") or []), *plan.excluded]
    meta["added"] = [
        *(meta.get("added") or []),
        {
            "at": datetime.now(UTC).isoformat(),
            "file": source.filename,
            "first": first,
            "last": last,
            "chapters": len(rows),
        },
    ]
    if meta.get("upto") is None:
        meta["upto"] = before_total
    if meta.get("stage") == "done":
        meta.update(stage="stopped", stop_reason="added", stop_note=f"补了第 {first}–{last} 章，还没拆。")
    book.teardown = meta
    await session.delete(source)
    await session.commit()
    await book_saves.checkpoint(session, book.id, title=f"补了第 {first}–{last} 章")
    if body.start is not None:
        await teardown_jobs.start(session, redis, book, body.start.upto)
    await session.refresh(book)
    return await detail(session, book)


@router.post("/teardown/{book_id}/start", response_model=JobOut)
async def start(body: StartIn, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)):
    return JobOut.model_validate(await teardown_jobs.start(session, redis, book, body.upto))


@router.post("/teardown/{book_id}/stop", response_model=JobOut)
async def stop(book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)):
    return JobOut.model_validate(await teardown_jobs.stop(session, redis, book))
