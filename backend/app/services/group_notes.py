"""群聊先落消息，再按消息序号串行判断；聊天永不偷偷变成要求。"""

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.schemas import LibraryIntent
from app.api.library_ai import RewriteIn, call_model, rewrite_target, say
from app.db import get_sessionmaker
from app.models import Book, Job, MeetingMessage, SettingSuggestion, SettingVersion
from app.schemas import ArcCreate, DraftRequest, MeetingMessageOut
from app.services import jobs
from app.services.chat import conversation_lock, reply_background
from app.services.chat_context import (
    ROLES,
    accepts_plan,
    dialogue,
    dialogue_text,
    obvious_question,
    thread_of,
    wants_new_pitches,
    wants_plan,
)
from app.services.desk import (
    category_label,
    category_layout,
    column_in,
    fill_entry,
    path_of,
    resolve_category,
    save_drafted,
    value_of,
)
from app.services.library import lock_book
from app.services.library_context import load_context
from app.services.meeting import message_dict, post_message, publish
from app.services.outline_write import new_arc_number, resolve_outline_target, write_outline_node
from app.services.requirements import SCOPE_INPUTS, add_requirement
from app.services.versions import target_type_of


async def active_note_job(session, book_id):
    return await session.scalar(
        select(Job)
        .where(Job.book_id == book_id, Job.status.in_(jobs.ACTIVE_STATUSES))
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def waiting_feedback(job):
    return (
        job
        and job.status == "waiting_author"
        and (job.pending or {}).get("kind") != "setup_prefill"
        and not jobs.open_wait(job)
    )


async def update_message(session, redis, message, **payload):
    message.payload = {**(message.payload or {}), **payload}
    await session.commit()
    await session.refresh(message)
    data = message_dict(message)
    await publish(redis, message.book_id, "message_update", data)
    return data


def viewing_text(viewing):
    """作者发话时正在看哪一页：给分流看，「这一篇」「这一条」指的就是它。"""
    if not viewing:
        return "（没说，或者在旧版页面上）"
    return viewing.get("label") or "（作者在看某一页，没有名字）"


async def classify(session, book_id, text, viewing=None):
    book = await session.get(Book, book_id)
    ctx = await load_context(session, book)
    state = await thread_of(session, book_id, "group")
    recent = dialogue_text((await dialogue(session, book_id, "group", state.reset_after))[-6:])
    library, outline = ctx.library, ctx.outline
    await session.commit()
    return await asyncio.wait_for(
        call_model(
            book_id,
            "router",
            LibraryIntent,
            "library_route",
            library=library,
            outline=outline,
            recent=recent,
            viewing=viewing_text(viewing),
            note=text,
            single_attempt=True,
        ),
        timeout=60,
    )


async def chatted_since_wait(session, book_id, job):
    state = await thread_of(session, book_id, "group")
    return (
        await session.scalar(
            select(MeetingMessage.id)
            .where(
                MeetingMessage.book_id == book_id,
                MeetingMessage.id > state.reset_after,
                MeetingMessage.created_at >= job.updated_at,
                MeetingMessage.payload["reply_to"].is_not(None),
                MeetingMessage.payload["thread"].astext.is_(None),
            )
            .limit(1)
        )
        is not None
    )


async def receive_note(body, background_tasks, book, session, redis):
    from app.services.chat_plans import latest_plan, make_plan_background, request_apply

    text, book_id, thread = body.content.strip(), book.id, body.to or "group"
    if not text:
        raise HTTPException(422, "请写下你的话")
    payload = {
        "requirement_saved": True,
        **({"thread": thread} if body.to else {}),
        **({"quote": body.quote.model_dump()} if body.quote else {}),
        # 新书页上带：作者正在看哪一页（只在群聊里用来认「这一篇」「这一条」）
        **({"viewing": body.viewing.model_dump()} if body.viewing and not body.to else {}),
        **({"ask": body.ask} if body.ask and not body.to else {}),
    }
    plan = None
    if wants_plan(text):
        payload["outcome"] = {"kind": "plan_pending"}
        task = "plan"
    elif accepts_plan(text):
        plan = await latest_plan(session, book_id, thread)
        payload["outcome"] = {"kind": "plan_apply", "plan_id": plan.id} if plan else {"kind": "chat"}
        task = "apply"
    elif body.to or (role := obvious_question(text)):
        payload.update(
            outcome={"kind": "chat", **({"shortcut": True} if not body.to else {})},
            chat_role=body.to or body.ask or role,
        )
        task = "reply"
    else:
        job = await active_note_job(session, book_id)
        if jobs.open_wait(job) and wants_new_pitches(text):
            raise HTTPException(409, {"code": "use_feedback", "message": "等你拍板时请直接提意见"})
        if waiting_feedback(job):
            try:
                intent = await classify(session, book_id, text, payload.get("viewing"))
            except Exception as exc:
                raise HTTPException(502, f"模型出错了：{exc}") from exc
            session.expire_all()
            job = await active_note_job(session, book_id)
            if intent.kind != "提问闲聊" and waiting_feedback(job):
                if not await chatted_since_wait(session, book_id, job):
                    raise HTTPException(409, {"code": "use_feedback", "message": "等你拍板时请直接提意见"})
                payload["outcome"] = {"kind": "plan_made"}
                task = "plan"
            else:
                payload["outcome"] = {"kind": "pending"}
                task = intent
        else:
            payload["outcome"] = {"kind": "pending"}
            task = "route"
    # Commit author messages in id order, without waiting for slow classification.
    async with conversation_lock(redis, book_id, "note_append"):
        data = await post_message(
            session, redis, book_id=book_id, job_id=None, speaker="author", kind="note", content=text, payload=payload
        )
    if task == "plan":
        background_tasks.add_task(make_plan_background, book_id, thread, data["id"], redis)
    elif task == "apply":
        if plan:
            # A fresh row lock after author-message commit makes double-clicks atomic.
            await request_apply(session, redis, plan.id, None, background_tasks)
        else:
            await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=None,
                speaker="chief",
                kind="speech",
                content="还没有方案可以照办。想让我把前面聊的整理成方案，就说「总结一下」。",
                payload={"reply_to": [data["id"]], **({"thread": thread} if body.to else {})},
            )
    elif task == "reply":
        background_tasks.add_task(reply_background, book_id, thread, redis)
    elif task == "route":
        background_tasks.add_task(route_background, book_id, redis)
    else:
        background_tasks.add_task(route_background, book_id, redis, data["id"], task)
    return MeetingMessageOut(**data)


