"""对话控制；不借用编辑作业的反馈接口。"""

import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.agents.schemas import ChatConclusion
from app.api.deps import SessionDep, get_book, get_redis
from app.models import Book, MeetingMessage, SettingSuggestion
from app.services.chat import conversation_lock, model
from app.services.chat_context import THREADS, dialogue, dialogue_text, thread_of
from app.services.library_context import load_context
from app.services.meeting import SPEAKER_NAMES, post_message

router = APIRouter(tags=["chat"])


def valid_thread(thread):
    if thread not in THREADS:
        raise HTTPException(422, "对话不存在")


class ConcludeIn(BaseModel):
    mode: Literal["requirement", "instruction"]


@router.post("/books/{book_id}/chat/{thread}/conclude", response_model=ChatConclusion)
async def conclude(thread: str, body: ConcludeIn, book: Book = Depends(get_book), session=SessionDep):
    valid_thread(thread)
    book_id = book.id
    state = await thread_of(session, book_id, thread)
    rows = await dialogue(session, book_id, thread, state.reset_after)
    ctx = await load_context(session, book)
    values = dict(
        who=SPEAKER_NAMES.get(thread, "编辑部"),
        concept=ctx.concept,
        library=ctx.library,
        summary=state.summary or "（没有）",
        recent=dialogue_text(rows[-20:]),
        mode_line="记成一条写作要求（以后规划、写作时编辑部照着做）"
        if body.mode == "requirement"
        else "交给编辑部去改",
        mode_rule="写成一句清楚的要求放进 text：说清做什么、不写理由，「这样」「那个」换成具体内容，60 字以内。作者说了只管下一章、这一卷、下一卷的，scope 照选；没说的选一直有效。"
        if body.mode == "requirement"
        else "写成作者在群聊里吩咐编辑部的一句话放进 text：要改哪一处（设定库里的哪一条、大纲里的哪一篇哪一卷哪个单元）、改成什么，80 字以内，用作者自己说话的口气。scope 不用管。",
    )
    await session.commit()
    try:
        result = await model(
            book_id, thread if thread != "group" else "chief", ChatConclusion, "chat_conclude", **values
        )
    except Exception as exc:
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    return result


@router.post("/books/{book_id}/chat/{thread}/reset")
async def reset(thread: str, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)):
    valid_thread(thread)
    book_id = book.id
    async with conversation_lock(redis, book_id, thread):
        state = await thread_of(session, book_id, thread)
        latest = await session.scalar(select(func.max(MeetingMessage.id)).where(MeetingMessage.book_id == book_id)) or 0
        state.reset_after = state.summarized_until = latest
        state.summary = ""
        who = SPEAKER_NAMES.get(thread, "编辑部")
        await post_message(
            session,
            redis,
            book_id=book_id,
            job_id=None,
            speaker="system",
            kind="decision",
            content=f"—— 换了个话题，前面的对话不再带给{who} ——",
            payload={"thread": thread},
        )
    return {"reset_after": latest}


class ReceiptIn(BaseModel):
    message_id: int | None = None
    content: str = Field(default="", max_length=5000)


@router.post("/books/{book_id}/chat/{thread}/receipt")
async def receipt(
    thread: str, body: ReceiptIn, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    valid_thread(thread)
    if thread == "group":
        raise HTTPException(422, "请选择私聊")
    m = await session.get(MeetingMessage, body.message_id) if body.message_id else None
    if m is None and body.message_id is None and body.content.strip():
        m = await session.scalar(
            select(MeetingMessage)
            .where(
                MeetingMessage.book_id == book.id,
                MeetingMessage.speaker == "author",
                MeetingMessage.content == body.content.strip(),
                MeetingMessage.payload["thread"].astext.is_(None),
            )
            .order_by(MeetingMessage.id.desc())
            .limit(1)
        )
    if m is None or m.book_id != book.id or m.speaker != "author" or (m.payload or {}).get("thread"):
        raise HTTPException(422, "群聊消息不存在")
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=None,
        speaker="system",
        kind="decision",
        content=f"已交给编辑部：「{m.content}」，去群聊看看。",
        payload={"thread": thread},
    )
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/run-chat")
async def run_chat_suggestion(
    suggestion_id: uuid.UUID, background_tasks: BackgroundTasks, session=SessionDep, redis: Redis = Depends(get_redis)
):
    from datetime import UTC, datetime

    from app.api.deps import ensure_idle
    from app.api.jobs import add_note
    from app.schemas import NoteIn

    async with redis.lock(f"zhibi:chat-suggestion:{suggestion_id}", timeout=300, blocking_timeout=1):
        row = await session.get(SettingSuggestion, suggestion_id)
        if row is None or row.kind != "chat":
            raise HTTPException(404, "群聊建议不存在")
        if row.status != "pending":
            raise HTTPException(409, "这条建议已经处理过")
        await ensure_idle(session, row.book_id)
        book = await session.get(Book, row.book_id)
        text = row.payload["content"]
        await session.commit()
        data = await add_note(NoteIn(content=text), background_tasks, book, session, redis)
        row = await session.get(SettingSuggestion, suggestion_id)
        row.status, row.resolved_at = "accepted", datetime.now(UTC)
        await session.commit()
        return data
