"""群聊里接话的人自己查、自己动手（工具调用）：一句话一轮，缺什么查什么，要改的列成清单交给程序办，
做完用一段话告诉作者。改动挂在作者那句话下面（payload.steps），查了什么、做了什么记在回答上（payload.tools）。
模型不支持工具调用（本机模型、演示模式、接口不认工具）时，照旧走分流。"""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.agents.editorial import persona
from app.db import get_sessionmaker
from app.llm import demo
from app.llm.router import LOCAL_HOSTS, LLMRouter, ToolCall, ToolsUnsupported
from app.models import Book, Chapter, Job, MeetingMessage
from app.prompts import render, tagged
from app.services import book_saves, chat_tools, jobs
from app.services.chat import PUSH_EVERY, answer, answered_ids, conversation_lock, finish_reply, merge_summary, stop_key
from app.services.chat_context import (
    ROLE_FOCUS,
    conversation_state,
    dialogue,
    dialogue_text,
    done_text,
    pending_of,
    progress_of,
    thread_of,
)
from app.services.chat_memories import memory_directory
from app.services.library_context import load_context
from app.services.meeting import SPEAKER_NAMES, message_dict, post_message, publish
from app.services.versions import target_type_of

log = logging.getLogger(__name__)

# 一句话最多来回几次、最多做多久；多久没动静算卡住了（每次查、改、吐字都算动静，改的那一处做的时候不算）
MAX_ROUNDS = 6
TOTAL_LIMIT = 8 * 60
IDLE_LIMIT = 90
# 设定加大纲在这么多字以内算书小：全文带上；书大了只带目录，要细节自己查
SMALL_BOOK = 10000
LIVE = ("thinking", "streaming")

# 不点名时挑谁接话：按话里的词，不另调模型；四个人工具一样，人设不同
ROLE_WORDS = (
    ("reviewer", ("毛病", "漏洞", "不好看", "哪里不对")),
    ("writer", ("怎么写", "文风", "写法", "示范", "描写", "对话")),
    ("lorekeeper", ("人物", "设定", "境界", "地点", "势力", "物品", "金手指")),
)


def pick_role(text: str) -> str:
    return next((role for role, words in ROLE_WORDS if any(word in text for word in words)), "chief")


async def supports_tools(role: str) -> bool:
    """普通群聊工具与结构化输出无关；没试过就试，只有明确拒绝过才走分流。"""
    profile = await LLMRouter(get_sessionmaker()).resolve(role)
    if profile.provider == "demo":
        return demo.FAKE_TOOLS
    url = urlparse(profile.base_url or "")
    if url.hostname in LOCAL_HOSTS or url.port == 11434:
        return False
    return profile.chat_tools is not False


@dataclass
class Turn:
    """一句话的这一轮：程序替模型记着做到哪了。"""

    redis: Any
    book_id: uuid.UUID
    message_id: int
    reply_id: int
    role: str
    read_only: bool
    viewing: dict | None
    allow_skills: bool = True
    allow_memories: bool = True
    memory_actions: list[dict] = field(default_factory=list)
    book_changed: bool = False
    # 做过的那几处（重试时跳过同一处）；算进处数的那几处
    done_keys: set[str] = field(default_factory=set)
    touched: set[str] = field(default_factory=set)
    acts: int = 0
    stopping: bool = False
    in_action: bool = False
    last_activity: float = field(default_factory=time.monotonic)
    parts: list[str] = field(default_factory=list)
    # 回答下面「查了：……」、重新回答照着说的：[{kind, label, text}]
    tools: list[dict] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.last_activity = time.monotonic()


async def set_doing(turn: Turn, text: str, *, ellipsis: bool = True) -> None:
    """回答框里那一行跟着变：「在查陈默……」「在改陈默的性格……」。"""
    async with get_sessionmaker()() as session:
        reply = await session.get(MeetingMessage, turn.reply_id)
        if reply is None or (reply.payload or {}).get("state") not in LIVE:
            return
        reply.content = ""
        reply.payload = {**(reply.payload or {}), "state": "thinking", "doing": text + ("……" if ellipsis else "")}
        await session.commit()
        await publish(turn.redis, turn.book_id, "message_update", message_dict(reply))


