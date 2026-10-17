"""群聊先落消息，再按消息序号串行判断；聊天永不偷偷变成要求。"""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.schemas import LibraryIntent
from app.api.library_ai import RewriteIn, call_model, rewrite_target, say
from app.db import get_sessionmaker
from app.models import Book, Job, MeetingMessage, SettingSuggestion, SettingVersion
from app.schemas import MeetingMessageOut
from app.services import jobs
from app.services.chat import conversation_lock, reply_background
from app.services.chat_context import (
    ROLES,
    accepts_plan,
    dialogue,
    dialogue_text,
    obvious_question,
    thread_of,
    wants_plan,
)
from app.services.library import lock_book
from app.services.library_context import load_context
from app.services.meeting import message_dict, post_message, publish
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
    return job and job.status == "waiting_author" and (job.pending or {}).get("kind") != "setup_prefill"


async def update_message(session, redis, message, **payload):
    message.payload = {**(message.payload or {}), **payload}
    await session.commit()
    await session.refresh(message)
    data = message_dict(message)
    await publish(redis, message.book_id, "message_update", data)
    return data


async def classify(session, book_id, text):
    book = await session.get(Book, book_id)
    ctx = await load_context(session, book)
    state = await thread_of(session, book_id, "group")
    recent = dialogue_text((await dialogue(session, book_id, "group", state.reset_after))[-6:])
    library = ctx.library
    await session.commit()
    return await asyncio.wait_for(
        call_model(
            book_id,
            "router",
            LibraryIntent,
            "library_route",
            library=library,
            recent=recent,
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
            outcome={"kind": "chat", **({"shortcut": True} if not body.to else {})}, chat_role=body.to or role
        )
        task = "reply"
    else:
        job = await active_note_job(session, book_id)
        if waiting_feedback(job):
            try:
                intent = await classify(session, book_id, text)
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
        await update_message(session, redis, message, outcome={"kind": "chat"}, chat_role=ROLES[intent.who])
        return True
    working = job is not None and job.status in jobs.BUSY_STATUSES
    if intent.kind == "改设定" and working and job.kind != "book_setup":
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
            reply = f"没找到「{intent.target_name}」这一条。去设定库点那一处改，或者告诉我它在哪一类。"
        else:
            body = RewriteIn(
                target_type=target_type_of(target),
                target_id=target.id,
                path=ctx.route_path(target, intent.part, intent.quote),
                mode="options" if intent.mode == "给几个写法" else "instruction",
                instruction=intent.instruction or text,
            )
            outcome = {
                "kind": "edit",
                "target_type": body.target_type,
                "target_id": str(body.target_id),
                "target_label": ctx.target_label(target, body.path),
                "mode": body.mode,
            }
            result = await rewrite_target(session, redis, book, body, require_idle=True)
            message = await session.get(MeetingMessage, message_id)
            if body.mode == "options":
                outcome["candidate_id"] = str(result["candidate"].id)
            else:
                outcome["revert_version_id"] = await revert_id(session, body.target_type, body.target_id)
            reply = intent.reply or "改好了，去看看。"
    await update_message(session, redis, message, outcome=outcome)
    if reply:
        await say(session, redis, book_id, "chief", reply)
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
            mid, text = message.id, message.content
            try:
                intent = known_intent if mid == known_id else await classify(session, book_id, text)
                needs_reply |= await apply_intent(session, redis, message, intent)
            except Exception as exc:
                await session.rollback()
                message = await session.get(MeetingMessage, mid)
                reason = "判断超时" if isinstance(exc, TimeoutError) else str(getattr(exc, "detail", exc))
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
                    MeetingMessage.payload["outcome"]["kind"].astext == "pending",
                )
            )
        )
        for message in messages:
            await update_message(session, redis, message, outcome={"kind": "failed", "reason": "判断中断"})
