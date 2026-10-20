"""新书页右栏的只读汇总：与取样张数据脚本同一套计数和先后顺序。"""

from collections import Counter

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.context import foreshadow_code
from app.models import Chapter, Character, Foreshadowing, PlotUnit, StoryNode, Volume


def mapped_name(name: str, names: dict) -> str:
    name, seen = name.strip(), set()
    while name in names and names[name] and name not in seen:
        seen.add(name)
        name = names[name].strip()
    return name


def people_count(records: list[dict], names: dict) -> list[dict]:
    counts, first = Counter(), {}
    for chapter in sorted(records, key=lambda row: row["index"]):
        seen = set()
        for person in chapter["read"].get("people", []):
            name = mapped_name(person["name"], names)
            if name and name not in seen:
                seen.add(name)
                counts[name] += 1
                first.setdefault(name, chapter["index"])
    return [
        {"name": name, "chapters": count, "first": first[name]}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], first[item[0]]))
    ]


async def read_records(session, book_id) -> list[dict]:
    # 只投影记录和归属，不把整本原文或章纲读进内存。
    rows = await session.execute(
        select(Chapter.index, Chapter.unit_id, Chapter.volume_id, Chapter.teardown)
        .where(Chapter.book_id == book_id)
        .order_by(Chapter.index)
    )
    return [
        {"index": index, "unit_id": unit_id, "volume_id": volume_id, "read": teardown.get("read") or {}}
        for index, unit_id, volume_id, teardown in rows
        if teardown and teardown.get("read_version")
    ]


async def digest(session, book, *, unit=None, volume=None, arc=None) -> dict:
    empty = {"people": [], "things": [], "waits": [], "hero": None, "changes": []}
    if book.source != "teardown":
        return empty
    if sum(value is not None for value in (unit, volume, arc)) != 1:
        raise HTTPException(422, "单元、卷和篇必须且只能选一个")
    model, target_id, key = (
        (PlotUnit, unit, "unit_id")
        if unit is not None
        else (Volume, volume, "volume_id")
        if volume is not None
        else (StoryNode, arc, "volume_id")
    )
    lookup = select(model.id).where(model.id == target_id, model.book_id == book.id)
    if arc is not None:
        lookup = lookup.where(StoryNode.kind == "milestone", StoryNode.segment.is_not(None))
    if not await session.scalar(lookup):
        raise HTTPException(404, "单元不存在" if unit is not None else "卷不存在" if volume is not None else "篇不存在")
    volume_ids = (
        set(await session.scalars(select(Volume.id).where(Volume.book_id == book.id, Volume.target_node_id == arc)))
        if arc is not None
        else None
    )
    names = (book.teardown or {}).get("names") or {}
    records = await read_records(session, book.id)
    all_people = people_count(records, names)
    hero = all_people[0]["name"] if all_people else None
    scope = (
        [row for row in records if row[key] in volume_ids]
        if volume_ids is not None
        else [row for row in records if row[key] == target_id]
    )
    things, waits, changes, seen = [], [], [], set()
    for chapter in scope:
        index, read = chapter["index"], chapter["read"]
        for thing in read.get("things", []):
            name = thing["name"].strip()
            identity = (thing["kind"], name)
            if identity not in seen:
                seen.add(identity)
                things.append(
                    dict(
                        chapter=index,
                        kind=thing["kind"],
                        name=name,
                        **{k: thing.get(k, "") for k in ("note", "belongs", "secret")},
                    )
                )
        waits.extend(dict(chapter=index, action=wait["action"], what=wait["what"]) for wait in read.get("waits", []))
        for person in read.get("people", []):
            identities = [person["name"], person.get("was", ""), *person.get("also_called", [])]
            if hero and any(mapped_name(name, names) == hero for name in identities) and person.get("change"):
                changes.append({"chapter": index, "change": person["change"]})
    return {"people": people_count(scope, names), "things": things, "waits": waits, "hero": hero, "changes": changes}


async def waits(session, book) -> dict:
    if book.source != "teardown":
        return {"upto": None, "last": 0, "items": []}
    last = await session.scalar(
        select(Chapter.index)
        .where(Chapter.book_id == book.id, Chapter.teardown["read_version"].astext.is_not(None))
        .order_by(Chapter.index.desc())
        .limit(1)
    )
    rows = await session.scalars(
        select(Foreshadowing)
        .where(Foreshadowing.book_id == book.id)
        .order_by(Foreshadowing.planted_chapter, Foreshadowing.seq)
    )
    items = []
    for row in rows:
        prefix = f"第 {row.resolved_chapter} 章："
        items.append(
            {
                "code": foreshadow_code({"seq": row.seq, "kind": row.kind}),
                "kind": row.kind,
                "what": row.description,
                "planted": row.planted_chapter,
                "hints": row.hint_chapters or [],
                "resolved": row.resolved_chapter,
                "how": (row.payoff_plan or "").removeprefix(prefix),
            }
        )
    return {"upto": ((book.teardown or {}).get("waits") or {}).get("upto"), "last": last or 0, "items": items}


async def appearances(session, book, character_id) -> dict:
    if book.source != "teardown":
        return {"chapters": []}
    character = await session.scalar(
        select(Character).where(Character.id == character_id, Character.book_id == book.id)
    )
    if character is None:
        raise HTTPException(404, "角色不存在")
    names = {name.strip() for name in [character.name, *(character.aliases or [])] if name.strip()}
    chapters = []
    for chapter in await read_records(session, book.id):
        if any(
            person["name"].strip() in names
            or person.get("was", "").strip() in names
            or names.intersection(alias.strip() for alias in person.get("also_called", []))
            for person in chapter["read"].get("people", [])
        ):
            chapters.append(chapter["index"])
    return {"chapters": chapters}
