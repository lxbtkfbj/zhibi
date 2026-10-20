"""写卡前合并同一个人：沿用名单和作者改字保护，只改身份映射。"""

from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select

from app.agents.schemas import TeardownMerge
from app.graphs.deps import JobCancelled
from app.models import Character, Relationship
from app.prompts import render
from app.services.teardown_settings import SettingsWriter, people_of, reads_of, row_hash, text_hash


def merge_material(roster) -> str:
    """逐字沿用 analyze.merge_material，数据改取已经套 names 的名单。"""
    lines = []
    for person in sorted(roster.people, key=lambda p: (p["first"], p["order"])):
        name, chs = person["name"], sorted(person["chapters"])
        shown = [(index, row["shown"]) for index, row in person["rows"] if row.get("shown")]
        notes = (
            [f"第 {i} 章：{s[:60]}" for i, s in ([shown[0]] + ([shown[-1]] if len(chs) > 1 and len(shown) > 1 else []))]
            if shown
            else []
        )
        others = set(person["aliases"]) - {name}
        lines.append(
            f"【{name}】出场 {len(chs)} 章（第 {chs[0]}–{chs[-1]} 章）；别的叫法：{'、'.join(sorted(others)) or '没有'}；"
            + "；".join(notes)
        )
    return "\n".join(lines)


def merge_batches(people: list[dict]) -> list[list[dict]]:
    """每段最多 150 人，相邻两段重叠 30 人，不另开全是重叠人的尾段。"""
    people = sorted(people, key=lambda p: (p["first"], p["order"]))
    batches = []
    for first in range(0, len(people), 120):
        batches.append(people[first : first + 150])
        if first + 150 >= len(people):
            break
    return batches


def combine_groups(groups: list[dict]) -> list[dict]:
    """重叠分段的传递合并；以最早一组的 keep 和说明为准。"""
    combined = []
    for group in groups:
        hits = [i for i, old in enumerate(combined) if set(old["names"]) & set(group["names"])]
        if not hits:
            combined.append(deepcopy(group))
            continue
        first = hits[0]
        target = combined[first]
        target["names"] = list(
            dict.fromkeys(
                [
                    *target["names"],
                    *[name for i in hits[1:] for name in combined[i]["names"]],
                    *group["names"],
                ]
            )
        )
        if group.get("kept_card") or any(combined[i].get("kept_card") for i in hits):
            target["kept_card"] = True
        for i in reversed(hits[1:]):
            combined.pop(i)
    return combined


def valid_groups(result: TeardownMerge, roster) -> list[dict]:
    names = {person["name"].strip().casefold(): person["name"] for person in roster.people}
    groups = []
    for group in result.groups:
        tokens = [name.strip().casefold() for name in group.names]
        keep = group.keep.strip().casefold()
        if any(name not in names for name in tokens) or keep not in tokens:
            continue
        members = list(dict.fromkeys(names[name] for name in tokens))
        if len(members) < 2:
            continue
        groups.append({"names": members, "keep": names[keep], "why": group.why})
    return groups


def relationship_snapshot(relation) -> dict:
    return {
        column.name: value.isoformat()
        if isinstance(value, datetime)
        else str(value)
        if column.name in {"id", "book_id", "source_id", "target_id"}
        else deepcopy(value)
        for column in relation.__table__.columns
        for value in [getattr(relation, column.name)]
    }


def archive_relationship(state: dict, relation, original: dict) -> None:
    pair = ":".join(sorted([original["source_id"], original["target_id"]]))
    info = state["relationships"].get(pair)
    owned = info and info["id"] == str(relation.id)
    state.setdefault("merged_relationships", []).append(
        {"row": original, "state": {pair: deepcopy(info)} if owned else {}}
    )
    if owned:
        state["relationships"].pop(pair, None)


