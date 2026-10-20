"""拆书右栏的两个只读接口，不改变已有书籍接口的投影。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_book
from app.models import Book
from app.services import teardown_digest

router = APIRouter(tags=["teardown"])


@router.get("/books/{book_id}/teardown/digest")
async def digest(
    unit: uuid.UUID | None = None,
    volume: uuid.UUID | None = None,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
) -> dict:
    return await teardown_digest.digest(session, book, unit=unit, volume=volume)


@router.get("/books/{book_id}/teardown/appearances")
async def appearances(
    character: uuid.UUID,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
) -> dict:
    return await teardown_digest.appearances(session, book, character)
