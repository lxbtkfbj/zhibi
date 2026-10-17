"""受限的编辑路径：只替换点中的字段或文字，不遍历任意对象属性。"""

import re
import uuid
from copy import deepcopy
from typing import Any

from app.library_config import STATUSES, STYLES
from app.models import Book, StoryNode, WorldEntry
from app.services.versions import EDITABLE_FIELDS, target_type_of

STALE_TEXT = "原文已经改过，没法只换这一段"
_RANGE = re.compile(r"(.+)@(\d+):(\d+)")
_LEVEL = re.compile(r"levels\.(\d+)\.(name|text)")
_STRING_LISTS = {"aliases", "tags", "key_events", "tropes", "techniques", "new_characters"}
_OBJECT_LISTS = {"thread_beats", "foreshadow_actions", "reveals"}


def _parse(path: str) -> tuple[str, tuple[int, int] | None]:
    if not isinstance(path, str) or not path:
        raise ValueError("修改路径无效")
    if "@" not in path:
        return path, None
    match = _RANGE.fullmatch(path)
    if match is None or "@" in match[1]:
        raise ValueError("修改路径无效")
    start, end = int(match[2]), int(match[3])
    if start > end:
        raise ValueError("选中文字的位置无效")
    return match[1], (start, end)


def _field(target: Any, path: str) -> tuple[str, Any]:
    """返回受限路径种类和地址；这里只做定位，绝不写入。"""
    kind = target_type_of(target)
    if isinstance(target, WorldEntry) and path.startswith("fields."):
        name = path.removeprefix("fields.")
        if not name:
            raise ValueError("卡片字段名不能为空")
        return "card", name
    if isinstance(target, WorldEntry) and path.startswith("levels."):
        match = _LEVEL.fullmatch(path)
        if match is None:
            raise ValueError("等级路径无效")
        index = int(match[1])
        if index >= len(target.levels or []):
            raise ValueError("这个等级不存在")
        return "level", (index, match[2])
    if isinstance(target, Book):
        if path not in {"story", "pitches", "secret_entry_id"}:
            raise ValueError("这一处不能修改")
        return "concept", path
    if isinstance(target, StoryNode):
        if path not in {"title", "text"}:
            raise ValueError("这一处不能修改")
        if target.segment is None:
            raise ValueError("这一篇还没规划，不能修改篇的内容")
        return "segment", path
    allowed = set(EDITABLE_FIELDS[kind])
    # 卷和篇的拓扑由专门接口管理，建议不能越过它们的校验直接改引用。
    allowed -= {"target_node_id", "reaches_node"}
    if path not in allowed:
        raise ValueError("这一处不能修改")
    return "column", path


def _read(target: Any, field: tuple[str, Any]) -> Any:
    kind, key = field
    if kind == "card":
        return next((row.get("value", "") for row in target.fields or [] if row.get("name") == key), "")
    if kind == "level":
        return target.levels[key[0]].get(key[1], "")
    if kind in {"concept", "segment"}:
        container = target.concept if kind == "concept" else target.segment
        default = [] if key == "pitches" else None if key == "secret_entry_id" else ""
        return (container or {}).get(key, default)
    return getattr(target, key)


def read_path(target: Any, path: str) -> Any:
    """读取指定字段的独立副本；带字符范围时只返回选中文字。"""
    name, span = _parse(path)
    value = _read(target, _field(target, name))
    if span is not None:
        if not isinstance(value, str):
            raise ValueError("只有文字才能选中一段修改")
        if span[1] > len(value):
            raise ValueError("选中文字的位置无效")
        value = value[span[0] : span[1]]
    return deepcopy(value)


def _validate(name: str, value: Any) -> Any:
    if name in {"locked", "reaches_node"}:
        valid = isinstance(value, bool)
    elif name in {"position", "chapter_count"}:
        valid = type(value) is int and value >= 0
    elif name in {"parent_id", "secret_id", "secret_entry_id"}:
        if value is None:
            return None
        try:
            parsed = uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("引用必须是有效的编号") from exc
        return str(parsed) if name == "secret_entry_id" else parsed
    elif name in _STRING_LISTS:
        valid = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif name in _OBJECT_LISTS:
        valid = isinstance(value, list) and all(isinstance(item, dict) for item in value)
    elif name in {"fields", "levels"}:
        keys = {"name", "value"} if name == "fields" else {"name", "text"}
        valid = isinstance(value, list) and all(
            isinstance(item, dict) and set(item) == keys and all(isinstance(item[key], str) for key in keys)
            for item in value
        )
        if valid and name == "fields":
            names = [item["name"] for item in value]
            valid = all(names) and len(set(names)) == len(names)
    elif name == "pitches":
        valid = isinstance(value, list) and all(
            isinstance(item, dict)
            and set(item) == {"name", "text", "titles"}
            and isinstance(item["name"], str)
            and isinstance(item["text"], str)
            and isinstance(item["titles"], list)
            and all(isinstance(title, str) for title in item["titles"])
            for item in value
        )
    else:
        valid = isinstance(value, str)
    if not valid:
        raise ValueError("这一处的内容类型不对")
    if name == "status" and value not in STATUSES:
        raise ValueError("设定状态无效")
    if name == "style" and value not in STYLES:
        raise ValueError("设定样式无效")
    return deepcopy(value)


def _write(target: Any, field: tuple[str, Any], value: Any) -> None:
    kind, key = field
    if kind in {"card", "level", "segment"}:
        if not isinstance(value, str):
            raise ValueError("这一处只能填写文字")
        value = deepcopy(value)
    else:
        value = _validate(key, value)
    if kind == "card":
        rows = deepcopy(target.fields or [])
        row = next((item for item in rows if item.get("name") == key), None)
        if row is None:
            rows.append({"name": key, "value": value})
        else:
            row["value"] = value
        target.fields = rows
    elif kind == "level":
        levels = deepcopy(target.levels)
        levels[key[0]][key[1]] = value
        target.levels = levels
    elif kind in {"concept", "segment"}:
        container = deepcopy(getattr(target, kind) or {})
        container[key] = value
        setattr(target, kind, container)
    else:
        setattr(target, key, value)


def set_field(target: Any, path: str, value: Any) -> tuple[Any, Any]:
    """设置一个可编辑值，返回该字段改前和改后的独立副本。"""
    name, span = _parse(path)
    if span is not None:
        return splice(target, path, value)
    field = _field(target, name)
    before = deepcopy(_read(target, field))
    _write(target, field, value)
    return before, deepcopy(_read(target, field))


def splice(target: Any, path: str, new_text: str, base: str | None = None) -> tuple[str, str]:
    """只换指定文字，返回所在字段的完整改前、改后文本。

    位置漂移时仅定位原文的第一次出现；找不到就拒绝，绝不扩大替换范围。
    """
    if not isinstance(new_text, str) or (base is not None and not isinstance(base, str)):
        raise ValueError("替换内容必须是文字")
    name, span = _parse(path)
    field = _field(target, name)
    before = _read(target, field)
    if not isinstance(before, str):
        raise ValueError("这一处不是文字，不能替换")
    if span is None:
        if base is not None and before != base:
            raise ValueError(STALE_TEXT)
        after = new_text
    else:
        start, end = span
        if base is None:
            if end > len(before):
                raise ValueError("选中文字的位置无效")
        elif end > len(before) or before[start:end] != base:
            start = before.find(base)
            if start < 0:
                raise ValueError(STALE_TEXT)
            end = start + len(base)
        after = before[:start] + new_text + before[end:]
    _write(target, field, after)
    return before, after
