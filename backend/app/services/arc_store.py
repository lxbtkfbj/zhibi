"""第三包篇规划与开写前补齐：只增量落库，不改作者已经看过的骨架。"""

import re
from copy import deepcopy

from sqlalchemy import func, select

from app.agents.glossary import clean_techniques
from app.library_config import BUILTIN_CATEGORIES, STATUSES
from app.models import (
    Chapter,
    Character,
    Foreshadowing,
    NodeAnchor,
    PlotUnit,
    Secret,
    SettingCategory,
    SettingSuggestion,
    StoryNode,
    StoryThread,
    Volume,
    WorldEntry,
)
from app.services.library import lock_book
from app.services.segment_planning import END_CONTENT
from app.services.setup_store import FORESHADOW_FIELDS, UNIT_FIELDS, VOLUME_FIELDS
from app.services.versions import record_version, snapshot_of

STATUS_KEYS = {value: key for key, value in STATUSES.items()}
STYLES = {item["key"]: item["style"] for item in BUILTIN_CATEGORIES}


async def rows(session, model, book_id):
    return list(await session.scalars(select(model).where(model.book_id == book_id)))


def names(row):
    return {row.name, *(row.aliases or [])}


async def version(session, book_id, kind, row, before=None, note="规划下一篇"):
    await session.flush()
    if before is None or before != snapshot_of(row):
        await record_version(session, book_id, kind, row, "ai", note, before=before)


async def save_arc_extras(session, book, endpoint, split, volumes, nodes_view, *, number, how):
    """首篇补齐与下一篇共用线索／锚点／期待／信息差落库。"""
    if not volumes:
        return {"threads": 0, "new_secrets": 0}
    first, last = min(v.index for v in volumes), max(v.index for v in volumes)
    threads = {row.name: row for row in await rows(session, StoryThread, book.id)}
    next_index = max((row.index for row in threads.values()), default=0) + 1
    for data in split.get("threads") or []:
        name = data.get("name", "").strip()
        if not name:
            continue
        row = threads.get(name)
        if row is None:
            row = StoryThread(
                book_id=book.id,
                name=name,
                index=next_index,
                kind=data.get("kind", "其他"),
                characters=deepcopy(data.get("characters") or []),
                beats=[],
            )
            session.add(row)
            threads[name] = row
            next_index += 1
        if not row.summary:
            row.summary = data.get("summary", "")
        beats = {beat["volume"]: deepcopy(beat) for beat in row.beats or []}
        beats.update(
            {
                beat["volume"]: deepcopy(beat)
                for beat in data.get("beats") or []
                if first <= int(beat.get("volume") or 0) <= last
            }
        )
        row.beats = [beat for _, beat in sorted(beats.items())]
    characters = {person.name: person for person in await rows(session, Character, book.id)}
    current_nodes = {str(node.id): node.id for node in await rows(session, StoryNode, book.id)}
    node_ids = {i: current_nodes.get(str(node.get("id"))) for i, node in enumerate(nodes_view, 1)}
    endpoint_index = next((i for i, node in enumerate(nodes_view, 1) if str(node.get("id")) == str(endpoint.id)), 0)
    # 新起的节点在确认前没有 ID，以规划终点序号接上。
    for i, node in enumerate(nodes_view, 1):
        if not node.get("id") and node.get("title") == endpoint.title:
            node_ids[i] = endpoint.id
            endpoint_index = i
    anchors = {(row.character_id, row.node_id, row.kind) for row in await rows(session, NodeAnchor, book.id)}
    for data in split.get("anchors") or []:
        person = characters.get(data.get("character"))
        node_id = node_ids.get(data.get("node"))
        if person is None or node_id is None:
            continue
        key = (person.id, node_id, data.get("kind", "登场"))
        if key not in anchors:
            session.add(
                NodeAnchor(book_id=book.id, character_id=key[0], node_id=key[1], kind=key[2], note=data.get("note", ""))
            )
            anchors.add(key)
    wait = split.get("wait") or {}
    if wait:
        seq = (
            int(await session.scalar(select(func.max(Foreshadowing.seq)).where(Foreshadowing.book_id == book.id)) or 0)
            + 1
        )
        payoff = int(wait.get("payoff_volume") or last)
        session.add(
            Foreshadowing(
                book_id=book.id,
                seq=seq,
                kind="期待",
                span="长",
                node_id=endpoint.id,
                description=wait.get("description", ""),
                plant_plan=wait.get("plant_plan", ""),
                payoff_plan=wait.get("payoff_plan", ""),
                plant_volume=max(first, min(last, int(wait.get("plant_volume") or first))),
                payoff_volume=payoff if first <= payoff <= last else last,
                status="planned",
            )
        )
    secrets = await rows(session, Secret, book.id)
    existing = {row.title for row in secrets}
    next_seq = max((row.seq for row in secrets), default=0) + 1
    entries = await rows(session, WorldEntry, book.id)
    added = 0
    for data in split.get("secrets") or []:
        if data.get("title") in existing:
            continue
        known = []
        for item in data.get("knowers") or []:
            name = item if isinstance(item, str) else item.get("name")
            if name in characters and name not in {row["name"] for row in known}:
                known.append({"name": name, "since_chapter": None, "how": how})
        secret = Secret(
            book_id=book.id,
            seq=next_seq,
            title=data.get("title", ""),
            truth=data.get("truth", ""),
            knowers=known,
            reader_knows=data.get("reader_knows"),
            reveal_plan=data.get("reveal_plan", ""),
            status="hidden",
            node_id=endpoint.id,
        )
        session.add(secret)
        await session.flush()
        entry = next(
            (
                row
                for row in entries
                if row.category == "往事与秘密" and data.get("entry") in names(row) and row.secret_id is None
            ),
            None,
        )
        if entry is not None:
            before = snapshot_of(entry)
            entry.secret_id = secret.id
            await version(session, book.id, "entry", entry, before, "关联信息差")
        existing.add(secret.title)
        next_seq += 1
        added += 1
    return {"threads": len(split.get("threads") or []), "new_secrets": added, "end_index": endpoint_index}


