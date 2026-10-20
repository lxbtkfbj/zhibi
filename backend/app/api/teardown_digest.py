"""拆书右栏的两个只读接口，不改变已有书籍接口的投影。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_book
from app.models import Book
from app.services import teardown_digest

router = APIRouter(tags=["teardown"])


@router.get("/books/{book_id}/teardown/essence")
async def essence(book: Book = Depends(get_book)) -> dict:
    if book.source != "teardown":
        raise HTTPException(404, "这本书不是拆的书")
    data = (book.teardown or {}).get("essence")
    if not data:
        return {"essence": None}
    sections = {
        key: {
            "name": section["name"],
            "points": section.get("points") or [],
            **({"figures": section["figures"]} if section.get("figures") else {}),
            "missing": section.get("missing") or [],
        }
        for key, section in (data.get("sections") or {}).items()
        if section.get("points") or section.get("figures")
    }
    return {
        "essence": {
            "upto": data.get("upto"),
            "at": data.get("at"),
            "overview": data.get("overview"),
            "sections": sections,
            "rails": data.get("rails") or {},
        }
    }


@router.get("/books/{book_id}/teardown/digest")
async def digest(
    unit: uuid.UUID | None = None,
    volume: uuid.UUID | None = None,
    arc: uuid.UUID | None = None,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
) -> dict:
    return await teardown_digest.digest(session, book, unit=unit, volume=volume, arc=arc)


@router.get("/books/{book_id}/teardown/waits")
async def waits(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    return await teardown_digest.waits(session, book)


@router.get("/books/{book_id}/teardown/appearances")
async def appearances(
    character: uuid.UUID,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
) -> dict:
    return await teardown_digest.appearances(session, book, character)
