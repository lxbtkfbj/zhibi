"""聊天里接话的人能用的工具：查（设定卡、大纲一段、某一章、搜正文、伏笔信息差）和动手（只有一个，参数是一张清单）。
动手由程序把关：同一张卡、大纲同一段算一处，新建和记要求不算；一两处直接改，落笔交给现成的几套提示词
（改一栏、补齐、帮写、大纲帮写、记要求），改完消息下面给前后对照；三处以上或者要删东西，整理成方案卡。"""

import re
import uuid
from typing import Literal

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agents.context import format_ledger, format_secrets
from app.agents.schemas import Lenient, LibraryIntent
from app.models import Book, Chapter, Character, NodeAnchor, Relationship, WorldEntry
from app.prompts import handbooks
from app.services import book_saves, outline_structure
from app.services.chat_context import done_text
from app.services.group_notes import CONCEPT_NAMES, SAID, SHOWN, apply_with_change
from app.services.library_context import load_context
from app.services.outline_write import chapter_fields, current_text, find_target, resolve_outline_target
from app.services.setup_store import load_ledger, load_secrets
from app.services.versions import target_type_of

# 每份查到的资料、每处写进去的字，交回给模型时截到这么长
RESULT_LIMIT = 2000
# 一句话里直接动手最多这么多处，再多就整理成方案卡
DIRECT_LIMIT = 2
# 一句话里最多报几回清单
MAX_ACTS = 2