async def save_arc(session, book, plan, split, *, number, status="confirmed", pin_end=False):
    await lock_book(session, book.id)
    await session.refresh(book)
    nodes = sorted(await rows(session, StoryNode, book.id), key=lambda row: row.position)
    saved = next((row for row in nodes if (row.segment or {}).get("number") == number), None)
    if saved is not None:
        volumes = [row for row in await rows(session, Volume, book.id) if row.target_node_id == saved.id]
        return {
            "volumes": len(volumes),
            "chapters": sum(v.chapter_count for v in volumes),
            "new_characters": 0,
            "new_entries": 0,
            "filled_entries": 0,
            "new_secrets": 0,
            "secret": "",
            "end_id": str(saved.id),
            "end_title": saved.title,
            "first_volume": min((v.index for v in volumes), default=1),
            "already_saved": True,
        }
    cards = deepcopy(split.get("volumes") or [])
    first = int(await session.scalar(select(func.max(Volume.index)).where(Volume.book_id == book.id)) or 0) + 1
    if not cards:
        raise ValueError("这一篇还没有分卷。")
    if [card.get("index") for card in cards] != list(range(first, first + len(cards))):
        raise ValueError("等待确认期间卷号发生了变化，请重新规划下一篇。")
    adopt, end = plan.get("adopt") or {}, plan.get("end") or {}
    endpoint = next((row for row in nodes if str(row.id) == adopt.get("node_id")), None)
    before = snapshot_of(endpoint) if endpoint is not None else None
    preserved = False
    if endpoint is None:
        position = max((row.position for row in nodes if row.segment is not None), default=0) + 1
        for row in nodes:
            if row.position >= position:
                row.position += 1
        endpoint = StoryNode(
            book_id=book.id,
            position=position,
            kind="milestone",
            status="pencil",
            origin="ai",
            title=end.get("title", ""),
            event=end.get("event", ""),
        )
        session.add(endpoint)
    elif endpoint.status != "pinned":
        preserved = any(getattr(endpoint, key) != adopt.get("snapshot", {}).get(key, "") for key in END_CONTENT)
        if not preserved:
            endpoint.title, endpoint.event = end.get("title", ""), end.get("event", "")
    if pin_end:
        endpoint.status = "pinned"
    final_count = int(
        await session.scalar(
            select(func.count(Chapter.id)).where(Chapter.book_id == book.id, Chapter.status == "final")
        )
        or 0
    )
    endpoint.segment = {
        "number": number,
        "title": plan.get("title", ""),
        "text": plan.get("text", ""),
        "status": status,
        "planned_at": final_count,
        "finale": bool(plan.get("finale")),
        "split": True,
    }
    if endpoint.status != "pinned" and not preserved:
        endpoint.volume = first + len(cards) - 1
    await version(session, book.id, "segment", endpoint, before)
    entries = await rows(session, WorldEntry, book.id)
    characters = await rows(session, Character, book.id)
    stats = {"new_entries": 0, "new_characters": 0, "filled_entries": 0, "secret": ""}
    for data in plan.get("fill_entries") or []:
        row = next((row for row in entries if data.get("name") in names(row) and row.status == "later"), None)
        if row is None:
            continue
        content = data.get("content", "")
        if row.locked:
            session.add(
                SettingSuggestion(
                    book_id=book.id,
                    kind="fill_gap",
                    target_type="entry",
                    target_id=row.id,
                    title=f"定下第 {number} 篇时，「{row.name}」可以写全了：{content[:30]}……",
                    payload={
                        "op": "set_field",
                        "target_type": "entry",
                        "target_id": str(row.id),
                        "path": "content",
                        "value": content,
                    },
                )
            )
        else:
            old = snapshot_of(row)
            row.content, row.status = content, "must"
            await version(session, book.id, "entry", row, old)
            stats["filled_entries"] += 1
    custom = {row.name: row for row in await rows(session, SettingCategory, book.id)}
    new_places = []
    for data in plan.get("new_entries") or []:
        category = data.get("category", "特殊规则")
        own = custom.get(category)
        category = f"custom:{own.key}" if own else category if category in STYLES else "特殊规则"
        existing = next((row for row in entries if row.category == category and data.get("name") in names(row)), None)
        if existing is not None:
            if category == "等级体系":
                fresh = [
                    level
                    for level in data.get("levels") or []
                    if level.get("name") not in {level.get("name") for level in existing.levels or []}
                ]
                if fresh and existing.locked:
                    session.add(
                        SettingSuggestion(
                            book_id=book.id,
                            kind="fill_gap",
                            target_type="entry",
                            target_id=existing.id,
                            title=f"第 {number} 篇要用到更高的等级：{'、'.join(level['name'] for level in fresh)}。「{existing.name}」锁住了，解锁后加上。",
                            payload={"op": "note"},
                        )
                    )
                elif fresh:
                    old = snapshot_of(existing)
                    existing.levels = [*(existing.levels or []), *deepcopy(fresh)]
                    await version(session, book.id, "entry", existing, old)
            elif existing.source in {"ai", "migration"} and not existing.locked:
                old = snapshot_of(existing)
                for key in ("one_line", "content", "fields"):
                    if key in data:
                        setattr(existing, key, deepcopy(data[key]))
                existing.status = STATUS_KEYS.get(data.get("status"), data.get("status", "must"))
                existing.source = "ai"
                if category == "世界与地图" and existing.name == "世界概况":
                    existing.position = 0
                await version(session, book.id, "entry", existing, old)
                if category == "世界与地图" and data.get("parent"):
                    new_places.append((existing, data["parent"]))
            continue
        if any(data.get("name") in names(person) for person in characters):
            continue
        position = max((row.position or 0 for row in entries if row.category == category), default=0) + 1
        row = WorldEntry(
            book_id=book.id,
            name=data["name"],
            category=category,
            style=own.style if own else STYLES[category],
            status=STATUS_KEYS.get(data.get("status"), data.get("status", "must")),
            source="ai",
            one_line=data.get("one_line", ""),
            content=data.get("content", ""),
            levels=deepcopy(data.get("levels") or []),
            fields=deepcopy(data.get("fields") or []),
            position=0 if category == "世界与地图" and data["name"] == "世界概况" else position,
        )
        session.add(row)
        entries.append(row)
        await version(session, book.id, "entry", row)
        if row.category == "世界与地图" and data.get("parent"):
            new_places.append((row, data["parent"]))
        stats["new_entries"] += 1
    for row, parent_name in new_places:
        parent = next((item for item in entries if item.category == "世界与地图" and parent_name in names(item)), None)
        if parent is None:
            continue
        visited, cursor = {row.id}, parent
        while cursor is not None and cursor.id not in visited:
            visited.add(cursor.id)
            cursor = next((item for item in entries if item.id == cursor.parent_id), None)
        if cursor is not None:
            continue
        old = snapshot_of(row)
        row.parent_id = parent.id
        await version(session, book.id, "entry", row, old)
    for data in plan.get("new_characters") or []:
        identities = {data.get("name"), *(data.get("aliases") or [])} - {"", None}
        if any(identities & names(person) for person in characters):
            continue
        fields = {
            key: deepcopy(value)
            for key, value in data.items()
            if key in Character.__table__.columns
            and key not in {"id", "book_id", "created_at", "updated_at", "status", "source"}
        }
        row = Character(
            book_id=book.id,
            **fields,
            source="ai",
            status=STATUS_KEYS.get(data.get("status"), data.get("status", "must")),
            position=max((person.position or 0 for person in characters), default=0) + 1,
        )
        session.add(row)
        characters.append(row)
        await version(session, book.id, "character", row)
        stats["new_characters"] += 1
    if (
        plan.get("secret")
        and not (book.concept or {}).get("story")
        and not (book.concept or {}).get("secret_entry_id")
        and not any("底牌" in (row.tags or []) for row in entries)
    ):
        secret = plan["secret"]
        row = WorldEntry(
            book_id=book.id,
            name="底牌",
            category="往事与秘密",
            content=secret,
            one_line=re.split(r"(?<=[。！？!?])|\n", secret, maxsplit=1)[0],
            tags=["底牌"],
            locked=True,
            status="must",
            source="ai",
        )
        session.add(row)
        await version(session, book.id, "entry", row)
        old = snapshot_of(book)
        book.concept = {**(book.concept or {}), "secret_entry_id": str(row.id)}
        await version(session, book.id, "concept", book, old)
        stats["secret"] = secret
        stats["new_entries"] += 1
    volumes = []
    for data in cards:
        volume = Volume(
            book_id=book.id,
            index=data["index"],
            title=data.get("title", ""),
            status="planned",
            target_node_id=endpoint.id,
        )
        for key in VOLUME_FIELDS:
            if data.get(key) is not None:
                setattr(volume, key, clean_techniques(data[key]) if key == "techniques" else deepcopy(data[key]))
        volume.reaches_node = volume.index == first + len(cards) - 1
        volume.thread_beats = deepcopy(data.get("thread_beats") or [])
        session.add(volume)
        volumes.append(volume)
        await version(session, book.id, "volume", volume)
    ending = next((row for row in nodes if row.kind == "ending"), None)
    if (
        plan.get("ending_change")
        and ending is not None
        and ending.status != "pinned"
        and not (ending is endpoint and preserved)
    ):
        old = snapshot_of(ending)
        ending.event = plan["ending_change"]
        await version(session, book.id, "segment", ending, old)
    nodes_view = deepcopy(plan.get("nodes_view") or [])
    end_index = plan.get("end_index", 0)
    if 1 <= end_index <= len(nodes_view):
        nodes_view[end_index - 1]["id"] = str(endpoint.id)
    extras = await save_arc_extras(
        session,
        book,
        endpoint,
        split,
        volumes,
        nodes_view,
        number=number,
        how=f"定下第 {number} 篇时",
    )
    await session.flush()
    return {
        **stats,
        **extras,
        "volumes": len(volumes),
        "chapters": sum(v.chapter_count for v in volumes),
        "end_id": str(endpoint.id),
        "end_title": endpoint.title,
        "preserved_end": preserved,
        "first_volume": first,
        "already_saved": False,
    }


