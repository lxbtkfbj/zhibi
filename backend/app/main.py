import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import select

from app.api import (
    bible,
    book_settings,
    books,
    chat,
    health,
    jobs,
    library,
    library_ai,
    llm_settings,
    new_book,
    outline_expand,
    outline_tree,
    prompt_tools,
    saves,
    story_map,
    teardown,
    workspace,
)
from app.config import get_settings
from app.crypto import encrypt
from app.db import dispose_engine, get_sessionmaker
from app.models import LlmProfile, RoleAssignment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def seed_default_profile() -> None:
    """首次启动时，如果配置了 ZHIBI_DEFAULT_LLM_*，自动创建默认模型配置。"""
    settings = get_settings()
    if not (settings.default_llm_base_url and settings.default_llm_model):
        return
    async with get_sessionmaker()() as session:
        if await session.scalar(select(LlmProfile.id).limit(1)):
            return
        profile = LlmProfile(
            name="默认模型",
            base_url=settings.default_llm_base_url,
            model=settings.default_llm_model,
            api_key_encrypted=encrypt(settings.default_llm_api_key) if settings.default_llm_api_key else None,
        )
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    await seed_default_profile()
    from app.services.chat import clean_live_replies
    from app.services.group_notes import clean_pending

    await clean_pending(application.state.redis)
    await clean_live_replies(application.state.redis)
    yield
    await application.state.redis.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(title="执笔 API", version="0.1.0", lifespan=lifespan)
    for module in (
        health,
        llm_settings,
        books,
        chat,
        bible,
        jobs,
        book_settings,
        prompt_tools,
        story_map,
        library,
        library_ai,
        outline_tree,
        outline_expand,
        new_book,
        workspace,
        saves,
        teardown,
    ):
        application.include_router(module.router, prefix="/api")
    return application


app = create_app()
