"""模型列表获取：未保存配置、凭据边界、只读性和安全错误提示。"""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.crypto import decrypt
from app.llm import discovery
from app.main import create_app
from app.models import LlmProfile


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


@pytest.fixture
def upstream(monkeypatch):
    requests = []
    options = []

    def install(handler):
        def record(request):
            requests.append(request)
            return handler(request)

        def factory(**kwargs):
            options.append(kwargs)
            return httpx.AsyncClient(transport=httpx.MockTransport(record), **kwargs)

        monkeypatch.setattr(discovery, "AsyncClient", factory)
        return requests, options

    return install


async def test_fetch_unsaved_models_normalizes_and_deduplicates_without_writes(client, upstream):
    requests, options = upstream(
        lambda _: httpx.Response(
            200,
            json={"data": [{"id": "zeta"}, {"id": " alpha "}, {"id": "zeta"}, {"id": ""}, {"id": 1}, None]},
        )
    )
    response = await client.post(
        "/api/llm/models", json={"base_url": " https://provider.test/v1/// ", "api_key": " sk-unsaved "}
    )
    assert response.status_code == 200
    assert response.json() == {"models": ["zeta", "alpha"]}
    assert str(requests[0].url) == "https://provider.test/v1/models"
    assert requests[0].headers["Authorization"] == "Bearer sk-unsaved"
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"].connect == 5
    assert options[0]["timeout"].read == 15
    assert (await client.get("/api/llm/profiles")).json() == []
    assert all(value is None for value in (await client.get("/api/llm/roles")).json().values())


async def test_keyless_local_provider_bypasses_proxy_and_empty_list_is_valid(client, upstream):
    requests, options = upstream(lambda _: httpx.Response(200, json={"data": []}))
    response = await client.post("/api/llm/models", json={"base_url": "http://localhost:11434/v1"})
    assert response.status_code == 200
    assert response.json() == {"models": []}
    assert "Authorization" not in requests[0].headers
    assert options[0]["trust_env"] is False


async def create_saved_profile(client, *, api_key="sk-saved"):
    response = await client.post(
        "/api/llm/profiles",
        json={"name": "已保存", "base_url": "https://provider.test/v1/", "model": "old-model", "api_key": api_key},
    )
    assert response.status_code == 201
    return response.json()


async def test_saved_key_is_reused_without_mutating_profile_or_roles(client, upstream, sessionmaker):
    profile = await create_saved_profile(client)
    roles_before = (await client.get("/api/llm/roles")).json()
    requests, _ = upstream(lambda _: httpx.Response(200, json={"data": [{"id": "new-model"}]}))
    response = await client.post(
        "/api/llm/models",
        json={"base_url": " https://provider.test/v1/// ", "profile_id": profile["id"], "api_key": ""},
    )
    assert response.status_code == 200
    assert requests[0].headers["Authorization"] == "Bearer sk-saved"
    assert "sk-saved" not in response.text
    assert (await client.get("/api/llm/profiles")).json() == [profile]
    assert (await client.get("/api/llm/roles")).json() == roles_before
    async with sessionmaker() as session:
        saved = (await session.execute(select(LlmProfile))).scalar_one()
        assert decrypt(saved.api_key_encrypted) == "sk-saved"


async def test_changed_url_cannot_receive_saved_key_but_explicit_key_is_allowed(client, upstream, sessionmaker):
    profile = await create_saved_profile(client)
    requests, _ = upstream(lambda _: httpx.Response(200, json={"data": []}))
    body = {"base_url": "https://different.test/v1", "profile_id": profile["id"]}
    response = await client.post("/api/llm/models", json=body)
    assert response.status_code == 422
    assert "重新填写 API Key" in response.json()["detail"]
    assert requests == []
    response = await client.post("/api/llm/models", json={**body, "api_key": "sk-new"})
    assert response.status_code == 200
    assert requests[0].headers["Authorization"] == "Bearer sk-new"
    assert (await client.get("/api/llm/profiles")).json() == [profile]
    async with sessionmaker() as session:
        saved = (await session.execute(select(LlmProfile))).scalar_one()
        assert decrypt(saved.api_key_encrypted) == "sk-saved"


async def test_changed_url_is_allowed_for_saved_keyless_profile(client, upstream):
    profile = await create_saved_profile(client, api_key="")
    requests, _ = upstream(lambda _: httpx.Response(200, json={"data": []}))
    response = await client.post(
        "/api/llm/models", json={"base_url": "http://localhost:11434/v1", "profile_id": profile["id"]}
    )
    assert response.status_code == 200
    assert "Authorization" not in requests[0].headers


