"""任务控制（拍板、继续、停止）与会议室（历史消息 + SSE 实时推送）。"""

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import SessionDep, get_book, get_redis
from app.db import get_sessionmaker
from app.graphs.deps import cancel_key
from app.models import Book, Job, LlmCall, MeetingMessage
from app.schemas import Answers, Decision, JobOut, MeetingMessageOut, NoteIn, UsageOut
from app.services import jobs
from app.services.meeting import job_dict, message_dict, post_message, publish, stream_key
from app.services.notes import note_requirement

router = APIRouter(tags=["jobs"])

APPROVE_TEXT = {
    "setup_review": "批准，就按这个方案来。",
    "volume_review": "批准这一卷的卷纲，开写。",
    "trial_read": "前几章看过了，继续写。",
    "chapter_stuck": "这一章就按现在的版本定稿。",
}


async def _job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


async def _set_status(session: AsyncSession, redis: Redis, job: Job, status: str) -> JobOut:
    job.status = status
    await session.commit()
    await session.refresh(job)
    await publish(redis, job.book_id, "job", job_dict(job))
    return JobOut.model_validate(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = SessionDep) -> JobOut:
    return JobOut.model_validate(await _job(session, job_id))


@router.post("/jobs/{job_id}/decision", response_model=JobOut)
async def decide(
    job_id: uuid.UUID, body: Decision, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    job = await _job(session, job_id)
    kind = jobs.pending_kind(job)
    if kind not in jobs.DECISION_KINDS:
        raise HTTPException(409, "当前没有等待你拍板的内容")
    feedback = body.feedback.strip()
    if body.action == "revise" and not feedback:
        raise HTTPException(422, "请写下修改意见")
    content = APPROVE_TEXT[kind] if body.action == "approve" else feedback
    await post_message(
        session, redis, book_id=job.book_id, job_id=job.id, speaker="author", kind="decision", content=content
    )
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, {"action": body.action, "feedback": feedback})
    return out


@router.post("/jobs/{job_id}/answers", response_model=JobOut)
async def answer(
    job_id: uuid.UUID, body: Answers, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    """回答主编动笔前的提问。没回答的问题交给编辑部决定。"""
    job = await _job(session, job_id)
    if jobs.pending_kind(job) != "setup_questions":
        raise HTTPException(409, "当前没有需要你回答的问题")
    questions = (job.pending or {}).get("questions") or []
    brief = [
        f"{questions[a.index]['question']}——{a.answer.strip()}"
        for a in body.answers
        if a.index < len(questions) and a.answer.strip()
    ]
    if body.extra.strip():
        brief.append(f"补充：{body.extra.strip()}")
    content = "\n".join(f"· {line}" for line in brief) if brief else "这些都交给编辑部决定。"
    await post_message(
        session, redis, book_id=job.book_id, job_id=job.id, speaker="author", kind="decision", content=content
    )
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, {"action": "answer", "brief": brief})
    return out


@router.post("/books/{book_id}/notes", response_model=MeetingMessageOut, status_code=201)
async def add_note(
    body: NoteIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> MeetingMessageOut:
    """工作中由流程消费插话；空闲或不读插话的任务中，直接记为下次开工的要求。"""
    job = await jobs.active_job(session, book.id)
    if job is not None and jobs.pending_kind(job) in jobs.DECISION_KINDS:
        raise HTTPException(409, "等你拍板时请直接提意见")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "请写下你的话")
    payload = {"thread": body.to} if body.to else None
    deferred = (
        job is not None
        and job.kind in ("book_setup", "write_book")
        and (job.status in jobs.BUSY_STATUSES or jobs.pending_kind(job) == "setup_questions")
    )
    # 不让失败任务以后恢复时再消费一遍已经立即记下的插话。
    job_id = job.id if deferred else None
    if not deferred:
        # get_book 可能在另一个请求提交前读过这本书；加锁并重新读取，避免同时插话互相覆盖要求。
        # 锁与下面的 note 消息一起提交，下一位作者请求再接着追加。
        await session.refresh(book, attribute_names=["requirements"], with_for_update=True)
        requirement = note_requirement(content, payload)
        book.requirements = list(dict.fromkeys([*(book.requirements or []), requirement]))
    data = await post_message(
        session, redis, book_id=book.id, job_id=job_id, speaker="author", kind="note", content=content, payload=payload
    )
    if not deferred:
        await post_message(
            session,
            redis,
            book_id=book.id,
            job_id=None,
            speaker=body.to or "chief",
            kind="speech",
            content="记下了，下次开工就照办。",
            payload=payload,
        )
    return MeetingMessageOut(**data)


