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
from app.schemas import ArcCreate, CardLayoutIn, ChapterCreate, DraftRequest
from app.services import outline_structure
from app.services.library import lock_book
from app.services.library_context import load_context
from app.services.requirements import active_requirements, requirement_text
from app.services.versions import record_version

router = APIRouter(tags=["workspace"])

# 角色卡上有专门一列的栏目
CHARACTER_COLUMNS = {
    "定位": "role_type",
    "性别": "gender",
    "年龄": "age",
    "别名": "aliases",
    "外貌": "appearance",
    "性格与说话方式": "personality",
    "身世": "background",
    "想要什么": "goal",
    "能力": "abilities",
    "备注": "notes",
}
# 工作台上的类别 → 设定库里的类别
ENTRY_CATEGORIES = {
    "地点列表": "世界与地图",
    "势力列表": "势力划分",
    "物品功法": "物品与功法",
    "往事秘密": "往事与秘密",
    "特殊规则": "特殊规则",
    "金手指": GOLDFINGER,
}
WORLD_OVERVIEW = "世界概况"


def content_key(category: str) -> str:
    """哪一栏存在条目的 content 里。"""
    return "能做什么" if category == GOLDFINGER else "内容"


def is_goldfinger(row: WorldEntry) -> bool:
    """金手指这一类，加上别的内置类别里带「金手指」标签的段落条目（和前端一样都摆在金手指里）。"""
    if row.category == GOLDFINGER:
        return True
    return GOLDFINGER in (row.tags or []) and row.style == "paragraph" and not row.category.startswith("custom:")


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


@router.post("/books/{book_id}/arcs", status_code=201)
async def create_arc(body: ArcCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    """在已规划的篇后面加一篇：只有名字和一段话，写到它时编辑部照这段话分卷。"""
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    nodes = await _ordered_nodes(session, book.id)
    planned = [i for i, node in enumerate(nodes) if node.segment is not None]
    if not planned and await session.scalar(select(Volume.id).where(Volume.book_id == book.id).limit(1)):
        raise HTTPException(409, "这本书的卷没有分篇，不能再加篇")
    if any(node.kind == "ending" and node.segment is not None for node in nodes):
        raise HTTPException(409, "全书已经规划到结局了，不能再往后加篇")
    if planned:
        at = planned[-1] + 1
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
    state.chapters.append(chapter)
    if len(own) + 1 > unit.chapter_count:
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
    unit.chapter_count = max(1, unit.chapter_count - 1)
    volume.chapter_count = sum(row.chapter_count for row in state.own_units(volume.id))
    await outline_structure.finish_structure(session, book.id, state, "删掉一章", affected={unit.id, volume.id})
    await session.commit()


# ---------- 编辑部帮写：在一类里写几条候选 ----------

LADDER = "等级体系"
# 地点这一类不要「第一条是世界概况」那句：世界概况在新书页上单独一页
PLACE_HINT = "一个个地方：这是什么地方，给人什么感觉；属于哪里；谁说了算；有什么规矩或危险；主角在这里处境如何；这里能得到什么。用得上的写，用不上的不写。"
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
