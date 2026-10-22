"""拆的书只查只答：两条群聊路径共用同一份资料和逐字约定的提示文字。"""

import re

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.models import Chapter
from app.prompts import tagged
from app.services.chat_context import dialogue_text, related_of
from app.services.library_context import load_context

PROGRESS = "还没开拆：只有原文，章纲、单元、设定都还没有。"
LOOKUP_TOOLS = "上面的设定和大纲只是目录，或者还没拆出来，原文一章都没贴。要细节、要核对，用工具查：某一章的原文和摘要、在原文里搜一个词、设定卡全文、大纲上的一段、伏笔。问「第一次出场」「在哪几章」的，先在原文里搜。能一起查的一次调几个工具；上面已经有的不要再查。"
LOOKUP_PLAIN = "你这次查不了资料，上面「和这次的话有关的资料」是程序按作者这句话找出来的：提到的几章、设定，还有作者用引号标出的词在原文里的位置。那里没有的就说没找到，不要猜；作者要找某个词在哪几章，告诉他在正文页目录的搜索框里搜原文。"
ROLE_FOCUS = {
    "chief": "你管剧情、节奏和结构：原书为什么这样安排，钩子和爽点是怎么做出来的，一个单元怎么起、怎么收。",
    "lorekeeper": "你管设定和前后一致：查清楚再答，说明出处（哪一条设定、第几章原文）。",
    "writer": "你管怎么写：文风、场面、对话；拿原文的句子说它好在哪。",
    "reviewer": "你管读者感受：站在付费读者的角度，说清哪里让人想追、哪里容易弃书，按影响大小排。",
}


def quoted_words(text: str) -> list[str]:
    """只认配对引号，去重后最多三个；过长的词不截断成另一种搜索。"""
    words = []
    for match in re.finditer(r'「([^」\n]*)」|“([^”\n]*)”|『([^』\n]*)』|"([^"\n]*)"', text):
        word = next(value for value in match.groups() if value is not None).strip()
        if 1 <= len(word) <= 30 and word not in words:
            words.append(word)
            if len(words) == 3:
                break
    return words


def book_info(book, chapters, volumes, units=(), nodes=()) -> str:
    info = book.teardown or {}
    author = f"（原作者：{info['author']}）" if info.get("author") else "（原作者没写）"
    chars = int((info.get("split") or {}).get("chars", sum(c.word_count or 0 for c in chapters)))
    words = f"共 {(chars + 5000) // 10000} 万字" if chars >= 10000 else f"共 {chars} 字"
    divided = bool(info.get("original_volumes"))
    volume_text = f"原书分了 {len(volumes)} 卷" if divided else "原书没有分卷"
    read = [c.index for c in chapters if (c.teardown or {}).get("read_version") is not None]
    volume_count = sum(
        1
        for volume in volumes
        if volume.title and str(volume.id) != str(info.get("open_volume_id")) and volume.title != "还没收尾"
    )
    stage = info.get("stage")
    progress = PROGRESS
    if stage in ("queued", "running"):
        progress = f"正在拆：前 {len(read)} 章有章纲，归成了 {len(units)} 个单元、{volume_count} 卷；后面的还没拆，设定还没整理。"
    elif stage == "stopped":
        progress = f"拆到第 {max(read, default=0)} 章停下了：前 {len(read)} 章有章纲，归成了 {len(units)} 个单元、{volume_count} 卷；后面的还没拆，设定还没整理。"
    elif stage == "done":
        progress = f"拆完了：每章都有章纲，归成了 {len(units)} 个单元、{volume_count} 卷；设定还没整理。"
    if settings_upto := (info.get("settings") or {}).get("upto"):
        progress = progress.replace("设定还没整理", f"设定整理到第 {settings_upto} 章")
    arcs = [node for node in nodes if node.kind == "milestone" and node.segment is not None]
    if arcs:
        progress += f"全书归成了 {len(arcs)} 篇。"
    ending = info.get("ending") or {}
    if any(node.kind == "ending" for node in nodes):
        progress += f"原书到第 {len(chapters)} 章完结，结局写在大纲的全书那一页。"
    elif ending and not ending.get("ended"):
        progress += f"主编看过最后几章，原书到第 {len(chapters)} 章还没完结。"
    if waits := info.get("waits"):
        progress += (
            f"读者在等的事整理到第 {waits['upto']} 章：一共 {waits['total']} 件，"
            f"还吊着 {waits['open']} 件（编号 E 是期待、F 是伏笔，要细节用查伏笔的工具）。"
        )
    text = f"书名：《{book.title}》{author}\n导入了 {len(chapters)} 章，{words}；{volume_text}。\n{progress}"
    if essence := info.get("essence"):
        overview = essence.get("overview") or {}
        points = "；".join(f"{i}. {p['title']}" for i, p in enumerate(overview.get("points") or [], 1))
        text += (
            f"\n精髓（基于前 {essence.get('upto', 0)} 章）：{overview.get('genre', '')}"
            f"\n一句话：{overview.get('engine', '')}\n核心要点：{points}"
        )
    return text


