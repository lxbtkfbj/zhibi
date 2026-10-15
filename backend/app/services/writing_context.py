"""写作阶段的上下文工程：从数据库取出本次需要的那一小部分，整理成提示词里的各段文字。

原则：每次只给模型「这一步真正用得上的」——当前这一卷的卡片和前后几卷的线索节拍、最近几章的摘要、
上一章的结尾、出场人物的当前状态、与本段相关的伏笔，而不是把整本书塞进去。
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import (
    format_character,
    format_character_state,
    format_concept,
    format_ledger,
    format_requirements,
    format_spine,
    format_style,
    format_threads,
    format_unit,
    format_volume_card,
)
from app.agents.planning import ref_seq, relevant_ledger, unit_hint
from app.models import Book, Chapter, Character, PlotUnit, Volume, WorldEntry
from app.services.setup_store import load_ledger, load_threads, unit_dict, volume_dict

RECENT_CHAPTERS = 5
USED_CLIMAXES = 30
MAX_CHARACTERS = 40
PREVIOUS_TAIL = 800


def format_chapter_outline(outline: dict[str, Any]) -> str:
    if not outline:
        return "（暂无）"
    lines = [f"目标：{outline.get('goal', '')}"]
    scenes = outline.get("scenes") or []
    if scenes:
        lines.append("场景：\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(scenes, start=1)))
    for label, key in (("冲突", "conflict"), ("爽点", "cool_point"), ("结尾钩子", "hook")):
        if outline.get(key):
            lines.append(f"{label}：{outline[key]}")
    if outline.get("characters"):
        lines.append(f"出场人物：{'、'.join(outline['characters'])}")
    actions = outline.get("foreshadow_actions") or []
    if actions:
        lines.append(
            "伏笔：" + "；".join(f"{a.get('action')}{a.get('ref')} {a.get('detail', '')}".strip() for a in actions)
        )
    return "\n".join(lines)


async def recent_summaries(session: AsyncSession, book_id: uuid.UUID, before: int, count: int = RECENT_CHAPTERS) -> str:
    rows = (
        await session.execute(
            select(Chapter.index, Chapter.title, Chapter.summary)
            .where(Chapter.book_id == book_id, Chapter.status == "final", Chapter.index < before)
            .order_by(Chapter.index.desc())
            .limit(count)
        )
    ).all()
    if not rows:
        return "（这是全书第一章，还没有前情）" if before <= 1 else "（暂无）"
    return "\n".join(f"第{r.index}章《{r.title}》：{r.summary}" for r in reversed(rows))


async def _characters(session: AsyncSession, book_id: uuid.UUID) -> list[Character]:
    return list(
        (await session.execute(select(Character).where(Character.book_id == book_id).order_by(Character.created_at)))
        .scalars()
        .all()
    )


def _char_dict(c: Character) -> dict[str, Any]:
    return {
        k: getattr(c, k)
        for k in (
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
            "is_alive",
        )
    }


def character_states(characters: list[Character]) -> str:
    major = [c for c in characters if c.role_type != "龙套"][:MAX_CHARACTERS]
    return "\n".join(format_character_state(_char_dict(c)) for c in major) or "（暂无）"


def character_profiles(characters: list[Character], names: list[str]) -> str:
    """出场人物的完整资料；主角总是带上。"""
    wanted = set(names)
    picked = [c for c in characters if c.name in wanted or c.role_type == "主角"]
    # 章纲里写的是别名或称呼时也尽量带上
    for c in characters:
        if c not in picked and any(alias in wanted for alias in c.aliases or []):
            picked.append(c)
    return "\n\n".join(format_character(_char_dict(c)) for c in picked) or "（暂无）"


async def world_text(session: AsyncSession, book_id: uuid.UUID, mention: str) -> str:
    rows = list(
        (await session.execute(select(WorldEntry).where(WorldEntry.book_id == book_id).order_by(WorldEntry.created_at)))
        .scalars()
        .all()
    )
    if len(rows) > 12:
        rows = [w for w in rows if w.category in ("力量体系", "规则") or w.name in mention]
    return "\n".join(f"- [{w.category}] {w.name}：{w.content}" for w in rows) or "（暂无）"


def ledger_for_refs(ledger: list[dict[str, Any]], refs: list[str], volume: int) -> list[dict[str, Any]]:
    seqs = {ref_seq(r) for r in refs}
    picked = [f for f in ledger if f["seq"] in seqs]
    for f in relevant_ledger(ledger, volume):
        if f["status"] == "planted" and f not in picked:
            picked.append(f)
    return picked


def requirements_of(book: Book) -> str:
    return format_requirements(list(book.requirements or []), [])


async def used_climaxes(session: AsyncSession, book_id: uuid.UUID, before_volume: int) -> str:
    rows = (
        await session.execute(
            select(Volume.index, PlotUnit.index, PlotUnit.title, PlotUnit.climax)
            .join(Volume, PlotUnit.volume_id == Volume.id)
            .where(PlotUnit.book_id == book_id, Volume.index < before_volume)
            .order_by(Volume.index, PlotUnit.index)
        )
    ).all()
    rows = rows[-USED_CLIMAXES:]
    return "\n".join(f"- 第{v}卷单元{u}「{t}」：{c}" for v, u, t, c in rows) or "（暂无）"


async def volume_blocks(session: AsyncSession, book: Book, volume: Volume) -> dict[str, str]:
    """拆某一卷的卷纲时需要的上下文。"""
    volumes = list(
        (await session.execute(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index))).scalars().all()
    )
    prev = next((v for v in volumes if v.index == volume.index - 1), None)
    following = next((v for v in volumes if v.index == volume.index + 1), None)
    neighbors = []
    if prev is not None:
        units = list(
            (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == prev.id).order_by(PlotUnit.index)))
            .scalars()
            .all()
        )
        recap = "\n".join(f"  单元{u.index}「{u.title}」：{u.outcome}" for u in units)
        neighbors.append(f"上一卷：{format_volume_card(volume_dict(prev))}\n各单元结果：\n{recap}")
    else:
        neighbors.append("上一卷：无（这是第一卷）")
    neighbors.append("下一卷：" + (format_volume_card(volume_dict(following)) if following else "无（这是最后一卷）"))
    first_chapter = (
        await session.scalar(select(func.coalesce(func.max(Chapter.index), 0)).where(Chapter.book_id == book.id))
    ) + 1
    ledger = await load_ledger(session, book.id)
    characters = await _characters(session, book.id)
    return {
        "volume_index": str(volume.index),
        "concept": format_concept(book.concept or {}),
        "spine": format_spine(book.spine or {}),
        "threads": format_threads(await load_threads(session, book.id), volume=volume.index),
        "volume": format_volume_card(volume_dict(volume)),
        "neighbors": "\n\n".join(neighbors),
        "story_so_far": await recent_summaries(session, book.id, first_chapter, count=8),
        "used_climaxes": await used_climaxes(session, book.id, volume.index),
        "characters": character_states(characters),
        "ledger": format_ledger(relevant_ledger(ledger, volume.index)),
        "requirements": requirements_of(book),
        "unit_hint": unit_hint(volume.chapter_count),
        "chapter_count": str(volume.chapter_count or "若干"),
    }


async def chapter_plan_blocks(
    session: AsyncSession, book: Book, volume: Volume, unit: PlotUnit, first_chapter: int
) -> dict[str, str]:
    """给一个剧情单元出章纲时需要的上下文。"""
    units = list(
        (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index)))
        .scalars()
        .all()
    )
    prev = next((u for u in units if u.index == unit.index - 1), None)
    following = next((u for u in units if u.index == unit.index + 1), None)
    neighbors = [
        f"上一个单元：「{prev.title}」{prev.outcome}" if prev else "上一个单元：无（本卷第一个单元）",
        f"下一个单元：「{following.title}」{following.goal}" if following else "下一个单元：无（本卷最后一个单元）",
    ]
    ledger = await load_ledger(session, book.id)
    refs = [a.get("ref", "") for a in unit.foreshadow_actions or []]
    count = max(1, unit.chapter_count)
    return {
        "volume_index": str(volume.index),
        "unit_index": str(unit.index),
        "chapter_count": str(count),
        "first_chapter": str(first_chapter),
        "last_chapter": str(first_chapter + count - 1),
        "concept": format_concept(book.concept or {}),
        "volume": format_volume_card(volume_dict(volume)),
        "unit": format_unit(unit_dict(unit)),
        "neighbors": "\n".join(neighbors),
        "recent": await recent_summaries(session, book.id, first_chapter),
        "characters": character_states(await _characters(session, book.id)),
        "ledger": format_ledger(ledger_for_refs(ledger, refs, volume.index)),
        "requirements": requirements_of(book),
    }


async def chapter_blocks(session: AsyncSession, book: Book, chapter: Chapter) -> dict[str, str]:
    """写一章、审一章、提取设定变化时需要的上下文（各提示词只取自己用得上的部分）。"""
    unit = await session.get(PlotUnit, chapter.unit_id) if chapter.unit_id else None
    volume = await session.get(Volume, chapter.volume_id) if chapter.volume_id else None
    outline = chapter.outline or {}
    previous = (
        await session.execute(
            select(Chapter.content).where(Chapter.book_id == book.id, Chapter.index == chapter.index - 1)
        )
    ).scalar()
    characters = await _characters(session, book.id)
    names = list(outline.get("characters") or [])
    mention = " ".join([str(outline), unit.title if unit else ""])
    ledger = await load_ledger(session, book.id)
    refs = [a.get("ref", "") for a in outline.get("foreshadow_actions") or []]
    return {
        "chapter_index": str(chapter.index),
        "chapter_title": chapter.title,
        "concept": format_concept(book.concept or {}),
        "outline": format_chapter_outline(outline),
        "unit": format_unit(unit_dict(unit)) if unit else "（暂无）",
        "characters": character_profiles(characters, names),
        "world": await world_text(session, book.id, mention),
        "recent": await recent_summaries(session, book.id, chapter.index, count=3),
        "previous_tail": (previous or "")[-PREVIOUS_TAIL:].strip() or "（这是第一章）",
        "style": format_style(book.style_reference or ""),
        "requirements": requirements_of(book),
        "chapter_words": str((book.concept or {}).get("chapter_words") or 3000),
        "ledger": format_ledger(ledger_for_refs(ledger, refs, volume.index if volume else 1)),
        "content": chapter.content,
    }