@router.post("/jobs/{job_id}/resume", response_model=JobOut)
async def resume(job_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)) -> JobOut:
    job = await _job(session, job_id)
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, "只有失败或已停止的任务可以继续")
    await redis.delete(cancel_key(job.id))
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, None)
    return out


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel(job_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)) -> JobOut:
    job = await _job(session, job_id)
    if job.status == "running":
        # 正在执行：通知 worker 在下一个节点开始前停下
        await redis.set(cancel_key(job.id), "1", ex=24 * 3600)
        return JobOut.model_validate(job)
    if job.status in ("queued", "waiting_author"):
        return await _set_status(session, redis, job, "cancelled")
    raise HTTPException(409, "任务已结束")


@router.get("/books/{book_id}/meeting", response_model=list[MeetingMessageOut])
async def meeting_history(
    book: Book = Depends(get_book),
    after: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = SessionDep,
) -> list[MeetingMessageOut]:
    rows = (
        (
            await session.execute(
                select(MeetingMessage)
                .where(MeetingMessage.book_id == book.id, MeetingMessage.id > after)
                .order_by(MeetingMessage.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [MeetingMessageOut(**message_dict(m)) for m in rows]


@router.get("/books/{book_id}/events")
async def meeting_events(
    request: Request,
    book: Book = Depends(get_book),
    after: int = Query(0, ge=0),
    redis: Redis = Depends(get_redis),
) -> EventSourceResponse:
    """先补发 after 之后的历史消息，再实时转发 Redis Stream 中的新事件。"""
    last_event_id = request.headers.get("last-event-id", "")
    if last_event_id.isdigit():
        after = max(after, int(last_event_id))
    book_id = book.id

    async def stream() -> AsyncIterator[dict]:
        key = stream_key(book_id)
        # 先记下流的当前位置，再查数据库，避免两步之间产生的消息被漏掉
        latest = await redis.xrevrange(key, count=1)
        cursor = latest[0][0] if latest else "0-0"
        sent = after
        async with get_sessionmaker()() as session:
            rows = (
                (
                    await session.execute(
                        select(MeetingMessage)
                        .where(MeetingMessage.book_id == book_id, MeetingMessage.id > after)
                        .order_by(MeetingMessage.id)
                    )
                )
                .scalars()
                .all()
            )
        for row in rows:
            sent = row.id
            yield {"event": "message", "id": str(row.id), "data": json.dumps(message_dict(row), ensure_ascii=False)}
        while not await request.is_disconnected():
            result = await redis.xread({key: cursor}, block=10_000, count=100)
            for _, entries in result or []:
                for entry_id, fields in entries:
                    cursor = entry_id
                    event, data = fields["event"], fields["data"]
                    if event == "message":
                        message_id = json.loads(data)["id"]
                        if message_id <= sent:
                            continue
                        sent = message_id
                        yield {"event": event, "id": str(message_id), "data": data}
                    else:
                        yield {"event": event, "data": data}

    return EventSourceResponse(stream(), ping=15)


@router.get("/books/{book_id}/usage", response_model=UsageOut)
async def usage(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> UsageOut:
    rows = (
        await session.execute(
            select(
                LlmCall.role,
                func.count(),
                func.coalesce(func.sum(LlmCall.prompt_tokens), 0),
                func.coalesce(func.sum(LlmCall.completion_tokens), 0),
            )
            .where(LlmCall.book_id == book.id)
            .group_by(LlmCall.role)
        )
    ).all()
    by_role = {role: {"calls": c, "prompt_tokens": p, "completion_tokens": o} for role, c, p, o in rows}
    return UsageOut(
        calls=sum(v["calls"] for v in by_role.values()),
        prompt_tokens=sum(v["prompt_tokens"] for v in by_role.values()),
        completion_tokens=sum(v["completion_tokens"] for v in by_role.values()),
        by_role=by_role,
    )
