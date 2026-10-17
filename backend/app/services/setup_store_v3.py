"""第三包开书落库：增量建库、作者内容保护和可回退版本。"""

import re
import uuid
from collections import Counter
from copy import deepcopy

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_config import BUILTIN_CATEGORIES, STATUSES
from app.models import (
    Book,
    Chapter,
    Character,
    PlotUnit,
    SettingCategory,
    SettingSuggestion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.services.library import lock_book
from app.services.library_context import load_context
from app.services.versions import json_copy, record_version, snapshot_of

_STATUS_KEYS = {value: key for key, value in STATUSES.items()}
_BUILTINS = {item["key"]: item for item in BUILTIN_CATEGORIES}
_CONCEPT_FIELDS = (
    "story",
    "pitches",
    "title",
    "alt_titles",
    "genre",
    "tags",
    "target_reader",
    "tone",
    "target_length",
    "chapter_words",
    "benchmark",
)
_CHARACTER_FIELDS = (
    "name",
    "aliases",
    "role_type",
    "one_line",
    "gender",
    "age",
    "appearance",
    "personality",
    "background",
    "goal",
    "abilities",
    "relation",
    "want",
)


async def _rows(session, model, book_id, order=None):
    stmt = select(model).where(model.book_id == book_id)
    if order is not None:
        stmt = stmt.order_by(order)
    return list(await session.scalars(stmt))


async def _version(session, book_id, kind, row, before, note):
    await session.flush()
    if before is None or before != snapshot_of(row):
        await record_version(session, book_id, kind, row, "ai", note, before=before)


async def save_story_concept(session: AsyncSession, book_id: uuid.UUID, concept: dict) -> None:
    await lock_book(session, book_id)
    book = await session.get(Book, book_id)
    before = snapshot_of(book)
    merged = {**(book.concept or {}), **{key: deepcopy(concept[key]) for key in _CONCEPT_FIELDS if key in concept}}
    secret = (concept.get("secret") or "").strip()
    if secret and secret != "没有":
        row = await session.scalar(
            select(WorldEntry).where(
                WorldEntry.book_id == book_id, WorldEntry.category == "往事与秘密", WorldEntry.name == "底牌"
            )
        )
        if row is None:
            row = WorldEntry(book_id=book_id, category="往事与秘密", name="底牌")
            session.add(row)
            entry_before = None
        else:
            entry_before = snapshot_of(row)
        if entry_before is None or row.source == "ai":
            row.content = secret
            row.one_line = re.split(r"(?<=[。！？!?])|\n", secret, maxsplit=1)[0]
            row.tags, row.locked, row.status, row.source = ["底牌"], True, "must", "ai"
            await _version(session, book_id, "entry", row, entry_before, "开书：底牌")
        merged["secret_entry_id"] = str(row.id)
    elif secret == "没有":
        merged["secret_entry_id"] = None
    book.concept = merged
    if merged.get("title"):
        book.title = merged["title"]
    if merged.get("genre"):
        book.genre = merged["genre"]
    await _version(session, book_id, "concept", book, before, "开书：定调")


async def _character(session, book_id, data, *, protagonist=False, position=0):
    row = next(
        (
            r
            for r in await _rows(session, Character, book_id)
            if data["name"] in [r.name, *(r.aliases or [])] or r.name in (data.get("aliases") or [])
        ),
        None,
    )
    if row is not None and (row.source not in {"ai", "migration"} or row.locked):
        return row
    before = snapshot_of(row) if row is not None else None
    if row is None:
        row = Character(book_id=book_id, name=data["name"])
        session.add(row)
    for key in _CHARACTER_FIELDS:
        if key in data:
            setattr(row, key, deepcopy(data[key]))
    row.status = _STATUS_KEYS.get(data.get("status"), data.get("status", "must"))
    row.source, row.position = "ai", position
    tags = list(row.tags or [])
    if protagonist:
        row.role_type = "主角"
        tags = list(dict.fromkeys([*tags, "主角"]))
    elif row.status == "must":
        tags = list(dict.fromkeys([*tags, "第一卷"]))
    row.tags = tags
    await _version(session, book_id, "character", row, before, "开书：角色卡片")
    return row


async def _entry(session, book_id, data, *, position=0, tags=()):
    category = data.get("category", "特殊规则")
    category = category if category in _BUILTINS else "特殊规则"
    row = next(
        (
            r
            for r in await _rows(session, WorldEntry, book_id)
            if r.category == category
            and (data["name"] in [r.name, *(r.aliases or [])] or r.name in (data.get("aliases") or []))
        ),
        None,
    )
    if row is not None and (row.source not in {"ai", "migration"} or row.locked):
        return row, False, None
    before = snapshot_of(row) if row is not None else None
    if row is None:
        row = WorldEntry(book_id=book_id, category=category, name=data["name"])
        session.add(row)
    for key in ("one_line", "content", "levels", "fields"):
        if key in data:
            setattr(row, key, deepcopy(data[key]))
    row.style = _BUILTINS[category]["style"]
    row.status = _STATUS_KEYS.get(data.get("status"), data.get("status", "must"))
    row.tags = list(dict.fromkeys([*(row.tags or []), *tags]))
    row.position = 0 if category == "世界与地图" and row.name == "世界概况" else position
    row.source = "ai"
    await session.flush()
    return row, True, before


async def _fill_focus(session, book_id, row, values):
    before = snapshot_of(row)
    if not row.locked:
        for key, value in values.items():
            if key not in {"name", "source", "position"} and hasattr(row, key) and not getattr(row, key):
                setattr(row, key, deepcopy(value))
        await _version(
            session, book_id, "character" if isinstance(row, Character) else "entry", row, before, "开书：补空"
        )
    return row


async def save_library_focus(session: AsyncSession, book_id: uuid.UUID, focus: dict) -> None:
    await lock_book(session, book_id)
    characters = await _rows(session, Character, book_id)
    entries = await _rows(session, WorldEntry, book_id)
    protagonist = next((r for r in characters if r.role_type == "主角"), None)
    if protagonist is None:
        protagonist = await _character(session, book_id, focus["protagonist"], protagonist=True)
    else:
        protagonist = await _fill_focus(
            session,
            book_id,
            protagonist,
            {key: value for key, value in focus["protagonist"].items() if key in _CHARACTER_FIELDS},
        )
    finger = focus["finger"]
    existing = next((r for r in [*characters, *entries] if "金手指" in (r.tags or [])), None)
    if existing is not None:
        values = (
            {"abilities": finger.get("content", "")}
            if isinstance(existing, Character)
            else {key: finger.get(key, "") for key in ("one_line", "content")}
        )
        await _fill_focus(session, book_id, existing, values)
    elif finger["place"] == "角色卡片":
        if not protagonist.locked:
            before = snapshot_of(protagonist)
            if not protagonist.abilities:
                protagonist.abilities = finger.get("content", "")
            protagonist.tags = list(dict.fromkeys([*(protagonist.tags or []), "金手指"]))
            await _version(session, book_id, "character", protagonist, before, "开书：金手指")
    else:
        # A same-name card/entry is also only filled, even if it lacked the tag.
        same = next(
            (r for r in entries if r.category == finger["place"] and finger["name"] in [r.name, *(r.aliases or [])]),
            None,
        )
        if same is not None:
            await _fill_focus(session, book_id, same, {key: finger.get(key, "") for key in ("one_line", "content")})
        else:
            row, writable, before = await _entry(
                session, book_id, {**finger, "category": finger["place"]}, tags=["金手指"]
            )
            if writable:
                await _version(session, book_id, "entry", row, before, "开书：金手指")


async def _suggest(session, book_id, *, kind, title, payload, origin):
    existing = await session.scalar(
        select(SettingSuggestion).where(
            SettingSuggestion.book_id == book_id,
            SettingSuggestion.kind == kind,
            SettingSuggestion.title == title,
            SettingSuggestion.status == "pending",
        )
    )
    if existing is None:
        session.add(
            SettingSuggestion(book_id=book_id, kind=kind, title=title, payload=deepcopy(payload), origin=origin)
        )
    else:
        existing.payload = deepcopy(payload)
    await session.flush()


async def save_library_rest(session: AsyncSession, book_id: uuid.UUID, rest: dict) -> None:
    await lock_book(session, book_id)
    for index, character in enumerate(rest.get("characters") or [], 1):
        rows = await _rows(session, Character, book_id)
        if any(
            character["name"] in [r.name, *(r.aliases or [])]
            or r.name in (character.get("aliases") or [])
            or (character.get("role_type") == "主角" and r.role_type == "主角")
            for r in rows
        ):
            continue
        await _character(session, book_id, character, position=index)
    categories = {category["name"]: category for category in rest.get("categories") or []}
    pending_entries = {name: [] for name in categories}
    saved = []
    for index, entry in enumerate(rest.get("entries") or [], 1):
        category = entry.get("category")
        if category not in _BUILTINS and category in categories:
            pending_entries[category].append(deepcopy(entry))
            continue
        if entry.get("name") == "世界概况" and any(
            r.category == "世界与地图" and r.name == "世界概况" for r in await _rows(session, WorldEntry, book_id)
        ):
            continue
        row, writable, before = await _entry(session, book_id, entry, position=index)
        if writable:
            saved.append((row, entry, before))
    places = {row.name: row for row in await _rows(session, WorldEntry, book_id) if row.category == "世界与地图"}
    for row, entry, before in saved:
        if row.category == "世界与地图":
            parent = places.get(entry.get("parent"))
            # Reject a generated cycle rather than corrupting the editor's tree.
            cursor, visited = parent, {row.id}
            while cursor is not None and cursor.id not in visited:
                visited.add(cursor.id)
                cursor = next((place for place in places.values() if place.id == cursor.parent_id), None)
            row.parent_id = parent.id if parent is not None and cursor is None else None
        await _version(session, book_id, "entry", row, before, "开书：其余设定")
    for name, category in categories.items():
        entries = pending_entries[name]
        await _suggest(
            session,
            book_id,
            kind="gap",
            title=f"建一个自建类别「{name}」，放进{len(entries)}条设定——{category.get('why', '')}",
            payload={
                "op": "create_category",
                "category": {**{k: deepcopy(v) for k, v in category.items() if k != "why"}, "entries": entries},
            },
            origin={"source": "book_setup", "step": "settings_rest"},
        )


def _protected_merge(old, drafts, *, protected, title_key="title"):
    """锁住的原位置由原对象占据；其余按新顺序写入，遗漏的锁定对象保留。"""
    fixed = {index: row for index, row in enumerate(old) if protected(row)}
    reserved = {row.id for row in fixed.values()}
    slots = [(None, draft) for draft in drafts]
    # 先消除模型在别处重复列出的锁定条目，再放回原位置。
    for index, row in fixed.items():
        match = next(
            (
                i
                for i, (_, draft) in enumerate(slots)
                if draft is not None and draft.get(title_key) == getattr(row, title_key)
            ),
            None,
        )
        if match is not None:
            slots.pop(match)
            slots.insert(min(index, len(slots)), (row, None))
        elif index < len(slots):
            slots[index] = (row, None)
        else:
            slots.append((row, None))
    used = set(reserved)
    result = []
    for index, (row, draft) in enumerate(slots):
        if row is None:
            same = next(
                (item for item in old if item.id not in used and getattr(item, title_key) == draft.get(title_key)), None
            )
            fallback = old[index] if index < len(old) and old[index].id not in used else None
            row = same or fallback
            if row is not None:
                used.add(row.id)
        result.append((row, draft))
    return result, [row for row in old if row.id not in used]


async def save_outline(session: AsyncSession, book_id: uuid.UUID, outline: dict) -> None:
    await lock_book(session, book_id)
    old_nodes = await _rows(session, StoryNode, book_id, StoryNode.position)
    old_volumes = await _rows(session, Volume, book_id, Volume.index)
    old_units = await _rows(session, PlotUnit, book_id, PlotUnit.index)
    chapters = await _rows(session, Chapter, book_id, Chapter.index)
    written_units = {chapter.unit_id for chapter in chapters if chapter.content or chapter.status == "final"}
    kept_volume_ids = {unit.volume_id for unit in old_units if unit.locked or unit.id in written_units}
    first_summary = next(iter(outline.get("units") or []), {}).get("summary", "")
    drafts = [{"kind": "opening", "title": "开篇", "event": first_summary}]
    drafts += [
        {
            "kind": "milestone",
            "title": arc["title"],
            "event": arc.get("text", ""),
            "segment": {"title": arc["title"], "text": arc.get("text", "")} if index == 0 else None,
        }
        for index, arc in enumerate(outline.get("arcs") or [])
    ]
    drafts += [{"kind": "ending", "title": "结局", "event": outline.get("ending", "")}]
    # 开篇、结局固定在树的两端，不能被遗漏的锁定篇占掉。
    middle, removed_nodes = _protected_merge(
        [row for row in old_nodes if row.kind == "milestone"],
        drafts[1:-1],
        protected=lambda row: row.status == "pinned",
    )
    opening = next((row for row in old_nodes if row.kind == "opening"), None)
    ending = next((row for row in old_nodes if row.kind == "ending"), None)
    nodes = [(opening, drafts[0]), *middle, (ending, drafts[-1])]
    saved_nodes = []
    for position, (row, draft) in enumerate(nodes, 1):
        before = snapshot_of(row) if row is not None else None
        if row is None:
            row = StoryNode(book_id=book_id, position=position, kind=draft["kind"])
            session.add(row)
        if row.status != "pinned" and draft is not None:
            row.kind, row.title, row.event = draft["kind"], draft["title"], draft["event"]
            row.segment, row.status, row.origin = draft.get("segment"), "pencil", "ai"
        row.position = position
        await session.flush()
        if row.kind == "milestone":
            await _version(session, book_id, "segment", row, before, "开书：篇")
        saved_nodes.append(row)
    target = next((row for row in saved_nodes if row.kind == "milestone"), None)
    volumes, removed_volumes = _protected_merge(
        old_volumes, outline.get("volumes") or [], protected=lambda row: row.locked or row.id in kept_volume_ids
    )
    # Move indices aside before a permutation to avoid immediate UNIQUE violations.
    for row in old_volumes:
        row.index = -row.index
    await session.flush()
    first_volume = None
    first_volume_before = None
    for index, (row, draft) in enumerate(volumes, 1):
        before = snapshot_of(row) if row is not None else None
        if row is None:
            row = Volume(book_id=book_id, index=index, title=draft["title"])
            session.add(row)
        if not row.locked and draft is not None:
            row.title, row.summary = draft["title"], draft.get("summary", "")
            row.chapter_count = draft.get("chapter_count", 0)
            row.target_node_id = target.id if target else None
            row.status = "approved" if index == 1 else "planned"
        row.index = index
        await session.flush()
        if index == 1:
            first_volume, first_volume_before = row, before
        else:
            await _version(session, book_id, "volume", row, before, "开书：卷")
    if first_volume is not None:
        previous_first_volume = old_volumes[0] if old_volumes else None
        if previous_first_volume is not None and previous_first_volume.id != first_volume.id:
            # 原第 1 卷挪到后面时，原单元不再是这次开书要展开的部分。
            # 先撤下未锁、未写的单元与章纲，避免旧章号占位使新第 1 卷从中途开始。
            for unit in old_units:
                if (
                    unit.volume_id == previous_first_volume.id
                    and not previous_first_volume.locked
                    and not unit.locked
                    and unit.id not in written_units
                ):
                    await session.execute(
                        delete(Chapter).where(
                            Chapter.unit_id == unit.id, Chapter.content == "", Chapter.status != "final"
                        )
                    )
                    await session.delete(unit)
            await session.flush()
        existing = [unit for unit in old_units if unit.volume_id == first_volume.id]
        previous_first = existing[0] if existing else None
        previous_first_text = (previous_first.title, previous_first.summary) if previous_first else None
        saved_units = []
        units, removed_units = _protected_merge(
            existing, outline.get("units") or [], protected=lambda row: row.locked or row.id in written_units
        )
        for row in existing:
            row.index = -row.index
        await session.flush()
        for index, (row, draft) in enumerate(units, 1):
            before = snapshot_of(row) if row is not None else None
            if row is None:
                row = PlotUnit(book_id=book_id, volume_id=first_volume.id, index=index, title=draft["title"])
                session.add(row)
            if not row.locked and row.id not in written_units and draft is not None:
                changed = row.title != draft["title"] or row.summary != draft.get("summary", "")
                if changed and row.id is not None:
                    await session.execute(
                        delete(Chapter).where(
                            Chapter.unit_id == row.id, Chapter.content == "", Chapter.status != "final"
                        )
                    )
                    row.status = "planned"
                row.title, row.summary = draft["title"], draft.get("summary", "")
                row.chapter_count = draft.get("chapter_count", 0)
            row.index = index
            await _version(session, book_id, "unit", row, before, "开书：单元")
            saved_units.append(row)
        if (
            previous_first is not None
            and saved_units
            and previous_first_text != (saved_units[0].title, saved_units[0].summary)
        ):
            # 第一单元换成另一行时，旧第一单元的未写章纲也必须撤下。
            # 否则旧章号仍占着 1 起的位置，新第一单元会从后面的章号开始。
            for row in {previous_first.id: previous_first, saved_units[0].id: saved_units[0]}.values():
                if not row.locked and row.id not in written_units:
                    await session.execute(
                        delete(Chapter).where(
                            Chapter.unit_id == row.id, Chapter.content == "", Chapter.status != "final"
                        )
                    )
                    row.status = "planned"
        for row in removed_units:
            await session.execute(
                delete(Chapter).where(Chapter.unit_id == row.id, Chapter.content == "", Chapter.status != "final")
            )
            await session.delete(row)
        if not first_volume.locked:
            await session.flush()
            first_volume.chapter_count = sum(
                row.chapter_count for row in await _rows(session, PlotUnit, book_id) if row.volume_id == first_volume.id
            )
        await _version(session, book_id, "volume", first_volume, first_volume_before, "开书：卷")
    for row in removed_volumes:
        await session.execute(
            delete(Chapter).where(Chapter.volume_id == row.id, Chapter.content == "", Chapter.status != "final")
        )
        await session.delete(row)
    for row in removed_nodes:
        await session.execute(
            update(Volume).where(Volume.target_node_id == row.id).values(target_node_id=target.id if target else None)
        )
        await session.delete(row)
    known = await _rows(session, Character, book_id) + await _rows(session, WorldEntry, book_id)
    names = {name for row in known for name in [row.name, *(row.aliases or [])]}
    custom_categories = await _rows(session, SettingCategory, book_id)
    custom_keys = {key: f"custom:{row.key}" for row in custom_categories for key in (row.name, f"custom:{row.key}")}
    custom_names = {f"custom:{row.key}": row.name for row in custom_categories}
    for item in outline.get("new_names") or []:
        if item["name"] in names:
            continue
        category = item.get("category", "特殊规则")
        character = category == "角色卡片"
        category = category if category in _BUILTINS or character else custom_keys.get(category, "特殊规则")
        category_name = custom_names.get(category, category)
        data = {"name": item["name"], "one_line": item.get("one_line", ""), "status": "one"}
        data.update({"role_type": "配角"} if character else {"category": category})
        await _suggest(
            session,
            book_id,
            kind="new_entry",
            title=f"大纲里出现了「{item['name']}」，要给它建一条{category_name}吗？",
            payload={
                "op": "create_character" if character else "create_entry",
                "character" if character else "entry": data,
            },
            origin={"source": "book_setup", "step": "outline"},
        )
    await session.flush()


async def load_new_setup(session: AsyncSession, book_id: uuid.UUID) -> dict:
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    context = await load_context(session, book)
    concept = deepcopy(context.book.concept or {})
    secret = next((row for row in context.entries if str(row.id) == str(concept.get("secret_entry_id"))), None)
    concept["secret"] = secret.content if secret is not None else "没有"

    def detail(row):
        return {"id": str(row.id), **snapshot_of(row), "source": row.source}

    characters, entries = [detail(row) for row in context.characters], [detail(row) for row in context.entries]
    counts = Counter(row.status for row in context.targets)
    suggestions = await _rows(session, SettingSuggestion, book_id)
    count = sum(row.status == "pending" for row in suggestions)
    summary = f"主编建了 {len(context.targets)} 条：现在要定 {counts['must']} 条，一句话 {counts['one']} 条，以后再说 {counts['later']} 条。先看「重点」就行。"
    if count:
        summary += f"另外有 {count} 条建议等你看。"
    units = [
        {
            "id": str(row.id),
            "index": row.index,
            "volume_id": str(row.volume_id),
            "status": row.status,
            **snapshot_of(row),
        }
        for row in context.units
    ]
    volumes = [
        {
            "id": str(row.id),
            "index": row.index,
            "status": row.status,
            **snapshot_of(row),
            "units": [unit for unit in units if unit["volume_id"] == str(row.id)],
        }
        for row in context.volumes
    ]
    chapters = await _rows(session, Chapter, book_id, Chapter.index)
    first_units = volumes[0]["units"] if volumes else []
    chapter_data = [
        {"id": str(row.id), "index": row.index, "title": row.title, "outline": json_copy(row.outline)}
        for row in chapters
        if first_units and str(row.unit_id) == first_units[0]["id"]
    ]
    arcs = [
        {
            "id": str(row.id),
            "title": row.title,
            "text": (row.segment or {}).get("text", row.event),
            "planned": row.segment is not None,
            "status": row.status,
            "segment": deepcopy(row.segment),
        }
        for row in context.nodes
        if row.kind == "milestone"
    ]
    ending = next((row.event for row in context.nodes if row.kind == "ending"), "")
    return {
        "concept": concept,
        "settings": {
            "characters": characters,
            "entries": entries,
            "categories": context.categories,
            "summary": summary,
            "suggestion_count": count,
        },
        "outline": {"arcs": arcs, "ending": ending, "volumes": volumes, "units": first_units, "chapters": chapter_data},
        "outline_chapters": {"chapters": chapter_data},
        "locked_names": [row.title for row in context.nodes if row.status == "pinned"]
        + [row.title for row in [*context.volumes, *context.units] if row.locked],
    }
