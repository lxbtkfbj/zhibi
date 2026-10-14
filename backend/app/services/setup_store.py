"""开书方案与数据库之间的读写：方案 dict ⇄ 设定库 / 大纲表。"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Book,
    Character,
    DraftVersion,
    Foreshadowing,
    PlotUnit,
    Relationship,
    Volume,
    WorldEntry,
)

CHARACTER_FIELDS = (
    "name",
    "role_type",
    "gender",
    "age",
    "appearance",
    "personality",
    "background",
    "abilities",
    "goal",
    "location",
    "condition",
    "secrets",
)
UNIT_FIELDS = ("index", "title", "chapter_count", "goal", "conflict", "climax", "outcome", "key_events")


async def save_setup(session: AsyncSession, book_id: uuid.UUID, setup: dict[str, dict[str, Any]]) -> None:
    """开书阶段整体替换：设定库与大纲以本次方案为准（方案本身已包含作者的手动修改）。

    setup 含 concept / lore / spine / outline 四部分，格式与 AI 产出一致。
    """
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    concept, lore, outline = setup.get("concept") or {}, setup.get("lore") or {}, setup.get("outline") or {}
    book.concept = concept
    book.spine = setup.get("spine") or {}
    book.title = concept.get("title") or book.title
    book.genre = concept.get("genre", "")

    for model in (Relationship, Character, WorldEntry, Foreshadowing, Volume):
        await session.execute(delete(model).where(model.book_id == book_id))
    await session.flush()

    by_name: dict[str, Character] = {}
    for ch in lore.get("characters", []):
        name = ch.get("name", "").strip()
        if not name or name in by_name:
            continue
        row = Character(book_id=book_id, **{k: ch.get(k) for k in CHARACTER_FIELDS if ch.get(k) is not None})
        session.add(row)
        by_name[name] = row
    for w in lore.get("world_entries", []):
        session.add(
            WorldEntry(
                book_id=book_id, category=w.get("category", "其他"), name=w["name"], content=w.get("content", "")
            )
        )
    await session.flush()

    for r in lore.get("relationships", []):
        a, b = by_name.get(r.get("source", "")), by_name.get(r.get("target", ""))
        if a and b and a is not b:
            session.add(
                Relationship(
                    book_id=book_id,
                    source_id=a.id,
                    target_id=b.id,
                    kind=r.get("kind", ""),
                    description=r.get("description", ""),
                )
            )

    units = outline.get("first_volume_units", [])
    for v in outline.get("volumes", []):
        is_first = v.get("index") == 1
        volume = Volume(
            book_id=book_id,
            index=v["index"],
            title=v.get("title", ""),
            summary=v.get("summary", ""),
            goal=v.get("goal", ""),
            chapter_count=v.get("chapter_count") or 0,
            status="detailed" if is_first and units else "planned",
        )
        session.add(volume)
        await session.flush()
        if is_first:
            for u in units:
                session.add(PlotUnit(volume_id=volume.id, book_id=book_id, **{k: u.get(k) for k in UNIT_FIELDS}))

    for f in outline.get("foreshadowings", []):
        session.add(
            Foreshadowing(
                book_id=book_id,
                description=f.get("description", ""),
                plant_plan=f.get("plant_plan", ""),
                payoff_plan=f.get("payoff_plan", ""),
            )
        )
    await session.flush()


async def load_setup(session: AsyncSession, book_id: uuid.UUID) -> dict[str, dict]:
    """从数据库读出当前方案（含作者的手动修改），格式与 AI 产出一致。"""
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    characters = (
        (await session.execute(select(Character).where(Character.book_id == book_id).order_by(Character.created_at)))
        .scalars()
        .all()
    )
    names = {c.id: c.name for c in characters}
    world = (
        (await session.execute(select(WorldEntry).where(WorldEntry.book_id == book_id).order_by(WorldEntry.created_at)))
        .scalars()
        .all()
    )
    relations = (await session.execute(select(Relationship).where(Relationship.book_id == book_id))).scalars().all()
    volumes = (
        (await session.execute(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index))).scalars().all()
    )
    foreshadowings = (
        (
            await session.execute(
                select(Foreshadowing).where(Foreshadowing.book_id == book_id).order_by(Foreshadowing.created_at)
            )
        )
        .scalars()
        .all()
    )

    first_units: list[dict] = []
    if volumes:
        rows = (
            (
                await session.execute(
                    select(PlotUnit).where(PlotUnit.volume_id == volumes[0].id).order_by(PlotUnit.index)
                )
            )
            .scalars()
            .all()
        )
        first_units = [{k: getattr(u, k) for k in UNIT_FIELDS} for u in rows]

    lore = {
        "world_entries": [{"category": w.category, "name": w.name, "content": w.content} for w in world],
        "characters": [{k: getattr(c, k) for k in CHARACTER_FIELDS} for c in characters],
        "relationships": [
            {
                "source": names.get(r.source_id, ""),
                "target": names.get(r.target_id, ""),
                "kind": r.kind,
                "description": r.description,
            }
            for r in relations
        ],
    }
    outline = {
        "volumes": [
            {"index": v.index, "title": v.title, "summary": v.summary, "goal": v.goal, "chapter_count": v.chapter_count}
            for v in volumes
        ],
        "first_volume_units": first_units,
        "foreshadowings": [
            {"description": f.description, "plant_plan": f.plant_plan, "payoff_plan": f.payoff_plan}
            for f in foreshadowings
        ],
    }
    return {"concept": dict(book.concept or {}), "lore": lore, "spine": dict(book.spine or {}), "outline": outline}


async def snapshot(
    session: AsyncSession,
    book_id: uuid.UUID,
    job_id: uuid.UUID | None,
    round_: int,
    source: str,
    note: str,
    payload: dict,
) -> None:
    session.add(DraftVersion(book_id=book_id, job_id=job_id, round=round_, source=source, note=note, payload=payload))
