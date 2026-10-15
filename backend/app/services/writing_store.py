"""写作阶段的入库：卷纲、章纲、定稿后的设定变化。都是校验后的增量修改，不整体重建。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.planning import ref_seq
from app.models import Chapter, Character, Foreshadowing, PlotUnit, Volume
from app.services.setup_store import FORESHADOW_FIELDS, UNIT_FIELDS


async def save_volume_plan(
    session: AsyncSession,
    book_id: uuid.UUID,
    volume: Volume,
    units: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    *,
    replace_new: bool,
) -> None:
    """保存某一卷的卷纲：剧情单元按序号对齐；本卷新埋的伏笔写进台账。

    replace_new：修改卷纲时，本卷上一版新埋、还没写到的伏笔若这一版不要了，就从台账删掉。
    """
    old_units = {
        u.index: u
        for u in (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volume.id))).scalars().all()
    }
    for u in units:
        index = u.get("index")
        if not index:
            continue
        row = old_units.pop(index, None) or PlotUnit(
            volume_id=volume.id, book_id=book_id, index=index, title=u.get("title", "")
        )
        for key in UNIT_FIELDS:
            if key in u and u[key] is not None:
                setattr(row, key, u[key])
        row.status = "planned"
        session.add(row)
    for row in old_units.values():
        await session.delete(row)

    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    keep = {f["seq"] for f in fresh}
    if replace_new:
        for seq, row in list(ledger.items()):
            if row.plant_volume == volume.index and row.span != "长" and row.status == "planned" and seq not in keep:
                await session.delete(row)
    for f in fresh:
        row = ledger.get(f["seq"]) or Foreshadowing(book_id=book_id, seq=f["seq"], description="")
        for key in FORESHADOW_FIELDS:
            if f.get(key) is not None:
                setattr(row, key, f[key])
        session.add(row)
    if not volume.chapter_count:
        volume.chapter_count = sum(int(u.get("chapter_count") or 0) for u in units)
    volume.status = "detailed"
    await session.flush()


async def next_chapter_index(session: AsyncSession, book_id: uuid.UUID) -> int:
    last = await session.scalar(select(func.coalesce(func.max(Chapter.index), 0)).where(Chapter.book_id == book_id))
    return int(last or 0) + 1


async def create_chapters(
    session: AsyncSession, book_id: uuid.UUID, unit: PlotUnit, chapters: list[dict[str, Any]]
) -> list[Chapter]:
    """把章纲建成章节行（只有章纲、还没有正文），章号接着全书往后排。"""
    start = await next_chapter_index(session, book_id)
    rows = []
    for offset, plan in enumerate(chapters):
        row = Chapter(
            book_id=book_id,
            volume_id=unit.volume_id,
            unit_id=unit.id,
            index=start + offset,
            title=(plan.get("title") or "").strip()[:200],
            outline=plan,
            status="planned",
        )
        session.add(row)
        rows.append(row)
    unit.chapter_count = len(rows)
    unit.status = "outlined"
    await session.flush()
    return rows


async def apply_digest(
    session: AsyncSession, book_id: uuid.UUID, chapter: Chapter, digest: s.ChapterDigest
) -> dict[str, int]:
    """把设定师提取的变化写进设定库：只认设定库里已有的人物和台账里已有的伏笔编号。"""
    characters = {
        c.name: c
        for c in (await session.execute(select(Character).where(Character.book_id == book_id))).scalars().all()
    }
    updated = created = 0
    for change in digest.character_updates:
        row = characters.get(change.name.strip())
        if row is None:
            continue
        touched = False
        for key in ("location", "condition", "abilities"):
            value = getattr(change, key).strip()
            if value and value != getattr(row, key):
                setattr(row, key, value)
                touched = True
        if not change.is_alive and row.is_alive:
            row.is_alive = False
            touched = True
        updated += touched
    for person in digest.new_characters:
        name = person.name.strip()
        if not name or name in characters:
            continue
        row = Character(
            book_id=book_id,
            name=name,
            role_type=person.role_type,
            background=person.background,
            personality=person.personality,
            first_appearance_chapter=chapter.index,
        )
        session.add(row)
        characters[name] = row
        created += 1

    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    moved = 0
    for change in digest.foreshadow_updates:
        row = ledger.get(ref_seq(change.ref) or -1)
        if row is None or row.status in ("resolved", "abandoned"):
            continue
        if change.action == "埋下" and row.status == "planned":
            row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "提醒" and chapter.index not in (row.hint_chapters or []):
            row.hint_chapters = [*(row.hint_chapters or []), chapter.index]
            if row.status == "planned":
                row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "回收":
            row.status, row.resolved_chapter = "resolved", chapter.index
            row.planted_chapter = row.planted_chapter or chapter.index
        else:
            continue
        moved += 1

    chapter.summary = digest.summary.strip()
    chapter.status = "final"
    await session.flush()
    if chapter.unit_id:
        left = await session.scalar(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.unit_id == chapter.unit_id, Chapter.status != "final")
        )
        if not left:
            unit = await session.get(PlotUnit, chapter.unit_id)
            if unit is not None:
                unit.status = "done"
    return {"characters_updated": updated, "characters_created": created, "foreshadowings": moved}
