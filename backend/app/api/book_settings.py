import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, ensure_book_not_teardown, ensure_not_teardown, get_book, get_redis
from app.book_settings import BookSettings, compile_rules, default_settings, merge_settings, settings_of
from app.models import AppSetting, AuthorRequirement, Book, Chapter, Job, MeetingMessage
from app.services import jobs
from app.services.meeting import post_message
from app.services.requirements import add_requirement, requirement_states, set_scope, suppress_legacy_text

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    settings: BookSettings
    rules_text: str


class RequirementIn(BaseModel):
    scope: Literal["always", "next_chapter", "this_volume", "next_volume"] = "always"
    message_id: int | None = None
    source: str = Field(default="manual", pattern=r"^(manual|chat:(chief|lorekeeper|writer|reviewer))$")
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("要求不能为空")
        return text.strip()


class RequirementPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    scope: Literal["always", "next_chapter", "this_volume", "next_volume"] | None = None

    @field_validator("text")
    @classmethod
    def not_blank(cls, text):
        if text is not None and not text.strip():
            raise ValueError("要求不能为空")
        return text.strip() if text is not None else None


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    text: str
    source: str
    scope: str
    chapter_index: int | None
    volume_index: int | None
    active: bool
    label: str
    message_id: int | None
    created_at: datetime
    updated_at: datetime


def result(settings: dict, *, title: bool = False) -> SettingsOut:
    # 书名规矩只在起书名时带：新书默认里有，已经建好的书没有
    return SettingsOut(settings=BookSettings.model_validate(settings), rules_text=compile_rules(settings, title=title))


def validated(current: dict, body: dict) -> dict:
    try:
        return merge_settings(current, body)
    except ValidationError as error:
        raise HTTPException(422, error.errors(include_context=False)) from error


async def new_book_defaults(session: AsyncSession) -> dict:
    row = await session.get(AppSetting, "new_book_defaults")
    return {**default_settings(), **(row.value if row else {})}


@router.get("/settings/new-book-defaults", response_model=SettingsOut)
async def get_defaults(session: AsyncSession = SessionDep):
    return result(await new_book_defaults(session), title=True)


@router.put("/settings/new-book-defaults", response_model=SettingsOut)
async def put_defaults(body: dict, session: AsyncSession = SessionDep):
    values = validated(await new_book_defaults(session), body)
    row = await session.get(AppSetting, "new_book_defaults")
    if row is None:
        session.add(AppSetting(key="new_book_defaults", value=values))
    else:
        row.value = values
    await session.commit()
    return result(values, title=True)


@router.get("/books/{book_id}/settings", response_model=SettingsOut)
async def get_settings(book: Book = Depends(get_book)):
    return result(settings_of(book))


LABELS = {
    "setup_mode": "开书方式",
    "title_style": "书名风格",
    "title_custom": "书名要求",
    "person": "人称",
    "intimacy": "亲密戏",
    "intimacy_custom": "亲密戏要求",
    "chapter_words": "每章字数",
    "other_rules": "其他规矩",
    "playbook": "题材打法",
    "effort_preset": "编辑部力度",
    "max_rewrites": "最多重写次数",
    "pitches": "卷纲方案数",
    "review_strictness": "审稿松紧",
    "volume_audit": "卷纲专项审稿",
    "volume_approval": "每卷卷纲拍板",
    "chapters_approval": "每个单元的章纲都给我看",
    "segment_approval": "每一篇开写前先给我确认",
    "trial_read": "前 3 章试读",
}
VALUES = {
    "oneshot": "一口气出方案",
    "puzzle": "逐块确认",
    "short": "经典短书名",
    "tomato": "番茄长书名",
    "chief": "交给主编",
    "custom": "自己写 / 自定义",
    "first": "第一人称",
    "second": "第二人称",
    "third": "第三人称",
    "heart": "只写心动",
    "fade": "点到为止",
    "quick": "省时",
    "balanced": "均衡",
    "premium": "精品",
    "lenient": "宽松",
    "standard": "标准",
    "strict": "严格",
    "auto": "自动匹配",
    "harem_xuanhuan": "后宫玄幻爽文",
    "general": "通用",
}


def change_summary(before: dict, after: dict) -> str:
    def display(value):
        if isinstance(value, bool):
            return "打开" if value else "关闭"
        if value is None or value == "":
            return "留空"
        return VALUES.get(str(value), str(value))

    return "；".join(f"{LABELS[k]}：{display(v)}" for k, v in after.items() if before.get(k) != v)


