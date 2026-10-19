"""群聊分成一段段对话（第五步第四批）：新对话、以前的对话、从这里重来。

每段只带自己的记录和摘要；书本身（设定、大纲、写作要求）就是长期记忆，不分段。私聊不分段，照旧用 chat_threads。
消息的 payload.conv 记着属于哪一段：作者的话发在作者正在看的那一段；回答、方案卡跟着作者那句话；
编辑部干活的进度、系统的话记在最近聊的那一段（最近说过话、或者刚开的那段）。
「从这里重来」只退聊天：那句话和后面的聊天标成 dropped，不再显示、不再带给编辑部；书不跟着退。
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import func, literal_column, select

from app.models import ChatConversation, MeetingMessage
from app.services.meeting import message_dict, publish

TITLE_LIMIT = 20
LIVE = ("thinking", "streaming")
# 作者那句话还在判断、还在改：改完才能从这里重来
BUSY = ("pending", "working", "plan_pending")


def title_of(text: str) -> str:
    text = " ".join((text or "").split())
    return text[:TITLE_LIMIT] + ("…" if len(text) > TITLE_LIMIT else "")


def dropped(message) -> bool:
    return bool((getattr(message, "payload", None) or {}).get("dropped"))


def chat_part(message) -> bool:
    """算这段聊天里的一句：作者的话、回答、方案卡；编辑部干活的进度、系统的话不算（从这里重来也不收起它们）"""
    payload = message.payload or {}
    return (
        (
            message.speaker == "author"
            and (message.kind == "note" or (message.kind == "decision" and not message.job_id))
        )
        or "reply_to" in payload
        or message.kind == "plan"
    )


async def current(session, book_id) -> ChatConversation:
    """最近聊的那一段；一段都没有就开一段"""
    row = await session.scalar(
        select(ChatConversation)
        .where(ChatConversation.book_id == book_id)
        .order_by(ChatConversation.last_at.desc(), ChatConversation.created_at.desc())
        .limit(1)
    )
    if row is None:
        row = ChatConversation(book_id=book_id)
        session.add(row)
        await session.flush()
    return row


async def find(session, book_id, conv_id) -> ChatConversation | None:
    try:
        key = uuid.UUID(str(conv_id))
    except (TypeError, ValueError):
        return None
    row = await session.get(ChatConversation, key)
    return row if row is not None and row.book_id == book_id else None


async def resolve(session, book_id, conv_id=None) -> ChatConversation:
    """给了哪一段就是哪一段（找不到 422）；没给就是最近聊的那一段"""
    if conv_id is None:
        return await current(session, book_id)
    row = await find(session, book_id, conv_id)
    if row is None:
        raise HTTPException(422, "这段对话不存在")
    return row


async def of_message(session, message) -> ChatConversation:
    """这句话属于哪一段；早先没记的算最近聊的那一段"""
    conv = (message.payload or {}).get("conv")
    return (await find(session, message.book_id, conv) if conv else None) or await current(session, message.book_id)


async def stamp(session, book_id, payload):
    """发消息时记上属于哪一段（私聊、已经记了的不动）"""
    payload = dict(payload) if isinstance(payload, dict) else payload
    if payload and (payload.get("thread") or payload.get("conv")):
        return payload
    conv = None
    note_id = ((payload or {}).get("reply_to") or [None])[0] or (payload or {}).get("from_note")
    if note_id:
        note = await session.get(MeetingMessage, note_id)
        conv = ((note.payload or {}).get("conv") if note else None) or None
    if conv is None:
        conv = str((await current(session, book_id)).id)
    return {**(payload or {}), "conv": conv}


async def spoke(session, conv: ChatConversation, text: str) -> None:
    """作者在这一段说了一句：这一段成了最近聊的；还没名字的按这句起名"""
    conv.last_at = func.clock_timestamp()
    if not conv.title:
        conv.title = title_of(text)


async def notes_in(session, book_id, conv_id) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(MeetingMessage)
        .where(
            MeetingMessage.book_id == book_id,
            MeetingMessage.speaker == "author",
            MeetingMessage.kind == "note",
            MeetingMessage.payload["conv"].astext == str(conv_id),
            MeetingMessage.payload["dropped"].astext.is_(None),
        )
    )


async def start(session, book_id) -> ChatConversation:
    """新对话：最近那一段还没说过话就接着用它，不开一堆空的"""
    row = await current(session, book_id)
    if await notes_in(session, book_id, row.id):
        row = ChatConversation(book_id=book_id)
        session.add(row)
        await session.flush()
    else:
        row.last_at = func.clock_timestamp()
    await session.commit()
    await session.refresh(row)
    return row


async def listing(session, book_id) -> list[dict]:
    """以前的对话：最近聊的在前；没说过话的不列（最近那一段除外，它就是「新对话」）"""
    rows = list(
        await session.scalars(
            select(ChatConversation)
            .where(ChatConversation.book_id == book_id)
            .order_by(ChatConversation.last_at.desc(), ChatConversation.created_at.desc())
        )
    )
    # 按段数作者说过几句（参数化的 payload->>'conv' 在 GROUP BY 里对不上，写成字面的）
    key = literal_column("meeting_messages.payload ->> 'conv'")
    counts = dict(
        (
            await session.execute(
                select(key, func.count())
                .where(
                    MeetingMessage.book_id == book_id,
                    MeetingMessage.speaker == "author",
                    MeetingMessage.kind == "note",
                    MeetingMessage.payload["dropped"].astext.is_(None),
                )
                .group_by(key)
            )
        ).all()
    )
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "created_at": row.created_at.isoformat(),
            "last_at": row.last_at.isoformat(),
            "notes": counts.get(str(row.id), 0),
            "current": i == 0,
        }
        for i, row in enumerate(rows)
        if i == 0 or counts.get(str(row.id))
    ]


async def rewind(session, redis, book_id, conv: ChatConversation, from_id: int) -> list[int]:
    """从这里重来：这句话和这一段里后面的聊天收起来（不删），不再带给编辑部。只退聊天，书不动。"""
    note = await session.get(MeetingMessage, from_id)
    if (
        note is None
        or note.book_id != book_id
        or note.speaker != "author"
        or note.kind != "note"
        or (note.payload or {}).get("conv") != str(conv.id)
        or dropped(note)
    ):
        raise HTTPException(404, "这句话不在这段对话里")
    rows = list(
        await session.scalars(
            select(MeetingMessage)
            .where(
                MeetingMessage.book_id == book_id,
                MeetingMessage.id >= from_id,
                MeetingMessage.payload["conv"].astext == str(conv.id),
            )
            .order_by(MeetingMessage.id)
            .with_for_update()
        )
    )
    rows = [m for m in rows if chat_part(m) and not dropped(m)]
    if any((m.payload or {}).get("state") in LIVE for m in rows):
        raise HTTPException(409, "还在回答，先停下再重来")
    if any(((m.payload or {}).get("outcome") or {}).get("kind") in BUSY for m in rows if m.speaker == "author"):
        raise HTTPException(409, "编辑部还在照这几句话办，办完再重来")
    for m in rows:
        payload = {**(m.payload or {}), "dropped": True}
        # 没照办的方案卡跟着作废：「按这个来」不会再找到它
        if m.kind == "plan" and payload.get("status") == "open":
            payload["status"] = "superseded"
        m.payload = payload
    if conv.summarized_until >= from_id:
        # 摘要里折进了收起来的话：作废，下次回答按剩下的重新折
        conv.summary, conv.summarized_until = "", 0
    await session.flush()
    if not await notes_in(session, book_id, conv.id):
        conv.title = ""
    await session.commit()
    for m in rows:
        await session.refresh(m)
        await publish(redis, book_id, "message_update", message_dict(m))
    return [m.id for m in rows]
