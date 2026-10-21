"""拆书收尾：只拿逐章记录整理设定，逐项落盘并保护作者改字。"""

import asyncio
import hashlib
import json
import re
import uuid
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select

from app.agents import schemas as s
from app.graphs.deps import JobCancelled
from app.models import Book, Character, Relationship, WorldEntry
from app.services.desk import DEFAULT_FIELDS, value_of, write_value
from app.services.teardown_prompts import render
from app.services.teardown_roster import Roster
from app.services.versions import record_version, snapshot_of


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def data_hash(value) -> str:
    return text_hash(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def spans(numbers: list[int]) -> str:
    """与试拆脚本一致：[1,2,3,7,9,10] → 1–3、7、9–10。"""
    out, start, prev = [], None, None
    for n in sorted(set(numbers)):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}–{prev}" if prev > start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}–{prev}" if prev > start else str(start))
    return "、".join(out)


def moment_shows(shows: str) -> str:
    """模型已带「立住（了）：」时只去前缀，正文保留，不润色。"""
    return re.sub(r"^(?:(?:立住了|立住)[：:\s]*)+", "", shows.strip())


def people_of(reads: list[dict], names: dict | None = None) -> tuple[Roster, list[dict], str]:
    """名单先照第二批重算，再套卡上已认定的名字；调用键仍认最初名单。"""
    roster = Roster()
    roster.add(reads)
    names = names or {}

    def canonical(name: str) -> str:
        seen = set()
        while name in names and names[name] and name not in seen:
            seen.add(name)
            name = names[name]
        return name

    # 读下一批时名单已经用卡上的名字，模型可以直接写新名而不再写 was。
    # 因而不能把「原始名单里碰巧已有新名」当重名拒绝：names 是此前已经认过
    # 的身份映射，此时两份逐章记录必须合并，且调用/行键仍用最初的名字。
    merged: dict[str, dict] = {}
    shared = roster.shared()
    for person in roster.people:
        old = person["name"]
        mapped_alias = next((alias for alias in person["aliases"] if alias in names and alias not in shared), old)
        name = canonical(old if old in names else mapped_alias)
        origin = next((key for key in names if canonical(key) == name), old)
        aliases = [*person["aliases"], old, *[key for key in names if canonical(key) == name]]
        hit = merged.get(name)
        if hit is None:
            hit = {
                **person,
                "name": name,
                "key_name": origin,
                "aliases": [],
                "chapters": set(person["chapters"]),
                "rows": [],
                "moments": [],
            }
            merged[name] = hit
        else:
            hit["chapters"] |= person["chapters"]
            if (person["first"], person["order"]) < (hit["first"], hit["order"]):
                hit["first"], hit["order"], hit["note"] = person["first"], person["order"], person["note"]
        hit["aliases"] = list(dict.fromkeys([*hit["aliases"], *[alias for alias in aliases if alias != name]]))
    roster.people = sorted(merged.values(), key=lambda person: (person["first"], person["order"]))
    for chapter in sorted(reads, key=lambda c: c["index"]):
        for row in chapter.get("people", []):
            person = roster.find(row["name"].strip()) or roster.find(row.get("was", "").strip())
            if person is not None:
                person["rows"].append((chapter["index"], row))
        for row in chapter.get("moments", []):
            person = roster.find(row.get("who", "").strip())
            if person is not None:
                person["moments"].append((chapter["index"], row))
    ordered = sorted(roster.people, key=lambda p: (-len(p["chapters"]), p["first"], p["order"]))
    full = [p for p in ordered if len(p["chapters"]) >= 5 or p["moments"]][:40]
    for person in ordered:
        person["full"] = person in full
    selected = [p for p in ordered if p["full"] or 2 <= len(p["chapters"]) <= 4 and not p["moments"]]
    return roster, selected, ordered[0]["name"] if ordered else "（没有）"


