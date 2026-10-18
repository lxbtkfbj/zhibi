"""新书页大纲每一页上的「编辑部帮写这一段」：全书结局、篇、卷、单元只写名字和一段话，章写章纲。

直接写进去，作者不满意就撤销（前端拿 before 存回去）。锁了的、开写了的不写。
"""

import asyncio
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import schemas as s
from app.agents.context import format_requirements
from app.api.deps import ensure_idle
from app.models import Book, Chapter, PlotUnit, StoryNode, Volume
from app.services import outline_structure
from app.services.desk import FILL_TIMEOUT
from app.services.library import lock_book
from app.services.library_context import LibraryContext, load_context
from app.services.requirements import active_requirements, requirement_text
from app.services.versions import record_version, snapshot_of

MARK = "  ← 要写的就是这一段"
EMPTY = "（还没写）"

RULES = {
    "ending": "全书的结局，不用起名字。text 一段话，三四句，150 字以内：主角最后走到哪一步，和最大的对手怎么了结，开书埋下的最大那件事怎么收。",
    "arc": "一篇。title 起个篇名，四到八个字（像「青阳城篇」「血狱试炼」）；text 一段话，四五句，200 字以内：这一篇主角要去哪、要什么、谁挡着，最后打成什么样，给下一篇留了什么。",
    "volume": "一卷。title 起个卷名，四到八个字；text 一段话，三四句，150 字以内：这一卷要做成什么事、对手是谁、卷末的高潮和结果。",
    "unit": "一个单元（几章讲完的一个完整小故事）。title 起个名字，四到八个字；text 一段话，两三句，100 字以内：什么事找上门、主角怎么应对、读者叫好的那一下、做完拿到了什么。",
    "chapter": "一章的章纲。title 起个章名，四到十二个字，网文风格，不带「第几章」；goal 一句话，30 字以内，写这一章要完成的剧情任务；scenes 按顺序列二到四个场景，每个一句、30 字以内：在哪、谁、发生什么；cool_point 一句话写这一章的爽点或情绪高点；hook 一句话写结尾停在什么悬念上。",
}

# 作者话里提到这些字才换名字，不然沿用作者起的
RENAME_WORDS = ("名", "标题", "题目")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _line(name: str, text: str, mark: bool) -> str:
    return f"{name}：{text or EMPTY}{MARK if mark else ''}"


def chapter_fields(chapter: Chapter) -> dict[str, str]:
    """章纲三栏，和新书页上一样：「发生什么」第一行是目标，下面每行一个场景。"""
    outline = chapter.outline or {}
    happen = "\n".join(filter(None, [_text(outline.get("goal")), *(_text(x) for x in outline.get("scenes") or [])]))
    return {"发生什么": happen, "看点": _text(outline.get("cool_point")), "结尾钩子": _text(outline.get("hook"))}


class Target:
    """要写的那一段：在哪、叫什么、现在写了什么。"""

    def __init__(self, kind: str, row: Any, name: str, title: str, text: str, sections: dict[str, str] | None = None):
        self.kind, self.row, self.name, self.title, self.text, self.sections = kind, row, name, title, text, sections

    @property
    def before(self) -> dict:
        """撤销时存回去的样子，和前端 saveNode 的 change 同形。"""
        if self.kind == "chapter":
            return {"name": self.title, "sections": self.sections or {}}
        if self.kind == "ending":
            return {"text": self.text}
        return {"name": self.title, "text": self.text}


def _volume_name(volume: Volume) -> str:
    return f"第 {volume.index} 卷「{volume.title}」" if volume.title else f"第 {volume.index} 卷"


def _unit_name(unit: PlotUnit) -> str:
    return f"单元 {unit.index}「{unit.title}」" if unit.title else f"单元 {unit.index}"


def _chapter_name(chapter: Chapter) -> str:
    return f"第 {chapter.index} 章「{chapter.title}」" if chapter.title else f"第 {chapter.index} 章"


def _arc_title(node: StoryNode) -> str:
    return _text((node.segment or {}).get("title")) if node.segment is not None else _text(node.title)


def _arc_text(node: StoryNode) -> str:
    return _text((node.segment or {}).get("text")) if node.segment is not None else _text(node.event)


