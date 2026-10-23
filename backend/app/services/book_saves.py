"""整本书的存档（设计说明 9.13「第二批：存档」）。

照 git 的办法：书里每一行转成规范化 JSON（键排好序），按 sha256 存进 book_objects，同样的内容只存一份；
每张表一张清单 {行 id: hash}，清单本身也存成对象；一档（book_saves.tree）就是「表名 → 清单的 hash」。
章的正文单独存成一个对象，章那一行里只记它的 hash，章从「写作中」变成「定稿」时不用把正文再存一遍。

存档只往后加，不删、不分叉；回到旧的一档也是在最后加一条「回到了『X』」。
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_config import CHARACTER_CATEGORY
from app.models import (
    Book,
    BookObject,
    BookSave,
    Chapter,
    Character,
    Foreshadowing,
    Job,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    SettingCandidate,
    SettingCategory,
    SettingSuggestion,
    StoryNode,
    StoryThread,
    TeardownSource,
    Volume,
    WorldEntry,
)

log = logging.getLogger(__name__)

# 算书里东西的表；插回去时按这个顺序（上层在前），删的时候反过来（下层在前）
TABLES = [
    StoryNode,
    Secret,
    Character,
    WorldEntry,
    Foreshadowing,
    StoryThread,
    Volume,
    PlotUnit,
    Chapter,
    SettingCategory,
    SettingSuggestion,
    Relationship,
    NodeAnchor,
]
MODELS = {model.__tablename__: model for model in TABLES}
BOOK_SKIP = ("id", "created_at", "updated_at")

ACTOR_NAMES = {
    "author": "你",
    "chief": "主编",
    "lorekeeper": "设定师",
    "writer": "写手",
    "reviewer": "审稿",
    "system": "编辑部",
}
GROUPS = ("简介", "设定", "大纲", "正文", "待处理", "编辑部记的")
TABLE_GROUP = {
    "books": "简介",
    "characters": "设定",
    "world_entries": "设定",
    "relationships": "设定",
    "setting_categories": "设定",
    "story_nodes": "大纲",
    "volumes": "大纲",
    "plot_units": "大纲",
    "chapters": "大纲",
    "setting_suggestions": "待处理",
    "foreshadowings": "编辑部记的",
    "secrets": "编辑部记的",
    "story_threads": "编辑部记的",
    "node_anchors": "编辑部记的",
}


# ---------- 规范化与 hash ----------


def plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=plain)


def digest(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def row_data(model, mapping) -> dict:
    skip = BOOK_SKIP if model is Book else ("updated_at",)
    # 没置顶的不记这一栏：加这一栏以前存的档，不会因为它对不上而算成每个人都改了
    if model is Book and "settings" in mapping:
        mapping = {**mapping, "settings": {k: v for k, v in (mapping["settings"] or {}).items() if k != "other_rules"}}
    return {
        key: plain(value)
        for key, value in mapping.items()
        if key not in skip and not (key == "pinned_at" and value is None) and not (key == "teardown" and not value)
    }


@dataclass
class Snapshot:
    """读出来的整本书：每张表 {行 id: hash}，每个 hash 对应的对象，和每一行的内容（给比对用）。"""

    rows: dict[str, dict[str, str]] = field(default_factory=dict)
    data: dict[str, dict[str, dict]] = field(default_factory=dict)
    objects: dict[str, tuple[str, Any]] = field(default_factory=dict)
    tree: dict[str, str] = field(default_factory=dict)
    chapters_final: int = 0

    def put(self, kind: str, data: Any) -> str:
        h = digest(data)
        self.objects[h] = (kind, data)
        return h

    def add(self, table: str, row_id: str, data: dict) -> None:
        self.rows.setdefault(table, {})[row_id] = self.put("row", data)
        self.data.setdefault(table, {})[row_id] = data

    def text_of(self, h: str) -> str:
        found = self.objects.get(h)
        return found[1] if found else ""


def chapter_row(mapping, snap: Snapshot | None = None) -> dict:
    """章这一行：正文换成正文对象的 hash。"""
    data = row_data(Chapter, mapping)
    content = data.get("content") or ""
    data["content"] = snap.put("text", content) if snap is not None else digest(content)
    return data


async def read_state(session: AsyncSession, book_id: uuid.UUID) -> Snapshot:
    snap = Snapshot()
    table = Book.__table__
    book = (await session.execute(select(table).where(table.c.id == book_id))).mappings().one_or_none()
    if book is None:
        raise HTTPException(404, "书不存在")
    snap.add("books", str(book_id), row_data(Book, book))
    for model in TABLES:
        t = model.__table__
        snap.rows.setdefault(t.name, {})
        snap.data.setdefault(t.name, {})
        for mapping in (await session.execute(select(t).where(t.c.book_id == book_id))).mappings():
            data = chapter_row(mapping, snap) if model is Chapter else row_data(model, mapping)
            snap.add(t.name, data["id"], data)
            if model is Chapter and data.get("status") == "final":
                snap.chapters_final = max(snap.chapters_final, data.get("index") or 0)
    for name, manifest in snap.rows.items():
        snap.tree[name] = snap.put("manifest", manifest)
    return snap


async def current_row_hash(session: AsyncSession, table: str, row_id: str) -> str | None:
    """这一行现在的 hash；没有这一行就是 None。"""
    model = Book if table == "books" else MODELS[table]
    t = model.__table__
    mapping = (await session.execute(select(t).where(t.c.id == uuid.UUID(row_id)))).mappings().one_or_none()
    if mapping is None:
        return None
    data = chapter_row(mapping) if model is Chapter else row_data(model, mapping)
    return digest(data)


async def load_objects(session: AsyncSession, book_id: uuid.UUID, hashes) -> dict[str, Any]:
    wanted = list({h for h in hashes if h})
    found: dict[str, Any] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        rows = await session.execute(
            select(BookObject.hash, BookObject.data).where(BookObject.book_id == book_id, BookObject.hash.in_(chunk))
        )
        found.update(dict(rows.all()))
    return found


async def store_objects(session: AsyncSession, book_id: uuid.UUID, snap: Snapshot, hashes) -> None:
    values = [
        {"book_id": book_id, "hash": h, "kind": snap.objects[h][0], "data": snap.objects[h][1]}
        for h in dict.fromkeys(hashes)
        if h in snap.objects
    ]
    for start in range(0, len(values), 500):
        await session.execute(
            pg_insert(BookObject)
            .values(values[start : start + 500])
            .on_conflict_do_nothing(index_elements=["book_id", "hash"])
        )


async def manifests(session: AsyncSession, book_id: uuid.UUID, tree: dict) -> dict[str, dict[str, str]]:
    found = await load_objects(session, book_id, tree.values())
    return {name: dict(found.get(h) or {}) for name, h in tree.items() if name == "books" or name in MODELS}


def row_hashes_with_text(snap: Snapshot, table: str, row_hash: str) -> list[str]:
    """一行要存的对象：这一行，章再加上它的正文。"""
    out = [row_hash]
    if table == "chapters":
        kind, data = snap.objects[row_hash]
        if data.get("content"):
            out.append(data["content"])
    return out


async def lock_saves(session: AsyncSession, book_id: uuid.UUID) -> None:
    """同一本书同时只能有一个在存、在回：工作进程和网页后台都会调到，用数据库的事务锁。"""
    name = f"book-save:{book_id}"
    key = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def latest_save(session: AsyncSession, book_id: uuid.UUID) -> BookSave | None:
    return await session.scalar(
        select(BookSave).where(BookSave.book_id == book_id).order_by(BookSave.id.desc()).limit(1)
    )


# ---------- 看得懂的名字和栏目 ----------

CHAR_LABELS = {
    **{column: label for label, column in CHARACTER_CATEGORY["fields"]},
    **{column: label for label, column in CHARACTER_CATEGORY["state_fields"]},
    "one_line": "一句话",
    "tags": "标签",
    "pinned_at": "置顶",
    "locked": "锁住",
    "position": "顺序",
    "source": "来源",
    "status": "写到多细",
    "first_appearance_chapter": "第一次出场",
}
FIELD_LABELS = {
    "books": {
        "title": "书名",
        "idea": "点子",
        "genre": "类别",
        "concept": "定调",
        "protagonist": "主角卡",
        "world": "世界",
        "spine": "主线",
        "setup_progress": "开书进度",
        "card_layouts": "设定的栏目",
        "settings": "本书设置",
        "status": "书的状态",
        "trial_read_done": "试读做过了",
        "style_reference": "文风参考",
        "source": "来源",
    },
    "characters": CHAR_LABELS,
    "world_entries": {
        "category": "类别",
        "name": "名称",
        "content": "内容",
        "style": "样式",
        "status": "写到多细",
        "tags": "标签",
        "one_line": "一句话",
        "aliases": "别名",
        "fields": "栏目",
        "levels": "各级",
        "parent_id": "上级",
        "secret_id": "对应的信息差",
        "locked": "锁住",
        "source": "来源",
        "position": "顺序",
        "created_chapter": "第几章记下的",
    },
    "relationships": {
        "source_id": "谁",
        "target_id": "和谁",
        "kind": "关系",
        "description": "说明",
        "since_chapter": "从第几章起",
    },
    "setting_categories": {
        "key": "代号",
        "name": "名称",
        "style": "样式",
        "fields": "栏目",
        "hint": "说明",
        "position": "顺序",
    },
    "story_nodes": {
        "position": "顺序",
        "kind": "种类",
        "title": "标题",
        "event": "一段话",
        "prerequisite": "之前得先有",
        "consequence": "之后变成",
        "segment": "这一篇的规划",
        "volume": "在第几卷",
        "status": "钉住没有",
        "origin": "谁写的",
        "updated_by_volume": "哪一卷改过",
        "editor_note": "编辑批注",
        "techniques": "手法",
    },
    "volumes": {
        "index": "第几卷",
        "title": "标题",
        "stage": "舞台",
        "summary": "一段话",
        "goal": "目标",
        "locked": "锁住",
        "want": "想做成什么",
        "pressure": "卷首处境",
        "climax": "高潮",
        "antagonist": "对手",
        "power_range": "实力从哪到哪",
        "thread_beats": "推进哪些线索",
        "new_characters": "新登场的人",
        "chapter_count": "章数",
        "target_node_id": "走向哪一篇",
        "reaches_node": "走到那一篇",
        "editor_note": "编辑批注",
        "techniques": "手法",
        "status": "进度",
        "recap": "卷回顾",
    },
    "plot_units": {
        "volume_id": "在哪一卷",
        "index": "第几个单元",
        "title": "标题",
        "chapter_count": "章数",
        "summary": "一段话",
        "locked": "锁住",
        "goal": "目标",
        "conflict": "冲突",
        "climax": "高潮",
        "outcome": "结果",
        "loop": "核心循环",
        "key_events": "关键事件",
        "thread_beats": "推进哪些线索",
        "foreshadow_actions": "伏笔动作",
        "tropes": "套路",
        "resolution": "破局",
        "reveals": "揭晓",
        "editor_note": "编辑批注",
        "techniques": "手法",
        "plan_issues": "章纲的问题",
        "status": "进度",
        "recap": "单元回顾",
    },
    "chapters": {
        "volume_id": "在哪一卷",
        "unit_id": "在哪个单元",
        "index": "第几章",
        "title": "标题",
        "outline": "章纲",
        "content": "正文",
        "word_count": "字数",
        "summary": "摘要",
        "review": "审稿结果",
        "materials": "写之前备的资料",
        "bible_changes": "记进设定的变化",
        "attempts": "重写次数",
        "source": "来源",
        "status": "进度",
    },
    "author_requirements": {
        "text": "原话",
        "source": "从哪来",
        "scope": "有效范围",
        "chapter_index": "管第几章",
        "volume_index": "管第几卷",
        "message_id": "哪句话里说的",
    },
    "setting_suggestions": {
        "kind": "种类",
        "target_type": "对象",
        "target_id": "对象",
        "title": "建议",
        "payload": "内容",
        "origin": "从哪来",
        "status": "处理了没有",
        "resolved_at": "什么时候处理的",
    },
    "foreshadowings": {
        "seq": "编号",
        "kind": "种类",
        "node_id": "在哪一篇",
        "description": "内容",
        "span": "跨度",
        "plant_plan": "打算怎么埋",
        "payoff_plan": "打算怎么收",
        "plant_volume": "第几卷埋",
        "payoff_volume": "第几卷收",
        "status": "进度",
        "planted_chapter": "第几章埋下",
        "hint_chapters": "提醒过的章",
        "resolved_chapter": "第几章收了",
    },
    "secrets": {
        "seq": "编号",
        "title": "标题",
        "truth": "真相",
        "knowers": "谁知道",
        "reader_knows": "读者知道多少",
        "reveal_plan": "打算怎么揭开",
        "node_id": "在哪一篇揭开",
        "status": "进度",
        "created_chapter": "第几章记下的",
    },
    "story_threads": {
        "index": "顺序",
        "name": "名称",
        "kind": "种类",
        "summary": "一段话",
        "characters": "人物",
        "beats": "各卷节拍",
    },
    "node_anchors": {"node_id": "哪一篇", "character_id": "谁", "kind": "种类", "note": "说明"},
}
# 嵌在 JSON 里的英文键（定调、篇的规划、章纲……）换成看得懂的名字；认不出的照原样
KEY_LABELS = {
    "title": "标题",
    "text": "一段话",
    "name": "名称",
    "value": "内容",
    "summary": "一段话",
    "pitch": "卖点",
    "hook": "钩子",
    "ending": "结局",
    "genre": "类别",
    "tags": "标签",
    "tone": "基调",
    "goal": "目标",
    "scenes": "场景",
    "conflict": "冲突",
    "payoff": "爽点",
    "characters": "出场人物",
    "foreshadowing": "伏笔",
    "target_length": "全书篇幅",
    "chapter_words": "每章字数",
    "selling_points": "卖点",
    "protagonist": "主角",
    "golden_finger": "金手指",
    "core_loop": "核心循环",
    "audience": "目标读者",
    "logline": "一句话故事",
    "secret": "底牌",
    # 新书页上叫「简介」
    "story": "简介",
}
# 前后对照里不值得给作者看的小改动
QUIET = {"顺序", "来源", "写到多细", "谁写的", "哪一卷改过", "字数", "重写次数"}


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return "、".join(value)
        return "\n".join(text_of(item) for item in value)
    if isinstance(value, dict):
        if set(value) <= {"name", "value"} and "name" in value:
            return f"{value.get('name')}：{text_of(value.get('value'))}"
        lines = []
        for key, item in value.items():
            shown = text_of(item)
            if shown:
                lines.append(
                    f"{KEY_LABELS.get(key, key)}：{shown}"
                    if "\n" not in shown
                    else f"{KEY_LABELS.get(key, key)}：\n{shown}"
                )
        return "\n".join(lines)
    return str(value)


class Namer:
    """给一行起看得懂的名字：主角、第 2 篇「……」、第 12 章「……」。"""

    def __init__(self, *sources: dict[str, dict[str, dict]]):
        self.data: dict[str, dict[str, dict]] = {}
        for source in sources:
            for table, rows in source.items():
                self.data.setdefault(table, {}).update(rows)
        nodes = sorted(self.data.get("story_nodes", {}).values(), key=lambda n: n.get("position") or 0)
        arcs = [
            n
            for n in nodes
            if n.get("kind") != "opening" and not (n.get("kind") == "ending" and n.get("segment") is None)
        ]
        self.arc_number = {n["id"]: i for i, n in enumerate(arcs, 1)}

    def char(self, row_id) -> str:
        return (self.data.get("characters", {}).get(row_id) or {}).get("name") or "某人"

    def name(self, table: str, data: dict) -> str:
        quote = lambda title: f"「{title}」" if title else ""  # noqa: E731
        if table == "books":
            return "这本书"
        if table == "characters" or table == "world_entries":
            return data.get("name") or "（没名字）"
        if table == "relationships":
            return f"{self.char(data.get('source_id'))}和{self.char(data.get('target_id'))}的关系"
        if table == "setting_categories":
            return f"类别{quote(data.get('name'))}"
        if table == "story_nodes":
            if data.get("kind") == "opening":
                return "开篇"
            if data.get("kind") == "ending" and data.get("segment") is None:
                return "全书结局"
            title = (data.get("segment") or {}).get("title") if data.get("segment") is not None else data.get("title")
            number = self.arc_number.get(data.get("id"))
            return (f"第 {number} 篇" if number else "一篇") + quote(title)
        if table == "volumes":
            return f"第 {data.get('index')} 卷{quote(data.get('title'))}"
        if table == "plot_units":
            volume = self.data.get("volumes", {}).get(data.get("volume_id")) or {}
            head = f"第 {volume['index']} 卷" if volume.get("index") else ""
            return f"{head}单元 {data.get('index')}{quote(data.get('title'))}"
        if table == "chapters":
            return f"第 {data.get('index')} 章{quote(data.get('title'))}"
        if table == "author_requirements":
            words = data.get("text") or ""
            return f"写作要求「{words[:24]}{'……' if len(words) > 24 else ''}」"
        if table == "setting_suggestions":
            words = data.get("title") or ""
            return f"建议「{words[:24]}{'……' if len(words) > 24 else ''}」"
        if table == "foreshadowings":
            return f"{data.get('kind') or '伏笔'} F{data.get('seq')}"
        if table == "secrets":
            return f"信息差 S{data.get('seq')}{quote(data.get('title'))}"
        if table == "story_threads":
            return f"线索{quote(data.get('name'))}"
        if table == "node_anchors":
            return f"{self.char(data.get('character_id'))}的人物锚点"
        return table


def parts(table: str, data: dict | None, texts=None) -> dict[str, str]:
    """一行拆成看得懂的几栏 {栏目名: 字}。texts：正文对象 hash → 正文。"""
    if not data:
        return {}
    labels = FIELD_LABELS.get(table, {})
    out: dict[str, str] = {}
    for key, value in data.items():
        if key in ("id", "book_id", "created_at"):
            continue
        if table == "books" and key == "settings" and isinstance(value, dict):
            value = {name: item for name, item in value.items() if name != "other_rules"}
        if table == "characters" and key == "extra":
            for name, item in (value or {}).items():
                out[name] = text_of(item)
            continue
        if table == "world_entries" and key == "fields":
            for item in value or []:
                if isinstance(item, dict) and item.get("name"):
                    out[item["name"]] = text_of(item.get("value"))
            continue
        if table == "books" and key == "concept" and isinstance(value, dict):
            for name, item in value.items():
                out[f"定调 · {KEY_LABELS.get(name, name)}"] = text_of(item)
            continue
        if table == "story_nodes" and key == "segment" and isinstance(value, dict):
            for name, item in value.items():
                out[f"规划 · {KEY_LABELS.get(name, name)}"] = text_of(item)
            continue
        if table == "chapters" and key == "content":
            out["正文"] = texts(value) if texts else value
            continue
        out[labels.get(key, key)] = text_of(value)
    return out


def changed_labels(table: str, before: dict | None, after: dict | None) -> list[str]:
    old, new = parts(table, before), parts(table, after)
    return [label for label in dict.fromkeys([*old, *new]) if old.get(label, "") != new.get(label, "")]


def group_of(table: str, labels: list[str], after: dict | None) -> str:
    if table == "chapters":
        if any(label in ("正文", "摘要", "审稿结果", "记进设定的变化", "进度") for label in labels):
            return "正文"
        if after and labels == [] and after.get("status") == "final":
            return "正文"
    return TABLE_GROUP.get(table, "编辑部记的")


def summarize(before_rows, after_rows, before_data, after_data, namer: Namer) -> dict:
    """和上一档比改了哪些行：给存档列表用。"""
    items, finished = [], []
    for table in ["books", *(m.__tablename__ for m in TABLES)]:
        old, new = before_rows.get(table, {}), after_rows.get(table, {})
        for row_id in dict.fromkeys([*old, *new]):
            if old.get(row_id) == new.get(row_id):
                continue
            b, a = before_data.get(old.get(row_id)), after_data.get(table, {}).get(row_id)
            op = "add" if b is None and row_id not in old else "del" if row_id not in new else "mod"
            labels = changed_labels(table, b, a) if op == "mod" else []
            if op == "mod" and not labels:
                labels = ["其他"]
            items.append(
                {
                    "table": table,
                    "id": row_id,
                    "op": op,
                    "group": group_of(table, labels, a),
                    "name": namer.name(table, a or b or {}),
                    "fields": [label for label in labels if label not in QUIET][:4] or labels[:1],
                }
            )
            if table == "chapters" and a and a.get("status") == "final" and (b or {}).get("status") != "final":
                finished.append({"index": a.get("index"), "title": a.get("title") or ""})
    finished.sort(key=lambda item: item["index"] or 0)
    order = {name: i for i, name in enumerate(GROUPS)}
    items.sort(key=lambda item: order.get(item["group"], 99))
    return {"items": items[:80], "more": max(0, len(items) - 80), "finished": finished}


def chapters_span(finished: list[dict]) -> str:
    if len(finished) == 1:
        one = finished[0]
        return f"第 {one['index']} 章" + (f"「{one['title']}」" if one["title"] else "")
    return f"第 {finished[0]['index']}–{finished[-1]['index']} 章"


def describe(summary: dict, limit: int = 3) -> str:
    """一档改了什么，一小句：改了主角（身世）、第 2 篇；新建了张三"""
    if summary.get("finished"):
        return "写完" + chapters_span(summary["finished"])
    items = [i for i in summary.get("items", []) if i["group"] != "编辑部记的"] or summary.get("items", [])
    pieces = []
    for op, verb in (("mod", "改了"), ("add", "新建了"), ("del", "删了")):
        rows = [i for i in items if i["op"] == op]
        if not rows:
            continue
        shown = []
        for i in rows[:limit]:
            fields = [f for f in i["fields"] if f != "其他"][:2]
            shown.append(i["name"] + (f"（{'、'.join(fields)}）" if op == "mod" and fields else ""))
        pieces.append(verb + "、".join(shown) + (f" 等 {len(rows)} 处" if len(rows) > limit else ""))
    return "；".join(pieces) or "没有改动"


def count_of(summary: dict) -> int:
    return len(summary.get("items", [])) + summary.get("more", 0)


# ---------- 存一档 ----------


async def checkpoint(
    session: AsyncSession,
    book_id: uuid.UUID,
    actor: str = "system",
    title: str | None = None,
    *,
    kind: str = "auto",
    force: bool = False,
    restored_from: int | None = None,
    lead: str | None = None,
) -> BookSave | None:
    """存一档。跟最新一档一模一样就不存（force 例外：作者手动存、回到某一档）。
    title 不给就按改了什么起：lead 是开头（「设定师照你的话」），后面接「改了主角（身世）」。
    调用方先把自己的改动提交了；这里会提交。"""
    await session.commit()
    await lock_saves(session, book_id)
    snap = await read_state(session, book_id)
    latest = await latest_save(session, book_id)
    if latest is not None and latest.tree == snap.tree and not force:
        await session.commit()
        return None
    before_rows = await manifests(session, book_id, latest.tree) if latest is not None else {}
    fresh: list[str] = []
    changed_before: list[tuple[str, str, str]] = []
    for table, rows in snap.rows.items():
        if latest is not None and latest.tree.get(table) == snap.tree[table]:
            continue
        fresh.append(snap.tree[table])
        old = before_rows.get(table, {})
        for row_id, h in rows.items():
            if old.get(row_id) != h:
                fresh.extend(row_hashes_with_text(snap, table, h))
        changed_before.extend((table, row_id, h) for row_id, h in old.items() if rows.get(row_id) != h)
    await store_objects(session, book_id, snap, fresh)
    if latest is None:
        # 第一档：这本书原来的样子，不列一大串「新建了」
        summary = {"items": [], "more": 0, "finished": [], "first": True}
        title = title or "存档从这里开始：这本书原来的样子"
    else:
        before_data = await load_objects(session, book_id, [h for _, _, h in changed_before])
        before_tables: dict[str, dict[str, dict]] = {}
        for table, row_id, h in changed_before:
            if h in before_data:
                before_tables.setdefault(table, {})[row_id] = before_data[h]
        summary = summarize(before_rows, snap.rows, before_data, snap.data, Namer(before_tables, snap.data))
    if title is None:
        said = describe(summary)
        if lead is not None:
            title = f"{lead}{said}"
        else:
            title = f"你自己改的：{said}" if actor == "author" else f"{ACTOR_NAMES.get(actor, '编辑部')}：{said}"
    save = BookSave(
        book_id=book_id,
        kind=kind,
        actor=actor,
        title=title[:500],
        summary=summary,
        tree=snap.tree,
        chapters_final=snap.chapters_final,
        parent_id=latest.id if latest is not None else None,
        restored_from=restored_from,
    )
    session.add(save)
    await session.commit()
    return save


async def safe_checkpoint(
    session: AsyncSession,
    book_id: uuid.UUID,
    actor: str = "system",
    title: str | None = None,
    *,
    lead: str | None = None,
    force: bool = False,
):
    """各处自动存：存不成只记日志，不耽误作者手上的事。"""
    try:
        return await checkpoint(session, book_id, actor, title, lead=lead, force=force)
    except Exception:  # noqa: BLE001
        log.exception("书 %s 自动存档没存成", book_id)
        await session.rollback()
        return None


async def editorial(session: AsyncSession, book_id: uuid.UUID, actor: str, lead: str, work):
    """页面上编辑部动书：做事前先存作者自己改了还没存的，做完存一档。没做成就不存。"""
    await before_ai(session, book_id)
    result = await work()
    await safe_checkpoint(session, book_id, actor, lead=lead)
    return result


async def before_ai(session: AsyncSession, book_id: uuid.UUID) -> None:
    """编辑部动书之前：作者自己改过还没存的，先存一档「你自己改的：……」。"""
    await safe_checkpoint(session, book_id, "author")


# ---------- 回到一档 ----------


def _column_value(column, value):
    if value is None:
        return None
    try:
        kind = column.type.python_type
    except NotImplementedError:
        return value
    if kind is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if kind is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _values(model, data: dict, texts: dict[str, Any]) -> dict:
    t = model.__table__
    out = {}
    for key, value in data.items():
        if key not in t.c:
            continue
        if model is Chapter and key == "content":
            value = texts.get(value, "") if value else ""
        out[key] = _column_value(t.c[key], value)
    return out


async def _put_rows(session: AsyncSession, model, rows: list[dict], texts: dict) -> None:
    if not rows:
        return
    values = [_values(model, row, texts) for row in rows]
    parents = {}
    if model is WorldEntry:
        # 上级条目也在同一张表里：先插进去，再补上 parent_id
        for row in values:
            if row.get("parent_id"):
                parents[row["id"]] = row["parent_id"]
            row["parent_id"] = None
    for start in range(0, len(values), 200):
        await session.execute(insert(model.__table__), values[start : start + 200])
    for row_id, parent in parents.items():
        await session.execute(
            update(WorldEntry.__table__).where(WorldEntry.__table__.c.id == row_id).values(parent_id=parent)
        )


async def restore(session: AsyncSession, book_id: uuid.UUID, save_id: int) -> tuple[BookSave, BookSave | None]:
    """整本书回到那一档：先存一档「回到『X』之前的样子」，再换回去，再记一档「回到了『X』」。"""
    from app.services import jobs
    from app.services.library import lock_book

    target = await session.get(BookSave, save_id)
    if target is None or target.book_id != book_id:
        raise HTTPException(404, "这一档不存在")

    async def ensure_free():
        busy = await session.scalar(
            select(Job.id).where(Job.book_id == book_id, Job.status.in_(jobs.ACTIVE_STATUSES)).limit(1)
        )
        if busy is not None:
            raise HTTPException(409, "编辑部正在干活或者在等你拍板：先停下（或者先拍板）再回去")

    await ensure_free()
    label = restore_label(target)
    before = await checkpoint(session, book_id, "author", f"回到「{label}」之前的样子", force=True)
    await lock_book(session, book_id)
    await ensure_free()
    await lock_saves(session, book_id)
    rows = await manifests(session, book_id, target.tree)
    data = await load_objects(session, book_id, [h for table in rows.values() for h in table.values()])
    chapter_hashes = set(rows.get("chapters", {}).values())
    texts = await load_objects(session, book_id, [d.get("content") for h, d in data.items() if h in chapter_hashes])
    book_data = data.get(next(iter(rows.get("books", {}).values()), ""), None)
    if (
        book_data
        and book_data.get("source") == "teardown"
        and (book_data.get("teardown") or {}).get("stage") == "confirming"
        and await session.get(TeardownSource, book_id) is None
    ):
        # 原文件不进存档，导入后就删除。先挡住，再删章，避免回档把唯一原文也清掉。
        raise HTTPException(409, "导入前的存档没有原文件，不能回到这一档；导入后的存档仍可恢复。")
    for model in reversed(TABLES):
        t = model.__table__
        await session.execute(delete(t).where(t.c.book_id == book_id))
    for model in TABLES:
        await _put_rows(session, model, [data[h] for h in rows.get(model.__tablename__, {}).values()], texts)
    if book_data:
        values = _values(Book, {k: v for k, v in book_data.items() if k not in BOOK_SKIP}, {})
        if "settings" in values:
            values["settings"] = {**values["settings"], "other_rules": ""}
        await session.execute(
            update(Book.__table__).where(Book.__table__.c.id == book_id).values(**values, updated_at=func.now())
        )

    # 停在半路能「接着做」的活作废：不然接着做会照着旧进度往下写
    await session.execute(
        update(Job)
        .where(Job.book_id == book_id, Job.status == "failed")
        .values(status="cancelled", error=Job.error + "（书回到了存档，这一次的活作废了）")
    )
    # 三种写法的临时候选清掉
    await session.execute(delete(SettingCandidate).where(SettingCandidate.book_id == book_id))
    await session.commit()
    # 表里的行整个换过了：会话里认得的旧对象都放掉，之后重新读（已经读出来的字段照样能看）
    target_id = target.id
    session.expunge_all()
    landed = await checkpoint(
        session, book_id, "author", f"回到了「{label}」", kind="restore", force=True, restored_from=target_id
    )
    return landed, before


def restore_label(save: BookSave) -> str:
    """回到这一档时怎么称呼它：一般用它的名字；它本身就是「回到…」那种，用时间称呼，免得一层套一层。"""
    if save.title and not save.title.startswith("回到"):
        return save.title
    return f"{save_label(save)} 那一档"


def save_label(save: BookSave) -> str:
    when = save.created_at.astimezone() if save.created_at else None
    return when.strftime("%m-%d %H:%M") if when else f"第 {save.id} 档"


def save_dict(save: BookSave) -> dict:
    return {
        "id": save.id,
        "created_at": save.created_at.isoformat() if save.created_at else None,
        "kind": save.kind,
        "actor": save.actor,
        "actor_name": ACTOR_NAMES.get(save.actor, "编辑部"),
        "title": save.title,
        "summary": save.summary or {},
        "count": count_of(save.summary or {}),
        "chapters_final": save.chapters_final,
        "restored_from": save.restored_from,
    }


# ---------- 和现在比 ----------

HEAD = 160
LONG = 2000


def _clip(value: str, limit: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= limit else (value[:limit] + "……", True)


async def compare(session: AsyncSession, book_id: uuid.UUID, save: BookSave) -> dict:
    """这一档和现在比改了哪些：按设定／大纲／正文／写作要求／简介分组，每一处给「那时」「现在」两段字。"""
    now = await read_state(session, book_id)
    then_rows = await manifests(session, book_id, save.tree)
    changed = []
    for table in ["books", *(m.__tablename__ for m in TABLES)]:
        old, new = then_rows.get(table, {}), now.rows.get(table, {})
        changed.extend(
            (table, row_id, old.get(row_id), new.get(row_id))
            for row_id in dict.fromkeys([*old, *new])
            if old.get(row_id) != new.get(row_id)
        )
    then_data = await load_objects(session, book_id, [c[2] for c in changed])
    then_texts = await load_objects(
        session, book_id, [then_data[c[2]].get("content") for c in changed if c[0] == "chapters" and c[2] in then_data]
    )
    namer = Namer(now.data)
    groups: dict[str, list] = {}
    for table, row_id, old_h, _ in changed:
        before, after = then_data.get(old_h), now.data.get(table, {}).get(row_id)
        old_parts = parts(table, before, lambda h: then_texts.get(h, ""))
        new_parts = parts(table, after, now.text_of)
        shown = []
        for label in dict.fromkeys([*old_parts, *new_parts]):
            a, b = old_parts.get(label, ""), new_parts.get(label, "")
            if a == b or (label in QUIET and before and after):
                continue
            limit = HEAD if label == "正文" else LONG
            then_text, cut_a = _clip(a, limit)
            now_text, cut_b = _clip(b, limit)
            shown.append(
                {
                    "label": label,
                    "then": then_text,
                    "now": now_text,
                    "then_words": len("".join(a.split())),
                    "now_words": len("".join(b.split())),
                    "long": cut_a or cut_b,
                }
            )
        if not shown and before and after:
            continue
        op = "add" if before is None else "del" if after is None else "mod"
        labels = [s["label"] for s in shown]
        group = group_of(table, labels, after or before)
        groups.setdefault(group, []).append(
            {
                "table": table,
                "id": row_id,
                # add：现在有、那时没有（回去会删掉）；del：那时有、现在没有（回去会加回来）
                "op": op,
                "name": namer.name(table, after or before or {}),
                "parts": shown,
            }
        )
    return {
        "save": save_dict(save),
        "now_final": now.chapters_final,
        "groups": [{"name": name, "items": groups[name]} for name in GROUPS if name in groups],
        "same": not changed,
    }


async def full_text(
    session: AsyncSession, book_id: uuid.UUID, save: BookSave, table: str, row_id: str, label: str
) -> dict:
    """点开看全文：那时、现在这一栏的全部字。"""
    now = await read_state(session, book_id)
    then_rows = await manifests(session, book_id, save.tree)
    old_h = then_rows.get(table, {}).get(row_id)
    before = (await load_objects(session, book_id, [old_h])).get(old_h) if old_h else None
    texts = await load_objects(session, book_id, [before.get("content")]) if before and table == "chapters" else {}
    old_parts = parts(table, before, lambda h: texts.get(h, ""))
    new_parts = parts(table, now.data.get(table, {}).get(row_id), now.text_of)
    return {"label": label, "then": old_parts.get(label, ""), "now": new_parts.get(label, "")}


# ---------- 聊天里的改动：前后对照、换回原来的 ----------


def row_changes(before: Snapshot, after: Snapshot) -> list[dict]:
    out = []
    for table in ["books", *(m.__tablename__ for m in TABLES)]:
        old, new = before.rows.get(table, {}), after.rows.get(table, {})
        for row_id in dict.fromkeys([*old, *new]):
            if old.get(row_id) != new.get(row_id):
                out.append({"table": table, "id": row_id, "before": old.get(row_id), "after": new.get(row_id)})
    return out


async def keep_change(
    session: AsyncSession, book_id: uuid.UUID, before: Snapshot, after: Snapshot, rows: list[dict]
) -> None:
    """改之前、改之后这几行都存进 book_objects：换回原来的要用改之前的样子。"""
    for snap, key in ((before, "before"), (after, "after")):
        hashes: list[str] = []
        for row in rows:
            if row[key]:
                hashes.extend(row_hashes_with_text(snap, row["table"], row[key]))
        await store_objects(session, book_id, snap, hashes)


def readable_diff(before: Snapshot, after: Snapshot, rows: list[dict]) -> list[dict]:
    """给作者看的前后对照：每一栏「原来」「改成」，太长截到 2000 字。"""
    namer = Namer(before.data, after.data)
    out = []
    for row in rows:
        table = row["table"]
        b = before.data.get(table, {}).get(row["id"]) if row["before"] else None
        a = after.data.get(table, {}).get(row["id"]) if row["after"] else None
        name = namer.name(table, a or b or {})
        old, new = parts(table, b, before.text_of), parts(table, a, after.text_of)
        if b is None or a is None:
            # 新建、删掉的：整条一起给
            whole = "\n".join(f"{k}：{v}" for k, v in (new if a else old).items() if v and k not in QUIET)
            text_, cut = _clip(whole, LONG)
            out.append(
                {
                    "label": ("新建 · " if a else "删掉 · ") + name,
                    "before": "" if a else text_,
                    "after": text_ if a else "",
                    "truncated": cut,
                }
            )
            continue
        for label in dict.fromkeys([*old, *new]):
            if old.get(label, "") == new.get(label, "") or label in QUIET:
                continue
            x, cut_x = _clip(old.get(label, ""), LONG)
            y, cut_y = _clip(new.get(label, ""), LONG)
            out.append({"label": f"{name} · {label}", "before": x, "after": y, "truncated": cut_x or cut_y})
    return out[:12]


async def rows_fresh(session: AsyncSession, rows: list[dict]) -> bool:
    """这几行现在还是改完时的样子：后来没被作者手改、写章、聊天里又改、回到存档动过。"""
    for row in rows:
        if row["table"] != "books" and row["table"] not in MODELS:
            continue
        if await current_row_hash(session, row["table"], row["id"]) != row["after"]:
            return False
    return True


async def put_back(session: AsyncSession, book_id: uuid.UUID, rows: list[dict]) -> None:
    """只把这几行换回改之前的样子（不是整本）：新建的删掉，改过的换回，删掉的加回来。"""
    rows = [row for row in rows if row["table"] == "books" or row["table"] in MODELS]
    data = await load_objects(session, book_id, [row["before"] for row in rows if row["before"]])
    texts = await load_objects(
        session,
        book_id,
        [data[r["before"]].get("content") for r in rows if r["table"] == "chapters" and r["before"] in data],
    )
    order = {name: i for i, name in enumerate(m.__tablename__ for m in TABLES)}
    gone = sorted((r for r in rows if not r["before"]), key=lambda r: -order.get(r["table"], -1))
    for row in gone:
        model = MODELS.get(row["table"])
        if model is not None:
            await session.execute(delete(model.__table__).where(model.__table__.c.id == uuid.UUID(row["id"])))
    for row in sorted((r for r in rows if r["before"]), key=lambda r: order.get(r["table"], -1)):
        before = data.get(row["before"])
        if before is None:
            raise HTTPException(409, "改之前的样子没存下来，换不回去；去存档里回到之前那一档")
        if row["table"] == "books":
            values = _values(Book, {k: v for k, v in before.items() if k not in BOOK_SKIP}, {})
            await session.execute(
                update(Book.__table__).where(Book.__table__.c.id == book_id).values(**values, updated_at=func.now())
            )
            continue
        model = MODELS[row["table"]]
        t = model.__table__
        values = _values(model, before, texts)
        exists = await session.scalar(select(t.c.id).where(t.c.id == values["id"]))
        if exists is None:
            await _put_rows(session, model, [before], texts)
        else:
            await session.execute(
                update(t)
                .where(t.c.id == values["id"])
                .values(**{k: v for k, v in values.items() if k != "id"}, updated_at=func.now())
            )
