"""手册管理：所有改动在同一数据库事务锁下校验并保存。"""

import hashlib
import uuid

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.models import Handbook, HandbookSave
from app.prompts import handbooks

router = APIRouter(prefix="/handbooks", tags=["handbooks"])


class HandbookIn(BaseModel):
    name: str
    when: str
    body: str


class EnabledIn(BaseModel):
    enabled: bool


def _row(row: Handbook) -> dict:
    return {column.name: getattr(row, column.name) for column in Handbook.__table__.columns}


async def _inventory(session: AsyncSession):
    systems = handbooks.system_books()
    rows = list(await session.scalars(select(Handbook)))
    return handbooks.resolve([_row(row) for row in rows], systems), systems, {row.key: row for row in rows}


def _hash(book: handbooks.Handbook) -> str:
    return hashlib.sha256(book.content.encode("utf-8")).hexdigest()


def _fields(book: handbooks.Handbook) -> dict:
    return {"name": book.name, "when": book.when, "body": book.body, "content": book.content}


def _meta(book, row, system) -> dict:
    modified = system is not None and row is not None and row["name"] is not None
    return {
        "key": book.key,
        "source": "system" if system is not None else "mine",
        "enabled": row["enabled"] if row else True,
        "name": book.name,
        "when": book.when,
        "modified": modified,
        "saved": row["saved"] if row else 0,
        "chars": len(book.content),
        "complete": bool(book.name.strip() and book.when.strip() and book.body.strip()),
        "system_updated": bool(modified and row["system_hash"] != _hash(system)),
    }


async def _current(session: AsyncSession, key: str):
    books, systems, rows = await _inventory(session)
    found = next(((book, row) for book, row in books if book.key == key), None)
    if found is None:
        raise HTTPException(404, "手册不存在。")
    return *found, systems.get(key), rows.get(key)


async def _detail(session: AsyncSession, key: str) -> dict:
    book, row, system, _ = await _current(session, key)
    return {**_meta(book, row, system), **_fields(book), "system": _fields(system) if system else None}


async def _lock(session: AsyncSession) -> None:
    # 虚拟系统行也在同一把锁的保护下，跨 API/worker 进程序列化名称变更。
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('zhibi:handbooks'))"))


def _validate(body: HandbookIn) -> HandbookIn:
    name, when = body.name.strip(), body.when.strip()
    error = None
    if not name:
        error = "名称不能空着。"
    elif len(name) > 20:
        error = "名称最多 20 个字。"
    elif len(body.name.splitlines()) > 1 or "\r" in body.name or "\n" in body.name:
        error = "名称只写一行。"
    elif len(body.when.splitlines()) > 1 or "\r" in body.when or "\n" in body.when:
        error = "什么时候翻只写一行。"
    elif len(when) > 300:
        error = "什么时候翻最多 300 个字。"
    elif len(body.body) > 50_000:
        error = "正文最多五万字。"
    elif any("{{" in value or "}}" in value for value in (name, when, body.body)):
        error = "手册里不能有 {{ 或 }}。"
    if error:
        raise HTTPException(422, error)
    return HandbookIn(name=name, when=when, body=body.body)


async def _check_enabled(session: AsyncSession, key: str, body: HandbookIn, *, opening=False) -> None:
    if not all(value.strip() for value in (body.name, body.when, body.body)):
        raise HTTPException(
            422,
            "名称、什么时候翻、正文都写上，才能打开。"
            if opening
            else "开着的手册，名称、什么时候翻、正文都得写上；还没写完，先关掉再存。",
        )
    books, _, _ = await _inventory(session)
    if any(book.key != key and book.name == body.name and (row is None or row["enabled"]) for book, row in books):
        raise HTTPException(422, f"已经有一本开着的「{body.name}」。先关掉那本，或者给这本改个名。")


async def _materialize(session, key, system, row):
    if row is None:
        row = Handbook(key=key, source="system", enabled=True, saved=0)
        session.add(row)
        await session.flush()
    elif system is None:
        row.source = "mine"
    return row


async def _save(session, row, body, kind, *, restore_saved=None, follows_system=False):
    row.saved += 1
    session.add(
        HandbookSave(
            key=row.key,
            saved=row.saved,
            name=body.name,
            when=body.when,
            body=body.body,
            kind=kind,
            restore_saved=restore_saved,
            follows_system=follows_system,
        )
    )
    await session.commit()
    return await _detail(session, row.key)


@router.get("")
async def list_handbooks(session: AsyncSession = SessionDep) -> dict:
    books, systems, _ = await _inventory(session)
    return {
        "items": [_meta(book, row, systems.get(book.key)) for book, row in books],
        "catalog": handbooks.description([book for book, row in books if row is None or row["enabled"]]),
    }


