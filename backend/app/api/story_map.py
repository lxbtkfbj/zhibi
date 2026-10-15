"""全书关键节点、人物锚点、信息差与术语表的读写接口。"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.glossary import terms
from app.api.deps import SessionDep, ensure_idle, get_book
from app.models import Book, Character, NodeAnchor, Secret, StoryNode
from app.schemas import (
    AnchorCreate,
    AnchorOut,
    AnchorPatch,
    NodeCreate,
    NodeOrder,
    NodeOut,
    NodePatch,
    SecretCreate,
    SecretOut,
    SecretPatch,
)

router = APIRouter(tags=["story-map"])


async def _row(session: AsyncSession, model: Any, row_id: uuid.UUID):
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "条目不存在")
    return row


async def validate_node(session: AsyncSession, book_id: uuid.UUID, node_id: uuid.UUID | None) -> None:
    if node_id is not None:
        node = await session.get(StoryNode, node_id)
        if node is None or node.book_id != book_id:
            raise HTTPException(422, "节点不属于这本书")


async def _lock_book(session: AsyncSession, book_id: uuid.UUID) -> Book:
    # 同一本书的编号分配与节点重排串行化，避免两个手动请求写出重复序号。
    return await session.scalar(select(Book).where(Book.id == book_id).with_for_update())


async def _nodes(session: AsyncSession, book_id: uuid.UUID) -> list[StoryNode]:
    return list(
        await session.scalars(select(StoryNode).where(StoryNode.book_id == book_id).order_by(StoryNode.position))
    )


def _validate_order(nodes: list[StoryNode]) -> None:
    openings = [i for i, node in enumerate(nodes) if node.kind == "opening"]
    endings = [i for i, node in enumerate(nodes) if node.kind == "ending"]
    if (openings and openings != [0]) or (endings and endings != [len(nodes) - 1]):
        raise HTTPException(422, "开篇必须在第一个，结局必须在最后一个")


def _renumber(nodes: list[StoryNode]) -> None:
    for index, node in enumerate(nodes, 1):
        node.position = index


async def _anchor_out(session: AsyncSession, anchor: NodeAnchor) -> AnchorOut:
    out = AnchorOut.model_validate(anchor)
    character = await session.get(Character, anchor.character_id)
    out.character_name = character.name
    return out


async def _node_out(session: AsyncSession, node: StoryNode) -> NodeOut:
    out = NodeOut.model_validate(node)
    rows = await session.execute(
        select(NodeAnchor, Character.name)
        .join(Character, Character.id == NodeAnchor.character_id)
        .where(NodeAnchor.node_id == node.id)
        .order_by(NodeAnchor.created_at, NodeAnchor.id)
    )
    out.anchors = [
        AnchorOut.model_validate(anchor).model_copy(update={"character_name": name}) for anchor, name in rows
    ]
    return out


@router.get("/books/{book_id}/nodes", response_model=list[NodeOut])
async def list_nodes(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return [await _node_out(session, node) for node in await _nodes(session, book.id)]


def _allow_empty(book: Book, status: str | None) -> None:
    if status == "empty" and book.status != "setting_up":
        raise HTTPException(422, "只有开书期间可以留空节点")


@router.post("/books/{book_id}/nodes", response_model=NodeOut, status_code=201)
async def create_node(body: NodeCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
    await _lock_book(session, book.id)
    _allow_empty(book, body.status)
    nodes = await _nodes(session, book.id)
    if body.after_node_id is not None:
        insert_at = next((i + 1 for i, node in enumerate(nodes) if node.id == body.after_node_id), None)
        if insert_at is None:
            raise HTTPException(422, "插入位置的节点不属于这本书")
    else:
        insert_at = next((i for i, node in enumerate(nodes) if node.kind == "ending"), len(nodes))
    node = StoryNode(book_id=book.id, kind="milestone", origin="author", **body.model_dump(exclude={"after_node_id"}))
    nodes.insert(insert_at, node)
    _validate_order(nodes)
    _renumber(nodes)
    session.add(node)
    await session.commit()
    await session.refresh(node)
    return await _node_out(session, node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(node_id: uuid.UUID, body: NodePatch, session: AsyncSession = SessionDep):
    node = await _row(session, StoryNode, node_id)
    await ensure_idle(session, node.book_id)
    book = await _lock_book(session, node.book_id)
    _allow_empty(book, body.status)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(node, field, value)
    await session.commit()
    await session.refresh(node)
    return await _node_out(session, node)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: uuid.UUID, session: AsyncSession = SessionDep):
    node = await _row(session, StoryNode, node_id)
    await ensure_idle(session, node.book_id)
    await _lock_book(session, node.book_id)
    if node.kind in {"opening", "ending"}:
        raise HTTPException(409, "开篇和结局不能删")
    nodes = [row for row in await _nodes(session, node.book_id) if row.id != node.id]
    await session.delete(node)
    _renumber(nodes)
    await session.commit()


@router.post("/books/{book_id}/nodes/order", response_model=list[NodeOut])
async def order_nodes(body: NodeOrder, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
    await _lock_book(session, book.id)
    nodes = {node.id: node for node in await _nodes(session, book.id)}
    if len(body.ids) != len(nodes) or set(body.ids) != set(nodes):
        raise HTTPException(422, "必须提交本书全部节点且不能重复")
    ordered = [nodes[node_id] for node_id in body.ids]
    _validate_order(ordered)
    _renumber(ordered)
    await session.commit()
    return [await _node_out(session, node) for node in ordered]


async def _validate_anchor(session: AsyncSession, book_id: uuid.UUID, node_id: uuid.UUID, character_id: uuid.UUID):
    await validate_node(session, book_id, node_id)
    character = await session.get(Character, character_id)
    if character is None or character.book_id != book_id:
        raise HTTPException(422, "人物不属于这本书")


@router.post("/books/{book_id}/anchors", response_model=AnchorOut, status_code=201)
async def create_anchor(body: AnchorCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
    await _validate_anchor(session, book.id, body.node_id, body.character_id)
    anchor = NodeAnchor(book_id=book.id, **body.model_dump())
    session.add(anchor)
    await session.commit()
    await session.refresh(anchor)
    return await _anchor_out(session, anchor)


@router.patch("/anchors/{anchor_id}", response_model=AnchorOut)
async def update_anchor(anchor_id: uuid.UUID, body: AnchorPatch, session: AsyncSession = SessionDep):
    anchor = await _row(session, NodeAnchor, anchor_id)
    await ensure_idle(session, anchor.book_id)
    values = body.model_dump(exclude_unset=True)
    await _validate_anchor(
        session, anchor.book_id, values.get("node_id", anchor.node_id), values.get("character_id", anchor.character_id)
    )
    for field, value in values.items():
        setattr(anchor, field, value)
    await session.commit()
    await session.refresh(anchor)
    return await _anchor_out(session, anchor)


@router.delete("/anchors/{anchor_id}", status_code=204)
async def delete_anchor(anchor_id: uuid.UUID, session: AsyncSession = SessionDep):
    anchor = await _row(session, NodeAnchor, anchor_id)
    await ensure_idle(session, anchor.book_id)
    await session.delete(anchor)
    await session.commit()


async def _validate_secret(session: AsyncSession, book_id: uuid.UUID, values: dict):
    await validate_node(session, book_id, values.get("node_id"))
    if "knowers" in values:
        names = set(await session.scalars(select(Character.name).where(Character.book_id == book_id)))
        if any(knower["name"] not in names for knower in values["knowers"]):
            raise HTTPException(422, "知情人必须是本书已有的人物")


@router.get("/books/{book_id}/secrets", response_model=list[SecretOut])
async def list_secrets(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return list(await session.scalars(select(Secret).where(Secret.book_id == book.id).order_by(Secret.seq)))


@router.post("/books/{book_id}/secrets", response_model=SecretOut, status_code=201)
async def create_secret(body: SecretCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
    await _lock_book(session, book.id)
    values = body.model_dump()
    await _validate_secret(session, book.id, values)
    seq = await session.scalar(select(func.coalesce(func.max(Secret.seq), 0)).where(Secret.book_id == book.id))
    secret = Secret(book_id=book.id, seq=int(seq or 0) + 1, **values)
    session.add(secret)
    await session.commit()
    await session.refresh(secret)
    return secret


@router.patch("/secrets/{secret_id}", response_model=SecretOut)
async def update_secret(secret_id: uuid.UUID, body: SecretPatch, session: AsyncSession = SessionDep):
    secret = await _row(session, Secret, secret_id)
    await ensure_idle(session, secret.book_id)
    values = body.model_dump(exclude_unset=True)
    await _validate_secret(session, secret.book_id, values)
    for field, value in values.items():
        setattr(secret, field, value)
    await session.commit()
    await session.refresh(secret)
    return secret


@router.delete("/secrets/{secret_id}", status_code=204)
async def delete_secret(secret_id: uuid.UUID, session: AsyncSession = SessionDep):
    secret = await _row(session, Secret, secret_id)
    await ensure_idle(session, secret.book_id)
    await session.delete(secret)
    await session.commit()


@router.get("/glossary")
def get_glossary() -> dict:
    return {"terms": [{"term": term, "explanation": explanation} for term, explanation in terms()]}
