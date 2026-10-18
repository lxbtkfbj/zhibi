"""新书页上的设定：每一类有哪几栏、一条设定每一栏写了什么，以及让编辑部把一条空着的栏目补上。

栏目和前端 frontend/src/pages/workspace/model.ts 的 DEFAULT_FIELDS 一致；这本书改过的栏目存在 books.card_layouts。
"""

import asyncio
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.context import format_requirements
from app.library_config import BUILTIN_CATEGORIES, CHARACTER_CATEGORY, GOLDFINGER
from app.models import Book, Character, SettingCategory, WorldEntry
from app.services.library import ensure_unlocked, infer_status, load_target, lock_book
from app.services.library_context import load_context
from app.services.requirements import active_requirements, requirement_text
from app.services.versions import previous_version_id, record_version, snapshot_of

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
# 新书页上的类别 → 设定库里的类别
ENTRY_CATEGORIES = {
    "地点列表": "世界与地图",
    "势力列表": "势力划分",
    "物品功法": "物品与功法",
    "往事秘密": "往事与秘密",
    "特殊规则": "特殊规则",
    "金手指": GOLDFINGER,
}
WORLD_OVERVIEW = "世界概况"
LADDER = "等级体系"
# 每一类默认有哪几栏：名字下面的小字、正文栏目
DEFAULT_FIELDS = {
    "角色列表": (["定位", "所属", "性别", "年龄", "别名"], ["外貌", "性格与说话方式", "身世", "想要什么", "软肋", "能力", "成长与结局", "备注"]),
    "金手指": (["是什么", "谁知道"], ["能做什么", "规矩和限制", "代价", "怎么变强", "来历"]),
    "地点列表": (["归谁管"], ["内容"]),
    "势力列表": (["领头的", "对主角", "地盘"], ["内容"]),
    "物品功法": (["品阶", "在谁手里"], ["内容"]),
    "往事秘密": (["谁知道", "打算何时揭开"], ["内容"]),
    "特殊规则": ([], ["内容"]),
}
# 地点这一类不要「第一条是世界概况」那句：世界概况在新书页上单独一页
PLACE_HINT = "一个个地方：这是什么地方，给人什么感觉；属于哪里；谁说了算；有什么规矩或危险；主角在这里处境如何；这里能得到什么。用得上的写，用不上的不写。"
FILL_TIMEOUT = 150


def content_key(category: str) -> str:
    """哪一栏存在条目的 content 里。"""
    return "能做什么" if category == GOLDFINGER else "内容"


def is_goldfinger(row: WorldEntry) -> bool:
    """金手指这一类，加上别的内置类别里带「金手指」标签的段落条目（和前端一样都摆在金手指里）。"""
    if row.category == GOLDFINGER:
        return True
    return GOLDFINGER in (row.tags or []) and row.style == "paragraph" and not row.category.startswith("custom:")


def desk_category(target: Character | WorldEntry) -> str:
    """一条设定在新书页上归哪一类。"""
    if isinstance(target, Character):
        return "角色列表"
    if target.category == "世界与地图" and target.name.strip() == WORLD_OVERVIEW:
        return WORLD_OVERVIEW
    if is_goldfinger(target):
        return GOLDFINGER
    if target.category.startswith("custom:") or target.category == LADDER:
        return target.category
    return next((name for name, key in ENTRY_CATEGORIES.items() if key == target.category), "特殊规则")


async def columns_of(session: AsyncSession, book: Book, target: Character | WorldEntry) -> list[tuple[str, str]]:
    """这一条有哪几栏：(存内容时认的名字, 现在显示的名字)，名字下面的小字在前。"""
    category = desk_category(target)
    if category == WORLD_OVERVIEW or getattr(target, "style", "") == "ladder":
        return [("内容", "总说明" if target.style == "ladder" else "内容")]
    saved = (book.card_layouts or {}).get(category)
    if saved:
        return [(f["key"], f["label"]) for f in [*saved.get("facts", []), *saved.get("sections", [])]]
    if category.startswith("custom:"):
        custom = await session.scalar(
            select(SettingCategory).where(
                SettingCategory.book_id == book.id, SettingCategory.key == category.removeprefix("custom:")
            )
        )
        fields = (custom.fields or []) if custom is not None and custom.style == "card" else ["内容"]
        return [(name, name) for name in fields]
    facts, sections = DEFAULT_FIELDS.get(category, ([], ["内容"]))
    return [(name, name) for name in [*facts, *sections]]


def value_of(target: Character | WorldEntry, key: str) -> str:
    if isinstance(target, Character):
        column = CHARACTER_COLUMNS.get(key)
        if column == "aliases":
            return "、".join(target.aliases or [])
        if column:
            return getattr(target, column) or ""
        return (target.extra or {}).get(key, "")
    if key == content_key(desk_category(target)) or key == "内容":
        return target.content or ""
    return next((f.get("value", "") for f in target.fields or [] if f.get("name") == key), "")