async def find_target(
    session: AsyncSession, book: Book, ctx: LibraryContext, state, target_type: str, target_id: str
) -> Target:
    if target_type == "book":
        ending = next((node for node in ctx.nodes if node.kind == "ending"), None)
        if ending is not None:
            return Target("ending", ending, "全书结局", "", _text(ending.event))
        return Target("ending", book, "全书结局", "", _text((book.concept or {}).get("ending")))
    if target_type == "segment":
        node = next((row for row in ctx.nodes if str(row.id) == target_id), None)
        if node is None:
            raise HTTPException(404, "这一篇不存在")
        if node.kind == "ending" and node.segment is None:
            return Target("ending", node, "全书结局", "", _text(node.event))
        if node.kind == "opening":
            raise HTTPException(422, "开篇不在大纲上写")
        title = _arc_title(node)
        number = ctx.segment_number(node)
        return Target("arc", node, f"第 {number} 篇「{title}」" if title else f"第 {number} 篇", title, _arc_text(node))
    if target_type == "volume":
        volume = next((row for row in state.volumes if str(row.id) == target_id), None)
        if volume is None:
            raise HTTPException(404, "这一卷不存在")
        return Target("volume", volume, _volume_name(volume), _text(volume.title), _text(volume.summary))
    if target_type == "unit":
        unit = next((row for row in state.units if str(row.id) == target_id), None)
        if unit is None:
            raise HTTPException(404, "这个单元不存在")
        return Target("unit", unit, _unit_name(unit), _text(unit.title), _text(unit.summary))
    if target_type == "chapter":
        chapter = next((row for row in state.chapters if str(row.index) == target_id), None)
        if chapter is None:
            raise HTTPException(404, "这一章不存在")
        return Target("chapter", chapter, _chapter_name(chapter), _text(chapter.title), "", chapter_fields(chapter))
    raise HTTPException(422, "不认识要写哪一段")


def ensure_writable(target: Target, state) -> None:
    row = target.row
    if isinstance(row, StoryNode) and row.status == "pinned":
        raise HTTPException(409, "这一段已锁：编辑部不能改，先解锁")
    if getattr(row, "locked", False):
        raise HTTPException(409, "这一段已锁：编辑部不能改，先解锁")
    if target.kind == "arc":
        for volume in state.volumes:
            if volume.target_node_id == row.id:
                state.ensure_unwritten(volume, "这一篇已经开写了，编辑部不改写过的大纲")
    elif target.kind in ("volume", "unit"):
        state.ensure_unwritten(row, f"这{'一卷' if target.kind == 'volume' else '个单元'}已经开写了，编辑部不改写过的大纲")
    elif target.kind == "chapter" and outline_structure.started(row):
        raise HTTPException(409, "这一章已经开写了，编辑部不改写过的章纲")


def outline_text(ctx: LibraryContext, state, target: Target) -> str:
    """整本书的大纲，要写的那一段标出来；它所在的卷展开到单元，所在的单元展开到章。"""
    row = target.row
    focus_volume = row.id if target.kind == "volume" else row.volume_id if target.kind == "unit" else None
    focus_unit = row.id if target.kind == "unit" else row.unit_id if target.kind == "chapter" else None
    if target.kind == "chapter" and focus_unit:
        focus_volume = next((u.volume_id for u in state.units if u.id == focus_unit), None)
    lines: list[str] = []

    def volume_lines(volume: Volume, indent: str) -> None:
        count = f"（{volume.chapter_count} 章）" if volume.chapter_count else ""
        lines.append(indent + _line(_volume_name(volume) + count, _text(volume.summary), target.row is volume))
        if volume.id != focus_volume:
            return
        for unit in state.own_units(volume.id):
            count = f"（{unit.chapter_count} 章）" if unit.chapter_count else ""
            lines.append(indent + "  " + _line(_unit_name(unit) + count, _text(unit.summary), target.row is unit))
            if unit.id != focus_unit:
                continue
            for chapter in state.own_chapters(unit):
                fields = chapter_fields(chapter)
                text = " / ".join(f"{k}：{v}" for k, v in fields.items() if v) or _text(chapter.summary)
                lines.append(indent + "    " + _line(_chapter_name(chapter), text, target.row is chapter))

    arcs = [node for node in ctx.nodes if node.kind not in ("opening", "ending")]
    if any(node.segment is not None for node in ctx.nodes) or target.kind == "arc":
        for number, node in enumerate(arcs, 1):
            title = _arc_title(node)
            later = "" if node.segment is not None else "（写到再定）"
            name = f"第 {number} 篇「{title}」{later}" if title else f"第 {number} 篇{later}"
            lines.append(_line(name, _arc_text(node), target.row is node))
            for volume in state.volumes:
                if volume.target_node_id == node.id:
                    volume_lines(volume, "  ")
        loose = [v for v in state.volumes if v.target_node_id not in {node.id for node in arcs}]
    else:
        loose = list(state.volumes)
    for volume in loose:
        volume_lines(volume, "")
    ending = next((node for node in ctx.nodes if node.kind == "ending"), None)
    ending_text = _text(ending.event) if ending is not None else _text((ctx.book.concept or {}).get("ending"))
    lines.append(_line("结局", ending_text, target.kind == "ending"))
    return "\n".join(lines)


