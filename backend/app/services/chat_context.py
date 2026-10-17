"""聊天专用只读上下文；可以谈底牌，但绝不进入写作图。"""

import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

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
from app.services.library_context import load_context
from app.services.meeting import SPEAKER_NAMES
from app.services.requirements import active_requirements, requirements_list
from app.services.setup_store import load_ledger, load_secrets
from app.services.writing_context import best_excerpt, character_states, story_so_far

ROLES = {"主编": "chief", "设定师": "lorekeeper", "写手": "writer", "审稿": "reviewer"}
THREADS = {"group", *ROLES.values()}


async def thread_of(session, book_id, thread):
    await session.execute(
        insert(ChatThread)
        .values(book_id=book_id, thread=thread)
        .on_conflict_do_nothing(index_elements=["book_id", "thread"])
    )
    return await session.scalar(select(ChatThread).where(ChatThread.book_id == book_id, ChatThread.thread == thread))


async def dialogue(session, book_id, thread, reset_after=0):
    rows = await session.scalars(
        select(MeetingMessage)
        .where(MeetingMessage.book_id == book_id, MeetingMessage.id > reset_after)
        .order_by(MeetingMessage.id)
    )
    return [
        m
        for m in rows
        if (
            ((m.payload or {}).get("thread") or "group") == thread
            and (
                (m.speaker == "author" and m.kind in {"note", "decision"})
                or (
                    m.kind in {"speech", "plan"}
                    and m.speaker in ROLES.values()
                    and (thread != "group" or m.kind == "plan" or "reply_to" in (m.payload or {}))
                )
            )
        )
    ]


def dialogue_text(rows, *, limited=True, limit=6000):
    lines = [
        f"{SPEAKER_NAMES.get(m.speaker, m.speaker)}：{m.content[:800] + ('……' if len(m.content) > 800 else '')}"
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
                chapter_lines.append("原文片段：" + (best_excerpt(c.content, text) or c.content[:300]))
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
            blocks.append("【正在写的这一篇】\n" + ((arc.segment or {}).get("text") or arc.event))
        if done and volume:
            lines = ["【正在写的这一卷】", volume.summary]
            current = next((u.id for u in ctx.units if u.volume_id == volume.id and u.status != "done"), None)
            lines.extend(
                f"单元「{u.title}」（{'已写完' if u.status == 'done' else '正在写' if u.id == current else '还没写'}）：{u.summary}"
                for u in ctx.units
                if u.volume_id == volume.id
            )
            blocks.append("\n".join(lines))
        opened = [f for f in ledger if f.get("kind") == "期待" and f.get("status") == "planted"]
        if opened:
            blocks.append("【还开着的期待】\n" + format_ledger(opened))
    elif role == "lorekeeper":
        if ctx.characters:
            blocks.append("【人物现在的状态】\n" + character_states(ctx.characters))
        secrets = [s for s in await load_secrets(session, ctx.book.id) if s.get("status") == "hidden"][:20]
        if secrets:
            blocks.append("【还藏着的信息差】\n" + format_secrets(secrets))
        opened = [f for f in ledger if f.get("kind") != "期待" and f.get("status") in {"planned", "planted"}][:20]
        if opened:
            blocks.append("【还没收的伏笔】\n" + format_ledger(opened))
    elif role == "reviewer":
        mentioned = references(text, "章", 3)
        c = (
            next((c for n in mentioned for c in chapters if c.index == n), None)
            if mentioned
            else (done[-1] if done else None)
        )
        if c and c.status == "final":
            lines = ["【最近定稿的一章】", f"第 {c.index} 章《{c.title}》：{c.summary}"]
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
            blocks.append("\n".join(lines))
    else:
        if rules := compile_rules(ctx.book.settings):
            blocks.append("【写作规矩】\n" + rules)
        if style := format_style(ctx.book.style_reference or ""):
            blocks.append("【文风参考】\n" + style)
        if done:
            blocks.append("【最近定稿一章的结尾】\n" + done[-1].content[-1500:])
    return "\n\n".join(blocks)


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
    return "【等你确认的内容】\n" + body


async def reply_values(session, book, thread, role, rows, unanswered, summary):
    ctx = await load_context(session, book)
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)))
    job = await session.scalar(
        select(Job)
        .where(Job.book_id == book.id, Job.status.in_(["queued", "running", "waiting_author"]))
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    note = "\n\n".join(m.content for m in unanswered)
    quotes = [(m.payload or {}).get("quote") for m in unanswered if (m.payload or {}).get("quote")]
    quote = "\n\n".join(f"【作者选中的原文】（{q['where']}）\n{q['text'][:2000]}" for q in quotes)
    query = note + "\n" + quote + "\n" + "\n".join(m.content for m in rows[-4:])
    return dict(
        where="私聊" if thread != "group" else "编辑部群聊",
        concept=ctx.concept,
        library=ctx.library,
        outline=ctx.outline,
        progress=await progress_of(session, ctx, chapters, job),
        requirements=requirements_list(await active_requirements(session, book.id)),
        related=await related_of(session, ctx, chapters, query),
        extras=await extras_of(session, ctx, chapters, role, query),
        pending=pending_of(job, ctx),
        summary=summary or "（没有）",
        recent=dialogue_text(rows[-20:]),
        quote=quote,
        note=note,
        how_to_apply="作者想让聊出来的想法生效，要先让你「总结一下」出一张方案卡，看过再点「按这个来」。聊到想法差不多成形时，可以提醒他一句；不要说「就这么定了」「咱们直接开始排……」，聊天里说的都还没生效。",
        role_focus={
            "chief": "你管剧情、节奏和方向：为什么这样安排、后面怎么走、哪里还能更爽。",
            "lorekeeper": "你管设定和前后一致：查清楚再答，说明出处（哪一条设定、第几章）。",
            "writer": "你管怎么写：文风、场面、对话；示范的时候贴着这本书的文风。",
            "reviewer": "你管挑毛病：站在付费读者的角度，只说真正影响阅读的问题，按严重程度排。",
        }[role],
    )


def _plain(text):
    import unicodedata

    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


def wants_plan(text):
    text = _plain(text)
    return len(text) <= 40 and any(
        word in text for word in ("总结", "归纳", "汇总", "整理一下", "整理成方案", "列个方案", "出个方案")
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
