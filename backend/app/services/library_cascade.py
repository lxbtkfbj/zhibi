"""专有叫法改动只生成建议，不自动改动别处或已写正文。"""

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_config import CHARACTER_CATEGORY
from app.models import Book, Chapter, Character, PlotUnit, SettingSuggestion, StoryNode, Volume, WorldEntry
from app.services.library_context import load_context
from app.services.versions import target_type_of


def iter_text_paths(target: Any) -> Iterable[tuple[str, str]]:
    """可搜索且可精确改写的文字；角色每章状态和非文字字段不在其中。"""
    if isinstance(target, WorldEntry):
        for field in ("name", "one_line", "content"):
            yield field, getattr(target, field) or ""
        for field in target.fields or []:
            yield f"fields.{field['name']}", field.get("value", "")
        for index, level in enumerate(target.levels or []):
            for field in ("name", "text"):
                yield f"levels.{index}.{field}", level.get(field, "")
    elif isinstance(target, Character):
        for _, field in CHARACTER_CATEGORY["fields"]:
            value = getattr(target, field, "")
            if isinstance(value, str):
                yield field, value
        yield "one_line", target.one_line or ""
    elif isinstance(target, Book):
        yield "story", (target.concept or {}).get("story", "")
    elif isinstance(target, StoryNode) and target.segment is not None:
        for field in ("title", "text"):
            yield field, target.segment.get(field, "")
    elif isinstance(target, (Volume, PlotUnit)):
        yield "summary", target.summary or ""


def _pairs(renamed: list[dict]) -> list[tuple[str, str]]:
    pairs = []
    for item in renamed:
        if not isinstance(item, dict):
            continue
        old, new = item.get("old"), item.get("new")
        if isinstance(old, str) and isinstance(new, str) and old and new and old != new and (old, new) not in pairs:
            pairs.append((old, new))
    return pairs


def _signature(row: SettingSuggestion) -> tuple:
    payload = row.payload or {}
    return (
        row.target_type,
        str(row.target_id) if row.target_id else None,
        payload.get("path"),
        payload.get("op"),
        payload.get("old"),
        payload.get("new"),
        payload.get("value") if isinstance(payload.get("value"), str) else None,
    )


def _chapter_matches(chapter: Chapter, old: str) -> dict:
    text, contexts, start = chapter.content, [], 0
    while len(contexts) < 3:
        index = text.find(old, start)
        if index < 0:
            break
        contexts.append(text[max(0, index - 15) : index + len(old) + 15])
        start = index + len(old)
    return {"chapter": chapter.index, "count": text.count(old), "contexts": contexts}


async def generate_cascade_suggestions(
    session: AsyncSession,
    book_id: uuid.UUID,
    target: Any,
    path: str,
    renamed: list[dict],
    *,
    one_line: str = "",
) -> list[SettingSuggestion]:
    """调用方先锁书并完成原处修改；本方法只挂建议并 flush，不提交事务。"""
    pairs = _pairs(renamed)
    if not pairs and not (isinstance(target, WorldEntry) and path.split("@", 1)[0] == "content" and one_line):
        return []
    book = target if isinstance(target, Book) else await session.get(Book, book_id)
    context = await load_context(session, book)
    source_type = target_type_of(target)
    source_field = path.split("@", 1)[0]
    origin = {"target_type": source_type, "target_id": str(target.id), "path": path}
    pending = await session.scalars(
        select(SettingSuggestion).where(SettingSuggestion.book_id == book_id, SettingSuggestion.status == "pending")
    )
    signatures = {_signature(row) for row in pending}
    created = []

    def add(kind, target_type, target_id, title, payload):
        row = SettingSuggestion(
            book_id=book_id,
            kind=kind,
            target_type=target_type,
            target_id=target_id,
            title=title,
            payload=payload,
            origin=origin,
        )
        signature = _signature(row)
        if signature not in signatures:
            signatures.add(signature)
            session.add(row)
            created.append(row)

    chapters = (
        list(
            await session.scalars(
                select(Chapter).where(Chapter.book_id == book_id, Chapter.status == "final").order_by(Chapter.index)
            )
        )
        if pairs
        else []
    )
    targets = [*context.targets, book, *context.nodes, *context.volumes, *context.units]
    for old, new in pairs:
        for other in targets:
            target_type = target_type_of(other)
            for field, text in iter_text_paths(other):
                if target_type == source_type and other.id == target.id and field == source_field:
                    continue
                if old not in text:
                    continue
                title = (
                    f"『{old}』改成了『{new}』，「{context.target_name(other)}」的"
                    f"{context.part_label(other, field)}里还写着旧叫法，要不要一起换？"
                )
                if getattr(other, "locked", False) or isinstance(other, StoryNode) and other.status == "pinned":
                    title += "（已锁）"
                add(
                    "cascade",
                    target_type,
                    other.id,
                    title,
                    {
                        "op": "replace_text",
                        "target_type": target_type,
                        "target_id": str(other.id),
                        "path": field,
                        "old": old,
                        "new": new,
                    },
                )
        matches = [_chapter_matches(chapter, old) for chapter in chapters if old in chapter.content]
        if matches:
            numbers = [match["chapter"] for match in matches]
            label = "、".join(str(number) for number in numbers[:10])
            if len(numbers) > 10:
                label += f"等 {len(numbers)}"
            add(
                "written",
                None,
                None,
                f"『{old}』在第 {label} 章的正文里出现过，要不要把前文也一起换成『{new}』？",
                {"op": "replace_in_chapters", "old": old, "new": new, "chapters": numbers, "matches": matches},
            )
    if isinstance(target, WorldEntry) and source_field == "content" and one_line:
        add(
            "cascade",
            source_type,
            target.id,
            f"『{target.name}』的一段话改了，一句话要不要跟着换成：{one_line}",
            {
                "op": "set_field",
                "target_type": source_type,
                "target_id": str(target.id),
                "path": "one_line",
                "value": one_line,
            },
        )
    await session.flush()
    return created


async def author_rename_suggestions(session: AsyncSession, target: Any, before: dict) -> list[SettingSuggestion]:
    """只比较明确名称字段；纯增删别名或重排不猜测改名关系。"""
    changes = []
    if before.get("name") != target.name:
        changes.append(("name", before.get("name"), target.name))
    old_aliases, new_aliases = before.get("aliases", []), target.aliases or []
    removed = [name for name in old_aliases if name not in new_aliases]
    added = [name for name in new_aliases if name not in old_aliases]
    if len(removed) == len(added):
        changes.extend(("aliases", old, new) for old, new in zip(removed, added, strict=True))
    if isinstance(target, WorldEntry):
        old_levels, new_levels = before.get("levels", []), target.levels or []
        # 先排除只挪位置、删去或插入的级名，再对稳定位置上的新旧名称配对。
        old_names = {level.get("name") for level in old_levels}
        new_names = {level.get("name") for level in new_levels}
        for index, (old, new) in enumerate(zip(old_levels, new_levels, strict=False)):
            if old.get("name") not in new_names and new.get("name") not in old_names:
                changes.append((f"levels.{index}.name", old.get("name"), new.get("name")))
    suggestions = []
    for path, old, new in changes:
        suggestions.extend(
            await generate_cascade_suggestions(session, target.book_id, target, path, [{"old": old, "new": new}])
        )
    return suggestions
