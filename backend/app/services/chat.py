"""与编辑作业队列分离的只读聊天回复；每本书、每个会话串行。"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress

from sqlalchemy import select

from app.agents import schemas
from app.agents.editorial import persona
from app.db import get_sessionmaker
from app.llm.router import LLMRouter
from app.models import Book, MeetingMessage
from app.prompts import render
from app.services.chat_context import dialogue, dialogue_text, reply_values, thread_of
from app.services.meeting import SPEAKER_NAMES, message_dict, post_message, publish

log = logging.getLogger(__name__)


def lock_key(book_id, thread):
    return f"zhibi:chat:{book_id}:{thread}"


async def model(book_id, role, schema, template, *, purpose=None, **values):
    llm = LLMRouter(get_sessionmaker(), book_id=book_id)
    try:
        return await llm.structured(
            role, schema, persona(role), render(template, **values), purpose=purpose or template
        )
    finally:
        await llm.aclose()


@asynccontextmanager
async def conversation_lock(redis, book_id, thread):
    lock = redis.lock(lock_key(book_id, thread), timeout=180, blocking_timeout=900)
    async with lock:
        owner = asyncio.current_task()

        async def renew():
            while True:
                await asyncio.sleep(60)
                try:
                    await lock.extend(180, replace_ttl=True)
                except Exception:
                    log.exception("聊天锁续租失败，停止当前回答，避免并发回答")
                    owner.cancel()
                    return

        renewal = asyncio.create_task(renew())
        try:
            yield
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError):
                await renewal


# 回答边写边推：先占一条空消息（state=thinking），写出字就推 chat_delta（带到目前为止的全文），写完存下来。
# 作者点「停」只是立个旗子，回答那边每 0.25 秒看一眼；写出来的字留着，state=stopped。
LIVE = ("thinking", "streaming")
PUSH_EVERY = 0.2
FIRST_WORD_TIMEOUT = 90
TOTAL_TIMEOUT = 300


def stop_key(message_id):
    return f"zhibi:chat:stop:{message_id}"


def reply_state(message):
    return (message.payload or {}).get("state")


async def stream_model(book_id, role, template, *, purpose, **values):
    llm = LLMRouter(get_sessionmaker(), book_id=book_id)
    try:
        async for chunk in llm.stream_text(role, persona(role), render(template, **values), purpose=purpose):
            yield chunk
    finally:
        await llm.aclose()


async def answered_ids(session, book_id, thread, reset_after):
    """哪些作者的话已经有回答了：在写的、停下的、没答上来的都算，不再自动答第二遍。"""
    payloads = await session.scalars(
        select(MeetingMessage.payload).where(
            MeetingMessage.book_id == book_id,
            MeetingMessage.id > reset_after,
            MeetingMessage.payload["reply_to"].is_not(None),
        )
    )
    return {i for p in payloads if ((p or {}).get("thread") or "group") == thread for i in p.get("reply_to", [])}


async def stream_reply(redis, book_id, role, reply_id, values):
    parts: list[str] = []
    pushed = 0.0

    async def consume():
        nonlocal pushed
        async for chunk in stream_model(book_id, role, "chat_reply", purpose=f"聊天·{SPEAKER_NAMES[role]}", **values):
            parts.append(chunk)
            now = time.monotonic()
            if now - pushed >= PUSH_EVERY:
                pushed = now
                await publish(redis, book_id, "chat_delta", {"id": reply_id, "text": "".join(parts)})

    task = asyncio.create_task(consume())
    started = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if done:
                task.result()
                return "".join(parts), "done"
            if await redis.exists(stop_key(reply_id)):
                return "".join(parts), "stopped"
            waited = time.monotonic() - started
            if not parts and waited > FIRST_WORD_TIMEOUT:
                raise TimeoutError(f"模型 {FIRST_WORD_TIMEOUT} 秒还没开口")
            if waited > TOTAL_TIMEOUT:
                raise TimeoutError(f"写了 {TOTAL_TIMEOUT // 60} 分钟还没写完")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def finish_reply(session, redis, reply_id, text, state, error=""):
    message = await session.get(MeetingMessage, reply_id)
    if message is None:
        return
    payload = {k: v for k, v in (message.payload or {}).items() if k not in ("state", "error")}
    if state != "done":
        payload["state"] = state
    if state == "failed":
        payload["error"] = error or "回答被打断了"
    message.content, message.payload = text, payload
    await session.commit()
    await publish(redis, message.book_id, "message_update", message_dict(message))
    await redis.delete(stop_key(reply_id))


async def merge_summary(session, book_id, thread, summary, old):
    """最近 20 条以前、还没折进摘要的有 10 条以上了：先折进摘要。失败了照旧用旧摘要。"""
    if len(old) < 10:
        return summary
    try:
        merged = await model(
            book_id,
            "lorekeeper",
            schemas.ChatSummary,
            "chat_summary",
            who=SPEAKER_NAMES.get(thread, "编辑部"),
            summary=summary or "（没有）",
            messages=dialogue_text(old, limited=False),
        )
        row = await thread_of(session, book_id, thread)
        row.summary, row.summarized_until = merged.summary, old[-1].id
        await session.commit()
        return merged.summary
    except Exception:
        await session.rollback()
        log.exception("对话摘要失败，继续用旧摘要回答")
        return summary


def tools_text(tools):
    """这一轮查到的、做了的：重新回答时交给模型照着说，不再给工具。"""
    return "\n\n".join(f"【{t.get('label', '')}】\n{t.get('text', '')}" for t in tools or []) or "（没有）"


async def answer(session, redis, book_id, thread, role, reply_id, rows, unanswered, summary, old, related=None):
    """写一条回答：要合摘要先合，再一边写一边推。出错、超时都落在这条消息上，给「重试」。
    related：自己查过、做过的那一轮重新回答时，资料换成那一轮查到的、做了的。"""
    await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": True})
    text, state, error = "", "failed", ""
    try:
        summary = await merge_summary(session, book_id, thread, summary, old)
        book = await session.get(Book, book_id)
        if book is None:
            return
        values = await reply_values(session, book, thread, role, rows, unanswered, summary)
        if related is not None:
            values["related"] = related
        await session.rollback()
        text, state = await stream_reply(redis, book_id, role, reply_id, values)
        text = text.strip()
        if state == "done" and not text:
            state, error = "failed", "模型什么也没说"
    except Exception as exc:
        await session.rollback()
        log.exception("聊天回答失败")
        error = str(exc) or type(exc).__name__
    finally:
        await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": False})
        await finish_reply(session, redis, reply_id, text, state, error)


async def reply_background(book_id, thread, redis):
    # Waiting contenders collect any author messages that arrived during the previous reply.
    async with conversation_lock(redis, book_id, thread):
        sm = get_sessionmaker()
        async with sm() as session:
            state = await thread_of(session, book_id, thread)
            await session.commit()
            rows = await dialogue(session, book_id, thread, state.reset_after)
            answered = await answered_ids(session, book_id, thread, state.reset_after)
            unanswered = [m for m in rows if m.speaker == "author" and i_chat(m) and m.id not in answered]
            if not unanswered:
                return
            role = thread if thread != "group" else (unanswered[-1].payload or {}).get("chat_role", "chief")
            summary, until = state.summary, state.summarized_until
            old = [m for m in rows[:-20] if m.id > until]
            reply = await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=None,
                speaker=role,
                kind="speech",
                content="",
                payload={
                    "reply_to": [m.id for m in unanswered],
                    "state": "thinking",
                    **({"thread": thread} if thread != "group" else {}),
                },
            )
            session.expunge_all()
            await session.rollback()
            await answer(session, redis, book_id, thread, role, reply["id"], rows, unanswered, summary, old)


async def again_background(book_id, thread, reply_id, redis):
    """重新回答、重试：同一条消息，照原来那几句话再答一遍。"""
    async with conversation_lock(redis, book_id, thread), get_sessionmaker()() as session:
        state = await thread_of(session, book_id, thread)
        await session.commit()
        reply = await session.get(MeetingMessage, reply_id)
        if reply is None or reply_state(reply) != "thinking":
            return
        asked = list(reply.payload.get("reply_to") or [])
        rows = [m for m in await dialogue(session, book_id, thread, state.reset_after) if m.id < reply_id]
        unanswered = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.id.in_(asked)).order_by(MeetingMessage.id)
            )
        )
        role, summary, until = reply.speaker, state.summary, state.summarized_until
        old = [m for m in rows[:-20] if m.id > until]
        payload = dict(reply.payload or {})
        session.expunge_all()
        await session.rollback()
        if not unanswered:
            await finish_reply(session, redis, reply_id, "", "failed", "原来那句话找不到了")
            return
        if payload.get("tools_mode"):
            if payload.get("again") == "retry":
                # 自己查、自己动手那一轮中途断了：重试接着做没做完的
                from app.services.chat_agent import answer_note

                await answer_note(redis, book_id, unanswered[0].id, reply_id=reply_id, retry=True)
                return
            # 重新回答：只重写那段话，不给工具，照这一轮查到的、做了的说；改动不动、也不重做
            related = tools_text(payload.get("tools"))
            await answer(session, redis, book_id, thread, role, reply_id, rows, unanswered, summary, old, related)
            return
        await answer(session, redis, book_id, thread, role, reply_id, rows, unanswered, summary, old)


async def clean_live_replies(redis):
    """启动时：上次没写完的回答（服务重启过）标成没答上来，能重试。"""
    async with get_sessionmaker()() as session:
        ids = list(
            await session.scalars(select(MeetingMessage.id).where(MeetingMessage.payload["state"].astext.in_(LIVE)))
        )
        for mid in ids:
            await finish_reply(session, redis, mid, "", "failed", "回答到一半断了（服务重启过）")


def i_chat(message):
    return (message.payload or {}).get("outcome", {}).get("kind") == "chat" and not (message.payload or {}).get(
        "outcome", {}
    ).get("handled")
