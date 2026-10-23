"""聊天专用只读上下文；可以谈底牌，但绝不进入写作图。"""

import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import defer

from app.agents.context import (
    format_foreshadowing,
    format_ledger,
    format_next_segment,
    format_secrets,
    format_style,
    format_volumes_part,
    planned_chapters,
)
from app.book_settings import compile_rules
from app.models import Chapter, ChatThread, Job, MeetingMessage
from app.prompts import tagged
from app.services.chat_memories import memory_directory
from app.services.library_context import load_context
from app.services.meeting import SPEAKER_NAMES
from app.services.setup_store import load_ledger, load_secrets
from app.services.writing_context import best_excerpt, character_states, story_so_far

ROLES = {"主编": "chief", "设定师": "lorekeeper", "写手": "writer", "审稿": "reviewer"}
ROLE_FOCUS = {
    "chief": "你管剧情、节奏和方向：为什么这样安排、后面怎么走、哪里还能更爽。",
    "lorekeeper": "你管设定和前后一致：查清楚再答，说明出处（哪一条设定、第几章）。",
    "writer": "你管怎么写：文风、场面、对话；示范的时候贴着这本书的文风。",
    "reviewer": "你管挑毛病：站在付费读者的角度，只说真正影响阅读的问题，按严重程度排。",
}
THREADS = {"group", *ROLES.values()}


async def thread_of(session, book_id, thread):
    await session.execute(
        insert(ChatThread)
        .values(book_id=book_id, thread=thread)
        .on_conflict_do_nothing(index_elements=["book_id", "thread"])
    )
    return await session.scalar(select(ChatThread).where(ChatThread.book_id == book_id, ChatThread.thread == thread))


async def conversation_state(session, book_id, thread, conv=None):
    """摘要存在哪：群聊是那一段对话（不给就是最近聊的那一段），私聊是 chat_threads 那一行"""
    if thread != "group":
        return await thread_of(session, book_id, thread)
    from app.services import chat_convs

    return (await chat_convs.find(session, book_id, conv) if conv else None) or await chat_convs.current(
        session, book_id
    )


async def dialogue(session, book_id, thread, reset_after=0, conv=None):
    """一个对话里说过的话。群聊给了 conv 就只要那一段（作者把书换回存档的那一行，这一段开始以后的都带上）；
    「从这里重来」收起来的不算。"""
    rows = list(
        await session.scalars(
            select(MeetingMessage)
            .where(MeetingMessage.book_id == book_id, MeetingMessage.id > reset_after)
            .order_by(MeetingMessage.id)
        )
    )
    if thread == "group" and conv:
        conv = str(getattr(conv, "id", conv))
        mine = [m for m in rows if (m.payload or {}).get("conv") == conv]
        start = mine[0].id if mine else None
        rows = [
            m
            for m in rows
            if (m.payload or {}).get("conv") == conv
            or (start is not None and m.id > start and m.speaker == "system" and "restore" in (m.payload or {}))
        ]
    return [
        m
        for m in rows
        if not (m.payload or {}).get("dropped")
        and (
            ((m.payload or {}).get("thread") or "group") == thread
            and (
                (m.speaker == "author" and m.kind in {"note", "decision"})
                # 作者把书换回了某一档：编辑部回答时要知道这之后的改动都退了
                or (m.speaker == "system" and "restore" in (m.payload or {}))
                or (
                    m.kind in {"speech", "plan"}
                    and m.speaker in ROLES.values()
                    and (thread != "group" or m.kind == "plan" or "reply_to" in (m.payload or {}))
                    # 还在写的、没答上来的回答不算说过的话
                    and m.content
                    and (m.payload or {}).get("state") not in {"thinking", "streaming", "failed"}
                )
            )
        )
    ]


