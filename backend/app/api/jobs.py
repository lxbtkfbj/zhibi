"""任务控制（拍板、继续、停止）与会议室（历史消息 + SSE 实时推送）。"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import SessionDep, get_book, get_redis
from app.db import get_sessionmaker
from app.graphs.deps import cancel_key
from app.models import Book, Job, LlmCall, MeetingMessage, StoryNode
from app.schemas import Answers, Decision, DirectionDecision, JobOut, MeetingMessageOut, NoteIn, PieceDecision, UsageOut
from app.services import jobs, setup_store
from app.services.meeting import job_dict, message_dict, post_message, publish, stream_key
from app.services.requirements import add_requirement, note_source
from app.services.usage import sum_known, token_sum

router = APIRouter(tags=["jobs"])

APPROVE_TEXT = {
    "setup_review": "批准，就按这个方案来。",
    "volume_review": "批准这一卷的卷纲，开写。",
    "trial_read": "前几章看过了，继续写。",
    "chapter_stuck": "这一章就按现在的版本定稿。",
}
PIECE_ORDER = ("concept", "protagonist", "world", "segment", "first_volume")
PIECE_NAMES = {
    "concept": "定调",
    "protagonist": "主角",
    "world": "世界与人",
    "segment": "第一段",
    "first_volume": "第一卷",
}


async def _job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


async def _reject_legacy_setup(job_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    # 在请求体校验之前拦住旧客户端的 nodes/cast/fill 等块名，统一给出可操作的重开提示。
    if jobs.is_legacy_setup(await _job(session, job_id)):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)


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
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
    if kind not in APPROVE_TEXT:
        raise HTTPException(409, "当前没有等待你拍板的内容")
    feedback = body.feedback.strip()
    if body.action == "revise" and not feedback:
        raise HTTPException(422, "请写下修改意见")
    if feedback:
        source = (
            "trial"
            if kind == "trial_read"
            else f"volume:{(job.pending or {}).get('volume')}"
            if kind == "volume_review"
            else "note"
        )
        await add_requirement(session, job.book_id, feedback, source)
    content = APPROVE_TEXT[kind] if body.action == "approve" else feedback
    await post_message(
        session, redis, book_id=job.book_id, job_id=job.id, speaker="author", kind="decision", content=content
    )
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, {"action": body.action, "feedback": feedback, "requirement_saved": True})
    return out


async def _setup_gate(session: AsyncSession, job_id: uuid.UUID, kind: str) -> Job:
    # 锁住等待状态，重复点击或两个窗口同时提交只能接受一次。
    job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "任务不存在")
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
    if job.kind != "book_setup" or jobs.pending_kind(job) != kind:
        raise HTTPException(
            409, "当前没有等待你选择方向" if kind == "setup_directions" else "当前没有等待你确认的开书拼图"
        )
    return job


async def _queue_setup_response(session: AsyncSession, redis: Redis, job: Job, content: str, resume: dict) -> JobOut:
    # post_message 会提交；在同一事务里写要求、作者消息和 queued，不能先放开 waiting_author 的锁。
    job.status = "queued"
    await post_message(
        session,
        redis,
        book_id=job.book_id,
        job_id=job.id,
        speaker="author",
        kind="decision",
        content=content,
        payload={"requirement_saved": True},
    )
    await session.refresh(job)
    await publish(redis, job.book_id, "job", job_dict(job))
    jobs.enqueue(job.id, {**resume, "requirement_saved": True})
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/directions", response_model=JobOut)
async def choose_direction(
    job_id: uuid.UUID,
    body: DirectionDecision,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    job = await _setup_gate(session, job_id, "setup_directions")
    mix, length, feedback = body.mix.strip(), body.length.strip(), body.feedback.strip()
    if body.action == "choose":
        directions = (job.pending or {}).get("directions") or []
        if body.choice is None or body.choice >= len(directions):
            raise HTTPException(422, "请选择一个现有的开书方向")
        if not length:
            raise HTTPException(422, "请选择这本书打算写多长")
        chosen = directions[body.choice]
        if body.title is not None and body.title not in (chosen.get("titles") or []):
            raise HTTPException(422, "请选择这个方向里的书名候选")
        name = chosen.get("name", "")
        await add_requirement(session, job.book_id, f"这本书打算写多长？——{length}", "answer")
        direction = f"开书方向：选用「{name}」" + (f"；混搭：{mix}" if mix else "")
        await add_requirement(session, job.book_id, direction, "answer")
        if body.title is not None:
            await add_requirement(session, job.book_id, f"书名用《{body.title}》", "answer")
        if feedback:
            await add_requirement(session, job.book_id, feedback, "note")
        content = (
            f"选方向「{name}」"
            + (f"，书名用《{body.title}》" if body.title is not None else "")
            + "。"
            + (f"\n混搭：{mix}" if mix else "")
            + (f"\n{feedback}" if feedback else "")
        )
    else:
        if not feedback:
            raise HTTPException(422, "请写下重新出方向的要求")
        await add_requirement(session, job.book_id, feedback, "note")
        content = feedback
    resume = {**body.model_dump(), "mix": mix, "length": length, "feedback": feedback}
    return await _queue_setup_response(session, redis, job, content, resume)


@router.post("/jobs/{job_id}/piece", response_model=JobOut, dependencies=[Depends(_reject_legacy_setup)])
async def decide_piece(
    job_id: uuid.UUID,
    body: PieceDecision,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    job = await _setup_gate(session, job_id, "setup_piece")
    current = (job.pending or {}).get("piece")
    feedback = body.feedback.strip()
    reopening = body.action in ("reopen", "unlock")
    if reopening:
        book = await session.get(Book, job.book_id)
        pieces = (book.setup_progress or {}).get("pieces", {}) if book else {}
        if current not in PIECE_ORDER or PIECE_ORDER.index(body.piece) >= PIECE_ORDER.index(current):
            raise HTTPException(422, "只能重新打开当前块之前已经确认的拼图")
        if pieces.get(body.piece) != "confirmed":
            raise HTTPException(422, "这一块还没有确认，不能重新打开")
    elif body.piece != current:
        raise HTTPException(409, "这一块已经变了，刷新一下再试")
    if body.action == "revise" and not (feedback or body.node_id or body.flips):
        raise HTTPException(422, "请写下修改意见、指定节点或选择要改的决定")
    if body.action in ("candidates", "fill") and body.node_id is None:
        raise HTTPException(422, "请选择要处理的节点")
    if (body.node_id or body.action in ("candidates", "fill")) and (
        current != "segment" or body.piece != "segment" or body.action not in ("revise", "candidates", "fill")
    ):
        raise HTTPException(422, "节点操作只能在「第一段」等确认时使用")
    node = None
    if body.node_id:
        node = await session.get(StoryNode, body.node_id)
        if node is None or node.book_id != job.book_id:
            raise HTTPException(422, "这个节点不属于当前书")
        if body.action == "fill" and node.status == "pinned":
            raise HTTPException(409, "铁钉节点不能由编辑部改写，请先改回暂定")
    if body.action in ("revise", "reopen", "unlock") and feedback:
        await add_requirement(session, job.book_id, feedback, "note")
    for flip in body.flips:
        await add_requirement(session, job.book_id, f"「{flip.topic}」改成：{flip.choice}", "answer")
    label = PIECE_NAMES[body.piece]
    changes = "\n".join(f"「{flip.topic}」改成：{flip.choice}" for flip in body.flips)
    if body.action == "confirm":
        content = f"确认「{label}」，下一块。"
    elif body.action == "delegate":
        content = f"「{label}」交给编辑部定。"
    elif body.action == "revise":
        content = "\n".join(value for value in (feedback, changes) if value)
        if not content and node:
            content = f"请修改节点 {node.position}「{node.title}」。"
    elif body.action == "candidates":
        content = f"给节点 {node.position} 出 3 个候选。"
    elif body.action == "fill":
        content = f"节点 {node.position}：{feedback}" if feedback else f"补上节点 {node.position}。"
    else:
        content = f"重新打开「{label}」。" + (f"\n{feedback}" if feedback else "")
    resume = {**body.model_dump(mode="json"), "feedback": feedback}
    return await _queue_setup_response(session, redis, job, content, resume)


@router.post("/jobs/{job_id}/answers", response_model=JobOut)
async def answer(
    job_id: uuid.UUID, body: Answers, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    """回答主编动笔前的提问。没回答的问题交给编辑部决定。"""
    job = await _job(session, job_id)
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
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
    for line in brief:
        await add_requirement(session, job.book_id, line, "answer")
    content = "\n".join(f"· {line}" for line in brief) if brief else "这些都交给编辑部决定。"
    await post_message(
        session, redis, book_id=job.book_id, job_id=job.id, speaker="author", kind="decision", content=content
    )
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, {"action": "answer", "brief": brief, "requirement_saved": True})
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
    payload = {"requirement_saved": True, **({"thread": body.to} if body.to else {})}
    deferred = (
        job is not None
        and job.kind in ("book_setup", "write_book")
        and (job.status in jobs.BUSY_STATUSES or jobs.pending_kind(job) == "setup_questions")
    )
    # 不让失败任务以后恢复时再消费一遍已经立即记下的插话。
    job_id = job.id if deferred else None
    # Persist immediately, including deferred notes. Graph checkpoints never own the ledger.
    await add_requirement(session, book.id, content, note_source(payload))
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


@router.post("/jobs/{job_id}/restart-setup", response_model=JobOut)
async def restart_setup(
    job_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "任务不存在")
    if not jobs.is_legacy_setup(job):
        raise HTTPException(409, "这个任务不需要重开")
    if job.status in jobs.BUSY_STATUSES:
        raise HTTPException(409, "编辑部正在工作，先停止再重开")
    book = await session.scalar(select(Book).where(Book.id == job.book_id).with_for_update())
    if book is None:
        raise HTTPException(404, "书不存在")
    if book.status not in {"setting_up", "awaiting_approval"}:
        raise HTTPException(409, "这本书已经开完了，不需要重开")
    restarted = await session.scalar(
        select(Job.id).where(Job.book_id == book.id, Job.params["restart_from"].astext == str(job.id)).limit(1)
    )
    if restarted:
        raise HTTPException(409, "这个任务已经按新流程重开")
    keep_concept = (book.setup_progress or {}).get("pieces", {}).get("concept") == "confirmed" and bool(
        (book.concept or {}).get("title")
    )
    job.status, job.finished_at = "cancelled", datetime.now(UTC)
    await setup_store.reset_for_restart(session, book.id, keep_concept)
    new_job = jobs.new_setup_job(book, ask=False, mode=(job.params or {}).get("mode", "oneshot"))
    new_job.params = {**new_job.params, "restart_from": str(job.id), "keep_concept": keep_concept}
    session.add(new_job)
    await session.flush()
    # 在首次提交释放锁之前，同时写入取消、清空与新任务，避免重复重开。
    await post_message(
        session,
        redis,
        book_id=book.id,
        job_id=new_job.id,
        speaker="author",
        kind="decision",
        content="按新流程重开开书。",
    )
    await session.refresh(job)
    await publish(redis, book.id, "job", job_dict(job))
    text = "开书流程更新了：保留你的点子、作者要求、已选的方向和已确认的定调，其余按新的五步重做。"
    if not keep_concept:
        text = text.replace("和已确认的定调", "")
    await post_message(
        session, redis, book_id=book.id, job_id=new_job.id, speaker="system", kind="decision", content=text
    )
    await session.refresh(new_job)
    await publish(redis, book.id, "job", job_dict(new_job))
    jobs.enqueue(new_job.id)
    return JobOut.model_validate(new_job)


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
                token_sum(LlmCall.prompt_tokens),
                token_sum(LlmCall.completion_tokens),
            )
            .where(LlmCall.book_id == book.id)
            .group_by(LlmCall.role)
        )
    ).all()
    by_role = {role: {"calls": c, "prompt_tokens": p, "completion_tokens": o} for role, c, p, o in rows}
    return UsageOut(
        calls=sum(v["calls"] for v in by_role.values()),
        prompt_tokens=sum_known(v["prompt_tokens"] for v in by_role.values()),
        completion_tokens=sum_known(v["completion_tokens"] for v in by_role.values()),
        by_role=by_role,
    )