def reuse_character_keys(roster: Roster, state: dict) -> None:
    """was 在后续章揭出真名时，一句话角色仍接回已归属的原行，不碰作者行。"""
    owned = {key.removeprefix("character:") for key in state.get("rows", {}) if key.startswith("character:")}
    shared = roster.shared()
    claimed = {person["key_name"] for person in roster.people if person["key_name"] in owned}
    for person in roster.people:
        if person["key_name"] in owned:
            continue
        aliases = [alias for alias in person["aliases"] if alias not in shared]
        candidates = owned.intersection([person["name"], *aliases]) - claimed
        if len(candidates) == 1:
            person["key_name"] = next(iter(candidates))
            claimed.add(person["key_name"])


def _even_order(indices: list[int]) -> list[int]:
    """先两端再逐层取中点，让任何长度的前缀都尽量均匀。"""
    if not indices:
        return []
    result = [indices[0]]
    if len(indices) > 1:
        result.append(indices[-1])
    ranges = [(1, len(indices) - 1)]
    while ranges:
        next_ranges = []
        for first, last in ranges:
            if first >= last:
                continue
            middle = (first + last) // 2
            result.append(indices[middle])
            next_ranges.extend([(first, middle), (middle + 1, last)])
        ranges = next_ranges
    return list(dict.fromkeys(result))


def dossier_of(person: dict, limit: int = 12000) -> str:
    blocks: dict[int, list[str]] = defaultdict(list)
    changed = []
    for index, row in person["rows"]:
        text = f"第 {index} 章：{row['shown']}"
        if row.get("change"):
            text += f"（变化：{row['change']}）"
            changed.append(index)
        blocks[index].append(text)
    moment_chapters = []
    for index, row in person["moments"]:
        blocks[index].append(f"第 {index} 章名场面：{row['what']}——立住了{moment_shows(row['shows'])}")
        moment_chapters.append(index)
    indices = sorted(blocks)
    full = "\n".join(line for index in indices for line in blocks[index])
    if len(full) <= limit:
        return full
    appearances = sorted({index for index, _ in person["rows"]})
    priority = list(dict.fromkeys([*sorted(moment_chapters), *sorted(changed), *appearances[:20], *appearances[-40:]]))
    priority.extend(n for n in _even_order(indices) if n not in priority)
    kept: dict[int, str] = {}
    # 给章数和提示留足空间；每个章块整体保留，名场面紧跟这一章。
    budget = max(0, limit - len(f"\n（中间有 {len(indices)} 章的记录没列出）"))
    used = 0
    for index in priority:
        block = "\n".join(blocks[index])
        cost = len(block) + bool(kept)
        if used + cost <= budget:
            kept[index] = block
            used += cost
        elif not kept and budget:
            # 极端的单章记录也不能突破总长度上限。
            kept[index] = block[:budget]
            used = budget
    omitted = len(indices) - len(kept)
    return "\n".join(kept[index] for index in sorted(kept)) + f"\n（中间有 {omitted} 章的记录没列出）"


def card_values(title: str, upto: int, person: dict, protagonist: str) -> dict:
    return dict(
        title=title,
        last=str(upto),
        name=person["name"],
        aliases="、".join(person["aliases"]) or "无",
        count=str(len(person["chapters"])),
        chapters=spans(list(person["chapters"])),
        protagonist=protagonist,
        dossier=dossier_of(person),
        _evidence=data_hash([person["rows"], person["moments"]]),
    )


def accept_card_name(person: dict, card, roster: Roster, missing: list[str]) -> str:
    old, new = person["name"], card.name.strip()
    if not new or new == old:
        return old
    if new not in person["aliases"] and old not in card.aliases:
        return old
    other = next((p for p in roster.people if p is not person and p["name"] == new), None)
    if other is not None:
        missing.append(f"卡上写的名字和 {other['name']} 重名，没改")
        return old
    return new


CHARACTER_VALUES = {
    "role_type": "定位",
    "belongs": "所属",
    "gender": "性别",
    "age": "年龄",
    "appearance": "外貌",
    "personality": "性格与说话方式",
    "background": "身世",
    "goal": "想要什么",
    "weakness": "软肋",
    "abilities": "能力",
    "growth": "成长与结局",
}


def managed_values(row, keys: list[str]) -> dict:
    return {key: value_of(row, key[6:]) if key.startswith("value:") else getattr(row, key) for key in keys}


def row_hash(row, keys: list[str]) -> str:
    return data_hash(managed_values(row, keys))


