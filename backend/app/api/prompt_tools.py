"""全局提示词、逐次模型调用详情，以及跨书用量。"""

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.models import Book, LlmCall, PromptOverride
from app.prompts import VARIABLE, default_content
from app.prompts.catalog import entries, entry, validate_content, variables
from app.services.usage import sum_known, token_sum

router = APIRouter(tags=["prompts-and-calls"])


class PromptIn(BaseModel):
    content: str = Field(max_length=500_000)


def _entry(name: str) -> tuple:
    try:
        return entry(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


async def _last_calls(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            text("""
        SELECT DISTINCT ON (prompt_name) prompt_name, id, created_at
        FROM llm_calls
        CROSS JOIN LATERAL jsonb_array_elements_text(
            COALESCE(request->'prompt_names', '[]'::jsonb)
        ) AS names(prompt_name)
        ORDER BY prompt_name, id DESC
    """)
        )
    ).mappings()
    return {row["prompt_name"]: {"id": row["id"], "created_at": row["created_at"]} for row in rows}


async def _used_prompts(session: AsyncSession, request: dict | None) -> dict:
    request = request or {}
    names = request.get("prompt_names") or []
    parts = request.get("prompt_parts")
    contents = {row.name: row.content for row in await session.scalars(select(PromptOverride))}
    titles = {row[0]: row[1] for row in entries(contents)}

    def refs(items: list[str]) -> list[dict[str, str]]:
        return [{"name": name, "title": titles.get(name, name)} for name in items]

    return {
        "parts": {key: refs(parts.get(key) or []) for key in ("system", "user")} if parts is not None else None,
        "names": refs(names),
    }


async def _last_call(session: AsyncSession, name: str) -> dict | None:
    call = await session.scalar(
        select(LlmCall).where(LlmCall.request["prompt_names"].contains([name])).order_by(LlmCall.id.desc()).limit(1)
    )
    if call is None:
        return None
    return {
        "id": call.id,
        "created_at": call.created_at,
        "purpose": call.purpose,
        "used_prompts": await _used_prompts(session, call.request),
    }


def _meta(row: tuple, override: PromptOverride | None, last: dict | None) -> dict:
    name, title, group, role, when = row
    if name.startswith("skills.") and override is not None:
        from app.prompts.handbooks import parse

        _, title, group, role, when = parse(name.split(".", 1)[1], override.content).entry()
    default_variables = variables(name)
    current = set(VARIABLE.findall(override.content)) if override else {item["name"] for item in default_variables}
    default = {item["name"] for item in default_variables}
    return {
        "name": name,
        "title": title,
        "group": group,
        "role": role,
        "when": when,
        "customized": override is not None,
        "updated_at": override.updated_at if override else None,
        "last_call": last,
        "variables": default_variables,
        "default_changed": override is not None and current != default,
        "new_variables": [item for item in default_variables if item["name"] not in current],
    }


@router.get("/prompts")
async def list_prompts(session: AsyncSession = SessionDep) -> list[dict]:
    overrides = {row.name: row for row in (await session.scalars(select(PromptOverride))).all()}
    calls = await _last_calls(session)
    return [
        _meta(row, overrides.get(row[0]), calls.get(row[0]))
        for row in entries({name: row.content for name, row in overrides.items()})
    ]


@router.get("/prompts/{name:path}")
async def get_prompt(name: str, session: AsyncSession = SessionDep) -> dict:
    row = _entry(name)
    name = row[0]
    override = await session.get(PromptOverride, name)
    result = _meta(row, override, await _last_call(session, name))
    default = default_content(name)
    return {**result, "content": override.content if override is not None else default, "default_content": default}


