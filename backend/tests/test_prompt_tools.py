"""提示词在线修改、真实请求原文、逐次失败及用量保留。"""

import asyncio
import json
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from pydantic import BaseModel
from sqlalchemy import func, select

from app.agents import playbook
from app.llm import router as module
from app.llm.router import DEMO_PROFILE, LLMError, LLMRouter, Outcome, ResolvedProfile
from app.main import app
from app.models import Book, LlmCall, PromptOverride
from app.prompts import default_content, render
from app.prompts.catalog import CATALOG, variables


class Answer(BaseModel):
    answer: str


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def rows(sessionmaker):
    async with sessionmaker() as session:
        return list((await session.scalars(select(LlmCall).order_by(LlmCall.id))).all())


def remote(router, monkeypatch, method="function_calling"):
    profile = ResolvedProfile(name="测试模型", provider="openai_compatible", model="test", structured_method=method)
    monkeypatch.setattr(router, "resolve", AsyncMock(return_value=profile))
    return profile


async def test_catalog_has_chinese_variable_labels_and_safe_names(client):
    response = await client.get("/api/prompts")
    assert response.status_code == 200
    assert len(response.json()) == len(CATALOG)
    for row in response.json():
        assert row["customized"] is False
        assert row["variables"] == variables(row["name"])
        assert all(any("\u4e00" <= char <= "\u9fff" for char in var["label"]) for var in row["variables"])
    assert (await client.get("/api/prompts/unknown")).status_code == 404
    assert (await client.get("/api/prompts/playbooks.general")).status_code == 200
    assert (await client.get("/api/prompts/playbooks/general")).status_code == 200


async def test_override_validates_renders_and_restores(client, sessionmaker):
    original = default_content("setup_story")
    values = {var["name"]: "" for var in variables("setup_story")}
    values["idea"] = "作者原文 {{不是模板变量}}"
    baseline = render("setup_story", **values)
    assert "{{不是模板变量}}" in baseline
    for invalid, message in ((original.replace("{{idea}}", ""), "缺少变量"), (original + "{{unknown}}", "不支持")):
        response = await client.put("/api/prompts/setup_story", json={"content": invalid})
        assert response.status_code == 422 and message in response.json()["detail"]
        async with sessionmaker() as session:
            assert await session.get(PromptOverride, "setup_story") is None
    custom = "作者自定义：\n" + original
    response = await client.put("/api/prompts/setup_story", json={"content": custom})
    assert response.status_code == 200 and response.json()["customized"]
    assert render("setup_story", **values).startswith("作者自定义：")
    response = await client.delete("/api/prompts/setup_story")
    assert response.status_code == 200 and not response.json()["customized"]
    assert render("setup_story", **values) == baseline


async def test_playbook_validation_hot_reload_and_explicit_pick(client):
    assert playbook.pick({"genre": "玄幻", "tags": ["后宫"]}, "general").key == "general"
    assert playbook.pick({}, "harem_xuanhuan").key == "harem_xuanhuan"
    assert (await client.put("/api/prompts/playbooks.general", json={"content": "# 坏打法\n正文"})).status_code == 422
    original = default_content("playbooks.general")
    assert playbook.load("general").name == "通用"
    response = await client.put(
        "/api/prompts/playbooks.general", json={"content": original.replace("# 通用", "# 自定义打法", 1)}
    )
    assert response.status_code == 200
    assert playbook.load("general").name == "自定义打法"
    await client.delete("/api/prompts/playbooks.general")
    assert playbook.load("general").name == "通用"


