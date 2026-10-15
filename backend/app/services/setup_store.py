"""开书方案与数据库之间的读写；按稳定编号对齐，保留作者维护的字段。"""

import string
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.glossary import clean_techniques
from app.models import (
    Book,
    Character,
    DraftVersion,
    Foreshadowing,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    StoryNode,
    StoryThread,
    Volume,
    WorldEntry,
)

CHARACTER_FIELDS = (
    "name",
    "role_type",
    "gender",
    "age",
    "appearance",
    "personality",
    "background",
    "abilities",
    "goal",
    "location",
    "condition",
)
THREAD_FIELDS = ("name", "kind", "summary", "characters", "beats")
VOLUME_FIELDS = (
    "title",
    "stage",
    "summary",
    "goal",
    "climax",
    "antagonist",
    "power_range",
    "thread_beats",
    "new_characters",
    "chapter_count",
    "reaches_node",
    "editor_note",
    "techniques",
)
UNIT_FIELDS = (
    "index",
    "title",
    "chapter_count",
    "goal",
    "conflict",
    "climax",
    "outcome",
    "key_events",
    "thread_beats",
    "foreshadow_actions",
    "tropes",
    "resolution",
    "reveals",
    "editor_note",
    "techniques",
)
FORESHADOW_FIELDS = (
    "description",
    "span",
    "plant_plan",
    "payoff_plan",
    "plant_volume",
    "payoff_volume",
    "kind",
)
NODE_FIELDS = (
    "kind",
    "title",
    "event",
    "prerequisite",
    "consequence",
    "volume",
    "status",
    "origin",
    "editor_note",
    "techniques",
)
SECRET_FIELDS = ("title", "truth", "knowers", "reader_knows", "reveal_plan", "status")


def _assign(row: Any, data: dict[str, Any], fields: tuple[str, ...]) -> None:
    for key in fields:
        if key in data and data[key] is not None:
            value = clean_techniques(data[key]) if key == "techniques" else data[key]
            setattr(row, key, value)


async def _rows(session: AsyncSession, model: Any, *where: Any, order: Any = None) -> list:
    stmt = select(model).where(*where)
    if order is not None:
        stmt = stmt.order_by(order)
    return list((await session.execute(stmt)).scalars().all())


def spine_from_legacy(spine: dict) -> dict:
    """旧检查点仍可使用；有 nodes 时以新结构为准，不重复生成节点。"""
    result = {key: value for key, value in spine.items() if key not in {"opening", "ending", "milestones"}}
    if "nodes" in spine:
        return result
    nodes = []
    if spine.get("opening"):
        nodes.append({"kind": "opening", "title": "开篇", "event": spine["opening"]})
    for item in sorted(spine.get("milestones") or [], key=lambda item: item.get("index") or 0):
        nodes.append(
            {
                "kind": "milestone",
                "title": item.get("title", ""),
                "event": item.get("event", ""),
                "volume": item.get("volume"),
                "consequence": item.get("change", ""),
            }
        )
    if spine.get("ending"):
        nodes.append({"kind": "ending", "title": "结局", "event": spine["ending"]})
    result["nodes"] = [
        {
            "id": None,
            "prerequisite": "",
            "consequence": "",
            "volume": None,
            "status": "pencil",
            "origin": "ai",
            "editor_note": "",
            "techniques": [],
            **node,
        }
        for node in nodes
    ]
    return result


def node_dict(node: StoryNode) -> dict[str, Any]:
    return {"id": str(node.id), **{key: getattr(node, key) for key in NODE_FIELDS}}


