"""任务控制（拍板、继续、停止）与会议室（历史消息 + SSE 实时推送）。"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import SessionDep, ensure_book_not_teardown, get_book, get_redis
from app.db import get_sessionmaker
from app.graphs.deps import cancel_key
from app.models import Book, Job, LlmCall, MeetingMessage
from app.schemas import (
    Answers,
    Decision,
    JobOut,
    MeetingMessageOut,
    NoteIn,
    PieceDecision,
    PitchDecision,
    SegmentDecision,
    UsageOut,
)
from app.services import jobs, setup_store
from app.services.library import lock_book
from app.services.meeting import job_dict, message_dict, post_message, publish, stream_key
from app.services.requirements import add_requirement
from app.services.usage import sum_known, token_sum

router = APIRouter(tags=["jobs"])

APPROVE_TEXT = {
    "setup_review": "批准，就按这个方案来。",
    "volume_review": "批准这一卷的卷纲，开写。",
    "chapters_review": "这个单元的章纲看过了，开写。",
    "trial_read": "前几章看过了，继续写。",
    "chapter_stuck": "这一章就按现在的版本定稿。",
}
PIECE_NAMES = {"concept": "定调", "settings": "设定库", "outline": "大纲"}


async def _job(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job


async def _locked_job(session, job_id):
    book_id = await session.scalar(select(Job.book_id).where(Job.id == job_id))
    if book_id is None:
        raise HTTPException(404, "任务不存在")
    await ensure_book_not_teardown(session, book_id, "让编辑部改书")
    await lock_book(session, book_id)
    return await session.scalar(
        select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True)
    )


async def _reject_legacy_setup(job_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    # 在请求体校验之前拦住旧客户端的 nodes/cast/fill 等块名，统一给出可操作的重开提示。
    job = await _job(session, job_id)
    await ensure_book_not_teardown(session, job.book_id, "让编辑部改书")
    if jobs.is_legacy_setup(job):
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
    job_id: uuid.UUID,
    body: Decision,
    background_tasks: BackgroundTasks,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    job = await _locked_job(session, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    kind = jobs.pending_kind(job)
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
    if kind not in APPROVE_TEXT:
        raise HTTPException(409, "当前没有等待你拍板的内容")
    feedback = body.feedback.strip()
    if body.action == "revise" and not feedback:
        raise HTTPException(422, "请写下修改意见")
    if body.action == "revise" and kind in {"volume_review", "chapters_review"}:
        return await feedback_to_job(session, redis, job, feedback, background_tasks=background_tasks)
    content = APPROVE_TEXT[kind] if body.action == "approve" else feedback
    return await _queue_setup_response(
        session, redis, job, content, {"action": body.action, "feedback": feedback}, background_tasks=background_tasks
    )


async def _setup_gate(session: AsyncSession, job_id: uuid.UUID, kind: str) -> Job:
    # 锁住等待状态，重复点击或两个窗口同时提交只能接受一次。
    job = await _locked_job(session, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
    if job.kind != "book_setup" or jobs.pending_kind(job) != kind:
        raise HTTPException(
            422 if kind == "setup_prefill" else 409,
            "当前没有等待你选择故事方向" if kind == "setup_pitches" else "当前没有等待你确认的开书步骤",
        )
    return job


async def _queue_setup_response(
    session: AsyncSession, redis: Redis, job: Job, content: str, resume: dict, *, background_tasks=None
) -> JobOut:
    from app.services import feedback_memory

    # 判断资料和 queued/作者消息一起提交；改稿不等，确认/试读由 worker 限时等判断落库。
    info = await feedback_memory.context(session, job, resume) if background_tasks is not None else None
    feedback = resume.get("feedback")
    author_feedback = (
        {"author_feedback": feedback}
        if isinstance(feedback, str) and feedback.strip() and feedback not in content
        else {}
    )
    job.status = "queued"
    message = await post_message(
        session,
        redis,
        book_id=job.book_id,
        job_id=job.id,
        speaker="author",
        kind="decision",
        content=content,
        payload={"requirement_saved": True, **({"feedback_memory": info} if info else {}), **author_feedback},
    )
    await session.refresh(job)
    await publish(redis, job.book_id, "job", job_dict(job))
    queued_resume = {**resume, "requirement_saved": True}
    if info and info["what_happens"] in (feedback_memory.CONFIRM, feedback_memory.TRIAL):
        queued_resume["feedback_memory_id"] = message["id"]
    jobs.enqueue(job.id, queued_resume)
    if info:
        background_tasks.add_task(feedback_memory.judge, message["id"], redis)
    return JobOut.model_validate(job)


FEEDBACK_LABELS = {
    "setup_pitches": "重出三个故事方向",
    "outline": "改大纲",
    "segment_review": "重出这一篇",
    "volume_review": "改卷纲",
    "chapters_review": "重出章纲",
}


async def feedback_to_job(session, redis, job, feedback, *, remember=True, background_tasks=None):
    kind = jobs.pending_kind(job)
    if jobs.is_legacy_setup(job):
        raise HTTPException(409, jobs.LEGACY_SETUP_MESSAGE)
    key = "outline" if kind == "setup_piece" and (job.pending or {}).get("piece") == "outline" else kind
    if key not in FEEDBACK_LABELS:
        raise HTTPException(409, "这一步不能接修改意见")
    if not feedback.strip():
        raise HTTPException(422, "请写下修改意见")
    resume = {"action": "redo" if kind == "setup_pitches" else "revise", "feedback": feedback}
    if key == "outline":
        resume["piece"] = "outline"
    return await _queue_setup_response(
        session, redis, job, feedback, resume, background_tasks=background_tasks if remember else None
    )


@router.post("/jobs/{job_id}/directions")
async def retired_directions(job_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    job = await _job(session, job_id)
    await ensure_book_not_teardown(session, job.book_id, "让编辑部改书")
    raise HTTPException(409, "这个任务用的是旧流程，请按新流程重开")


@router.post("/jobs/{job_id}/pitches", response_model=JobOut, dependencies=[Depends(_reject_legacy_setup)])
async def choose_pitch(
    job_id: uuid.UUID,
    body: PitchDecision,
    background_tasks: BackgroundTasks,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    if body.action == "start":
        job = await _setup_gate(session, job_id, "setup_prefill")
        return await _queue_setup_response(
            session,
            redis,
            job,
            "出三个故事方向",
            {"action": "start", "feedback": body.feedback.strip()},
            background_tasks=background_tasks,
        )
    job = await _setup_gate(session, job_id, "setup_pitches")
    if body.action == "redo":
        return await feedback_to_job(session, redis, job, body.feedback.strip(), background_tasks=background_tasks)
    feedback = body.feedback.strip()
    if body.action == "fill":
        book = await session.get(Book, job.book_id)
        if not (book.concept or {}).get("story", "").strip():
            raise HTTPException(422, "还没有定调。先挑一个故事方向，或者在群聊里聊定了让我照方案办。")
        content = "不挑方向了，用现在的定调和设定补齐开书稿。"
        await add_requirement(session, job.book_id, "开书不挑故事方向，用已经写好的定调和设定补齐。", "answer")
    elif body.action == "pick":
        pitches = (job.pending or {}).get("pitches") or []
        if body.index is None or body.index > len(pitches):
            raise HTTPException(422, "请选择一个故事方向")
        chosen = pitches[body.index - 1]
        content = f"选用第 {body.index} 个故事方向「{chosen.get('name', '')}」。"
        await add_requirement(session, job.book_id, f"开书的故事方向：选用「{chosen.get('name', '')}」", "answer")
    else:
        if not feedback:
            raise HTTPException(422, "请写下重新出故事方向的要求")
        content = feedback
    if body.length is not None:
        await add_requirement(session, job.book_id, f"这本书打算写 {body.length} 万字。", "answer")
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(422, "书名不能为空")
        await add_requirement(session, job.book_id, f"书名用《{body.title.strip()}》", "answer")
    resume = {**body.model_dump(), "feedback": feedback}
    return await _queue_setup_response(session, redis, job, content, resume, background_tasks=background_tasks)


@router.post("/jobs/{job_id}/segment", response_model=JobOut)
async def decide_segment(
    job_id: uuid.UUID,
    body: SegmentDecision,
    background_tasks: BackgroundTasks,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    job = await _locked_job(session, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if jobs.pending_kind(job) != "segment_review":
        raise HTTPException(409, "当前没有等待你确认的下一篇")
    pending = job.pending or {}
    if pending.get("flow") == 2:
        if body.action != "redo":
            raise HTTPException(422, "这一篇要先按新写法重出")
        return await _queue_setup_response(session, redis, job, "按新写法重出这一篇", {"action": "redo"})
    if body.action == "redo":
        raise HTTPException(422, "只有旧写法的篇需要重出")
    feedback = (body.feedback or "").strip()
    if body.action == "revise" and not (feedback or body.flips):
        raise HTTPException(422, "请写下修改意见或选择要改的决定")
    if body.action == "revise" and not body.flips:
        return await feedback_to_job(session, redis, job, feedback, background_tasks=background_tasks)
    pending = job.pending or {}
    number = pending.get("number", 2)
    if body.action == "confirm":
        volumes = (pending.get("split") or {}).get("volumes") or []
        first = volumes[0].get("index", 1) if volumes else 1
        content = f"确认第 {number} 篇，开拆第 {first} 卷。" + ("终点锁住。" if body.pin_end else "")
    elif body.action == "delegate":
        content = f"第 {number} 篇交给编辑部定。"
    else:
        content = feedback or "\n".join(f"「{flip.topic}」改成：{flip.choice}" for flip in body.flips)
    return await _queue_setup_response(
        session,
        redis,
        job,
        content,
        {**body.model_dump(mode="json"), "feedback": feedback},
        background_tasks=background_tasks,
    )


@router.post("/jobs/{job_id}/piece", response_model=JobOut, dependencies=[Depends(_reject_legacy_setup)])
async def decide_piece(
    job_id: uuid.UUID,
    body: PieceDecision,
    background_tasks: BackgroundTasks,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> JobOut:
    job = await _setup_gate(session, job_id, "setup_piece")
    current = (job.pending or {}).get("piece")
    if (
        current not in PIECE_NAMES
        or body.piece is not None
        and body.piece != current
        and not (current == "settings" and body.piece == "concept")
    ):
        raise HTTPException(409, "这一步已经变了，刷新一下再试")
    feedback = body.feedback.strip()
    if body.action == "revise" and not (feedback or body.flips):
        raise HTTPException(422, "请写下修改意见或选择要改的决定")
    if current == "outline" and body.action == "revise" and not body.flips:
        return await feedback_to_job(session, redis, job, feedback, background_tasks=background_tasks)
    label = PIECE_NAMES[current]
    changes = "\n".join(f"「{flip.topic}」改成：{flip.choice}" for flip in body.flips)
    content = (
        f"确认「{label}」。"
        if body.action == "confirm"
        else f"「{label}」交给编辑部定。"
        if body.action == "delegate"
        else "\n".join(value for value in (feedback, changes) if value)
    )
    resume = {
        **body.model_dump(mode="json"),
        "piece": current,
        "feedback": feedback,
        "decision_piece": body.piece or current,
    }
    return await _queue_setup_response(session, redis, job, content, resume, background_tasks=background_tasks)


@router.post("/jobs/{job_id}/answers", response_model=JobOut)
async def answer(
    job_id: uuid.UUID, body: Answers, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    """回答主编动笔前的提问。没回答的问题交给编辑部决定。"""
    job = await _job(session, job_id)
    await ensure_book_not_teardown(session, job.book_id, "让编辑部改书")
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
    body: NoteIn,
    background_tasks: BackgroundTasks,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
) -> MeetingMessageOut:
    from app.services.group_notes import receive_note

    return await receive_note(body, background_tasks, book, session, redis)


@router.post("/jobs/{job_id}/restart-setup", response_model=JobOut)
async def restart_setup(
    job_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
) -> JobOut:
    job = await _locked_job(session, job_id)
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
    text = "开书流程更新了：保留你的点子、作者要求、已选的方向和已确认的定调，其余按新的三步重做。"
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
    job = await _locked_job(session, job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job.kind == "outline_expand":
        raise HTTPException(409, "请回到大纲，在对应的卷或单元上重新点「展开这一个」")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, "只有失败或已停止的任务可以继续")
    # 与手动规划、开写和重写共用书锁，旧失败任务不能从恢复入口绕过同书单任务约束。
    await session.execute(select(Book.id).where(Book.id == job.book_id).with_for_update())
    active = await session.scalar(
        select(Job.id)
        .where(Job.book_id == job.book_id, Job.id != job.id, Job.status.in_(jobs.ACTIVE_STATUSES))
        .limit(1)
    )
    if active is not None:
        raise HTTPException(409, "编辑部手上还有没做完的事，先处理完再继续")
    await redis.delete(cancel_key(job.id))
    out = await _set_status(session, redis, job, "queued")
    jobs.enqueue(job.id, None)
    return out


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel(job_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)) -> JobOut:
    job = await _job(session, job_id)
    if job.kind == "teardown":
        from app.services import teardown_jobs

        if job.status not in jobs.BUSY_STATUSES:
            raise HTTPException(409, "任务已结束")
        book = await session.get(Book, job.book_id)
        return JobOut.model_validate(await teardown_jobs.stop(session, redis, book))
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
