"""开书方案与数据库之间的读写：方案 dict ⇄ 设定库 / 线索 / 总纲 / 卷纲 / 伏笔台账。

保存是「按名称或序号逐条对齐」的增量更新：已有的行原地更新（ID 不变，作者单独维护的字段如别名、备注、
存活状态、伏笔状态都保留），方案里没有的行才删除，新出现的才插入。
"""

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
    StoryThread,
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
THREAD_FIELDS = ("name", "kind", "summary", "characters", "beats")
VOLUME_FIELDS = (
    "title",
    "stage",
    "summary",
    "goal",
    "climax",
    "antagonist",
    "power_range",
    "thread_beats",
    "new_characters",
    "chapter_count",
)
UNIT_FIELDS = (
    "index",
    "title",
    "chapter_count",
    "goal",
    "conflict",
    "climax",
    "outcome",
    "key_events",
    "thread_beats",
    "foreshadow_actions",
)
FORESHADOW_FIELDS = ("description", "span", "plant_plan", "payoff_plan", "plant_volume", "payoff_volume")


def _assign(row: Any, data: dict[str, Any], fields: tuple[str, ...]) -> None:
    for key in fields:
        if key in data and data[key] is not None:
            setattr(row, key, data[key])


async def _rows(session: AsyncSession, model: Any, *where: Any, order: Any = None) -> list:
    stmt = select(model).where(*where)
    if order is not None:
        stmt = stmt.order_by(order)
    return list((await session.execute(stmt)).scalars().all())