async def update_note(session, turn: Turn, **payload) -> None:
    from app.services.group_notes import update_message

    message = await session.get(MeetingMessage, turn.message_id)
    await session.refresh(message)
    await update_message(session, turn.redis, message, **payload)


class Stopped(Exception):
    """作者点了「停」：正在改的那一处改完了，不再接着问模型。"""


async def run_tool(turn: Turn, call: ToolCall) -> str:
    turn.touch()
    if turn.stopping:
        raise Stopped
    try:
        if call.name == "read_skill" and not turn.allow_skills:
            return "拆的书群聊不能翻手册。"
        args = chat_tools.tool_args(call.name, call.args or {})
    except Exception as exc:
        return f"参数不对：{exc}。照工具说明重新调一次。"
    if call.name in chat_tools.MEMORY_TOOLS:
        if not turn.allow_memories:
            return "拆的书群聊不能用记忆。"
        return await memory_tool(turn, call.name, args)
    if isinstance(args, chat_tools.MakeChanges):
        if turn.read_only:
            return "作者这句话是在问，只查只答，不能动手；觉得该改，在回答里问作者一句要不要改。"
        result = await act(turn, args)
        if turn.stopping:
            raise Stopped
        return result
    await set_doing(turn, chat_tools.doing_of(call.name, args), ellipsis=not isinstance(args, chat_tools.ReadSkill))
    async with get_sessionmaker()() as session:
        book = await session.get(Book, turn.book_id)
        try:
            label, text = await chat_tools.look_up(session, book, call.name, args, turn.viewing)
        except Exception as exc:
            log.exception("聊天里查资料出错")
            label, text = chat_tools.doing_of(call.name, args).removeprefix("在"), f"没查成：{exc}"
        await session.rollback()
    turn.tools.append({"kind": "query", "label": label, "text": text})
    turn.touch()
    return text


async def memory_tool(turn: Turn, name: str, args) -> str:
    from app.services.chat_memories import execute
    from app.services.group_notes import update_message
    from app.services.memories import notify

    await set_doing(turn, chat_tools.doing_of(name, args))
    turn.in_action = True
    try:
        async with get_sessionmaker()() as session:
            text, outcome, queries = await execute(session, turn.book_id, turn.message_id, args)
            if outcome:
                outcome["model_text"] = text
                reply = await session.get(MeetingMessage, turn.reply_id)
                actions = [*((reply.payload or {}).get("memories") or []), outcome]
                await update_message(session, turn.redis, reply, memories=actions)
                turn.memory_actions = actions
                await notify(session, turn.redis)
                turn.finished.append(done_text(outcome))
            else:
                await session.rollback()
            turn.tools.extend({"kind": "query", "label": label, "text": block} for label, block in queries)
            return text
    finally:
        turn.in_action = False
        turn.touch()