async def test_running_worker_reads_committed_override_without_restart(client):
    # 子进程先把默认文本读进缓存，再保持原进程存活；API 保存后下一次 render 必须变更。
    code = (
        "import json,sys; from app.prompts import render; "
        "print(json.dumps(render('rules')), flush=True); sys.stdin.readline(); "
        "print(json.dumps(render('rules')), flush=True)"
    )
    # psycopg 使用 Windows SelectorEventLoop，不支持 asyncio subprocess transport。
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-u", "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert (
            json.loads(await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), timeout=15))
            == default_content("rules").strip()
        )
        custom = "跨进程热更新\n" + default_content("rules")
        assert (await client.put("/api/prompts/rules", json={"content": custom})).status_code == 200
        process.stdin.write(b"next\n")
        process.stdin.flush()
        assert json.loads(await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), timeout=15)).startswith(
            "跨进程热更新"
        )
        assert await asyncio.to_thread(process.wait, timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            await asyncio.to_thread(process.wait)


async def test_demo_structured_logs_original_request_response_and_latest_prompt(sessionmaker, client, monkeypatch):
    router = LLMRouter(sessionmaker)
    monkeypatch.setattr(module.demo, "respond", AsyncMock(return_value=Answer(answer="原样回复")))
    system = render("persona_chief", rules=render("rules"))
    user = render("setup_story", idea="点子", pitch="", requirements="规矩", style="", revision="", existing="")
    await router.structured("chief", Answer, system, user, purpose="开书·概念")
    call = (await rows(sessionmaker))[0]
    assert call.request["system"] == system and call.request["user"] == user
    assert call.request["schema_name"] == "Answer" and call.request["schema"] == Answer.model_json_schema()
    assert call.request["method"] == "demo"
    assert set(call.request["prompt_names"]) >= {"setup_story", "persona_chief", "rules"}
    assert json.loads(call.response) == {"answer": "原样回复"}
    prompt = (await client.get("/api/prompts/setup_story")).json()
    assert prompt["last_call"]["id"] == call.id


@pytest.mark.parametrize("method", ["function_calling", "json_mode"])
async def test_remote_structured_preserves_tool_arguments_or_json(sessionmaker, monkeypatch, method):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch, method)
    raw_text = '{ "answer" : "原样 JSON，不改变空格" }'
    raw = AIMessage(
        content=raw_text if method == "json_mode" else "",
        additional_kwargs={}
        if method == "json_mode"
        else {
            "tool_calls": [{"id": "tool_1", "type": "function", "function": {"name": "Answer", "arguments": raw_text}}]
        },
        usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13},
    )
    model = SimpleNamespace(
        bind=lambda **kwargs: SimpleNamespace(ainvoke=AsyncMock(return_value=raw)),
        with_structured_output=lambda *args, **kwargs: SimpleNamespace(
            ainvoke=AsyncMock(
                return_value={
                    "raw": raw,
                    "parsed": Answer(answer="原样 JSON，不改变空格"),
                    "parsing_error": None,
                }
            )
        ),
    )
    monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: model)
    await router.structured("chief", Answer, "系统", "用户", purpose="测试")
    call = (await rows(sessionmaker))[0]
    assert call.response == raw_text and call.prompt_tokens == 10 and call.completion_tokens == 3
    assert call.request["method"] == method and call.request["user"] == "用户"
    assert call.request["system"] == ("系统" + module.schema_instruction(Answer) if method == "json_mode" else "系统")


async def test_parse_failures_each_have_raw_response_and_retry_request(sessionmaker, monkeypatch):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch)
    monkeypatch.setattr(
        router,
        "_invoke_structured",
        AsyncMock(
            side_effect=[
                Outcome(usage=(1, 2), error="坏 JSON", response="{ broken JSON"),
                Outcome(usage=(3, 4), parsed=Answer(answer="好了"), response='{"answer":"好了"}'),
            ]
        ),
    )
    result = await router.structured("chief", Answer, "系统", "原始用户", purpose="测试重试")
    assert result.answer == "好了"
    failed, passed = await rows(sessionmaker)
    assert failed.ok is False and failed.response == "{ broken JSON" and failed.error == "坏 JSON"
    assert failed.request["method"] == "function_calling"
    assert passed.ok and passed.request["method"] == "json_mode" and "坏 JSON" in passed.request["user"]
    assert passed.response == '{"answer":"好了"}'


