"""设定库 AI 操作的中文上下文；展示文案与第三包任务 2 第 3 节一致。"""

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import format_concept
from app.library_config import BUILTIN_CATEGORIES, CHARACTER_CATEGORY, GENRE_DEFAULTS, LEGACY_ROLE_TYPES, STATUSES
from app.models import Book, Character, PlotUnit, SettingCategory, StoryNode, Volume, WorldEntry
from app.services.splice import read_path


def rewrite_mode(mode: str, instruction: str = "") -> str:
    return {
        "options": "给三种写法：稳妥、大胆、出格。稳妥的最贴近原来的意思，只把它写得更好；大胆的换一个更抓人的方向；出格的走一步险棋，但要和定调、底牌对得上。",
        "instruction": f"照作者的意思改：{instruction}。作者没提到的意思，原样保留。",
        "expand": "写细一点：把这一处展开写具体，原来的意思一个都不能丢。",
        "shorten": "精简一点：把这一处压短，留下最要紧的意思。",
    }[mode]


def genre_defaults(genre: str) -> str:
    groups = (
        (("玄幻", "仙侠", "修仙"), "玄幻、仙侠"),
        (("都市",), "都市"),
        (("无限", "网游", "游戏"), "无限流、网游"),
        (("悬疑", "灵异", "惊悚", "怪谈"), "悬疑、灵异"),
        (("历史", "宫斗", "官场", "宅斗"), "历史、宫斗、官场"),
    )
    chosen = next((name for words, name in groups if any(word in genre for word in words)), None)
    lines = [f"这本书的题材：{genre or '没写'}", "这类书常建的条目（只是起点，按定调增减）："]
    for group, entries in GENRE_DEFAULTS.items():
        if chosen and group != chosen:
            continue
        if not chosen:
            lines.append(f"【{group}】")
        lines.extend(f"- {category} · {name}（{STATUSES[status]}）" for category, name, status in entries)
    return "\n".join(lines)


