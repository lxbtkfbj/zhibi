"""联网搜索密钥归属在模型配置的列表、新建和修改响应中保持一致。"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.crypto import encrypt
from app.main import create_app
from app.models import LlmProfile


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


def profile(name, *, created_at, id=None, **changes):
    return LlmProfile(
        **{
            "id": id or uuid.uuid4(),
            "name": name,
            "provider": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash",
            "api_key_encrypted": encrypt("fake-web-search-key"),
            "created_at": created_at,
            **changes,
        }
    )


async def test_list_only_marks_earliest_eligible_profile_with_id_tiebreak(client, sessionmaker):
    created_at = datetime(2026, 10, 24, tzinfo=UTC)
    older = created_at - timedelta(days=1)
    rows = [
        profile("较晚创建", created_at=created_at + timedelta(seconds=1), id=uuid.UUID(int=1)),
        profile("同日较大id", created_at=created_at, id=uuid.UUID(int=3)),
        profile("官方DeepSeek", created_at=created_at, id=uuid.UUID(int=2), base_url="https://api.deepseek.com"),
        profile("没有密钥", created_at=older, api_key_encrypted=None),
        profile("别的主机", created_at=older, base_url="https://api.deepseek.com.example/v1"),
        profile("演示模式", created_at=older, provider="demo"),
    ]
    async with sessionmaker() as session:
        session.add_all(rows)
        await session.commit()

    response = await client.get("/api/llm/profiles")
    assert response.status_code == 200
    data = response.json()
    assert {item["name"]: item["web_search"] for item in data} == {row.name: row.name == "官方DeepSeek" for row in rows}
    assert all("api_key" not in item and "api_key_encrypted" not in item for item in data)
    assert "fake-web-search-key" not in response.text


async def test_create_returns_selected_flag_for_only_first_official_key(client):
    bodies = [
        {"name": "演示模式", "provider": "demo"},
        {
            "name": "官方DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-flash",
            "api_key": "fake-first",
        },
        {
            "name": "另一套官方",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-flash",
            "api_key": "fake-second",
        },
    ]
    for body, selected in zip(bodies, [False, True, False], strict=True):
        response = await client.post("/api/llm/profiles", json=body)
        assert response.status_code == 201
        assert response.json()["web_search"] is selected
    data = (await client.get("/api/llm/profiles")).json()
    assert [item["name"] for item in data if item["web_search"]] == ["官方DeepSeek"]


async def test_update_response_recalculates_selection_after_key_and_host_changes(client, sessionmaker):
    created_at = datetime(2026, 10, 24, tzinfo=UTC)
    oldest = profile("最早但没密钥", created_at=created_at, api_key_encrypted=None)
    newer = profile("后建官方", created_at=created_at + timedelta(days=1))
    async with sessionmaker() as session:
        session.add_all([oldest, newer])
        await session.commit()

    data = (await client.get("/api/llm/profiles")).json()
    assert [item["id"] for item in data if item["web_search"]] == [str(newer.id)]
    response = await client.patch(f"/api/llm/profiles/{oldest.id}", json={"api_key": "fake-now-available"})
    assert response.status_code == 200
    assert response.json()["web_search"] is True
    response = await client.patch(f"/api/llm/profiles/{newer.id}", json={"name": "后建官方改名"})
    assert response.json()["web_search"] is False
    response = await client.patch(f"/api/llm/profiles/{oldest.id}", json={"base_url": "https://proxy.example/v1"})
    assert response.json()["web_search"] is False
    data = (await client.get("/api/llm/profiles")).json()
    assert [item["id"] for item in data if item["web_search"]] == [str(newer.id)]


async def test_unreadable_selected_key_leaves_every_profile_unmarked(client, sessionmaker):
    created_at = datetime(2026, 10, 24, tzinfo=UTC)
    first = profile("密钥损坏", created_at=created_at, api_key_encrypted="not-an-encrypted-key")
    second = profile("较晚配置", created_at=created_at + timedelta(days=1))
    async with sessionmaker() as session:
        session.add_all([first, second])
        await session.commit()

    response = await client.get("/api/llm/profiles")
    assert response.status_code == 200
    assert not any(item["web_search"] for item in response.json())
    response = await client.patch(f"/api/llm/profiles/{first.id}", json={"name": "仍然读不开"})
    assert response.status_code == 200
    assert response.json()["web_search"] is False