async def fill_arc(session, book, endpoint_id, split, nodes_view, *, matching_count=None):
    await lock_book(session, book.id)
    endpoint = await session.get(StoryNode, endpoint_id)
    if endpoint.segment is None or "split" in endpoint.segment or "number" in endpoint.segment:
        return {"threads": 0, "new_secrets": 0, "already_saved": True}
    all_nodes = sorted(await rows(session, StoryNode, book.id), key=lambda row: row.position)
    number = [row.id for row in all_nodes if row.segment is not None].index(endpoint.id) + 1
    volumes = sorted(
        [row for row in await rows(session, Volume, book.id) if row.target_node_id == endpoint.id],
        key=lambda row: row.index,
    )
    if not volumes:
        # 作者自己加的篇还没有卷：按编辑部分好的卷接在最后面建出来
        first = int(await session.scalar(select(func.max(Volume.index)).where(Volume.book_id == book.id)) or 0) + 1
        cards = split.get("volumes") or []
        if not cards:
            raise ValueError("这一篇还没有分卷。")
        if [card.get("index") for card in cards] != list(range(first, first + len(cards))):
            raise ValueError("分卷期间卷号发生了变化，请重试。")
        for data in cards:
            volume = Volume(book_id=book.id, index=data["index"], title=data.get("title", ""), status="planned")
            volume.target_node_id = endpoint.id
            for key in VOLUME_FIELDS:
                if data.get(key) is not None:
                    setattr(volume, key, clean_techniques(data[key]) if key == "techniques" else deepcopy(data[key]))
            volume.thread_beats = deepcopy(data.get("thread_beats") or [])
            session.add(volume)
            volumes.append(volume)
            await version(session, book.id, "volume", volume, note="开写前给这一篇分卷")
        matching_count = 0
    allowed = {
        "stage",
        "want",
        "goal",
        "climax",
        "antagonist",
        "power_range",
        "new_characters",
        "editor_note",
        "techniques",
        "thread_beats",
    }
    matched = volumes if matching_count is None else volumes[:matching_count]
    for volume, data in zip(matched, split.get("volumes") or [], strict=False):
        old = snapshot_of(volume)
        for key in allowed:
            if data.get(key) is not None:
                setattr(volume, key, clean_techniques(data[key]) if key == "techniques" else deepcopy(data[key]))
        if volume is volumes[-1]:
            volume.reaches_node = True
        await version(session, book.id, "volume", volume, old, "开写前补齐")
    if volumes and not volumes[-1].reaches_node:
        old = snapshot_of(volumes[-1])
        volumes[-1].reaches_node = True
        await version(session, book.id, "volume", volumes[-1], old, "开写前补齐")
    result = await save_arc_extras(session, book, endpoint, split, volumes, nodes_view, number=number, how="开书设定")
    old = snapshot_of(endpoint)
    endpoint.segment = {**endpoint.segment, "number": number, "planned_at": 0, "split": True}
    await version(session, book.id, "segment", endpoint, old, "开写前补齐")
    return {**result, "number": number, "already_saved": False}