def done_text(outcome):
    """编辑部照作者这句话实际做了什么，一小句；只是聊天、还在判断的不算"""
    kind, label = outcome.get("kind"), outcome.get("target_label") or ""
    if kind == "memory":
        memory = outcome["memory"]
        text = {"create": "记住了", "update": "改了一条记忆", "forget": "忘掉了"}[memory["action"]]
        return f"{text}：{memory['summary']}" + ("（作者点了撤销）" if outcome.get("undone") else "")
    if kind == "edit":
        return f"给「{label}」出了三种写法，等作者挑" if outcome.get("mode") == "options" else f"改了「{label}」"
    if kind == "fill":
        filled = outcome.get("filled") or []
        return f"补了「{label}」空着的{'、'.join(filled)}" if filled else f"「{label}」每一栏都写了，没补"
    return {
        "created": f"新建了{label}，放进了设定库",
        "outline": f"写好了大纲里的{label}，已经换上去",
        "requirement": f"记住了：{(outcome.get('memory') or {}).get('summary', '')}（写书时照做）",
        "to_job": f"记住了：{(outcome.get('memory') or {}).get('summary', '')}（写书时照做），正在写的编辑部从下一步起照办",
        "later": "编辑部当时在写，没改，放进了待处理的建议",
        "not_found": f"设定库里没找到「{outcome.get('target_name') or ''}」，什么也没改",
        "too_late": "当时在等作者拍板，没改书",
        "failed": f"再改一版没做成（{outcome.get('reason') or ''}），这一处换回了改之前的样子"
        if outcome.get("redo_failed")
        else f"没做成（{outcome.get('reason') or ''}），什么也没改",
        "plan_apply": "照方案卡办了",
        "saved": f"把书存了一档「{outcome.get('title') or ''}」",
        "deleted": f"删掉了{label}",
        "plan_made": "要动的多，整理成了方案卡，等作者点「按这个来」才改" if outcome.get("count") else "",
    }.get(kind, "")


def done_note(message):
    """写进对话里：作者这句话后面带上编辑部照办了什么，回答的人才知道已经改了、写了"""
    payload = getattr(message, "payload", None) or {}
    if message.speaker != "author":
        parts = [done_text(item) for item in payload.get("memories") or []]
        return f"（编辑部照这句做了：{'；'.join(parts)}）" if parts else ""
    parts = [
        t + (("（作者点了撤销）" if o.get("memory") else "（作者后来换回了原来的）") if o.get("undone") else "")
        for o in payload.get("steps") or [payload.get("outcome") or {}]
        if (t := done_text(o))
    ]
    return f"（编辑部照这句做了：{'；'.join(parts)}）" if parts else ""


def dialogue_text(rows, *, limited=True, limit=6000):
    lines = [
        f"{SPEAKER_NAMES.get(m.speaker, m.speaker)}：{m.content[:800] + ('……' if len(m.content) > 800 else '')}"
        f"{done_note(m)}"
        for m in rows
    ]
    if limited:
        while lines and len("\n".join(lines)) > limit:
            lines.pop(0)
    return "\n".join(lines) or "（没有）"


def number(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip("零一二三四五六七八九两〇", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2, 0], strict=True))
    total = current = 0
    for c in value:
        if c in digits:
            current = digits[c]
        else:
            total += (current or 1) * {"十": 10, "百": 100, "千": 1000}.get(c, 1)
            current = 0
    return total + current


def references(text, kind, limit):
    return list(
        dict.fromkeys(number(n) for n in re.findall(r"第\s*([0-9零〇一二三四五六七八九十百千两]+)\s*" + kind, text))
    )[:limit]