class SettingsIncomplete(Exception):
    def __init__(self, result: dict, errors: list[str]) -> None:
        self.result = result
        self.errors = errors
        super().__init__("；".join(errors)[:180])


class SettingsWriter:
    def __init__(self, runner, upto: int) -> None:
        self.runner, self.upto = runner, upto
        self.skipped: list[str] = []
        self.missing: list[str] = []

    async def check(self) -> None:
        if await self.runner.cancelled():
            raise JobCancelled()

    async def book(self, session):
        await self.check()
        book = await session.scalar(select(Book).where(Book.id == self.runner.book_id).with_for_update())
        if book is None:
            raise JobCancelled()
        return book

    @staticmethod
    def state(book) -> dict:
        state = deepcopy((book.teardown or {}).get("settings") or {})
        for key in ("inputs", "rows", "contexts", "relationships", "pending_parents", "pending_ties", "overviews"):
            state.setdefault(key, {})
        return state

    @staticmethod
    def save_state(book, state):
        state["missing"] = list(
            dict.fromkeys(item for context in state.get("contexts", {}).values() for item in context.get("missing", []))
        )
        book.teardown = {**(book.teardown or {}), "settings": state}

    def protected(self, row, info: dict | None) -> bool:
        if info is None or row.locked or row.source != "teardown":
            return True
        keys = info.get("keys")
        return not keys or row_hash(row, keys) != info.get("hash")

    def skipped_name(self, name: str) -> None:
        if name not in self.skipped:
            self.skipped.append(name)

    @staticmethod
    def save_input(state, key: str, user: str, values: dict, *, missing: list[str] | None = None):
        state["inputs"][key] = text_hash(user)
        previous_missing = state["contexts"].get(key, {}).get("missing", [])
        state["contexts"][key] = {
            "title": values.get("title", ""),
            "last": str(values.get("last", "")),
            "missing": list(dict.fromkeys(previous_missing if missing is None else missing)),
        }
        if "_evidence" in values:
            state["contexts"][key]["evidence"] = values["_evidence"]

    async def character(self, person, card=None, *, user="", values=None, roster=None):
        key = f"character:{person['key_name']}"
        async with self.runner.sm() as session:
            book = await self.book(session)
            state = self.state(book)
            info = state["rows"].get(key)
            row = await session.get(Character, uuid.UUID(info["id"])) if info else None
            if info and row is None or row is not None and self.protected(row, info):
                # 留着已删除行的归属记录：作者删掉的角色不能被续拆或强制重跑复活。
                self.skipped_name(row.name if row is not None else person["name"])
                if user:
                    self.save_input(state, f"card:{person['key_name']}", user, values)
                self.save_state(book, state)
                await session.commit()
                return None
            names = deepcopy((book.teardown or {}).get("names") or {})
            call_missing: list[str] = []
            name = accept_card_name(person, card, roster, call_missing) if card else person["name"]
            self.missing.extend(call_missing)
            collision = await session.scalar(
                select(Character).where(Character.book_id == book.id, Character.name == name)
            )
            if collision is not None and (row is None or collision.id != row.id):
                name = f"{name}（第 {person['first']} 章起）"
                # 作者自己建的区分名也不覆盖。
                base, number = name, 2
                while await session.scalar(
                    select(Character.id).where(
                        Character.book_id == book.id,
                        Character.name == name,
                        Character.id != row.id if row is not None else True,
                    )
                ):
                    name = f"{base}（{number}）"
                    number += 1
            before = snapshot_of(row) if row is not None else None
            if row is None:
                row = Character(book_id=book.id, name=name, source="teardown")
                session.add(row)
            row.name, row.source = name, "teardown"
            aliases = list(card.aliases) if card else list(person["aliases"])
            canonical_name = accept_card_name(person, card, roster, []) if card else person["name"]
            if canonical_name != person["name"]:
                # 写卡又选了同一人的另一个正式叫法时，整条旧身份链一起迁移，
                # 不能把「乙→甲」改成「乙→乙」后重新拆成两个人。
                def target(name):
                    seen = set()
                    while name in names and name not in seen:
                        seen.add(name)
                        name = names[name]
                    return name

                previous_aliases = [alias for alias in names if target(alias) == person["name"]]
                for alias in [*previous_aliases, person["name"], person["key_name"]]:
                    if alias != canonical_name:
                        names[alias] = canonical_name
                names.pop(canonical_name, None)
            elif person["key_name"] != canonical_name and person["key_name"] in person["aliases"]:
                # 逐章 was 已把旧称和真名合为一人；把同一行的新名字登记下来，
                # 后续按新名单直接返回真名时，调用键仍不会漂移。
                names[person["key_name"]] = canonical_name
            # 合并步骤已经确认的旧名不能因角色卡漏写 aliases 而从卡上丢失。
            aliases.extend(alias for alias in person["aliases"] if names.get(alias) == canonical_name)
            row.aliases = list(dict.fromkeys(a.strip() for a in aliases if a.strip() and a.strip() != name))
            row.one_line = card.one_line if card else person["note"]
            row.first_appearance_chapter = person["first"]
            keys = ["name", "aliases", "one_line", "first_appearance_chapter"]
            if card:
                for attr, label in CHARACTER_VALUES.items():
                    write_value(row, label, getattr(card, attr))
                    keys.append(f"value:{label}")
                write_value(row, "实力与地位", card.now.power)
                keys.append("value:实力与地位")
                row.location, row.condition, row.want, row.is_alive = (
                    card.now.location,
                    card.now.condition,
                    card.now.want,
                    card.now.alive,
                )
                keys.extend(["location", "condition", "want", "is_alive"])
                moments = [m for m in card.moments if 1 <= m.chapter <= self.upto]
                write_value(
                    row,
                    "名场面",
                    "\n".join(f"第 {m.chapter} 章：{m.what}——立住了{moment_shows(m.shows)}" for m in moments),
                )
                keys.append("value:名场面")
                self.missing.extend(card.missing)
            else:
                row.role_type = "配角"
                keys.append("value:定位")
            await session.flush()
            await record_version(session, book.id, "character", row, "teardown", "拆书整理设定", before=before)
            state["rows"][key] = {"id": str(row.id), "hash": row_hash(row, keys), "keys": keys}
            if user:
                self.save_input(
                    state,
                    f"card:{person['key_name']}",
                    user,
                    values,
                    missing=[*call_missing, *(card.missing if card else [])],
                )
            book.teardown = {**(book.teardown or {}), "names": names}
            self.save_state(book, state)
            if card:
                state["pending_ties"][str(row.id)] = [tie.model_dump() for tie in card.ties]
                self.save_state(book, state)
            await session.commit()
            # 供势力使用的名字是卡上认定的，不是重名时为了唯一性加的显示后缀。
            if canonical_name != person["name"]:
                person["aliases"] = list(dict.fromkeys([*person["aliases"], person["name"]]))
                person["name"] = canonical_name
            return row

    async def world(self, job, result):
        from app.services.teardown_world import merge_world_overviews, world_rows

        rows = world_rows(result, job.kind, self.upto)
        self.missing.extend(result.missing)
        async with self.runner.sm() as session:
            book = await self.book(session)
            state = self.state(book)
            for item in rows:
                if item.name == "世界概况" and item.category == "世界与地图":
                    state["overviews"][job.key] = item.values.get("内容", "")
                    item.values["内容"] = merge_world_overviews(state["overviews"])
                info = state["rows"].get(item.key)
                row = await session.get(WorldEntry, uuid.UUID(info["id"])) if info else None
                if info and row is None or row is not None and self.protected(row, info):
                    self.skipped_name(row.name if row is not None else item.name)
                    continue
                before = snapshot_of(row) if row is not None else None
                if row is None:
                    name = item.name
                    existing = set(
                        await session.scalars(
                            select(WorldEntry.name).where(
                                WorldEntry.book_id == book.id,
                                WorldEntry.category == item.category,
                            )
                        )
                    )
                    if name in existing:
                        name += "（拆书）"
                        base, number = name, 2
                        while name in existing:
                            name = f"{base}（{number}）"
                            number += 1
                    row = WorldEntry(book_id=book.id, category=item.category, name=name, source="teardown")
                    session.add(row)
                row.aliases, row.created_chapter = list(item.aliases), item.created_chapter
                row.source = "teardown"
                keys = ["name", "aliases", "created_chapter"]
                if item.levels is not None:
                    row.style, row.levels = "ladder", item.levels
                    row.content = item.values.get("总说明", item.values.get("内容", ""))
                    keys.extend(["style", "levels", "content"])
                else:
                    row.style = "paragraph"
                    keys.append("style")
                    for label, value in item.values.items():
                        write_value(row, label, value)
                        keys.append(f"value:{label}")
                if item.category == "世界与地图" and item.name != "世界概况":
                    row.parent_id = None
                    keys.append("parent_id")
                await session.flush()
                await record_version(session, book.id, "entry", row, "teardown", "拆书整理设定", before=before)
                state["rows"][item.key] = {"id": str(row.id), "hash": row_hash(row, keys), "keys": keys}
                if item.category == "世界与地图" and item.name != "世界概况":
                    state["pending_parents"][item.key] = item.parent
            self.save_input(state, job.key, job.user, job.values, missing=result.missing)
            self.save_state(book, state)
            await session.commit()

    async def merits(self, result, *, user: str, values: dict):
        """模型回答和离线试整理结果共用同一写库入口。"""
        async with self.runner.sm() as session:
            book = await self.book(session)
            state = self.state(book)
            book.teardown = {
                **(book.teardown or {}),
                "merits": {
                    "upto": self.upto,
                    "at": datetime.now(UTC).isoformat(),
                    "points": [point.model_dump() for point in result.points],
                    "missing": result.missing,
                },
            }
            self.save_input(state, "merits", user, values, missing=result.missing)
            self.save_state(book, state)
            await session.commit()
        self.missing.extend(result.missing)

    async def link_parents(self):
        async with self.runner.sm() as session:
            book = await self.book(session)
            state = self.state(book)
            places = list(
                await session.scalars(
                    select(WorldEntry).where(
                        WorldEntry.book_id == book.id,
                        WorldEntry.category == "世界与地图",
                    )
                )
            )
            by_id = {str(row.id): row for row in places}
            for key, parent_name in state["pending_parents"].items():
                info = state["rows"].get(key)
                row = by_id.get(info["id"]) if info else None
                if row is None or self.protected(row, info):
                    continue
                matches = [p for p in places if p.name == parent_name or parent_name in (p.aliases or [])]
                # 原文名字撞上作者条目时，归属优先连本次拆书创建的那条区分名。
                parent_info = state["rows"].get(f"entry:地点列表:{parent_name}")
                owned_parent = by_id.get(parent_info["id"]) if parent_info else None
                parent = owned_parent or (matches[0] if len(matches) == 1 and parent_name else None)
                # 模型的循环归属不能写成循环树，也不能把自己挂给自己。
                seen = {row.id}
                current = parent
                while current is not None and current.id not in seen:
                    seen.add(current.id)
                    current = by_id.get(str(current.parent_id))
                if current is not None:
                    parent = None
                target_id = parent.id if parent else None
                if row.parent_id != target_id:
                    row.parent_id = target_id
                    info["hash"] = row_hash(row, info["keys"])
                    # 同次整理只有一个版本，补上挂树后的最终快照。
                    from app.models.library import SettingVersion

                    version = await session.scalar(
                        select(SettingVersion)
                        .where(
                            SettingVersion.book_id == book.id,
                            SettingVersion.target_type == "entry",
                            SettingVersion.target_id == row.id,
                        )
                        .order_by(SettingVersion.version.desc())
                        .limit(1)
                    )
                    if version is not None and version.source == "teardown":
                        version.snapshot = snapshot_of(row)
            state["pending_parents"] = {}
            self.save_state(book, state)
            await session.commit()

    async def link_relationships(self):
        async with self.runner.sm() as session:
            book = await self.book(session)
            state = self.state(book)
            characters = list(await session.scalars(select(Character).where(Character.book_id == book.id)))
            by_id = {str(row.id): row for row in characters}
            relationships = list(await session.scalars(select(Relationship).where(Relationship.book_id == book.id)))
            for source_id, tie_rows in state["pending_ties"].items():
                source = by_id.get(source_id)
                if source is None:
                    continue
                info = next((info for info in state["rows"].values() if info["id"] == source_id), None)
                if self.protected(source, info):
                    continue
                for tie_row in tie_rows:
                    tie = s.TeardownTie.model_validate(tie_row)
                    tokens = [name.strip() for name in re.split(r"[/、]", tie.who) if name.strip()]
                    targets = [p for p in characters if any(n == p.name or n in (p.aliases or []) for n in tokens)]
                    for target in targets:
                        if target.id == source.id:
                            continue
                        pair = ":".join(sorted([str(source.id), str(target.id)]))
                        info = state["relationships"].get(pair)
                        own = next((r for r in relationships if info and str(r.id) == info["id"]), None)
                        same = [r for r in relationships if {r.source_id, r.target_id} == {source.id, target.id}]
                        if own is None and same:
                            continue
                        if (
                            own is not None
                            and data_hash([own.kind, own.description, own.since_chapter]) != info["hash"]
                        ):
                            continue
                        if own is None:
                            own = Relationship(book_id=book.id, source_id=source.id, target_id=target.id)
                            session.add(own)
                            relationships.append(own)
                        own.kind, own.description = tie.relation[:50], tie.relation
                        own.since_chapter = (
                            tie.since_chapter if tie.since_chapter and 1 <= tie.since_chapter <= self.upto else None
                        )
                        await session.flush()
                        state["relationships"][pair] = {
                            "id": str(own.id),
                            "hash": data_hash([own.kind, own.description, own.since_chapter]),
                        }
            state["pending_ties"] = {}
            self.save_state(book, state)
            await session.commit()