async def fill_units(session, book_id, volume, plans, fresh, *, want="", pressure=""):
    await lock_book(session, book_id)
    units = sorted(
        [row for row in await rows(session, PlotUnit, book_id) if row.volume_id == volume.id], key=lambda row: row.index
    )
    chapter_units = {row.unit_id for row in await rows(session, Chapter, book_id)}
    eligible = {row.index for row in units if row.status != "done" and not row.key_events}
    if not eligible:
        return {"foreshadowings": 0, "expectations": 0}
    by_index = {data.get("index"): data for data in plans}
    for unit in units:
        if unit.index not in eligible:
            continue
        old = snapshot_of(unit)
        data = by_index.get(unit.index, {})
        for key in set(UNIT_FIELDS) - {"index", "title", "summary", "chapter_count", "locked", "status"}:
            if data.get(key) is not None:
                setattr(unit, key, clean_techniques(data[key]) if key == "techniques" else deepcopy(data[key]))
        if not unit.key_events:
            unit.key_events = [unit.summary or unit.title]
        if unit.id in chapter_units:
            unit.foreshadow_actions, unit.reveals = [], []
        await version(session, book_id, "unit", unit, old, "开写前补齐")
    nodes = sorted(await rows(session, StoryNode, book_id), key=lambda row: row.position)
    accepted = [item for item in fresh if item.get("plant_unit") in eligible]
    for data in accepted:
        row = Foreshadowing(book_id=book_id, seq=data["seq"], description=data.get("description", ""))
        for key in FORESHADOW_FIELDS:
            if data.get(key) is not None:
                setattr(row, key, deepcopy(data[key]))
        ref = data.get("node")
        row.node_id = nodes[ref - 1].id if isinstance(ref, int) and 1 <= ref <= len(nodes) else None
        session.add(row)
    old = snapshot_of(volume)
    if not volume.want:
        volume.want = want
    if not volume.pressure:
        volume.pressure = pressure
    if volume.status == "planned":
        volume.status = "approved"
    await version(session, book_id, "volume", volume, old, "开写前补齐")
    return {
        "foreshadowings": sum(row.get("kind") == "伏笔" for row in accepted),
        "expectations": sum(row.get("kind") == "期待" for row in accepted),
    }
