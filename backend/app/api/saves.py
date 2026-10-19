"""整本书的存档：列表、存一档、看这一档和现在比改了什么、回到这一档。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.deps import SessionDep, get_book, get_redis
from app.models import Book, BookSave
from app.services import book_saves
from app.services.meeting import post_message, publish

router = APIRouter(tags=["saves"])


@router.get("/books/{book_id}/saves")
async def list_saves(before: int | None = None, limit: int = 60, book: Book = Depends(get_book), session=SessionDep):
    limit = max(1, min(limit, 200))
    query = select(BookSave).where(BookSave.book_id == book.id)
    if before:
        query = query.where(BookSave.id < before)
    rows = list(await session.scalars(query.order_by(BookSave.id.desc()).limit(limit + 1)))
    return {"items": [book_saves.save_dict(row) for row in rows[:limit]], "more": len(rows) > limit}


class SaveIn(BaseModel):
    # 作者起的名字；不起就按时间叫
    label: str = Field(default="", max_length=60)
    # 作者手改后停手 3 分钟、关页面时前端自动调：跟上一档一样就不存
    auto: bool = False


@router.post("/books/{book_id}/saves")
async def create_save(
    body: SaveIn | None = None, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    body = body or SaveIn()
    book_id = book.id
    if body.auto:
        save = await book_saves.checkpoint(session, book_id, "author")
    else:
        save = await manual_save(session, book_id, body.label)
    if save is not None:
        await publish(redis, book_id, "saves", {"id": save.id})
    return {"save": book_saves.save_dict(save) if save else None}


async def manual_save(session, book_id, label: str) -> BookSave:
    from datetime import datetime

    name = label.strip() or datetime.now().astimezone().strftime("%m-%d %H:%M 存的")
    return await book_saves.checkpoint(session, book_id, "author", name, kind="manual", force=True)


async def save_of(session, book_id, save_id) -> BookSave:
    save = await session.get(BookSave, save_id)
    if save is None or save.book_id != book_id:
        raise HTTPException(404, "这一档不存在")
    return save


@router.get("/books/{book_id}/saves/{save_id}")
async def show_save(save_id: int, book: Book = Depends(get_book), session=SessionDep):
    save = await save_of(session, book.id, save_id)
    return await book_saves.compare(session, book.id, save)


@router.get("/books/{book_id}/saves/{save_id}/text")
async def save_text(save_id: int, table: str, row: str, label: str, book: Book = Depends(get_book), session=SessionDep):
    save = await save_of(session, book.id, save_id)
    if table != "books" and table not in book_saves.MODELS:
        raise HTTPException(422, "没有这一类")
    return await book_saves.full_text(session, book.id, save, table, row, label)


@router.post("/books/{book_id}/saves/{save_id}/restore")
async def restore_save(
    save_id: int, book: Book = Depends(get_book), session=SessionDep, redis: Redis = Depends(get_redis)
):
    book_id = book.id
    target = await save_of(session, book_id, save_id)
    label = book_saves.restore_label(target)
    when = book_saves.save_label(target)
    landed, before = await book_saves.restore(session, book_id, save_id)
    back = before.title if before else f"回到「{label}」之前的样子"
    # 聊天里插一行：编辑部回答时也看得到书换回去了
    await post_message(
        session,
        redis,
        book_id=book_id,
        job_id=None,
        speaker="system",
        kind="decision",
        content=f"—— 你把书换回了存档「{label}」（{when}），这之后的改动都退了；要回来，存档里点「{back}」那一档 ——",
        payload={
            "restore": {
                "save_id": target.id,
                "title": label,
                "at": target.created_at.isoformat() if target.created_at else None,
                "before_id": before.id if before else None,
            }
        },
    )
    for event in ("book", "library", "saves"):
        await publish(redis, book_id, event, {"id": str(book_id)})
    return {
        "save": book_saves.save_dict(landed) if landed else None,
        "before": book_saves.save_dict(before) if before else None,
    }
