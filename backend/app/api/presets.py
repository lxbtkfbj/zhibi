"""全局主编群聊预设：系统版本只读，作者的修改逐次保存。"""

import json
import uuid
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import SessionDep
from app.models import Book, ChatConversation, ChatThread, Preset, PresetSave
from app.services import preset_store, presets

router = APIRouter(prefix="/presets", tags=["presets"])


def system_of(kind: str, version: int | None = None) -> dict:
    preset_store.ensure_kind(kind)
    try:
        return presets.system_preset(kind, version)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("")
async def listing(kind: str = "chief_group", session=SessionDep):
    preset_store.ensure_kind(kind)
    rows = await session.scalars(
        select(Preset).where(Preset.kind == kind).order_by(Preset.updated_at.desc(), Preset.id)
    )
    return {
        "kinds": list(presets.KINDS),
        "kind": kind,
        "active": await preset_store.active_selection(session, kind),
        "system": system_of(kind),
        "versions": presets.system_versions(kind),
        "mine": [preset_store.summary(row) for row in rows],
    }


@router.get("/conditions")
async def conditions():
    return list(presets.CONDITIONS)


@router.get("/placeholders")
async def placeholders(kind: str = "chief_group", book_id: uuid.UUID | None = None, session=SessionDep):
    preset_store.ensure_kind(kind)
    items = [dict(row) for row in presets.PLACEHOLDERS]
    if book_id is None:
        return items
    book = await session.get(Book, book_id)
    if book is None:
        raise HTTPException(404, "书不存在")
    if book.source == "teardown":
        raise HTTPException(422, "主编群聊预设只用于作者自己的书，拆的书照旧用原来的提示词")
    # 预览只读已有摘要、原话和书的当前资料，不新建对话、不折叠摘要、不调用模型。
    from app.services.chat_agent import agent_values
    from app.services.chat_context import dialogue

    state = await session.scalar(
        select(ChatConversation)
        .where(ChatConversation.book_id == book_id, ChatConversation.archived_at.is_(None))
        .order_by(ChatConversation.last_at.desc(), ChatConversation.created_at.desc())
        .limit(1)
    )
    if state is not None:
        rows = await dialogue(session, book_id, "group", conv=state.id)
    else:
        has_conversation = await session.scalar(
            select(ChatConversation.id).where(ChatConversation.book_id == book_id).limit(1)
        )
        if has_conversation is not None:
            # 全部归档后，真正发话会开一个空段；不能把归档的聊天拿来预览。
            rows = []
        else:
            state = await session.scalar(
                select(ChatThread).where(ChatThread.book_id == book_id, ChatThread.thread == "group")
            )
            rows = await dialogue(session, book_id, "group", reset_after=state.reset_after if state else 0)
    rows = [row for row in rows if row.id > state.summarized_until] if state else rows
    message = SimpleNamespace(content="", payload={})
    values = await agent_values(session, book, "chief", message, rows, state.summary if state else "", False, False)
    current = presets.placeholder_values(values)
    dynamic = {"正在看的那一页", "选中的原文", "上次做到一半", "作者这次说的"}
    short = {"资料说明", "等你确认的", "编辑部正在干活"}
    for row in items:
        name = row["name"]
        value = current[name]
        row["preview"] = (
            "发的时候才有"
            if name in dynamic
            else (value or "（现在是空的）")
            if name in short
            else value[:300] + ("……" if len(value) > 300 else "")
        )
    return items


@router.get("/system/{kind}")
async def show_system(kind: str, version: int | None = None):
    return system_of(kind, version)


def download(preset: dict) -> Response:
    data = preset_store.exported(preset)
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(preset["name"] + ".json", safe="")},
    )


@router.get("/system/{kind}/export")
async def export_system(kind: str, version: int | None = None):
    return download(system_of(kind, version))


class CreateIn(BaseModel):
    kind: str = "chief_group"
    name: str | None = Field(default=None, max_length=200)
    source: str = "system"
    id: uuid.UUID | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        return value.strip() or None if value is not None else None


