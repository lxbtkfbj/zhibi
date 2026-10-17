"""设定与大纲的可编辑快照；版本随调用方事务一起提交。"""

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_config import CHARACTER_CATEGORY, SOURCES
from app.models import Book, Character, PlotUnit, StoryNode, Volume, WorldEntry
from app.models.library import SettingVersion

TARGET_MODELS = {
    "character": Character,
    "entry": WorldEntry,
    "concept": Book,
    "segment": StoryNode,
    "volume": Volume,
    "unit": PlotUnit,
}

# 不含 ID、归属、时间戳、写作进度及每章更新的角色状态。
EDITABLE_FIELDS = {
    "entry": (
        "category",
        "name",
        "aliases",
        "style",
        "status",
        "tags",
        "one_line",
        "content",
        "fields",
        "levels",
        "parent_id",
        "secret_id",
        "locked",
        "position",
    ),
    "character": tuple(column for _, column in CHARACTER_CATEGORY["fields"])
    + ("one_line", "status", "tags", "locked", "position"),
    "segment": ("title", "event", "status", "segment"),
    "volume": (
        "title",
        "summary",
        "chapter_count",
        "locked",
        "stage",
        "goal",
        "want",
        "pressure",
        "climax",
        "antagonist",
        "power_range",
        "thread_beats",
        "new_characters",
        "target_node_id",
        "reaches_node",
        "editor_note",
        "techniques",
    ),
    "unit": (
        "title",
        "summary",
        "chapter_count",
        "locked",
        "goal",
        "conflict",
        "climax",
        "outcome",
        "loop",
        "key_events",
        "thread_beats",
        "foreshadow_actions",
        "tropes",
        "resolution",
        "reveals",
        "editor_note",
        "techniques",
    ),
}

UUID_FIELDS = {"parent_id", "secret_id", "target_node_id"}


def target_type_of(target: Any) -> str:
    for target_type, model in TARGET_MODELS.items():
        if isinstance(target, model):
            return target_type
    raise ValueError("不支持的修改目标")


def _json_default(value: Any) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"快照中有不能保存的类型：{type(value).__name__}")


def json_copy(value: Any) -> Any:
    """切断嵌套 JSON 引用，同时将外键 UUID 转成 JSONB 可保存的字符串。"""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=_json_default))


def snapshot_of(target: Any) -> dict:
    target_type = target_type_of(target)
    if target_type == "concept":
        return json_copy(target.concept or {})
    return json_copy({field: getattr(target, field) for field in EDITABLE_FIELDS[target_type]})


def apply_snapshot(target: Any, snapshot: dict) -> None:
    """只恢复可编辑内容，绝不恢复 ID、书籍归属、写作状态或来源。"""
    target_type = target_type_of(target)
    if not isinstance(snapshot, dict):
        raise ValueError("版本快照必须是对象")
    values = json_copy(snapshot)
    if target_type == "concept":
        title = values.get("title")
        if title is not None and not isinstance(title, str):
            raise ValueError("定调中的书名必须是文字")
        target.concept = values
        # 与作者修改定调时相同：首页和导出使用的书名也跟着恢复。
        if title:
            target.title = title
        return
    if set(values) - set(EDITABLE_FIELDS[target_type]):
        raise ValueError("版本快照包含不可编辑的字段")
    # 先完整校验再赋值，坏外键不会留下半个快照。
    for field in UUID_FIELDS & values.keys():
        if values[field] is not None:
            try:
                values[field] = uuid.UUID(values[field])
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("版本快照中的引用无效") from exc
    for field, value in values.items():
        setattr(target, field, value)


async def record_version(
    session: AsyncSession,
    book_id: uuid.UUID,
    target_type: str,
    target: Any,
    source: str,
    note: str = "",
    *,
    before: dict | None = None,
    previous_source: str | None = None,
) -> SettingVersion:
    """新建记一版；首次修改记原文和改后两版；以后每改一次加一版。

    调用方应在修改前拿快照并锁住目标，避免修改本身丢失更新。本方法独立
    用事务级目标锁保护版本序号；既不提交，也不改变调用方持有的目标来源。
    """
    if target_type != target_type_of(target):
        raise ValueError("目标类型与对象不一致")
    if source not in SOURCES:
        raise ValueError("版本来源无效")
    owner_id = target.id if target_type == "concept" else target.book_id
    if owner_id != book_id:
        raise ValueError("目标不属于这本书")
    if target.id is None:
        await session.flush()
    lock_name = f"setting-version:{book_id}:{target_type}:{target.id}"
    lock_key = int.from_bytes(hashlib.sha256(lock_name.encode()).digest()[:8], "big", signed=True)
    with session.no_autoflush:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    # 查询会先 flush 本事务前一次的版本，连续调用同样不会得到重复编号。
    latest = await session.scalar(
        select(func.max(SettingVersion.version)).where(
            SettingVersion.book_id == book_id,
            SettingVersion.target_type == target_type,
            SettingVersion.target_id == target.id,
        )
    )
    number = latest or 0
    if not number and before is not None:
        original_source = previous_source or getattr(target, "source", "ai")
        # Book.source 的 new / imported 不是设定库的内容来源。
        if original_source not in SOURCES:
            original_source = "ai"
        session.add(
            SettingVersion(
                book_id=book_id,
                target_type=target_type,
                target_id=target.id,
                version=1,
                snapshot=json_copy(before),
                source=original_source,
                note="初版",
            )
        )
        number = 1
    version = SettingVersion(
        book_id=book_id,
        target_type=target_type,
        target_id=target.id,
        version=number + 1,
        snapshot=deepcopy(snapshot_of(target)),
        source=source,
        note=note,
    )
    session.add(version)
    await session.flush()
    return version