async def test_bad_request_fallback_and_network_retries_are_logged(sessionmaker, monkeypatch):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch)
    request = httpx.Request("POST", "https://example.test/chat/completions")
    bad = openai.BadRequestError(
        "不支持工具调用", response=httpx.Response(400, request=request), body={"error": "tools"}
    )
    monkeypatch.setattr(
        router,
        "_invoke_structured",
        AsyncMock(
            side_effect=[
                bad,
                openai.APIConnectionError(request=request),
                Outcome(usage=(1, 1), parsed=Answer(answer="恢复"), response="结果"),
            ]
        ),
    )
    await router.structured("chief", Answer, "系统", "用户", purpose="网络重试")
    calls = await rows(sessionmaker)
    assert [row.ok for row in calls] == [False, False, True]
    assert json.loads(calls[0].response) == {"error": "tools"}
    assert [row.request["method"] for row in calls] == ["function_calling", "json_mode", "json_mode"]


async def test_truncation_is_failed_even_when_partial_schema_parses(sessionmaker, monkeypatch):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch)
    invoke = AsyncMock(
        return_value=Outcome(usage=(1, 2), truncated=True, parsed=Answer(answer="部分"), response="部分 JSON")
    )
    monkeypatch.setattr(router, "_invoke_structured", invoke)
    with pytest.raises(LLMError, match="截断"):
        await router.structured("chief", Answer, "系统", "用户", purpose="截断")
    assert invoke.await_count == 1
    call = (await rows(sessionmaker))[0]
    assert not call.ok and call.response == "部分 JSON"


@pytest.mark.parametrize("demo", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_stream_logs_full_or_partial_response(sessionmaker, monkeypatch, demo, fails):
    router = LLMRouter(sessionmaker)
    if demo:

        async def stream(*args):
            yield "第一段"
            if fails:
                raise TimeoutError("中途断线")
            yield "第二段"

        monkeypatch.setattr(module.demo, "stream_text", stream)
    else:
        remote(router, monkeypatch)

        async def stream(*args):
            yield AIMessageChunk(
                content="第一段", usage_metadata={"input_tokens": 7, "output_tokens": 2, "total_tokens": 9}
            )
            if fails:
                raise TimeoutError("中途断线")
            yield AIMessageChunk(
                content="第二段", usage_metadata={"input_tokens": 7, "output_tokens": 4, "total_tokens": 11}
            )

        monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: SimpleNamespace(astream=stream))
    chunks = []
    try:
        async for chunk in router.stream_text("writer", "系统", "用户", purpose="正文"):
            chunks.append(chunk)
    except LLMError:
        assert fails
    call = (await rows(sessionmaker))[0]
    assert call.response == "".join(chunks) == ("第一段" if fails else "第一段第二段")
    assert call.ok is not fails
    assert call.request["system"] == "系统" and call.request["user"] == "用户"
    assert call.request["schema"] is None
    if fails:
        assert "中途断线" in call.error


