"""设定师逐章新增条目和矛盾提醒；快照保护作者修改，重写时只撤销本章仍保持原样的数据。"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Book, Chapter, SettingSuggestion, WorldEntry
from app.services.library_context import load_context
from app.services.versions import record_version, snapshot_of


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[。！？!?])|\n", text.strip(), maxsplit=1)[0]


def entry_snapshot(row: WorldEntry) -> dict:
    return {**snapshot_of(row), "source": row.source, "created_chapter": row.created_chapter}


async def add_digest_library(session: AsyncSession, book_id: uuid.UUID, chapter: Chapter, digest) -> tuple[list, list]:
    # 新人物要先 flush，配置排序与完整快照才能读到数据库默认值。
    await session.flush()
    context = await load_context(session, await session.get(Book, book_id))
    names = {name.strip() for row in context.targets for name in [row.name, *(row.aliases or [])] if name.strip()}
    categories = {value: category for category in context.categories for value in (category["key"], category["name"])}
    created = []
    for entry in digest.new_entries:
        name = entry.name.strip()[:100]
        if not name or name in names:
            continue
        category = categories.get(entry.category.strip())
        if not category or category["key"] == "角色卡片":
            category = categories["特殊规则"]
        row = WorldEntry(
            book_id=book_id,
            category=category["key"],
            style=category["style"],
            name=name,
            one_line=entry.one_line,
            content=entry.content,
            source="writing",
            status="one",
            created_chapter=chapter.index,
            parent_id=None,
            fields=[{"name": field, "value": ""} for field in category.get("fields", [])],
        )
        session.add(row)
        await session.flush()
        await record_version(session, book_id, "entry", row, "writing", f"第 {chapter.index} 章记下的")
        created.append({"id": str(row.id), "snapshot": entry_snapshot(row)})
        names.add(name)
    suggestions = []
    for conflict in dict.fromkeys(value.strip() for value in digest.conflicts if value.strip()):
        suggestion = SettingSuggestion(
            book_id=book_id,
            kind="review",
            title=f"第 {chapter.index} 章：{conflict}",
            payload={"op": "note"},
            origin={"target_type": "chapter", "target_id": str(chapter.id), "chapter": chapter.index},
        )
        session.add(suggestion)
        await session.flush()
        suggestions.append(str(suggestion.id))
    return created, suggestions


async def revert_digest_library(
    session: AsyncSession, book_id: uuid.UUID, chapter: Chapter, later: int
) -> dict[str, int]:
    log = chapter.bible_changes or {}
    removed = 0
    for item in log.get("created_entries") or []:
        row = await session.get(WorldEntry, uuid.UUID(item["id"]))
        if (
            row is not None
            and row.book_id == book_id
            and row.created_chapter == chapter.index
            and not later
            and entry_snapshot(row) == item.get("snapshot")
        ):
            await session.delete(row)
            removed += 1
    suggestions = 0
    ids = [uuid.UUID(value) for value in log.get("created_suggestions") or []]
    if ids:
        rows = await session.scalars(
            select(SettingSuggestion).where(
                SettingSuggestion.book_id == book_id,
                SettingSuggestion.id.in_(ids),
                SettingSuggestion.status == "pending",
            )
        )
        for row in rows:
            # 同时核对原始归属，不能用损坏的撤销记录删掉其他章节的建议。
            if row.origin == {"target_type": "chapter", "target_id": str(chapter.id), "chapter": chapter.index}:
                await session.delete(row)
                suggestions += 1
    return {"removed_entries": removed, "removed_suggestions": suggestions}
