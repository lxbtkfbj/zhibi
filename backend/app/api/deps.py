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


def ensure_not_teardown(book: Book, action: str) -> None:
    """拆书保留原文和结构；只在具体写入入口调用，不影响手改设定和存档。"""
    if book.source == "teardown":
        raise HTTPException(409, f"拆的书里不能{action}：原文和大纲结构照原书来，编辑部只回答问题。")


async def ensure_book_not_teardown(session: AsyncSession, book_id: uuid.UUID, action: str) -> None:
    ensure_not_teardown(await get_book(book_id, session), action)


async def ensure_idle(session: AsyncSession, book_id: uuid.UUID) -> None:
    """编辑部工作时不允许手动改设定和大纲，避免和 AI 的修改互相覆盖。"""
    if await jobs.is_busy(session, book_id):
        raise HTTPException(409, "编辑部正在工作，请等这一轮结束再修改")
