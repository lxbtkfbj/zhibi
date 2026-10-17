"""设定库的共用校验、归属检查与目标装载。"""

import uuid
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_config import (
    BUILTIN_CATEGORIES,
    OLD_CATEGORY_MAP,
    STATUSES,
    STYLES,
    category_style,
    normalize_category,
)
from app.models import Book, Chapter, Character, PlotUnit, Secret, SettingCategory, StoryNode, Volume, WorldEntry

TARGET_MODELS = {
    "character": Character,
    "entry": WorldEntry,
    "concept": Book,
    "segment": StoryNode,
    "volume": Volume,
    "unit": PlotUnit,
    "chapter": Chapter,
}


def author_source(target: Any) -> str:
    """作者自己写的保留来源；其他来源经作者修改后明确标记。"""
    return "author" if target.source == "author" else "ai_edited"


def parse_uuid(value: Any, label: str = "目标") -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, f"{label}的编号不正确") from exc


async def lock_book(session: AsyncSession, book_id: uuid.UUID) -> None:
    # 各种编辑先锁书再锁目标，与版本序号的锁顺序一致。
    if await session.scalar(select(Book.id).where(Book.id == book_id).with_for_update()) is None:
        raise HTTPException(404, "书不存在")


async def load_target(
    session: AsyncSession,
    book_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID | str,
    *,
    for_update: bool = False,
) -> Any:
    model = TARGET_MODELS.get(target_type)
    if model is None:
        raise HTTPException(422, "不支持的目标类型")
    target_id = parse_uuid(target_id)
    query = select(model).where(model.id == target_id)
    query = query.where(model.id == book_id) if model is Book else query.where(model.book_id == book_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    target = await session.scalar(query)
    if target is None:
        raise HTTPException(404, "目标不存在或不属于这本书")
    return target


def ensure_unlocked(target: Any) -> None:
    if getattr(target, "locked", False) or isinstance(target, StoryNode) and target.status == "pinned":
        raise HTTPException(409, "这一条已锁，先解锁再改")


async def validate_entry(
    session: AsyncSession, book_id: uuid.UUID, data: dict, current: WorldEntry | None = None
) -> dict:
    """只返回待写字段；旧类别兼容，但未知类别、跨书引用和地方循环不能写入。"""
    values = deepcopy(data)
    raw_category = values.get("category", current.category if current is not None else "特殊规则")
    if not isinstance(raw_category, str):
        raise HTTPException(422, "类别不能为空")
    builtin = {item["key"] for item in BUILTIN_CATEGORIES}
    if raw_category not in builtin and raw_category not in OLD_CATEGORY_MAP and not raw_category.startswith("custom:"):
        raise HTTPException(422, "这个类别不存在")
    category = normalize_category(raw_category)
    categories = await session.scalars(select(SettingCategory).where(SettingCategory.book_id == book_id))
    custom = {f"custom:{row.key}": row.style for row in categories}
    if category.startswith("custom:") and category not in custom:
        raise HTTPException(422, "这个自建类别不属于这本书")
    expected = category_style(category, custom)
    if "style" in values and values["style"] != expected:
        raise HTTPException(422, f"这个类别用的是{STYLES[expected]}")
    if current is None or "category" in values or "style" in values:
        values["category"] = category
        values["style"] = expected
    if "status" in values and values["status"] not in STATUSES:
        raise HTTPException(422, "状态只能是现在要定、一句话就好或以后再说")

    parent_id = values.get("parent_id", current.parent_id if current is not None else None)
    if parent_id is not None:
        parent_id = parse_uuid(parent_id, "上级地方")
        if "parent_id" in values:
            values["parent_id"] = parent_id
        visited = {current.id} if current is not None else set()
        cursor = parent_id
        while cursor is not None:
            if cursor in visited:
                raise HTTPException(422, "不能属于自己或自己的下级地方")
            visited.add(cursor)
            parent = await session.get(WorldEntry, cursor)
            if parent is None or parent.book_id != book_id or parent.category != "世界与地图":
                raise HTTPException(422, "上级地方必须是这本书里世界与地图的条目")
            cursor = parent.parent_id
    if current is not None and category != "世界与地图":
        children = await session.scalar(
            select(func.count()).select_from(WorldEntry).where(WorldEntry.parent_id == current.id)
        )
        if children:
            raise HTTPException(422, "这个地方还有下级，先挪走下级再换类别")

    secret_id = values.get("secret_id", current.secret_id if current is not None else None)
    if secret_id is not None:
        secret_id = parse_uuid(secret_id, "信息差")
        secret = await session.get(Secret, secret_id)
        if secret is None or secret.book_id != book_id:
            raise HTTPException(422, "信息差不属于这本书")
        if "secret_id" in values:
            values["secret_id"] = secret_id
    return values


async def ensure_unwritten(session, target):
    if not isinstance(target, (StoryNode, Volume, PlotUnit)):
        return
    query = select(Chapter.id).where(
        Chapter.book_id == target.book_id, (Chapter.content != "") | (Chapter.status.in_(["drafting", "final"]))
    )
    if isinstance(target, StoryNode):
        query = query.where(Chapter.volume_id.in_(select(Volume.id).where(Volume.target_node_id == target.id)))
    elif isinstance(target, Volume):
        query = query.where(Chapter.volume_id == target.id)
    else:
        query = query.where(Chapter.unit_id == target.id)
    if await session.scalar(query.limit(1)):
        raise HTTPException(409, "这一处已经开写了，不能改")
