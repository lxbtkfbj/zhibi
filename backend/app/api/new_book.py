"""新建页：类别标签选项，和作者叫了才动的「按点子起草」「按意见改」。都不建书。"""

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.editorial import draft_book
from app.api.book_settings import new_book_defaults
from app.api.deps import SessionDep
from app.book_meta import CHANNEL_KEYS, CHANNELS, DEFAULT_CHAPTER_WORDS, MAX_TAGS, catalog_text, channel_of
from app.book_settings import compile_rules
from app.db import get_sessionmaker
from app.llm.router import LLMRouter
from app.schemas import BookDraftFields, BookDraftIn, BookDraftOut

router = APIRouter(tags=["new-book"])


@router.get("/book-meta")
async def book_meta(session: AsyncSession = SessionDep) -> dict:
    defaults = await new_book_defaults(session)
    return {
        "channels": CHANNELS,
        "chapter_words": defaults.get("chapter_words") or DEFAULT_CHAPTER_WORDS,
        "max_tags": MAX_TAGS,
    }


def format_current(fields: BookDraftFields) -> str:
    rows = [
        ("书名", fields.title),
        ("简介", fields.blurb),
        ("频道", fields.channel),
        ("类别", fields.genre),
        ("标签", "、".join(fields.tags)),
        ("篇幅", f"{fields.target_length} 万字" if fields.target_length else ""),
    ]
    return "\n".join(f"{label}：{value or '（空着）'}" for label, value in rows)


def tidy(result) -> BookDraftOut:
    """模型交回的只当建议：去掉书名号，类别和频道对齐，标签去重限量，篇幅夹在范围里。"""
    genre = result.genre.strip()[:100]
    channel = channel_of(genre) or (result.channel if result.channel in CHANNEL_KEYS else "")
    tags = list(dict.fromkeys(tag.strip()[:20] for tag in result.tags if tag.strip()))[:MAX_TAGS]
    return BookDraftOut(
        title=result.title.strip().strip("《》").strip()[:200],
        blurb=result.blurb.strip()[:5000],
        channel=channel,
        genre=genre,
        tags=tags,
        target_length=min(max(result.target_length, 1), 5000),
        reply=result.reply.strip(),
    )


@router.post("/book-drafts", response_model=BookDraftOut)
async def draft(body: BookDraftIn, session: AsyncSession = SessionDep) -> BookDraftOut:
    defaults = await new_book_defaults(session)
    revising = bool(body.feedback.strip())
    blocks = {
        "idea": body.idea.strip() or "（作者没写点子，按下面现在的样子来）",
        "catalog": catalog_text(),
        "requirements": compile_rules(defaults),
        "revision": (
            f"【新建页上现在的样子】\n{format_current(body.current)}\n\n【作者的意见】\n{body.feedback.strip()}"
            if revising
            else ""
        ),
        "mode_rule": (
            "8. 这次是按作者的意见改：只改作者说到的地方；作者没提的项照【新建页上现在的样子】原样交回，"
            "一个字不动，空着的也照样空着（篇幅空着就写 200）。reply 说清这次改了哪里。"
            if revising
            else ""
        ),
    }
    llm = LLMRouter(get_sessionmaker())
    try:
        result = await draft_book(llm, blocks)
    except Exception as exc:
        raise HTTPException(502, f"模型出错了：{exc}") from exc
    finally:
        await llm.aclose()
    out = tidy(result)
    if revising and body.current and not body.current.target_length and "篇幅" not in body.feedback:
        # 作者没碰篇幅、页面上也空着，就别替作者填上
        out.target_length = None
    return out