async def act(turn: Turn, args: chat_tools.MakeChanges) -> str:
    """动手：程序数处数，一两处直接改，三处以上或要删东西整理成方案卡。正在改的那一处改完才停。"""
    if turn.acts >= chat_tools.MAX_ACTS:
        return "这句话已经动过两回手了，不能再动。把做了什么告诉作者，还要改的请他再说一句。"
    turn.acts += 1
    if not args.items:
        return "清单是空的，什么也没做。"
    turn.in_action = True
    try:
        async with get_sessionmaker()() as session:
            book = await session.get(Book, turn.book_id)
            places = [await chat_tools.place_of(session, book, item, turn.viewing) for item in args.items]
            await session.rollback()
        lines, todo = [], []
        for item, (key, counted) in zip(args.items, places, strict=True):
            if key in turn.done_keys:
                lines.append(f"「{chat_tools.item_doing(item).removeprefix('在')}」这一处之前已经做过了，没有再做。")
            else:
                todo.append((item, key, counted))
        if not todo:
            return "\n".join(lines)
        counted = {key for _, key, c in todo if c}
        deleting = any(item.kind == "删除" for item, _, _ in todo)
        if deleting or len(turn.touched | counted) > chat_tools.DIRECT_LIMIT:
            lines.append(await make_card(turn, args, [item for item, _, _ in todo], deleting))
            return "\n\n".join(lines)
        turn.touched |= counted
        for item, key, _ in todo:
            if turn.stopping:
                turn.skipped.append(chat_tools.item_doing(item).removeprefix("在"))
                lines.append(f"「{chat_tools.item_doing(item).removeprefix('在')}」没做：作者让停下了。")
                continue
            await set_doing(turn, chat_tools.item_doing(item))
            outcome, said = await do_one(turn, item, key)
            lines.append(chat_tools.result_text(item, outcome, said))
            turn.touch()
        turn.tools.append({"kind": "act", "label": f"动手 {len(todo)} 处", "text": "\n\n".join(lines)})
        return "\n\n".join(lines)
    finally:
        turn.in_action = False
        turn.touch()


async def do_one(turn: Turn, item: chat_tools.ChangeItem, key: str) -> tuple[dict, list[str]]:
    """照清单的一条去做，结果挂在作者那句话下面（前后对照、换回原来的、再改一版都现成）。"""
    from app.services.group_notes import failure_reason

    async with get_sessionmaker()() as session:
        message = await session.get(MeetingMessage, turn.message_id)
        try:
            outcome, said = await chat_tools.run_change(session, turn.redis, message, item)
        except Exception as exc:
            await session.rollback()
            log.info("聊天里动手没做成：%s", exc)
            outcome, said = {"kind": "failed", "reason": failure_reason(exc)}, []
        turn.book_changed |= bool(outcome.get("change"))
        outcome["key"] = key
        message = await session.get(MeetingMessage, turn.message_id)
        await session.refresh(message)
        steps = [*((message.payload or {}).get("steps") or []), outcome]
        await update_note(session, turn, steps=steps, outcome={"kind": "agent"})
    if outcome.get("kind") not in ("failed", "not_found", "too_late"):
        turn.done_keys.add(key)
        turn.finished.append(done_text(outcome) or chat_tools.item_doing(item).removeprefix("在"))
    return outcome, said


async def make_card(turn: Turn, args: chat_tools.MakeChanges, items: list, deleting: bool) -> str:
    """要动的多、或者要删东西：不直接改，整理成方案卡，作者能划掉不要的，点「按这个来」才改。"""
    from app.services.chat_plans import latest_plan, plan_text
    from app.services.group_notes import update_message

    await set_doing(turn, "在整理方案卡")
    async with get_sessionmaker()() as session:
        book = await session.get(Book, turn.book_id)
        title = re.sub(r"\s+", "", args.title)[:12] or "这次要改的"
        why = "还要删东西" if deleting else f"一次要动 {len(items)} 处"
        plan = {
            "title": title,
            "summary": f"这句话{why}，先列在这里：看过、划掉不要的、点文字能改，点「按这个来」才改。",
            "items": await chat_tools.plan_items(session, book, items),
            "open_questions": [],
        }
        previous = await latest_plan(session, turn.book_id, "group")
        while previous:
            await update_message(session, turn.redis, previous, status="superseded")
            previous = await latest_plan(session, turn.book_id, "group")
        data = await post_message(
            session,
            turn.redis,
            book_id=turn.book_id,
            job_id=None,
            speaker=turn.role,
            kind="plan",
            content=plan_text(plan),
            payload={"plan": plan, "status": "open", "results": [], "from_note": turn.message_id},
        )
        message = await session.get(MeetingMessage, turn.message_id)
        await session.refresh(message)
        step = {"kind": "plan_made", "plan_id": data["id"], "count": len(items), "deleting": deleting}
        await update_note(session, turn, steps=[*((message.payload or {}).get("steps") or []), step])
    turn.tools.append({"kind": "act", "label": f"方案卡「{title}」", "text": plan_text(plan)})
    return (
        f"这 {len(items)} 处没有直接改：{why}，整理成了方案卡「{title}」，在你这条回答的下面。"
        "作者看过点「按这个来」才会改。回答里告诉作者去看方案卡，别说已经改了。"
    )


