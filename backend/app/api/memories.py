import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.deps import SessionDep, ensure_not_teardown, get_book, get_redis
from app.models import Book, Chapter, Memory
from app.services import jobs
from app.services.library import lock_book
from app.services.memories import accessible, check_library, forget, lock_memories, notify, remember, summary_of
from app.services.requirements import (
    requirement_states,
    scope_label,
    set_scope,
    suppress_legacy_text,
    unsuppress_legacy_text,
)

router = APIRouter(tags=["memories"])
Scope = Literal["always", "next_chapter", "this_volume", "next_volume"]


class MemoryIn(BaseModel):
    book_id: uuid.UUID | None
    kind: Literal["writing", "chat"] = "writing"
    summary: str = Field(min_length=1, max_length=20000)
    detail: str = Field(default="", max_length=20000)
    scope: Scope = "always"

    @field_validator("summary")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("简述不能为空")
        return value.strip()


class MemoryPatch(BaseModel):
    book_id: uuid.UUID | None = None
    kind: Literal["writing", "chat"] | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=20000)
    detail: str | None = Field(default=None, max_length=20000)
    scope: Scope | None = None


def output(row, active=True):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "book_id",
            "kind",
            "summary",
            "detail",
            "source",
            "scope",
            "chapter_index",
            "volume_index",
            "message_id",
            "created_at",
            "updated_at",
            "deleted_at",
            "version",
        )
    } | {"active": active, "label": scope_label(row)}


async def outputs(session, book_id):
    return [
        output(item["row"], item["active"]) for item in await requirement_states(session, book_id, include_global=True)
    ]


@router.get("/books/{book_id}/memories")
async def get_memories(book: Book = Depends(get_book), session=SessionDep):
    ensure_not_teardown(book, "查看记忆")
    return await outputs(session, book.id)


@router.get("/books/{book_id}/memories/{memory_id}")
async def get_memory(memory_id: int, book: Book = Depends(get_book), session=SessionDep):
    ensure_not_teardown(book, "查看记忆")
    row = await accessible(session, book.id, memory_id, deleted=True)
    return output(row)


def check_target(book, target):
    ensure_not_teardown(book, "改记忆")
    if target not in (None, book.id):
        raise HTTPException(422, "只能放在这本书或全局")


