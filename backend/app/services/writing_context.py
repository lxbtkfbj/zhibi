"""写作阶段的上下文工程：从数据库取出本次需要的那一小部分，整理成提示词里的各段文字。

原则：每次只给模型「这一步真正用得上的」——当前这一卷的卡片和前后几卷的线索节拍、分层的前情提要
（全书各卷回顾 → 本卷各单元回顾 → 最近几章摘要，总长有上限）、上一章的结尾、设定师为这一章备的资料、
本章要处理的伏笔（连同当初埋下那一章的原文片段），而不是把整本书塞进去。
"""

import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import (
    EXPECTATION_STATUS,
    FORESHADOW_STATUS,
    foreshadow_code,
    format_character,
    format_character_state,
    format_concept,
    format_ledger,
    format_requirements,
    format_reveals,
    format_spine,
    format_style,
    format_threads,
    format_unit,
    format_volume_card,
)
from app.agents.planning import ref_seq, relevant_ledger, unit_hint
from app.agents.playbook import pick, usage_text
from app.book_settings import settings_of
from app.models import Book, Chapter, Character, PlotUnit, Volume, WorldEntry
from app.services.requirements import list_requirements
from app.services.setup_store import load_ledger, load_nodes, load_threads, unit_dict, volume_dict

RECENT_CHAPTERS = 5
USED_CLIMAXES = 30
MAX_CHARACTERS = 40
PREVIOUS_TAIL = 800
# 分层前情提要每一层的总长上限（字）。超出时从最早的回顾开始压缩，再不够就略去最早的
VOLUME_RECAP_BUDGET = 3000
UNIT_RECAP_BUDGET = 2400
RECAP_FLOOR = 100
# 伏笔回收时摘给写手的原文片段长度
EXCERPT_CHARS = 300
# 设定师备资料时能看到的前文目录：最近多少章、每章摘要截多长；最多回顾几章
CATALOG_CHAPTERS = 60
CATALOG_SUMMARY = 60
MAX_RECALL = 5
CATALOG_CHARACTERS = 80
# 设定条目少于这个数时全部给写手，多了才挑
ALL_WORLD_UNDER = 12


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
    emotions = {-2: "憋屈压抑", -1: "偏压", 0: "平稳或悬着", 1: "偏扬", 2: "爆发爽快"}
    emotion, mood = outline.get("emotion"), outline.get("mood")
    if emotion in emotions:
        number = f"{emotion:+d}" if emotion else "0"
        lines.append(f"情绪：{number} {emotions[emotion]}" + (f"（{mood}）" if mood else ""))
    elif mood:
        lines.append(f"情绪：{mood}")
    lines.extend(format_reveals(outline.get("reveals") or []))
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


def fit_entries(entries: list[str], budget: int, floor: int = RECAP_FLOOR) -> list[str]:
    """按时间顺序排好的若干条回顾，总长超过 budget 时从最早的开始压缩到 floor 字；还超就略去最早的。

    最近的一条最要紧，不压缩；只剩它一条还超长时才截短。
    """
    out = list(entries)
    excess = sum(len(e) for e in out) - budget
    for i in range(len(out) - 1):
        if excess <= 0:
            break
        if len(out[i]) > floor:
            cut = min(excess, len(out[i]) - floor)
            out[i] = out[i][: len(out[i]) - cut - 1] + "…"
            excess -= cut
    dropped = 0
    while excess > 0 and len(out) > 1:
        excess -= len(out.pop(0))
        dropped += 1
    if excess > 0 and out:
        out[-1] = out[-1][: max(floor, len(out[-1]) - excess - 1)] + "…"
    if dropped:
        out.insert(0, f"（更早的 {dropped} 段从略）")
    return out