async def drive(turn: Turn, system: str, user: str) -> str:
    pushed = 0.0
    llm = LLMRouter(get_sessionmaker(), book_id=turn.book_id)
    try:
        async for kind, value in llm.tool_rounds(
            turn.role,
            system,
            user,
            chat_tools.tool_specs(turn.read_only, skills=turn.allow_skills, memories=turn.allow_memories),
            lambda call: run_tool(turn, call),
            purpose=f"聊天·{SPEAKER_NAMES[turn.role]}",
            max_rounds=MAX_ROUNDS,
        ):
            turn.touch()
            if kind == "tick":
                continue
            if kind == "reset":
                turn.parts.clear()
                continue
            turn.parts.append(value)
            now = time.monotonic()
            if now - pushed >= PUSH_EVERY:
                pushed = now
                await publish(
                    turn.redis, turn.book_id, "chat_delta", {"id": turn.reply_id, "text": "".join(turn.parts)}
                )
    finally:
        await llm.aclose()
    return "".join(turn.parts)


async def watch(turn: Turn, task: asyncio.Task) -> str | None:
    """看着这一轮：作者点「停」时，查资料、说话马上停，正在改的那一处改完再停；按进度算超时。返回 None 是停下了。"""
    started = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=0.25)
        if done:
            try:
                return task.result()
            except Stopped:
                return None
        if not turn.stopping and await turn.redis.exists(stop_key(turn.reply_id)):
            turn.stopping = True
        if turn.in_action:
            continue
        if turn.stopping:
            return None
        if time.monotonic() - turn.last_activity > IDLE_LIMIT:
            raise TimeoutError(f"{IDLE_LIMIT} 秒没动静")
        if time.monotonic() - started > TOTAL_LIMIT:
            raise TimeoutError(f"{TOTAL_LIMIT // 60} 分钟还没做完")


def failure(exc) -> str:
    from app.services.group_notes import failure_reason

    # 这一轮自己的超时（多久没动静、多久没做完）照实说，不说成「判断超时」
    if isinstance(exc, TimeoutError) and str(exc):
        return f"超时了：{exc}"
    return failure_reason(exc) or type(exc).__name__


def stop_text(turn: Turn, text: str) -> str:
    """停下时说改到哪了。"""
    notes = []
    if turn.finished:
        notes.append("停之前做完了：" + "；".join(turn.finished))
    if turn.skipped:
        notes.append("没做：" + "、".join(turn.skipped))
    return (text + "\n\n" if text else "") + ("（" + "；".join(notes) + "）" if notes else "")


def first_line(text: str, limit: int = 40) -> str:
    line = re.split(r"(?<=[。！？!?])|\n", (text or "").strip(), maxsplit=1)[0].strip()
    return line if len(line) <= limit else line[:limit] + "…"


def outline_of(ctx, full: bool) -> str:
    """大纲：篇、卷、单元各一段话（书小时全文；书大了每段只留第一句，要细节自己查）。章不列，要看自己查。"""
    cut = (lambda text: (text or "").strip()) if full else first_line
    lines: list[str] = []

    def volume_lines(volume, indent):
        lines.append(f"{indent}第 {volume.index} 卷「{volume.title}」：{cut(volume.summary)}")
        lines.extend(
            f"{indent}  单元 {u.index}「{u.title}」：{cut(u.summary)}" for u in ctx.units if u.volume_id == volume.id
        )

    arcs = ctx._arcs()
    if any(node.segment is not None for node in ctx.nodes):
        for i, node in enumerate(arcs, 1):
            plan = node.segment or {}
            later = "" if node.segment is not None else "（写到再定）"
            lines.append(f"第 {i} 篇「{plan.get('title', node.title)}」{later}：{cut(plan.get('text') or node.event)}")
            for volume in ctx.volumes:
                if volume.target_node_id == node.id:
                    volume_lines(volume, "  ")
        placed = {node.id for node in arcs}
        loose = [v for v in ctx.volumes if v.target_node_id not in placed]
    else:
        loose = list(ctx.volumes)
    for volume in loose:
        volume_lines(volume, "")
    ending = next((node for node in reversed(ctx.nodes) if node.kind == "ending"), None)
    if ending is not None:
        lines.append(f"结局：{cut(ending.event)}")
    elif ctx.concept_ending:
        lines.append(f"结局：{cut(ctx.concept_ending)}")
    return "\n".join(lines) or "（还没有大纲）"