@router.post("/books/{book_id}/memories", status_code=201)
async def post_memory(
    body: MemoryIn, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    check_target(book, body.book_id)
    await lock_book(session, book.id)
    row = await remember(session, **body.model_dump(), source="你加的")
    await session.commit()
    await notify(session, redis)
    return output(row)


@router.patch("/books/{book_id}/memories/{memory_id}")
async def patch_memory(
    memory_id: int,
    body: MemoryPatch,
    book: Book = Depends(get_book),
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    ensure_not_teardown(book, "改记忆")
    await lock_book(session, book.id)
    await lock_memories(session)
    row = await accessible(session, book.id, memory_id)
    values = {"book_id": row.book_id, "kind": row.kind, "summary": row.summary, "detail": row.detail}
    values.update({key: value for key, value in body.model_dump(exclude_unset=True).items() if key != "scope"})
    from pydantic import ValidationError

    try:
        data = MemoryIn.model_validate({**values, "scope": body.scope or "always"})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from exc
    check_target(book, data.book_id)
    await check_library(session, data.book_id)
    if data.book_id is None and body.scope not in (None, "always"):
        raise HTTPException(422, "全局的只能一直有效")
    duplicate = await session.scalar(
        select(Memory.id).where(
            Memory.book_id == data.book_id,
            Memory.kind == data.kind,
            Memory.summary == data.summary,
            Memory.deleted_at.is_(None),
            Memory.id != row.id,
        )
    )
    if duplicate is not None:
        raise HTTPException(409, "这条记忆已经存在")
    if (
        row.book_id is not None
        and row.kind == "writing"
        and (
            row.detail != (data.detail.strip() or data.summary) or row.kind != data.kind or row.book_id != data.book_id
        )
    ):
        await suppress_legacy_text(session, row.book_id, row.detail)
    row.book_id, row.kind, row.summary = data.book_id, data.kind, data.summary
    row.detail = data.detail.strip() or data.summary
    if body.scope is not None or row.book_id is None or row.kind == "chat":
        await set_scope(session, row, body.scope or "always")
    row.version += 1
    await session.commit()
    await notify(session, redis)
    return next(item for item in await outputs(session, book.id) if item["id"] == row.id)


@router.delete("/books/{book_id}/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: int, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    ensure_not_teardown(book, "改记忆")
    await lock_book(session, book.id)
    await lock_memories(session)
    await forget(session, await accessible(session, book.id, memory_id))
    await session.commit()
    await notify(session, redis)


@router.post("/books/{book_id}/memories/{memory_id}/restore")
async def restore_memory(
    memory_id: int, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    ensure_not_teardown(book, "改记忆")
    await lock_book(session, book.id)
    await lock_memories(session)
    row = await accessible(session, book.id, memory_id, deleted=True)
    if row.deleted_at is not None:
        duplicate = await session.scalar(
            select(Memory.id).where(
                Memory.book_id == row.book_id,
                Memory.kind == row.kind,
                Memory.summary == row.summary,
                Memory.deleted_at.is_(None),
                Memory.id != row.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(409, "这条记忆已经存在")
        row.deleted_at = None
        if row.book_id is not None and row.kind == "writing":
            await unsuppress_legacy_text(session, row.book_id, row.detail)
        row.version += 1
        await session.commit()
        await notify(session, redis)
    return output(row)


class MemoryUndo(BaseModel):
    version: int


@router.post("/books/{book_id}/memories/{memory_id}/undo")
async def undo_memory(
    memory_id: int,
    body: MemoryUndo,
    book: Book = Depends(get_book),
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    ensure_not_teardown(book, "改记忆")
    await lock_book(session, book.id)
    await lock_memories(session)
    row = await accessible(session, book.id, memory_id, deleted=True)
    from app.models import MeetingMessage
    from app.services.chat_memories import SNAPSHOT_FIELDS
    from app.services.group_notes import update_message

    messages = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.book_id == book.id)))
    snapshots = []
    for message in messages:
        payload = message.payload or {}
        for key in ("outcome", "steps", "results", "memories"):
            values = payload.get(key) or []
            for item in values if isinstance(values, list) else [values]:
                snapshot = item.get("memory") or {}
                if snapshot.get("id") == row.id and snapshot.get("version") == body.version:
                    snapshots.append(snapshot)
    receipt = next((item for item in snapshots if item.get("action")), {})
    action = receipt.get("action", "create")
    # A forget receipt owns exactly this deleted version, not later deletions.
    own_forget = action == "forget" and row.deleted_at is not None and row.version == body.version
    if row.deleted_at is not None and not own_forget:
        raise HTTPException(409, "这条后来删掉了")
    if row.version != body.version:
        raise HTTPException(409, "这条后来又改过，去「记忆」里改")
    if action == "create":
        await forget(session, row)
    else:
        before = receipt.get("before") or {}
        target = uuid.UUID(before["book_id"]) if before.get("book_id") else None
        check_target(book, target)
        duplicate = await session.scalar(
            select(Memory.id).where(
                Memory.book_id == target,
                Memory.kind == before["kind"],
                Memory.summary == before["summary"],
                Memory.deleted_at.is_(None),
                Memory.id != row.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(409, "这条记忆已经存在")
        if row.book_id is not None and row.kind == "writing":
            await suppress_legacy_text(session, row.book_id, row.detail)
        # JSON snapshots do not participate in FK SET NULL. Resolve the old
        # source before mutating the row, so query autoflush cannot revive it.
        origin = before["message_id"]
        if origin is not None and await session.get(MeetingMessage, origin) is None:
            before = {**before, "message_id": None}
        for key in SNAPSHOT_FIELDS:
            setattr(row, key, target if key == "book_id" else before[key])
        row.deleted_at = None
        row.version += 1
        if row.book_id is not None and row.kind == "writing":
            await unsuppress_legacy_text(session, row.book_id, row.detail)
        await session.flush()
    for message in messages:
        payload = dict(message.payload or {})
        changed = False
        for key in ("outcome", "steps", "results", "memories"):
            values = payload.get(key)
            if not values:
                continue
            items = values if isinstance(values, list) else [values]
            fresh = []
            for item in items:
                snapshot = item.get("memory") or {}
                if snapshot.get("id") == row.id and snapshot.get("version") == body.version:
                    item = {**item, "undone": True}
                    changed = True
                fresh.append(item)
            payload[key] = fresh if isinstance(values, list) else fresh[0]
        if changed:
            await update_message(session, redis, message, **payload)
    await session.commit()
    await notify(session, redis)
    return output(row)


@router.post("/books/{book_id}/memories/tidy")
async def tidy_requirements(book: Book = Depends(get_book), session=SessionDep):
    ensure_not_teardown(book, "改记忆")
    from app.agents.schemas import RequirementsTidy
    from app.services.chat import model
    from app.services.chat_context import progress_of
    from app.services.library_context import load_context

    book_id = book.id
    ctx = await load_context(session, book)
    items = [
        item
        for item in await outputs(session, book_id)
        if item["active"] and item["book_id"] == book_id and item["kind"] == "writing"
    ]
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index)))
    job = await jobs.active_job(session, book_id)
    values = dict(
        concept=ctx.concept,
        progress=await progress_of(session, ctx, chapters, job),
        requirements="\n".join(
            f"{i}. {' '.join(item['detail'].splitlines())}（{item['label']}；来自{item['source']}）"
            for i, item in enumerate(items, 1)
        )
        or "（没有）",
    )
    await session.commit()
    try:
        result = await model(book_id, "chief", RequirementsTidy, "requirements_tidy", **values)
    except Exception as exc:
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    by_index = {item.index: item for item in result.items}
    return {
        "items": [
            {
                "id": item["id"],
                "text": item["detail"],
                "action": by_index[i].action if i in by_index else "保留",
                "reason": by_index[i].reason if i in by_index else "主编没有建议改这一条",
                "rewrite": by_index[i].rewrite if i in by_index else "",
            }
            for i, item in enumerate(items, 1)
        ]
    }


class RequirementRewrite(BaseModel):
    id: int
    text: str = Field(min_length=1, max_length=20000)


class RequirementsApply(BaseModel):
    delete: list[int] = Field(default_factory=list)
    rewrite: list[RequirementRewrite] = Field(default_factory=list)


@router.post(
    "/books/{book_id}/memories/apply",
)
async def apply_requirements(
    body: RequirementsApply, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    ensure_not_teardown(book, "改记忆")
    await lock_book(session, book.id)
    await lock_memories(session)
    ids = {*body.delete, *(r.id for r in body.rewrite)}
    rows = {
        r.id: r
        for r in await session.scalars(
            select(Memory).where(Memory.book_id == book.id, Memory.kind == "writing", Memory.deleted_at.is_(None))
        )
    }
    if not ids.issubset(rows):
        raise HTTPException(409, "要求清单已经变了，重新整理一下")
    if set(body.delete) & {r.id for r in body.rewrite}:
        raise HTTPException(422, "不能同时删掉和改写同一条")
    future = [r.text.strip() for r in body.rewrite]
    kept = {r.text for r in rows.values() if r.id not in ids}
    if any(not text for text in future) or len(set(future)) != len(future) or set(future) & kept:
        raise HTTPException(409, "改写后的要求为空或重复")
    for id in body.delete:
        await suppress_legacy_text(session, book.id, rows[id].text)
        await forget(session, rows[id])
    for item in body.rewrite:
        await suppress_legacy_text(session, book.id, rows[item.id].text)
        rows[item.id].detail = item.text.strip()
        rows[item.id].summary = summary_of(item.text.strip())
        rows[item.id].version += 1
    await session.commit()
    await notify(session, redis)
    return await outputs(session, book.id)