def input_unchanged(state: dict, key: str, template: str, values: dict, *, force=False) -> bool:
    if force:
        return False
    previous = state.get("inputs", {}).get(key)
    if previous is None:
        return False
    # inputs 始终是实际发给模型的 user 的 SHA1。全局的书名/整理范围不算新人物记录，
    # 用这个调用上次的外壳回放当前材料；不能拿全书上一次 upto 误判很久没出场的人。
    context = state.get("contexts", {}).get(
        key, {"title": values["title"], "last": str(state.get("upto", values["last"]))}
    )
    if values.get("_evidence") and context.get("evidence") == values["_evidence"]:
        return True
    replay = {**values, **{key: value for key, value in context.items() if key in ("title", "last")}}
    return text_hash(render(template, **replay)) == previous


def reads_of(chapters, upto: int) -> list[dict]:
    return [
        {
            **(c.teardown or {}).get("read", {}),
            "index": c.index,
            "summary": c.summary or "",
            "cool_point": (c.outline or {}).get("cool_point", ""),
            "hook": (c.outline or {}).get("hook", ""),
        }
        for c in chapters
        if c.index <= upto and (c.teardown or {}).get("read_version") is not None
    ]


async def run_parallel(coroutines) -> None:
    """取消或致命异常必须等所有兄弟调用退出，不能让收尾先清掉取消标记。"""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        # gather 本身不会因一个子任务抛异常而取消其它任务；等待清理结束后，
        # 再原样抛 JobCancelled/CancelledError，避免 ExceptionGroup 改变调用方语义。
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def write_positions(session, book, reads: list[dict]) -> None:
    """拆书的全部角色统一排序；位置不是作者内容 hash 的一部分。"""
    if book.source != "teardown":
        return
    roster, _, protagonist = people_of(reads, (book.teardown or {}).get("names"))
    rows = list(await session.scalars(select(Character).where(Character.book_id == book.id)))
    owned = {
        info["id"]: key.removeprefix("character:")
        for key, info in SettingsWriter.state(book)["rows"].items()
        if key.startswith("character:")
    }

    def key(row):
        person = roster.find(row.name) or next(
            (p for p in roster.people if p["key_name"] == owned.get(str(row.id))), None
        )
        return (
            0 if person and person["name"] == protagonist and not owned.get(str(row.id), "").startswith("kept:") else 1,
            -len(person["chapters"]) if person else 0,
            person["first"] if person else (row.first_appearance_chapter or 10**9),
            person["order"] if person else 10**9,
            row.created_at,
            str(row.id),
        )

    for position, row in enumerate(sorted(rows, key=key)):
        row.position = position