async def collect_merge(runner, *, force=False) -> dict:
    book, chapters, _, _ = await runner.snapshot()
    if book is None or book.source != "teardown":
        raise JobCancelled()
    upto = max((c.index for c in chapters if (c.teardown or {}).get("read_version") is not None), default=0)
    writer = SettingsWriter(runner, upto)
    await writer.check()
    reads = reads_of(chapters, upto)
    roster, _, _ = people_of(reads, (book.teardown or {}).get("names"))
    material = merge_material(roster)
    signature = text_hash(material)
    old = (book.teardown or {}).get("merges") or {}
    if not force and old.get("inputs") == signature:
        return deepcopy(old)
    batches = merge_batches(roster.people)
    groups = []
    system = render(
        "persona_essence", title=book.title, upto=str(upto), total=str(len(chapters)), rules=render("rules")
    )
    for done, batch in enumerate(batches):
        await writer.check()
        await runner.progress("settings", settings={"done": done, "total": len(batches), "now": "合并同一个人"})
        subset = type(roster)()
        subset.people = batch
        result = await runner.call_user(
            TeardownMerge,
            render("teardown_merge", title=book.title, people=merge_material(subset)),
            "拆书：合并同一个人",
            system=system,
        )
        await writer.check()
        groups.extend(valid_groups(result, roster))
    groups = combine_groups(groups)
    async with runner.sm() as session:
        current = await writer.book(session)
        names = deepcopy((current.teardown or {}).get("names") or {})
        state = writer.state(current)
        rows = list(await session.scalars(select(Character).where(Character.book_id == current.id)))
        relationships = list(await session.scalars(select(Relationship).where(Relationship.book_id == current.id)))
        by_id = {str(row.id): row for row in rows}
        previous = {person["name"]: person for person in roster.people}
        survivor_info = {}
        for group in groups:
            keep = group["keep"]
            keep_key = "character:" + previous[keep]["key_name"]
            if keep_key in state["rows"]:
                survivor_info[keep] = deepcopy(state["rows"][keep_key])
            keep_info = state["rows"].get(keep_key)
            keep_row = by_id.get(keep_info["id"]) if keep_info else next((r for r in rows if r.name == keep), None)
            for name in group["names"]:
                if name != keep:
                    names[name] = keep
                    key = "character:" + previous[name]["key_name"]
                    info = state["rows"].get(key)
                    row = by_id.get(info["id"]) if info else next((r for r in rows if r.name == name), None)
                    if row is not None:
                        if writer.protected(row, info):
                            group["kept_card"] = True
                            # 作者改过的旧卡独立保留，不能再被合并主卡的稳定 key 认领。
                            if info:
                                state["rows"][f"character:kept:{row.id}"] = deepcopy(info)
                        else:
                            affected = [r for r in relationships if row.id in (r.source_id, r.target_id)]
                            if keep_row is None and keep_info:
                                # 主名卡曾被作者删除，不能为迁移关系复活；完整归档失去目标的边。
                                for relation in affected:
                                    await session.refresh(relation)
                                    archive_relationship(state, relation, relationship_snapshot(relation))
                                    relationships.remove(relation)
                                    await session.delete(relation)
                                affected = []
                            if affected and keep_row is None:
                                # 关系迁移必须和删旧卡同事务。先给主名一张受管占位卡，
                                # 后面的 SettingsWriter 会认领它，不能级联删作者关系。
                                keep_row = Character(book_id=current.id, name=keep, source="teardown")
                                session.add(keep_row)
                                await session.flush()
                                keys = ["name", "aliases", "one_line", "first_appearance_chapter"]
                                survivor_info[keep] = {
                                    "id": str(keep_row.id),
                                    "keys": keys,
                                    "hash": row_hash(keep_row, keys),
                                }
                                rows.append(keep_row)
                                by_id[str(keep_row.id)] = keep_row
                            for relation in affected:
                                await session.refresh(relation)
                                old_pair = ":".join(sorted([str(relation.source_id), str(relation.target_id)]))
                                original = relationship_snapshot(relation)
                                info = state["relationships"].get(old_pair)
                                if relation.source_id == row.id:
                                    relation.source_id = keep_row.id
                                if relation.target_id == row.id:
                                    relation.target_id = keep_row.id
                                if relation.source_id == relation.target_id:
                                    # 两个名字已认成同一人，原边不再成立；完整归档而非丢作者改字。
                                    archive_relationship(state, relation, original)
                                    relationships.remove(relation)
                                    await session.delete(relation)
                                    continue
                                new_pair = ":".join(sorted([str(relation.source_id), str(relation.target_id)]))
                                if info and info["id"] == str(relation.id):
                                    state["relationships"].pop(old_pair, None)
                                    # 保留原 hash（而非给作者改字重新盖章），让 link_relationships
                                    # 仍能认出这条关系已经由作者改过。
                                    if new_pair not in state["relationships"]:
                                        state["relationships"][new_pair] = info
                            # 先写端点再删旧卡，避免数据库 ON DELETE CASCADE 抢先删除。
                            await session.flush()
                            await session.delete(row)
                    state["rows"].pop(key, None)
                # 合并后证据改变，下一步必须重新写主卡；旧缓存不能挡住。
                card_key = "card:" + previous[name]["key_name"]
                state["inputs"].pop(card_key, None)
                state["contexts"].pop(card_key, None)
            state["rows"].pop(keep_key, None)
        merged, _, _ = people_of(reads, names)
        for person in merged.people:
            if person["name"] in survivor_info:
                state["rows"]["character:" + person["key_name"]] = survivor_info[person["name"]]

        def canonical(name):
            seen = set()
            while name in names and name not in seen:
                seen.add(name)
                name = names[name]
            return name

        history = combine_groups([*((current.teardown or {}).get("merges") or {}).get("groups", []), *groups])
        for group in history:
            group["keep"] = canonical(group["keep"])
        result = {"inputs": signature, "groups": history, "at": datetime.now(UTC).isoformat()}
        current.teardown = {**(current.teardown or {}), "names": names, "merges": result}
        writer.save_state(current, state)
        await session.commit()
    await runner.progress("settings", settings={"done": len(batches), "total": len(batches), "now": "合并同一个人"})
    await runner.refresh(force=True)
    return result


async def estimate_calls(session, book, *, force=False) -> int:
    """只估合并的分段数，不读取原文、不改数据库。"""
    from sqlalchemy.orm import defer

    from app.models import Chapter

    chapters = list(
        await session.scalars(
            select(Chapter).where(Chapter.book_id == book.id).options(defer(Chapter.content)).order_by(Chapter.index)
        )
    )
    upto = max((c.index for c in chapters if (c.teardown or {}).get("read_version") is not None), default=0)
    roster, _, _ = people_of(reads_of(chapters, upto), (book.teardown or {}).get("names"))
    signature = text_hash(merge_material(roster))
    if not force and ((book.teardown or {}).get("merges") or {}).get("inputs") == signature:
        return 0
    return len(merge_batches(roster.people))
