"""作者点名提前展开；接口内执行，用同书运行任务防止并发覆盖。"""

import logging
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import editorial
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts
from app.agents.setup_puzzle import clean_reveals
from app.api.deps import SessionDep, ensure_idle, get_redis
from app.db import get_sessionmaker
from app.graphs.deps import GraphDeps
from app.graphs.write_book import prepare_unit_chapters
from app.llm.router import LLMRouter
from app.models import Book, Chapter, Job, MeetingMessage, PlotUnit, Volume
from app.schemas import UnitOut, VolumeOut
from app.services import book_saves, setup_store, writing_store
from app.services.library import lock_book
from app.services.meeting import Emitter, job_dict, message_dict, publish
from app.services.versions import record_version, snapshot_of
from app.services.writing_context import volume_blocks

router = APIRouter(tags=["outline-expand"])
logger = logging.getLogger(__name__)


async def reserve(session, model, row_id):
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    await lock_book(session, row.book_id)
    try:
        await ensure_idle(session, row.book_id)
    except HTTPException as exc:
        raise HTTPException(409, "编辑部正在工作，等这一步做完再展开") from exc
    if model is Volume:
        exists = await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == row.id).limit(1))
        written = await session.scalar(
            select(Chapter.id).where(Chapter.volume_id == row.id, Chapter.status != "planned").limit(1)
        )
        if written:
            raise HTTPException(409, "这一卷已经开写了，不能展开")
    else:
        exists = await session.scalar(select(Chapter.id).where(Chapter.unit_id == row.id).limit(1))
    if exists:
        raise HTTPException(409, "已经展开过了")
    if model is PlotUnit:
        units = list(
            await session.scalars(
                select(PlotUnit)
                .join(Volume, PlotUnit.volume_id == Volume.id)
                .where(PlotUnit.book_id == row.book_id)
                .order_by(Volume.index, PlotUnit.index)
            )
        )
        covered = set(await session.scalars(select(Chapter.unit_id).where(Chapter.book_id == row.book_id)))
        following = next((unit for unit in units if unit.id not in covered), None)
        if following is None or following.id != row.id:
            raise HTTPException(409, "先展开前面的单元")
    before = snapshot_of(row)
    job = Job(
        book_id=row.book_id,
        kind="outline_expand",
        status="running",
        thread_id=str(uuid.uuid4()),
        params={"target": "volume" if model is Volume else "unit", "target_id": str(row.id)},
    )
    session.add(job)
    await session.commit()
    return row, SimpleNamespace(id=job.id, book_id=job.book_id), before


def dependencies(redis, job):
    sm = get_sessionmaker()
    llm = LLMRouter(sm, book_id=job.book_id, job_id=job.id)
    return GraphDeps(sm, redis, llm, Emitter(sm, redis, job.book_id, job.id), job.book_id, job.id)


async def broadcast(redis, book_id, event, data):
    try:
        await publish(redis, book_id, event, data)
    except RedisError:
        logger.warning("大纲展开的实时通知未发送，已保存的内容仍可刷新查看", exc_info=True)


async def finish(session, redis, job, content):
    row = await session.get(Job, job.id)
    row.status = "succeeded"
    from app.services.chat_convs import stamp

    message = MeetingMessage(
        book_id=job.book_id,
        job_id=job.id,
        speaker="chief",
        kind="speech",
        content=content,
        payload=await stamp(session, job.book_id, None),
    )
    session.add(message)
    await session.commit()
    await session.refresh(row)
    await session.refresh(message)
    await broadcast(redis, job.book_id, "job", job_dict(row))
    await broadcast(redis, job.book_id, "message", message_dict(message))


async def mark(session, redis, job, status, error=""):
    await session.rollback()
    row = await session.get(Job, job.id)
    row.status, row.error = status, error
    await session.commit()
    await session.refresh(row)
    await broadcast(redis, job.book_id, "job", job_dict(row))


