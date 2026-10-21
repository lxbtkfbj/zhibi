"""拆书的七类设定：程序数原文、拼材料、检查章号并映射现有栏目。

原文只在数据库里按名字计数，不读回、不送给整理设定的模型；持久化与作者保护由
teardown_settings 统一处理。
"""

from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.models import Book, Chapter
from app.services.teardown_prompts import render
from app.services.teardown_roster import Roster

KINDS = ("金手指", "等级", "地方", "势力", "物品功法", "秘密", "规矩")
CATEGORIES = {
    "金手指": "金手指",
    "等级": "等级体系",
    "地方": "地点列表",
    "势力": "势力列表",
    "物品功法": "物品功法",
    "秘密": "往事秘密",
    "规矩": "特殊规则",
}
STORED_CATEGORIES = {
    "金手指": "金手指",
    "等级": "等级体系",
    "地方": "世界与地图",
    "势力": "势力划分",
    "物品功法": "物品与功法",
    "秘密": "往事与秘密",
    "规矩": "特殊规则",
}
KIND_RULES = {
    "等级": "等级按高低排，低的在前，一套等级一条（修炼境界、职位、品阶……分开写）；每一级写原文怎么说它；主角第几章到了这一级，看上面主角各章的变化，看不出就留空；怎么往上升、难在哪写进 how_up。",
    "金手指": "写清是什么、谁知道、能做什么、规矩和限制、代价、来历、第几章出现；后来陆续冒出来的本事，按章写进怎么变强。",
    "地方": "每个地方写它属于哪里（上一级地方的名字，要是上面列出的另一个地方；最大的留空）、第一次出现在第几章。再写一段世界概况（world）：什么时代，超凡的力量是公开的还是藏着的，普通人知道多少，钱用什么；只写记录里看得出的。",
    "势力": "写清什么组织、谁领头、地盘在哪、和主角是敌是友、第一次出现在第几章；成员只写上面「角色卡上写的所属」里有的人。",
    "物品功法": "写清是什么、品阶、有什么用、在谁手里、第一次出现在第几章。",
    "秘密": "同一个秘密分几次揭开的合成一条：写真相是什么、谁知道、第几章埋下、第几章揭开（还没揭开留空）；揭开不能早于埋下。",
    "规矩": "写清管什么、怎么运作、有什么限制和代价、第一次出现在第几章。",
}


@dataclass
class WorldJob:
    key: str
    kind: str
    user: str
    schema: type[BaseModel]
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class WorldRow:
    key: str
    category: str
    name: str
    values: dict[str, str]
    aliases: list[str] = field(default_factory=list)
    created_chapter: int | None = None
    levels: list[dict] | None = None
    parent: str = ""


def evenly[T](items: list[T], limit: int) -> list[T]:
    """均匀挑选，首尾都保留；只取已有行，不拆改模型记下的文字。"""
    if len(items) <= limit:
        return items
    if limit <= 1:
        return items[:limit]
    return [items[round(i * (len(items) - 1) / (limit - 1))] for i in range(limit)]


def groups_of(reads: list[dict], upto: int) -> dict[tuple[str, str], list[tuple[int, dict]]]:
    groups: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for chapter in sorted(reads, key=lambda c: c["index"]):
        if not 1 <= chapter["index"] <= upto:
            continue
        for thing in chapter.get("things", []):
            name, kind = thing["name"].strip(), thing["kind"]
            if name and kind in KINDS:
                groups.setdefault((kind, name), []).append((chapter["index"], thing))
    return groups


async def count_occurrences(
    session: AsyncSession, book_id, name: str, upto: int, records: list[tuple[int, dict]]
) -> int:
    """和搜原文一样用 strpos，一次查一个名字；单字按记录数，不误把通配符当名字。"""
    if len(name) < 2:
        return len({index for index, _ in records})
    return int(
        await session.scalar(
            select(func.count(Chapter.id)).where(
                Chapter.book_id == book_id,
                Chapter.index <= upto,
                func.strpos(Chapter.content, name) > 0,
            )
        )
        or 0
    )


