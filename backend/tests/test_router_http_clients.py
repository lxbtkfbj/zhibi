"""HTTP 客户端必须由路由器/一次性调用持有并关闭，而不是由 SDK 全局复用。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.llm import router as module
from app.llm.router import DEMO_PROFILE, LLMRouter, ResolvedProfile


@pytest.fixture
def transports(monkeypatch):
    created = []

    class SyncClient:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = 0
            created.append(self)

        def close(self):
            self.closed += 1

    class AsyncClient(SyncClient):
        async def aclose(self):
            self.closed += 1

    monkeypatch.setattr(module.httpx, "Client", SyncClient)
    monkeypatch.setattr(module.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(module, "ChatOpenAI", lambda **kwargs: SimpleNamespace(**kwargs))
    return created


def remote_profile(**kwargs):
    return ResolvedProfile(
        name="remote", provider="openai", base_url="https://models.example/v1", model="chat", **kwargs,
    )


async def test_router_clients_are_lazy_shared_and_task_scoped(transports):
    first, second = LLMRouter(None), LLMRouter(None)
    assert transports == []
    profile = remote_profile(timeout_s=41)
    structured = first._chat_model(profile)
    stream = first._chat_model(profile, streaming=True)
    other_task = second._chat_model(profile)
    assert len(transports) == 4
    assert structured.http_client is stream.http_client
    assert structured.http_async_client is stream.http_async_client
    assert structured.http_client is not other_task.http_client
    assert structured.http_async_client is not other_task.http_async_client
    assert structured.http_client.options == {"trust_env": True, "timeout": 41}
    assert structured.http_async_client.options == {"trust_env": True, "timeout": 41}
    assert stream.streaming is True
    assert structured.timeout == 41
    assert structured.max_retries == 0
    assert structured.http_socket_options == ()
    await first.aclose()
    await first.aclose()
    assert [client.closed for client in transports] == [1, 1, 0, 0]
    await second.aclose()
    assert all(client.closed == 1 for client in transports)
    with pytest.raises(RuntimeError, match="已经关闭"):
        first._chat_model(profile)


async def test_proxy_policy_and_timeouts_get_separate_pairs(transports):
    async with LLMRouter(None) as router:
        remote = router._chat_model(remote_profile(timeout_s=25))
        local = router._chat_model(ResolvedProfile(
            name="local", provider="openai", base_url="http://localhost:11434/v1", model="chat", timeout_s=25,
        ))
        slow = router._chat_model(remote_profile(timeout_s=90))
        assert len(transports) == 6
        assert local.http_client.options == {"trust_env": False, "timeout": 25}
        assert local.http_async_client.options == {"trust_env": False, "timeout": 25}
        assert remote.http_client is not local.http_client
        assert slow.http_client is not remote.http_client
        assert slow.http_async_client.options == {"trust_env": True, "timeout": 90}
    assert all(client.closed == 1 for client in transports)


async def test_unused_router_does_not_create_clients_on_close(transports):
    router = LLMRouter(None)
    await router.aclose()
    await router.aclose()
    assert transports == []


async def test_close_failure_still_closes_every_other_client(transports, monkeypatch):
    router = LLMRouter(None)
    first = router._chat_model(remote_profile(timeout_s=25))
    router._chat_model(remote_profile(timeout_s=90))

    async def fail_close():
        first.http_async_client.closed += 1
        raise RuntimeError("close failed")

    monkeypatch.setattr(first.http_async_client, "aclose", fail_close)
    with pytest.raises(RuntimeError, match="close failed"):
        await router.aclose()
    assert all(client.closed == 1 for client in transports)
    await router.aclose()


async def test_async_client_creation_failure_closes_sync_client(transports, monkeypatch):
    def fail_create(**_kwargs):
        raise RuntimeError("creation failed")

    monkeypatch.setattr(module.httpx, "AsyncClient", fail_create)
    async with LLMRouter(None) as router:
        with pytest.raises(RuntimeError, match="creation failed"):
            router._chat_model(remote_profile())
    assert len(transports) == 1
    assert transports[0].closed == 1


@pytest.mark.parametrize("fail", [False, True])
async def test_ping_closes_one_shot_clients_on_success_or_failure(transports, monkeypatch, fail):
    class Model:
        def bind(self, **kwargs):
            assert kwargs == {"max_tokens": 64}
            return self

        async def ainvoke(self, _messages):
            if fail:
                raise RuntimeError("request failed")
            return SimpleNamespace(content="连接成功")

    monkeypatch.setattr(module, "ChatOpenAI", lambda **kwargs: Model())
    if fail:
        with pytest.raises(RuntimeError, match="request failed"):
            await module.ping(remote_profile())
    else:
        assert await module.ping(remote_profile()) == "连接成功"
    assert len(transports) == 2
    assert all(client.closed == 1 for client in transports)
    assert await module.ping(DEMO_PROFILE) == "演示模式无需联网"
    assert len(transports) == 2


async def test_remote_ping_reaches_environment_forward_proxy(monkeypatch):
    """虚拟上游不可直连：真实 HTTP 请求只能经本地代理的 absolute-form 路径成功。"""
    requests = []

    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            payload = json.dumps({
                "id": "proxy-test", "object": "chat.completion", "created": 1, "model": "chat",
                "choices": [{
                    "index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "proxied"},
                }],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proxy = f"http://127.0.0.1:{server.server_port}"
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(variable, proxy)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.delenv("OPENAI_PROXY", raising=False)
        profile = ResolvedProfile(
            name="proxy", provider="openai", base_url="http://model.example.invalid/v1", model="chat", timeout_s=5,
        )
        assert await module.ping(profile) == "proxied"
        assert len(requests) == 1
        assert requests[0][0] == "http://model.example.invalid/v1/chat/completions"
        assert requests[0][1]["model"] == "chat"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
