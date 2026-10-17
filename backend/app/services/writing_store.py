"""写作阶段的入库：卷纲、章纲、定稿后的设定变化（以及重写时撤销）。都是校验后的增量修改，不整体重建。"""

import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.context import foreshadow_code
from app.agents.glossary import clean_techniques
from app.agents.planning import ref_seq, secret_seq
from app.agents.setup_puzzle import clean_reveals
from app.models import (
    Book,
    Chapter,
    Character,
    Foreshadowing,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    StoryNode,
    StoryThread,
    Volume,
)
from app.services.arc_store import save_arc as save_arc
from app.services.digest_library import add_digest_library, first_sentence, revert_digest_library
from app.services.segment_planning import END_CONTENT
from app.services.setup_store import (
    CHARACTER_FIELDS,
    FORESHADOW_FIELDS,
    UNIT_FIELDS,
    VOLUME_FIELDS,
    load_nodes,
    load_secrets,
)

# 定稿时设定师会改的人物状态、伏笔进展；记下改前改后的值，重写时据此撤销
CHARACTER_STATE = ("location", "condition", "want", "abilities", "is_alive")
LEDGER_STATE = ("status", "planted_chapter", "hint_chapters", "resolved_chapter")


async def save_segment(
    session: AsyncSession,
    book: Book,
    plan: dict,
    split: dict,
    *,
    number: int,
    status: str = "confirmed",
    pin_end: bool = False,
) -> dict[str, Any]:
    """确认整段后一次增量入库；事务由调用方提交，锁行复核作者等待期间的改动。"""
    book = await session.scalar(
        select(Book).where(Book.id == book.id).with_for_update().execution_options(populate_existing=True)
    )
    if book is None:
        raise ValueError("书不存在")
    nodes = list(
        (
            await session.scalars(
                select(StoryNode)
                .where(StoryNode.book_id == book.id)
                .order_by(StoryNode.position)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    # 保存已提交、图检查点尚未落下时恢复：同一段不能重复插卷、重记期待或追加主角卡。
    saved = next((node for node in nodes if (node.segment or {}).get("number") == number), None)
    if saved is not None:
        volumes = list(
            await session.scalars(select(Volume).where(Volume.book_id == book.id, Volume.target_node_id == saved.id))
        )
        return {
            "volumes": len(volumes),
            "chapters": sum(volume.chapter_count for volume in volumes),
            "new_characters": 0,
            "new_secrets": 0,
            "preserved_end": False,
            "first_volume": min((volume.index for volume in volumes), default=1),
            "end_title": saved.title,
            "end_id": str(saved.id),
            "already_saved": True,
        }
    cards = deepcopy(split.get("volumes") or [])
    if not cards:
        raise ValueError("这一篇还没有分卷。")
    current_last = int(await session.scalar(select(func.max(Volume.index)).where(Volume.book_id == book.id)) or 0)
    first, last = current_last + 1, current_last + len(cards)
    if [card.get("index") for card in cards] != list(range(first, last + 1)):
        raise ValueError("等待确认期间卷号发生了变化，请重新规划下一篇。")
    final_count = int(
        await session.scalar(
            select(func.count(Chapter.id)).where(Chapter.book_id == book.id, Chapter.status == "final")
        )
        or 0
    )
    adopt = plan.get("adopt") or {}
    endpoint = next((node for node in nodes if str(node.id) == adopt.get("node_id")), None)
    end = plan.get("end") or {}
    preserved_end = False
    if endpoint is None:
        position = max((node.position for node in nodes if node.segment is not None), default=0) + 1
        for node in nodes:
            if node.position >= position:
                node.position += 1
        endpoint = StoryNode(book_id=book.id, position=position, kind="milestone", status="pencil", origin="ai")
        for key in END_CONTENT:
            setattr(endpoint, key, end.get(key, ""))
        endpoint.volume = last
        endpoint.editor_note = end.get("editor_note", "")
        endpoint.techniques = clean_techniques(end.get("techniques"))
        session.add(endpoint)
    elif endpoint.status != "pinned":
        snapshot = adopt.get("snapshot") or {}
        if all(getattr(endpoint, key) == snapshot.get(key, "") for key in END_CONTENT):
            for key in END_CONTENT:
                setattr(endpoint, key, end.get(key, ""))
            endpoint.volume = last
        else:
            preserved_end = True
    if pin_end:
        endpoint.status = "pinned"
    endpoint.segment = {
        "number": number,
        "status": status,
        "planned_at": final_count,
        **{key: plan.get(key, "") for key in ("map", "trouble", "opponent", "goal", "goal_link")},
        "wait": (plan.get("wait") or {}).get("description", ""),
        "reveal": plan.get("reveal", ""),
        "opening": None,
        **{key: plan.get(key, "") for key in ("carried", "pursuit", "finger_next", "answers")},
        "finale": bool(plan.get("finale")),
    }
    ending = next((node for node in nodes if node.kind == "ending"), None)
    if (
        plan.get("ending")
        and ending is not None
        and ending.status != "pinned"
        and not (ending is endpoint and preserved_end)
    ):
        ending.event = plan["ending"]
    world = deepcopy(book.world or {})
    new_map = plan.get("new_map") or {}
    if new_map:
        maps = deepcopy(world.get("maps") or [])
        match = next((i for i, item in enumerate(maps) if item.get("name") == new_map.get("name")), None)
        if match is None:
            maps.append(deepcopy(new_map))
        else:
            maps[match] = deepcopy(new_map)
        world["maps"] = maps
        world["far_maps"] = [item for item in world.get("far_maps") or [] if item.get("name") != new_map.get("name")]
    if plan.get("power"):
        world["power"] = "\n".join(
            value for value in (world.get("power"), f"（第 {number} 段）{plan['power']}") if value
        )
    if plan.get("answers") and not world.get("mystery_answer"):
        world["mystery_answer"] = plan["answers"]
    book.world = world
    protagonist = deepcopy(book.protagonist or {})
    for target, source in (("escalation", "pursuit"), ("finger_later", "finger_next")):
        if plan.get(source):
            protagonist[target] = "\n".join(
                value for value in (protagonist.get(target), f"第 {number} 段：{plan[source]}") if value
            )
    book.protagonist = protagonist
    characters = {
        person.name: person for person in await session.scalars(select(Character).where(Character.book_id == book.id))
    }
    new_characters = 0
    for person in plan.get("new_characters") or []:
        name = str(person.get("name", "")).strip()
        if not name or name in characters:
            continue
        row = Character(book_id=book.id, name=name)
        for key in CHARACTER_FIELDS:
            if key != "name" and person.get(key) is not None:
                setattr(row, key, person[key])
        session.add(row)
        characters[name] = row
        new_characters += 1
    await session.flush()
    relations = {
        (row.source_id, row.target_id, row.kind)
        for row in await session.scalars(select(Relationship).where(Relationship.book_id == book.id))
    }
    for relation in plan.get("relationships") or []:
        source, target = characters.get(relation.get("source")), characters.get(relation.get("target"))
        if source is None or target is None or source is target:
            continue
        key = (source.id, target.id, relation.get("kind", ""))
        if key in relations:
            continue
        session.add(
            Relationship(
                book_id=book.id,
                source_id=source.id,
                target_id=target.id,
                kind=key[2],
                description=relation.get("description", ""),
            )
        )
        relations.add(key)
    next_secret = int(await session.scalar(select(func.max(Secret.seq)).where(Secret.book_id == book.id)) or 0) + 1
    new_secrets = 0
    for secret in plan.get("secrets") or []:
        knowers, known = [], set()
        for item in secret.get("knowers") or []:
            item = {"name": item} if isinstance(item, str) else item
            name = str(item.get("name", "")).strip()
            if name in characters and name not in known:
                knowers.append({"name": name, "since_chapter": None, "how": "开书设定"})
                known.add(name)
        session.add(
            Secret(
                book_id=book.id,
                seq=next_secret,
                title=secret.get("title", ""),
                truth=secret.get("truth", ""),
                knowers=knowers,
                reader_knows=secret.get("reader_knows"),
                reveal_plan=secret.get("reveal_plan", ""),
                status="hidden",
                node_id=endpoint.id,
            )
        )
        next_secret += 1
        new_secrets += 1
    wait = plan.get("wait") or {}
    if wait:
        seq = (
            int(await session.scalar(select(func.max(Foreshadowing.seq)).where(Foreshadowing.book_id == book.id)) or 0)
            + 1
        )
        plant = max(first, min(last, int(wait.get("plant_volume") or first)))
        payoff = int(wait.get("payoff_volume") or last)
        if not first <= payoff <= last:
            payoff = last
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
                plant_volume=plant,
                payoff_volume=payoff,
                status="planned",
            )
        )
    for card in cards:
        row = Volume(book_id=book.id, index=card["index"], title=card.get("title", ""), status="planned")
        for key in VOLUME_FIELDS:
            if card.get(key) is not None:
                setattr(row, key, clean_techniques(card[key]) if key == "techniques" else deepcopy(card[key]))
        row.target_node_id = endpoint.id
        row.reaches_node = row.index == last
        row.thread_beats = [
            {"thread": thread["name"], "beat": beat.get("beat", "")}
            for thread in split.get("threads") or []
            for beat in thread.get("beats") or []
            if beat.get("volume") == row.index
        ]
        session.add(row)
    threads = {
        row.name: row for row in await session.scalars(select(StoryThread).where(StoryThread.book_id == book.id))
    }
    next_thread = max((row.index for row in threads.values()), default=0) + 1
    for thread in split.get("threads") or []:
        name = str(thread.get("name", "")).strip()
        if not name:
            continue
        row = threads.get(name)
        if row is None:
            row = StoryThread(
                book_id=book.id,
                name=name,
                index=next_thread,
                kind=thread.get("kind", "其他"),
                characters=deepcopy(thread.get("characters") or []),
                beats=[],
            )
            next_thread += 1
            threads[name] = row
            session.add(row)
        if not row.summary:
            row.summary = thread.get("summary", "")
        beats = {beat.get("volume"): deepcopy(beat) for beat in row.beats or []}
        beats.update(
            {
                beat["volume"]: deepcopy(beat)
                for beat in thread.get("beats") or []
                if first <= int(beat.get("volume") or 0) <= last
            }
        )
        row.beats = [beat for _, beat in sorted(beats.items())]
    current_ids = {str(node.id): node.id for node in nodes}
    node_ids = {
        index: current_ids.get(str(node.get("id"))) for index, node in enumerate(plan.get("nodes_view") or [], 1)
    }
    node_ids[plan.get("end_index", 0)] = endpoint.id
    anchors = {
        (row.character_id, row.node_id, row.kind)
        for row in await session.scalars(select(NodeAnchor).where(NodeAnchor.book_id == book.id))
    }
    for anchor in split.get("anchors") or []:
        person, node_id = characters.get(anchor.get("character")), node_ids.get(anchor.get("node"))
        if person is None or node_id is None:
            continue
        key = (person.id, node_id, anchor.get("kind", "登场"))
        if key in anchors:
            continue
        session.add(
            NodeAnchor(
                book_id=book.id, character_id=person.id, node_id=node_id, kind=key[2], note=anchor.get("note", "")
            )
        )
        anchors.add(key)
    await session.flush()
    return {
        "volumes": len(cards),
        "chapters": sum(int(card.get("chapter_count") or 0) for card in cards),
        "new_characters": new_characters,
        "new_secrets": new_secrets,
        "preserved_end": preserved_end,
        "first_volume": first,
        "end_title": endpoint.title,
        "end_id": str(endpoint.id),
        "already_saved": False,
    }


def _secret_state(row: Secret) -> dict[str, Any]:
    return {"knowers": deepcopy(row.knowers or []), "status": row.status}


def _secret_snapshot(row: Secret) -> dict[str, Any]:
    """删除本章新秘密前核对整条内容，避免连作者之后的修改一起删掉。"""
    return {
        **_secret_state(row),
        "title": row.title,
        "truth": row.truth,
        "reader_knows": row.reader_knows,
        "reveal_plan": row.reveal_plan,
        "node_id": str(row.node_id) if row.node_id else None,
        "created_chapter": row.created_chapter,
    }


def _state(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: (list(getattr(row, k) or []) if k == "hint_chapters" else getattr(row, k)) for k in keys}


async def save_volume_plan(
    session: AsyncSession,
    book_id: uuid.UUID,
    volume: Volume,
    units: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    *,
    replace_new: bool,
    replace_expectations: bool = False,
    want: str = "",
    pressure: str = "",
) -> None:
    """保存某一卷的卷纲：剧情单元按序号对齐；本卷新埋的伏笔写进台账。

    replace_new：修改卷纲时，本卷上一版新埋、还没写到的伏笔若这一版不要了，就从台账删掉。
    """
    for key, value in (("want", want), ("pressure", pressure)):
        if value and value.strip():
            setattr(volume, key, value)
    nodes = await load_nodes(session, book_id)
    node_ids = {index: uuid.UUID(node["id"]) for index, node in enumerate(nodes, 1)}
    units = clean_reveals(units, await load_secrets(session, book_id, nodes))
    old_units = {
        u.index: u
        for u in (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volume.id))).scalars().all()
    }
    for u in units:
        index = u.get("index")
        if not index:
            continue
        row = old_units.pop(index, None) or PlotUnit(
            volume_id=volume.id, book_id=book_id, index=index, title=u.get("title", "")
        )
        for key in UNIT_FIELDS:
            if key in u and u[key] is not None:
                setattr(row, key, clean_techniques(u[key]) if key == "techniques" else u[key])
        row.status = "planned"
        session.add(row)
    for row in old_units.values():
        await session.delete(row)

    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    keep = {f["seq"] for f in fresh}
    if replace_new:
        for seq, row in list(ledger.items()):
            # 旧检查点没有 new_expectations 时仍保留作者的期待；新 schema 明确管理两类条目。
            if (
                (row.kind == "伏笔" or replace_expectations)
                and row.plant_volume == volume.index
                and row.span != "长"
                and row.status == "planned"
                and seq not in keep
            ):
                await session.delete(row)
    for f in fresh:
        if f.get("kind") == "期待" and not f.get("span"):
            f = {**f, "span": "中"}
        row = ledger.get(f["seq"]) or Foreshadowing(book_id=book_id, seq=f["seq"], description="")
        for key in FORESHADOW_FIELDS:
            if f.get(key) is not None:
                setattr(row, key, f[key])
        if "node" in f:
            row.node_id = node_ids.get(f["node"])
        session.add(row)
    if not volume.chapter_count:
        volume.chapter_count = sum(int(u.get("chapter_count") or 0) for u in units)
    volume.status = "detailed"
    await session.flush()