@router.patch("/books/{book_id}/settings", response_model=SettingsOut)
async def patch_settings(
    body: dict, book: Book = Depends(get_book), session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)
):
    # Live editing is explicitly allowed while workers are running; lock only this short transaction.
    ensure_not_teardown(book, "改本书设置")
    await session.refresh(book, attribute_names=["settings"], with_for_update=True)
    before = settings_of(book)
    values = validated(before, body)
    if values["setup_mode"] != before["setup_mode"] and await session.scalar(
        select(Job.id).where(Job.book_id == book.id, Job.kind == "book_setup").limit(1)
    ):
        raise HTTPException(409, "开书任务已经开始，不能切换开书方式")
    book.settings = values
    changed = change_summary(before, values)
    job = await jobs.active_job(session, book.id)
    if changed and job and job.status in jobs.ACTIVE_STATUSES:
        if job.kind == "book_setup":
            await post_message(
                session,
                redis,
                book_id=book.id,
                job_id=job.id,
                speaker="author",
                kind="note",
                content=f"（作者修改了写作规矩）{changed}",
                payload={"settings_change": True},
            )
        elif job.kind in ("write_book", "rewrite_chapter"):
            await post_message(
                session,
                redis,
                book_id=book.id,
                job_id=job.id,
                speaker="system",
                kind="status",
                content=f"作者修改了本书设置：{changed}",
            )
    await session.commit()
    return result(values)


@router.get("/books/{book_id}/requirements", response_model=list[RequirementOut])
async def get_requirements(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return await requirement_outputs(session, book.id)


@router.post("/books/{book_id}/requirements", response_model=RequirementOut, status_code=201)
async def post_requirement(
    body: RequirementIn,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    ensure_not_teardown(book, "加写作要求")
    message = await session.get(MeetingMessage, body.message_id) if body.message_id else None
    if body.message_id and (
        message is None
        or message.book_id != book.id
        or message.speaker != "author"
        or (message.payload or {}).get("thread")
    ):
        raise HTTPException(422, "请选择这本书的群聊消息")
    row = await add_requirement(session, book.id, body.text, body.source, body.scope, body.message_id)
    if message:
        message.payload = {
            **(message.payload or {}),
            "requirement_saved": True,
            "outcome": {"kind": "requirement", "requirement_id": str(row.id)},
        }
    await session.commit()
    out = next(item for item in await requirement_outputs(session, book.id) if item["id"] == row.id)
    if body.source.startswith("chat:"):
        await post_message(
            session,
            redis,
            book_id=book.id,
            job_id=None,
            speaker="system",
            kind="decision",
            content=f"加了一条写作要求：「{row.text}」（{out['label']}）",
            payload={"thread": body.source.split(":", 1)[1]},
        )
    if message:
        from app.services.meeting import message_dict, publish

        await publish(redis, book.id, "message_update", message_dict(message))
    return out


async def requirement(session: AsyncSession, requirement_id: uuid.UUID) -> AuthorRequirement:
    row = await session.get(AuthorRequirement, requirement_id)
    if row is None:
        raise HTTPException(404, "作者要求不存在")
    return row


@router.patch("/requirements/{requirement_id}", response_model=RequirementOut)
async def patch_requirement(requirement_id: uuid.UUID, body: RequirementPatch, session: AsyncSession = SessionDep):
    row = await requirement(session, requirement_id)
    await ensure_book_not_teardown(session, row.book_id, "加写作要求")
    text = body.text if body.text is not None else row.text
    await session.execute(select(Book.id).where(Book.id == row.book_id).with_for_update())
    duplicate = await session.scalar(
        select(AuthorRequirement.id).where(
            AuthorRequirement.book_id == row.book_id,
            AuthorRequirement.text == text,
            AuthorRequirement.id != row.id,
        )
    )
    if duplicate:
        raise HTTPException(409, "这条要求已经存在")
    if row.text != text:
        await suppress_legacy_text(session, row.book_id, row.text)
    row.text = text
    if body.scope is not None:
        await set_scope(session, row, body.scope)
    await session.commit()
    return next(item for item in await requirement_outputs(session, row.book_id) if item["id"] == row.id)


@router.delete("/requirements/{requirement_id}", status_code=204)
async def delete_requirement(requirement_id: uuid.UUID, session: AsyncSession = SessionDep):
    row = await requirement(session, requirement_id)
    await ensure_book_not_teardown(session, row.book_id, "加写作要求")
    await suppress_legacy_text(session, row.book_id, row.text)
    await session.delete(row)
    await session.commit()


async def requirement_outputs(session, book_id):
    return [
        {
            **{
                key: getattr(item["row"], key)
                for key in (
                    "id",
                    "book_id",
                    "text",
                    "source",
                    "scope",
                    "chapter_index",
                    "volume_index",
                    "message_id",
                    "created_at",
                    "updated_at",
                )
            },
            "active": item["active"],
            "label": item["label"],
        }
        for item in await requirement_states(session, book_id)
    ]


def source_label(source):
    from app.services.meeting import SPEAKER_NAMES

    if source.startswith("private:"):
        return "私聊" + SPEAKER_NAMES.get(source[8:], source[8:])
    if source.startswith("chat:"):
        return "和" + SPEAKER_NAMES.get(source[5:], source[5:]) + "聊天时记下"
    prefix, _, value = source.partition(":")
    return {
        "note": "群聊",
        "answer": "开书时的回答",
        "volume": f"第 {value} 卷卷纲的意见",
        "segment": f"定下第 {value} 篇时的意见",
        "unit": "单元章纲的意见",
        "trial": "试读意见",
        "manual": "手动添加",
    }.get(prefix, "其他")


@router.post("/books/{book_id}/requirements/tidy")
async def tidy_requirements(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    ensure_not_teardown(book, "加写作要求")
    from app.agents.schemas import RequirementsTidy
    from app.services.chat import model
    from app.services.chat_context import progress_of
    from app.services.library_context import load_context

    book_id = book.id
    ctx = await load_context(session, book)
    items = [item for item in await requirement_outputs(session, book_id) if item["active"]]
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index)))
    job = await jobs.active_job(session, book_id)
    values = dict(
        concept=ctx.concept,
        progress=await progress_of(session, ctx, chapters, job),
        requirements="\n".join(
            f"{i}. {item['text']}（{item['label']}；来自{source_label(item['source'])}）"
            for i, item in enumerate(items, 1)
        )
        or "（没有）",
    )
    await session.commit()
    try:
        result = await model(book_id, "chief", RequirementsTidy, "requirements_tidy", **values)
    except Exception as exc:
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    by_index = {item.index: item for item in result.items}
    return {
        "items": [
            {
                "id": item["id"],
                "text": item["text"],
                "action": by_index[i].action if i in by_index else "保留",
                "reason": by_index[i].reason if i in by_index else "主编没有建议改这一条",
                "rewrite": by_index[i].rewrite if i in by_index else "",
            }
            for i, item in enumerate(items, 1)
        ]
    }


