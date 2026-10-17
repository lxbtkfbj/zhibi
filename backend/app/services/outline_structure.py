"""作者调整大纲结构：同一书锁内重排，只移动尚未开写的章纲。"""

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planning import fit_chapter_counts
from app.models import Chapter, PlotUnit, Volume
from app.services.versions import record_version, snapshot_of


def started(chapter: Chapter) -> bool:
    return chapter.status != "planned" or bool(chapter.content)


@dataclass
class Structure:
    volumes: list[Volume]
    units: list[PlotUnit]
    chapters: list[Chapter]
    before: dict

    def own_units(self, volume_id: uuid.UUID) -> list[PlotUnit]:
        return sorted((u for u in self.units if u.volume_id == volume_id), key=lambda u: u.index)

    def own_chapters(self, target: Volume | PlotUnit) -> list[Chapter]:
        return [
            c
            for c in self.chapters
            if (c.volume_id == target.id if isinstance(target, Volume) else c.unit_id == target.id)
        ]

    def ensure_unwritten(self, target: Volume | PlotUnit, message: str) -> None:
        if any(started(c) for c in self.own_chapters(target)):
            raise HTTPException(409, message)


async def load_structure(session: AsyncSession, book_id: uuid.UUID) -> Structure:
    rows = []
    for model in (Volume, PlotUnit, Chapter):
        rows.append(
            list(
                await session.scalars(
                    select(model)
                    .where(model.book_id == book_id)
                    .order_by(model.index)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
        )
    volumes, units, chapters = rows
    before = {row.id: (row.index, snapshot_of(row)) for row in [*volumes, *units]}
    return Structure(volumes, units, chapters, before)


async def assign_indices(session: AsyncSession, rows: list, numbers: list[int]) -> None:
    """两次 flush 避免交换或向前插入时撞到非延迟唯一约束。"""
    changed = [(row, number) for row, number in zip(rows, numbers, strict=True) if row.index != number]
    if not changed:
        return
    model = type(rows[0])
    occupied_min = await session.scalar(select(func.min(model.index)).where(model.book_id == rows[0].book_id))
    # 删除中的行还占着临时负号，但已不在 rows 里；临时区间必须同时避开数据库里的它。
    floor = min(occupied_min or 0, *(row.index for row in rows)) - len(rows) - 1
    for offset, (row, _) in enumerate(changed):
        row.index = floor - offset
    await session.flush()
    for row, number in changed:
        row.index = number
    await session.flush()


async def resize_unit(session: AsyncSession, state: Structure, unit: PlotUnit, count: int) -> None:
    state.ensure_unwritten(unit, "这个单元已经开写了，不能改章数")
    own = state.own_chapters(unit)
    # 缩短只裁掉末尾的计划章纲；扩长保留原章纲，写到后面时补出缺少的章纲。
    for chapter in own[count:]:
        state.chapters.remove(chapter)
        await session.delete(chapter)
    unit.chapter_count = count
    if count > len(own):
        unit.status = "planned"
    await session.flush()


async def resize_target(session: AsyncSession, state: Structure, target: Volume | PlotUnit, count: int) -> None:
    if isinstance(target, PlotUnit):
        await resize_unit(session, state, target, count)
        volume = next(v for v in state.volumes if v.id == target.volume_id)
        volume.chapter_count = sum(u.chapter_count for u in state.own_units(volume.id))
        return
    state.ensure_unwritten(target, "这一卷已经开写了，不能改章数")
    units = state.own_units(target.id)
    if units and count < len(units):
        raise HTTPException(422, "章数不能少于单元数，每个单元至少一章")
    plans = fit_chapter_counts([{"chapter_count": unit.chapter_count} for unit in units], count, minimum=1)
    for unit, plan in zip(units, plans, strict=True):
        if plan["chapter_count"] > 50:
            raise HTTPException(422, "每个单元最多 50 章，请先增加单元")
        await resize_unit(session, state, unit, plan["chapter_count"])
    target.chapter_count = count


def chapter_positions(state: Structure) -> dict[uuid.UUID, int]:
    """已拆的卷以单元章数为准；未拆的卷以卷章数预留空间。"""
    owned = {u.id for u in state.units}
    attached = {v.id for v in state.volumes}
    orphan = [c for c in state.chapters if c.unit_id not in owned and c.volume_id not in attached]
    cursor = max((c.index for c in orphan), default=0) + 1
    positions = {}
    for volume in sorted(state.volumes, key=lambda v: v.index):
        units = state.own_units(volume.id)
        if not units:
            own = state.own_chapters(volume)
            for offset, chapter in enumerate(own):
                positions[chapter.id] = cursor + offset
            cursor += max(volume.chapter_count, len(own))
            continue
        for unit in units:
            own = state.own_chapters(unit)
            for offset, chapter in enumerate(own):
                positions[chapter.id] = cursor + offset
            cursor += max(unit.chapter_count, len(own))
    return positions


async def finish_structure(
    session: AsyncSession,
    book_id: uuid.UUID,
    state: Structure,
    note: str,
    *,
    affected: set[uuid.UUID] | None = None,
    deleted: list[Volume | PlotUnit] | None = None,
    source: str = "author",
) -> None:
    """调用方先设置卷／单元顺序；此处顺延章号并给所有受影响节点记版。"""
    affected = set(affected or ())
    positions = chapter_positions(state)
    changed = [c for c in state.chapters if c.id in positions and positions[c.id] != c.index]
    if any(started(chapter) for chapter in changed):
        raise HTTPException(409, "这样调整会挪动已经开写的章节，请只改后面的部分")
    for chapter in changed:
        affected.update((chapter.volume_id, chapter.unit_id))
        if "index" in (chapter.outline or {}):
            chapter.outline = {**chapter.outline, "index": positions[chapter.id]}
    await assign_indices(session, state.chapters, [positions.get(c.id, c.index) for c in state.chapters])
    for row in [*state.volumes, *state.units, *(deleted or [])]:
        before = state.before.get(row.id)
        changed_index = before is not None and before[0] != row.index and row not in (deleted or [])
        if before is None or changed_index or row.id in affected or before[1] != snapshot_of(row):
            position_note = f"；序号 {before[0]} → {row.index}" if changed_index else ""
            await record_version(
                session,
                book_id,
                "volume" if isinstance(row, Volume) else "unit",
                row,
                source,
                note + position_note,
                before=before[1] if before else None,
            )
