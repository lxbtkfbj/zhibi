"""设定库的查看与手动修改。"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, ensure_idle, get_book
from app.api.story_map import validate_node
from app.models import Book, Character, Foreshadowing, Relationship, Secret, WorldEntry
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
    SecretOut,
    WorldEntryBase,
    WorldEntryOut,
    WorldEntryPatch,
)
from app.services.library import (
    CHARACTER_CONTENT,
    ENTRY_CONTENT,
    author_source,
    infer_status,
    lock_book,
    validate_entry,
)
from app.services.library_cascade import author_rename_suggestions
from app.services.versions import record_version, snapshot_of

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
        foreshadowings=[
            ForeshadowingOut.model_validate(r)
            for r in sorted(await _rows(session, Foreshadowing, book.id), key=lambda f: f.seq)
        ],
        secrets=[
            SecretOut.model_validate(r)
            for r in sorted(await _rows(session, Secret, book.id), key=lambda secret: secret.seq)
        ],
    )


async def _create(session: AsyncSession, book_id: uuid.UUID, model: Any, body: BaseModel) -> Any:
    await lock_book(session, book_id)
    await ensure_idle(session, book_id)
    data = body.model_dump(exclude_unset=True)
    if model is WorldEntry:
        data = await validate_entry(session, book_id, data)
    if model in (Character, WorldEntry):
        data["source"] = "candidate" if data.get("source") == "candidate" else "author"
    row = model(book_id=book_id, **data)
    if model in (Character, WorldEntry) and "status" not in data:
        row.status = infer_status(row)
    session.add(row)
    try:
        if model in (Character, WorldEntry):
            await record_version(session, book_id, "character" if model is Character else "entry", row, "author")
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "名称重复或引用的人物不存在") from exc
    await session.refresh(row)
    return row


def merge_partial(row: Any, data: dict) -> dict:
    """角色的 extra、条目的 field_values 只改给出的几栏：合进原来的，空字符串就清掉。"""
    if isinstance(row, Character) and "extra" in data:
        merged = {**(row.extra or {}), **data["extra"]}
        data["extra"] = {key: value for key, value in merged.items() if value}
    if isinstance(row, WorldEntry) and "field_values" in data:
        values = data.pop("field_values")
        fields = [dict(f) for f in data.get("fields", row.fields or [])]
        for name, value in values.items():
            hit = next((f for f in fields if f.get("name") == name), None)
            if hit is not None:
                hit["value"] = value
            elif value:
                fields.append({"name": name, "value": value})
        data["fields"] = [f for f in fields if f.get("value")]
    return data


async def _update(session: AsyncSession, model: Any, row_id: uuid.UUID, body: BaseModel) -> Any:
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    await lock_book(session, row.book_id)
    await ensure_idle(session, row.book_id)
    row = await session.scalar(
        select(model).where(model.id == row_id).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "条目不存在")
    versioned = model in (Character, WorldEntry)
    before = snapshot_of(row) if versioned else None
    previous_source = row.source if versioned else None
    data = merge_partial(row, body.model_dump(exclude_unset=True))
    if model is WorldEntry:
        data = await validate_entry(session, row.book_id, data, current=row)
    if model is Foreshadowing:
        await validate_node(session, row.book_id, body.model_dump(exclude_unset=True).get("node_id"))
    if model is Character and body.name is not None and body.name != row.name:
        old_name = row.name
        secrets = await session.scalars(select(Secret).where(Secret.book_id == row.book_id))
        for secret in secrets:
            if any(knower.get("name") == old_name for knower in secret.knowers):
                secret.knowers = [
                    {**knower, "name": body.name} if knower.get("name") == old_name else knower
                    for knower in secret.knowers
                ]
    for key, value in data.items():
        setattr(row, key, value)
    content = CHARACTER_CONTENT if model is Character else ENTRY_CONTENT
    if versioned and "status" not in data and any(key in data for key in content):
        row.status = infer_status(row)
    try:
        if versioned:
            row.source = author_source(row)
            await record_version(
                session,
                row.book_id,
                "character" if model is Character else "entry",
                row,
                row.source,
                before=before,
                previous_source=previous_source,
            )
            await author_rename_suggestions(session, row, before)
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "名称重复") from exc
    await session.refresh(row)
    return row


async def _delete(session: AsyncSession, model: Any, row_id: uuid.UUID) -> None:
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    await lock_book(session, row.book_id)
    await ensure_idle(session, row.book_id)
    row = await session.scalar(
        select(model).where(model.id == row_id).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "条目不存在")
    await session.delete(row)
    await session.commit()


# 人物
@router.post("/books/{book_id}/characters", response_model=CharacterOut, status_code=201)
async def create_character(body: CharacterBase, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return await _create(session, book.id, Character, body)


@router.patch("/characters/{row_id}", response_model=CharacterOut)
async def update_character(row_id: uuid.UUID, body: CharacterPatch, session: AsyncSession = SessionDep):
    return await _update(session, Character, row_id, body)


class PinIn(BaseModel):
    pinned: bool


@router.post("/characters/{row_id}/pin", response_model=CharacterOut)
async def pin_character(row_id: uuid.UUID, body: PinIn, session: AsyncSession = SessionDep):
    """置顶、取消置顶：排在角色目录最上面（后置顶的在上），编辑部每写一章都带上他的卡。
    只是排个顺序、告诉编辑部谁要一直记着，不算改了这张卡：不记版本，编辑部在干活时也能点。"""
    row = await session.get(Character, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    row.pinned_at = datetime.now(UTC) if body.pinned else None
    await session.commit()
    await session.refresh(row)
    return row


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
    await ensure_idle(session, book.id)
    await session.execute(select(Book.id).where(Book.id == book.id).with_for_update())
    await validate_node(session, book.id, body.node_id)
    seq = await session.scalar(
        select(func.coalesce(func.max(Foreshadowing.seq), 0)).where(Foreshadowing.book_id == book.id)
    )
    row = Foreshadowing(book_id=book.id, seq=int(seq or 0) + 1, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@router.patch("/foreshadowings/{row_id}", response_model=ForeshadowingOut)
async def update_foreshadowing(row_id: uuid.UUID, body: ForeshadowingPatch, session: AsyncSession = SessionDep):
    return await _update(session, Foreshadowing, row_id, body)


@router.delete("/foreshadowings/{row_id}", status_code=204)
async def delete_foreshadowing(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    await _delete(session, Foreshadowing, row_id)


# 人物关系
@router.post("/books/{book_id}/relationships", response_model=RelationshipOut, status_code=201)
async def create_relationship(body: RelationshipIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
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
