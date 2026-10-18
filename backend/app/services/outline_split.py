"""编辑部帮拆：单元出章纲、卷拆成单元。先出一版给作者看（不存），作者改过、删过以后收下才存，收下了也能撤销。

出章纲和写书流程里「写到没章纲的单元先出章纲」是同一份提示词和同一套检查；拆卷和「提前展开」是同一份卷纲提示词。
单元里已经写好的章不动，只换还没写的；已经有单元的卷不整个重拆。
"""

import asyncio
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import editorial
from app.agents.context import format_revision
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts
from app.agents.playbook import pick
from app.agents.setup_puzzle import clean_reveals
from app.api.deps import ensure_idle
from app.book_settings import settings_of
from app.db import get_sessionmaker
from app.llm.router import LLMRouter
from app.models import Book, Chapter, Foreshadowing, PlotUnit, Volume
from app.services import outline_structure, setup_store, writing_store
from app.services.library import lock_book
from app.services.versions import record_version, snapshot_of
from app.services.writing_context import chapter_plan_blocks, format_chapter_outline, volume_blocks

# 出一版最多等多久：章纲要过一遍检查，不对还会重出一次；拆一卷真模型要四分钟上下
SPLIT_TIMEOUT = 480
CHAPTER_KEYS = ("发生什么", "看点", "结尾钩子")


def make_llm(book_id: uuid.UUID) -> LLMRouter:
    """调模型用的：真模型试用脚本会换掉它。"""
    return LLMRouter(get_sessionmaker(), book_id=book_id)


def chapter_view(plan: dict[str, Any]) -> dict[str, str]:
    """新书页上一章章纲的三栏：发生什么（第一行是这一章要做成什么，下面每行一个场景）、看点、结尾钩子。"""
    happen = "\n".join(
        x for x in [str(plan.get("goal") or "").strip(), *(str(s).strip() for s in plan.get("scenes") or [])] if x
    )
    return {
        "发生什么": happen,
        "看点": str(plan.get("cool_point") or "").strip(),
        "结尾钩子": str(plan.get("hook") or "").strip(),
    }


def chapter_plan_from(draft: dict[str, Any]) -> dict[str, Any]:
    """作者在草稿上改过的名字和三栏，写回模型给的那一章（别的字段原样留着）。"""
    plan = dict(draft.get("raw") or {})
    plan["title"] = str(draft.get("name") or plan.get("title") or "").strip()[:200]
    sections = draft.get("sections") or {}
    if "发生什么" in sections:
        lines = [line.strip() for line in str(sections["发生什么"]).split("\n") if line.strip()]
        plan["goal"] = lines[0] if lines else ""
        plan["scenes"] = lines[1:]
    if "看点" in sections:
        plan["cool_point"] = str(sections["看点"]).strip()
    if "结尾钩子" in sections:
        plan["hook"] = str(sections["结尾钩子"]).strip()
    return plan


async def _unit(session: AsyncSession, book: Book, target_id: str) -> tuple[PlotUnit, Volume]:
    try:
        unit = await session.get(PlotUnit, uuid.UUID(target_id))
    except ValueError as exc:
        raise HTTPException(404, "这个单元不存在") from exc
    if unit is None or unit.book_id != book.id:
        raise HTTPException(404, "这个单元不存在")
    volume = await session.get(Volume, unit.volume_id)
    return unit, volume


async def _volume(session: AsyncSession, book: Book, target_id: str) -> Volume:
    try:
        volume = await session.get(Volume, uuid.UUID(target_id))
    except ValueError as exc:
        raise HTTPException(404, "这一卷不存在") from exc
    if volume is None or volume.book_id != book.id:
        raise HTTPException(404, "这一卷不存在")
    return volume


def _label(chapter: Chapter) -> str:
    return f"第{chapter.index}章　{chapter.title}"


# ---------- 出一版 ----------


async def draft_split(
    session: AsyncSession, book: Book, target_type: str, target_id: str, request: str, current: list[dict] | None
) -> dict[str, Any]:
    await ensure_idle(session, book.id)
    work = _draft_unit if target_type == "unit" else _draft_volume
    try:
        return await asyncio.wait_for(work(session, book, target_id, request.strip(), current), timeout=SPLIT_TIMEOUT)
    except TimeoutError as exc:
        raise HTTPException(504, "这次编辑部太慢了，八分钟还没出好，大纲没动。再试一次") from exc