async def story_so_far(
    session: AsyncSession,
    book: Book,
    volume_index: int,
    *,
    before_chapter: int,
    unit_index: int | None = None,
    recent: int = RECENT_CHAPTERS,
) -> str:
    """分层的前情提要：前面各卷的卷回顾、本卷前面各单元的回顾、最近几章的摘要。

    还没写回顾的卷或单元（例如老数据）用卷纲里的概要或单元结果代替，并标明是计划。
    """
    parts = []
    volumes = (
        (
            await session.execute(
                select(Volume).where(Volume.book_id == book.id, Volume.index < volume_index).order_by(Volume.index)
            )
        )
        .scalars()
        .all()
    )
    if volumes:
        entries = [f"第{v.index}卷《{v.title}》：{v.recap.strip() or '（卷纲概要）' + v.summary}" for v in volumes]
        parts.append("◆ 前面各卷回顾\n" + "\n".join(fit_entries(entries, VOLUME_RECAP_BUDGET)))
    if unit_index:
        units = (
            (
                await session.execute(
                    select(PlotUnit)
                    .join(Volume, PlotUnit.volume_id == Volume.id)
                    .where(PlotUnit.book_id == book.id, Volume.index == volume_index, PlotUnit.index < unit_index)
                    .order_by(PlotUnit.index)
                )
            )
            .scalars()
            .all()
        )
        if units:
            entries = [f"单元{u.index}「{u.title}」：{u.recap.strip() or '（卷纲结果）' + u.outcome}" for u in units]
            parts.append("◆ 本卷前面各单元回顾\n" + "\n".join(fit_entries(entries, UNIT_RECAP_BUDGET)))
    parts.append("◆ 最近几章\n" + await recent_summaries(session, book.id, before_chapter, count=recent))
    return "\n\n".join(parts)


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


async def _world(session: AsyncSession, book_id: uuid.UUID) -> list[WorldEntry]:
    return list(
        (await session.execute(select(WorldEntry).where(WorldEntry.book_id == book_id).order_by(WorldEntry.created_at)))
        .scalars()
        .all()
    )


def world_text(rows: list[WorldEntry], mention: str, picked: list[str] | None = None) -> str:
    """相关设定：条目不多时全给；多了只给力量体系、规则，以及设定师挑的（没挑过就按名字出现在章纲里来找）。"""
    if len(rows) > ALL_WORLD_UNDER:
        wanted = set(picked or [])
        rows = [
            w for w in rows if w.category in ("力量体系", "规则") or (w.name in wanted if picked else w.name in mention)
        ]
    return "\n".join(f"- [{w.category}] {w.name}：{w.content}" for w in rows) or "（暂无）"


def ledger_for_refs(ledger: list[dict[str, Any]], refs: list[str], volume: int) -> list[dict[str, Any]]:
    seqs = {ref_seq(r) for r in refs}
    picked = [f for f in ledger if f["seq"] in seqs]
    for f in relevant_ledger(ledger, volume):
        if f["status"] == "planted" and f not in picked:
            picked.append(f)
    return picked


async def requirements_of(book: Book, session: AsyncSession) -> str:
    rows = await list_requirements(session, book.id)
    return format_requirements([row.text for row in rows], [], settings_of(book))


# ---------- 伏笔回收：摘出当初埋下那一章的原文 ----------

SENTENCE = re.compile(r"[^。！？!?…\n]+[。！？!?…」”』）)]*")
NOT_TEXT = re.compile(r"[^\w]")


def _bigrams(text: str) -> set[str]:
    clean = NOT_TEXT.sub("", text)
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def best_excerpt(text: str, query: str, limit: int = EXCERPT_CHARS) -> str:
    """从一章正文里找出和 query（伏笔描述）最相关的句子，向前后扩到 limit 字左右。找不到相关的返回空。"""
    grams = _bigrams(query)
    sentences = [s.strip() for s in SENTENCE.findall(text or "") if s.strip()]
    if not grams or not sentences:
        return ""
    scores = [len(_bigrams(s) & grams) for s in sentences]
    best = max(range(len(sentences)), key=lambda i: scores[i])
    if scores[best] < 2:
        return ""
    lo = hi = best
    size = len(sentences[best])
    while True:
        grew = False
        for j in (hi + 1, lo - 1):
            if 0 <= j < len(sentences) and not lo <= j <= hi and size + len(sentences[j]) <= limit:
                size += len(sentences[j])
                lo, hi = min(lo, j), max(hi, j)
                grew = True
        if not grew:
            break
    excerpt = "".join(sentences[lo : hi + 1])
    return excerpt if len(excerpt) <= limit else excerpt[:limit] + "…"