# 作者明说要改名时，part 才会是这几种说法
NAME_PARTS = {"名称", "名字", "姓名", "名"}
# 判断完以后真正去改、去补：最多等这么久，到了就停手，不改
ACTION_TIMEOUT = 150


async def apply_intent(session, redis, message, intent):
    book_id, text, message_id = message.book_id, message.content, message.id
    # State checked at classification completion, with the same lock as manual edits/start writing.
    await lock_book(session, book_id)
    session.expire_all()
    book = await session.get(Book, book_id)
    job = await active_note_job(session, book_id)
    message = await session.get(MeetingMessage, message_id)
    if intent.kind != "提问闲聊" and waiting_feedback(job):
        await update_message(session, redis, message, outcome={"kind": "too_late"})
        return False
    if intent.kind == "提问闲聊":
        # 作者点了名就由他答，没点名照分流挑的人
        role = (message.payload or {}).get("ask") or ROLES[intent.who]
        await update_message(session, redis, message, outcome={"kind": "chat"}, chat_role=role)
        return True
    working = job is not None and job.status in jobs.BUSY_STATUSES
    if intent.kind == "写大纲":
        return await write_outline_from_chat(session, redis, book, message, intent)
    if intent.kind in ("改设定", "新建设定") and working and job.kind != "book_setup":
        title = text[:40] + ("……" if len(text) > 40 else "")
        suggestion = SettingSuggestion(
            book_id=book_id,
            kind="chat",
            title=f"群聊里说的：{title}（编辑部当时在写，没改）",
            payload={"op": "note", "content": text},
        )
        session.add(suggestion)
        await session.flush()
        outcome = {"kind": "later", "suggestion_id": str(suggestion.id)}
        reply = "编辑部正在写，这一处等写完再改。我放进待处理的建议了，写完点「现在改」。"
    elif intent.kind == "新建设定" and not working:
        return await create_from_chat(session, redis, book, message, intent)
    elif intent.kind == "写作要求" or working:
        row = await add_requirement(
            session, book_id, intent.requirement or text, "note", SCOPE_INPUTS[intent.scope], message_id=message_id
        )
        outcome = {"kind": "to_job" if working else "requirement", "requirement_id": str(row.id)}
        message.job_id = job.id if working else None
        reply = intent.reply or "记下了。"
    else:
        ctx = await load_context(session, book)
        target = ctx.find_target(intent.target_name)
        if target is None:
            outcome = {"kind": "not_found", "target_name": intent.target_name}
            reply = (
                f"设定库里还没有「{intent.target_name}」。要新写一条就说「新建{intent.target_name}」；"
                "要改的是别的哪一条，说一下它的名字。"
            )
        else:
            # 先按新书页上这一条的栏目认改哪一栏：模型写的 part，或者作者话里提到的栏目名
            key = (
                None if intent.part.strip() in NAME_PARTS else await column_in(session, book, target, intent.part, text)
            )
            if key is not None:
                path = path_of(target, key)
                value = value_of(target, key)
                if intent.quote and intent.quote in value:
                    start = value.index(intent.quote)
                    path = f"{path}@{start}:{start + len(intent.quote)}"
            else:
                path = ctx.route_path(target, intent.part, intent.quote)
            # 说不清改哪一栏时，程序会退到名字上：除非作者明说改名，不拿名字开刀，当成补齐
            unclear = path.split("@", 1)[0] == "name" and intent.part.strip() not in NAME_PARTS
            target_type, target_id, name = target_type_of(target), target.id, target.name
            if intent.mode == "补齐空着的" or unclear:
                await update_message(
                    session, redis, message, outcome={"kind": "working", "text": f"设定师在补「{name}」空着的栏目"}
                )
                result = await fill_entry(session, book, target_type, target_id, intent.instruction or text)
                message = await session.get(MeetingMessage, message_id)
                outcome = {
                    "kind": "fill",
                    "target_type": target_type,
                    "target_id": str(target_id),
                    "target_label": name,
                    "filled": result["filled"],
                    "revert_version_id": result["revert_version_id"],
                }
                if not result["filled"]:
                    reply = f"「{name}」每一栏都写了。想改哪一栏就直接说，比如「{name}的身世改成……」。"
                elif unclear and intent.mode != "补齐空着的":
                    reply = f"你没说改「{name}」哪一栏，我先把空着的 {len(result['filled'])} 栏补上了，在卡上看。想改别的就说具体哪一栏。"
                else:
                    reply = f"补好了「{name}」空着的 {len(result['filled'])} 栏：{'、'.join(result['filled'])}。在卡上看，不满意可以撤销。"
            else:
                body = RewriteIn(
                    target_type=target_type,
                    target_id=target_id,
                    path=path,
                    mode="options" if intent.mode == "给几个写法" else "instruction",
                    instruction=intent.instruction or text,
                    quiet=True,
                )
                outcome = {
                    "kind": "edit",
                    "target_type": body.target_type,
                    "target_id": str(body.target_id),
                    "target_label": ctx.target_label(target, body.path),
                    "mode": body.mode,
                }
                doing = "出三种写法" if body.mode == "options" else "改"
                await update_message(
                    session,
                    redis,
                    message,
                    outcome={"kind": "working", "text": f"设定师在{doing}「{outcome['target_label']}」"},
                )
                try:
                    result = await asyncio.wait_for(
                        rewrite_target(session, redis, book, body, require_idle=True), timeout=ACTION_TIMEOUT
                    )
                except TimeoutError as exc:
                    raise HTTPException(504, "这次编辑部太慢了，两分半还没写完，没改。再试一次") from exc
                message = await session.get(MeetingMessage, message_id)
                if body.mode == "options":
                    outcome["candidate_id"] = str(result["candidate"].id)
                else:
                    outcome["revert_version_id"] = result.get("revert_version_id") or await revert_id(
                        session, body.target_type, body.target_id
                    )
                reply = intent.reply or (
                    "三种写法在这条消息下面，挑一个换上。" if body.mode == "options" else "改好了，去看看。"
                )
    await update_message(session, redis, message, outcome=outcome)
    if reply:
        await say(session, redis, book_id, (message.payload or {}).get("ask") or "chief", reply)
    return False


