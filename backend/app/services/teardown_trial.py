"""装修验收：将旧试整理 JSON 适配为第三批模型回答，复用保护写入器。"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.agents import schemas as s
from app.models import Book, Character, Job, WorldEntry
from app.services.desk import DEFAULT_FIELDS
from app.services.teardown_digest import people_count, read_records
from app.services.teardown_roster import Roster
from app.services.teardown_settings import SettingsWriter
from app.services.teardown_world import WorldJob, world_rows


def ensure_trial_database(url: str) -> None:
    if (make_url(url).database or "").casefold() == "zhibi":
        raise ValueError("不能向日常库 zhibi 灌验收数据，请使用独立库")


def clean_trial(value):
    if isinstance(value, str):
        return "" if value.strip() == "（记录里没有）" else value
    if isinstance(value, list):
        return [clean_trial(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_trial(item) for key, item in value.items()}
    return value


def trial_card(card: dict, hero: str | None) -> s.TeardownCard:
    value = clean_trial(card)
    return s.TeardownCard.model_validate(
        {
            **value,
            "one_line": value.get("relation", ""),
            "role_type": "主角" if hero in [value["name"], *value.get("aliases", [])] else "配角",
            "now": {**value.get("now", {}), "power": value.get("power", "")},
        }
    )


def trial_world(world: dict) -> list[tuple[str, object]]:
    world = clean_trial(world.get("world", world))
    missing = world.get("missing", [])
    groups = [
        ("等级", s.TeardownLadders, {"ladders": world.get("ladders", [])}),
        ("金手指", s.TeardownGoldfingers, {"items": world.get("goldfingers", [])}),
        ("地方", s.TeardownPlaces, {"items": world.get("places", []), "world": world.get("overview", "")}),
        (
            "势力",
            s.TeardownFactions,
            {"items": [{**item, "note": item.get("note", item.get("what", ""))} for item in world.get("factions", [])]},
        ),
        ("物品功法", s.TeardownItems, {"items": world.get("items", [])}),
        ("秘密", s.TeardownSecrets, {"items": world.get("secrets", [])}),
        ("规矩", s.TeardownRules, {"items": world.get("rules", [])}),
    ]
    return [(kind, schema.model_validate({**values, "missing": missing})) for kind, schema, values in groups]


async def seed_trial(sm, book_id, directory: Path) -> dict:
    # 此处也检查绑定 URL；脚本入口在创建 engine 之前检查，两层均不先连日常库。
    async with sm() as session:
        ensure_trial_database(str(session.bind.url))
        book = await session.get(Book, book_id)
        if book is None or book.source != "teardown":
            raise ValueError("只能给独立库里已有的拆书灌验收数据")
        if await session.scalar(select(Job.id).where(Job.book_id == book_id, Job.status.in_(("queued", "running")))):
            raise ValueError("这本书有任务在跑，不能灌验收数据")
        records = await read_records(session, book_id)
        ranked = people_count(records, (book.teardown or {}).get("names") or {})
        hero = ranked[0]["name"] if ranked else None
        title = book.title
    cards = json.loads((directory / "cards.json").read_text(encoding="utf-8"))
    world = json.loads((directory / "world.json").read_text(encoding="utf-8"))
    merits = json.loads((directory / "merits.json").read_text(encoding="utf-8"))
    # 所有文件先完成验证，避免格式坏到一半才发现。
    converted = [(item, trial_card(item["card"], hero)) for item in cards if item.get("card")]
    world_results = trial_world(world)
    merits_result = s.TeardownMerits.model_validate(clean_trial(merits.get("merits", merits)))

    async def cancelled():
        return False

    runner = SimpleNamespace(sm=sm, book_id=book_id, cancelled=cancelled)
    writer = SettingsWriter(runner, 50)
    roster = Roster()
    for index, (item, card) in enumerate(converted):
        identity = {item["name"], card.name, *card.aliases}
        appearances = [
            chapter["index"]
            for chapter in records
            if chapter["index"] <= 50
            and any(
                person["name"].strip() in identity or person.get("was", "").strip() in identity
                for person in chapter["read"].get("people", [])
            )
        ]
        first = min(appearances, default=min((moment.chapter for moment in card.moments), default=1))
        roster.people.append(
            dict(
                name=item["name"],
                key_name=item["name"],
                aliases=card.aliases,
                first=first,
                order=index,
                chapters=set(appearances),
                note=card.one_line,
            )
        )
    async with sm() as session:
        book = await writer.book(session)
        if "角色列表" not in (book.card_layouts or {}):
            facts, sections = DEFAULT_FIELDS["角色列表"]
            book.card_layouts = {
                **(book.card_layouts or {}),
                "角色列表": {
                    "facts": [{"key": x, "label": x} for x in facts],
                    "sections": [{"key": x, "label": x} for x in [*sections, "名场面"]],
                },
            }
            await session.commit()
    for person, (_, card) in zip(roster.people, converted, strict=True):
        await writer.character(person, card, roster=roster)
    for kind, result in world_results:
        job = WorldJob(f"world:{kind}:1", kind, "离线试整理结果", type(result), {"title": title, "last": "50"})
        await writer.world(job, result)
    await writer.link_parents()
    await writer.link_relationships()
    await writer.merits(
        merits_result, user=merits.get("facts", "离线试整理结果"), values={"title": title, "last": "50"}
    )
    async with sm() as session:
        book = await writer.book(session)
        state = writer.state(book)
        # writer 保持生产环境原有排序；仅离线验收灌入按试验文件的数组顺序排列。
        # 通过 writer 的行键找本次受管条目，不靠同名匹配，也不挪动作者条目。
        ordered = [(Character, [f"character:{person['key_name']}" for person in roster.people])]
        ordered.extend(
            (WorldEntry, [row.key for row in world_rows(result, kind, 50)]) for kind, result in world_results
        )
        for model, keys in ordered:
            for position, key in enumerate(keys):
                info = state["rows"].get(key)
                row = await session.get(model, uuid.UUID(info["id"])) if info else None
                if row is not None and row.book_id == book.id and not writer.protected(row, info):
                    row.position = position
        state.update(upto=50, at=datetime.now(UTC).isoformat())
        writer.save_state(book, state)
        await session.commit()
    return {"cards": len(converted), "world_calls": len(world_results), "skipped": writer.skipped, "upto": 50}