def assign_seqs(items: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给伏笔编号：内容与已有伏笔相同的沿用原编号，新伏笔接着往后编。"""
    by_text = {f.get("description", "").strip(): f.get("seq") for f in existing if f.get("seq")}
    used = {f.get("seq") for f in existing if f.get("seq")}
    next_seq = max(used, default=0) + 1
    out = []
    for item in items:
        seq = item.get("seq") or by_text.get(item.get("description", "").strip())
        if not seq or seq in {o["seq"] for o in out}:
            while next_seq in used:
                next_seq += 1
            seq = next_seq
            used.add(seq)
        out.append({**item, "seq": seq})
    return out


def ledger_of(setup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """方案里的全部伏笔：总纲的长线伏笔 + 第一卷卷纲新埋的伏笔。"""
    outline, first = setup.get("outline") or {}, setup.get("first_volume") or {}
    merged: dict[int, dict[str, Any]] = {}
    for f in [*(outline.get("foreshadowings") or []), *(first.get("new_foreshadowings") or [])]:
        if f.get("seq") and f.get("description", "").strip():
            merged[f["seq"]] = f
    return [merged[k] for k in sorted(merged)]


async def save_setup(session: AsyncSession, book_id: uuid.UUID, setup: dict[str, dict[str, Any]]) -> None:
    """开书阶段保存整套方案（方案本身已包含作者的手动修改）。

    setup 含 concept / lore / spine / threads / outline / first_volume，格式与 AI 产出一致。
    """
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    concept, lore = setup.get("concept") or {}, setup.get("lore") or {}
    book.concept = concept
    book.spine = setup.get("spine") or {}
    book.title = concept.get("title") or book.title
    book.genre = concept.get("genre", "")

    # 人物：按姓名对齐
    old = {c.name: c for c in await _rows(session, Character, Character.book_id == book_id)}
    by_name: dict[str, Character] = {}
    for ch in lore.get("characters", []):
        name = (ch.get("name") or "").strip()
        if not name or name in by_name:
            continue
        row = old.pop(name, None) or Character(book_id=book_id, name=name)
        _assign(row, {**ch, "name": name}, CHARACTER_FIELDS)
        session.add(row)
        by_name[name] = row
    for row in old.values():
        await session.delete(row)

    # 世界观：按名称对齐
    old_world = {w.name: w for w in await _rows(session, WorldEntry, WorldEntry.book_id == book_id)}
    seen: set[str] = set()
    for w in lore.get("world_entries", []):
        name = (w.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        row = old_world.pop(name, None) or WorldEntry(book_id=book_id, name=name)
        row.category = w.get("category") or row.category or "其他"
        row.content = w.get("content", "")
        session.add(row)
    for row in old_world.values():
        await session.delete(row)
    await session.flush()

    # 人物关系只靠姓名定位，整体替换
    await session.execute(delete(Relationship).where(Relationship.book_id == book_id))
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

    # 线索：按名称对齐
    old_threads = {t.name: t for t in await _rows(session, StoryThread, StoryThread.book_id == book_id)}
    seen = set()
    for i, t in enumerate((setup.get("threads") or {}).get("threads", []), start=1):
        name = (t.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        row = old_threads.pop(name, None) or StoryThread(book_id=book_id, name=name)
        _assign(row, {**t, "name": name}, THREAD_FIELDS)
        row.index = i
        session.add(row)
    for row in old_threads.values():
        await session.delete(row)

    # 分卷卡片：按卷序号对齐，保留卷的 ID（剧情单元挂在卷下面）
    outline, first = setup.get("outline") or {}, setup.get("first_volume") or {}
    old_volumes = {v.index: v for v in await _rows(session, Volume, Volume.book_id == book_id)}
    units = first.get("units") or []
    first_volume: Volume | None = None
    seen_index: set[int] = set()
    for v in outline.get("volumes", []):
        index = v.get("index")
        if not index or index in seen_index:
            continue
        seen_index.add(index)
        row = old_volumes.pop(index, None) or Volume(book_id=book_id, index=index, title=v.get("title", ""))
        _assign(row, v, VOLUME_FIELDS)
        row.status = "detailed" if index == 1 and units else "planned"
        session.add(row)
        if index == 1:
            first_volume = row
    for row in old_volumes.values():
        await session.delete(row)
    await session.flush()

    # 第一卷的剧情单元：按单元序号对齐
    if first_volume is not None:
        old_units = {u.index: u for u in await _rows(session, PlotUnit, PlotUnit.volume_id == first_volume.id)}
        for u in units:
            index = u.get("index")
            if not index:
                continue
            row = old_units.pop(index, None) or PlotUnit(
                volume_id=first_volume.id, book_id=book_id, index=index, title=u.get("title", "")
            )
            _assign(row, u, UNIT_FIELDS)
            session.add(row)
        for row in old_units.values():
            await session.delete(row)

    # 伏笔台账：按编号对齐，保留状态与埋下、回收的章节
    old_fs = {f.seq: f for f in await _rows(session, Foreshadowing, Foreshadowing.book_id == book_id)}
    for f in ledger_of(setup):
        row = old_fs.pop(f["seq"], None) or Foreshadowing(book_id=book_id, seq=f["seq"], description="")
        _assign(row, f, FORESHADOW_FIELDS)
        session.add(row)
    for row in old_fs.values():
        await session.delete(row)
    await session.flush()


def thread_dict(t: StoryThread) -> dict[str, Any]:
    return {k: getattr(t, k) for k in THREAD_FIELDS}


def volume_dict(v: Volume) -> dict[str, Any]:
    return {"index": v.index, **{k: getattr(v, k) for k in VOLUME_FIELDS}}


def unit_dict(u: PlotUnit) -> dict[str, Any]:
    return {k: getattr(u, k) for k in UNIT_FIELDS}


def foreshadow_dict(f: Foreshadowing) -> dict[str, Any]:
    return {
        "seq": f.seq,
        **{k: getattr(f, k) for k in FORESHADOW_FIELDS},
        "status": f.status,
        "planted_chapter": f.planted_chapter,
        "resolved_chapter": f.resolved_chapter,
        "hint_chapters": list(f.hint_chapters or []),
    }


async def load_ledger(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _rows(session, Foreshadowing, Foreshadowing.book_id == book_id, order=Foreshadowing.seq)
    return [foreshadow_dict(f) for f in rows]


async def load_threads(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _rows(session, StoryThread, StoryThread.book_id == book_id, order=StoryThread.index)
    return [thread_dict(t) for t in rows]


async def load_setup(session: AsyncSession, book_id: uuid.UUID) -> dict[str, dict]:
    """从数据库读出当前方案（含作者的手动修改），格式与 AI 产出一致。"""
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    characters = await _rows(session, Character, Character.book_id == book_id, order=Character.created_at)
    names = {c.id: c.name for c in characters}
    world = await _rows(session, WorldEntry, WorldEntry.book_id == book_id, order=WorldEntry.created_at)
    relations = await _rows(session, Relationship, Relationship.book_id == book_id, order=Relationship.created_at)
    volumes = await _rows(session, Volume, Volume.book_id == book_id, order=Volume.index)
    first_units: list[dict] = []
    if volumes and volumes[0].index == 1:
        rows = await _rows(session, PlotUnit, PlotUnit.volume_id == volumes[0].id, order=PlotUnit.index)
        first_units = [unit_dict(u) for u in rows]
    ledger = await load_ledger(session, book_id)

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
    # 长线伏笔归总纲，短线、中线伏笔归第一卷卷纲
    return {
        "concept": dict(book.concept or {}),
        "lore": lore,
        "spine": dict(book.spine or {}),
        "threads": {"threads": await load_threads(session, book_id)},
        "outline": {
            "volumes": [volume_dict(v) for v in volumes],
            "foreshadowings": [f for f in ledger if f["span"] == "长"],
        },
        "first_volume": {
            "units": first_units,
            "new_foreshadowings": [f for f in ledger if f["span"] != "长"],
        },
    }


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
