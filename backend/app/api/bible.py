"""设定库的查看与手动修改。"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, ensure_idle, get_book
from app.models import Book, Character, Foreshadowing, Relationship, WorldEntry
from app.schemas import (
    BibleOut,
    CharacterBase,
    CharacterOut,
    CharacterPatch,
    ForeshadowingBase,
    ForeshadowingOut,
    ForeshadowingPatch,
    RelationshipIn,
    RelationshipOut,
    RelationshipPatch,
    WorldEntryBase,
    WorldEntryOut,
    WorldEntryPatch,
)

router = APIRouter(tags=["bible"])


async def _rows(session: AsyncSession, model: Any, book_id: uuid.UUID) -> list:
    return list(
        (await session.execute(select(model).where(model.book_id == book_id).order_by(model.created_at))).scalars()
    )


@router.get("/books/{book_id}/bible", response_model=BibleOut)
async def get_bible(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> BibleOut:
    return BibleOut(
        characters=[CharacterOut.model_validate(r) for r in await _rows(session, Character, book.id)],
        relationships=[RelationshipOut.model_validate(r) for r in await _rows(session, Relationship, book.id)],
        world_entries=[WorldEntryOut.model_validate(r) for r in await _rows(session, WorldEntry, book.id)],
        foreshadowings=[ForeshadowingOut.model_validate(r) for r in await _rows(session, Foreshadowing, book.id)],
    )


async def _create(session: AsyncSession, book_id: uuid.UUID, model: Any, body: BaseModel) -> Any:
    await ensure_idle(session, book_id)
    row = model(book_id=book_id, **body.model_dump())
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "名称重复或引用的人物不存在") from exc
    await session.refresh(row)
    return row


async def _update(session: AsyncSession, model: Any, row_id: uuid.UUID, body: BaseModel) -> Any:
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    await ensure_idle(session, row.book_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "名称重复") from exc
    await session.refresh(row)
    return row


async def _delete(session: AsyncSession, model: Any, row_id: uuid.UUID) -> None:
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    await ensure_idle(session, row.book_id)
    await session.delete(row)
    await session.commit()


# 人物
@router.post("/books/{book_id}/characters", response_model=CharacterOut, status_code=201)
async def create_character(body: CharacterBase, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return await _create(session, book.id, Character, body)


@router.patch("/characters/{row_id}", response_model=CharacterOut)
async def update_character(row_id: uuid.UUID, body: CharacterPatch, session: AsyncSession = SessionDep):
    return await _update(session, Character, row_id, body)


@router.delete("/characters/{row_id}", status_code=204)
async def delete_character(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    await _delete(session, Character, row_id)


# 世界观
@router.post("/books/{book_id}/world-entries", response_model=WorldEntryOut, status_code=201)
async def create_world_entry(body: WorldEntryBase, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return await _create(session, book.id, WorldEntry, body)


@router.patch("/world-entries/{row_id}", response_model=WorldEntryOut)
async def update_world_entry(row_id: uuid.UUID, body: WorldEntryPatch, session: AsyncSession = SessionDep):
    return await _update(session, WorldEntry, row_id, body)


@router.delete("/world-entries/{row_id}", status_code=204)
async def delete_world_entry(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    await _delete(session, WorldEntry, row_id)


# 伏笔
@router.post("/books/{book_id}/foreshadowings", response_model=ForeshadowingOut, status_code=201)
async def create_foreshadowing(
    body: ForeshadowingBase, book: Book = Depends(get_book), session: AsyncSession = SessionDep
):
    return await _create(session, book.id, Foreshadowing, body)


@router.patch("/foreshadowings/{row_id}", response_model=ForeshadowingOut)
async def update_foreshadowing(row_id: uuid.UUID, body: ForeshadowingPatch, session: AsyncSession = SessionDep):
    return await _update(session, Foreshadowing, row_id, body)


@router.delete("/foreshadowings/{row_id}", status_code=204)
async def delete_foreshadowing(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    await _delete(session, Foreshadowing, row_id)


# 人物关系
@router.post("/books/{book_id}/relationships", response_model=RelationshipOut, status_code=201)
async def create_relationship(body: RelationshipIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    if body.source_id == body.target_id:
        raise HTTPException(422, "关系的两端不能是同一个人")
    count = await session.scalar(
        select(func.count())
        .select_from(Character)
        .where(Character.book_id == book.id, or_(Character.id == body.source_id, Character.id == body.target_id))
    )
    if count != 2:
        raise HTTPException(422, "关系引用的人物不属于这本书")
    return await _create(session, book.id, Relationship, body)


@router.patch("/relationships/{row_id}", response_model=RelationshipOut)
async def update_relationship(row_id: uuid.UUID, body: RelationshipPatch, session: AsyncSession = SessionDep):
    return await _update(session, Relationship, row_id, body)


@router.delete("/relationships/{row_id}", status_code=204)
async def delete_relationship(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    await _delete(session, Relationship, row_id)