async def foreshadow_tasks(
    session: AsyncSession, book_id: uuid.UUID, ledger: list[dict[str, Any]], actions: list[dict[str, Any]], before: int
) -> str:
    """本章要处理的伏笔：台账里的描述和计划；提醒、回收时附上当初埋下（和最近一次提醒）那一章的原文片段。"""
    by_seq = {f["seq"]: f for f in ledger}
    lines = []
    for a in actions:
        f = by_seq.get(ref_seq(a.get("ref", "")) or -1)
        if f is None:
            continue
        action, detail = a.get("action", ""), (a.get("detail") or "").strip()
        expectation = f.get("kind") == "期待"
        status = (EXPECTATION_STATUS if expectation else FORESHADOW_STATUS).get(f.get("status", "planned"), "")
        action_label = {"埋下": "立下", "回收": "兑现"}.get(action, action) if expectation else action
        lines.append(
            f"- {action_label}{foreshadow_code(f)}［{status}］{f.get('description', '')}"
            + (f"（这一章：{detail}）" if detail else "")
        )
        if action == "埋下":
            if f.get("plant_plan"):
                lines.append(f"  埋法：{f['plant_plan']}")
            continue
        sources = [("埋下", f.get("planted_chapter"))]
        if action == "回收" and f.get("hint_chapters"):
            sources.append(("提醒", f["hint_chapters"][-1]))
        found = False
        for label, index in sources:
            if not index or index >= before or (label == "提醒" and index == f.get("planted_chapter")):
                continue
            row = (
                await session.execute(
                    select(Chapter.title, Chapter.content).where(Chapter.book_id == book_id, Chapter.index == index)
                )
            ).first()
            if row is None:
                continue
            excerpt = best_excerpt(row.content, " ".join([f.get("description", ""), detail, f.get("plant_plan", "")]))
            if excerpt:
                lines.append(f"  第{index}章《{row.title}》（{label}）原文：「{excerpt}」")
                found = True
            else:
                lines.append(f"  第{index}章《{row.title}》{label}了这条伏笔（没找到明显相关的段落，按描述自然带出）")
                found = True
        if not found:
            lines.append("  台账里还没记下埋在哪一章，按描述自然带出。")
        if action == "回收" and f.get("payoff_plan"):
            lines.append(f"  回收方式：{f['payoff_plan']}")
    if not lines:
        return ""
    return (
        "【本章要处理的伏笔】\n"
        + "\n".join(lines)
        + "\n提醒、回收伏笔时，要写出能让读者想起当初那一幕的细节（可以化用上面的原文，不要整段照抄）。"
    )


# ---------- 设定师备资料 ----------