def write_value(target: Character | WorldEntry, key: str, value: str) -> None:
    if isinstance(target, Character):
        column = CHARACTER_COLUMNS.get(key)
        if column == "aliases":
            target.aliases = [name.strip() for name in value.replace("，", "、").split("、") if name.strip()]
        elif column:
            setattr(target, column, value)
        else:
            target.extra = {**(target.extra or {}), key: value}
        return
    if key == content_key(desk_category(target)) or key == "内容":
        target.content = value
    else:
        target.fields = [*[f for f in target.fields or [] if f.get("name") != key], {"name": key, "value": value}]


def hint_of(target: Character | WorldEntry, custom_hint: str = "") -> str:
    if isinstance(target, Character):
        return CHARACTER_CATEGORY["hint"]
    if target.category == "世界与地图":
        return PLACE_HINT
    if target.category.startswith("custom:"):
        return custom_hint or "（作者没写说明）"
    return next((c["hint"] for c in BUILTIN_CATEGORIES if c["key"] == target.category), "")


async def fill_entry(
    session: AsyncSession, book: Book, target_type: str, target_id: uuid.UUID, request: str = ""
) -> dict:
    """让设定师把一条设定空着的栏目补上：作者写过的不动；定位不补。调模型时不占着数据库。"""
    from app.api.library_ai import call_model

    book_id = book.id
    target = await load_target(session, book_id, target_type, target_id)
    try:
        ensure_unlocked(target)
    except HTTPException as exc:
        raise HTTPException(409, "已锁：AI 不能改这一条，先解锁") from exc
    columns = await columns_of(session, book, target)
    empty = [(key, label) for key, label in columns if key != "定位" and not value_of(target, key).strip()]
    name = target.name
    if not empty:
        return {"filled": [], "note": "", "target_name": name, "revert_version_id": None}
    ctx = await load_context(session, book)
    custom_hint = ""
    if isinstance(target, WorldEntry) and target.category.startswith("custom:"):
        custom_hint = next((c.get("hint", "") for c in ctx.categories if c["key"] == target.category), "")
    requirements = await active_requirements(session, book_id)
    blocks = dict(
        target_name=name,
        concept=ctx.concept,
        library=ctx.library,
        target_full=ctx.entry_full_text(target),
        related=ctx.related(target),
        category_hint=hint_of(target, custom_hint),
        fields="、".join(label for _, label in empty),
        requirements=format_requirements([requirement_text(row) for row in requirements], [], book.settings),
        request=request.strip() or "（作者只说把这一条补齐）",
    )
    await session.rollback()
    try:
        result = await asyncio.wait_for(
            call_model(book_id, "lorekeeper", s.FillEntry, "library_fill_entry", **blocks), timeout=FILL_TIMEOUT
        )
    except TimeoutError as exc:
        raise HTTPException(504, "这次编辑部太慢了，两分半还没写完，没改。再试一次") from exc

    await lock_book(session, book_id)
    target = await load_target(session, book_id, target_type, target_id, for_update=True)
    ensure_unlocked(target)
    labels = {label.strip(): key for key, label in empty}
    before = snapshot_of(target)
    filled = []
    for item in result.values:
        key, value = labels.get(item.name.strip()), item.value.strip()
        # 只填现在还空着的：等模型的工夫作者自己写了的，不盖
        if key and value and not value_of(target, key).strip():
            write_value(target, key, value)
            filled.append(next(label for k, label in empty if k == key))
    if not filled:
        await session.rollback()
        return {"filled": [], "note": result.note, "target_name": name, "revert_version_id": None}
    if target.source != "author":
        target.source = "ai"
    target.status = infer_status(target)
    await record_version(session, book_id, target_type, target, "ai", "补齐空着的栏目", before=before)
    revert = await previous_version_id(session, target_type, target.id)
    await session.commit()
    return {"filled": filled, "note": result.note, "target_name": name, "revert_version_id": revert}


def path_of(target: Character | WorldEntry, key: str) -> str:
    """一栏存在哪：局部改写用的路径。"""
    if isinstance(target, Character):
        column = CHARACTER_COLUMNS.get(key)
        return column if column else f"extra.{key}"
    if key == content_key(desk_category(target)) or key == "内容":
        return "content"
    return f"fields.{key}"


async def column_in(session: AsyncSession, book: Book, target: Character | WorldEntry, *texts: str) -> str | None:
    """作者话里提到了这一条的哪一栏（按显示名找，长的先认）：返回存内容时认的名字。"""
    columns = sorted(await columns_of(session, book, target), key=lambda item: -len(item[1]))
    for text in texts:
        text = (text or "").strip()
        if not text:
            continue
        for key, label in columns:
            if key != "定位" and (text == label or len(label) >= 2 and label in text):
                return key
    return None