async def write_outline_from_chat(session, redis, book, message, intent):
    """群聊里说「帮我写一下这一篇」：认出大纲上哪一段，主编直接写进去，消息下面能撤销。
    编辑部正在干活时写不了，write_outline_node 会报出来，消息上显示没做成。"""
    book_id, message_id = book.id, message.id
    viewing = (message.payload or {}).get("viewing")
    found = await resolve_outline_target(session, book, intent.outline_target, viewing)
    created = None
    if found is None and (number := await new_arc_number(session, book, intent.outline_target)):
        # 要写的那一篇还没有、又正好是下一篇：先在最后加上空的一篇，再写
        from app.api.workspace import create_arc

        created = (await create_arc(ArcCreate(), book, session))["id"]
        found = ("segment", created, f"第 {number} 篇")
    if found is None:
        said = intent.outline_target if intent.outline_target and intent.outline_target != "正在看的" else ""
        await update_message(session, redis, message, outcome={"kind": "not_found", "target_name": said or "这一段"})
        head = f"没认出要写大纲上的「{said}」。" if said else "没认出要写大纲上的哪一段。"
        await say(
            session,
            redis,
            book_id,
            "chief",
            head + "先在新书页打开那一页再说「帮我写这一段」，或者说清是第几篇、第几卷、第几章。",
        )
        return False
    target_type, target_id, label = found
    await update_message(session, redis, message, outcome={"kind": "working", "text": f"主编在写{label}"})
    try:
        result = await write_outline_node(session, book, target_type, target_id, intent.instruction or message.content)
    except Exception:
        if created:
            # 没写成：刚加的空篇也拿掉
            from app.api.workspace import delete_arc

            await session.rollback()
            await delete_arc(uuid.UUID(created), session)
        raise
    message = await session.get(MeetingMessage, message_id)
    outcome = {
        "kind": "outline",
        "target_type": target_type,
        "target_id": target_id,
        "target_label": label,
        "before": result["before"],
        # 新加的这一篇：撤销就把整篇删掉
        **({"created_id": created} if created else {}),
    }
    await update_message(session, redis, message, outcome=outcome)
    note = result.get("note", "").strip().removeprefix("思路：").removeprefix("这次的思路：")
    await say(
        session,
        redis,
        book_id,
        "chief",
        (
            f"大纲里还没有{label}，我在最后加上了，写好了，在大纲上看。"
            if created
            else f"{label}写好了，已经换上去，在大纲上看。"
        )
        + (f"这次的思路：{note}" if note else ""),
    )
    return False