def write_rule(target: Target, state) -> str:
    rule = RULES[target.kind]
    row = target.row
    if target.kind in ("volume", "unit"):
        count = row.chapter_count or (len(state.own_chapters(row)) if target.kind == "unit" else 0)
        rule += f"\n这{'一卷' if target.kind == 'volume' else '个单元'}" + (
            f"定了 {count} 章，写的事要撑得起 {count} 章，也别塞不下。" if row.chapter_count else "章数还没定，按剧情需要写，不用管章数。"
        )
    return rule


def current_text(target: Target) -> str:
    if target.kind == "chapter":
        fields = target.sections or {}
        body = "\n".join(f"{k}：{v}" for k, v in fields.items() if v)
        head = f"章名：{target.title}\n" if target.title else ""
        return (head + body).strip() or "（空的，还没写）"
    if not target.title and not target.text:
        return "（空的，还没写）"
    head = f"名字：{target.title}\n" if target.title else ""
    return head + (target.text or EMPTY)


async def write_outline_node(
    session: AsyncSession, book: Book, target_type: str, target_id: str, request: str = ""
) -> dict:
    """让编辑部把大纲上的这一段写出来，直接写进去。调模型时不占着数据库。"""
    from app.api.library_ai import call_model

    book_id = book.id
    await ensure_idle(session, book_id)
    ctx = await load_context(session, book)
    state = await outline_structure.load_structure(session, book_id)
    target = await find_target(session, book, ctx, state, target_type, target_id)
    ensure_writable(target, state)
    requirements = await active_requirements(session, book_id)
    schema = s.ChapterOutlineWrite if target.kind == "chapter" else s.OutlineNodeWrite
    blocks = dict(
        node_name=target.name,
        concept=ctx.concept,
        library=ctx.library,
        outline=outline_text(ctx, state, target),
        current=current_text(target),
        requirements=format_requirements([requirement_text(row) for row in requirements], [], book.settings),
        request=request.strip() or "（作者只说帮忙写一下这一段）",
        write_rule=write_rule(target, state),
    )
    before = target.before
    await session.rollback()
    try:
        result = await asyncio.wait_for(
            call_model(book_id, "chief", schema, "outline_write", **blocks), timeout=FILL_TIMEOUT
        )
    except TimeoutError as exc:
        raise HTTPException(504, "这次编辑部太慢了，两分半还没写完，没改。再试一次") from exc

    await lock_book(session, book_id)
    await ensure_idle(session, book_id)
    # rollback 之后原来的 book 已经过期：重新取
    book = await session.get(Book, book_id, populate_existing=True)
    ctx = await load_context(session, book)
    state = await outline_structure.load_structure(session, book_id)
    target = await find_target(session, book, ctx, state, target_type, target_id)
    ensure_writable(target, state)
    if target.before != before:
        await session.rollback()
        raise HTTPException(409, "等编辑部写的工夫这一段被改过了，没盖上去。再让编辑部写一次")
    keep_title = bool(target.title) and not any(word in request for word in RENAME_WORDS)
    title = target.title if keep_title else _text(result.title)[:200]
    row = target.row
    if target.kind == "chapter":
        scenes = [_text(x) for x in result.scenes if _text(x)]
        outline = {**(row.outline or {}), "goal": _text(result.goal), "scenes": scenes,
                   "cool_point": _text(result.cool_point), "hook": _text(result.hook)}
        if not (outline["goal"] or scenes):
            await session.rollback()
            raise HTTPException(502, "编辑部这次没写出东西，没改。再试一次")
        row.title = title
        row.outline = outline
        await session.commit()
        return {"title": title, "sections": chapter_fields(row), "note": _text(result.note), "before": before}
    text = _text(result.text)
    if not text:
        await session.rollback()
        raise HTTPException(502, "编辑部这次没写出东西，没改。再试一次")
    snapshot = snapshot_of(row)
    if target.kind == "ending":
        if isinstance(row, Book):
            row.concept = {**(row.concept or {}), "ending": text}
            await record_version(session, book_id, "concept", row, "ai", "编辑部帮写结局", before=snapshot)
        else:
            row.event = text
            await record_version(session, book_id, "segment", row, "ai", "编辑部帮写结局", before=snapshot)
        await session.commit()
        return {"title": "", "text": text, "note": _text(result.note), "before": before}
    if target.kind == "arc":
        if row.segment is not None:
            row.segment = {**row.segment, "title": title, "text": text}
        else:
            row.title, row.event = title, text
        await record_version(session, book_id, "segment", row, "ai", "编辑部帮写这一篇", before=snapshot)
    else:
        row.title, row.summary = title, text
        note = f"编辑部帮写这{'一卷' if target.kind == 'volume' else '个单元'}"
        await record_version(session, book_id, target.kind, row, "ai", note, before=snapshot)
    await session.commit()
    return {"title": title, "text": text, "note": _text(result.note), "before": before}