@dataclass
class LibraryContext:
    book: Book
    characters: list[Character]
    entries: list[WorldEntry]
    categories: list[dict]
    nodes: list[StoryNode]
    volumes: list[Volume]
    units: list[PlotUnit]

    @property
    def targets(self) -> list[Character | WorldEntry]:
        return [
            target
            for category in self.categories
            for target in (self.characters if category["key"] == "角色卡片" else self.entries)
            if isinstance(target, Character) or target.category == category["key"]
        ]

    def category(self, target: Character | WorldEntry) -> dict:
        key = "角色卡片" if isinstance(target, Character) else target.category
        return next(category for category in self.categories if category["key"] == key)

    @property
    def concept(self) -> str:
        concept = self.book.concept or {}
        if not concept.get("story"):
            return (
                format_concept(concept)
                if any(concept.get(key) for key in ("logline", "synopsis", "hook", "core_conflict"))
                else (f"点子：{self.book.idea}" if self.book.idea else "（还没有定调）")
            )
        lines = [concept["story"]]
        if self.concept_ending:
            lines.append(f"全书结局：{self.concept_ending}")
        secret_id = concept.get("secret_entry_id")
        secret = next((entry for entry in self.entries if str(entry.id) == str(secret_id)), None)
        if secret is not None:
            lines.append(f"底牌（只有作者和编辑部知道）：{secret.content or secret.one_line}")
        return "\n".join(lines)

    @property
    def concept_ending(self) -> str:
        """作者写在概念里的全书结局；已经有结局节点时以节点为准。"""
        if any(node.kind == "ending" for node in self.nodes):
            return ""
        return str((self.book.concept or {}).get("ending") or "").strip()

    @property
    def library(self) -> str:
        lines = []
        for category in self.categories:
            targets = [target for target in self.targets if self.category(target)["key"] == category["key"]]
            if not targets:
                continue
            lines.append(f"【{category['name']}】" + ("（自建类别）" if not category.get("builtin", True) else ""))
            for target in targets:
                label = target.name
                if isinstance(target, Character) and target.role_type:
                    label += f"（{LEGACY_ROLE_TYPES.get(target.role_type, target.role_type)}）"
                if isinstance(target, WorldEntry) and target.parent_id:
                    parent = next((entry for entry in self.entries if entry.id == target.parent_id), None)
                    if parent:
                        label += f"（属于{parent.name}）"
                if target.status == "later":
                    label += "（以后再说）"
                if target.locked:
                    label += "（已锁）"
                if target.one_line:
                    label += f"：{target.one_line}"
                lines.append(f"- {label}")
        return "\n".join(lines)

    def _arcs(self) -> list[StoryNode]:
        return [
            node
            for node in self.nodes
            if node.kind != "opening" and not (node.kind == "ending" and node.segment is None)
        ]

    def segment_number(self, target: StoryNode) -> int:
        return next((i for i, node in enumerate(self._arcs(), 1) if node.id == target.id), 1)

    def target_name(self, target: Any) -> str:
        if isinstance(target, Book):
            return "定调"
        if isinstance(target, StoryNode):
            return (target.segment or {}).get("title", target.title)
        return target.name if isinstance(target, (Character, WorldEntry)) else target.title

    def target_heading(self, target: Any) -> str:
        name = self.target_name(target)
        if isinstance(target, Book):
            return "定调"
        if isinstance(target, StoryNode):
            return f"大纲 · 第 {self.segment_number(target)} 篇「{name}」"
        if isinstance(target, Volume):
            return f"大纲 · 第 {target.index} 卷「{name}」"
        if isinstance(target, PlotUnit):
            return f"大纲 · 单元「{name}」"
        return f"{self.category(target)['name']} · {name}"

    def entry_full_text(self, target: Any) -> str:
        heading = self.target_heading(target)
        if isinstance(target, Book):
            return f"定调：{(target.concept or {}).get('story', '')}"
        if isinstance(target, StoryNode):
            return f"{heading}：{(target.segment or {}).get('text', '')}"
        if isinstance(target, (Volume, PlotUnit)):
            return f"{heading}：{target.summary}"
        lines = [heading]
        if isinstance(target, Character):
            for label, column in CHARACTER_CATEGORY["fields"]:
                value = getattr(target, column, "")
                if value:
                    lines.append(f"{label}：{'、'.join(value) if isinstance(value, list) else value}")
            lines.extend(f"{label}：{value}" for label, value in (target.extra or {}).items() if value)
            if target.want:
                lines.append(f"此刻想要：{target.want}")
        elif target.style == "ladder":
            lines.extend([f"总说明：{target.content or ''}", "各级（从低到高）："])
            lines.extend(f"{i}. {level['name']}：{level['text']}" for i, level in enumerate(target.levels or [], 1))
        elif target.style == "card":
            lines.extend(f"{field['name']}：{field['value']}" for field in target.fields or [])
        else:
            lines.append(f"一句话：{target.one_line or ''}")
            lines.extend(f"{field['name']}：{field['value']}" for field in target.fields or [] if field.get("value"))
            lines.append(target.content or "")
        return "\n".join(lines)

    @property
    def library_full(self) -> str:
        return "\n\n".join(self.entry_full_text(target) for target in self.targets)

    def related(self, target: Any) -> str:
        text = self.entry_full_text(target)
        matches = []
        for order, other in enumerate(self.targets):
            if type(other) is type(target) and other.id == target.id:
                continue
            positions = [text.find(name) for name in [other.name, *(other.aliases or [])] if name and name in text]
            if positions:
                matches.append((min(positions), order, other))
        matches.sort(key=lambda match: match[:2])
        return "\n\n".join(self.entry_full_text(item[2]) for item in matches[:8]) or "（没有）"

    def part_label(self, target: Any, path: str) -> str:
        field = path.split("@", 1)[0]
        if isinstance(target, Book):
            part = "一段话"
        elif isinstance(target, StoryNode):
            part = "篇名" if field == "title" else "一段话"
        elif isinstance(target, (Volume, PlotUnit)):
            part = "一段话"
        elif field.startswith("fields."):
            part = field.removeprefix("fields.")
        elif field.startswith("extra."):
            part = field.removeprefix("extra.")
        elif match := re.fullmatch(r"levels\.(\d+)\.(name|text)", field):
            index = int(match[1])
            part = f"第 {index + 1} 级「{target.levels[index]['name']}」的{'名称' if match[2] == 'name' else '介绍'}"
        elif isinstance(target, Character):
            part = dict((column, label) for label, column in CHARACTER_CATEGORY["fields"]).get(field, field)
            if field == "name":
                part = "名称"
            elif field == "one_line":
                part = "一句话"
        else:
            part = {
                "content": "总说明" if target.style == "ladder" else "一段话",
                "one_line": "一句话",
                "name": "名称",
                "aliases": "别名",
            }.get(field, field)
        return part + ("里选中的一句" if "@" in path else "")

    def target_label(self, target: Any, path: str) -> str:
        return f"{self.target_heading(target)} · {self.part_label(target, path)}"

    def category_hint(self, target: Any) -> str:
        if isinstance(target, Book):
            return "一段话说清这本小说主要讲什么故事"
        if isinstance(target, (StoryNode, Volume, PlotUnit)):
            return "这一层的一段话要说清的事，见大纲的写法"
        return self.category(target)["hint"]

    @property
    def genre_defaults(self) -> str:
        return genre_defaults(self.book.genre or "")

    @property
    def outline(self) -> str:
        lines = []
        if any(node.segment is not None for node in self.nodes):
            for i, node in enumerate(self._arcs(), 1):
                plan = node.segment or {}
                lines.append(f"第 {i} 篇「{plan.get('title', node.title)}」：{plan.get('text') or node.event}")
                lines.extend(
                    f"  第 {volume.index} 卷「{volume.title}」：{volume.summary}"
                    for volume in self.volumes
                    if volume.target_node_id == node.id
                )
        elif self.volumes:
            lines.append("第 1 篇「全书」：")
            lines.extend(f"  第 {volume.index} 卷「{volume.title}」：{volume.summary}" for volume in self.volumes)
        ending = next((node for node in reversed(self.nodes) if node.kind == "ending"), None)
        if ending:
            lines.append(f"结局：{ending.event}")
        elif self.concept_ending:
            lines.append(f"结局：{self.concept_ending}")
        return "\n".join(lines) or "（还没有大纲）"

    def scope(self, target: Any | None = None) -> str:
        return (
            f"只查这一条：{self.target_heading(target)}；需要时对照别的条目。"
            if target is not None
            else "查整个设定库。"
        )

    def find_target(self, name: str) -> Character | WorldEntry | None:
        if not name:
            return None
        tests = (
            lambda target: target.name == name,
            lambda target: name in (target.aliases or []),
            lambda target: name in target.name,
        )
        return next((target for test in tests for target in self.targets if test(target)), None)

    def route_path(self, target: Character | WorldEntry, part: str, quote: str = "") -> str:
        field = {"名称": "name", "一句话": "one_line", "一段话": "content", "总说明": "content"}.get(part)
        if isinstance(target, Character):
            columns = dict(CHARACTER_CATEGORY["fields"] + CHARACTER_CATEGORY["state_fields"])
            field = columns.get(part, part if part in columns.values() else field)
            # 找到了每章状态时保留真正的目标，让 rewrite 返回 422，不能悄悄改姓名。
            if field in dict(CHARACTER_CATEGORY["state_fields"]).values():
                return field
            if field in {None, "content"}:
                field = next(
                    (
                        column
                        for _, column in CHARACTER_CATEGORY["fields"]
                        if column != "aliases" and getattr(target, column, "")
                    ),
                    "name",
                )
        elif target.style == "card":
            names = set(self.category(target).get("fields", [])) | {item["name"] for item in target.fields or []}
            if part in names:
                field = f"fields.{part}"
            elif field is None or field == "content":
                field = next((f"fields.{item['name']}" for item in target.fields or [] if item["value"]), "name")
        elif target.style == "ladder":
            # 长级名优先，避免「真灵海」错误命中前面的「灵海」。
            for i, level in sorted(enumerate(target.levels or []), key=lambda item: -len(item[1]["name"])):
                if level["name"] and level["name"] in part:
                    field = f"levels.{i}.{'name' if '名称' in part or '名字' in part else 'text'}"
                    break
        field = field or "content"
        current = read_path(target, field)
        if quote and isinstance(current, str) and quote in current:
            start = current.index(quote)
            return f"{field}@{start}:{start + len(quote)}"
        return field


