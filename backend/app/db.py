from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def make_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or get_settings().database_url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """API 进程共用的会话工厂。worker 每个任务在自己的事件循环里另建。"""
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = make_engine()
        _sessionmaker = make_sessionmaker(_engine)
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