async def next_chapter_index(session: AsyncSession, book_id: uuid.UUID) -> int:
    last = await session.scalar(select(func.coalesce(func.max(Chapter.index), 0)).where(Chapter.book_id == book_id))
    return int(last or 0) + 1


async def unit_next_chapter_index(session: AsyncSession, book_id: uuid.UUID, unit: PlotUnit) -> int:
    """新插入的单元要填回预留位置，不能越过后面已经存在的计划章纲。"""
    own = list(await session.scalars(select(Chapter).where(Chapter.unit_id == unit.id).order_by(Chapter.index)))
    if own:
        return own[-1].index + 1
    volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index)))
    units = list(await session.scalars(select(PlotUnit).where(PlotUnit.book_id == book_id).order_by(PlotUnit.index)))
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book_id)))
    volume_order = {volume.id: volume.index for volume in volumes}
    later_ids = {
        row.id for row in units if (volume_order[row.volume_id], row.index) > (volume_order[unit.volume_id], unit.index)
    }
    if not any(chapter.unit_id in later_ids for chapter in chapters):
        return await next_chapter_index(session, book_id)
    cursor = max((chapter.index for chapter in chapters if chapter.volume_id is None), default=0) + 1
    for volume in volumes:
        own_units = [row for row in units if row.volume_id == volume.id]
        if not own_units:
            cursor += volume.chapter_count
        for row in own_units:
            if row.id == unit.id:
                return cursor
            cursor += row.chapter_count
    return cursor