@router.put("/prompts/{name:path}")
async def save_prompt(name: str, body: PromptIn, session: AsyncSession = SessionDep) -> dict:
    name = _entry(name)[0]
    if name.startswith("skills."):
        # 不同手册并发改名时也不能落下同名目录项。
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('zhibi:skill-names'))"))
    try:
        contents = {row.name: row.content for row in await session.scalars(select(PromptOverride))}
        validate_content(name, body.content, skill_contents=contents)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.execute(
        insert(PromptOverride)
        .values(name=name, content=body.content)
        .on_conflict_do_update(
            index_elements=[PromptOverride.name], set_={"content": body.content, "updated_at": func.now()}
        )
    )
    await session.commit()
    return await get_prompt(name, session)


@router.delete("/prompts/{name:path}")
async def restore_prompt(name: str, session: AsyncSession = SessionDep) -> dict:
    name = _entry(name)[0]
    if name.startswith("skills."):
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('zhibi:skill-names'))"))
        contents = {row.name: row.content for row in await session.scalars(select(PromptOverride))}
        try:
            validate_content(name, default_content(name), skill_contents=contents)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    row = await session.get(PromptOverride, name)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return await get_prompt(name, session)


CALL_COLUMNS = (
    "id",
    "book_id",
    "role",
    "purpose",
    "model",
    "profile_name",
    "prompt_tokens",
    "completion_tokens",
    "latency_ms",
    "ok",
    "error",
    "created_at",
)


def _calls_query(*, detail: bool = False):
    columns = (*CALL_COLUMNS, "request", "response") if detail else CALL_COLUMNS
    return select(
        *(getattr(LlmCall, key) for key in columns),
        func.coalesce(Book.title, "未关联书籍").label("book_title"),
    ).outerjoin(Book, LlmCall.book_id == Book.id)


@router.get("/llm-calls")
async def list_calls(
    book_id: uuid.UUID | None = None,
    role: str | None = None,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = SessionDep,
) -> dict:
    query = _calls_query()
    if book_id is not None:
        query = query.where(LlmCall.book_id == book_id)
    if role:
        query = query.where(LlmCall.role == role)
    if before is not None:
        query = query.where(LlmCall.id < before)
    rows = (await session.execute(query.order_by(LlmCall.id.desc()).limit(limit + 1))).mappings().all()
    return {
        "items": [dict(row) for row in rows[:limit]],
        "next_before": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


@router.get("/llm-calls/{call_id}")
async def get_call(call_id: int, session: AsyncSession = SessionDep) -> dict:
    row = (await session.execute(_calls_query(detail=True).where(LlmCall.id == call_id))).mappings().first()
    if row is None:
        raise HTTPException(404, "调用记录不存在")
    return {**row, "used_prompts": await _used_prompts(session, row["request"])}


@router.get("/usage")
async def usage(session: AsyncSession = SessionDep) -> dict:
    query = (
        select(
            LlmCall.book_id,
            func.coalesce(Book.title, "未关联书籍").label("book_title"),
            LlmCall.role,
            func.count(LlmCall.id).label("calls"),
            token_sum(LlmCall.prompt_tokens).label("prompt_tokens"),
            token_sum(LlmCall.completion_tokens).label("completion_tokens"),
        )
        .outerjoin(Book, LlmCall.book_id == Book.id)
        .group_by(
            LlmCall.book_id,
            Book.title,
            LlmCall.role,
        )
        .order_by(Book.title, LlmCall.role)
    )
    items = [dict(row) for row in (await session.execute(query)).mappings()]
    total = {key: sum_known(row[key] for row in items) for key in ("calls", "prompt_tokens", "completion_tokens")}
    # 按模型：花多少钱主要看用的是哪个模型（配置名、模型名都是调用当时记下的）
    by_model = [
        dict(row)
        for row in (
            await session.execute(
                select(
                    LlmCall.profile_name,
                    LlmCall.model,
                    func.count(LlmCall.id).label("calls"),
                    token_sum(LlmCall.prompt_tokens).label("prompt_tokens"),
                    token_sum(LlmCall.completion_tokens).label("completion_tokens"),
                )
                .group_by(LlmCall.profile_name, LlmCall.model)
                .order_by(func.count(LlmCall.id).desc())
            )
        ).mappings()
    ]
    return {"items": items, "total": total, "by_model": by_model}
