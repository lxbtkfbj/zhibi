"""新工作台：每本书每一类设定有哪几栏；作者自己在大纲里加篇、加章。

栏目按名字存内容：角色有专门一列的栏目（外貌、身世……）存在列里，其余放 extra；
设定条目的「内容」存 content，其余放 fields。改名时内容跟着改名，删掉的栏目内容一起清掉。
作者加的篇只有名字和一段话，排在已规划的篇后面；写到它时编辑部照这段话分卷（write_book.fill_segment）。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.context import format_requirements
from app.api.deps import SessionDep, ensure_idle, get_book
from app.api.library_ai import call_model
from app.library_config import BUILTIN_CATEGORIES, CHARACTER_CATEGORY, GOLDFINGER, LEGACY_ROLE_TYPES, ROLE_TYPES
from app.models import Book, Chapter, Character, PlotUnit, SettingCategory, StoryNode, Volume, WorldEntry
from app.schemas import ArcCreate, CardLayoutIn, ChapterCreate, DraftRequest, FillRequest, OutlineMove, OutlineRestoreIn, OutlineWriteIn
from app.services import outline_structure
from app.services.desk import (
    CHARACTER_COLUMNS,
    ENTRY_CATEGORIES,
    LADDER,
    PLACE_HINT,
    WORLD_OVERVIEW,
    content_key,
    fill_entry,
    is_goldfinger,
)
from app.services.library import lock_book
from app.services.library_context import load_context
from app.services.outline_write import restore_outline_node, write_outline_node
from app.services.requirements import active_requirements, requirement_text
from app.services.versions import record_version, snapshot_of

router = APIRouter(tags=["workspace"])

async def entry_rows(session: AsyncSession, book_id, category: str) -> list[WorldEntry]:
    rows = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book_id)))
    if category == GOLDFINGER:
        return [r for r in rows if is_goldfinger(r)]
    if category.startswith("custom:"):
        return [r for r in rows if r.category == category]
    key = ENTRY_CATEGORIES[category]
    return [
        r
        for r in rows
        if r.category == key
        and not is_goldfinger(r)
        and not (key == "世界与地图" and r.name.strip() == WORLD_OVERVIEW)
    ]


def clear_character(row: Character, key: str) -> None:
    column = CHARACTER_COLUMNS.get(key)
    if column:
        setattr(row, column, [] if column == "aliases" else "")
    elif key in (row.extra or {}):
        row.extra = {k: v for k, v in row.extra.items() if k != key}


def rename_character(row: Character, old: str, new: str) -> None:
    extra = dict(row.extra or {})
    if old in extra:
        extra[new] = extra.pop(old)
        row.extra = extra


def clear_entry(row: WorldEntry, key: str, category: str) -> None:
    if key == content_key(category):
        row.content = ""
    else:
        row.fields = [f for f in row.fields or [] if f.get("name") != key]


def rename_entry(row: WorldEntry, old: str, new: str) -> None:
    fields = [dict(f) for f in row.fields or []]
    if any(f.get("name") == old for f in fields):
        fields = [f for f in fields if f.get("name") != new]
        for f in fields:
            if f.get("name") == old:
                f["name"] = new
        row.fields = fields


@router.put("/books/{book_id}/card-layouts/{category}")
async def save_card_layout(
    category: str, body: CardLayoutIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep
) -> dict[str, Any]:
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    people = category == "角色列表"
    custom = None
    if category.startswith("custom:"):
        custom = await session.scalar(
            select(SettingCategory).where(
                SettingCategory.book_id == book.id, SettingCategory.key == category.removeprefix("custom:")
            )
        )
        if custom is None:
            raise HTTPException(404, "这个类别不属于这本书")
        if custom.style == "ladder":
            raise HTTPException(422, "阶梯类没有栏目可调")
    elif not people and category not in ENTRY_CATEGORIES:
        raise HTTPException(422, "这一类没有栏目可调")
    if people and ("定位" in body.dropped or "定位" not in {f.key for f in body.facts}):
        raise HTTPException(422, "「定位」按它分组，不能删")

    characters: list[Character] = (
        list(await session.scalars(select(Character).where(Character.book_id == book.id))) if people else []
    )
    entries = [] if people else await entry_rows(session, book.id, category)
    kept = {f.key for f in [*body.facts, *body.sections]}
    for key in body.dropped:
        if key in kept:
            continue
        for row in characters:
            clear_character(row, key)
        for row in entries:
            clear_entry(row, key, category)

    def settle(field) -> dict[str, str]:
        label = field.label.strip()
        fixed = (people and field.key in CHARACTER_COLUMNS) or (not people and field.key == content_key(category))
        if fixed or field.key == label:
            return {"key": field.key, "label": label}
        # 没有专门一列的栏目，改名就是把内容挪到新名字下面
        for row in characters:
            rename_character(row, field.key, label)
        for row in entries:
            rename_entry(row, field.key, label)
        return {"key": label, "label": label}

    layout = {"facts": [settle(f) for f in body.facts], "sections": [settle(f) for f in body.sections]}
    book.card_layouts = {**(book.card_layouts or {}), category: layout}
    if custom is not None and custom.style == "card":
        custom.fields = [f["label"] for f in [*layout["facts"], *layout["sections"]]]
    await session.commit()
    return layout


@router.delete("/books/{book_id}/card-layouts/{category}", status_code=204)
async def reset_card_layout(category: str, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> None:
    """恢复默认：只去掉存的栏目，已经写的内容不动。"""
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    book.card_layouts = {k: v for k, v in (book.card_layouts or {}).items() if k != category}
    await session.commit()


# ---------- 大纲：作者自己加篇、加章 ----------


async def _ordered_nodes(session: AsyncSession, book_id) -> list[StoryNode]:
    return list(
        await session.scalars(
            select(StoryNode).where(StoryNode.book_id == book_id).order_by(StoryNode.position, StoryNode.id)
        )
    )


async def plan_earlier_arcs(session: AsyncSession, book_id, nodes: list[StoryNode]) -> None:
    """定下来的篇前面不能夹着「写到再定」的篇（写的时候会被跳过）：前面的都按节点上写的定下来。"""
    last = max((i for i, node in enumerate(nodes) if node.segment is not None), default=-1)
    for node in nodes[:last]:
        if node.kind == "milestone" and node.segment is None:
            before = snapshot_of(node)
            node.segment = {"title": node.title, "text": node.event}
            await record_version(session, book_id, "segment", node, "author", before=before)


@router.post("/books/{book_id}/arcs", status_code=201)
async def create_arc(body: ArcCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """加一篇：只有名字和一段话，写到它时编辑部照这段话分卷。可以插在任何一篇的前面或后面；
    不说插哪就接在已经定下来的篇后面。开篇前面、结局后面不能插。"""
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    nodes = await _ordered_nodes(session, book.id)
    planned = [i for i, node in enumerate(nodes) if node.segment is not None]
    if not planned and await session.scalar(select(Volume.id).where(Volume.book_id == book.id).limit(1)):
        raise HTTPException(409, "这本书的卷没有分篇，不能再加篇")
    ending = next((i for i, node in enumerate(nodes) if node.kind == "ending"), len(nodes))
    if body.before_node_id or body.after_node_id:
        anchor = body.before_node_id or body.after_node_id
        found = next((i for i, node in enumerate(nodes) if node.id == anchor), None)
        if found is None:
            raise HTTPException(422, "插入位置的那一篇不属于这本书")
        if body.before_node_id and nodes[found].kind == "opening":
            raise HTTPException(422, "开篇前面不能插")
        if body.after_node_id and nodes[found].kind == "ending":
            raise HTTPException(422, "结局后面不能插")
        at = found if body.before_node_id else found + 1
    elif planned:
        at = min(planned[-1] + 1, ending)
    else:
        at = next((i + 1 for i, node in enumerate(nodes) if node.kind == "opening"), 0)
    title = body.title.strip()
    node = StoryNode(
        book_id=book.id,
        position=0,
        kind="milestone",
        title=title,
        event="",
        segment={"title": title, "text": body.text.strip()},
        status="pencil",
        origin="author",
    )
    nodes.insert(at, node)
    for position, row in enumerate(nodes, 1):
        row.position = position
    session.add(node)
    await session.flush()
    await record_version(session, book.id, "segment", node, "author")
    await plan_earlier_arcs(session, book.id, nodes)
    await session.commit()
    return {"id": str(node.id)}


@router.delete("/arcs/{node_id}", status_code=204)
async def delete_arc(node_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    """删一篇：下面还有卷的先删卷；开篇和结局不能删。"""
    node = await session.get(StoryNode, node_id)
    if node is None:
        raise HTTPException(404, "这一篇不存在")
    await lock_book(session, node.book_id)
    await ensure_idle(session, node.book_id)
    if node.kind in {"opening", "ending"}:
        raise HTTPException(409, "开篇和结局不能删")
    if await session.scalar(select(Volume.id).where(Volume.target_node_id == node.id).limit(1)):
        raise HTTPException(409, "这一篇下面还有卷，先把卷删掉")
    nodes = [row for row in await _ordered_nodes(session, node.book_id) if row.id != node.id]
    await session.delete(node)
    await session.flush()
    for position, row in enumerate(nodes, 1):
        row.position = position
    await session.commit()


@router.post("/units/{unit_id}/chapters", status_code=201)
async def create_chapter(unit_id: uuid.UUID, body: ChapterCreate, session: AsyncSession = SessionDep) -> dict:
    """在单元最后加一章。单元原来预留了章数的，先填预留的；没有了就多算一章。"""
    unit = await session.get(PlotUnit, unit_id)
    if unit is None:
        raise HTTPException(404, "剧情单元不存在")
    await lock_book(session, unit.book_id)
    await ensure_idle(session, unit.book_id)
    state = await outline_structure.load_structure(session, unit.book_id)
    unit = next(row for row in state.units if row.id == unit_id)
    volume = next(row for row in state.volumes if row.id == unit.volume_id)
    if unit.status == "done" or volume.status == "done":
        raise HTTPException(409, "这个单元已经写完了，不能再加章")
    own = state.own_chapters(unit)
    if len(own) >= 50:
        raise HTTPException(422, "每个单元最多 50 章，请先增加单元")
    anchor = None
    if body.before_index is not None or body.after_index is not None:
        wanted = body.before_index if body.before_index is not None else body.after_index
        anchor = next((row for row in own if row.index == wanted), None)
        if anchor is None:
            raise HTTPException(422, "插入位置的那一章不在这个单元里")
    outline = body.outline.model_dump(exclude_none=True)
    outline["scenes"] = [scene.strip() for scene in outline.get("scenes") or [] if scene.strip()]
    chapter = Chapter(
        book_id=unit.book_id,
        volume_id=unit.volume_id,
        unit_id=unit.id,
        # 先放在最前面的空号，下面按顺序重排章号
        index=min((row.index for row in state.chapters), default=1) - 1,
        title=body.title.strip(),
        outline=outline,
        status="planned",
    )
    session.add(chapter)
    await session.flush()
    # 章号按 state.chapters 里的先后排：插在那一章前面或后面，不给位置就接在这个单元最后
    if anchor is not None:
        at = state.chapters.index(anchor) + (0 if body.before_index is not None else 1)
    else:
        at = state.chapters.index(own[-1]) + 1 if own else len(state.chapters)
    state.chapters.insert(at, chapter)
    # 章数定了、又填满了，就多算一章；章数没定（0）的有几章算几章
    if unit.chapter_count > 0 and len(own) + 1 > unit.chapter_count:
        unit.chapter_count = len(own) + 1
        volume.chapter_count = sum(row.chapter_count for row in state.own_units(volume.id))
    await outline_structure.finish_structure(
        session, unit.book_id, state, "新增一章", affected={unit.id, volume.id}
    )
    await session.commit()
    return {"index": chapter.index}


@router.delete("/books/{book_id}/chapters/{index}", status_code=204)
async def delete_chapter(index: int, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> None:
    """删一章还没开写的章纲，单元少算一章。"""
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    state = await outline_structure.load_structure(session, book.id)
    chapter = next((row for row in state.chapters if row.index == index), None)
    if chapter is None:
        raise HTTPException(404, "这一章还不存在")
    if outline_structure.started(chapter):
        raise HTTPException(409, "这一章已经开写了，不能删")
    unit = next((row for row in state.units if row.id == chapter.unit_id), None)
    if unit is None:
        raise HTTPException(409, "这一章不在哪个单元里，不能在这里删")
    volume = next(row for row in state.volumes if row.id == unit.volume_id)
    state.chapters.remove(chapter)
    await session.delete(chapter)
    await session.flush()
    if unit.chapter_count > 0:
        unit.chapter_count = max(1, unit.chapter_count - 1)
    volume.chapter_count = sum(row.chapter_count for row in state.own_units(volume.id))
    await outline_structure.finish_structure(session, book.id, state, "删掉一章", affected={unit.id, volume.id})
    await session.commit()


# ---------- 编辑部帮写：在一类里写几条候选 ----------

SAME_KIND_BUDGET = 5000


def same_kind_text(ctx, rows) -> str:
    """这一类已经有的：先放全文，放不下的只列名字。"""
    if not rows:
        return "（还没有）"
    full, names = [], []
    for row in rows:
        text = ctx.entry_full_text(row)
        if not names and len("\n\n".join([*full, text])) <= SAME_KIND_BUDGET:
            full.append(text)
        else:
            names.append(row.name)
    return "\n\n".join(full) + (f"\n\n还有：{'、'.join(names)}" if names else "")


@router.post("/books/{book_id}/drafts")
async def draft_entries(body: DraftRequest, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """编辑部帮写：写几条候选，不存。作者收下哪条，前端就按新增一条存进来（来源记成从候选里收下的）。"""
    people = body.category == "角色列表"
    ladder = body.category == LADDER
    custom = None
    if body.category.startswith("custom:"):
        custom = await session.scalar(
            select(SettingCategory).where(
                SettingCategory.book_id == book.id, SettingCategory.key == body.category.removeprefix("custom:")
            )
        )
        if custom is None:
            raise HTTPException(404, "这个类别不属于这本书")
        ladder = custom.style == "ladder"
    elif not people and not ladder and body.category not in ENTRY_CATEGORIES:
        raise HTTPException(422, "这一类不能帮写")

    ctx = await load_context(session, book)
    if people:
        same, name, hint = ctx.characters, "角色", CHARACTER_CATEGORY["hint"]
    elif custom is not None:
        same, name, hint = await entry_rows(session, book.id, body.category), custom.name, custom.hint or "（作者没写说明）"
    elif ladder:
        same = [row for row in ctx.entries if row.category == LADDER]
        name, hint = LADDER, next(c["hint"] for c in BUILTIN_CATEGORIES if c["key"] == LADDER)
    else:
        key = ENTRY_CATEGORIES[body.category]
        same, name = await entry_rows(session, book.id, body.category), body.category
        hint = PLACE_HINT if key == "世界与地图" else next(c["hint"] for c in BUILTIN_CATEGORIES if c["key"] == key)
    if ladder:
        fields = "一级一级往上排：values 只写一栏「总说明」，各级写在 levels 里。"
    else:
        facts = "、".join(f.label for f in body.facts)
        sections = "、".join(f.label for f in body.sections) or "内容"
        fields = (f"名字下面的短栏目：{facts}\n" if facts else "") + f"正文栏目：{sections}"
    requirements = await active_requirements(session, book.id)
    blocks = dict(
        category=name,
        concept=ctx.concept,
        library=ctx.library,
        same_kind=same_kind_text(ctx, same),
        category_hint=hint,
        fields=fields,
        requirements=format_requirements([requirement_text(row) for row in requirements], [], book.settings),
        request=body.request.strip() or "（作者没说，按定调和已有的设定来）",
        count=f"{body.count} 条",
    )
    taken = {n for row in [*ctx.characters, *ctx.entries] for n in [row.name, *(row.aliases or [])] if n}
    book_id = book.id
    # 调模型时不占着数据库
    await session.rollback()
    result = await call_model(book_id, "lorekeeper", s.DraftSet, "library_draft", **blocks)

    keys = {f.label.strip(): f.key for f in [*body.facts, *body.sections]}
    entries = []
    for item in result.entries:
        title = item.name.strip()
        if not title or title in taken:
            continue
        taken.add(title)
        values = {}
        for field in item.values:
            label, value = field.name.strip(), field.value.strip()
            if not value:
                continue
            if ladder and label == "总说明":
                values[label] = value
            elif label in keys:
                values[keys[label]] = value
        if people:
            # 模型偶尔写成「明面上的对手」：认出里面的定位词，认不出算配角
            role = values.get("定位", "")
            names = [*ROLE_TYPES, *LEGACY_ROLE_TYPES]
            found = next((name for name in names if name in role), "配角")
            values["定位"] = LEGACY_ROLE_TYPES.get(found, found)
        levels = [
            {"name": level.name.strip(), "text": level.text.strip()} for level in item.levels if level.name.strip()
        ]
        entries.append({"name": title, "values": values, "levels": levels if ladder else []})
        if len(entries) >= body.count:
            break
    return {"entries": entries, "note": result.note}


@router.post("/books/{book_id}/fill-entry")
async def fill_one_entry(body: FillRequest, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """让编辑部把这一条空着的栏目补上（卡片右上角「⋯」里点的）。"""
    return await fill_entry(session, book, body.target_type, body.target_id, body.request)


@router.post("/books/{book_id}/outline/write")
async def write_outline(body: OutlineWriteIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """大纲上每一页的「编辑部帮写这一段」：直接写进去，返回改之前的样子好撤销。"""
    return await write_outline_node(session, book, body.target_type, body.target_id, body.request)


@router.post("/books/{book_id}/outline/restore")
async def restore_outline(
    body: OutlineRestoreIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep
) -> dict:
    """群聊里点「撤销」：把编辑部帮写之前的那一段存回去。"""
    await restore_outline_node(session, book, body.target_type, body.target_id, body.before)
    return {"ok": True}


@router.post("/books/{book_id}/outline/move")
async def move_outline(body: OutlineMove, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """篇、卷、单元、章往前或往后挪一格。卷跟着篇走；已经开写的章节不能被挪动。"""
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    step = -1 if body.direction == "up" else 1
    edge = "已经在最前面了" if step < 0 else "已经在最后面了"

    def swap(rows: list, row, other) -> list:
        rows = list(rows)
        a, b = rows.index(row), rows.index(other)
        rows[a], rows[b] = rows[b], rows[a]
        return rows

    if body.kind == "arc":
        nodes = await _ordered_nodes(session, book.id)
        node = next((row for row in nodes if str(row.id) == body.id), None)
        if node is None or node.kind != "milestone":
            raise HTTPException(404, "这一篇不存在")
        arcs = [row for row in nodes if row.kind == "milestone"]
        j = arcs.index(node) + step
        if not 0 <= j < len(arcs):
            raise HTTPException(422, edge)
        nodes = swap(nodes, node, arcs[j])
        for position, row in enumerate(nodes, 1):
            row.position = position
        await plan_earlier_arcs(session, book.id, nodes)
        # 卷跟着篇的顺序走：写作按卷号往下写
        state = await outline_structure.load_structure(session, book.id)
        order = {row.id: i for i, row in enumerate(nodes)}
        ordered = sorted(state.volumes, key=lambda v: (order.get(v.target_node_id, len(order)), v.index))
        if ordered != state.volumes:
            await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
            state.volumes = ordered
        await outline_structure.finish_structure(session, book.id, state, "挪动篇的顺序")
        await session.commit()
        return {"id": body.id}

    state = await outline_structure.load_structure(session, book.id)
    if body.kind == "volume":
        volume = next((row for row in state.volumes if str(row.id) == body.id), None)
        if volume is None:
            raise HTTPException(404, "这一卷不存在")
        siblings = [row for row in state.volumes if row.target_node_id == volume.target_node_id]
        j = siblings.index(volume) + step
        if not 0 <= j < len(siblings):
            raise HTTPException(422, edge)
        ordered = swap(state.volumes, volume, siblings[j])
        await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
        state.volumes = ordered
        await outline_structure.finish_structure(
            session, book.id, state, "挪动卷的顺序", affected={volume.id, siblings[j].id}
        )
        await session.commit()
        return {"id": body.id}
    if body.kind == "unit":
        unit = next((row for row in state.units if str(row.id) == body.id), None)
        if unit is None:
            raise HTTPException(404, "这个单元不存在")
        siblings = state.own_units(unit.volume_id)
        j = siblings.index(unit) + step
        if not 0 <= j < len(siblings):
            raise HTTPException(422, edge)
        ordered = swap(siblings, unit, siblings[j])
        await outline_structure.assign_indices(session, ordered, list(range(1, len(ordered) + 1)))
        await outline_structure.finish_structure(
            session, book.id, state, "挪动单元的顺序", affected={unit.id, siblings[j].id, unit.volume_id}
        )
        await session.commit()
        return {"id": body.id}
    chapter = next((row for row in state.chapters if str(row.index) == body.id), None)
    if chapter is None or chapter.unit_id is None:
        raise HTTPException(404, "这一章不存在")
    unit = next(row for row in state.units if row.id == chapter.unit_id)
    siblings = state.own_chapters(unit)
    j = siblings.index(chapter) + step
    if not 0 <= j < len(siblings):
        raise HTTPException(422, edge)
    if outline_structure.started(chapter) or outline_structure.started(siblings[j]):
        raise HTTPException(409, "已经开写的章不能挪")
    state.chapters = swap(state.chapters, chapter, siblings[j])
    await outline_structure.finish_structure(session, book.id, state, "挪动章的顺序", affected={unit.id})
    await session.commit()
    return {"id": str(chapter.index)}