async def material_blocks(session: AsyncSession, book: Book, chapter: Chapter) -> dict[str, str]:
    """设定师备资料时看的东西：章纲、所在单元、分层前情、人物名单、设定目录、前文目录、相关伏笔。"""
    unit = await session.get(PlotUnit, chapter.unit_id) if chapter.unit_id else None
    volume = await session.get(Volume, chapter.volume_id) if chapter.volume_id else None
    outline = chapter.outline or {}
    characters = await _characters(session, book.id)
    roster = sorted(characters, key=lambda c: c.role_type == "龙套")[:CATALOG_CHARACTERS]
    world = await _world(session, book.id)
    ledger = await load_ledger(session, book.id)
    refs = [a.get("ref", "") for a in outline.get("foreshadow_actions") or []]
    related = ledger_for_refs(ledger, refs, volume.index if volume else 1)
    linked = {c for f in related for c in [f.get("planted_chapter"), *(f.get("hint_chapters") or [])] if c}
    rows = (
        await session.execute(
            select(Chapter.index, Chapter.title, Chapter.summary)
            .where(Chapter.book_id == book.id, Chapter.status == "final", Chapter.index < chapter.index)
            .order_by(Chapter.index.desc())
        )
    ).all()
    catalog = [r for i, r in enumerate(rows) if i < CATALOG_CHAPTERS or r.index in linked]
    return {
        "chapter_index": str(chapter.index),
        "chapter_title": chapter.title,
        "outline": format_chapter_outline(outline),
        "unit": format_unit(unit_dict(unit)) if unit else "（暂无）",
        "story_so_far": await story_so_far(
            session,
            book,
            volume.index if volume else 1,
            before_chapter=chapter.index,
            unit_index=unit.index if unit else None,
            recent=3,
        ),
        "roster": "\n".join(format_character_state(_char_dict(c)) for c in roster) or "（暂无）",
        "world_catalog": "\n".join(f"- [{w.category}] {w.name}：{w.content[:40]}" for w in world) or "（暂无）",
        "chapter_catalog": "\n".join(
            f"第{r.index}章《{r.title}》：{r.summary[:CATALOG_SUMMARY]}" for r in reversed(catalog)
        )
        or "（还没有前文）",
        "ledger": format_ledger(related),
    }


def clean_materials(
    materials: dict[str, Any], characters: list[Character], world: list[WorldEntry], before: int
) -> dict:
    """只保留设定库里真有的人物、条目和已经写过的章节。"""
    names = {c.name for c in characters} | {a for c in characters for a in c.aliases or []}
    entries = {w.name for w in world}
    return {
        "characters": list(dict.fromkeys(n.strip() for n in materials.get("characters", []) if n.strip() in names)),
        "world": list(dict.fromkeys(n.strip() for n in materials.get("world", []) if n.strip() in entries)),
        "chapters": sorted({int(i) for i in materials.get("chapters", []) if 0 < int(i) < before})[-MAX_RECALL:],
        "notes": [n.strip() for n in materials.get("notes", []) if n.strip()][:MAX_RECALL],
    }


async def pick_materials(session: AsyncSession, book_id: uuid.UUID, before: int, raw: dict[str, Any]) -> dict:
    return clean_materials(raw, await _characters(session, book_id), await _world(session, book_id), before)


async def _recall(session: AsyncSession, book_id: uuid.UUID, indexes: list[int]) -> str:
    if not indexes:
        return ""
    rows = (
        await session.execute(
            select(Chapter.index, Chapter.title, Chapter.summary)
            .where(Chapter.book_id == book_id, Chapter.index.in_(indexes), Chapter.status == "final")
            .order_by(Chapter.index)
        )
    ).all()
    if not rows:
        return ""
    return "【设定师挑出的相关前文】\n" + "\n".join(f"第{r.index}章《{r.title}》：{r.summary}" for r in rows)


def _notes(notes: list[str]) -> str:
    return "【设定师的提醒】\n" + "\n".join(f"- {n}" for n in notes) if notes else ""


# ---------- 各环节的上下文 ----------


async def prior_units(session: AsyncSession, book_id: uuid.UUID, before_volume: int) -> list[dict[str, Any]]:
    """前面各卷的剧情单元（按卷、单元顺序），统计套路、检查重复用。"""
    rows = (
        await session.execute(
            select(Volume.index, PlotUnit)
            .join(Volume, PlotUnit.volume_id == Volume.id)
            .where(PlotUnit.book_id == book_id, Volume.index < before_volume)
            .order_by(Volume.index, PlotUnit.index)
        )
    ).all()
    return [{"volume": v, **unit_dict(u)} for v, u in rows]