def clip(text: str, limit: int = RESULT_LIMIT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + f"……（后面还有 {len(text) - limit} 字，截掉了）"


# ---------- 查 ----------


class LookUpSettings(BaseModel):
    """查设定卡的全文（每一栏都在）。资料里只有名字和一句话、要细节时用。"""

    names: list[str] = Field(description="要查的条目或人物的名字，照设定库里的写法，一次最多 5 个")


class LookUpOutline(BaseModel):
    """查大纲上的一段：这一段的全文，连同它下面的卷、单元、章的标题和一句话。"""

    where: str = Field(
        description="查哪一段：「结局」「第 N 篇」「第 N 卷」「单元「名称」」「第 N 章」，或者篇、卷、单元的名字；「正在看的」是作者正在看的那一页"
    )


class ReadChapter(BaseModel):
    """看某一章：章纲和摘要；要看原文时一次给两千字左右，可以从第几个字开始往后翻。"""

    index: int = Field(ge=1, description="第几章")
    original: bool = Field(default=False, description="要不要看原文；只看章纲和摘要就不要")
    start: int = Field(default=0, ge=0, description="原文从第几个字开始看，往后翻时用")


class SearchText(BaseModel):
    """在已经写出来的正文里搜一个词（人名、地名、物品……）：在哪几章出现、第一次出现在哪、前后写了什么。"""

    word: str = Field(description="要搜的词，越短越准，比如人名")


class LookUpClues(BaseModel):
    """查伏笔、读者在等的期待、信息差（谁知道什么秘密）。不给编号就列出还开着的。"""

    codes: list[str] = Field(default_factory=list, description="编号，比如 F3、E2、S1；不知道编号就留空")


class ReadSkill(BaseModel):
    name: str


# ---------- 动手 ----------


class ChangeItem(Lenient):
    kind: Literal["改设定", "补齐", "给几个写法", "新建设定", "写大纲", "写作要求", "改简介", "删除"] = Field(
        description="做哪一种：改设定库里已有一条的某一栏，选「改设定」；把一条设定空着的栏目补上，选「补齐」；作者只说不满意、没说怎么改，给他三种写法挑，选「给几个写法」；在设定库里新写现在还没有的人物、地方、势力、物品、规矩……，选「新建设定」；把大纲上的一段（结局、某一篇、某一卷、某个单元、某一章）写出来或重写，选「写大纲」；以后规划、写作都要照着做的，选「写作要求」；改简介那段话，选「改简介」；删掉一张设定卡或大纲上还没开写的一段，选「删除」"
    )
    target: str = Field(
        default="",
        description="改哪一处：设定写那一条的名字，照设定库里的写法；大纲写「结局」「第 N 篇」「第 N 卷」「单元「名称」」「第 N 章」，作者正在看的那一页写「正在看的」；要写还没有的下一篇写「第 N 篇」。新建设定、写作要求、改简介留空",
    )
    part: str = Field(
        default="",
        description="改设定、给几个写法时写：改这一条的哪一栏，卡片上的栏目名（比如「性格与说话方式」「身世」），或者「名称」「一句话」；说不清就留空",
    )
    quote: str = Field(default="", description="只改其中一句时，把那一句从原文里照抄出来；否则留空")
    category: str = Field(
        default="", description="新建设定时写：放进哪一类，照设定库里的类名，比如「角色列表」「地点列表」"
    )
    new_names: list[str] = Field(
        default_factory=list, description="新建设定时写：要建的几条的名字；没定名字的留空，由设定师起名"
    )
    count: int = Field(default=1, ge=1, le=5, description="新建设定时写：建几条；写了名字的就是名字的条数")
    instruction: str = Field(
        default="",
        description="改成什么样、写成什么样：把作者的意思和商量好的具体内容写清楚，不看前面的对话也能照做；不要写「照刚才说的」",
    )
    requirement: str = Field(
        default="", description="写作要求时写：写成一句清楚的要求，说清做什么、不写理由，60 字以内"
    )
    scope: Literal["一直有效", "只管下一章", "只管这一卷", "只管下一卷"] = Field(
        default="一直有效", description="写作要求时写：作者说了只管下一章、这一卷、下一卷的照选，没说的选一直有效"
    )


class MakeChanges(BaseModel):
    """动手改书：把这次要做的改动列成一张清单，程序按顺序做，回给你每一处真正写进去的字。一两处直接改；三处以上或者要删东西，会整理成方案卡，作者点「按这个来」才改。"""

    items: list[ChangeItem] = Field(description="要做的改动，按先后排；同一张卡、大纲同一段的写成一条")
    title: str = Field(
        default="", description="给这批改动起个名字，4 到 10 个字，比如「陈默的身世」；变成方案卡时当标题"
    )


QUERY_TOOLS = {
    "look_up_settings": LookUpSettings,
    "look_up_outline": LookUpOutline,
    "read_chapter": ReadChapter,
    "search_text": SearchText,
    "look_up_clues": LookUpClues,
}
ACT_TOOLS = {"make_changes": MakeChanges}


def tool_specs(read_only: bool, *, skills: bool = True) -> list[dict]:
    """给模型的工具；只读的（只问不改、拆书）只有查的那几个。"""
    tools = QUERY_TOOLS if read_only else {**QUERY_TOOLS, **ACT_TOOLS}
    specs = []
    for name, model in tools.items():
        spec = convert_to_openai_tool(model)
        spec["function"]["name"] = name
        specs.append(spec)
    if skills and (skill := handbooks.tool_spec()) is not None:
        specs.append(skill)
    return specs


def doing_of(name: str, args: BaseModel) -> str:
    """回答框里那一行：在查什么、在改什么。"""
    if isinstance(args, ReadSkill):
        return f"在翻《{args.name}》"
    if isinstance(args, LookUpSettings):
        return f"在查{'、'.join(args.names[:5])}"
    if isinstance(args, LookUpOutline):
        return f"在查大纲上的{args.where}"
    if isinstance(args, ReadChapter):
        return f"在看第 {args.index} 章" + ("的原文" if args.original else "")
    if isinstance(args, SearchText):
        return f"在正文里搜「{args.word}」"
    if isinstance(args, LookUpClues):
        return "在查伏笔和信息差"
    return "在动手"


def item_doing(item: ChangeItem) -> str:
    return {
        "改设定": f"在改{item.target}" + (f"的{item.part}" if item.part else ""),
        "补齐": f"在补{item.target}空着的栏目",
        "给几个写法": f"在给{item.target}想三种写法",
        "新建设定": f"在新建{'、'.join(item.new_names) or item.category or '设定'}",
        "写大纲": f"在写{'正在看的这一段' if item.target in ('', '正在看的') else item.target}",
        "写作要求": "在记写作要求",
        "改简介": "在改简介",
        "删除": f"在删{item.target}",
    }[item.kind]


async def look_up(session, book: Book, name: str, args: BaseModel, viewing: dict | None) -> tuple[str, str]:
    """查的工具：返回 (给作者看的「查了：……」里那一项, 交回给模型的资料)。"""
    if isinstance(args, ReadSkill):
        return f"手册《{args.name}》", handbooks.read(args.name)
    if isinstance(args, LookUpSettings):
        ctx = await load_context(session, book)
        labels, blocks = [], []
        for asked in args.names[:5]:
            target = ctx.find_target(asked)
            if target is None:
                labels.append(asked)
                blocks.append(f"设定库里没有「{asked}」。")
                continue
            labels.append(target.name)
            blocks.append(clip(ctx.entry_full_text(target)))
        return "、".join(dict.fromkeys(labels)) or "设定", "\n\n".join(blocks) or "没说要查谁。"
    if isinstance(args, LookUpOutline):
        found = await resolve_outline_target(session, book, args.where, viewing)
        if found is None:
            return f"大纲 · {args.where}", f"大纲上没找到「{args.where}」。大纲上有哪些，见资料里的 <大纲>。"
        return f"大纲 · {found[2]}", clip(await outline_piece(session, book, found[0], found[1]))
    if isinstance(args, ReadChapter):
        return f"第 {args.index} 章", await chapter_text(session, book, args)
    if isinstance(args, SearchText):
        return f"搜「{args.word.strip()[:30]}」", await search_text(session, book, args.word)
    if isinstance(args, LookUpClues):
        return "伏笔和信息差", await clues_text(session, book, args.codes)
    raise ValueError(f"没有这个工具：{name}")


async def outline_piece(session, book: Book, target_type: str, target_id: str) -> str:
    """大纲上的一段：这一段的字，连同下面一层的标题和一句话。"""
    ctx = await load_context(session, book)
    state = await outline_structure.load_structure(session, book.id)
    target = await find_target(session, book, ctx, state, target_type, target_id)
    lines = [f"{target.name}", current_text(target)]
    row = target.row

    def first(text: str) -> str:
        line = re.split(r"(?<=[。！？!?])|\n", text or "", maxsplit=1)[0].strip()
        return line[:60] + ("…" if len(line) > 60 else "")

    if target.kind == "arc":
        below = [v for v in state.volumes if v.target_node_id == row.id]
        lines += [f"  第 {v.index} 卷「{v.title}」：{first(v.summary)}" for v in below] or ["  （这一篇还没分卷）"]
    elif target.kind == "volume":
        lines += [
            f"  单元 {u.index}「{u.title}」"
            + (f"（{u.chapter_count} 章）" if u.chapter_count else "")
            + f"：{first(u.summary)}"
            for u in state.own_units(row.id)
        ] or ["  （这一卷还没拆单元）"]
    elif target.kind == "unit":
        lines += [
            f"  第 {c.index} 章「{c.title}」：{first((c.outline or {}).get('goal', '') or c.summary)}"
            for c in state.own_chapters(row)
        ] or ["  （这个单元还没出章纲）"]
    elif target.kind == "chapter" and row.status == "final" and row.summary:
        lines.append(f"已经写完，摘要：{row.summary}")
    return "\n".join(lines)


STATUS_NAMES = {"final": "已定稿", "planned": "还没写"}


async def chapter_text(session, book: Book, args: ReadChapter) -> str:
    chapter = await session.scalar(select(Chapter).where(Chapter.book_id == book.id, Chapter.index == args.index))
    if chapter is None:
        return f"还没有第 {args.index} 章。"
    lines = [f"第 {chapter.index} 章《{chapter.title}》（{STATUS_NAMES.get(chapter.status, '写到一半')}）"]
    if fields := {k: v for k, v in chapter_fields(chapter).items() if v}:
        lines.append("章纲：\n" + "\n".join(f"{k}：{v}" for k, v in fields.items()))
    if chapter.summary:
        lines.append(f"摘要：{chapter.summary}")
    if args.original:
        content = chapter.content or ""
        if not content:
            lines.append("这一章还没写正文。")
        else:
            start = min(args.start, len(content))
            piece = content[start : start + RESULT_LIMIT]
            more = start + len(piece) < len(content)
            lines.append(
                f"原文（第 {start + 1}～{start + len(piece)} 字，全章 {len(content)} 字）：\n{piece}"
                + (f"\n……后面还有；要接着看，start 填 {start + len(piece)}" if more else "")
            )
    return "\n".join(lines)


async def search_text(session, book: Book, word: str) -> str:
    from app.services.text_search import search_original

    word = word.strip()[:30]
    if not word:
        return "没给要搜的词。"
    result = await search_original(session, book.id, word)
    rows = result["results"]
    if not rows:
        return f"原文里没有「{word}」。" if book.source == "teardown" else f"写出来的正文里没有「{word}」。"
    lines = [f"「{word}」在 {result['chapters']} 章里出现过，第一次在第 {rows[0]['index']} 章。"]
    for row in rows[:8]:
        lines.append(
            f"第 {row['index']} 章《{row['title']}》（{row['times']} 次），第一次出现前后：……{row['near'].strip()}……"
        )
    if len(rows) > 8:
        lines.append("还有：" + "、".join(f"第 {row['index']} 章" for row in rows[8:40]))
    return clip("\n".join(lines))


async def clues_text(session, book: Book, codes: list[str]) -> str:
    ledger = await load_ledger(session, book.id)
    secrets = await load_secrets(session, book.id)
    wanted = {code.strip().upper() for code in codes if code.strip()}
    if wanted:
        picked = [f for f in ledger if f"{'E' if f.get('kind') == '期待' else 'F'}{f['seq']}" in wanted]
        hidden = [s for s in secrets if f"S{s['seq']}" in wanted]
    else:
        picked = [f for f in ledger if f.get("status") in {"planned", "planted"}][:20]
        hidden = [s for s in secrets if s.get("status") == "hidden"][:20]
    if not picked and not hidden:
        return "没有对得上的伏笔、期待或信息差。" if wanted else "这本书还没有开着的伏笔、期待或信息差。"
    blocks = []
    if picked:
        blocks.append("伏笔和期待：\n" + format_ledger(picked))
    if hidden:
        blocks.append("信息差：\n" + format_secrets(hidden))
    return clip("\n\n".join(blocks))


# ---------- 动手：数处数、落笔、方案卡 ----------


def norm(text: str) -> str:
    return re.sub(r"（[^）]*）|\([^)]*\)|\s", "", text or "")


async def place_of(session, book: Book, item: ChangeItem, viewing: dict | None) -> tuple[str, bool]:
    """这一条动的是哪一处：(一处的记号, 算不算处数)。同一张卡、大纲同一段是同一处；新建、记要求不算处数。"""
    ctx = await load_context(session, book)
    if item.kind == "改简介" or (item.kind in ("改设定", "补齐", "给几个写法") and norm(item.target) in CONCEPT_NAMES):
        return "简介", True
    if item.kind in ("改设定", "补齐", "给几个写法"):
        target = ctx.find_target(item.target)
        return f"设定:{target.id if target else norm(item.target)}", True
    if item.kind == "新建设定":
        names = sorted(norm(n) for n in item.new_names if norm(n))
        return (
            "新建:" + "、".join(names)
        ) if names else f"新建:{norm(item.category)}:{item.instruction.strip()[:60]}", False
    if item.kind == "写作要求":
        return f"要求:{(item.requirement or item.instruction).strip()}", False
    if item.kind == "删除":
        target = ctx.find_target(item.target)
        if target is not None:
            return f"设定:{target.id}", True
    found = await resolve_outline_target(session, book, item.target or "正在看的", viewing)
    return (f"大纲:{found[0]}:{found[1]}" if found else f"大纲:{norm(item.target)}"), True


def to_intent(item: ChangeItem) -> LibraryIntent:
    if item.kind in ("改设定", "补齐", "给几个写法", "改简介"):
        mode = {"补齐": "补齐空着的", "给几个写法": "给几个写法"}.get(item.kind, "照作者的意思改")
        return LibraryIntent(
            kind="改设定",
            target_name="简介" if item.kind == "改简介" else item.target,
            part=item.part,
            quote=item.quote,
            mode=mode,
            instruction=item.instruction,
        )
    if item.kind == "新建设定":
        return LibraryIntent(
            kind="新建设定",
            category=item.category,
            new_names=item.new_names,
            count=max(item.count, len(item.new_names) or 1),
            instruction=item.instruction,
        )
    if item.kind == "写大纲":
        return LibraryIntent(kind="写大纲", outline_target=item.target or "正在看的", instruction=item.instruction)
    return LibraryIntent(kind="写作要求", requirement=item.requirement or item.instruction, scope=item.scope)


async def run_change(session, redis, message, item: ChangeItem) -> tuple[dict, list[str]]:
    """照清单里的一条去做（作者的那句话，或者方案卡的那一张）：返回 (这一处的结果, 编辑部本来要在群里说的话)。
    结果里有前后对照（diff）、换回要用的几行（change）、再改一版要用的判断（redo），和第二批聊天里改的一样。"""
    said: list[str] = []
    token = SAID.set(said)
    try:
        if item.kind == "删除":
            outcome = await delete_change(session, message, item)
        else:
            await apply_with_change(session, redis, message, to_intent(item))
            await session.refresh(message)
            outcome = dict((message.payload or {}).get("outcome") or {})
    finally:
        SAID.reset(token)
    return outcome, said


def result_text(item: ChangeItem, outcome: dict, said: list[str]) -> str:
    """交回给模型的：这一处真做成了什么、真正写进去的字。不只说「改好了」，不然模型会把打算当成结果说。"""
    kind = outcome.get("kind")
    head = f"「{item_doing(item).removeprefix('在')}」"
    if kind == "edit" and outcome.get("mode") == "options":
        return f"{head}：给「{outcome.get('target_label')}」出了三种写法，放在作者那句话下面等他挑；还没换上。"
    if kind in SHOWN or kind == "deleted":
        written = "\n".join(
            f"【{d['label']}】\n原来：{d['before'] or '（空着）'}\n现在：{d['after'] or '（删掉了）'}"
            for d in outcome.get("diff") or []
        )
        return clip(f"{head}做成了：{done_text(outcome)}。" + (f"真正写进去的：\n{written}" if written else ""))
    if kind == "failed":
        return f"{head}没做成：{outcome.get('reason') or '出错了'}，什么也没改。"
    words = done_text(outcome) or "没做成"
    return f"{head}：{words}。" + (" ".join(said) if kind == "not_found" else "")


# ---------- 删除（只在方案卡上，作者点「按这个来」才删） ----------


async def deletion_target(session, book: Book, words: str) -> tuple[str, str, str] | None:
    """要删的是哪一条：设定卡，或者大纲上的篇、卷、单元、章。返回 (类型, id, 叫法)。结局不能删。"""
    ctx = await load_context(session, book)
    target = ctx.find_target(words)
    if target is not None:
        return target_type_of(target), str(target.id), f"{ctx.category(target)['name']} · {target.name}"
    found = await resolve_outline_target(session, book, words, None)
    return found if found and found[0] != "book" else None


async def linked_of(session, book: Book, found: tuple[str, str, str]) -> str:
    """方案卡上写清删了会连带什么：关系、出场、下面的卷和章，正文里写到过的不跟着改。"""
    kind, target_id, _ = found
    parts = []
    if kind in ("character", "entry"):
        row = await session.get(Character if kind == "character" else WorldEntry, uuid.UUID(target_id))
        if kind == "character":
            relations = await session.scalar(
                select(func.count(Relationship.id)).where(
                    (Relationship.source_id == row.id) | (Relationship.target_id == row.id)
                )
            )
            anchors = await session.scalar(select(func.count(NodeAnchor.id)).where(NodeAnchor.character_id == row.id))
            if relations:
                parts.append(f"他的 {relations} 条关系一起删")
            if anchors:
                parts.append(f"大纲上 {anchors} 处人物锚点一起删")
        else:
            children = await session.scalar(select(func.count(WorldEntry.id)).where(WorldEntry.parent_id == row.id))
            if children:
                parts.append(f"属于它的 {children} 条不再有上级")
        chapters = list(
            await session.scalars(
                select(Chapter.index)
                .where(Chapter.book_id == book.id, func.strpos(Chapter.content, row.name) > 0)
                .order_by(Chapter.index)
                .limit(6)
            )
        )
        if chapters:
            parts.append(f"正文第 {'、'.join(map(str, chapters))} 章写到过，正文不跟着改")
    else:
        state = await outline_structure.load_structure(session, book.id)
        if kind == "segment":
            volumes = [v for v in state.volumes if str(v.target_node_id) == target_id]
            chapters = sum(len(state.own_chapters(v)) for v in volumes)
            if volumes:
                parts.append(f"下面的 {len(volumes)} 卷" + (f"、{chapters} 章章纲" if chapters else "") + "一起删")
        elif kind == "volume":
            volume = next(v for v in state.volumes if str(v.id) == target_id)
            units, chapters = state.own_units(volume.id), state.own_chapters(volume)
            if units:
                parts.append(
                    f"下面的 {len(units)} 个单元" + (f"、{len(chapters)} 章章纲" if chapters else "") + "一起删"
                )
        elif kind == "unit":
            unit = next(u for u in state.units if str(u.id) == target_id)
            if chapters := state.own_chapters(unit):
                parts.append(f"下面的 {len(chapters)} 章章纲一起删")
    return "；".join(parts)


async def delete_target(session, book: Book, kind: str, target_id: str) -> None:
    from app.api.bible import _delete
    from app.api.books import delete_unit, delete_volume
    from app.api.workspace import delete_arc, delete_chapter

    if kind in ("character", "entry"):
        model = Character if kind == "character" else WorldEntry
        row = await session.get(model, uuid.UUID(target_id))
        if row is not None and row.locked:
            raise ValueError("这一条已锁，编辑部不能删，先解锁")
        await _delete(session, model, uuid.UUID(target_id))
    elif kind == "segment":
        state = await outline_structure.load_structure(session, book.id)
        volumes = [v for v in state.volumes if str(v.target_node_id) == target_id]
        for volume in volumes:
            state.ensure_unwritten(volume, "这一篇已经开写了，不能删")
        for volume in volumes:
            await delete_volume(volume.id, session)
        await delete_arc(uuid.UUID(target_id), session)
    elif kind == "volume":
        await delete_volume(uuid.UUID(target_id), session)
    elif kind == "unit":
        await delete_unit(uuid.UUID(target_id), session)
    elif kind == "chapter":
        await delete_chapter(int(target_id), book, session)
    else:
        raise ValueError("这一处不能删")


async def delete_change(session, message, item: ChangeItem) -> dict:
    """删掉一张设定卡或大纲上还没开写的一段，前后对照和换回原来的照常有（删掉的能加回来）。"""
    book_id = message.book_id
    book = await session.get(Book, book_id)
    found = await deletion_target(session, book, item.target)
    if found is None:
        return {"kind": "not_found", "target_name": item.target}
    kind, target_id, label = found
    before = await book_saves.read_state(session, book_id)
    await session.commit()
    await delete_target(session, book, kind, target_id)
    after = await book_saves.read_state(session, book_id)
    rows = book_saves.row_changes(before, after)
    await book_saves.keep_change(session, book_id, before, after, rows)
    await session.commit()
    return {
        "kind": "deleted",
        "target_type": kind,
        "target_id": target_id,
        "target_label": label,
        "change": rows,
        "diff": book_saves.readable_diff(before, after, rows),
    }


# ---------- 方案卡 ----------


def plan_item(item: ChangeItem, linked: str = "") -> dict:
    """清单里的一条摆成方案卡上的一条：原来的清单存在 tool 里，「按这个来」照它做。"""
    where, target, part, category = "设定库", item.target, item.part, ""
    if item.kind == "改设定":
        change = item.instruction
    elif item.kind == "补齐":
        change = "把空着的栏目补上" + (f"：{item.instruction}" if item.instruction else "")
    elif item.kind == "给几个写法":
        change = "出三种写法挑一个" + (f"：{item.instruction}" if item.instruction else "")
    elif item.kind == "新建设定":
        target, category, change = "、".join(item.new_names), item.category or "（编辑部挑一类）", item.instruction
    elif item.kind == "写大纲":
        where, change = "大纲", item.instruction or "把这一段写出来"
    elif item.kind == "写作要求":
        where, target, change = "写作要求", "", item.requirement or item.instruction
    elif item.kind == "改简介":
        where, target, change = "定调", "", item.instruction
    else:
        where, change = "删除", f"删掉「{item.target}」" + (f"。{linked}" if linked else "")
    return {
        "where": where,
        "target": target,
        "part": part if item.kind in ("改设定", "给几个写法") else "",
        "category": category,
        "change": change or item.instruction or "照作者的话改",
        "scope": item.scope,
        "tool": {**item.model_dump(), "shown": change, "linked": linked},
    }


async def plan_items(session, book: Book, items: list[ChangeItem]) -> list[dict]:
    out = []
    for item in items:
        linked = ""
        if item.kind == "删除" and (found := await deletion_target(session, book, item.target)):
            linked = await linked_of(session, book, found)
        out.append(plan_item(item, linked))
    return out


def change_from_plan(item: dict) -> ChangeItem:
    """方案卡上的一条换回清单：编辑部动手时出的卡存着原来的清单；「总结一下」出的照落在哪、改谁换过来。
    作者在卡上改了字的，照他改的写。"""
    change = (item.get("change") or "").strip()
    if tool := item.get("tool"):
        result = ChangeItem.model_validate(tool)
        if change and change != (tool.get("shown") or "").strip():
            if result.kind == "写作要求":
                result.requirement = change
            elif result.kind != "删除":
                result.instruction = change
        return result
    where, target = item.get("where"), item.get("target") or ""
    if where == "写作要求":
        return ChangeItem(kind="写作要求", requirement=change, scope=item.get("scope") or "一直有效")
    if where == "定调":
        return ChangeItem(kind="改简介", instruction=change)
    if where == "删除":
        return ChangeItem(kind="删除", target=target)
    if where == "大纲":
        return ChangeItem(kind="写大纲", target=target, instruction=change)
    if item.get("category"):
        names = [n.strip() for n in re.split(r"[、，,]", target) if n.strip()]
        return ChangeItem(kind="新建设定", category=item["category"], new_names=names, instruction=change)
    return ChangeItem(kind="改设定", target=target, part=item.get("part") or "", instruction=change)


async def plan_change(session, book: Book, item: dict) -> ChangeItem:
    """「总结一下」出的卡里写了要改设定库里的一条、可它还没有：当成新建，放进卡上写的那一类。"""
    from app.services.desk import resolve_category

    change = change_from_plan(item)
    if change.kind == "改设定" and not item.get("tool") and norm(change.target) not in CONCEPT_NAMES:
        ctx = await load_context(session, book)
        if ctx.find_target(change.target) is None:
            change = ChangeItem(
                kind="新建设定",
                category=item.get("category") or "",
                new_names=[change.target] if change.target else [],
                instruction=change.instruction,
            )
    if change.kind == "新建设定" and await resolve_category(session, book.id, change.category) is None:
        # 卡上写的类别对不上：照旧放进「特殊规则」，不丢这一条
        change.category = "特殊规则"
    return change


def tool_args(name: str, raw: dict) -> BaseModel:
    models = {**QUERY_TOOLS, **ACT_TOOLS, "read_skill": ReadSkill}
    model = models.get(name)
    if model is None:
        raise ValueError(f"没有这个工具：{name}。能用的是：{'、'.join(models)}")
    return model.model_validate(raw)