async def _expand_volume(volume_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    volume, job, before = await reserve(session, Volume, volume_id)
    d = dependencies(redis, job)
    try:
        await broadcast(redis, job.book_id, "job", job_dict(await session.get(Job, job.id)))
        book = await session.get(Book, volume.book_id)
        blocks = await volume_blocks(session, book, volume)
        await session.rollback()
        result = await editorial.plan_volume(d.llm, blocks, {}, "", purpose="大纲·提前拆卷")
        plan = result.model_dump()
        volume = await session.get(Volume, volume_id)
        units_plan = plan.get("units") or []
        if volume.chapter_count > 0:
            units_plan = fit_chapter_counts(units_plan[: volume.chapter_count], volume.chapter_count, minimum=1)
        units_plan = clean_reveals(units_plan, await setup_store.load_secrets(session, job.book_id))
        ledger = await setup_store.load_ledger(session, job.book_id)
        fresh = setup_store.assign_seqs(
            [
                *({**item, "kind": "伏笔"} for item in plan.get("new_foreshadowings") or []),
                *({"span": "中", **item, "kind": "期待"} for item in plan.get("new_expectations") or []),
            ],
            ledger,
        )
        units_plan, fresh = attach_new_foreshadowings(units_plan, fresh, volume.index)
        if not units_plan:
            raise ValueError("主编没有给出单元")
        await writing_store.save_volume_plan(
            session,
            job.book_id,
            volume,
            units_plan,
            fresh,
            replace_new=False,
            want=plan.get("want", ""),
            pressure=plan.get("pressure", ""),
        )
        volume.status = "approved"
        await record_version(session, volume.book_id, "volume", volume, "ai", "提前展开", before=before)
        units = list(
            await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == volume_id).order_by(PlotUnit.index))
        )
        for unit in units:
            await record_version(session, volume.book_id, "unit", unit, "ai", "提前展开")
        content = f"第 {volume.index} 卷提前拆好了：{len(units)} 个单元，新埋伏笔 {sum(row['kind'] == '伏笔' for row in fresh)} 条，新立期待 {sum(row['kind'] == '期待' for row in fresh)} 条。"
        await finish(session, redis, job, content)
        volume = await session.get(Volume, volume_id)
        await session.refresh(volume, attribute_names=["units", "updated_at"])
        return VolumeOut.model_validate(volume)
    except Exception as exc:
        await mark(session, redis, job, "failed", str(exc))
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    finally:
        await d.llm.aclose()


async def _expand_unit(unit_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    unit, job, before = await reserve(session, PlotUnit, unit_id)
    d = dependencies(redis, job)
    try:
        await broadcast(redis, job.book_id, "job", job_dict(await session.get(Job, job.id)))
        await session.rollback()
        planned = await prepare_unit_chapters({"unit_id": str(unit_id)}, SimpleNamespace(context=d), persist=False)
        unit = await session.get(PlotUnit, unit_id)
        unit.plan_issues = planned["issues"]
        chapters = await writing_store.create_chapters(session, job.book_id, unit, planned["plans"])
        await record_version(session, unit.book_id, "unit", unit, "ai", "提前展开", before=before)
        await finish(
            session, redis, job, f"「{unit.title}」的章纲提前出好了：第 {chapters[0].index}-{chapters[-1].index} 章。"
        )
        unit = await session.get(PlotUnit, unit_id)
        return UnitOut.model_validate(unit)
    except Exception as exc:
        await mark(session, redis, job, "failed", str(exc))
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    finally:
        await d.llm.aclose()


# 编辑部动书：做事前先存作者自己改了还没存的，做完存一档（设计说明 9.13「第二批：存档」）
@router.post("/volumes/{volume_id}/expand", response_model=VolumeOut)
async def expand_volume(volume_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    row = await session.get(Volume, volume_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return await book_saves.editorial(
        session, row.book_id, "chief", "主编提前拆好了：", lambda: _expand_volume(volume_id, session, redis)
    )


@router.post("/units/{unit_id}/expand", response_model=UnitOut)
async def expand_unit(unit_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    row = await session.get(PlotUnit, unit_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return await book_saves.editorial(
        session, row.book_id, "chief", "主编提前出了章纲：", lambda: _expand_unit(unit_id, session, redis)
    )