async def _draft_unit(
    session: AsyncSession, book: Book, target_id: str, request: str, current: list[dict] | None
) -> dict:
    unit, volume = await _unit(session, book, target_id)
    if unit.locked:
        raise HTTPException(409, "这个单元锁住了，AI 不改，先解锁")
    chapters = list(await session.scalars(select(Chapter).where(Chapter.unit_id == unit.id).order_by(Chapter.index)))
    written = [c for c in chapters if outline_structure.started(c)]
    planned = [c for c in chapters if not outline_structure.started(c)]
    if written and planned and planned[0].index < written[-1].index:
        raise HTTPException(409, "这个单元写到一半，中间还夹着没写的章，先在旧版处理")
    if unit.status == "done" or (written and not planned and unit.chapter_count and len(written) >= unit.chapter_count):
        raise HTTPException(409, "这个单元已经写完了，不用再出章纲")
    if planned:
        first = planned[0].index
    elif written:
        first = written[-1].index + 1
    else:
        first = await writing_store.unit_next_chapter_index(session, book.id, unit)
    # 章数定了：照剩下的章数出；没定、或者写的已经超过定的：编辑部按剧情定
    fixed = unit.chapter_count - len(written) if unit.chapter_count > len(written) else 0
    blocks = await chapter_plan_blocks(session, book, volume, unit, first, chapter_count=fixed)
    if current:
        shown = "\n\n".join(
            f"第 {first + i} 章《{d.get('name', '')}》\n{format_chapter_outline(chapter_plan_from(d))}"
            for i, d in enumerate(current)
        )
        blocks["revision"] = format_revision(
            "当前章纲", shown, request or "换个排法：和当前这一版要有实质的不同，关键事件照旧落地。"
        )
    elif request:
        blocks["revision"] = f"【作者对这个单元的要求】\n{request}\n\n照这个要求出章纲。"
    else:
        blocks["revision"] = ""
    from app.graphs.write_book import _chapter_plan_issues  # 写书流程里同一套章纲检查

    key = pick(book.concept, settings_of(book)["playbook"]).key
    history = list(
        await session.scalars(
            select(Chapter)
            .where(Chapter.book_id == book.id, Chapter.index < first)
            .order_by(Chapter.index.desc())
            .limit(5)
        )
    )
    prior = [{**(c.outline or {}), "index": c.index} for c in reversed(history)]
    ledger = await setup_store.load_ledger(session, book.id)
    secrets = await setup_store.load_secrets(session, book.id)
    keeps = [_label(c) for c in written]
    replaces = [_label(c) for c in planned]
    book_id = book.id
    # 调模型时不占着数据库
    await session.rollback()
    llm = make_llm(book_id)
    try:
        for attempt in range(2):
            result = await editorial.plan_chapters(llm, blocks)
            plans = [c.model_dump() for c in result.chapters if c.title.strip() or c.goal.strip()]
            issues = _chapter_plan_issues(plans, first, key, prior, ledger, secrets)
            if fixed and len(plans) != fixed:
                issues.insert(0, f"这一单元需要出 {fixed} 章章纲，现在是 {len(plans)} 章；必须照作者已定的章数重出。")
            elif not fixed and not 1 <= len(plans) <= 30:
                issues.insert(0, f"这一单元出了 {len(plans)} 章章纲；章数按剧情定，一般 5 到 15 章。")
            if not issues or attempt:
                break
            blocks["revision"] = format_revision(
                "当前章纲",
                "\n\n".join(f"第 {first + i} 章\n{format_chapter_outline(plan)}" for i, plan in enumerate(plans)),
                "\n".join(f"- {issue}" for issue in issues),
            )
    finally:
        await llm.aclose()
    if not plans:
        raise HTTPException(502, "主编没出来章纲，大纲没动。再试一次")
    return {
        "drafts": [{"name": p.get("title", ""), "sections": chapter_view(p), "raw": p} for p in plans],
        "note": result.remark,
        "first": first,
        "keeps": keeps,
        "replaces": replaces,
    }


async def _draft_volume(
    session: AsyncSession, book: Book, target_id: str, request: str, current: list[dict] | None
) -> dict:
    volume = await _volume(session, book, target_id)
    if volume.locked:
        raise HTTPException(409, "这一卷锁住了，AI 不改，先解锁")
    if await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == volume.id).limit(1)):
        raise HTTPException(409, "这一卷已经有单元了，不整个重拆；想改哪个单元，去那个单元里改")
    blocks = await volume_blocks(session, book, volume)
    if request and not current:
        blocks["direction"] = f"【作者对这一卷的要求】\n{request}\n照这个要求拆。"
    count = volume.chapter_count
    book_id = book.id
    await session.rollback()
    llm = make_llm(book_id)
    try:
        previous = {"units": [_unit_plan_from(d, i) for i, d in enumerate(current or [], 1)]} if current else {}
        result = await editorial.plan_volume(
            llm, blocks, previous, request or "换个拆法：和当前这一版要有实质的不同。", purpose="大纲·帮拆单元"
        )
    finally:
        await llm.aclose()
    plan = result.model_dump()
    units = plan.get("units") or []
    if count > 0:
        units = fit_chapter_counts(units[:count], count, minimum=1)
    if not units:
        raise HTTPException(502, "主编没拆出单元，大纲没动。再试一次")
    plan["units"] = units
    return {
        "drafts": [
            {"name": u.get("title", ""), "text": u.get("summary", ""), "chapters": u.get("chapter_count", 0), "raw": u}
            for u in units
        ],
        "note": plan.get("remark", ""),
        "keeps": [],
        "replaces": [],
        "plan": {key: value for key, value in plan.items() if key != "units"},
    }


