"""看稿意见独立判断：只记长期规矩，不阻塞或重做眼前改稿。"""

import asyncio
import logging
import uuid
from contextlib import suppress

from sqlalchemy import select

from app.agents import schemas
from app.db import get_sessionmaker
from app.models import Book, MeetingMessage, Memory, PlotUnit
from app.services.chat import model
from app.services.chat_memories import directory_rows, memory_directory, number, snapshot
from app.services.library import lock_book
from app.services.meeting import post_message
from app.services.memories import lock_memories, notify, remembered_outcome
from app.services.requirements import SCOPE_INPUTS, set_scope, suppress_legacy_text, unsuppress_legacy_text

log = logging.getLogger(__name__)

REVISE = "编辑部会照这段意见改这一处，这件事不用你管。"
CONFIRM = "作者点了确认，这一处不再改。只说这一处的，不记，回话里告诉作者：要改这一处，在聊天里跟编辑部说。"
TRIAL = "前 3 章已经写完，不会照这段意见重写，这段意见是说给后面的章听的。只说前 3 章里某一章的，不记，回话里告诉作者：要改那一章，去「正文」那一页让编辑部重写。"
WAIT_TIMEOUT_S = 120
WAIT_POLL_S = 0.25


async def wait_for_result(message_id, sm, emit, check_cancel, *, book_id, job_id):
    """确认/试读后先等本条判断落库；到时放行，不取消独立运行的判断。"""
    if not message_id:
        return
    deadline = asyncio.get_running_loop().time() + WAIT_TIMEOUT_S
    announced = False
    while True:
        await check_cancel()
        async with sm() as session:
            message = await session.get(MeetingMessage, message_id)
            if message is None or message.book_id != book_id or message.job_id != job_id:
                return
            info = (message.payload or {}).get("feedback_memory") or {}
            if info.get("what_happens") not in (CONFIRM, TRIAL) or info.get("state") not in ("pending", "running"):
                return
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        if not announced:
            await emit.status("chief", "主编正在看你写的意见…")
            announced = True
        await asyncio.sleep(min(WAIT_POLL_S, remaining))


async def context(session, job, resume):
    """在 pending 被下一步替换前，固定作者实际看过的页面名称及原话。"""
    feedback = (resume.get("feedback") or "").strip()
    if not feedback:
        return None
    pending = job.pending or {}
    kind = pending.get("kind")
    if kind == "trial_read":
        where = "试读前 3 章"
    elif kind == "volume_review":
        where = f"第 {pending.get('volume', 1)} 卷的卷纲"
    elif kind == "chapters_review":
        unit = None
        with suppress(ValueError):
            unit = await session.get(PlotUnit, uuid.UUID(str(pending.get("unit_id"))))
        where = f"单元「{unit.title if unit and unit.book_id == job.book_id else pending.get('unit_title', '')}」的章纲"
    elif kind == "segment_review":
        where = f"第 {pending.get('number', 2)} 篇"
    elif kind == "setup_piece":
        where = {"concept": "定调", "settings": "设定库", "outline": "大纲"}.get(
            resume.get("decision_piece") or pending.get("piece")
        )
        if where is None:
            return None
    elif kind in ("setup_prefill", "setup_pitches"):
        where = "三个故事方向"
    else:
        return None
    action = resume.get("action")
    what_happens = (
        TRIAL
        if kind == "trial_read"
        else CONFIRM
        if action in ("approve", "confirm", "delegate", "pick", "fill")
        else REVISE
    )
    return {"state": "pending", "where": where, "what_happens": what_happens, "feedback": feedback}


async def apply_items(session, book_id, message_id, items):
    await lock_book(session, book_id)
    await lock_memories(session)
    eligible = {
        row.id: row
        for row in await directory_rows(session, book_id)
        if row.book_id == book_id and row.kind == "writing"
    }
    from app.services import jobs

    working = await jobs.is_busy(session, book_id)
    outcomes = []
    for item in items:
        row = eligible.get(number(item.id))
        before = snapshot(row) if row else None
        if row is None:
            # 本轮没有指定可改的本书有效编号，就新记；不能复活已过期的同简述。
            row = Memory(
                book_id=book_id,
                kind="writing",
                summary=item.summary.strip(),
                detail=item.detail.strip() or item.summary.strip(),
                source="看稿时说的",
                message_id=message_id,
            )
            session.add(row)
            await set_scope(session, row, SCOPE_INPUTS[item.lasts])
            await unsuppress_legacy_text(session, book_id, row.detail)
            await session.flush()
        else:
            await suppress_legacy_text(session, book_id, row.detail)
            row.summary, row.detail = item.summary.strip(), item.detail.strip() or item.summary.strip()
            row.source, row.message_id = "看稿时说的", message_id
            row.version += 1
            await set_scope(session, row, SCOPE_INPUTS[item.lasts])
            await unsuppress_legacy_text(session, book_id, row.detail)
            await session.flush()
        outcome = remembered_outcome(row, working=working)
        outcome["kind"] = "memory"
        outcome["memory"].update(action="update" if before else "create", before=before)
        outcomes.append(outcome)
    return outcomes


async def judge(message_id, redis):
    """持久领取一次；模型阶段不占书锁，失败也不影响已排队的改稿。"""
    sm = get_sessionmaker()
    async with sm() as session:
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.id == message_id).with_for_update())
        info = (message.payload or {}).get("feedback_memory") if message else None
        if not info or info.get("state") != "pending":
            return
        book = await session.get(Book, message.book_id)
        if book is None or book.source == "teardown":
            return
        book_id, job_id = message.book_id, message.job_id
        info = {**info, "state": "running"}
        message.payload = {**message.payload, "feedback_memory": info}
        conv = (message.payload or {}).get("conv")
        await session.commit()
    error = None
    try:
        async with sm() as session:
            memory = await memory_directory(session, book_id)
        result = await model(
            book_id,
            "chief",
            schemas.FeedbackMemory,
            "feedback_memory",
            purpose="看稿意见要不要记",
            where=info["where"],
            what_happens=info["what_happens"],
            feedback=info["feedback"],
            memory=memory,
        )
        async with sm() as session:
            message = await session.get(MeetingMessage, message_id)
            if message is None:
                return
            outcomes = await apply_items(session, book_id, message_id, result.items)
            message.payload = {**message.payload, "feedback_memory": {**info, "state": "done"}}
            await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=job_id,
                speaker="chief",
                kind="speech",
                content=result.reply,
                payload={"feedback_to": message_id, "memories": outcomes, **({"conv": conv} if conv else {})},
            )
            if outcomes:
                await notify(session, redis)
    except Exception as exc:
        from app.services.chat_agent import failure

        error = failure(exc)
        log.exception("看稿意见记忆判断失败，改稿照常")
    if error is not None:
        async with sm() as session:
            message = await session.get(MeetingMessage, message_id)
            if message is None or (message.payload or {}).get("feedback_memory", {}).get("state") != "running":
                return
            message.payload = {**message.payload, "feedback_memory": {**info, "state": "failed"}}
            await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=job_id,
                speaker="chief",
                kind="speech",
                content=f"这段意见没来得及判断要不要记（{error}）。要以后都照做，在聊天里跟我说「记住……」。",
                payload={"feedback_to": message_id, **({"conv": conv} if conv else {})},
            )
