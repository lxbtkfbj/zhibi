import os

# 必须在导入 app 之前设置：测试使用独立的数据库和 Redis 库
TEST_DB = "zhibi_test"
os.environ["ZHIBI_DATABASE_URL"] = f"postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/{TEST_DB}"
os.environ["ZHIBI_REDIS_URL"] = "redis://127.0.0.1:6380/15"
os.environ["ZHIBI_SECRET_KEY"] = "kM0Y9jvXnS3cJ3i2c3Jt2v1yYF2n3tqQ5fWm5b7gk6E="

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app  # noqa: E402,F401
from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_sessionmaker  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    with psycopg.connect("postgresql://zhibi:zhibi@127.0.0.1:5433/zhibi", autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean_tables():
    sm = get_sessionmaker()
    async with sm() as session:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    redis = Redis.from_url(get_settings().redis_url)
    await redis.flushdb()
    await redis.aclose()
    yield


@pytest.fixture(scope="session", autouse=True)
async def _dispose():
    yield
    await dispose_engine()


@pytest.fixture
def sessionmaker():
    return get_sessionmaker()