def outline_of(ctx, chapters, *, full: bool, open_volume_id) -> str:
    """沿用聊天大纲的卷／单元取法，每卷补上尚未归单元的章。"""
    from app.services.chat_agent import first_line

    cut = (lambda text: (text or "").strip()) if full else first_line
    lines = []

    def append_volume(volume):
        title = "还没收尾" if str(volume.id) == str(open_volume_id) else volume.title
        lines.append(f"第 {volume.index} 卷「{title}」：{cut(volume.summary)}")
        lines.extend(
            f"  单元 {unit.index}「{unit.title}」：{cut(unit.summary)}"
            for unit in ctx.units
            if unit.volume_id == volume.id
        )
        loose = [c.index for c in chapters if c.volume_id == volume.id and c.unit_id is None]
        if loose:
            lines.append(f"第 {min(loose)} 到 {max(loose)} 章还没归单元。")

    nodes = getattr(ctx, "nodes", [])
    arcs = [node for node in nodes if node.kind == "milestone" and node.segment is not None]
    if arcs:
        for number, node in enumerate(arcs, 1):
            own = [volume for volume in ctx.volumes if volume.target_node_id == node.id]
            if not own:
                continue
            segment = node.segment
            lines.append(
                f"第 {number} 篇「{segment.get('title', node.title)}」（第 {own[0].index}–{own[-1].index} 卷）："
                f"{cut(segment.get('text', ''))}"
            )
            for volume in own:
                append_volume(volume)
        unassigned = [volume for volume in ctx.volumes if volume.target_node_id not in {node.id for node in arcs}]
        if unassigned:
            lines.append("还没归篇：")
            for volume in unassigned:
                append_volume(volume)
    else:
        for volume in ctx.volumes:
            append_volume(volume)
    ending = next((node for node in reversed(nodes) if node.kind == "ending"), None)
    if ending:
        lines.append(f"全书结局：{ending.event}")
    return "\n".join(lines)


async def values(session, book, role, message, rows, summary, *, tools: bool, retry: bool = False) -> dict:
    # 与 agent 共用小书全文／大书目录、当前页、重试和对话的取法，不能带写书进度或写作要求。
    from app.services.chat_agent import SMALL_BOOK, retry_note, viewing_full
    from app.services.chat_tools import search_text

    ctx = await load_context(session, book)
    chapters = list(
        await session.scalars(
            select(Chapter).where(Chapter.book_id == book.id).options(defer(Chapter.content)).order_by(Chapter.index)
        )
    )
    if ctx.units:
        full_outline = outline_of(ctx, chapters, full=True, open_volume_id=(book.teardown or {}).get("open_volume_id"))
    else:
        ranges = {}
        for chapter in chapters:
            bounds = ranges.setdefault(chapter.volume_id, [chapter.index, chapter.index])
            bounds[1] = chapter.index
        full_outline = "\n".join(
            f"第 {volume.index} 卷「{volume.title}」：第 {ranges[volume.id][0]} 到 {ranges[volume.id][1]} 章，还没拆出章纲。"
            for volume in ctx.volumes
            if volume.id in ranges
        )
    full_library = ctx.library_full
    small = len(full_library) + len(full_outline) <= SMALL_BOOK
    payload = message.payload or {}
    quote = payload.get("quote")
    related = ""
    if not tools:
        found = await related_of(session, ctx, chapters, message.content)
        blocks = [found] if found and found != "（没有）" else []
        blocks.extend([await search_text(session, book, word) for word in quoted_words(message.content)])
        related = tagged("和这次的话有关的资料", "\n\n".join(blocks) or "（没找到）")
    return dict(
        material_note="" if small else "（书比较大：设定和大纲只列了目录，要细节用工具查）",
        book_info=book_info(book, chapters, ctx.volumes, ctx.units, ctx.nodes),
        library=(full_library if small else "这里只列名字和一句话，要细节用 look_up_settings 查：\n" + ctx.library)
        if full_library
        else "（还没拆出设定）",
        outline=full_outline
        if small or not ctx.units
        else outline_of(ctx, chapters, full=False, open_volume_id=(book.teardown or {}).get("open_volume_id")),
        viewing=await viewing_full(session, book, ctx, payload.get("viewing")),
        related=related,
        summary=summary or "（没有）",
        recent=dialogue_text(rows[-20:]),
        quote=tagged("作者选中的原文", f"（{quote['where']}）\n{quote['text'][:2000]}") if quote else "",
        retry=retry_note(payload.get("steps") or []) if retry else "",
        note=message.content,
        lookup=LOOKUP_TOOLS if tools else LOOKUP_PLAIN,
        role_focus=ROLE_FOCUS[role],
    )