@router.post("/mine", status_code=201)
async def create_mine(body: CreateIn | None = None, session=SessionDep):
    body = body or CreateIn()
    return await preset_store.create(
        session, kind=body.kind, name=body.name, source=body.source, source_id=body.id, version=body.version
    )


@router.get("/mine/{preset_id}")
async def show_mine(preset_id: uuid.UUID, session=SessionDep):
    return await preset_store.detail(session, await preset_store.mine_of(session, preset_id))


class SaveIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    blocks: list[dict]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("预设名字不能为空")
        return value.strip()


@router.put("/mine/{preset_id}")
async def save_mine(preset_id: uuid.UUID, body: SaveIn, session=SessionDep):
    row = await preset_store.mine_of(session, preset_id, lock=True)
    blocks = preset_store.normalize_blocks(body.blocks, existing=row.blocks)
    return await preset_store.save(session, row, body.name, blocks)


@router.delete("/mine/{preset_id}")
async def delete_mine(preset_id: uuid.UUID, session=SessionDep):
    await preset_store.remove(session, await preset_store.mine_of(session, preset_id, lock=True))
    return {"deleted": True}


def save_dict(row: PresetSave, *, blocks: bool = False) -> dict:
    result = {
        "id": str(row.id),
        "preset_id": str(row.preset_id),
        "saved": row.saved,
        "name": row.name,
        "saved_at": row.saved_at.isoformat(),
    }
    if blocks:
        result["blocks"] = row.blocks
    return result


@router.get("/mine/{preset_id}/saves")
async def saves(preset_id: uuid.UUID, session=SessionDep):
    await preset_store.mine_of(session, preset_id)
    rows = await session.scalars(
        select(PresetSave).where(PresetSave.preset_id == preset_id).order_by(PresetSave.saved.desc())
    )
    return [save_dict(row) for row in rows]


async def save_of(session, preset_id, number) -> PresetSave:
    row = await session.scalar(select(PresetSave).where(PresetSave.preset_id == preset_id, PresetSave.saved == number))
    if row is None:
        raise HTTPException(404, "没有这一次保存")
    return row


@router.get("/mine/{preset_id}/saves/{number}")
async def show_save(preset_id: uuid.UUID, number: int, session=SessionDep):
    await preset_store.mine_of(session, preset_id)
    return save_dict(await save_of(session, preset_id, number), blocks=True)


@router.post("/mine/{preset_id}/saves/{number}/restore")
async def restore(preset_id: uuid.UUID, number: int, session=SessionDep):
    row = await preset_store.mine_of(session, preset_id, lock=True)
    old = await save_of(session, preset_id, number)
    return await preset_store.save(session, row, old.name, old.blocks)


class ActiveIn(BaseModel):
    kind: str = "chief_group"
    source: str
    id: uuid.UUID | None = None


@router.put("/active")
async def activate(body: ActiveIn, session=SessionDep):
    return await preset_store.set_active(session, kind=body.kind, source=body.source, preset_id=body.id)


@router.post("/check")
async def check(request: Request):
    try:
        body = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "预设检查内容必须是 JSON") from exc
    kind = body.get("kind", "chief_group") if isinstance(body, dict) else "chief_group"
    preset_store.ensure_kind(kind)
    blocks = body.get("blocks") if isinstance(body, dict) else body
    blocks = preset_store.normalize_blocks(blocks, imported=True)
    return {"issues": presets.check(blocks, kind=kind)}


@router.get("/mine/{preset_id}/export")
async def export_mine(preset_id: uuid.UUID, session=SessionDep):
    row = await preset_store.mine_of(session, preset_id)
    return download({"kind": row.kind, "name": row.name, "blocks": row.blocks})


@router.post("/import", status_code=201)
async def import_file(request: Request, session=SessionDep):
    try:
        if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            form = await request.form()
            uploaded = form.get("file")
            if uploaded is None or not hasattr(uploaded, "read"):
                raise HTTPException(422, "请在 file 字段传预设 JSON 文件")
            try:
                data = json.loads(await uploaded.read())
            finally:
                await uploaded.close()
        else:
            data = await request.json()
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(422, "预设文件不是有效的 UTF-8 JSON") from exc
    return await preset_store.import_preset(session, data)