async def viewing_full(session, book, ctx, viewing) -> str:
    """作者正在看的那一页的全文：说「这一条」「这一篇」就是它。"""
    if not viewing:
        return "（没说，或者在旧版页面上）"
    kind, target_id, label = viewing.get("target_type"), str(viewing.get("target_id") or ""), viewing.get("label") or ""
    try:
        if kind in ("character", "entry"):
            target = next((t for t in ctx.targets if str(t.id) == target_id and target_type_of(t) == kind), None)
            if target is not None:
                return chat_tools.clip(ctx.entry_full_text(target))
        elif kind == "concept":
            return "简介：" + ((book.concept or {}).get("story") or "（还没写）")
        elif kind in ("book", "segment", "volume", "unit", "chapter"):
            return chat_tools.clip(await chat_tools.outline_piece(session, book, kind, target_id))
    except Exception:
        log.info("没读出作者正在看的那一页：%s", viewing)
    return label or "（作者在看某一页）"


ACT_RULE = "作者明说要改、要写的，自己动手（make_changes）：改一栏、补齐空着的栏目、出三种写法、新建设定卡、写大纲上的一段（还没有的下一篇也能写）、改简介、删掉一张卡或还没开写的一段。作者只是问、商量、出主意的，只查只答，不要动手；拿不准是要改还是在问，就当成在问，最后问一句要不要改。作者说了「先别改」「先别动」「我再想想」的，哪怕说的是以后怎么写，也一处都不动，写书时照做的规矩也不记，只聊。"

ASK_RULE = "作者这句话是在问。只查只答，不要动手改书；你觉得该改，最多在回答里问一句要不要改。"


def retry_note(steps: list[dict]) -> str:
    done = [done_text(o) for o in steps if o.get("kind") != "failed" and done_text(o)]
    return tagged(
        "上次做到一半",
        "这句话上次没做完就断了。"
        + (f"已经做完的：{'；'.join(done)}。这次只接着做没做完的，做过的不要再做。" if done else "这次重新做。"),
    )


async def agent_values(session, book, role, message, rows, summary, read_only, retry) -> dict:
    if book.source == "teardown":
        from app.services.teardown_chat import values

        return await values(session, book, role, message, rows, summary, tools=True, retry=retry)
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
    full_library, full_outline = ctx.library_full, outline_of(ctx, full=True)
    small = len(full_library) + len(full_outline) <= SMALL_BOOK
    payload = message.payload or {}
    quote = payload.get("quote")
    busy = job is not None and job.status in jobs.BUSY_STATUSES
    return dict(
        material_note="" if small else "（书比较大：设定和大纲只列了目录，要细节用工具查）",
        concept=ctx.concept,
        library=(full_library or "（还没有设定）")
        if small
        else "这里只列名字和一句话，要细节用 look_up_settings 查：\n" + ctx.library,
        outline=full_outline if small else outline_of(ctx, full=False),
        progress=await progress_of(session, ctx, chapters, job),
        memory=await memory_directory(session, book.id),
        viewing=await viewing_full(session, book, ctx, payload.get("viewing")),
        pending=pending_of(job, ctx),
        working=tagged(
            "编辑部正在干活",
            "编辑部正在写书。这时改设定不会马上改，会放进待处理的建议，等写完作者点「现在改」；大纲这时改不了；记忆照常能记，写书时照做的，正在写的编辑部从下一步起照办。",
        )
        if busy
        else "",
        summary=summary or "（没有）",
        recent=dialogue_text(rows[-20:]),
        quote=tagged("作者选中的原文", f"（{quote['where']}）\n{quote['text'][:2000]}") if quote else "",
        retry=retry_note(payload.get("steps") or []) if retry else "",
        note=message.content,
        act_rule=ASK_RULE if read_only else ACT_RULE,
        role_focus=ROLE_FOCUS[role],
    )


