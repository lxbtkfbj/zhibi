"""新工作台：每本书每一类设定有哪几栏。

栏目按名字存内容：角色有专门一列的栏目（外貌、身世……）存在列里，其余放 extra；
设定条目的「内容」存 content，其余放 fields。改名时内容跟着改名，删掉的栏目内容一起清掉。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, ensure_idle, get_book
from app.models import Book, Character, SettingCategory, WorldEntry
from app.schemas import CardLayoutIn
from app.services.library import lock_book

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
# 工作台上的类别 → 设定库里的类别；金手指是带「金手指」标签的条目
ENTRY_CATEGORIES = {
    "地点列表": "世界与地图",
    "势力列表": "势力划分",
    "物品功法": "物品与功法",
    "往事秘密": "往事与秘密",
    "特殊规则": "特殊规则",
    "金手指": None,
}
GOLDFINGER = "金手指"
WORLD_OVERVIEW = "世界概况"


def content_key(category: str) -> str:
    """哪一栏存在条目的 content 里。"""
    return "能做什么" if category == GOLDFINGER else "内容"


async def entry_rows(session: AsyncSession, book_id, category: str) -> list[WorldEntry]:
    rows = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book_id)))
    if category == GOLDFINGER:
        return [r for r in rows if GOLDFINGER in (r.tags or [])]
    if category.startswith("custom:"):
        return [r for r in rows if r.category == category]
    key = ENTRY_CATEGORIES[category]
    return [
        r
        for r in rows
        if r.category == key
        and GOLDFINGER not in (r.tags or [])
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
