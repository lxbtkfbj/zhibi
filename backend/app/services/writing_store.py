"""写作阶段的入库：卷纲、章纲、定稿后的设定变化（以及重写时撤销）。都是校验后的增量修改，不整体重建。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.glossary import clean_techniques
from app.agents.planning import ref_seq
from app.models import Chapter, Character, Foreshadowing, PlotUnit, Volume
from app.services.setup_store import FORESHADOW_FIELDS, UNIT_FIELDS

# 定稿时设定师会改的人物状态、伏笔进展；记下改前改后的值，重写时据此撤销
CHARACTER_STATE = ("location", "condition", "abilities", "is_alive")
LEDGER_STATE = ("status", "planted_chapter", "hint_chapters", "resolved_chapter")


def _state(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: (list(getattr(row, k) or []) if k == "hint_chapters" else getattr(row, k)) for k in keys}


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
                setattr(row, key, clean_techniques(u[key]) if key == "techniques" else u[key])
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
            # 任务 1 的旧 VolumePlan 只管理伏笔，不能因为它尚不会输出期待而删除作者已建的期待。
            if (
                row.kind == "伏笔"
                and row.plant_volume == volume.index
                and row.span != "长"
                and row.status == "planned"
                and seq not in keep
            ):
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
    """把设定师提取的变化写进设定库：只认设定库里已有的人物和台账里已有的伏笔编号。

    每处改动都记下改之前和改之后的值（chapter.bible_changes），重写这一章时据此撤销。
    这一章以前记过的改动（重写后重新提取时）先撤销再写。
    """
    await revert_chapter(session, book_id, chapter)
    log: dict[str, list] = {"characters": [], "created": [], "foreshadowings": []}
    characters = {
        c.name: c
        for c in (await session.execute(select(Character).where(Character.book_id == book_id))).scalars().all()
    }
    # 重写前面的章节时，后面的章节改过的人物状态更新，不能被这一章的旧状态盖掉
    later = set()
    for changes in (
        await session.execute(
            select(Chapter.bible_changes).where(
                Chapter.book_id == book_id, Chapter.status == "final", Chapter.index > chapter.index
            )
        )
    ).scalars():
        for item in (changes or {}).get("characters") or []:
            after = item.get("after") or {}
            later |= {(item.get("name"), k) for k, v in (item.get("before") or {}).items() if after.get(k) != v}
    updated = created = 0
    for change in digest.character_updates:
        row = characters.get(change.name.strip())
        if row is None:
            continue
        before = _state(row, CHARACTER_STATE)
        for key in ("location", "condition", "abilities"):
            value = getattr(change, key).strip()
            if value and value != getattr(row, key) and (row.name, key) not in later:
                setattr(row, key, value)
        if not change.is_alive and row.is_alive and (row.name, "is_alive") not in later:
            row.is_alive = False
        after = _state(row, CHARACTER_STATE)
        if after != before:
            log["characters"].append({"name": row.name, "before": before, "after": after})
            updated += 1
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
        log["created"].append(name)
        created += 1

    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    moved = 0
    for change in digest.foreshadow_updates:
        row = ledger.get(ref_seq(change.ref) or -1)
        if row is None or row.status == "abandoned":
            continue
        before = _state(row, LEDGER_STATE)
        if row.status == "resolved":
            # 已经收了的伏笔只补记埋在哪一章（重写前面的章节后会出现这种情况）
            if change.action == "埋下" and not row.planted_chapter:
                row.planted_chapter = chapter.index
        elif change.action == "埋下" and row.status == "planned":
            row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "提醒" and chapter.index not in (row.hint_chapters or []):
            row.hint_chapters = sorted([*(row.hint_chapters or []), chapter.index])
            if row.status == "planned":
                row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "回收":
            row.status, row.resolved_chapter = "resolved", chapter.index
            row.planted_chapter = row.planted_chapter or chapter.index
        after = _state(row, LEDGER_STATE)
        if after == before:
            continue
        log["foreshadowings"].append({"seq": row.seq, "before": before, "after": after})
        moved += 1

    chapter.summary = digest.summary.strip()
    chapter.bible_changes = log
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


async def later_finals(session: AsyncSession, book_id: uuid.UUID, index: int) -> int:
    """这一章后面已经定稿了几章。"""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.book_id == book_id, Chapter.status == "final", Chapter.index > index)
        )
        or 0
    )


async def revert_chapter(session: AsyncSession, book_id: uuid.UUID, chapter: Chapter) -> dict[str, int]:
    """撤销这一章定稿时记进设定库和伏笔台账的改动。

    只改回「现在还是这一章改成的样子」的字段；后面的章节又改过的保持不动。这一章新建的人物，
    后面没有定稿的章节时才删掉（后面的章节可能已经写到这个人）。
    """
    log = chapter.bible_changes or {}
    out = {"characters": 0, "removed": 0, "foreshadowings": 0}
    if not any(log.get(k) for k in ("characters", "created", "foreshadowings")):
        chapter.bible_changes = {}
        return out
    later = await later_finals(session, book_id, chapter.index)
    characters = {
        c.name: c
        for c in (await session.execute(select(Character).where(Character.book_id == book_id))).scalars().all()
    }
    for item in reversed(log.get("characters") or []):
        row = characters.get(item.get("name", ""))
        if row is None:
            continue
        changed = False
        for key, before in (item.get("before") or {}).items():
            if key in CHARACTER_STATE and getattr(row, key) == (item.get("after") or {}).get(key):
                setattr(row, key, before)
                changed = True
        out["characters"] += changed
    for name in log.get("created") or []:
        row = characters.get(name)
        if row is not None and row.first_appearance_chapter == chapter.index and not later:
            await session.delete(row)
            out["removed"] += 1
    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    for item in reversed(log.get("foreshadowings") or []):
        row = ledger.get(item.get("seq"))
        if row is None:
            continue
        before, after = item.get("before") or {}, item.get("after") or {}
        changed = False
        for key in LEDGER_STATE:
            if key not in before:
                continue
            if key == "hint_chapters":
                current = list(row.hint_chapters or [])
                if chapter.index in current and chapter.index not in (before.get(key) or []):
                    row.hint_chapters = [c for c in current if c != chapter.index]
                    changed = True
            elif getattr(row, key) == after.get(key) and getattr(row, key) != before[key]:
                setattr(row, key, before[key])
                changed = True
        out["foreshadowings"] += changed
    chapter.bible_changes = {}
    await session.flush()
    return out


async def reopen_chapter(session: AsyncSession, book_id: uuid.UUID, chapter: Chapter) -> dict[str, int]:
    """作者要重写一章已定稿的章节：撤销它记进设定库的改动，章节回到写作中；所在单元和卷的回顾作废，重写后重新写。"""
    changes = await revert_chapter(session, book_id, chapter)
    chapter.status = "drafting"
    chapter.attempts = 0
    if chapter.unit_id:
        unit = await session.get(PlotUnit, chapter.unit_id)
        if unit is not None:
            unit.status, unit.recap = "outlined", ""
    if chapter.volume_id:
        volume = await session.get(Volume, chapter.volume_id)
        if volume is not None:
            volume.recap = ""
            if volume.status == "done":
                volume.status = "approved"
    await session.flush()
    return changes