@router.get("/{key}")
async def get_handbook(key: str, session: AsyncSession = SessionDep) -> dict:
    return await _detail(session, key)


@router.post("")
async def create_handbook(session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    books, _, _ = await _inventory(session)
    names = {book.name for book, _ in books}
    name, n = "新手册", 2
    while name in names:
        name = f"新手册 {n}"
        n += 1
    row = Handbook(key="mine_" + uuid.uuid4().hex, source="mine", enabled=False, saved=0, name=name, when="", body="")
    session.add(row)
    await session.flush()
    return await _save(session, row, HandbookIn(name=name, when="", body=""), "create")


@router.put("/{key}")
async def save_handbook(key: str, body: HandbookIn, session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    _, old, system, row = await _current(session, key)
    body = _validate(body)
    if old is None or old["enabled"]:
        await _check_enabled(session, key, body)
    row = await _materialize(session, key, system, row)
    if system is not None and row.system_hash is None:
        row.system_hash = _hash(system)
    row.name, row.when, row.body = body.name, body.when, body.body
    return await _save(session, row, body, "save")


@router.put("/{key}/enabled")
async def enable_handbook(key: str, body: EnabledIn, session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    book, _, system, row = await _current(session, key)
    if body.enabled:
        await _check_enabled(session, key, HandbookIn(name=book.name, when=book.when, body=book.body), opening=True)
    row = await _materialize(session, key, system, row)
    row.enabled = body.enabled
    await session.commit()
    return await _detail(session, key)


@router.delete("/{key}", status_code=204)
async def delete_handbook(key: str, session: AsyncSession = SessionDep) -> Response:
    await _lock(session)
    _, _, system, row = await _current(session, key)
    if system is not None:
        raise HTTPException(409, "程序带的手册不能删，可以关掉。")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.post("/{key}/use-system")
async def use_system(key: str, session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    book, old, system, row = await _current(session, key)
    if system is None:
        raise HTTPException(409, "这本不是程序带的手册。")
    if old is None or old["name"] is None:
        return await _detail(session, key)
    body = HandbookIn(name=system.name, when=system.when, body=system.body)
    if row.enabled:
        await _check_enabled(session, key, body)
    row.name = row.when = row.body = row.system_hash = None
    return await _save(session, row, body, "use_system", follows_system=True)


@router.post("/{key}/seen-system")
async def seen_system(key: str, session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    _, old, system, row = await _current(session, key)
    if system is not None and old and old["name"] is not None:
        row.system_hash = _hash(system)
        await session.commit()
    return await _detail(session, key)


def _saved(row: HandbookSave) -> dict:
    return {
        "saved": row.saved,
        "name": row.name,
        "when": row.when,
        "body": row.body,
        "kind": row.kind,
        "restore_saved": row.restore_saved,
        "saved_at": row.saved_at,
        "chars": len(handbooks.compose(row.name, row.when, row.body)),
    }


@router.get("/{key}/saves")
async def list_saves(key: str, session: AsyncSession = SessionDep) -> list[dict]:
    await _current(session, key)
    rows = await session.scalars(
        select(HandbookSave).where(HandbookSave.key == key).order_by(HandbookSave.saved.desc())
    )
    return [_saved(row) for row in rows]


async def _get_save(session, key, n):
    row = await session.get(HandbookSave, (key, n))
    if row is None:
        raise HTTPException(404, "保存记录不存在。")
    return row


@router.get("/{key}/saves/{n}")
async def get_save(key: str, n: int, session: AsyncSession = SessionDep) -> dict:
    await _current(session, key)
    return _saved(await _get_save(session, key, n))


@router.post("/{key}/saves/{n}/restore")
async def restore_save(key: str, n: int, session: AsyncSession = SessionDep) -> dict:
    await _lock(session)
    _, _, system, row = await _current(session, key)
    saved = await _get_save(session, key, n)
    follows_system = system is not None and saved.follows_system
    body = (
        HandbookIn(name=system.name, when=system.when, body=system.body)
        if follows_system
        else HandbookIn(name=saved.name, when=saved.when, body=saved.body)
    )
    body = _validate(body)
    if row.enabled:
        await _check_enabled(session, key, body)
    row = await _materialize(session, key, system, row)
    if follows_system:
        row.name = row.when = row.body = row.system_hash = None
    else:
        row.name, row.when, row.body = body.name, body.when, body.body
        if system is not None and row.system_hash is None:
            row.system_hash = _hash(system)
    return await _save(session, row, body, "restore", restore_saved=n, follows_system=follows_system)
