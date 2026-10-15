"""Exercise the real SDK/httpx path against an HTTP/1.1 keep-alive server.

No network methods are mocked: only profile resolution and audit persistence are
replaced in the cross-loop test, so it isolates the HTTP pool from DB pools.
"""

import asyncio
import json
import logging
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.llm import router as router_module
from app.models import LlmCall, LlmProfile, RoleAssignment


class NetworkAnswer(BaseModel):
    answer: str


class FakeOpenAI(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), OpenAIHandler)
        self.requests: list[dict] = []
        self.reject_tools = False
        self.reject_json = False
        self.error_code = "unsupported_tools"

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}/v1"


class OpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        if (body.get("tools") and self.server.reject_tools) or (
            body.get("response_format") and self.server.reject_json
        ):
            self.send_json(400, {"error": {
                "message": self.server.error_code,
                "type": "invalid_request_error",
                "code": self.server.error_code,
            }})
            return
        if body.get("stream"):
            chunks = [
                {"index": 0, "delta": {"role": "assistant", "content": "第一段"}, "finish_reason": None},
                {"index": 0, "delta": {"content": "第二段"}, "finish_reason": None},
                {"index": 0, "delta": {}, "finish_reason": "stop"},
            ]
            events = [{
                "id": "fake-stream", "object": "chat.completion.chunk", "created": 1,
                "model": "fake-chat", "choices": [choice],
            } for choice in chunks]
            events.append({
                "id": "fake-stream", "object": "chat.completion.chunk", "created": 1,
                "model": "fake-chat", "choices": [],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            })
            payload = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
            self.send_body(200, (payload + "data: [DONE]\n\n").encode(), "text/event-stream")
            return
        message = {"role": "assistant", "content": '{"answer":"ok"}'}
        finish_reason = "stop"
        if body.get("tools"):
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_fake", "type": "function", "function": {
                    "name": body["tools"][0]["function"]["name"], "arguments": '{"answer":"ok"}',
                },
            }]}
            finish_reason = "tool_calls"
        self.send_json(200, {
            "id": "fake-completion", "object": "chat.completion", "created": 1,
            "model": "fake-chat", "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        })

    def send_json(self, status, body):
        self.send_body(status, json.dumps(body).encode(), "application/json")

    def send_body(self, status, payload, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()


@contextmanager
def openai_server():
    server = FakeOpenAI()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def fake_openai(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1")
    # Test the production remote/proxy-aware branch while connecting only locally.
    monkeypatch.setattr(router_module, "LOCAL_HOSTS", set())
    with openai_server() as server:
        yield server


async def close_router(router):
    # Allows the same regression to be run against a saved pre-fix module.
    if hasattr(router, "aclose"):
        await router.aclose()


def run_on_two_loops(module, server, mode):
    profile = module.ResolvedProfile(
        name="HTTP regression", provider="openai_compatible", base_url=server.base_url,
        api_key="fake-test-key", model="fake-chat", structured_method="json_mode", timeout_s=10,
    )
    loops = []
    calls = []

    async def one_task():
        loops.append(asyncio.get_running_loop())
        router = module.LLMRouter(None)
        router.resolve = AsyncMock(return_value=profile)

        async def record(*_, **kwargs):
            calls.append(kwargs)

        router._record = record
        try:
            if mode == "structured":
                result = await router.structured("chief", NetworkAnswer, "Return JSON.", "hello", purpose="loop-test")
                assert result.answer == "ok"
            else:
                result = "".join([part async for part in router.stream_text(
                    "writer", "Write text.", "hello", purpose="loop-test"
                )])
                assert result == "第一段第二段"
        finally:
            await close_router(router)

    asyncio.run(one_task())
    asyncio.run(one_task())
    assert loops[0] is not loops[1] and all(loop.is_closed() for loop in loops)
    # A retry can hide Event loop is closed in structured(): successful final
    # output alone is insufficient. Both tasks must succeed on their first try.
    assert len(calls) == 2 and all(call["ok"] for call in calls), calls
    assert len(server.requests) == 2


@pytest.mark.parametrize("mode", ["structured", "stream_text"])
def test_remote_http_clients_do_not_cross_event_loops(fake_openai, mode):
    run_on_two_loops(router_module, fake_openai, mode)


async def seed_profile(sessionmaker, server, *, method="function_calling"):
    async with sessionmaker() as session:
        profile = LlmProfile(
            name="HTTP fallback", provider="openai_compatible", base_url=server.base_url,
            model="fake-chat", structured_method=method, timeout_s=10,
        )
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()
        return profile.id


async def test_unsupported_tools_fallback_persists_and_next_task_skips_tools(
    fake_openai, sessionmaker, caplog, monkeypatch
):
    # Alembic's session fixture disables pre-existing module loggers.
    monkeypatch.setattr(router_module.log, "disabled", False)
    caplog.set_level(logging.INFO, logger="app.llm.router")
    fake_openai.reject_tools = True
    profile_id = await seed_profile(sessionmaker, fake_openai)
    for task in range(2):
        router = router_module.LLMRouter(sessionmaker)
        try:
            result = await router.structured("chief", NetworkAnswer, "Return JSON.", "hello", purpose="fallback")
            assert result.answer == "ok"
        finally:
            await close_router(router)
        async with sessionmaker() as session:
            profile = await session.get(LlmProfile, profile_id)
            assert profile.structured_method == "json_mode"
            assert profile.structured_method_auto is True
        assert len(fake_openai.requests) == task + 2
    assert "json_mode" in caplog.text
    assert "tools" in fake_openai.requests[0]
    assert all("tools" not in body for body in fake_openai.requests[1:])
    assert all(body["response_format"] == {"type": "json_object"} for body in fake_openai.requests[1:])
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).order_by(LlmCall.id)))
        assert [call.ok for call in calls] == [False, True, True]
        assert [call.request["method"] for call in calls] == ["function_calling", "json_mode", "json_mode"]


@pytest.mark.parametrize("error_code,reject_json", [
    ("unsupported_tools", True),
    ("context_length_exceeded", False),
])
async def test_failed_or_unrelated_fallback_does_not_persist(fake_openai, sessionmaker, error_code, reject_json):
    fake_openai.reject_tools = True
    fake_openai.reject_json = reject_json
    fake_openai.error_code = error_code
    profile_id = await seed_profile(sessionmaker, fake_openai)
    router = router_module.LLMRouter(sessionmaker)
    try:
        with pytest.raises(router_module.LLMError):
            await router.structured("chief", NetworkAnswer, "Return JSON.", "hello", purpose="fallback-failure")
    finally:
        await close_router(router)
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.structured_method == "function_calling"
        assert profile.structured_method_auto is False
    assert len(fake_openai.requests) == (2 if reject_json else 1)