def used_climaxes(prior: list[dict[str, Any]]) -> str:
    lines = []
    for u in prior[-USED_CLIMAXES:]:
        how = f"（破局：{u['resolution']}）" if u.get("resolution") else ""
        lines.append(f"- 第{u['volume']}卷单元{u['index']}「{u['title']}」：{u['climax']}{how}")
    return "\n".join(lines) or "（暂无）"


async def volume_blocks(session: AsyncSession, book: Book, volume: Volume) -> dict[str, str]:
    """拆某一卷的卷纲时需要的上下文。"""
    nodes = await load_nodes(session, book.id)
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
        neighbors.append(f"上一卷：{format_volume_card(volume_dict(prev, nodes))}\n各单元结果：\n{recap}")
    else:
        neighbors.append("上一卷：无（这是第一卷）")
    neighbors.append(
        "下一卷：" + (format_volume_card(volume_dict(following, nodes)) if following else "无（这是最后一卷）")
    )
    first_chapter = (
        await session.scalar(select(func.coalesce(func.max(Chapter.index), 0)).where(Chapter.book_id == book.id))
    ) + 1
    ledger = await load_ledger(session, book.id)
    characters = await _characters(session, book.id)
    prior = await prior_units(session, book.id, volume.index)
    playbook = pick(book.concept, settings_of(book)["playbook"])
    return {
        "volume_index": str(volume.index),
        "concept": format_concept({**(book.concept or {}), "chapter_words": chapter_words(book)}),
        "spine": format_spine({**(book.spine or {}), "nodes": nodes}),
        "threads": format_threads(await load_threads(session, book.id), volume=volume.index),
        "volume": format_volume_card(volume_dict(volume, nodes)),
        "neighbors": "\n\n".join(neighbors),
        "story_so_far": await story_so_far(session, book, volume.index, before_chapter=first_chapter),
        "used_climaxes": used_climaxes(prior),
        "trope_usage": usage_text(playbook, prior),
        "playbook": playbook.text("volume"),
        "characters": character_states(characters),
        "ledger": format_ledger(relevant_ledger(ledger, volume.index)),
        "requirements": await requirements_of(book, session),
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
        "concept": format_concept({**(book.concept or {}), "chapter_words": chapter_words(book)}),
        "volume": format_volume_card(volume_dict(volume, await load_nodes(session, book.id))),
        "unit": format_unit(unit_dict(unit)),
        "neighbors": "\n".join(neighbors),
        "story_so_far": await story_so_far(
            session, book, volume.index, before_chapter=first_chapter, unit_index=unit.index
        ),
        "characters": character_states(await _characters(session, book.id)),
        "ledger": format_ledger(ledger_for_refs(ledger, refs, volume.index)),
        # 套路库只带本单元用到的套路，省篇幅
        "playbook": pick(book.concept, settings_of(book)["playbook"]).text("chapters", tropes=list(unit.tropes or [])),
        "requirements": await requirements_of(book, session),
    }


