"""联网搜索的密钥在系统设置里单独存：存、清、测试，不再挂在模型配置上；升级时抄一份旧的。"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql

from alembic import command
from app.crypto import decrypt, encrypt
from app.llm import web_search
from app.main import create_app
from app.models import AppSetting, LlmProfile


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


@pytest.fixture
def tried(monkeypatch):
    keys = []

    async def fake(api_key):
        keys.append(api_key)
        return True, "能搜：假的"

    monkeypatch.setattr(web_search, "try_key", fake)
    return keys


async def test_save_clear_and_profiles_no_longer_carry_the_flag(client, sessionmaker):
    async with sessionmaker() as session:
        session.add(
            LlmProfile(
                name="官方DeepSeek",
                provider="openai_compatible",
                base_url="https://api.deepseek.com/v1",
                api_key_encrypted=encrypt("profile-key"),
                model="deepseek-flash",
            )
        )
        await session.commit()
    assert (await client.get("/api/llm/web-search")).json() == {"has_key": False}
    profiles = (await client.get("/api/llm/profiles")).json()
    assert all("web_search" not in item for item in profiles)

    assert (await client.put("/api/llm/web-search", json={"api_key": "   "})).status_code == 422
    response = await client.put("/api/llm/web-search", json={"api_key": " fake-search-key "})
    assert response.status_code == 200 and response.json() == {"has_key": True}
    assert "fake-search-key" not in response.text
    assert (await client.get("/api/llm/web-search")).json() == {"has_key": True}
    async with sessionmaker() as session:
        row = await session.get(AppSetting, web_search.SETTING)
        assert set(row.value) == {"api_key_encrypted"}
        assert "fake-search-key" not in row.value["api_key_encrypted"]
        assert decrypt(row.value["api_key_encrypted"]) == "fake-search-key"
        assert await web_search.load_key(session) == web_search.SearchKey("fake-search-key")

    response = await client.put("/api/llm/web-search", json={"api_key": "fake-second"})
    assert response.json() == {"has_key": True}
    async with sessionmaker() as session:
        assert (await web_search.load_key(session)).api_key == "fake-second"

    assert (await client.delete("/api/llm/web-search")).json() == {"has_key": False}
    assert (await client.delete("/api/llm/web-search")).json() == {"has_key": False}
    assert (await client.get("/api/llm/web-search")).json() == {"has_key": False}
    async with sessionmaker() as session:
        assert await web_search.load_key(session) is None


async def test_test_uses_typed_key_first_then_saved_one(client, sessionmaker, tried):
    response = await client.post("/api/llm/web-search/test", json={})
    assert response.json() == {"ok": False, "message": "还没填 API Key", "tools": None, "tools_message": ""}
    assert tried == []

    await client.put("/api/llm/web-search", json={"api_key": "saved-key"})
    assert (await client.post("/api/llm/web-search/test", json={"api_key": " typed-key "})).json()["ok"] is True
    assert (await client.post("/api/llm/web-search/test", json={"api_key": ""})).json()["message"] == "能搜：假的"
    assert tried == ["typed-key", "saved-key"]
    async with sessionmaker() as session:
        assert (await web_search.load_key(session)).api_key == "saved-key"

    async with sessionmaker() as session:
        (await session.get(AppSetting, web_search.SETTING)).value = {"api_key_encrypted": "broken"}
        await session.commit()
    response = await client.post("/api/llm/web-search/test", json={})
    assert response.json()["message"] == "已保存的 API Key 无法读取，请重新填写"
    assert (await client.get("/api/llm/web-search")).json() == {"has_key": True}
    assert tried == ["typed-key", "saved-key"]


@contextmanager
def database_at_0028(migration_database_urls):
    name = f"zhibi_web_search_key_test_{uuid.uuid4().hex}"
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0028")
        yield config, engine
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def add_profile(
    connection, name, created_at, *, url="https://api.deepseek.com/v1", key="", provider="openai_compatible"
):
    connection.execute(
        sa.text(
            "INSERT INTO llm_profiles (id, name, provider, base_url, api_key_encrypted, model, temperature, "
            "structured_method, timeout_s, created_at, updated_at) VALUES (:id, :name, :provider, :url, :key, 'm', "
            "0.8, 'function_calling', 300, :created_at, :created_at)"
        ),
        {
            "id": uuid.uuid4(),
            "name": name,
            "provider": provider,
            "url": url,
            "key": key or None,
            "created_at": created_at,
        },
    )


def web_search_row(engine):
    with engine.connect() as connection:
        return connection.execute(sa.text("SELECT value FROM app_settings WHERE key = 'web_search'")).scalar()


def test_upgrade_copies_the_key_search_used_to_borrow(migration_database_urls):
    day = datetime(2026, 10, 24, tzinfo=UTC)
    with database_at_0028(migration_database_urls) as (config, engine):
        with engine.begin() as connection:
            add_profile(connection, "演示", day - timedelta(days=9), provider="demo", key="demo-token")
            add_profile(
                connection, "别的主机", day - timedelta(days=8), url="https://api.deepseek.com.example/v1", key="other"
            )
            add_profile(connection, "没密钥", day - timedelta(days=7))
            add_profile(connection, "后建官方", day + timedelta(days=1), url="https://api.deepseek.com", key="later")
            add_profile(connection, "最早的官方", day, key="earliest")
        command.upgrade(config, "0029")
        assert web_search_row(engine) == {"api_key_encrypted": "earliest"}
        command.downgrade(config, "0028")
        assert web_search_row(engine) is None


def test_upgrade_without_deepseek_profile_leaves_search_off(migration_database_urls):
    with database_at_0028(migration_database_urls) as (config, engine):
        with engine.begin() as connection:
            add_profile(connection, "gemini", datetime(2026, 1, 1, tzinfo=UTC), url="https://relay.example/v1", key="k")
        command.upgrade(config, "0029")
        assert web_search_row(engine) is None
