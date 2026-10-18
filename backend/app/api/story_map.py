"""全书关键节点、人物锚点、信息差与术语表的读写接口。"""

import uuid
from copy import deepcopy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.glossary import terms
from app.api.deps import SessionDep, ensure_idle, get_book
from app.models import Book, Character, Foreshadowing, NodeAnchor, Secret, StoryNode, Volume
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
from app.services.versions import record_version, snapshot_of

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


def _opening_segment(book: Book, nodes: list[StoryNode]) -> tuple[uuid.UUID, dict] | None:
    """仅新流程开书中的第一段随节点拓扑变更；已开完的书和旧书保持原规则。"""
    if book.status not in {"setting_up", "awaiting_approval"} or (book.setup_progress or {}).get("flow") != 2:
        return None
    endpoint = next((node for node in nodes if (node.segment or {}).get("number") == 1), None)
    return (endpoint.id, deepcopy(endpoint.segment)) if endpoint else None


async def _rebind_opening_segment(
    session: AsyncSession,
    book: Book,
    nodes: list[StoryNode],
    previous: tuple[uuid.UUID, dict] | None,
) -> None:
    """作者仍可插入、删除、重排；第一段的规划和分卷始终跟随新的第二个节点。"""
    if previous is None:
        return
    if len(nodes) < 2 or nodes[1].kind != "milestone":
        raise HTTPException(409, "第一段至少要保留一个终点节点，请先新增一个节点再删除。")
    old_id, segment = previous
    endpoint = nodes[1]
    # 先分配作者新建节点的稳定 ID，后续只移动段规划及关联，不覆盖任何节点文案。
    await session.flush()
    volumes = list(
        await session.scalars(select(Volume).where(Volume.book_id == book.id, Volume.target_node_id == old_id))
    )
    expectations = list(
        await session.scalars(
            select(Foreshadowing).where(
                Foreshadowing.book_id == book.id,
                Foreshadowing.kind == "期待",
                Foreshadowing.span == "长",
                Foreshadowing.node_id == old_id,
                Foreshadowing.description == segment.get("wait", ""),
            )
        )
    )
    for node in nodes:
        node.segment = deepcopy(segment) if node is endpoint else None
    for volume in volumes:
        volume.target_node_id = endpoint.id
    for expectation in expectations:
        expectation.node_id = endpoint.id
    if volumes and endpoint.status != "pinned":
        endpoint.volume = max(volume.index for volume in volumes)
    await session.flush()


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
    book = await _lock_book(session, book.id)
    _allow_empty(book, body.status)
    nodes = await _nodes(session, book.id)
    segment = _opening_segment(book, nodes)
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
    await _rebind_opening_segment(session, book, nodes, segment)
    await session.commit()
    await session.refresh(node)
    return await _node_out(session, node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(node_id: uuid.UUID, body: NodePatch, session: AsyncSession = SessionDep):
    node = await _row(session, StoryNode, node_id)
    book = await _lock_book(session, node.book_id)
    await ensure_idle(session, node.book_id)
    node = await session.scalar(
        select(StoryNode).where(StoryNode.id == node_id).with_for_update().execution_options(populate_existing=True)
    )
    if node is None:
        raise HTTPException(404, "条目不存在")
    before = snapshot_of(node)
    _allow_empty(book, body.status)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "segment":
            if node.segment is None:
                raise HTTPException(422, "这一段还没规划，写到这里时主编会来定")
            if isinstance(value.get("opening"), dict):
                value["opening"] = {**(node.segment.get("opening") or {}), **value["opening"]}
            value = {**node.segment, **value}
            if node.origin == "author" and not node.event and "title" in value:
                # 作者自己加的篇没有单写终点，终点名跟着篇名走
                node.title = str(value["title"])[:100]
        setattr(node, field, value)
    if node.kind == "ending" and body.event is not None and "ending" in (book.concept or {}):
        # 全书结局只认一处：有了结局节点，概念里旧写的那句就不留
        book.concept = {key: value for key, value in book.concept.items() if key != "ending"}
    await record_version(session, node.book_id, "segment", node, "author", before=before)
    await session.commit()
    await session.refresh(node)
    return await _node_out(session, node)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(node_id: uuid.UUID, session: AsyncSession = SessionDep):
    node = await _row(session, StoryNode, node_id)
    await ensure_idle(session, node.book_id)
    book = await _lock_book(session, node.book_id)
    if node.kind in {"opening", "ending"}:
        raise HTTPException(409, "开篇和结局不能删")
    previous_nodes = await _nodes(session, node.book_id)
    segment = _opening_segment(book, previous_nodes)
    nodes = [row for row in previous_nodes if row.id != node.id]
    _renumber(nodes)
    # 在删除旧终点触发外键清理之前重连段内卷和期待；秘密、锚点仍按原节点处理。
    await _rebind_opening_segment(session, book, nodes, segment)
    await session.delete(node)
    await session.commit()


@router.post("/books/{book_id}/nodes/order", response_model=list[NodeOut])
async def order_nodes(body: NodeOrder, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await ensure_idle(session, book.id)
    book = await _lock_book(session, book.id)
    nodes = {node.id: node for node in await _nodes(session, book.id)}
    if len(body.ids) != len(nodes) or set(body.ids) != set(nodes):
        raise HTTPException(422, "必须提交本书全部节点且不能重复")
    segment = _opening_segment(book, list(nodes.values()))
    ordered = [nodes[node_id] for node_id in body.ids]
    _validate_order(ordered)
    _renumber(ordered)
    await _rebind_opening_segment(session, book, ordered, segment)
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