def _unit_plan_from(draft: dict[str, Any], index: int) -> dict[str, Any]:
    unit = dict(draft.get("raw") or {})
    unit["index"] = index
    unit["title"] = str(draft.get("name") or unit.get("title") or "").strip()[:200]
    if draft.get("text") is not None:
        unit["summary"] = str(draft["text"]).strip()
    if draft.get("chapters"):
        unit["chapter_count"] = max(1, min(50, int(draft["chapters"])))
    return unit


# ---------- 收下 ----------


async def accept_split(
    session: AsyncSession, book: Book, target_type: str, target_id: str, drafts: list[dict], plan: dict | None
) -> dict[str, Any]:
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    if target_type == "unit":
        undo = await _accept_unit(session, book, target_id, drafts)
    else:
        undo = await _accept_volume(session, book, target_id, drafts, plan or {})
    await session.commit()
    return {"undo": undo}


async def _accept_unit(session: AsyncSession, book: Book, target_id: str, drafts: list[dict]) -> dict:
    state = await outline_structure.load_structure(session, book.id)
    unit = next((row for row in state.units if str(row.id) == target_id), None)
    if unit is None:
        raise HTTPException(404, "这个单元不存在")
    volume = next(row for row in state.volumes if row.id == unit.volume_id)
    own = state.own_chapters(unit)
    planned = [c for c in own if not outline_structure.started(c)]
    kept = [c for c in own if outline_structure.started(c)]
    undo = {
        "created": [],
        "removed": [{"title": c.title, "outline": c.outline} for c in planned],
        "unit": {"chapter_count": unit.chapter_count, "status": unit.status},
        "volume_count": volume.chapter_count,
    }
    # 还没写的章换成新的；写好的不动。新的先放在最前面的空号，下面按顺序重排章号
    at = (
        state.chapters.index(planned[0])
        if planned
        else (state.chapters.index(kept[-1]) + 1 if kept else _unit_slot(state, unit))
    )
    for chapter in planned:
        state.chapters.remove(chapter)
        await session.delete(chapter)
    await session.flush()
    floor = min((row.index for row in state.chapters), default=1)
    created = []
    for offset, draft in enumerate(drafts):
        plan = chapter_plan_from(draft)
        chapter = Chapter(
            book_id=book.id,
            volume_id=unit.volume_id,
            unit_id=unit.id,
            index=floor - len(drafts) - 1 + offset,
            title=plan["title"],
            outline=plan,
            status="planned",
        )
        session.add(chapter)
        created.append(chapter)
    await session.flush()
    state.chapters[at:at] = created
    total = len(kept) + len(created)
    # 作者不要的那几章不占章数：收下几章就是几章
    unit.chapter_count = total
    unit.status = "outlined"
    volume.chapter_count = sum(row.chapter_count for row in state.own_units(volume.id))
    await outline_structure.finish_structure(
        session, book.id, state, "收下编辑部出的章纲", affected={unit.id, volume.id}, source="ai"
    )
    undo["created"] = [str(c.id) for c in created]
    return undo


def _unit_slot(state: outline_structure.Structure, unit: PlotUnit) -> int:
    """单元还一章都没有：新章插在它前面那些单元的最后一章后面。"""
    order = {v.id: v.index for v in state.volumes}
    before = {row.id for row in state.units if (order[row.volume_id], row.index) < (order[unit.volume_id], unit.index)}
    volumes_before = {v.id for v in state.volumes if v.index < order[unit.volume_id]}
    last = -1
    for i, chapter in enumerate(state.chapters):
        if chapter.unit_id in before or (chapter.unit_id is None and chapter.volume_id in volumes_before):
            last = i
    return last + 1