def thing_line(name: str, count: int, records: list[tuple[int, dict]]) -> str:
    notes = []
    for index, thing in records:
        note = f"第 {index} 章：{thing.get('note', '')}"
        if thing.get("belongs"):
            note += f"（属于 {thing['belongs']}）"
        if thing.get("secret"):
            note += f"（{thing['secret']}）"
        notes.append(note)
    if len(notes) > 6:
        notes = [*notes[:3], "……", *notes[-3:]]
    return f"- {name}（原文里出现过 {count} 章，第一次在第 {records[0][0]} 章）：{'；'.join(notes)}"


def world_context(
    kind: str,
    reads: list[dict],
    protagonist: str,
    full_cards: list[dict],
    *,
    names: dict[str, str] | None = None,
) -> str:
    if kind == "等级":
        roster = Roster()
        roster.add(reads)
        names = names or {}

        def is_protagonist(person):
            entry = roster.find(person["name"].strip()) or roster.find(person.get("was", "").strip())
            name = entry["name"] if entry else person["name"].strip()
            return names.get(name, name) == protagonist

        changes = list(
            dict.fromkeys(
                (chapter["index"], person["change"])
                for chapter in sorted(reads, key=lambda c: c["index"])
                for person in chapter.get("people", [])
                if is_protagonist(person) and person.get("change")
            )
        )
        return (
            "主角各章的变化：\n" + "\n".join(f"- 第 {index} 章：{change}" for index, change in evenly(changes, 120))
            if changes
            else "主角各章的变化：（没有）"
        )
    if kind == "势力":
        cards = [card for card in full_cards if card.get("belongs")]
        return (
            "角色卡上写的所属：\n" + "\n".join(f"- {card['name']}：{card['belongs']}" for card in cards)
            if cards
            else "角色卡上写的所属：（没有）"
        )
    return ""


async def prepare_world_jobs(
    session: AsyncSession,
    book: Book,
    upto: int,
    reads: list[dict],
    protagonist: str,
    full_cards: list[dict],
    *,
    only_kinds: set[str] | None = None,
) -> list[WorldJob]:
    reads = [chapter for chapter in reads if 1 <= chapter["index"] <= upto]
    groups = groups_of(reads, upto)
    parents = [thing.get("belongs", "") for (kind, _), rows in groups.items() if kind == "地方" for _, thing in rows]
    schemas = {
        "等级": s.TeardownLadders,
        "金手指": s.TeardownGoldfingers,
        "地方": s.TeardownPlaces,
        "势力": s.TeardownFactions,
        "物品功法": s.TeardownItems,
        "秘密": s.TeardownSecrets,
        "规矩": s.TeardownRules,
    }
    jobs = []
    counts = {}
    for kind in KINDS:
        if only_kinds is not None and kind not in only_kinds:
            continue
        kept = []
        for (item_kind, name), records in groups.items():
            if item_kind != kind:
                continue
            if len(name) < 2:
                count = await count_occurrences(session, book.id, name, upto, records)
            else:
                if name not in counts:
                    counts[name] = await count_occurrences(session, book.id, name, upto, records)
                count = counts[name]
            parent_needed = kind == "地方" and any(name in parent for parent in parents)
            if count >= 2 or kind in ("金手指", "等级", "秘密") or parent_needed:
                kept.append((name, count, records))
        kept.sort(key=lambda item: item[2][0][0])
        for offset in range(0, len(kept), 60):
            values = dict(
                title=book.title,
                last=str(upto),
                protagonist=protagonist,
                kind=kind,
                things="\n".join(thing_line(name, count, rows) for name, count, rows in kept[offset : offset + 60]),
                context=world_context(kind, reads, protagonist, full_cards, names=(book.teardown or {}).get("names")),
                kind_rule=KIND_RULES[kind],
            )
            jobs.append(
                WorldJob(
                    key=f"world:{kind}:{offset // 60 + 1}",
                    kind=kind,
                    user=render("teardown_world", **values),
                    schema=schemas[kind],
                    values=values,
                )
            )
    return jobs


def valid_chapter(chapter: int | None, upto: int) -> int | None:
    return chapter if chapter is not None and 1 <= chapter <= upto else None


