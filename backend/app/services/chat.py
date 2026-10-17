"""与编辑作业队列分离的只读聊天回复；每本书、每个会话串行。"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from app.agents import schemas
from app.agents.editorial import persona
from app.db import get_sessionmaker
from app.llm.router import LLMRouter
from app.models import Book
from app.prompts import render
from app.services.chat_context import dialogue, dialogue_text, reply_values, thread_of
from app.services.meeting import SPEAKER_NAMES, post_message, publish

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


async def reply_background(book_id, thread, redis):
    # Waiting contenders collect any author messages that arrived during the previous reply.
    async with conversation_lock(redis, book_id, thread):
        sm = get_sessionmaker()
        async with sm() as session:
            state = await thread_of(session, book_id, thread)
            await session.commit()
            rows = await dialogue(session, book_id, thread, state.reset_after)
            answered = {i for m in rows for i in (m.payload or {}).get("reply_to", [])}
            unanswered = [m for m in rows if m.speaker == "author" and i_chat(m) and m.id not in answered]
            if not unanswered:
                return
            role = thread if thread != "group" else (unanswered[-1].payload or {}).get("chat_role", "chief")
            summary, until = state.summary, state.summarized_until
            old = [m for m in rows[:-20] if m.id > until]
            session.expunge_all()
            await session.rollback()
            await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": True})
            try:
                if len(old) >= 10:
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
                        state = await thread_of(session, book_id, thread)
                        state.summary, state.summarized_until = merged.summary, old[-1].id
                        await session.commit()
                        summary = merged.summary
                    except Exception:
                        await session.rollback()
                        log.exception("对话摘要失败，继续用旧摘要回答")
                book = await session.get(Book, book_id)
                if book is None:
                    return
                values = await reply_values(session, book, thread, role, rows, unanswered, summary)
                await session.rollback()
                result = await model(
                    book_id, role, schemas.ChatReply, "chat_reply", purpose=f"聊天·{SPEAKER_NAMES[role]}", **values
                )
                await post_message(
                    session,
                    redis,
                    book_id=book_id,
                    job_id=None,
                    speaker=role,
                    kind="speech",
                    content=result.reply,
                    payload={
                        "reply_to": [m.id for m in unanswered],
                        **({"thread": thread} if thread != "group" else {}),
                    },
                )
            except Exception as exc:
                await session.rollback()
                await post_message(
                    session,
                    redis,
                    book_id=book_id,
                    job_id=None,
                    speaker="system",
                    kind="error",
                    content=f"{SPEAKER_NAMES[role]}这会儿没答上来：{exc}。再问一次试试。",
                    payload={"thread": thread},
                )
            finally:
                await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": False})


def i_chat(message):
    return (message.payload or {}).get("outcome", {}).get("kind") == "chat"