async def create_from_chat(session, redis, book, message, intent):
    """群聊里说「写一张封不觉的角色卡」：设定师照这一类现在的栏目写好，直接放进设定库，消息下面能撤销。"""
    from app.api.workspace import draft_entries

    book_id, message_id = book.id, message.id
    category = await resolve_category(session, book_id, intent.category)
    if category is None:
        said = f"「{intent.category}」" if intent.category.strip() else ""
        await update_message(
            session, redis, message, outcome={"kind": "not_found", "target_name": intent.category or "这一类"}
        )
        await say(
            session,
            redis,
            book_id,
            "chief",
            f"没认出要放进哪一类{said}。说清是角色、地点、势力还是别的哪一类，或者去那一类里点「编辑部帮写」。",
        )
        return False
    label = await category_label(session, book_id, category)
    ctx = await load_context(session, book)
    taken = {n for row in [*ctx.characters, *ctx.entries] for n in [row.name, *(row.aliases or [])] if n}
    asked = [name.strip() for name in intent.new_names if name.strip()]
    names = [name for name in asked if name not in taken]
    if asked and not names:
        have = "、".join(f"「{name}」" for name in asked)
        await update_message(session, redis, message, outcome={"kind": "not_found", "target_name": asked[0]})
        await say(
            session,
            redis,
            book_id,
            "chief",
            f"设定库里已经有{have}了。想补齐空着的就说「把{asked[0]}补齐」，想改哪一栏就直接说。",
        )
        return False
    count = len(names) or intent.count
    request = (intent.instruction.strip() or message.content) + (f"\n名字就用：{'、'.join(names)}" if names else "")
    facts, sections = await category_layout(session, book, category)
    what = "、".join(f"「{name}」" for name in names) if names else f" {count} 条{label}"
    await update_message(session, redis, message, outcome={"kind": "working", "text": f"设定师在写{what}"})
    body = DraftRequest(category=category, request=request[:1000], count=count, facts=facts, sections=sections)
    try:
        result = await asyncio.wait_for(draft_entries(body, book, session), timeout=ACTION_TIMEOUT)
    except TimeoutError as exc:
        raise HTTPException(504, "这次编辑部太慢了，两分半还没写完，没建。再试一次") from exc
    if not result["entries"]:
        raise HTTPException(502, "设定师这次没写出来，再试一次")
    await lock_book(session, book_id)
    rows = await save_drafted(session, book_id, category, result["entries"])
    items = [{"target_type": target_type_of(row), "target_id": str(row.id), "name": row.name} for row in rows]
    message = await session.get(MeetingMessage, message_id)
    outcome = {
        "kind": "created",
        "target_type": items[0]["target_type"],
        "target_id": items[0]["target_id"],
        "target_label": f"{label} · {'、'.join(item['name'] for item in items)}",
        "items": items,
    }
    await update_message(session, redis, message, outcome=outcome)
    note = (result.get("note") or "").strip()
    made = "、".join(f"「{item['name']}」" for item in items)
    await say(
        session,
        redis,
        book_id,
        "chief",
        f"写好了{made}，放进了{label}，在卡上看；不满意可以撤销。" + (f"这次的思路：{note}" if note else ""),
    )
    return False


