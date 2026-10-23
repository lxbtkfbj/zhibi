"""The memory ledger is independent of book saves and graph state."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import or_, select, text

from app.models import Book, Memory

SOURCES = ("聊天里记的", "你加的", "方案卡", "开书时答的", "看稿时说的")


def summary_of(detail: str) -> str:
    return detail[:40] + ("……" if len(detail) > 40 else "")


def source_of(source: str) -> str:
    if source in SOURCES:
        return source
    if source == "note" or source.startswith(("private:", "chat:")):
        return "聊天里记的"
    if source == "plan":
        return "方案卡"
    if source == "answer":
        return "开书时答的"
    if source == "trial" or source.startswith(("volume:", "unit:", "segment:")):
        return "看稿时说的"
    return "你加的"


async def lock_memories(session):
    # Includes the global library and moves between libraries. No long-text B-tree key.
    await session.execute(text("SELECT pg_advisory_xact_lock(72841028)"))


async def check_library(session, book_id):
    if book_id is not None:
        book = await session.get(Book, book_id)
        if book is None:
            raise HTTPException(404, "书不存在")
        if book.source == "teardown":
            raise HTTPException(409, "拆的书没有记忆")


async def remember(
    session, book_id, summary, detail="", kind="writing", source="你加的", scope="always", message_id=None
):
    from app.services.library import lock_book
    from app.services.requirements import set_scope, suppress_legacy_text, unsuppress_legacy_text

    await check_library(session, book_id)
    if book_id is None and scope != "always":
        raise HTTPException(422, "全局的只能一直有效")
    summary = summary.strip()
    if not summary:
        raise HTTPException(422, "简述不能为空")
    # Every book writer locks the parent first; a new memory FK must not invert that order.
    if book_id is not None:
        await lock_book(session, book_id)
    await lock_memories(session)
    row = await session.scalar(
        select(Memory)
        .where(Memory.book_id == book_id, Memory.kind == kind, Memory.summary == summary, Memory.deleted_at.is_(None))
        .order_by(Memory.id)
    )
    if row is None:
        row = Memory(book_id=book_id, kind=kind, summary=summary, detail=detail.strip() or summary)
        session.add(row)
    else:
        if book_id is not None and kind == "writing" and row.detail != (detail.strip() or summary):
            await suppress_legacy_text(session, book_id, row.detail)
        row.version += 1
        row.detail = detail.strip() or summary
        row.created_at = row.updated_at = datetime.now(UTC)
    row.source, row.message_id = source_of(source), message_id
    await set_scope(session, row, scope if kind == "writing" else "always")
    if book_id is not None and kind == "writing":
        await unsuppress_legacy_text(session, book_id, row.detail)
    await session.flush()
    return row


async def visible_rows(session, book_id: uuid.UUID):
    return list(
        await session.scalars(
            select(Memory)
            .where(or_(Memory.book_id.is_(None), Memory.book_id == book_id), Memory.deleted_at.is_(None))
            .order_by(Memory.book_id.is_not(None), Memory.id)
        )
    )


async def accessible(session, book_id, memory_id, *, deleted=False):
    row = await session.get(Memory, memory_id, populate_existing=True)
    if row is None or row.book_id not in (None, book_id) or (row.deleted_at is not None and not deleted):
        raise HTTPException(404, "没有这条记忆")
    return row


async def forget(session, row):
    from app.services.requirements import suppress_legacy_text

    if row.book_id is not None and row.kind == "writing":
        await suppress_legacy_text(session, row.book_id, row.detail)
    row.deleted_at = datetime.now(UTC)
    row.version += 1
    row.updated_at = datetime.now(UTC)
    await session.flush()


def remembered_outcome(row, *, working=False):
    from app.services.requirements import scope_label

    return {
        "kind": "to_job" if working else "requirement",
        "requirement_id": str(row.id),
        "memory": {
            "id": row.id,
            "version": row.version,
            "summary": row.summary,
            "kind": row.kind,
            "book_id": str(row.book_id) if row.book_id else None,
            "label": scope_label(row),
            "working": working,
        },
    }


async def notify(session, redis):
    from app.services.meeting import publish

    # Global edits must also refresh another open book, not just the initiating book.
    ids = list(await session.scalars(select(Book.id).where(Book.source != "teardown")))
    for book_id in ids:
        await publish(redis, book_id, "memories", {})