def validate_world_result(result: BaseModel, upto: int) -> None:
    for item in getattr(result, "items", []):
        if hasattr(item, "first_chapter"):
            item.first_chapter = valid_chapter(item.first_chapter, upto)
        if hasattr(item, "planted_chapter"):
            item.planted_chapter = valid_chapter(item.planted_chapter, upto)
            item.revealed_chapter = valid_chapter(item.revealed_chapter, upto)
            if (
                item.planted_chapter is not None
                and item.revealed_chapter is not None
                and item.revealed_chapter < item.planted_chapter
            ):
                item.revealed_chapter = None
                message = f"{item.name}：揭开的章号早于埋下，没写揭开"
                if message not in result.missing:
                    result.missing.append(message)
    for ladder in getattr(result, "ladders", []):
        for level in ladder.levels:
            level.protagonist_chapter = valid_chapter(level.protagonist_chapter, upto)


def world_rows(result: BaseModel, kind: str, upto: int) -> list[WorldRow]:
    """不触碰数据库；保留栏目名，把不同模型 schema 变成同一种保护写入材料。"""
    validate_world_result(result, upto)
    rows = []
    items = result.ladders if kind == "等级" else result.items
    for item in items:
        name = item.name.strip()
        if not name:
            continue
        values, levels = {}, None
        if kind == "等级":
            values = {"总说明": item.how_up}
            levels = [
                {
                    "name": level.name,
                    "text": level.note
                    + (f"（主角第 {level.protagonist_chapter} 章到）" if level.protagonist_chapter is not None else ""),
                    "protagonist_chapter": level.protagonist_chapter,
                }
                for level in item.levels
            ]
        elif kind == "金手指":
            values = dict(
                zip(
                    ("是什么", "谁知道", "能做什么", "规矩和限制", "代价", "怎么变强", "来历"),
                    (item.what, item.knowers, item.can, item.rules, item.cost, item.grows, item.origin),
                    strict=True,
                )
            )
        elif kind == "地方" or kind == "规矩":
            values = {"内容": item.note}
        elif kind == "势力":
            values = {
                "领头的": item.leader,
                "对主角": item.stance,
                "地盘": item.turf,
                "内容": item.note + ("\n成员：" + "、".join(item.members) if item.members else ""),
            }
        elif kind == "物品功法":
            values = {"品阶": item.grade, "在谁手里": item.holder, "内容": item.note}
        elif kind == "秘密":
            values = {
                "谁知道": item.knowers,
                "打算何时揭开": (
                    f"第 {item.revealed_chapter} 章揭开"
                    if item.revealed_chapter is not None
                    else f"到第 {upto} 章还没揭开"
                ),
                "内容": item.truth
                + (f"\n第 {item.planted_chapter} 章埋下" if item.planted_chapter is not None else ""),
            }
        aliases = list(
            dict.fromkeys(
                alias.strip() for alias in getattr(item, "aliases", []) if alias.strip() != name and alias.strip()
            )
        )
        rows.append(
            WorldRow(
                key=f"entry:{CATEGORIES[kind]}:{name}",
                category=STORED_CATEGORIES[kind],
                name=name,
                values=values,
                aliases=aliases,
                created_chapter=getattr(item, "first_chapter", getattr(item, "planted_chapter", None)),
                levels=levels,
                parent=item.parent.strip() if kind == "地方" else "",
            )
        )
    if kind == "地方" and result.world:
        rows.append(WorldRow("entry:世界概况:世界概况", "世界与地图", "世界概况", {"内容": result.world}))
    return rows


def resolve_place_parents(rows: list[WorldRow]) -> dict[str, str | None]:
    """同类名字或别名匹配，拒绝自挂与成环；返回行键，持久化时再换成真实 id。"""
    places = [row for row in rows if row.category == "世界与地图" and row.name != "世界概况"]
    names: dict[str, set[str]] = {}
    for row in places:
        for name in [row.name, *row.aliases]:
            names.setdefault(name, set()).add(row.key)
    parents = {
        row.key: next(iter(names[row.parent])) if len(names.get(row.parent, set())) == 1 else None for row in places
    }
    for key, parent in list(parents.items()):
        seen = {key}
        while parent is not None:
            if parent in seen:
                parents[key] = None
                break
            seen.add(parent)
            parent = parents.get(parent)
    return parents


def merge_world_overviews(parts: dict[str, str]) -> str:
    """地方分批时合并本轮的概况，按批次顺序而非返回顺序，重复整段只留一次。"""
    ordered = sorted(parts, key=lambda key: int(key.rsplit(":", 1)[-1]))
    return "\n".join(dict.fromkeys(parts[key].strip() for key in ordered if parts[key].strip()))
