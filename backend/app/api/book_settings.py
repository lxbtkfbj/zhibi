from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, ensure_not_teardown, get_book, get_redis
from app.book_settings import BookSettings, compile_rules, default_settings, merge_settings, settings_of
from app.models import AppSetting, Book, Job
from app.services import jobs
from app.services.meeting import post_message

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    settings: BookSettings
    rules_text: str


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