async def test_retention_keeps_2000_per_book_and_usage_pagination_remains(sessionmaker, client):
    async with sessionmaker() as session:
        first, second = Book(title="第一本", idea="点子"), Book(title="第二本", idea="点子")
        session.add_all([first, second])
        await session.flush()
        session.add_all(
            [
                LlmCall(
                    book_id=first.id,
                    role="chief",
                    prompt_tokens=2,
                    completion_tokens=3,
                    request={"system": "保留内容"},
                    response="原文",
                )
                for _ in range(2001)
            ]
        )
        session.add(
            LlmCall(
                book_id=second.id,
                role="writer",
                prompt_tokens=0,
                completion_tokens=0,
                request={"user": "另一本"},
                response="另一本原文",
            )
        )
        await session.commit()
    router = LLMRouter(sessionmaker, book_id=first.id)
    await router._record(
        "reviewer", DEMO_PROFILE, "最新", time.monotonic(), 5, 7, ok=True, request={"user": "最新"}, response="最新"
    )
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.book_id == first.id)) == 2002
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LlmCall)
                .where(LlmCall.book_id == first.id, LlmCall.request.is_not(None))
            )
            == 2000
        )
        oldest = await session.scalar(select(LlmCall).where(LlmCall.book_id == first.id).order_by(LlmCall.id))
        assert oldest.request is None and oldest.response is None and oldest.prompt_tokens == 2
        other = await session.scalar(select(LlmCall).where(LlmCall.book_id == second.id))
        assert other.response == "另一本原文"
    page = (await client.get("/api/llm-calls", params={"book_id": str(first.id), "limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_before"]
    assert "request" not in page["items"][0]
    next_page = (
        await client.get("/api/llm-calls", params={"book_id": str(first.id), "limit": 2, "before": page["next_before"]})
    ).json()
    assert next_page["items"][0]["id"] < page["items"][-1]["id"]
    detail = (await client.get(f"/api/llm-calls/{page['items'][0]['id']}")).json()
    assert detail["response"] == "最新" and detail["request"] == {"user": "最新"}
    filtered = (await client.get("/api/llm-calls", params={"role": "writer"})).json()
    assert len(filtered["items"]) == 1 and filtered["items"][0]["book_id"] == str(second.id)
    usage = (await client.get("/api/usage")).json()
    assert usage["total"] == {"calls": 2003, "prompt_tokens": 4007, "completion_tokens": 6010}
    assert (await client.get("/api/llm-calls/999999999")).status_code == 404


async def test_missing_provider_usage_is_unknown_not_zero(sessionmaker, client, monkeypatch):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch, "json_mode")
    raw = AIMessage(content='{"answer":"没有用量"}')
    model = SimpleNamespace(bind=lambda **kwargs: SimpleNamespace(ainvoke=AsyncMock(return_value=raw)))
    monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: model)
    await router.structured("chief", Answer, "系统", "用户", purpose="未提供用量")
    call = (await rows(sessionmaker))[0]
    assert call.prompt_tokens is None and call.completion_tokens is None
    assert (await client.get(f"/api/llm-calls/{call.id}")).json()["prompt_tokens"] is None
    assert module._usage(SimpleNamespace(usage_metadata={"input_tokens": 0, "output_tokens": 0})) == (0, 0)
    assert module._usage(SimpleNamespace(usage_metadata={"output_tokens": 7})) == (None, 7)


async def test_usage_totals_do_not_understate_partly_unknown_counts(sessionmaker, client):
    async with sessionmaker() as session:
        book = Book(title="用量未知", idea="点子")
        session.add(book)
        await session.flush()
        session.add_all(
            [
                LlmCall(book_id=book.id, role="chief", prompt_tokens=0, completion_tokens=0),
                LlmCall(book_id=book.id, role="chief", prompt_tokens=5, completion_tokens=7),
                LlmCall(book_id=book.id, role="writer", prompt_tokens=None, completion_tokens=9),
            ]
        )
        await session.commit()
    global_usage = (await client.get("/api/usage")).json()
    assert global_usage["total"] == {"calls": 3, "prompt_tokens": None, "completion_tokens": 16}
    items = {row["role"]: row for row in global_usage["items"]}
    assert items["chief"]["prompt_tokens"] == 5
    assert items["writer"]["prompt_tokens"] is None
    book_usage = (await client.get(f"/api/books/{book.id}/usage")).json()
    assert book_usage["calls"] == 3 and book_usage["prompt_tokens"] is None and book_usage["completion_tokens"] == 16
    assert book_usage["by_role"]["writer"]["prompt_tokens"] is None


async def test_truncated_stream_logs_failed_and_preserves_all_partial_text(sessionmaker, monkeypatch):
    router = LLMRouter(sessionmaker)
    remote(router, monkeypatch)

    async def stream(*args):
        yield AIMessageChunk(content="已经写出的正文")
        yield AIMessageChunk(content="仍然保留", response_metadata={"finish_reason": "length"})

    monkeypatch.setattr(module, "build_chat_model", lambda *args, **kwargs: SimpleNamespace(astream=stream))
    parts = []
    with pytest.raises(LLMError, match="被截断"):
        async for chunk in router.stream_text("writer", "系统", "用户", purpose="截断正文"):
            parts.append(chunk)
    call = (await rows(sessionmaker))[0]
    assert not call.ok and "被截断" in call.error
    assert call.response == "".join(parts) == "已经写出的正文仍然保留"
    assert call.prompt_tokens is None and call.completion_tokens is None
