import os
import re

from sqlalchemy.engine import make_url

# 必须在导入 app 之前设置：测试使用独立的数据库和 Redis 库
TEST_DATABASE_URL = os.environ.get(
    "ZHIBI_TEST_DATABASE_URL", "postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/zhibi_test"
)
test_url = make_url(TEST_DATABASE_URL)
TEST_DB = test_url.database or ""
if test_url.drivername != "postgresql+psycopg" or not re.fullmatch(r"[a-z][a-z0-9_]*_test", TEST_DB):
    raise ValueError("测试数据库必须使用 postgresql+psycopg，库名须为小写字母开头且以 _test 结尾的测试专用名称")
TEST_ADMIN_URL = test_url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
os.environ["ZHIBI_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ZHIBI_REDIS_URL"] = os.environ.get("ZHIBI_TEST_REDIS_URL", "redis://127.0.0.1:6380/15")
os.environ["ZHIBI_SECRET_KEY"] = "kM0Y9jvXnS3cJ3i2c3Jt2v1yYF2n3tqQ5fWm5b7gk6E="

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from psycopg import sql  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app  # noqa: E402,F401
from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import dispose_engine, get_sessionmaker  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    with psycopg.connect(TEST_ADMIN_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
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


@pytest.fixture
def migration_database_urls():
    """迁移回归另建随机测试库，但必须留在显式指定的测试实例。"""

    def urls(name: str) -> tuple[str, str]:
        if not re.fullmatch(r"zhibi_[a-z_]+_test_[a-f0-9]{32}", name):
            raise ValueError("迁移测试库名必须带测试用途和随机 UUID")
        return TEST_ADMIN_URL, test_url.set(database=name).render_as_string(hide_password=False)

    return urls
