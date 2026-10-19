"""对话控制；不借用编辑作业的反馈接口。"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.agents.schemas import PlanItem
from app.api.deps import SessionDep, get_book, get_redis
from app.models import Book, MeetingMessage, SettingSuggestion
from app.services import chat_convs
from app.services.chat import LIVE, again_background, conversation_lock, reply_state, stop_key
from app.services.chat_context import THREADS, thread_of
from app.services.meeting import SPEAKER_NAMES, message_dict, post_message, publish

router = APIRouter(tags=["chat"])


def valid_thread(thread):
    if thread not in THREADS:
        raise HTTPException(422, "对话不存在")


@router.post("/books/{book_id}/chat/{thread}/reset")
async def reset(thread: str, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)):
    valid_thread(thread)
    book_id = book.id
    async with conversation_lock(redis, book_id, thread):
        latest = await session.scalar(select(func.max(MeetingMessage.id)).where(MeetingMessage.book_id == book_id)) or 0
        if thread == "group":
            # 群聊换个话题（旧版书页）就是开一段新对话
            await chat_convs.start(session, book_id)
        else:
            state = await thread_of(session, book_id, thread)
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


@router.get("/books/{book_id}/chat/conversations")
async def conversations(book: Book = Depends(get_book), session=SessionDep):
    """群聊的一段段对话：最近聊的在前，按作者的第一句话起名"""
    rows = await chat_convs.listing(session, book.id)
    await session.commit()
    return rows


@router.post("/books/{book_id}/chat/conversations", status_code=201)
async def new_conversation(book: Book = Depends(get_book), session=SessionDep):
    """新对话：最近那一段还没说过话就接着用它"""
    row = await chat_convs.start(session, book.id)
    return {"id": str(row.id), "title": row.title, "created_at": row.created_at.isoformat()}


async def reply_of(session, book, message_id):
    m = await session.get(MeetingMessage, message_id)
    if m is None or m.book_id != book.id or m.kind != "speech" or not (m.payload or {}).get("reply_to"):
        raise HTTPException(404, "这条回答不存在")
    return m


@router.post("/books/{book_id}/chat/replies/{message_id}/stop")
async def stop_reply(
    message_id: int, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    """作者点「停」：回答那边看到旗子就停，写出来的字留着。已经写完的不动。"""
    m = await reply_of(session, book, message_id)
    if reply_state(m) in LIVE:
        await redis.set(stop_key(m.id), "1", ex=600)
    return {"ok": True}


@router.post("/books/{book_id}/chat/replies/{message_id}/again", status_code=202)
async def again_reply(
    message_id: int,
    background_tasks: BackgroundTasks,
    book: Book = Depends(get_book),
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    """重新回答、重试：只认这个对话里最新的一条回答；这一条清空了重写，不留旧的。"""
    m = await reply_of(session, book, message_id)
    if reply_state(m) in LIVE:
        raise HTTPException(409, "还在回答，先停下")
    thread = (m.payload or {}).get("thread") or "group"
    later = await session.scalars(
        select(MeetingMessage).where(MeetingMessage.book_id == book.id, MeetingMessage.id > m.id)
    )
    if any(
        ((x.payload or {}).get("thread") or "group") == thread
        and (x.speaker == "author" or "reply_to" in (x.payload or {}))
        for x in later
    ):
        raise HTTPException(409, "后面又聊了，只有最新的一条回答能重新回答")
    # 没答上来的点的是「重试」：自己动手的那一轮接着做没做完的；答完、停下的点的是「重新回答」：只重写那段话
    again = "retry" if reply_state(m) == "failed" else "again"
    payload = {k: v for k, v in (m.payload or {}).items() if k not in ("state", "error", "doing")}
    m.content, m.payload = "", {**payload, "state": "thinking", "again": again}
    await session.commit()
    data = message_dict(m)
    await redis.delete(stop_key(m.id))
    await publish(redis, book.id, "message_update", data)
    background_tasks.add_task(again_background, book.id, thread, m.id, redis)
    return data


class NoteStepIn(BaseModel):
    # 一句话拆成好几件事时，是第几件；没拆的不给
    step: int | None = None


@router.post("/books/{book_id}/notes/{message_id}/revert")
async def revert_note(
    message_id: int,
    body: NoteStepIn | None = None,
    book: Book = Depends(get_book),
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    """消息下面的「换回原来的」：这一处换回改之前的样子；后来又被动过就 409。"""
    from app.services.group_notes import revert_note as revert

    return await revert(session, redis, book.id, message_id, body.step if body else None)


@router.post("/books/{book_id}/notes/{message_id}/redo", status_code=202)
async def redo_note(
    message_id: int,
    background_tasks: BackgroundTasks,
    body: NoteStepIn | None = None,
    book: Book = Depends(get_book),
    session=SessionDep,
    redis: Redis = Depends(get_redis),
):
    """消息下面的「再改一版」：先换回，再照同一句话重改这一处。"""
    from app.services.group_notes import redo_note as redo

    return await redo(session, redis, book.id, message_id, body.step if body else None, background_tasks)


@router.get("/books/{book_id}/note-changes")
async def note_changes(book: Book = Depends(get_book), session=SessionDep):
    """聊天里每一处改动现在还能不能换回、再改：这一处后来又改过就不能了。"""
    from app.services.group_notes import note_changes as changes

    return await changes(session, book.id)


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
        # 编辑部自己动手的那一轮：结果在 steps 里，做成了一处就算
        done = {o.get("kind") for o in (message.payload or {}).get("steps") or [outcome]}
        if not done & {"edit", "fill", "created", "outline", "requirement", "to_job", "plan_apply", "plan_made"}:
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