async def create_chapters(
    session: AsyncSession, book_id: uuid.UUID, unit: PlotUnit, chapters: list[dict[str, Any]]
) -> list[Chapter]:
    """把章纲建成章节行（只有章纲、还没有正文），章号接着全书往后排。"""
    start = await unit_next_chapter_index(session, book_id, unit)
    existing = int(await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.unit_id == unit.id)))
    if existing + len(chapters) > unit.chapter_count:
        raise ValueError("章纲数量超过作者已定的章数，原章数和章纲已保留")
    rows = []
    for offset, plan in enumerate(chapters):
        row = Chapter(
            book_id=book_id,
            volume_id=unit.volume_id,
            unit_id=unit.id,
            index=start + offset,
            title=(plan.get("title") or "").strip()[:200],
            outline=plan,
            status="planned",
        )
        session.add(row)
        rows.append(row)
    unit.status = "outlined"
    await session.flush()
    return rows


async def apply_digest(
    session: AsyncSession, book_id: uuid.UUID, chapter: Chapter, digest: s.ChapterDigest
) -> dict[str, int]:
    """把设定师提取的变化写进设定库：只认已有的人物、伏笔、期待与信息差编号。

    每处改动都记下改之前和改之后的值（chapter.bible_changes），重写这一章时据此撤销。
    这一章以前记过的改动（重写后重新提取时）先撤销再写。
    """
    await revert_chapter(session, book_id, chapter)
    log: dict[str, Any] = {
        "characters": [],
        "created": [],
        "foreshadowings": [],
        "secrets": [],
        "created_secrets": [],
        "created_secret_snapshots": {},
        "created_entries": [],
        "created_suggestions": [],
    }
    characters = {
        c.name: c
        for c in (await session.execute(select(Character).where(Character.book_id == book_id))).scalars().all()
    }
    # 重写前面的章节时，后面的章节改过的人物状态更新，不能被这一章的旧状态盖掉
    later = set()
    for changes in (
        await session.execute(
            select(Chapter.bible_changes).where(
                Chapter.book_id == book_id, Chapter.status == "final", Chapter.index > chapter.index
            )
        )
    ).scalars():
        for item in (changes or {}).get("characters") or []:
            after = item.get("after") or {}
            later |= {(item.get("name"), k) for k, v in (item.get("before") or {}).items() if after.get(k) != v}
    updated = created = 0
    for change in digest.character_updates:
        row = characters.get(change.name.strip())
        if row is None:
            continue
        before = _state(row, CHARACTER_STATE)
        for key in ("location", "condition", "want", "abilities"):
            value = getattr(change, key).strip()
            if value and value != getattr(row, key) and (row.name, key) not in later:
                setattr(row, key, value)
        if not change.is_alive and row.is_alive and (row.name, "is_alive") not in later:
            row.is_alive = False
        after = _state(row, CHARACTER_STATE)
        if after != before:
            log["characters"].append({"name": row.name, "before": before, "after": after})
            updated += 1
    for person in digest.new_characters:
        name = person.name.strip()
        if not name or name in characters or any(name in (row.aliases or []) for row in characters.values()):
            continue
        row = Character(
            book_id=book_id,
            name=name,
            role_type=person.role_type,
            background=person.background,
            personality=person.personality,
            first_appearance_chapter=chapter.index,
            source="writing",
            status="one",
            one_line=first_sentence(person.background),
        )
        session.add(row)
        characters[name] = row
        log["created"].append(name)
        created += 1

    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    moved = 0
    for change in digest.foreshadow_updates:
        row = ledger.get(ref_seq(change.ref) or -1)
        if (
            row is None
            or change.ref.strip().upper() != foreshadow_code({"seq": row.seq, "kind": row.kind})
            or row.status == "abandoned"
        ):
            continue
        before = _state(row, LEDGER_STATE)
        if row.status == "resolved":
            # 已经收了的伏笔只补记埋在哪一章（重写前面的章节后会出现这种情况）
            if change.action == "埋下" and not row.planted_chapter:
                row.planted_chapter = chapter.index
        elif change.action == "埋下" and row.status == "planned":
            row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "提醒" and chapter.index not in (row.hint_chapters or []):
            row.hint_chapters = sorted([*(row.hint_chapters or []), chapter.index])
            if row.status == "planned":
                row.status, row.planted_chapter = "planted", chapter.index
        elif change.action == "回收":
            row.status, row.resolved_chapter = "resolved", chapter.index
            row.planted_chapter = row.planted_chapter or chapter.index
        after = _state(row, LEDGER_STATE)
        if after == before:
            continue
        log["foreshadowings"].append({"seq": row.seq, "before": before, "after": after})
        moved += 1

    secrets = {row.seq: row for row in (await session.scalars(select(Secret).where(Secret.book_id == book_id))).all()}
    secret_before = {}
    for change in digest.secret_updates:
        row = secrets.get(secret_seq(change.ref) or -1)
        if row is None or change.ref.strip().upper() != f"S{row.seq}":
            continue
        secret_before.setdefault(row.seq, _secret_state(row))
        knowers = deepcopy(row.knowers or [])
        names = {item.get("name") for item in knowers}
        for name in change.learned_by:
            name = name.strip()
            if name in characters and name not in names:
                knowers.append({"name": name, "since_chapter": chapter.index, "how": change.how.strip()})
                names.add(name)
        row.knowers = knowers
        if change.public:
            row.status = "public"
    for seq, before in secret_before.items():
        after = _secret_state(secrets[seq])
        if after != before:
            log["secrets"].append({"seq": seq, "before": before, "after": after})

    seq = max(secrets, default=0)
    for new in digest.new_secrets:
        title, truth = new.title.strip(), new.truth.strip()
        if not title or not truth:
            continue
        # 重写前文时，本章创建的秘密可能因后文已使用而保留，不能再复制出同一条。
        if any(row.title == title and row.truth == truth for row in secrets.values()):
            continue
        names = dict.fromkeys(name.strip() for name in new.knowers if name.strip() in characters)
        seq += 1
        row = Secret(
            book_id=book_id,
            seq=seq,
            title=title[:100],
            truth=truth,
            knowers=[{"name": name, "since_chapter": chapter.index, "how": "本章"} for name in names],
            reader_knows=new.reader_knows,
            reveal_plan="",
            status="hidden",
            created_chapter=chapter.index,
        )
        session.add(row)
        secrets[seq] = row
        log["created_secrets"].append(seq)
        log["created_secret_snapshots"][str(seq)] = _secret_snapshot(row)

    log["created_entries"], log["created_suggestions"] = await add_digest_library(session, book_id, chapter, digest)
    chapter.summary = digest.summary.strip()
    chapter.bible_changes = log
    chapter.status = "final"
    await session.flush()
    if chapter.unit_id:
        left = await session.scalar(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.unit_id == chapter.unit_id, Chapter.status != "final")
        )
        if not left:
            unit = await session.get(PlotUnit, chapter.unit_id)
            if unit is not None:
                unit.status = "done"
    return {
        "characters_updated": updated,
        "characters_created": created,
        "foreshadowings": moved,
        "secrets_updated": len(log["secrets"]),
        "secrets_created": len(log["created_secrets"]),
        "new_entries": len(log["created_entries"]),
        "conflicts": len(log["created_suggestions"]),
    }