async def answer_note(redis, book_id, message_id, *, reply_id=None, retry=False) -> None:
    """答作者的一句话（调用方已经拿着群聊的锁）：先占一条回答，接话的人自己查、自己动手，最后说一段话。"""
    sm = get_sessionmaker()
    async with sm() as session:
        message = await session.get(MeetingMessage, message_id)
        if message is None:
            return
        payload = dict(message.payload or {})
        role = payload.get("chat_role") or "chief"
        if reply_id is None:
            reply = await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=None,
                speaker=role,
                kind="speech",
                content="",
                payload={"reply_to": [message_id], "state": "thinking", "tools_mode": True},
            )
            reply_id = reply["id"]
        book = await session.get(Book, book_id)
        teardown = book.source == "teardown"
        read_only = teardown or bool(payload.get("ask_only"))
        # 只带这句话所在的那一段对话和它的摘要
        state = await conversation_state(session, book_id, "group", payload.get("conv"))
        await session.commit()
        rows = [m for m in await dialogue(session, book_id, "group", conv=state.id) if m.id < message_id]
        old = [m for m in rows[:-20] if m.id > state.summarized_until]
        summary = await merge_summary(session, book_id, "group", state.summary, old, state.id)
        book = await session.get(Book, book_id)
        message = await session.get(MeetingMessage, message_id)
        values = await agent_values(session, book, role, message, rows, summary, read_only, retry)
        await session.rollback()
    turn = Turn(
        redis,
        book_id,
        message_id,
        reply_id,
        role,
        read_only,
        payload.get("viewing"),
        allow_skills=not teardown,
        allow_memories=not teardown,
    )
    if retry:
        async with sm() as session:
            previous_reply = await session.get(MeetingMessage, reply_id)
            turn.memory_actions = list((previous_reply.payload or {}).get("memories") or [])
        for step in payload.get("steps") or []:
            if step.get("key") and step.get("kind") not in ("failed", "not_found", "too_late"):
                turn.done_keys.add(step["key"])
                if step.get("kind") not in ("created", "requirement", "to_job", "plan_made"):
                    turn.touched.add(step["key"])
    await publish(redis, book_id, "chat_typing", {"thread": "group", "speaker": role, "on": True})
    text, state_name, error, finished = "", "failed", "", False
    try:
        task = asyncio.create_task(
            drive(turn, persona(role), render("chat_teardown" if teardown else "chat_agent", **values))
        )
        try:
            result = await watch(turn, task)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if result is None:
            text, state_name = stop_text(turn, "".join(turn.parts).strip()), "stopped"
        else:
            text, state_name = result.strip(), "done"
            if not text and turn.finished:
                text = "做好了：" + "；".join(turn.finished) + "。在你那句话下面看前后对照。"
            if not text:
                state_name, error = "failed", "模型什么也没说"
    except ToolsUnsupported:
        log.warning("这个模型不认工具调用，这句话改走分流")
        try:
            finished = await fall_back(redis, book_id, message_id, reply_id, role)
        except Exception as exc:
            log.exception("改走分流也没办成")
            error = failure(exc)
    except Exception as exc:
        log.exception("聊天里自己查、自己动手出错")
        error = failure(exc)
    finally:
        await publish(redis, book_id, "chat_typing", {"thread": "group", "speaker": role, "on": False})
        async with sm() as session:
            reply = await session.get(MeetingMessage, reply_id)
            if reply is not None:
                reply.payload = {
                    **{k: v for k, v in (reply.payload or {}).items() if k not in ("doing", "again")},
                    "tools": turn.tools,
                }
                await session.commit()
            if not finished:
                await finish_reply(session, redis, reply_id, text if state_name != "failed" else "", state_name, error)
            message = await session.get(MeetingMessage, message_id)
            if message is not None and not finished:
                await session.refresh(message)
                if not (message.payload or {}).get("steps"):
                    await update_note(session, turn, outcome={"kind": "chat", "handled": True})
                elif ((message.payload or {}).get("outcome") or {}).get("kind") != "agent":
                    await update_note(session, turn, outcome={"kind": "agent"})
            # 动完存一档：一句话一档
            if turn.book_changed:
                await book_saves.safe_checkpoint(session, book_id, role, lead=f"{SPEAKER_NAMES[role]}照你的话")
        if turn.finished:
            for event in ("library", "saves"):
                await publish(redis, book_id, event, {"id": str(book_id)})


