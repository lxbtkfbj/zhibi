import uuid

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Book
from app.services import jobs

SessionDep = Depends(get_session)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


async def get_book(book_id: uuid.UUID, session: AsyncSession = SessionDep) -> Book:
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404, "书不存在")
    return book


async def ensure_idle(session: AsyncSession, book_id: uuid.UUID) -> None:
    """编辑部工作时不允许手动改设定和大纲，避免和 AI 的修改互相覆盖。"""
    if await jobs.is_busy(session, book_id):
        raise HTTPException(409, "编辑部正在工作，请等这一轮结束再修改")
