"""设定库的请求内 AI 操作：模型只交回局部文字，程序负责合回与版本。"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import library_config as config
from app.agents import schemas as s
from app.agents.context import format_requirements
from app.agents.editorial import persona
from app.api.deps import SessionDep, ensure_idle, get_book, get_redis
from app.api.library import _splice_error, _validate_changed_target
from app.db import get_sessionmaker
from app.library_schemas import CandidateOut, SuggestionOut
from app.llm.router import LLMRouter
from app.models import Book, Character, Job, SettingCandidate, SettingSuggestion, WorldEntry
from app.prompts import render
from app.services.library import ensure_unlocked, load_target, lock_book
from app.services.library_cascade import generate_cascade_suggestions, iter_text_paths
from app.services.library_context import load_context, rewrite_mode
from app.services.meeting import post_message
from app.services.requirements import active_requirements, requirement_text
from app.services.splice import STALE_TEXT, read_path, splice
from app.services.versions import previous_version_id, record_version, snapshot_of, target_type_of

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
    # 新书页上选中文字改：结果就地给作者看，不在群聊里再说一遍
    quiet: bool = False
    # 选中的原字：页面算的位置和存下的字对不上时（比如刚改完还没存好），按它重新找；找不到就不改
    quote: str = ""


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["entry", "character"]
    target_id: uuid.UUID


async def call_model(book_id, role, schema, template, *, single_attempt=False, **values):
    """每个请求独占客户端；不在模型调用期间持有书锁（调用日志也会锁书）。"""
    llm = LLMRouter(get_sessionmaker(), book_id=book_id)
    try:
        try:
            return await llm.structured(
                role,
                schema,
                persona("chief" if role == "router" else role),
                render(template, **values),
                purpose="群聊分流" if template == "library_route" else template,
                **({"max_attempts": 1} if single_attempt else {}),
            )
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


async def rewrite_target(
    session,
    redis,
    book,
    body: RewriteIn,
    *,
    require_idle=False,
    allow_waiting=False,
    require_unwritten=False,
    single_attempt=False,
):
    if body.mode == "instruction" and not body.instruction.strip():
        raise HTTPException(422, "先写一句你想怎么改")
    book_id = book.id
    target = await load_target(session, book_id, body.target_type, body.target_id)
    _unlocked(target)
    if require_unwritten:
        from app.services.library import ensure_unwritten

        await ensure_unwritten(session, target)
    try:
        current = read_path(target, body.path)
        if not isinstance(current, str):
            raise ValueError("这一处不是文字，不能替换")
        if body.quote and "@" in body.path and current != body.quote:
            field = body.path.rsplit("@", 1)[0]
            start = str(read_path(target, field)).find(body.quote)
            if start < 0:
                raise ValueError(STALE_TEXT)
            body.path, current = f"{field}@{start}:{start + len(body.quote)}", body.quote
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
        **({"single_attempt": True} if single_attempt else {}),
        **values,
    )
    await lock_book(session, book_id)
    if require_idle:
        await ensure_idle(session, book_id)
        if not allow_waiting and await session.scalar(
            select(Job.id)
            .where(
                Job.book_id == book_id,
                Job.status == "waiting_author",
                Job.pending["kind"].astext.not_in(["setup_prefill", "setup_pitches"]),
            )
            .limit(1)
        ):
            # 作者消息已保存；不要返回 use_feedback，避免前端把同一句再交一次。
            raise HTTPException(409, "编辑部状态变了，请刷新后再改")
    target = await load_target(session, book_id, body.target_type, body.target_id, for_update=True)
    _unlocked(target)
    if require_unwritten:
        await ensure_unwritten(session, target)
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
        if body.quiet:
            await session.commit()
        else:
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
        revert_version_id = await previous_version_id(session, body.target_type, target.id)
        if body.quiet:
            await session.commit()
        else:
            await say(session, redis, book_id, "lorekeeper", f"{verb}「{name}」的{part}。")
    except ValueError as exc:
        raise _splice_error(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "修改后的名称重复或引用已不存在") from exc
    response = {
        "applied": {"path": body.path, "before": old, "after": new},
        "version": version.version,
        "revert_version_id": revert_version_id,
        "suggestions": [SuggestionOut.model_validate(row) for row in suggestions],
    }
    if isinstance(target, Book) and body.path.split("@", 1)[0] == "story":
        await review_concept_change(
            session, redis, book_id, before.get("story", ""), **({"single_attempt": True} if single_attempt else {})
        )
    return response


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
    requirements = await active_requirements(session, book_id)
    values = dict(
        concept=ctx.concept,
        library=ctx.library,
        genre_defaults=ctx.genre_defaults,
        requirements=format_requirements([requirement_text(row) for row in requirements], [], book.settings),
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


async def review_library(
    session,
    redis,
    book,
    check: CheckIn | None = None,
    *,
    scope: str | None = None,
    kind: str = "review",
    single_attempt=False,
):
    book_id = book.id
    ctx = await load_context(session, book)
    scope = scope or "查整个设定库。"
    if check:
        target = await load_target(session, book_id, check.target_type, check.target_id)
        scope = f"只查这一条：{ctx.target_heading(target)}；需要时对照别的条目。"
    values = dict(concept=ctx.concept, library_full=ctx.library_full, outline=ctx.outline, scope=scope)
    await session.rollback()
    result = await call_model(
        book_id,
        "reviewer",
        s.LibraryReview,
        "library_review",
        **({"single_attempt": True} if single_attempt else {}),
        **values,
    )
    await lock_book(session, book_id)
    book = await session.get(Book, book_id)
    ctx = await load_context(session, book)
    suggestions = []
    for issue in result.issues:
        target = next(
            (
                row
                for row in [*ctx.characters, *ctx.entries, *ctx.nodes, *ctx.volumes, *ctx.units]
                if ctx.target_name(row) == issue.target_name
            ),
            None,
        )
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
            kind=kind,
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


async def review_concept_change(session, redis, book_id, old_story: str, *, single_attempt=False) -> None:
    book = await session.get(Book, book_id)
    new_story = (book.concept or {}).get("story", "")
    if old_story == new_story:
        return
    built = await session.scalar(
        select(WorldEntry.id).where(WorldEntry.book_id == book_id, ~WorldEntry.tags.contains(["底牌"])).limit(1)
    )
    if built is None:
        built = await session.scalar(select(Character.id).where(Character.book_id == book_id).limit(1))
    if built is None:
        return
    scope = f"定调改了。\n改之前：{old_story}\n改之后：{new_story}\n查设定库和大纲里哪些地方要跟着改。"
    await session.commit()
    try:
        await review_library(
            session, redis, book, scope=scope, kind="concept", **({"single_attempt": True} if single_attempt else {})
        )
    except HTTPException as exc:
        if exc.status_code != 502:
            raise
        # The edit and its version have already committed. A failed follow-up
        # review must not turn an undoable successful edit into a false failure.
        await session.rollback()
        warning = f"定调已经改好了，但连带检查没做成：{exc.detail}。可以稍后在设定库点「全部查一遍」。"
        session.add(
            SettingSuggestion(
                book_id=book_id, kind="concept", title=warning, payload={"op": "note", "content": warning}
            )
        )
        await say(session, redis, book_id, "reviewer", warning)