async def chapter_blocks(session: AsyncSession, book: Book, chapter: Chapter) -> dict[str, str]:
    """写一章、审一章、提取设定变化时需要的上下文（各提示词只取自己用得上的部分）。

    设定师备过资料的，人物、设定条目、要回顾的前文都按设定师挑的来（章纲里点名的人物和主角总会带上）。
    """
    unit = await session.get(PlotUnit, chapter.unit_id) if chapter.unit_id else None
    volume = await session.get(Volume, chapter.volume_id) if chapter.volume_id else None
    volume_index = volume.index if volume else 1
    outline = chapter.outline or {}
    materials = chapter.materials or {}
    previous = (
        await session.execute(
            select(Chapter.content).where(Chapter.book_id == book.id, Chapter.index == chapter.index - 1)
        )
    ).scalar()
    characters = await _characters(session, book.id)
    names = list(dict.fromkeys([*(outline.get("characters") or []), *materials.get("characters", [])]))
    mention = " ".join([str(outline), unit.title if unit else ""])
    ledger = await load_ledger(session, book.id)
    actions = outline.get("foreshadow_actions") or []
    refs = [a.get("ref", "") for a in actions]
    return {
        "chapter_index": str(chapter.index),
        "chapter_title": chapter.title,
        "concept": format_concept({**(book.concept or {}), "chapter_words": chapter_words(book)}),
        "outline": format_chapter_outline(outline),
        "unit": format_unit(unit_dict(unit)) if unit else "（暂无）",
        "characters": character_profiles(characters, names),
        "world": world_text(await _world(session, book.id), mention, materials.get("world") if materials else None),
        "recent": await recent_summaries(session, book.id, chapter.index, count=3),
        "story_so_far": await story_so_far(
            session,
            book,
            volume_index,
            before_chapter=chapter.index,
            unit_index=unit.index if unit else None,
            recent=3,
        ),
        "recall": await _recall(session, book.id, list(materials.get("chapters") or [])),
        "notes": _notes(list(materials.get("notes") or [])),
        "foreshadow_tasks": await foreshadow_tasks(session, book.id, ledger, actions, chapter.index),
        "previous_tail": (previous or "")[-PREVIOUS_TAIL:].strip() or "（这是第一章）",
        "style": format_style(book.style_reference or ""),
        "requirements": await requirements_of(book, session),
        "chapter_words": str(chapter_words(book)),
        "ledger": format_ledger(ledger_for_refs(ledger, refs, volume_index)),
        "content": chapter.content,
    }


def chapter_words(book: Book) -> int:
    return int(settings_of(book)["chapter_words"] or (book.concept or {}).get("chapter_words") or 3000)


# ---------- 回顾 ----------


async def unit_recap_blocks(session: AsyncSession, book: Book, unit: PlotUnit) -> dict[str, str]:
    volume = await session.get(Volume, unit.volume_id)
    rows = (
        await session.execute(
            select(Chapter.index, Chapter.title, Chapter.summary)
            .where(Chapter.unit_id == unit.id, Chapter.status == "final")
            .order_by(Chapter.index)
        )
    ).all()
    ledger = await load_ledger(session, book.id)
    refs = [a.get("ref", "") for a in unit.foreshadow_actions or []]
    return {
        "volume_index": str(volume.index),
        "unit_index": str(unit.index),
        "unit_title": unit.title,
        "unit": format_unit(unit_dict(unit)),
        "chapters": "\n".join(f"第{r.index}章《{r.title}》：{r.summary}" for r in rows) or "（暂无）",
        "characters": character_states(await _characters(session, book.id)),
        "ledger": format_ledger(ledger_for_refs(ledger, refs, volume.index)),
    }


async def volume_recap_blocks(session: AsyncSession, book: Book, volume: Volume) -> dict[str, str]:
    units = (
        (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index)))
        .scalars()
        .all()
    )
    entries = []
    for u in units:
        recap = u.recap.strip()
        if not recap:
            # 没有单元回顾（老数据）：用这一单元各章的摘要
            rows = (
                await session.execute(
                    select(Chapter.summary)
                    .where(Chapter.unit_id == u.id, Chapter.status == "final")
                    .order_by(Chapter.index)
                )
            ).scalars()
            recap = " ".join(rows) or u.outcome
        entries.append(f"单元{u.index}「{u.title}」：{recap}")
    ledger = await load_ledger(session, book.id)
    return {
        "volume_index": str(volume.index),
        "volume_title": volume.title,
        "volume": format_volume_card(volume_dict(volume, await load_nodes(session, book.id))),
        "units": "\n\n".join(fit_entries(entries, UNIT_RECAP_BUDGET * 3)) or "（暂无）",
        "characters": character_states(await _characters(session, book.id)),
        "ledger": format_ledger(relevant_ledger(ledger, volume.index)),
    }