async def load_context(session: AsyncSession, book: Book) -> LibraryContext:
    def sort_key(row):
        return list(STATUSES).index(row.status), row.position, row.created_at, str(row.id)

    characters = sorted(await session.scalars(select(Character).where(Character.book_id == book.id)), key=sort_key)
    entries = sorted(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id)), key=sort_key)
    custom = await session.scalars(
        select(SettingCategory)
        .where(SettingCategory.book_id == book.id)
        .order_by(SettingCategory.position, SettingCategory.created_at, SettingCategory.id)
    )
    categories = [{**spec, "builtin": True} for spec in [CHARACTER_CATEGORY, *BUILTIN_CATEGORIES]]
    categories.extend(
        {
            "key": f"custom:{row.key}",
            "name": row.name,
            "style": row.style,
            "fields": row.fields,
            "hint": row.hint,
            "builtin": False,
        }
        for row in custom
    )
    nodes = list(
        await session.scalars(
            select(StoryNode).where(StoryNode.book_id == book.id).order_by(StoryNode.position, StoryNode.id)
        )
    )
    volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index)))
    units = list(await session.scalars(select(PlotUnit).where(PlotUnit.book_id == book.id).order_by(PlotUnit.index)))
    return LibraryContext(book, characters, entries, categories, nodes, volumes, units)


def existing_text(ctx, exclude=()):
    targets = [target for target in ctx.targets if target.id not in {getattr(item, "id", item) for item in exclude}]
    if not targets:
        return ""
    lines, compact = ["【设定库里已经有的】"], []
    for target in targets:
        full = ctx.entry_full_text(target)
        if not compact and len("\n\n".join([*lines, full])) <= 8000:
            lines.append(full)
        else:
            compact.append(f"- {target.name}：{target.one_line}")
    text = "\n\n".join(lines)
    if compact:
        text += "\n（下面这些只列名字和一句话）\n" + "\n".join(compact)
    return text