async def later_finals(session: AsyncSession, book_id: uuid.UUID, index: int) -> int:
    """这一章后面已经定稿了几章。"""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Chapter)
            .where(Chapter.book_id == book_id, Chapter.status == "final", Chapter.index > index)
        )
        or 0
    )


async def revert_chapter(session: AsyncSession, book_id: uuid.UUID, chapter: Chapter) -> dict[str, int]:
    """撤销这一章定稿时记进设定库、伏笔台账和信息差表的改动。

    只改回「现在还是这一章改成的样子」的字段；后面的章节又改过的保持不动。这一章新建的人物，
    后面没有定稿的章节时才删掉（后面的章节可能已经写到这个人）。
    """
    log = chapter.bible_changes or {}
    out = {
        "characters": 0,
        "removed": 0,
        "foreshadowings": 0,
        "secrets": 0,
        "removed_secrets": 0,
        "removed_entries": 0,
        "removed_suggestions": 0,
    }
    if not any(
        log.get(k)
        for k in (
            "characters",
            "created",
            "foreshadowings",
            "secrets",
            "created_secrets",
            "created_entries",
            "created_suggestions",
        )
    ):
        chapter.bible_changes = {}
        return out
    later = await later_finals(session, book_id, chapter.index)
    characters = {
        c.name: c
        for c in (await session.execute(select(Character).where(Character.book_id == book_id))).scalars().all()
    }
    for item in reversed(log.get("characters") or []):
        row = characters.get(item.get("name", ""))
        if row is None:
            continue
        changed = False
        for key, before in (item.get("before") or {}).items():
            if key in CHARACTER_STATE and getattr(row, key) == (item.get("after") or {}).get(key):
                setattr(row, key, before)
                changed = True
        out["characters"] += changed
    for name in log.get("created") or []:
        row = characters.get(name)
        if row is not None and row.first_appearance_chapter == chapter.index and not later:
            await session.delete(row)
            out["removed"] += 1
    ledger = {
        f.seq: f
        for f in (await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id))).scalars().all()
    }
    for item in reversed(log.get("foreshadowings") or []):
        row = ledger.get(item.get("seq"))
        if row is None:
            continue
        before, after = item.get("before") or {}, item.get("after") or {}
        changed = False
        for key in LEDGER_STATE:
            if key not in before:
                continue
            if key == "hint_chapters":
                current = list(row.hint_chapters or [])
                if chapter.index in current and chapter.index not in (before.get(key) or []):
                    row.hint_chapters = [c for c in current if c != chapter.index]
                    changed = True
            elif getattr(row, key) == after.get(key) and getattr(row, key) != before[key]:
                setattr(row, key, before[key])
                changed = True
        out["foreshadowings"] += changed

    secrets = {row.seq: row for row in (await session.scalars(select(Secret).where(Secret.book_id == book_id))).all()}
    for item in reversed(log.get("secrets") or []):
        row = secrets.get(item.get("seq"))
        if row is None:
            continue
        before, after = item.get("before") or {}, item.get("after") or {}
        current = _secret_state(row)
        previous_names = {knower.get("name") for knower in before.get("knowers") or []}
        added = [
            knower
            for knower in after.get("knowers") or []
            if knower.get("name") not in previous_names and knower.get("since_chapter") == chapter.index
        ]
        # 只移除本章追加且仍保持原样的记录；作者改过获知方式或后文改过获知章号的保留。
        row.knowers = [knower for knower in row.knowers or [] if knower not in added]
        if "status" in before and row.status == after.get("status"):
            row.status = before["status"]
        out["secrets"] += current != _secret_state(row)
    for seq in log.get("created_secrets") or []:
        row = secrets.get(seq)
        snapshot = (log.get("created_secret_snapshots") or {}).get(str(seq))
        if (
            row is not None
            and row.created_chapter == chapter.index
            and not later
            and (snapshot is None or _secret_snapshot(row) == snapshot)
        ):
            await session.delete(row)
            out["removed_secrets"] += 1
    out.update(await revert_digest_library(session, book_id, chapter, later))
    chapter.bible_changes = {}
    await session.flush()
    return out


async def reopen_chapter(session: AsyncSession, book_id: uuid.UUID, chapter: Chapter) -> dict[str, int]:
    """作者要重写一章已定稿的章节：撤销它记进设定库的改动，章节回到写作中；所在单元和卷的回顾作废，重写后重新写。"""
    changes = await revert_chapter(session, book_id, chapter)
    chapter.status = "drafting"
    chapter.attempts = 0
    if chapter.unit_id:
        unit = await session.get(PlotUnit, chapter.unit_id)
        if unit is not None:
            unit.status, unit.recap = "outlined", ""
    if chapter.volume_id:
        volume = await session.get(Volume, chapter.volume_id)
        if volume is not None:
            volume.recap = ""
            if volume.status == "done":
                volume.status = "approved"
    await session.flush()
    return changes