async def fall_back(redis, book_id, message_id, reply_id, role) -> bool:
    """模型不认工具调用：这一句照旧走分流（判断、去做），回答写进已经占好的那一条。"""
    from app.services import group_notes

    sm = get_sessionmaker()
    said: list[str] = []
    token = group_notes.SAID.set(said)
    try:
        async with sm() as session:
            message = await session.get(MeetingMessage, message_id)
            text, viewing = message.content, (message.payload or {}).get("viewing")
            conv = (message.payload or {}).get("conv")
            book = await session.get(Book, book_id)
            teardown = book.source == "teardown"
            intent = (
                None
                if teardown
                else await group_notes.classify(session, book_id, text, viewing, conv, before=message_id)
            )
            if teardown or (intent.kind == "提问闲聊" and not intent.more):
                state = await conversation_state(session, book_id, "group", conv)
                await session.commit()
                conv = state.id
                rows = [m for m in await dialogue(session, book_id, "group", conv=conv) if m.id < reply_id]
                old = [m for m in rows[:-20] if m.id > state.summarized_until]
                summary = state.summary
                message = await session.get(MeetingMessage, message_id)
                await group_notes.update_message(session, redis, message, outcome={"kind": "chat", "handled": True})
                session.expunge_all()
                await session.rollback()
                await answer(session, redis, book_id, "group", role, reply_id, rows, [message], summary, old, conv=conv)
                return True
            more = [step.strip() for step in intent.more or [] if step.strip()][:3]
            if more:
                await group_notes.apply_steps(session, redis, message, intent, more, viewing)
            else:
                await group_notes.apply_with_change(session, redis, message, intent)
            if group_notes.changed_book(await session.get(MeetingMessage, message_id)):
                await book_saves.safe_checkpoint(session, book_id, role, lead=f"{SPEAKER_NAMES[role]}照你的话")
            await finish_reply(session, redis, reply_id, "\n".join(said) or "办好了，在你那句话下面看。", "done")
    finally:
        group_notes.SAID.reset(token)
    for event in ("library", "saves"):
        await publish(redis, book_id, event, {"id": str(book_id)})
    return True


async def agent_background(book_id, redis) -> None:
    """群聊里交给接话的人自己办的话：一句一轮，按先后一句一句答。"""
    async with conversation_lock(redis, book_id, "group"):
        while True:
            async with get_sessionmaker()() as session:
                state = await thread_of(session, book_id, "group")
                await session.commit()
                answered = await answered_ids(session, book_id, "group", state.reset_after)
                message_id = await session.scalar(
                    select(MeetingMessage.id)
                    .where(
                        MeetingMessage.book_id == book_id,
                        MeetingMessage.id > state.reset_after,
                        MeetingMessage.speaker == "author",
                        MeetingMessage.payload["turn"].astext == "tools",
                        # 「从这里重来」收起来的不答
                        MeetingMessage.payload["dropped"].astext.is_(None),
                        MeetingMessage.id.not_in(list(answered) or [0]),
                    )
                    .order_by(MeetingMessage.id)
                    .limit(1)
                )
            if message_id is None:
                return
            await answer_note(redis, book_id, message_id)