class RequirementRewrite(BaseModel):
    id: uuid.UUID
    text: str = Field(min_length=1, max_length=20000)


class RequirementsApply(BaseModel):
    delete: list[uuid.UUID] = Field(default_factory=list)
    rewrite: list[RequirementRewrite] = Field(default_factory=list)


@router.post("/books/{book_id}/requirements/apply", response_model=list[RequirementOut])
async def apply_requirements(
    body: RequirementsApply, book: Book = Depends(get_book), session: AsyncSession = SessionDep
):
    ensure_not_teardown(book, "加写作要求")
    await session.execute(select(Book.id).where(Book.id == book.id).with_for_update())
    ids = {*body.delete, *(r.id for r in body.rewrite)}
    rows = {
        r.id: r for r in await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == book.id))
    }
    if not ids.issubset(rows):
        raise HTTPException(409, "要求清单已经变了，重新整理一下")
    if set(body.delete) & {r.id for r in body.rewrite}:
        raise HTTPException(422, "不能同时删掉和改写同一条")
    future = [r.text.strip() for r in body.rewrite]
    kept = {r.text for r in rows.values() if r.id not in ids}
    if any(not text for text in future) or len(set(future)) != len(future) or set(future) & kept:
        raise HTTPException(409, "改写后的要求为空或重复")
    for id in body.delete:
        await suppress_legacy_text(session, book.id, rows[id].text)
        await session.delete(rows[id])
    for item in body.rewrite:
        await suppress_legacy_text(session, book.id, rows[item.id].text)
        rows[item.id].text = item.text.strip()
    await session.commit()
    return await requirement_outputs(session, book.id)
