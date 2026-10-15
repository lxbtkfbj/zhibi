import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_book, get_redis
from app.book_settings import BookSettings, compile_rules, default_settings, merge_settings, settings_of
from app.models import AppSetting, AuthorRequirement, Book, Job
from app.services import jobs
from app.services.meeting import post_message
from app.services.requirements import add_requirement, list_requirements, suppress_legacy_text

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    settings: BookSettings
    rules_text: str


class RequirementIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, text: str) -> str:
        if not text.strip():
            raise ValueError("要求不能为空")
        return text.strip()


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    text: str
    source: str
    created_at: datetime
    updated_at: datetime


def result(settings: dict) -> SettingsOut:
    return SettingsOut(settings=BookSettings.model_validate(settings), rules_text=compile_rules(settings))


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
    return result(await new_book_defaults(session))


@router.put("/settings/new-book-defaults", response_model=SettingsOut)
async def put_defaults(body: dict, session: AsyncSession = SessionDep):
    values = validated(await new_book_defaults(session), body)
    row = await session.get(AppSetting, "new_book_defaults")
    if row is None:
        session.add(AppSetting(key="new_book_defaults", value=values))
    else:
        row.value = values
    await session.commit()
    return result(values)


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
    return await list_requirements(session, book.id)


@router.post("/books/{book_id}/requirements", response_model=RequirementOut, status_code=201)
async def post_requirement(body: RequirementIn, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    row = await add_requirement(session, book.id, body.text, "manual")
    await session.commit()
    await session.refresh(row)
    return row


async def requirement(session: AsyncSession, requirement_id: uuid.UUID) -> AuthorRequirement:
    row = await session.get(AuthorRequirement, requirement_id)
    if row is None:
        raise HTTPException(404, "作者要求不存在")
    return row


@router.patch("/requirements/{requirement_id}", response_model=RequirementOut)
async def patch_requirement(requirement_id: uuid.UUID, body: RequirementIn, session: AsyncSession = SessionDep):
    row = await requirement(session, requirement_id)
    await session.execute(select(Book.id).where(Book.id == row.book_id).with_for_update())
    duplicate = await session.scalar(
        select(AuthorRequirement.id).where(
            AuthorRequirement.book_id == row.book_id,
            AuthorRequirement.text == body.text,
            AuthorRequirement.id != row.id,
        )
    )
    if duplicate:
        raise HTTPException(409, "这条要求已经存在")
    if row.text != body.text:
        await suppress_legacy_text(session, row.book_id, row.text)
    row.text = body.text
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/requirements/{requirement_id}", status_code=204)
async def delete_requirement(requirement_id: uuid.UUID, session: AsyncSession = SessionDep):
    row = await requirement(session, requirement_id)
    await suppress_legacy_text(session, row.book_id, row.text)
    await session.delete(row)
    await session.commit()
