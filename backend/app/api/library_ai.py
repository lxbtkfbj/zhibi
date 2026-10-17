"""设定库的请求内 AI 操作：模型只交回局部文字，程序负责合回与版本。"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import library_config as config
from app.agents import schemas as s
from app.agents.context import format_requirements
from app.agents.editorial import persona
from app.api.deps import SessionDep, get_book, get_redis
from app.api.library import _splice_error, _validate_changed_target
from app.db import get_sessionmaker
from app.library_schemas import CandidateOut, SuggestionOut
from app.llm.router import LLMRouter
from app.models import Book, Character, SettingCandidate, SettingSuggestion, WorldEntry
from app.prompts import render
from app.services.library import ensure_unlocked, load_target, lock_book
from app.services.library_cascade import generate_cascade_suggestions, iter_text_paths
from app.services.library_context import load_context, rewrite_mode
from app.services.meeting import post_message
from app.services.requirements import list_requirements
from app.services.splice import read_path, splice
from app.services.versions import record_version, snapshot_of, target_type_of

router = APIRouter(tags=["library"])
TargetType = Literal["entry", "character", "concept", "segment", "volume", "unit"]
MODE_NAMES = {"instruction": "照作者的意思改", "expand": "写细一点", "shorten": "精简一点"}


class RewriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: TargetType
    target_id: uuid.UUID
    path: str
    mode: Literal["options", "instruction", "expand", "shorten"] = "options"
    instruction: str = ""


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["entry", "character"]
    target_id: uuid.UUID


async def call_model(book_id, role, schema, template, **values):
    """每个请求独占客户端；不在模型调用期间持有书锁（调用日志也会锁书）。"""
    llm = LLMRouter(get_sessionmaker(), book_id=book_id)
    try:
        try:
            return await llm.structured(role, schema, persona(role), render(template, **values), purpose=template)
        finally:
            await llm.aclose()
    except Exception as exc:
        raise HTTPException(502, f"模型出错了：{exc}") from exc


def _unlocked(target):
    try:
        ensure_unlocked(target)
    except HTTPException as exc:
        raise HTTPException(409, "已锁：AI 不能改这一处，先解锁") from exc


async def say(session, redis, book_id, speaker, content):
    return await post_message(
        session, redis, book_id=book_id, job_id=None, speaker=speaker, kind="speech", content=content
    )


async def rewrite_target(session, redis, book, body: RewriteIn):
    if body.mode == "instruction" and not body.instruction.strip():
        raise HTTPException(422, "先写一句你想怎么改")
    book_id = book.id
    target = await load_target(session, book_id, body.target_type, body.target_id)
    _unlocked(target)
    try:
        current = read_path(target, body.path)
        if not isinstance(current, str):
            raise ValueError("这一处不是文字，不能替换")
    except ValueError as exc:
        raise _splice_error(exc) from exc
    ctx = await load_context(session, book)
    name, part = ctx.target_name(target), ctx.part_label(target, body.path)
    values = dict(
        concept=ctx.concept,
        library=ctx.library,
        target_full=ctx.entry_full_text(target),
        related=ctx.related(target),
        target_label=ctx.target_label(target, body.path),
        current=current,
        category_hint=ctx.category_hint(target),
        mode=rewrite_mode(body.mode, body.instruction),
    )
    # 释放读事务，再调模型；写入前重新读取并锁定目标，base 检查保护作者并发修改。
    await session.rollback()
    result = await call_model(
        book_id,
        "lorekeeper",
        s.RewriteOptions if body.mode == "options" else s.RewriteOne,
        "library_rewrite",
        **values,
    )
    await lock_book(session, book_id)
    target = await load_target(session, book_id, body.target_type, body.target_id, for_update=True)
    _unlocked(target)
    if body.mode == "options":
        if [item.label for item in result.options] != ["稳妥", "大胆", "出格"]:
            raise HTTPException(502, "模型出错了：没有按稳妥、大胆、出格给出三种写法")
        candidate = SettingCandidate(
            book_id=book_id,
            target_type=body.target_type,
            target_id=body.target_id,
            path=body.path,
            base=current,
            options=[item.model_dump() for item in result.options],
        )
        session.add(candidate)
        await say(session, redis, book_id, "lorekeeper", f"我给「{name}」的{part}出了三种写法，去设定库挑一个。")
        return {"candidate": CandidateOut.model_validate(candidate)}
    before = snapshot_of(target)
    previous_source = getattr(target, "source", "ai")
    try:
        with session.no_autoflush:
            old, new = splice(target, body.path, result.text, base=current)
            await _validate_changed_target(session, book_id, target, before)
        if isinstance(target, (WorldEntry, Character)):
            target.source = "ai"
        version = await record_version(
            session,
            book_id,
            body.target_type,
            target,
            "ai",
            MODE_NAMES[body.mode],
            before=before,
            previous_source=previous_source,
        )
        suggestions = await generate_cascade_suggestions(
            session,
            book_id,
            target,
            body.path,
            [item.model_dump() for item in result.renamed],
            one_line=result.one_line,
        )
        verb = {"instruction": "照你的意思改了", "expand": "写细了", "shorten": "精简了"}[body.mode]
        await say(session, redis, book_id, "lorekeeper", f"{verb}「{name}」的{part}。")
    except ValueError as exc:
        raise _splice_error(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "修改后的名称重复或引用已不存在") from exc
    return {
        "applied": {"path": body.path, "before": old, "after": new},
        "version": version.version,
        "suggestions": [SuggestionOut.model_validate(row) for row in suggestions],
    }


@router.post("/books/{book_id}/library/rewrite")
async def rewrite(
    body: RewriteIn,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    return await rewrite_target(session, redis, book, body)


@router.post("/books/{book_id}/library/fill-gaps")
async def fill_gaps(
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    book_id = book.id
    ctx = await load_context(session, book)
    requirements = await list_requirements(session, book_id)
    values = dict(
        concept=ctx.concept,
        library=ctx.library,
        genre_defaults=ctx.genre_defaults,
        requirements=format_requirements([row.text for row in requirements], [], book.settings),
    )
    await session.rollback()
    result = await call_model(book_id, "chief", s.GapReport, "library_fill_gaps", **values)
    await lock_book(session, book_id)
    book = await session.get(Book, book_id)
    ctx = await load_context(session, book)
    categories = {row["name"]: row for row in ctx.categories}
    statuses = {value: key for key, value in config.STATUSES.items()}
    columns = dict(config.CHARACTER_CATEGORY["fields"])
    suggestions = []
    for entry in result.entries:
        data = {"name": entry.name, "one_line": entry.one_line, "status": statuses[entry.status]}
        if entry.category == "角色卡片":
            for field in entry.fields:
                column = columns.get(field.name)
                if column and column != "name":
                    data[column] = (
                        field.value.split("、")
                        if column == "aliases" and field.value
                        else ([] if column == "aliases" else field.value)
                    )
            payload = {"op": "create_character", "character": data}
            category_name = "角色卡片"
        else:
            category = categories.get(entry.category, categories["特殊规则"])
            data.update(category=category["key"], style=category["style"], content=entry.content)
            if category["style"] == "card":
                data["fields"] = [field.model_dump() for field in entry.fields]
            payload = {"op": "create_entry", "entry": data}
            category_name = entry.category if entry.category in categories else "特殊规则"
        row = SettingSuggestion(
            book_id=book_id,
            kind="fill_gap",
            payload=payload,
            title=f"补一条{category_name}：「{entry.name}」——{entry.why}",
        )
        session.add(row)
        suggestions.append(row)
    for category in result.categories:
        row = SettingSuggestion(
            book_id=book_id,
            kind="fill_gap",
            title=f"建一个自建类别「{category.name}」——{category.why}",
            payload={"op": "create_category", "category": category.model_dump(exclude={"why"})},
        )
        session.add(row)
        suggestions.append(row)
    await say(session, redis, book_id, "chief", result.note)
    return {"suggestions": [SuggestionOut.model_validate(row) for row in suggestions], "note": result.note}


async def review_library(session, redis, book, check: CheckIn | None = None):
    book_id = book.id
    ctx = await load_context(session, book)
    scope = "查整个设定库。"
    if check:
        target = await load_target(session, book_id, check.target_type, check.target_id)
        scope = f"只查这一条：{ctx.target_heading(target)}；需要时对照别的条目。"
    values = dict(concept=ctx.concept, library_full=ctx.library_full, outline=ctx.outline, scope=scope)
    await session.rollback()
    result = await call_model(book_id, "reviewer", s.LibraryReview, "library_review", **values)
    await lock_book(session, book_id)
    book = await session.get(Book, book_id)
    ctx = await load_context(session, book)
    suggestions = []
    for issue in result.issues:
        target = next((row for row in [*ctx.characters, *ctx.entries] if row.name == issue.target_name), None)
        payload = {"op": "note", "why": issue.why}
        target_type = target_type_of(target) if target is not None else None
        target_id = target.id if target is not None else None
        if target is not None and issue.quote and issue.fix:
            for path, value in iter_text_paths(target):
                start = value.find(issue.quote)
                if start >= 0:
                    payload = {
                        "op": "splice",
                        "target_type": target_type,
                        "target_id": str(target_id),
                        "path": f"{path}@{start}:{start + len(issue.quote)}",
                        "base": issue.quote,
                        "new": issue.fix,
                        "why": issue.why,
                    }
                    break
        row = SettingSuggestion(
            book_id=book_id,
            kind="review",
            target_type=target_type,
            target_id=target_id,
            title=f"【{issue.kind}】{issue.title}",
            payload=payload,
        )
        session.add(row)
        suggestions.append(row)
    await say(session, redis, book_id, "reviewer", result.note if result.issues else "查过了，没发现问题。")
    return {"suggestions": [SuggestionOut.model_validate(row) for row in suggestions], "note": result.note}


@router.post("/books/{book_id}/library/review")
async def review(
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    return await review_library(session, redis, book)


@router.post("/books/{book_id}/library/check")
async def check(
    body: CheckIn,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    return await review_library(session, redis, book, body)
