"""群聊只读翻拆过的书：每句话固定书目，按需查精髓、卡片、期待和原文。"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator
from sqlalchemy import func, select

from app.agents.context import foreshadow_code, format_foreshadowing
from app.agents.schemas import Lenient
from app.models import Book, Chapter, Character
from app.services.library_context import load_context
from app.services.outline_write import chapter_fields
from app.services.setup_store import load_ledger
from app.services.teardown_essence import SECTIONS

DESCRIPTION = (
    "查作者拆过的书。这些是别人写好的小说，作者导入后拆过，拿来学人家怎么写，不是作者正在写的这本。"
    "能查四样：精髓（拆出来的写法，还有人物的人设模板）；设定（人物、金手指、等级、地方、势力、物品、秘密的卡片）；"
    "读者在等的事（书里立下、兑现的期待和伏笔，带章号：结下的仇谁报了、立下的约兑现没有、埋的秘密哪章揭开，都记在这里）；"
    "原文（搜一个词在哪几章出现，或者看第几章写了什么）。"
)
BOOK_DESCRIPTION = "哪本书，照上面的书名写，不带书名号"
LOOK_DESCRIPTION = (
    "查哪一样。问书里谁做了什么、结的仇报了没有、立的约兑现没有、秘密在哪章揭开，先查「读者在等的事」，"
    "比搜原文准；要找原话，或者某个词在哪几章，再搜「原文」。"
)
WORDS_DESCRIPTION = (
    "查什么，一次最多 5 个。精髓：写目录里的节名（整节都给你），或者一条的招式名（冒号前面那几个字），"
    "或者人物名（看他的人设模板）；不写就给核心要点。设定：写名字。读者在等的事：写关键词，比如「下毒」「三年」，"
    "或者编号，比如「E2」；不写就列出到最后还吊着的。原文：写要搜的词，越短越准；要看第几章写了什么，写「第 35 章」。"
)
LOOKS = ["精髓", "设定", "读者在等的事", "原文"]


class LookUpTeardown(Lenient):
    book: str = Field(description=BOOK_DESCRIPTION)
    look: Literal["精髓", "设定", "读者在等的事", "原文"] = Field(description=LOOK_DESCRIPTION)
    words: list[str] = Field(default_factory=list, description=WORDS_DESCRIPTION)

    @field_validator("words", mode="before")
    @classmethod
    def one_word(cls, value):
        # Lenient 先还原 JSON 数组；没写成 JSON 的普通字符串也当成一个词。
        return [value] if isinstance(value, str) else value

    @field_validator("words")
    @classmethod
    def clean_words(cls, value):
        words = [re.sub(r"^[\s「」《》]+|[\s「」《》]+$", "", word) for word in value]
        return [word for word in words if word][:5]


@dataclass(frozen=True)
class CatalogEntry:
    id: uuid.UUID
    title: str
    created_at: datetime
    chapters: int
    essence: dict
    waits: dict | None


async def load_catalog(session) -> list[CatalogEntry]:
    """只取需要的 JSON 路径；不载入大列 teardown，也不载入精髓里的 rails 等材料。"""
    chapters = select(func.count(Chapter.id)).where(Chapter.book_id == Book.id).scalar_subquery()
    rows = await session.execute(
        select(
            Book.id,
            Book.title,
            Book.created_at,
            chapters.label("chapters"),
            Book.teardown["essence"]["upto"].label("upto"),
            Book.teardown["essence"]["overview"].label("overview"),
            Book.teardown["essence"]["sections"].label("sections"),
            Book.teardown.has_key("waits").label("has_waits"),
            Book.teardown["waits"]["upto"].label("waits_upto"),
            Book.teardown["waits"]["total"].label("waits_total"),
        )
        .where(Book.source == "teardown")
        .order_by(Book.created_at, Book.id)
    )
    by_title = {}
    for row in rows:
        if not (row.overview or {}).get("points"):
            continue
        item = CatalogEntry(
            id=row.id,
            title=row.title,
            created_at=row.created_at,
            chapters=row.chapters,
            essence={"upto": row.upto or 0, "overview": row.overview, "sections": row.sections or {}},
            waits={"upto": row.waits_upto or 0, "total": row.waits_total or 0} if row.has_waits else None,
        )
        previous = by_title.get(item.title)
        if previous is None or (item.chapters, item.created_at) >= (previous.chapters, previous.created_at):
            by_title[item.title] = item
    return sorted(by_title.values(), key=lambda item: (item.created_at, str(item.id)))


def catalog_text(catalog) -> str:
    lines = []
    for book in catalog:
        essence = book.essence
        overview = essence["overview"]
        partial = f"，精髓只整理到第 {essence['upto']} 章" if essence["upto"] < book.chapters else ""
        lines.append(f"《{book.title}》{book.chapters} 章{partial}。{overview.get('genre', '')}")
        lines.append("- 核心要点：" + "".join(f"「{point['title']}」" for point in overview["points"]))
        for key, (name, _) in SECTIONS.items():
            section = essence["sections"].get(key) or {}
            points = section.get("points") or []
            figures = section.get("figures") or [] if key == "cast" else []
            if not points and not figures:
                continue
            cast = "、".join(f"{figure['name']}（{figure['archetype']}）" for figure in figures)
            titles = "".join(f"「{point['title']}」" for point in points)
            lines.append(f"- {name}：" + (cast + "；" if cast else "") + titles)
    return "\n".join(lines)


def tool_spec(catalog) -> dict | None:
    if not catalog:
        return None
    return {
        "type": "function",
        "function": {
            "name": "look_up_teardown",
            "description": DESCRIPTION + "\n拆过的书和它们精髓的目录：\n" + catalog_text(catalog),
            "parameters": {
                "type": "object",
                "properties": {
                    "book": {
                        "type": "string",
                        "enum": [book.title for book in catalog],
                        "description": BOOK_DESCRIPTION,
                    },
                    "look": {"type": "string", "enum": LOOKS, "description": LOOK_DESCRIPTION},
                    "words": {"type": "array", "items": {"type": "string"}, "description": WORDS_DESCRIPTION},
                },
                "required": ["book", "look"],
            },
        },
    }


def resolve_book(catalog, title: str) -> CatalogEntry | None:
    if exact := next((book for book in catalog if book.title == title), None):
        return exact
    normalized = re.sub(r"[《》\s]", "", title)
    return next((book for book in catalog if re.sub(r"[《》\s]", "", book.title) == normalized), None)


def doing_of(args: LookUpTeardown, catalog) -> str:
    book = resolve_book(catalog, args.book)
    if book is None:
        return "在查拆过的书……"
    return {
        "精髓": f"在翻《{book.title}》的精髓……",
        "设定": f"在查《{book.title}》的设定……",
        "读者在等的事": f"在查《{book.title}》读者在等的事……",
        "原文": f"在翻《{book.title}》的原文……",
    }[args.look]


def _point(section: str, point: dict) -> str:
    lines = [f"【{section}】{point['title']}", "怎么用："]
    lines.extend(f"{index}. {step}" for index, step in enumerate(point.get("steps") or [], 1))
    lines.append(f"书里的证据：{point.get('evidence', '')}")
    if point.get("note"):
        lines.append(f"要注意：{point['note']}")
    lines.append("见第 " + "、".join(str(chapter) for chapter in point.get("chapters") or []) + " 章")
    return "\n".join(lines)


def _figure(figure: dict) -> str:
    lines = [
        f"【配角与对手】{figure['name']}：{figure['archetype']}",
        f"怎么立起来：{figure.get('build', '')}",
        f"在剧情里起什么作用：{figure.get('role', '')}",
    ]
    if figure.get("arc"):
        lines.append(f"怎么变：{figure['arc']}")
    lines.append("见第 " + "、".join(str(chapter) for chapter in figure.get("chapters") or []) + " 章")
    return "\n".join(lines)


def _figures(essence: dict) -> list[dict]:
    return (essence.get("sections", {}).get("cast") or {}).get("figures") or []


def essence_text(essence: dict, word: str) -> str:
    overview = essence["overview"]
    if word == "核心要点":
        blocks = [
            f"【核心要点】\n这是一本什么书：{overview.get('genre', '')}\n靠什么让人一直追：{overview.get('engine', '')}"
        ]
        blocks.extend(_point("核心要点", point) for point in overview.get("points") or [])
        return "\n\n".join(blocks)
    for key, (name, _) in SECTIONS.items():
        if word != name:
            continue
        section = essence["sections"].get(key) or {}
        blocks = [_figure(figure) for figure in _figures(essence)] if key == "cast" else []
        blocks.extend(_point(name, point) for point in section.get("points") or [])
        if section.get("missing"):
            blocks.append("这一节拆书时没看出来的：" + "；".join(section["missing"]))
        return "\n\n".join(blocks) or f"【{name}】"
    matches, seen = [], set()
    sections = [("核心要点", overview)] + [
        (name, essence["sections"].get(key) or {}) for key, (name, _) in SECTIONS.items()
    ]
    for name, section in sections:
        for point in section.get("points") or []:
            identity = point["title"], tuple(point.get("steps") or [])
            if word in point["title"] and identity not in seen:
                matches.append(_point(name, point))
                seen.add(identity)
    if matches:
        return "\n\n".join(matches)
    figures = [figure for figure in _figures(essence) if word in figure["name"] or word in figure["archetype"]]
    if figures:
        return "\n\n".join(_figure(figure) for figure in figures)
    return f"精髓里没有「{word}」：写目录里的节名、招式名，或者人物名。"


def _waits_text(ledger: list[dict], word: str = "") -> str:
    if re.fullmatch(r"[EF]\d+", word, re.IGNORECASE):
        found = next((item for item in ledger if foreshadow_code(item) == word.upper()), None)
        return format_foreshadowing(found) if found else f"没有「{word}」这一件。"
    if word:
        matches = [
            item
            for item in ledger
            if any(word in (item.get(key) or "") for key in ("description", "plant_plan", "payoff_plan"))
        ]
        if not matches:
            return f"没有提到「{word}」的：换个说法，或者到原文里搜。"
        count, lines = 8, []
    else:
        matches = [item for item in ledger if item.get("status") in ("planned", "planted")]
        if not matches:
            return "没有还吊着的。"
        count, lines = 20, ["到最后还吊着的："]
    lines.extend(format_foreshadowing(item) for item in matches[:count])
    if extra := matches[count:]:
        mention = f"也提到「{word}」" if word else ""
        lines.append(
            f"还有 {len(extra)} 件{mention}："
            + "、".join(foreshadow_code(item) for item in extra)
            + "（要细节写编号再查）"
        )
    return "\n".join(lines)


async def _chapter_text(session, book: CatalogEntry, index: int) -> str:
    # 这里只看章纲和摘要，不把整章原文和拆书记录读出来。
    row = (
        await session.execute(
            select(Chapter.index, Chapter.title, Chapter.outline, Chapter.summary).where(
                Chapter.book_id == book.id, Chapter.index == index
            )
        )
    ).first()
    if row is None:
        return f"没有第 {index} 章。"
    lines = [f"第 {row.index} 章《{row.title}》"]
    if fields := {key: value for key, value in chapter_fields(row).items() if value}:
        lines.append("章纲：\n" + "\n".join(f"{key}：{value}" for key, value in fields.items()))
    if row.summary:
        lines.append(f"摘要：{row.summary}")
    return "\n".join(lines)


async def look_up(session, catalog, args: LookUpTeardown) -> tuple[str, str]:
    # chat_tools 把动态工具接到现有分派；局部导入复用截断与搜索，避免循环导入。
    from app.services.chat_tools import clip, search_text

    book = resolve_book(catalog, args.book)
    if book is None:
        books = "".join(f"《{item.title}》" for item in catalog)
        return (
            f"拆过的书「{args.book}」",
            f"没有这本拆过的书：「{args.book}」。拆过的有：{books}，book 照工具说明里的书名写。",
        )
    words = args.words
    blocks, labels = [], list(words)
    if args.look == "精髓":
        labels = words or ["核心要点"]
        header = f"《{book.title}》精髓：拆书时从前 {book.essence['upto']} 章整理的，章号是原书的。"
        blocks = [clip(essence_text(book.essence, word), 3000) for word in labels]
    elif args.look == "设定":
        header = f"《{book.title}》设定：拆书时从原文整理的卡片。"
        if not words:
            blocks = ["没说要查谁。"]
        else:
            # 卡片格式只用书的 id；不为查卡片重新加载 Book（尤其是 teardown 大列）。
            ctx = await load_context(session, Book(id=book.id, title=book.title, source="teardown"))
            labels = []
            for word in words:
                target = ctx.find_target(word)
                labels.append(target.name if target is not None else word)
                if target is None:
                    text = f"设定里没有「{word}」：拆书时不是每个人、每样东西都写了卡，可以到原文里搜。"
                else:
                    text = ctx.entry_full_text(target)
                    if isinstance(target, Character):
                        names = [target.name, *(target.aliases or [])]
                        for figure in _figures(book.essence):
                            if figure["name"] in names:
                                text += f"\n精髓里的人设模板：{figure['archetype']}（怎么立起来，查精髓「{figure['name']}」）"
                blocks.append(clip(text))
    elif args.look == "读者在等的事":
        labels = words or ["还吊着的"]
        if book.waits is None:
            return f"《{book.title}》读者在等的事" + "".join(
                f"「{word}」" for word in labels
            ), f"《{book.title}》还没整理读者在等的事。"
        header = (
            f"《{book.title}》读者在等的事：拆书时整理到第 {book.waits['upto']} 章，一共 {book.waits['total']} 件。"
        )
        ledger = sorted(await load_ledger(session, book.id), key=lambda item: (item["seq"], foreshadow_code(item)))
        blocks = [clip(_waits_text(ledger, word)) for word in words or [""]]
    else:
        header = f"《{book.title}》原文：一共 {book.chapters} 章。"
        for word in words:
            match = re.fullmatch(r"第\s*(\d+)\s*章", word)
            if match:
                blocks.append(clip(await _chapter_text(session, book, int(match[1]))))
            else:
                # search_text 已经按词截过一次，不再截，保持与现有搜原文完全一致。
                blocks.append(await search_text(session, Book(id=book.id, source="teardown"), word))
        if not words:
            blocks = ["没说要搜什么。"]
    label = f"《{book.title}》{args.look}" + "".join(f"「{word}」" for word in labels)
    return label, header + "\n" + "\n\n".join(blocks)
