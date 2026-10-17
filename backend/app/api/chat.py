"""对话控制；不借用编辑作业的反馈接口。"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.agents.schemas import PlanItem
from app.api.deps import SessionDep, get_book, get_redis
from app.models import Book, MeetingMessage, SettingSuggestion
from app.services.chat import conversation_lock
from app.services.chat_context import THREADS, thread_of
from app.services.meeting import SPEAKER_NAMES, message_dict, post_message

router = APIRouter(tags=["chat"])


def valid_thread(thread):
    if thread not in THREADS:
        raise HTTPException(422, "对话不存在")


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
    from app.schemas import MeetingMessageOut, NoteIn

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
        # This is an explicit AI edit, not the fast /notes send path. Wait for
        # classification/edit before consuming the original suggestion; failed,
        # unmatched or newly deferred notes must remain actionable.
        work = BackgroundTasks()
        data = await add_note(NoteIn(content=text), work, book, session, redis)
        await session.rollback()
        await work()
        session.expire_all()
        message = await session.get(MeetingMessage, data.id)
        outcome = (message.payload or {}).get("outcome", {})
        if outcome.get("kind") not in {"edit", "requirement", "to_job", "plan_apply"}:
            raise HTTPException(409, outcome.get("reason") or "这一条还没有落实，建议已保留，请看看群聊里的处理结果")
        row = await session.get(SettingSuggestion, suggestion_id)
        row.status, row.resolved_at = "accepted", datetime.now(UTC)
        await session.commit()
        return MeetingMessageOut(**message_dict(message))


class PlanApplyIn(BaseModel):
    items: list[PlanItem] | None = Field(default=None, max_length=12)


@router.post("/plans/{message_id}/apply", status_code=202)
async def apply_plan(
    message_id: int,
    background_tasks: BackgroundTasks,
    body: PlanApplyIn | None = None,
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    from app.services.chat_plans import request_apply

    return await request_apply(session, redis, message_id, body.items if body else None, background_tasks)


@router.post("/plans/{message_id}/results/{index}/undo")
async def undo_plan_created(message_id: int, index: int, session=SessionDep, redis: Redis = Depends(get_redis)):
    from app.services.chat_plans import undo_created

    return await undo_created(session, redis, message_id, index)