async def _accept_volume(session: AsyncSession, book: Book, target_id: str, drafts: list[dict], plan: dict) -> dict:
    volume = await _volume(session, book, target_id)
    if await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == volume.id).limit(1)):
        raise HTTPException(409, "这一卷已经有单元了，不整个重拆")
    if await session.scalar(select(Chapter.id).where(Chapter.volume_id == volume.id).limit(1)):
        raise HTTPException(409, "这一卷已经有章了，先在旧版处理")
    before = snapshot_of(volume)
    undo = {
        "volume": {
            "status": volume.status,
            "chapter_count": volume.chapter_count,
            "want": volume.want,
            "pressure": volume.pressure,
        }
    }
    units = [_unit_plan_from(d, i) for i, d in enumerate(drafts, 1)]
    units = clean_reveals(units, await setup_store.load_secrets(session, book.id))
    ledger = await setup_store.load_ledger(session, book.id)
    fresh = setup_store.assign_seqs(
        [
            *({**item, "kind": "伏笔"} for item in plan.get("new_foreshadowings") or []),
            *({"span": "中", **item, "kind": "期待"} for item in plan.get("new_expectations") or []),
        ],
        ledger,
    )
    units, fresh = attach_new_foreshadowings(units, fresh, volume.index)
    await writing_store.save_volume_plan(
        session,
        book.id,
        volume,
        units,
        fresh,
        replace_new=False,
        want=plan.get("want", ""),
        pressure=plan.get("pressure", ""),
    )
    # 作者自己收下的：不用再拍板卷纲
    volume.status = "approved"
    volume.chapter_count = sum(int(u.get("chapter_count") or 0) for u in units)
    await record_version(session, book.id, "volume", volume, "ai", "收下编辑部拆的单元", before=before)
    rows = list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index)))
    for row in rows:
        await record_version(session, book.id, "unit", row, "ai", "收下编辑部拆的单元")
    await session.flush()
    undo["units"] = [str(row.id) for row in rows]
    undo["foreshadowings"] = [f["seq"] for f in fresh]
    return undo


# ---------- 撤销 ----------


async def undo_split(session: AsyncSession, book: Book, target_type: str, target_id: str, undo: dict) -> None:
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    if target_type == "unit":
        await _undo_unit(session, book, target_id, undo)
    else:
        await _undo_volume(session, book, target_id, undo)
    await session.commit()


async def _undo_unit(session: AsyncSession, book: Book, target_id: str, undo: dict) -> None:
    state = await outline_structure.load_structure(session, book.id)
    unit = next((row for row in state.units if str(row.id) == target_id), None)
    if unit is None:
        raise HTTPException(404, "这个单元不存在")
    volume = next(row for row in state.volumes if row.id == unit.volume_id)
    created = [c for c in state.chapters if str(c.id) in set(undo.get("created") or [])]
    if any(outline_structure.started(c) for c in created):
        raise HTTPException(409, "收下的章已经开写了，不能撤销")
    at = state.chapters.index(created[0]) if created else len(state.chapters)
    for chapter in created:
        state.chapters.remove(chapter)
        await session.delete(chapter)
    await session.flush()
    floor = min((row.index for row in state.chapters), default=1)
    restored = []
    removed = undo.get("removed") or []
    for offset, item in enumerate(removed):
        chapter = Chapter(
            book_id=book.id,
            volume_id=unit.volume_id,
            unit_id=unit.id,
            index=floor - len(removed) - 1 + offset,
            title=str(item.get("title") or ""),
            outline=item.get("outline") or {},
            status="planned",
        )
        session.add(chapter)
        restored.append(chapter)
    await session.flush()
    state.chapters[at:at] = restored
    old = undo.get("unit") or {}
    unit.chapter_count = int(old.get("chapter_count", unit.chapter_count))
    unit.status = str(old.get("status") or unit.status)
    volume.chapter_count = sum(row.chapter_count for row in state.own_units(volume.id))
    await outline_structure.finish_structure(
        session, book.id, state, "撤销编辑部出的章纲", affected={unit.id, volume.id}, source="author"
    )


async def _undo_volume(session: AsyncSession, book: Book, target_id: str, undo: dict) -> None:
    volume = await _volume(session, book, target_id)
    if await session.scalar(select(Chapter.id).where(Chapter.volume_id == volume.id).limit(1)):
        raise HTTPException(409, "这一卷已经出了章纲，不能撤销拆单元")
    before = snapshot_of(volume)
    for unit_id in undo.get("units") or []:
        row = await session.get(PlotUnit, uuid.UUID(unit_id))
        if row is not None and row.volume_id == volume.id:
            await session.delete(row)
    seqs = [int(seq) for seq in undo.get("foreshadowings") or []]
    if seqs:
        for row in await session.scalars(
            select(Foreshadowing).where(Foreshadowing.book_id == book.id, Foreshadowing.seq.in_(seqs))
        ):
            if row.status == "planned":
                await session.delete(row)
    old = undo.get("volume") or {}
    for key in ("status", "chapter_count", "want", "pressure"):
        if key in old:
            setattr(volume, key, old[key])
    await session.flush()
    await record_version(session, book.id, "volume", volume, "author", "撤销编辑部拆的单元", before=before)