async def collect_settings(runner, *, force=False) -> dict:
    """最多八个模型调用并行；单项失败不撤销已落库的结果，末尾给出可重试摘要。"""
    from app.services.teardown_merge import collect_merge
    from app.services.teardown_world import prepare_world_jobs

    await collect_merge(runner, force=force)
    book, chapters, _, _ = await runner.snapshot()
    if book is None or book.source != "teardown":
        raise JobCancelled()
    upto = max((c.index for c in chapters if (c.teardown or {}).get("read_version") is not None), default=0)
    writer = SettingsWriter(runner, upto)
    await writer.check()
    reads = reads_of(chapters, upto)
    roster, selected, protagonist = people_of(reads, (book.teardown or {}).get("names"))
    state = writer.state(book)
    reuse_character_keys(roster, state)
    semaphore = asyncio.Semaphore(8)
    progress_lock = asyncio.Lock()
    card_write_lock = asyncio.Lock()
    errors = []
    done, total = 0, 0

    async def progress(now):
        await runner.progress("settings", settings={"done": done, "total": total, "now": now})

    async def call(schema, user, purpose, now, store, *, key):
        nonlocal done
        async with semaphore:
            await writer.check()
            async with progress_lock:
                await progress(now)
            try:
                result = await runner.call_user(schema, user, purpose)
                await writer.check()
                await store(result)
                await runner.refresh(force=True)
            except (JobCancelled, asyncio.CancelledError):
                raise
            except Exception as exc:
                errors.append(f"{now}：{' '.join(str(exc).split())[:100] or '没有返回结果'}")
                async with runner.sm() as session:
                    current = await writer.book(session)
                    failed_state = writer.state(current)
                    failed_state["inputs"].pop(key, None)
                    writer.save_state(current, failed_state)
                    await session.commit()
            finally:
                async with progress_lock:
                    done += 1
                    await progress(now)

    async with runner.sm() as session:
        current = await writer.book(session)
        layouts = deepcopy(current.card_layouts or {})
        if "角色列表" not in layouts:
            facts, sections = DEFAULT_FIELDS["角色列表"]
            layouts["角色列表"] = {
                "facts": [{"key": name, "label": name} for name in facts],
                "sections": [{"key": name, "label": name} for name in [*sections, "名场面"]],
            }
            current.card_layouts = layouts
        world_jobs = await prepare_world_jobs(
            session,
            current,
            upto,
            reads,
            protagonist,
            [],
            only_kinds={"金手指", "等级", "地方", "物品功法", "秘密", "规矩"},
        )
        saved = writer.state(current)
        place_keys = {job.key for job in world_jobs if job.kind == "地方"}
        saved["overviews"] = {key: value for key, value in saved["overviews"].items() if key in place_keys}
        writer.save_state(current, saved)
        await session.commit()
    card_jobs = []
    for person in selected:
        if person["full"]:
            values = card_values(book.title, upto, person, protagonist)
            key = f"card:{person['key_name']}"
            if not input_unchanged(state, key, "teardown_card", values, force=force):
                card_jobs.append((person, values, render("teardown_card", **values)))
        else:
            info = state["rows"].get(f"character:{person['key_name']}")
            # 不经模型的一句话角色也只在自身证据变化时更新，不给同一结果重复记版本。
            signature = data_hash([person["name"], person["aliases"], person["note"], person["first"]])
            if force or not info or info.get("evidence") != signature:
                await writer.character(person)
                async with runner.sm() as session:
                    current = await writer.book(session)
                    saved = writer.state(current)
                    info = saved["rows"].get(f"character:{person['key_name']}")
                    if info:
                        info["evidence"] = signature
                    writer.save_state(current, saved)
                    await session.commit()
    world_jobs = [
        job for job in world_jobs if not input_unchanged(state, job.key, "teardown_world", job.values, force=force)
    ]
    # 势力先预留一个，拿到角色卡后再把准确的分批数量补进总数。
    total = len(card_jobs) + len(world_jobs) + 1
    await progress("角色卡")

    async def write_card(person, values, user, result):
        async with card_write_lock:
            await writer.character(person, result, user=user, values=values, roster=roster)

    async def write_world(job, result):
        await writer.world(job, result)

    tasks = [
        call(
            s.TeardownCard,
            user,
            "拆书：写角色卡",
            "角色卡",
            lambda result, p=person, v=values, u=user: write_card(p, v, u, result),
            key=f"card:{person['key_name']}",
        )
        for person, values, user in card_jobs
    ]
    tasks.extend(
        call(
            job.schema,
            job.user,
            f"拆书：整理{job.kind}",
            job.kind,
            lambda result, j=job: write_world(j, result),
            key=job.key,
        )
        for job in world_jobs
    )
    await run_parallel(tasks)
    await writer.check()
    # 卡上所属包括增量跳过的旧全卡；作者改过的所属也是当前库里的真值。
    async with runner.sm() as session:
        current = await session.get(Book, runner.book_id)
        state = writer.state(current)
        full_cards = []
        for person in selected:
            if person["full"]:
                info = state["rows"].get(f"character:{person['key_name']}")
                row = await session.get(Character, uuid.UUID(info["id"])) if info else None
                if row is not None:
                    full_cards.append({"name": person["name"], "belongs": value_of(row, "所属")})
        faction_jobs = await prepare_world_jobs(
            session, current, upto, reads, protagonist, full_cards, only_kinds={"势力"}
        )
    faction_jobs = [
        job for job in faction_jobs if not input_unchanged(state, job.key, "teardown_world", job.values, force=force)
    ]
    total += len(faction_jobs) - 1
    await run_parallel(
        call(
            job.schema,
            job.user,
            "拆书：整理势力",
            "势力",
            lambda result, j=job: write_world(j, result),
            key=job.key,
        )
        for job in faction_jobs
    )
    await writer.link_parents()
    await writer.link_relationships()

    await writer.check()
    await progress("整理设定")
    async with runner.sm() as session:
        current = await writer.book(session)
        saved = writer.state(current)
        # 每次调用各自记缺项，增量跳过的旧调用也不会把先前的警告丢掉。
        saved["missing"] = list(
            dict.fromkeys(
                [
                    *[item for context in saved["contexts"].values() for item in context.get("missing", [])],
                    *writer.missing,
                ]
            )
        )
        if not errors:
            saved.update(upto=upto, at=datetime.now(UTC).isoformat())
        writer.save_state(current, saved)
        await write_positions(session, current, reads)
        # 数的是当前实际还存在的拆书条目，不把作者条目或已删除行算进去。
        character_ids = {
            str(row) for row in await session.scalars(select(Character.id).where(Character.book_id == runner.book_id))
        }
        entry_ids = {
            str(row) for row in await session.scalars(select(WorldEntry.id).where(WorldEntry.book_id == runner.book_id))
        }
        result = {
            "characters": sum(
                key.startswith("character:") and info["id"] in character_ids for key, info in saved["rows"].items()
            ),
            "entries": sum(key.startswith("entry:") and info["id"] in entry_ids for key, info in saved["rows"].items()),
            "skipped": writer.skipped,
            "missing": saved["missing"],
        }
        await session.commit()
    await runner.refresh(force=True)
    if errors:
        raise SettingsIncomplete(result, errors)
    return result


async def estimate_calls(session, book) -> int:
    """重跑确认前显示的首轮调用数；这里不调用模型，也不修改任何数据。"""
    from sqlalchemy.orm import defer

    from app.models import Chapter
    from app.services.teardown_world import prepare_world_jobs

    chapters = list(
        await session.scalars(
            select(Chapter).where(Chapter.book_id == book.id).options(defer(Chapter.content)).order_by(Chapter.index)
        )
    )
    upto = max((c.index for c in chapters if (c.teardown or {}).get("read_version") is not None), default=0)
    reads = reads_of(chapters, upto)
    _, selected, protagonist = people_of(reads, (book.teardown or {}).get("names"))
    jobs = await prepare_world_jobs(session, book, upto, reads, protagonist, [])
    from app.services.teardown_merge import merge_batches

    roster, _, _ = people_of(reads, (book.teardown or {}).get("names"))
    return sum(person["full"] for person in selected) + len(jobs) + len(merge_batches(roster.people))