async def progress_of(session, ctx, chapters, job):
    done = [c for c in chapters if c.status == "final"]
    if not done:
        text = "还没开写。"
        if job and job.kind == "book_setup" and job.status in {"queued", "running", "waiting_author"}:
            piece = (job.pending or {}).get("piece") or (ctx.book.setup_progress or {}).get("current", "concept")
            text += "\n开书正在做：" + {"concept": "定调", "settings": "设定库", "outline": "大纲"}.get(piece, "定调")
        return text
    planned = planned_chapters(ctx.book.concept or {})
    lines = [f"已定稿 {len(done)} 章，全书计划约 {planned} 章。" if planned else f"已定稿 {len(done)} 章。"]
    chapter = next((c for c in chapters if c.status != "final"), None)
    volume = next((v for v in ctx.volumes if v.status != "done"), None)
    if chapter and chapter.volume_id:
        volume = next((v for v in ctx.volumes if v.id == chapter.volume_id), volume)
    unit = next((u for u in ctx.units if chapter and u.id == chapter.unit_id), None)
    if unit is None and volume:
        unit = next((u for u in ctx.units if u.volume_id == volume.id and u.status != "done"), None)
    arc = next((n for n in ctx._arcs() if volume and n.id == volume.target_node_id), None)
    parts = []
    if arc and arc.segment:
        parts.append(f"第 {ctx.segment_number(arc)} 篇「{ctx.target_name(arc)}」")
    if volume:
        parts.append(f"第 {volume.index} 卷「{volume.title}」")
    if unit:
        parts.append(f"单元「{unit.title}」")
    if chapter:
        parts.append(f"第 {chapter.index} 章《{chapter.title}》")
    if parts:
        lines.append("正在写：" + " · ".join(parts))
    lines.extend(
        [
            "前情提要：",
            await story_so_far(
                session,
                ctx.book,
                volume.index if volume else 1,
                before_chapter=chapter.index if chapter else max(c.index for c in done) + 1,
                unit_index=unit.index if unit else None,
            ),
        ]
    )
    return "\n".join(lines)


async def related_of(session, ctx, chapters, text):
    blocks = []
    found = []
    for order, target in enumerate(ctx.targets):
        positions = [text.find(n) for n in [target.name, *(target.aliases or [])] if n and n in text]
        if positions:
            found.append((min(positions), order, target))
    found.sort(key=lambda item: item[:2])
    if found:
        blocks.append("设定：\n" + "\n\n".join(ctx.entry_full_text(item[2]) for item in found[:8]))
    chapter_lines = []
    for n in references(text, "章", 3):
        c = next((c for c in chapters if c.index == n), None)
        if c:
            chapter_lines.append(
                f"第 {n} 章《{c.title}》："
                + (
                    c.summary
                    if c.status == "final"
                    else f"{(c.outline or {}).get('goal', '')}；{(c.outline or {}).get('hook', '')}"
                )
            )
            if c.status == "final":
                content = await chapter_content(session, c)
                chapter_lines.append("原文片段：" + (best_excerpt(content, text) or content[:300]))
    if chapter_lines:
        blocks.append("\n".join(chapter_lines))
    for n in references(text, "卷", 2):
        v = next((v for v in ctx.volumes if v.index == n), None)
        if v:
            lines = [f"第 {n} 卷「{v.title}」：{v.summary}"]
            lines.extend(f"  单元「{u.title}」：{u.summary}" for u in ctx.units if u.volume_id == v.id)
            blocks.append("\n".join(lines))
    for node in ctx._arcs():
        if ctx.target_name(node) and ctx.target_name(node) in text:
            blocks.append(
                f"第 {ctx.segment_number(node)} 篇「{ctx.target_name(node)}」：{(node.segment or {}).get('text') or node.event}"
            )
    for unit in ctx.units:
        if unit.title and unit.title in text:
            blocks.append(f"单元「{unit.title}」：{unit.summary}")
    codes = set(re.findall(r"(?<![A-Za-z0-9])[FE]\d+(?!\d)", text, re.I))
    ledger = [
        f
        for f in await load_ledger(session, ctx.book.id)
        if f"{'E' if f.get('kind') == '期待' else 'F'}{f['seq']}" in {s.upper() for s in codes}
    ]
    if ledger:
        blocks.append("台账：\n" + "\n".join(format_foreshadowing(f) for f in ledger))
    secret_codes = set(re.findall(r"(?<![A-Za-z0-9])S\d+(?!\d)", text.upper()))
    secrets = [s for s in await load_secrets(session, ctx.book.id) if f"S{s['seq']}" in secret_codes]
    if secrets:
        blocks.append("信息差：\n" + format_secrets(secrets))
    return "\n\n".join(blocks) or "（没有）"


