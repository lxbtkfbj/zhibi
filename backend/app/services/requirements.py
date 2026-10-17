"""The database ledger, never a graph checkpoint, owns persistent author requirements."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, AuthorRequirement, Book, Chapter, MeetingMessage, Volume


async def list_requirements(session: AsyncSession, book_id: uuid.UUID) -> list[AuthorRequirement]:
    return list(
        (
            await session.scalars(
                select(AuthorRequirement)
                .where(AuthorRequirement.book_id == book_id)
                .order_by(AuthorRequirement.created_at, AuthorRequirement.id)
            )
        ).all()
    )


async def add_requirement(
    session: AsyncSession,
    book_id: uuid.UUID,
    text: str,
    source: str = "manual",
    scope: str = "always",
    message_id: int | None = None,
) -> AuthorRequirement | None:
    text = text.strip()
    if not text:
        return None
    # Serialize concurrent append/edit operations without a PostgreSQL B-tree limit on long text.
    await session.execute(select(Book.id).where(Book.id == book_id).with_for_update())
    existing = await session.scalar(
        select(AuthorRequirement).where(AuthorRequirement.book_id == book_id, AuthorRequirement.text == text)
    )
    if existing is not None:
        await set_scope(session, existing, scope)
        if message_id is not None:
            existing.message_id = message_id
        return existing
    tombstone = await session.get(AppSetting, f"requirement_tombstones:{book_id}")
    if tombstone and text in (tombstone.value or {}).get("texts", []):
        tombstone.value = {"texts": [item for item in tombstone.value["texts"] if item != text]}
    row = AuthorRequirement(book_id=book_id, text=text, source=source)
    await set_scope(session, row, scope)
    row.message_id = message_id
    session.add(row)
    await session.flush()
    return row


async def suppress_legacy_text(session: AsyncSession, book_id: uuid.UUID, text: str) -> None:
    """Remember an explicit edit/delete so an old checkpoint cannot resurrect its text."""
    await session.execute(select(Book.id).where(Book.id == book_id).with_for_update())
    key = f"requirement_tombstones:{book_id}"
    marker = await session.get(AppSetting, key)
    values = list(dict.fromkeys([*((marker.value or {}).get("texts", []) if marker else []), text]))
    if marker:
        marker.value = {"texts": values}
    else:
        session.add(AppSetting(key=key, value={"texts": values}))


async def import_legacy_checkpoint(session: AsyncSession, book_id: uuid.UUID, job_id: uuid.UUID, state: dict) -> None:
    """Pre-upgrade setup checkpoints may hold answers never yet persisted in books.

    New graphs are marked at creation. Old checkpoints are imported once under the same
    book lock as edits; tombstones ensure an author deletion wins even before first resume.
    """
    if state.get("requirements_ledger_ready"):
        return
    await session.execute(select(Book.id).where(Book.id == book_id).with_for_update())
    key = f"requirements_checkpoint:{job_id}"
    if await session.get(AppSetting, key):
        return
    marker = await session.get(AppSetting, f"requirement_tombstones:{book_id}")
    deleted = set((marker.value or {}).get("texts", []) if marker else [])
    existing = {row.text for row in await list_requirements(session, book_id)}
    for text in state.get("brief") or []:
        if text not in deleted:
            await add_requirement(session, book_id, text, "answer")
    roles = {"主编": "chief", "设定师": "lorekeeper", "写手": "writer", "审稿": "reviewer"}
    for original in state.get("notes") or []:
        text, source = original, "note"
        for label, role in roles.items():
            prefix = f"（作者对{label}说）"
            if original.startswith(prefix):
                text, source = original[len(prefix) :], f"private:{role}"
                break
        if text not in deleted and original not in deleted and text not in existing and original not in existing:
            await add_requirement(session, book_id, text, source)
    session.add(AppSetting(key=key, value={"imported": True}))


async def deleted_texts(session: AsyncSession, book_id: uuid.UUID) -> set[str]:
    marker = await session.get(AppSetting, f"requirement_tombstones:{book_id}")
    return set((marker.value or {}).get("texts", []) if marker else [])


def note_source(payload: dict | None) -> str:
    thread = (payload or {}).get("thread")
    return f"private:{thread}" if thread in ("chief", "lorekeeper", "writer", "reviewer") else "note"


def note_aliases(content: str, payload: dict | None) -> set[str]:
    label = {"chief": "主编", "lorekeeper": "设定师", "writer": "写手", "reviewer": "审稿"}.get(
        (payload or {}).get("thread")
    )
    return {content, f"（作者对{label}说）{content}", f"对{label}：{content}"} if label else {content}


async def ingest_notes(session: AsyncSession, book_id: uuid.UUID, rows: list[tuple]) -> None:
    """Import pre-upgrade pending messages once; never recreate author-deleted requirements."""
    deleted = await deleted_texts(session, book_id)
    for message_id, content, payload in rows:
        if (payload or {}).get("settings_change") or (payload or {}).get("requirement_saved"):
            continue
        if not (note_aliases(content, payload) & deleted):
            await add_requirement(session, book_id, content, note_source(payload))
        message = await session.get(MeetingMessage, message_id)
        if message is not None:
            message.payload = {**(message.payload or {}), "requirement_saved": True}


async def active_notes(session: AsyncSession, book_id: uuid.UUID, rows: list[tuple]) -> list[tuple]:
    texts = {row.text for row in await active_requirements(session, book_id)}
    deleted = await deleted_texts(session, book_id)
    return [
        row
        for row in rows
        if (row[2] or {}).get("settings_change")
        or (
            not (note_aliases(row[1], row[2]) & deleted)
            and (not (row[2] or {}).get("requirement_saved") or row[1] in texts)
        )
    ]


SCOPE_INPUTS = {
    "一直有效": "always",
    "只管下一章": "next_chapter",
    "只管这一卷": "this_volume",
    "只管下一卷": "next_volume",
}


async def set_scope(session: AsyncSession, row: AuthorRequirement, scope: str) -> None:
    chapters = list(
        await session.scalars(select(Chapter).where(Chapter.book_id == row.book_id).order_by(Chapter.index))
    )
    volumes = list(await session.scalars(select(Volume).where(Volume.book_id == row.book_id).order_by(Volume.index)))
    row.scope, row.chapter_index, row.volume_index = "always", None, None
    if scope == "next_chapter":
        row.scope = "chapter"
        row.chapter_index = next(
            (c.index for c in chapters if c.status != "final"), max((c.index for c in chapters), default=0) + 1
        )
    elif scope in ("this_volume", "next_volume"):
        row.scope = "volume"
        current = next((v.index for v in volumes if v.status != "done"), max((v.index for v in volumes), default=0) + 1)
        row.volume_index = current + (scope == "next_volume")


async def requirement_states(session: AsyncSession, book_id: uuid.UUID) -> list[dict]:
    done_chapters = set(
        await session.scalars(select(Chapter.index).where(Chapter.book_id == book_id, Chapter.status == "final"))
    )
    done_volumes = set(
        await session.scalars(select(Volume.index).where(Volume.book_id == book_id, Volume.status == "done"))
    )
    result = []
    for row in await list_requirements(session, book_id):
        active = not (
            (row.scope == "chapter" and row.chapter_index in done_chapters)
            or (row.scope == "volume" and row.volume_index in done_volumes)
        )
        label = (
            "一直有效"
            if row.scope == "always"
            else f"只管第 {row.chapter_index} 章"
            if row.scope == "chapter"
            else f"只管第 {row.volume_index} 卷"
        )
        result.append({"row": row, "active": active, "label": label if active else "已过期 · " + label})
    return sorted(result, key=lambda item: not item["active"])


async def active_requirements(session: AsyncSession, book_id: uuid.UUID) -> list[AuthorRequirement]:
    return [item["row"] for item in await requirement_states(session, book_id) if item["active"]]


def requirement_text(row: AuthorRequirement) -> str:
    prefix = (
        f"（只管第 {row.chapter_index} 章）"
        if row.scope == "chapter"
        else f"（只管第 {row.volume_index} 卷）"
        if row.scope == "volume"
        else ""
    )
    return prefix + row.text


def requirements_list(rows: list[AuthorRequirement]) -> str:
    return "\n".join(f"- {requirement_text(row)}" for row in rows) or "（没有）"