async def load_nodes(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _rows(session, StoryNode, StoryNode.book_id == book_id, order=StoryNode.position)
    return [node_dict(row) for row in rows]


async def save_nodes(session: AsyncSession, book_id: uuid.UUID, items: list[dict]) -> list[StoryNode]:
    """原地更新有 ID 的节点；先验证整份顺序，避免失败时留下半份修改。"""
    old = {str(row.id): row for row in await _rows(session, StoryNode, StoryNode.book_id == book_id)}
    ids = [str(item["id"]) for item in items if item.get("id")]
    if len(ids) != len(set(ids)) or any(id_ not in old for id_ in ids):
        raise ValueError("节点 ID 重复或不属于本书")
    kinds = [item.get("kind", "milestone") for item in items]
    if any(kind not in {"opening", "milestone", "ending"} for kind in kinds):
        raise ValueError("节点类型无效")
    if kinds.count("opening") > 1 or ("opening" in kinds and kinds[0] != "opening"):
        raise ValueError("开篇必须是第一个节点")
    if kinds.count("ending") > 1 or ("ending" in kinds and kinds[-1] != "ending"):
        raise ValueError("结局必须是最后一个节点")
    out = []
    for index, item in enumerate(items, 1):
        row = old.pop(str(item["id"]), None) if item.get("id") else None
        row = row or StoryNode(book_id=book_id, kind=item.get("kind", "milestone"))
        _assign(row, item, NODE_FIELDS)
        if "volume" in item:
            row.volume = item["volume"]
        row.position = index
        session.add(row)
        out.append(row)
    # 数据库的 SET NULL 不会自动刷新同一个 Session 已加载的对象，先同步引用，
    # 避免分块保存之后读回旧 ID，或后续更新把已删除的 ID 写回去。
    removed = [row.id for row in old.values()]
    if removed:
        for model, column in (
            (Volume, Volume.target_node_id),
            (Foreshadowing, Foreshadowing.node_id),
            (Secret, Secret.node_id),
        ):
            await session.execute(
                update(model)
                .where(column.in_(removed))
                .values({column.key: None})
                .execution_options(synchronize_session="fetch")
            )
    for row in old.values():
        await session.delete(row)
    await session.flush()
    return out


def _node_indices(nodes: list | None) -> dict[str, tuple[int, str]]:
    result = {}
    for index, node in enumerate(nodes or [], 1):
        id_ = node.get("id") if isinstance(node, dict) else node.id
        title = node.get("title", "") if isinstance(node, dict) else node.title
        result[str(id_)] = (index, title)
    return result


def _node_ids(nodes: list) -> dict[int, uuid.UUID]:
    return {
        index: uuid.UUID(str(node["id"])) if isinstance(node, dict) else node.id for index, node in enumerate(nodes, 1)
    }


def merge_legacy_spine(spine: dict, previous_nodes: list[dict]) -> dict:
    """在旧 schema 产出进入下游之前补回稳定 ID、铁钉与旧 schema 无法表达的作者字段。"""
    converted = spine_from_legacy(spine)
    items = [dict(item) for item in converted.get("nodes", [])]
    if "nodes" not in spine:
        # 旧 schema 不会输出 ID；为未改变或同位置的旧节点补回 ID，铁钉不交给 AI 改写。
        previous = previous_nodes
        available = list(previous)
        matches: dict[int, dict] = {}
        # 先完成名称匹配，再给改名的节点按同类型顺位兜底；新插入的节点不能抢走后续同名节点的 ID。
        for index, item in enumerate(items):
            match = next(
                (node for node in available if node["kind"] == item["kind"] and node["title"] == item["title"]), None
            )
            if match is not None:
                available.remove(match)
                matches[index] = match
        for index, item in enumerate(items):
            match = matches.get(index)
            if match is None:
                match = next((node for node in available if node["kind"] == item["kind"]), None)
                if match is not None:
                    available.remove(match)
            if match is not None:
                item["id"] = match["id"]
                if match["status"] == "pinned":
                    item.update(match)
                else:
                    # 旧 schema 没有这些字段，不能用转换时的默认值抹掉作者已维护的内容。
                    for key in ("prerequisite", "status", "origin", "editor_note", "techniques"):
                        if key in match:
                            item[key] = match[key]
                    if item["kind"] in {"opening", "ending"}:
                        for key in ("title", "volume", "consequence"):
                            if key in match:
                                item[key] = match[key]
        # 铁钉不仅内容不变，顺序也不能由模型调整；无论匹配、改名还是漏报，都移回原位。
        pinned = [(index, node) for index, node in enumerate(previous) if node.get("status") == "pinned"]
        pinned_ids = {str(node["id"]) for _, node in pinned if node.get("id")}
        items = [item for item in items if not item.get("id") or str(item["id"]) not in pinned_ids]
        for index, node in pinned:
            if node["kind"] == "opening":
                position = 0
            elif node["kind"] == "ending":
                position = len(items)
            else:
                lower = 1 if items and items[0]["kind"] == "opening" else 0
                upper = len(items) - (1 if items and items[-1]["kind"] == "ending" else 0)
                position = max(lower, min(index, upper))
            items.insert(position, node)
    return deepcopy({**converted, "nodes": items})


async def _save_spine(session: AsyncSession, book: Book, spine: dict) -> list[StoryNode]:
    previous = await load_nodes(session, book.id) if "nodes" not in spine else []
    converted = merge_legacy_spine(spine, previous)
    book.spine = {key: value for key, value in converted.items() if key != "nodes"}
    return await save_nodes(session, book.id, converted["nodes"])


def assign_seqs(items: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """伏笔、期待共用编号；相同内容沿用原编号，新条目接着往后编。"""
    by_text = {(f.get("kind", "伏笔"), f.get("description", "").strip()): f["seq"] for f in existing if f.get("seq")}
    used = {f["seq"] for f in [*existing, *items] if f.get("seq")}
    next_seq = max(used, default=0) + 1
    out = []
    assigned = set()
    for item in items:
        seq = item.get("seq") or by_text.get((item.get("kind", "伏笔"), item.get("description", "").strip()))
        if not seq or seq in assigned:
            while next_seq in used:
                next_seq += 1
            seq = next_seq
            used.add(seq)
        assigned.add(seq)
        out.append({**item, "seq": seq})
    return out


def ledger_of(setup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    outline, first = setup.get("outline") or {}, setup.get("first_volume") or {}
    items = []
    for source, key, kind, span in (
        (outline, "foreshadowings", "伏笔", "长"),
        (outline, "expectations", "期待", "长"),
        (first, "new_foreshadowings", "伏笔", "中"),
        (first, "new_expectations", "期待", "中"),
    ):
        for item in source.get(key) or []:
            if item.get("description", "").strip():
                items.append({"span": span, **item, "kind": kind})
    return sorted(assign_seqs(items, []), key=lambda item: item["seq"])


async def _save_concept(session: AsyncSession, book: Book, concept: dict) -> None:
    book.concept = concept
    book.title = concept.get("title") or book.title
    book.genre = concept.get("genre", "")


async def _save_lore(session: AsyncSession, book_id: uuid.UUID, lore: dict, nodes: list) -> dict[str, int]:
    old = {c.name: c for c in await _rows(session, Character, Character.book_id == book_id)}
    by_name = {}
    legacy_secrets = []
    for ch in lore.get("characters", []):
        name = (ch.get("name") or "").strip()
        if not name or name in by_name:
            continue
        row = old.pop(name, None) or Character(book_id=book_id, name=name)
        _assign(row, {**ch, "name": name}, CHARACTER_FIELDS)
        session.add(row)
        by_name[name] = row
        for text in ch.get("secrets") or []:
            if isinstance(text, str) and text.strip():
                legacy_secrets.append(
                    {
                        "title": text[:12].rstrip(string.punctuation + "，。！？；：、…—“”‘’（）【】《》"),
                        "truth": text,
                        "knowers": [{"name": name, "since_chapter": None, "how": "开书设定"}],
                    }
                )
    for row in old.values():
        await session.delete(row)
    old_world = {w.name: w for w in await _rows(session, WorldEntry, WorldEntry.book_id == book_id)}
    seen = set()
    for world in lore.get("world_entries", []):
        name = (world.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        row = old_world.pop(name, None) or WorldEntry(book_id=book_id, name=name)
        _assign(row, world, ("category", "content"))
        session.add(row)
    for row in old_world.values():
        await session.delete(row)
    await session.flush()
    old_relations = {
        (r.source_id, r.target_id, r.kind): r
        for r in await _rows(session, Relationship, Relationship.book_id == book_id)
    }
    seen = set()
    for relation in lore.get("relationships", []):
        a, b = by_name.get(relation.get("source", "")), by_name.get(relation.get("target", ""))
        if a is None or b is None or a is b:
            continue
        key = (a.id, b.id, relation.get("kind", ""))
        if key in seen:
            continue
        seen.add(key)
        row = old_relations.pop(key, None) or Relationship(book_id=book_id, source_id=a.id, target_id=b.id, kind=key[2])
        _assign(row, relation, ("description",))
        session.add(row)
    for row in old_relations.values():
        await session.delete(row)
    # 旧 LoreDraft 不认识锚点和结构化信息差；字段缺失不是作者要求清空。
    dropped_anchors = 0
    if "anchors" in lore:
        dropped_anchors = await _save_anchors(session, book_id, lore.get("anchors") or [], nodes, by_name)
    if "secrets" in lore:
        secret_items = list(lore.get("secrets") or [])
    else:
        secret_items = await load_secrets(session, book_id, nodes)
    known = {
        (item.get("truth", "").strip(), knower.get("name"))
        for item in secret_items
        for knower in item.get("knowers") or []
    }
    for item in legacy_secrets:
        key = (item["truth"].strip(), item["knowers"][0]["name"])
        if key not in known:
            secret_items.append(item)
            known.add(key)
    dropped_knowers = await _save_secrets(session, book_id, secret_items, nodes, by_name)
    await session.flush()
    return {"dropped_anchors": dropped_anchors, "dropped_knowers": dropped_knowers}


async def _save_anchors(session: AsyncSession, book_id: uuid.UUID, items: list, nodes: list, characters: dict) -> int:
    node_ids = _node_ids(nodes)
    old = {
        (a.character_id, a.node_id, a.kind): a for a in await _rows(session, NodeAnchor, NodeAnchor.book_id == book_id)
    }
    seen = set()
    dropped = 0
    for item in items:
        character, node_id = characters.get(item.get("character")), node_ids.get(item.get("node"))
        if character is None or node_id is None:
            dropped += 1
            continue
        key = (character.id, node_id, item.get("kind", "登场"))
        if key in seen:
            continue
        seen.add(key)
        row = old.pop(key, None) or NodeAnchor(book_id=book_id, character_id=character.id, node_id=node_id, kind=key[2])
        row.note = item.get("note", "")
        session.add(row)
    for row in old.values():
        await session.delete(row)
    return dropped


async def _save_secrets(session: AsyncSession, book_id: uuid.UUID, items: list, nodes: list, characters: dict) -> int:
    old = {s.seq: s for s in await _rows(session, Secret, Secret.book_id == book_id, order=Secret.seq)}
    node_ids = _node_ids(nodes)
    next_seq = max([*old, *(item.get("seq") or 0 for item in items)], default=0) + 1
    seen = set()
    dropped = 0
    for item in items:
        seq = item.get("seq")
        if not seq:
            seq = next((s.seq for s in old.values() if s.title == item.get("title", "")), None)
        if not seq:
            seq, next_seq = next_seq, next_seq + 1
        if seq in seen:
            raise ValueError("信息差编号不能重复")
        seen.add(seq)
        row = old.pop(seq, None) or Secret(book_id=book_id, seq=seq)
        _assign(row, item, SECRET_FIELDS)
        if "reader_knows" in item:
            row.reader_knows = item["reader_knows"]
        knowers = []
        for knower in item.get("knowers") or []:
            if knower.get("name") not in characters:
                dropped += 1
            else:
                knowers.append(dict(knower))
        row.knowers = knowers
        if "node" in item:
            row.node_id = node_ids.get(item["node"])
        session.add(row)
    for row in old.values():
        await session.delete(row)
    return dropped


async def _save_volumes(session: AsyncSession, book_id: uuid.UUID, outline: dict, nodes: list, has_units: bool) -> None:
    old = {v.index: v for v in await _rows(session, Volume, Volume.book_id == book_id)}
    node_ids = _node_ids(nodes)
    seen = set()
    for item in outline.get("volumes", []):
        index = item.get("index")
        if not index or index in seen:
            continue
        seen.add(index)
        row = old.pop(index, None)
        if row is None:
            row = Volume(
                book_id=book_id,
                index=index,
                title=item.get("title", ""),
                status="detailed" if index == 1 and has_units else "planned",
            )
        elif index == 1 and has_units and row.status == "planned":
            row.status = "detailed"
        _assign(row, item, VOLUME_FIELDS)
        if "target_node" in item:
            row.target_node_id = node_ids.get(item["target_node"])
        elif row.target_node_id is None:
            # 旧总纲不带目标节点，按迁移相同规则补齐。
            last_volume = max((v.get("index", 0) for v in outline.get("volumes", [])), default=0)
            for node in nodes:
                kind = node.kind if isinstance(node, StoryNode) else node["kind"]
                volume = node.volume if isinstance(node, StoryNode) else node.get("volume")
                if kind == "ending" and volume is None:
                    volume = last_volume
                if kind in {"milestone", "ending"} and volume is not None and volume >= index:
                    row.target_node_id = node.id if isinstance(node, StoryNode) else uuid.UUID(node["id"])
                    row.reaches_node = volume == index
                    break
        session.add(row)
    for row in old.values():
        await session.delete(row)
    await session.flush()


async def _save_threads(session: AsyncSession, book_id: uuid.UUID, threads: dict) -> None:
    old = {t.name: t for t in await _rows(session, StoryThread, StoryThread.book_id == book_id)}
    seen = set()
    for index, item in enumerate(threads.get("threads", []), 1):
        name = (item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        row = old.pop(name, None) or StoryThread(book_id=book_id, name=name)
        _assign(row, {**item, "name": name}, THREAD_FIELDS)
        row.index = index
        session.add(row)
    for row in old.values():
        await session.delete(row)


async def _save_units(session: AsyncSession, book_id: uuid.UUID, first: dict) -> None:
    volume = await session.scalar(select(Volume).where(Volume.book_id == book_id, Volume.index == 1))
    if volume is None:
        return
    old = {u.index: u for u in await _rows(session, PlotUnit, PlotUnit.volume_id == volume.id)}
    seen = set()
    for item in first.get("units") or []:
        index = item.get("index")
        if not index or index in seen:
            continue
        seen.add(index)
        row = old.pop(index, None) or PlotUnit(
            volume_id=volume.id, book_id=book_id, index=index, title=item.get("title", "")
        )
        _assign(row, item, UNIT_FIELDS)
        session.add(row)
    for row in old.values():
        await session.delete(row)
    if seen and volume.status == "planned":
        volume.status = "detailed"


async def _save_ledger(
    session: AsyncSession, book_id: uuid.UUID, setup: dict, nodes: list, long: bool | None = None
) -> None:
    existing = await _rows(session, Foreshadowing, Foreshadowing.book_id == book_id)
    # ledger_of assigns missing numbers within one snapshot; use the full DB as numbering history instead.
    items = []
    outline, first = setup.get("outline") or {}, setup.get("first_volume") or {}
    old = {
        f.seq: f
        for f in existing
        if (long is None or (f.span == "长") == long)
        and not (
            f.kind == "期待"
            and (
                (f.span == "长" and "expectations" not in outline)
                or (f.span != "长" and "new_expectations" not in first)
            )
        )
    }
    for source, key, kind, span in (
        (outline, "foreshadowings", "伏笔", "长"),
        (outline, "expectations", "期待", "长"),
        (first, "new_foreshadowings", "伏笔", "中"),
        (first, "new_expectations", "期待", "中"),
    ):
        for item in source.get(key) or []:
            item = {"span": span, **item, "kind": kind}
            if item.get("description", "").strip() and (long is None or (item["span"] == "长") == long):
                items.append(item)
    protected = {f.seq for f in existing if f.seq not in old}
    if any(item.get("seq") in protected for item in items):
        raise ValueError("不能覆盖其他块的台账编号")
    node_ids = _node_ids(nodes)
    for item in assign_seqs(items, [foreshadow_dict(f) for f in existing]):
        row = old.pop(item["seq"], None) or Foreshadowing(book_id=book_id, seq=item["seq"], description="")
        _assign(row, item, FORESHADOW_FIELDS)
        if "node" in item:
            row.node_id = node_ids.get(item["node"])
        session.add(row)
    for row in old.values():
        await session.delete(row)


def remap_node_refs(setup: dict, previous_nodes: list[dict], new_nodes: list) -> dict:
    """旧 schema 不会产生节点引用；这些序号来自旧 load_setup，按旧 ID 对齐而不是重新解释。"""
    result = deepcopy(setup)
    before = {index: str(node["id"]) for index, node in enumerate(previous_nodes, 1) if node.get("id")}
    after = {}
    snapshot_refs = {}
    titles = {}
    for index, node in enumerate(new_nodes, 1):
        id_ = node.get("id") if isinstance(node, dict) else node.id
        titles[index] = node.get("title", "") if isinstance(node, dict) else node.title
        if id_:
            after[str(id_)] = index
        if isinstance(node, dict) and node.get("_snapshot_ref"):
            snapshot_refs[node["_snapshot_ref"]] = index
    for block, collection, field in (
        ("lore", "anchors", "node"),
        ("lore", "secrets", "node"),
        ("outline", "volumes", "target_node"),
        ("outline", "foreshadowings", "node"),
        ("outline", "expectations", "node"),
        ("first_volume", "new_foreshadowings", "node"),
        ("first_volume", "new_expectations", "node"),
    ):
        for item in (result.get(block) or {}).get(collection) or []:
            if field in item:
                old_index = item[field]
                old_id = before.get(old_index)
                item[field] = after.get(old_id, 0) if old_id else snapshot_refs.get(old_index, 0)
                title_field = "target_node_title" if field == "target_node" else "node_title"
                if title_field in item:
                    item[title_field] = titles.get(item[field], "")
    return result


async def save_setup(session: AsyncSession, book_id: uuid.UUID, setup: dict[str, dict[str, Any]]) -> dict[str, int]:
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    previous_nodes = await load_nodes(session, book_id) if "nodes" not in (setup.get("spine") or {}) else []
    await _save_concept(session, book, setup.get("concept") or {})
    nodes = await _save_spine(session, book, setup.get("spine") or {})
    if previous_nodes:
        setup = remap_node_refs(setup, previous_nodes, nodes)
    result = await _save_lore(session, book_id, setup.get("lore") or {}, nodes)
    first = setup.get("first_volume") or {}
    await _save_volumes(session, book_id, setup.get("outline") or {}, nodes, bool(first.get("units")))
    await _save_threads(session, book_id, setup.get("threads") or {})
    await _save_units(session, book_id, first)
    await _save_ledger(session, book_id, setup, nodes)
    await session.flush()
    return result


async def save_piece(session: AsyncSession, book_id: uuid.UUID, piece: str, setup: dict) -> dict[str, int]:
    if piece not in {"concept", "nodes", "cast", "fill", "first_volume"}:
        raise ValueError("未知的开书拼图块")
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    result = {"dropped_anchors": 0, "dropped_knowers": 0}
    nodes = await load_nodes(session, book_id)
    if piece == "concept":
        await _save_concept(session, book, setup.get("concept") or {})
    elif piece == "nodes":
        await _save_spine(session, book, setup.get("spine") or {})
    elif piece == "cast":
        result = await _save_lore(session, book_id, setup.get("lore") or {}, nodes)
    elif piece == "fill":
        await _save_volumes(session, book_id, setup.get("outline") or {}, nodes, False)
        await _save_threads(session, book_id, setup.get("threads") or {})
        await _save_ledger(session, book_id, setup, nodes, long=True)
    else:
        await _save_units(session, book_id, setup.get("first_volume") or {})
        await _save_ledger(session, book_id, setup, nodes, long=False)
    await session.flush()
    return result


def thread_dict(t: StoryThread) -> dict[str, Any]:
    return {key: getattr(t, key) for key in THREAD_FIELDS}


def volume_dict(v: Volume, nodes: list | None = None) -> dict[str, Any]:
    index, title = _node_indices(nodes).get(str(v.target_node_id), (0, ""))
    return {
        "index": v.index,
        **{key: getattr(v, key) for key in VOLUME_FIELDS},
        "target_node": index,
        "target_node_title": title,
    }


def unit_dict(u: PlotUnit) -> dict[str, Any]:
    return {key: getattr(u, key) for key in UNIT_FIELDS}


def foreshadow_dict(f: Foreshadowing, nodes: list | None = None) -> dict[str, Any]:
    return {
        "seq": f.seq,
        **{key: getattr(f, key) for key in FORESHADOW_FIELDS},
        "node": _node_indices(nodes).get(str(f.node_id), (0, ""))[0],
        "status": f.status,
        "planted_chapter": f.planted_chapter,
        "resolved_chapter": f.resolved_chapter,
        "hint_chapters": list(f.hint_chapters or []),
    }


async def load_ledger(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    nodes = await load_nodes(session, book_id)
    rows = await _rows(session, Foreshadowing, Foreshadowing.book_id == book_id, order=Foreshadowing.seq)
    return [foreshadow_dict(f, nodes) for f in rows]


async def load_threads(session: AsyncSession, book_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await _rows(session, StoryThread, StoryThread.book_id == book_id, order=StoryThread.index)
    return [thread_dict(t) for t in rows]


async def load_secrets(session: AsyncSession, book_id: uuid.UUID, nodes: list | None = None) -> list[dict]:
    if nodes is None:
        nodes = await load_nodes(session, book_id)
    indices = _node_indices(nodes)
    rows = await _rows(session, Secret, Secret.book_id == book_id, order=Secret.seq)
    return [
        {
            "seq": row.seq,
            **{key: getattr(row, key) for key in SECRET_FIELDS},
            "node": indices.get(str(row.node_id), (0, ""))[0],
        }
        for row in rows
    ]


async def load_anchors(session: AsyncSession, book_id: uuid.UUID, nodes: list | None = None) -> list[dict]:
    if nodes is None:
        nodes = await load_nodes(session, book_id)
    indices = _node_indices(nodes)
    characters = await _rows(session, Character, Character.book_id == book_id)
    names = {character.id: character.name for character in characters}
    rows = await _rows(session, NodeAnchor, NodeAnchor.book_id == book_id, order=NodeAnchor.created_at)
    return [
        {
            "character": names.get(row.character_id, ""),
            "node": indices.get(str(row.node_id), (0, ""))[0],
            "node_title": indices.get(str(row.node_id), (0, ""))[1],
            "kind": row.kind,
            "note": row.note,
        }
        for row in rows
    ]


async def load_setup(session: AsyncSession, book_id: uuid.UUID) -> dict[str, dict]:
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    nodes = await load_nodes(session, book_id)
    characters = await _rows(session, Character, Character.book_id == book_id, order=Character.created_at)
    names = {character.id: character.name for character in characters}
    world = await _rows(session, WorldEntry, WorldEntry.book_id == book_id, order=WorldEntry.created_at)
    relations = await _rows(session, Relationship, Relationship.book_id == book_id, order=Relationship.created_at)
    volumes = await _rows(session, Volume, Volume.book_id == book_id, order=Volume.index)
    first_units = []
    if volumes and volumes[0].index == 1:
        rows = await _rows(session, PlotUnit, PlotUnit.volume_id == volumes[0].id, order=PlotUnit.index)
        first_units = [unit_dict(unit) for unit in rows]
    ledger = await load_ledger(session, book_id)
    lore = {
        "world_entries": [{"category": row.category, "name": row.name, "content": row.content} for row in world],
        "characters": [{key: getattr(row, key) for key in CHARACTER_FIELDS} for row in characters],
        "relationships": [
            {
                "source": names.get(row.source_id, ""),
                "target": names.get(row.target_id, ""),
                "kind": row.kind,
                "description": row.description,
            }
            for row in relations
        ],
        "anchors": await load_anchors(session, book_id, nodes),
        "secrets": await load_secrets(session, book_id, nodes),
    }
    return {
        "concept": dict(book.concept or {}),
        "lore": lore,
        "spine": {**(book.spine or {}), "nodes": nodes},
        "threads": {"threads": await load_threads(session, book_id)},
        "outline": {
            "volumes": [volume_dict(volume, nodes) for volume in volumes],
            "foreshadowings": [f for f in ledger if f["kind"] == "伏笔" and f["span"] == "长"],
            "expectations": [f for f in ledger if f["kind"] == "期待" and f["span"] == "长"],
        },
        "first_volume": {
            "units": first_units,
            "new_foreshadowings": [f for f in ledger if f["kind"] == "伏笔" and f["span"] != "长"],
            "new_expectations": [f for f in ledger if f["kind"] == "期待" and f["span"] != "长"],
        },
    }


async def snapshot(
    session: AsyncSession,
    book_id: uuid.UUID,
    job_id: uuid.UUID | None,
    round_: int,
    source: str,
    note: str,
    payload: dict,
) -> None:
    session.add(DraftVersion(book_id=book_id, job_id=job_id, round=round_, source=source, note=note, payload=payload))