async def test_missing_profile_and_unreadable_saved_key_are_safe(client, upstream, sessionmaker):
    requests, _ = upstream(lambda _: httpx.Response(200, json={"data": []}))
    response = await client.post(
        "/api/llm/models", json={"base_url": "https://provider.test/v1", "profile_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    profile = await create_saved_profile(client)
    async with sessionmaker() as session:
        saved = await session.get(LlmProfile, uuid.UUID(profile["id"]))
        saved.api_key_encrypted = "invalid-ciphertext"
        await session.commit()
    response = await client.post(
        "/api/llm/models", json={"base_url": "https://provider.test/v1", "profile_id": profile["id"]}
    )
    assert response.status_code == 422
    assert "重新填写 API Key" in response.json()["detail"]
    assert requests == []
    assert "invalid-ciphertext" not in response.text


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "   ",
        "provider.test/v1",
        "ftp://provider.test/v1",
        "https:///v1",
        "https://user:secret@provider.test/v1",
        "https://provider.test/v1?api_key=secret",
        "https://provider.test/v1?",
        "https://provider.test/v1#fragment",
        "https://provider.test/v1#",
        "https://bad host/v1",
        "https://provider.test:invalid/v1",
    ],
)
async def test_invalid_base_url_never_contacts_upstream(client, upstream, base_url):
    requests, _ = upstream(lambda _: httpx.Response(200, json={"data": []}))
    response = await client.post("/api/llm/models", json={"base_url": base_url})
    assert response.status_code == 422
    assert "接口地址" in response.json()["detail"]
    assert requests == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "模型列表请求被拒绝"),
        (401, "认证失败"),
        (402, "付费状态"),
        (403, "访问被拒绝"),
        (404, "未找到 /models"),
        (405, "不允许 GET /models"),
        (408, "处理请求超时"),
        (422, "请求格式被拒绝"),
        (501, "尚未实现"),
        (302, "重定向"),
        (429, "频繁"),
        (500, "暂时无法"),
        (503, "暂时无法"),
        (418, "请求未成功"),
    ],
)
async def test_upstream_errors_are_actionable_without_leaking_body_or_following_redirects(
    client, upstream, status, message
):
    requests, _ = upstream(
        lambda _: httpx.Response(status, text="sk-secret upstream failure", headers={"Location": "https://other.test"})
    )
    response = await client.post(
        "/api/llm/models", json={"base_url": "https://provider.test/v1", "api_key": "sk-secret"}
    )
    assert response.status_code == 502
    assert message in response.json()["detail"]
    assert f"模型服务返回 HTTP {status}" in response.json()["detail"]
    assert isinstance(response.json()["detail"], str)
    assert "sk-secret" not in response.text
    assert "upstream failure" not in response.text
    assert "other.test" not in response.text
    assert len(requests) == 1


async def test_local_missing_route_is_distinct_from_upstream_404(client, upstream):
    upstream(lambda _: httpx.Response(404, json={"detail": "Not Found"}))
    local_missing = await client.post("/api/llm/missing-route", json={"base_url": ""})
    assert local_missing.status_code == 404
    assert local_missing.json() == {"detail": "Not Found"}
    provider_missing = await client.post("/api/llm/models", json={"base_url": "https://provider.test/v1"})
    assert provider_missing.status_code == 502
    assert "模型服务返回 HTTP 404" in provider_missing.json()["detail"]
    assert "Not Found" not in provider_missing.text
    assert "/api/llm/models" in (await client.get("/openapi.json")).json()["paths"]


@pytest.mark.parametrize("payload", ["sk-secret not json", [], {"data": {}}, {"data": [{"id": None}]}])
async def test_invalid_model_responses_are_safe(client, upstream, payload):
    upstream(
        lambda _: (
            httpx.Response(200, content=payload) if isinstance(payload, str) else httpx.Response(200, json=payload)
        )
    )
    response = await client.post("/api/llm/models", json={"base_url": "https://provider.test/v1"})
    assert response.status_code == 502
    assert "模型" in response.json()["detail"]
    assert "HTTP 200" in response.json()["detail"]
    assert "sk-secret" not in response.text


@pytest.mark.parametrize(
    ("error_type", "status", "message"),
    [
        (httpx.ReadTimeout, 504, "超时"),
        (httpx.ConnectError, 502, "尚未收到 HTTP 响应"),
        (httpx.ProxyError, 502, "连接代理失败"),
        (httpx.RemoteProtocolError, 502, "返回无效 HTTP 响应"),
    ],
)
async def test_transport_errors_do_not_echo_credentials(client, upstream, error_type, status, message):
    def fail(_):
        raise error_type("sk-secret https://provider.test/secret")

    upstream(fail)
    response = await client.post("/api/llm/models", json={"base_url": "https://provider.test/v1"})
    assert response.status_code == status
    assert message in response.json()["detail"]
    assert "secret" not in response.text


async def test_discovery_has_an_overall_deadline(client, upstream, monkeypatch):
    async def slow(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"data": []})

    upstream(slow)
    monkeypatch.setattr(discovery, "REQUEST_TIMEOUT_S", 0.01)
    response = await client.post("/api/llm/models", json={"base_url": "https://provider.test/v1"})
    assert response.status_code == 504
    assert "超时" in response.json()["detail"]


async def test_oversized_response_is_rejected(client, upstream, monkeypatch):
    upstream(lambda _: httpx.Response(200, json={"data": [{"id": "long-model-name"}]}))
    monkeypatch.setattr(discovery, "MAX_RESPONSE_BYTES", 10)
    response = await client.post("/api/llm/models", json={"base_url": "https://provider.test/v1"})
    assert response.status_code == 502
    assert "过大" in response.json()["detail"]
    assert "HTTP 200" in response.json()["detail"]
