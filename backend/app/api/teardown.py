"""拆书第一批：上传、确认、换编码和一次事务导入；不调用模型。"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import insert, select
from starlette.concurrency import run_in_threadpool

from app.api.books import detail
from app.api.deps import SessionDep, get_book
from app.models import Book, Chapter, TeardownSource, Volume
from app.services import book_saves, teardown_split
from app.services.library import lock_book

router = APIRouter(tags=["teardown"])
MAX_BYTES = 52_428_800
ENCODINGS = {"auto": "自动", "utf-8": "UTF-8", "gb18030": "GB18030", "utf-16": "UTF-16", "big5": "BIG5"}


class EncodingIn(BaseModel):
    encoding: str


class ImportIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    author: str | None = Field(None, max_length=200)
    include: list[int] = Field(default_factory=list)


def check_confirming(book):
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    if (book.teardown or {}).get("stage") != "confirming":
        raise HTTPException(409, "这本书已经导入了")


async def split_file(data, encoding=None):
    try:
        result = await run_in_threadpool(teardown_split.split, data, encoding=encoding or None)
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
    result = await split_file(source.data, chosen)
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
async def import_book(body: ImportIn, book: Book = Depends(get_book), session=SessionDep):
    source = await locked_source(session, book)
    result = await split_file(source.data, source.encoding)
    excluded_orders = {i for i, piece in enumerate(result["chapters"]) if set(piece.flags) & {"不像正文", "空的"}}
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
    names = result["volumes"] or ["还没分卷"]
    volumes = [
        Volume(
            id=uuid.uuid4(),
            book_id=book.id,
            index=i,
            title=name,
            status="done",
            chapter_count=sum(1 for piece in selected if (piece.volume or 1) == i),
        )
        for i, name in enumerate(names, 1)
    ]
    session.add_all(volumes)
    await session.flush()
    rows = [
        {
            "book_id": book.id,
            "volume_id": volumes[(piece.volume or 1) - 1].id,
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
        open_volume_id=None if result["volumes"] else str(volumes[0].id),
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
                "reason": "空的" if "空的" in piece.flags else "不像正文",
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
    await session.refresh(book)
    return await detail(session, book)