async def revert_id(session, target_type, target_id):
    versions = list(
        await session.scalars(
            select(SettingVersion)
            .where(SettingVersion.target_type == target_type, SettingVersion.target_id == target_id)
            .order_by(SettingVersion.version.desc())
            .limit(2)
        )
    )
    return str(versions[1].id)


SPLIT_NOTE = "\n（这是作者上一句话里拆出来的一件事，前面那几件已经在做了，只按这一件判断）"
OUTLINE_WORDS = re.compile(r"结局|结尾|开局|开头|第\s*[0-9一二两三四五六七八九十]+\s*[篇卷章]")


def failure_reason(exc) -> str:
    return "判断超时" if isinstance(exc, TimeoutError) else str(getattr(exc, "detail", exc))


async def apply_steps(session, redis, message, first, more, viewing):
    """一句话里要做好几件事：一件一件做，后一件做之前再判断一次（前一件做完，设定和大纲可能变了）。
    每件的结果都记在这条消息的 payload.steps 里；后面的没做成，不影响前面做好的。"""
    mid, book_id = message.id, message.book_id
    steps, needs_reply = [], False
    for said in [None, *more]:
        try:
            if said is None:
                intent = first
            else:
                intent = await classify(session, book_id, said + SPLIT_NOTE, viewing)
                # 拆出来的这一句里说清了写大纲上哪一段（结局、第几篇），就照这一句找，不再听模型另认
                if intent.kind == "写大纲" and OUTLINE_WORDS.search(said):
                    intent.outline_target = said
                # 拆出来的这一件，作者的话就是改写后的那一句
                intent.instruction = intent.instruction or said
                intent.requirement = intent.requirement or said
            intent.more = []
            message = await session.get(MeetingMessage, mid)
            needs_reply |= await apply_intent(session, redis, message, intent)
            message = await session.get(MeetingMessage, mid)
            await session.refresh(message)
            steps.append(dict((message.payload or {}).get("outcome") or {}))
        except Exception as exc:
            await session.rollback()
            steps.append({"kind": "failed", "reason": failure_reason(exc)})
        message = await session.get(MeetingMessage, mid)
        if message:
            await update_message(session, redis, message, steps=steps)
    return needs_reply


async def route_background(book_id, redis, known_id=None, known_intent=None):
    needs_reply = False
    async with conversation_lock(redis, book_id, "routing"), get_sessionmaker()() as session:
        while True:
            message = await session.scalar(
                select(MeetingMessage)
                .where(
                    MeetingMessage.book_id == book_id,
                    MeetingMessage.payload["outcome"]["kind"].astext == "pending",
                    MeetingMessage.payload["thread"].astext.is_(None),
                )
                .order_by(MeetingMessage.id)
                .limit(1)
            )
            if message is None:
                break
            mid, text, viewing = message.id, message.content, (message.payload or {}).get("viewing")
            try:
                intent = known_intent if mid == known_id else await classify(session, book_id, text, viewing)
                more = [step.strip() for step in intent.more or [] if step.strip()][:3]
                if more:
                    needs_reply |= await apply_steps(session, redis, message, intent, more, viewing)
                else:
                    needs_reply |= await apply_intent(session, redis, message, intent)
            except Exception as exc:
                await session.rollback()
                message = await session.get(MeetingMessage, mid)
                reason = failure_reason(exc)
                if message:
                    await update_message(session, redis, message, outcome={"kind": "failed", "reason": reason})
    if needs_reply:
        await reply_background(book_id, "group", redis)


async def clean_pending(redis):
    async with get_sessionmaker()() as session:
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(
                    MeetingMessage.created_at < datetime.now(UTC) - timedelta(minutes=2),
                    MeetingMessage.payload["outcome"]["kind"].astext.in_(["pending", "working"]),
                )
            )
        )
        for message in messages:
            await update_message(session, redis, message, outcome={"kind": "failed", "reason": "判断中断"})