async def extras_of(session, ctx, chapters, role, text):
    blocks = []
    done = [c for c in chapters if c.status == "final"]
    ledger = await load_ledger(session, ctx.book.id)
    if role == "chief":
        volume = next((v for v in ctx.volumes if v.status != "done"), None)
        arc = next((n for n in ctx._arcs() if volume and n.id == volume.target_node_id), None)
        if done and arc:
            blocks.append(tagged("正在写的这一篇", (arc.segment or {}).get("text") or arc.event))
        if done and volume:
            lines = [volume.summary]
            current = next((u.id for u in ctx.units if u.volume_id == volume.id and u.status != "done"), None)
            lines.extend(
                f"单元「{u.title}」（{'已写完' if u.status == 'done' else '正在写' if u.id == current else '还没写'}）：{u.summary}"
                for u in ctx.units
                if u.volume_id == volume.id
            )
            blocks.append(tagged("正在写的这一卷", "\n".join(lines)))
        opened = [f for f in ledger if f.get("kind") == "期待" and f.get("status") == "planted"]
        if opened:
            blocks.append(tagged("还开着的期待", format_ledger(opened)))
    elif role == "lorekeeper":
        if ctx.characters:
            blocks.append(tagged("人物现在的状态", character_states(ctx.characters)))
        secrets = [s for s in await load_secrets(session, ctx.book.id) if s.get("status") == "hidden"][:20]
        if secrets:
            blocks.append(tagged("还藏着的信息差", format_secrets(secrets)))
        opened = [f for f in ledger if f.get("kind") != "期待" and f.get("status") in {"planned", "planted"}][:20]
        if opened:
            blocks.append(tagged("还没收的伏笔", format_ledger(opened)))
    elif role == "reviewer":
        mentioned = references(text, "章", 3)
        c = (
            next((c for n in mentioned for c in chapters if c.index == n), None)
            if mentioned
            else (done[-1] if done else None)
        )
        if c and c.status == "final":
            lines = [f"第 {c.index} 章《{c.title}》：{c.summary}"]
            review = c.review or {}
            review = review.get("review", review)
            if review.get("highlights"):
                lines.append("审稿时写得好的：" + "；".join(review["highlights"]))
            if review.get("issues"):
                lines.append("审稿时的问题：")
                lines.extend(
                    f"- [{i.get('severity', '')}] {i.get('problem', '')}——{i.get('suggestion', '')}"
                    for i in review["issues"]
                )
            blocks.append(tagged("最近定稿的一章", "\n".join(lines)))
    else:
        if rules := compile_rules(ctx.book.settings):
            blocks.append(tagged("写作规矩", rules))
        if style := format_style(ctx.book.style_reference or ""):
            blocks.append(tagged("文风参考", style))
        if done:
            blocks.append(tagged("最近定稿一章的结尾", (await chapter_content(session, done[-1]))[-1500:]))
    return "\n\n".join(blocks)


async def chapter_content(session, chapter):
    """全书目录不加载正文；只有明确引用的一章再单独取，避免异步隐式懒加载。"""
    if "content" in chapter.__dict__:
        return chapter.content or ""
    return await session.scalar(select(Chapter.content).where(Chapter.id == chapter.id)) or ""


def pending_of(job, ctx):
    if not job or job.status != "waiting_author":
        return ""
    p = job.pending or {}
    kind = p.get("kind")
    if kind == "segment_review" and p.get("flow") == 3:
        body = (
            format_next_segment(p.get("plan") or p.get("segment") or p)
            + "\n\n"
            + format_volumes_part(p.get("split") or {})
        )
    elif kind == "setup_pitches":
        body = "\n".join(
            f"{i}. {v.get('name', '')}：{v.get('text', '')}（书名候选：{'、'.join(v.get('titles') or [])}）"
            for i, v in enumerate(p.get("pitches") or [], 1)
        )
    else:
        unit = next((u for u in ctx.units if str(u.id) == p.get("unit_id")), None)
        name = {
            "setup_piece": {"concept": "定调", "settings": "定调和设定库", "outline": "大纲"}.get(
                p.get("piece"), "定调"
            ),
            "setup_review": "大纲",
            "volume_review": f"第 {p.get('volume')} 卷卷纲",
            "chapters_review": f"单元「{unit.title if unit else p.get('unit_title', '')}」的章纲",
            "trial_read": "前 3 章试读",
            "chapter_stuck": f"第 {p.get('chapter')} 章（写不过去了）",
        }.get(kind, "定调")
        body = f"等你确认：{name}（内容在上面的资料里）"
    return tagged("等你确认的内容", body)


async def reply_values(session, book, thread, role, rows, unanswered, summary):
    ctx = await load_context(session, book)
    chapters = list(
        await session.scalars(
            select(Chapter).where(Chapter.book_id == book.id).options(defer(Chapter.content)).order_by(Chapter.index)
        )
    )
    job = await session.scalar(
        select(Job)
        .where(Job.book_id == book.id, Job.status.in_(["queued", "running", "waiting_author"]))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    note = "\n\n".join(m.content for m in unanswered)
    quotes = [(m.payload or {}).get("quote") for m in unanswered if (m.payload or {}).get("quote")]
    quote = "\n\n".join(tagged("作者选中的原文", f"（{q['where']}）\n{q['text'][:2000]}") for q in quotes)
    # 作者这次说的单独放在 <作者这次说的>，最近的对话里不再重复
    asked = {m.id for m in unanswered}
    rows = [m for m in rows if m.id not in asked]
    query = note + "\n" + quote + "\n" + "\n".join(m.content for m in rows[-4:])
    return dict(
        where="私聊" if thread != "group" else "编辑部群聊",
        concept=ctx.concept,
        library=ctx.library_material,
        outline=ctx.outline,
        progress=await progress_of(session, ctx, chapters, job),
        memory=await memory_directory(session, book.id),
        related=await related_of(session, ctx, chapters, query),
        extras=await extras_of(session, ctx, chapters, role, query),
        pending=pending_of(job, ctx),
        summary=summary or "（没有）",
        recent=dialogue_text(rows[-20:]),
        quote=quote,
        note=note,
        how_to_apply=(
            "作者想让聊出来的想法生效，要先让你「总结一下」出一张方案卡，看过再点「按这个来」。聊到想法差不多成形时，可以提醒他一句；不要说「就这么定了」「咱们直接开始排……」，聊天里说的都还没生效。作者要你记住什么，私聊里记不了，请作者到群聊里说「记住……」。"
            if thread != "group"
            else "群聊里作者明说要改、要写、要记的，编辑部已经照办了：最近的对话里作者那句话后面写着「（编辑部照这句做了：……）」，那些就是真改了、真写进去了，照实说，别说成没生效。"
            "只是商量出来的想法还没生效：作者想改哪一处，直接说「把……改成……」就会改（一次要动三处以上或者要删东西，会先出方案卡，他点「按这个来」才改）；"
            "聊了一大堆想一起落实，可以让你「总结一下」出一张方案卡。没照办的别说成已经办了。"
        ),
        role_focus=ROLE_FOCUS[role],
    )


def _plain(text):
    import unicodedata

    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


def wants_plan(text):
    text = _plain(text)
    return len(text) <= 40 and any(
        word in text for word in ("总结", "归纳", "汇总", "整理一下", "整理成方案", "列个方案", "出个方案")
    )


def wants_new_pitches(text):
    text = _plain(text)
    return len(text) <= 200 and any(
        word in text
        for word in (
            "再来三个",
            "再出三个",
            "重出",
            "重新出",
            "换三个",
            "换一批",
            "换几个方向",
            "都不要",
            "都不满意",
            "都不喜欢",
        )
    )


def accepts_plan(text):
    text = _plain(text)
    return len(text) <= 20 and any(
        word in text
        for word in (
            "按这个来",
            "按这个办",
            "照这个来",
            "照这个办",
            "就这么定",
            "就这样定",
            "就按这个",
            "按方案来",
            "就按方案",
            "照方案",
        )
    )


def obvious_question(text):
    if not text.rstrip().endswith(("？", "?")) or any(
        word in text
        for word in (
            "改",
            "换",
            "加",
            "删",
            "去掉",
            "别",
            "不要",
            "以后",
            "下一",
            "从现在",
            "帮我",
            "记下",
            "记住",
            "照这个",
            "按这个",
            "写一下",
            "写写",
            "细化",
            "重写",
        )
    ):
        return None
    for role, words in (
        ("lorekeeper", ("境界", "设定", "在哪", "谁知道", "前后")),
        ("writer", ("怎么写", "文风", "示范", "写法")),
        ("reviewer", ("毛病", "不好看", "漏洞", "问题")),
    ):
        if any(word in text for word in words):
            return role
    return "chief"
