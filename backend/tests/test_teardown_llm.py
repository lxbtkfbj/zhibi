"""拆书专用临时调用策略、原样提示词/schema 和演示模式。"""

import ast
import asyncio
import hashlib
import re
import textwrap
from pathlib import Path

import httpx
import openai
import pytest
from pydantic import BaseModel

from app.agents import schemas
from app.llm import demo
from app.llm import router as module
from app.llm.router import LLMError, LLMRouter, Outcome, ResolvedProfile, TeardownPolicy
from app.prompts import VARIABLE, catalog, default_content


class Payload(BaseModel):
    value: str


def api_error(code, message):
    response = httpx.Response(code, request=httpx.Request("POST", "https://example.test/v1/chat/completions"))
    cls = openai.RateLimitError if code == 429 else openai.BadRequestError
    return cls(message, response=response, body={"error": message})


def fake_router(monkeypatch, invoke):
    router = LLMRouter(None)
    records = []
    profile = ResolvedProfile(
        name="测试", provider="openai", model="fake", reasoning_effort="high", structured_method="json_mode"
    )

    async def resolve(role):
        return profile

    async def record(*args, **kwargs):
        records.append(kwargs)

    monkeypatch.setattr(router, "resolve", resolve)
    monkeypatch.setattr(router, "_record", record)
    monkeypatch.setattr(router, "_invoke_structured", invoke)
    return router, profile, records


async def test_teardown_remembers_rejected_low_without_mutating_model(monkeypatch):
    seen = []

    async def invoke(profile, *args):
        seen.append(profile.reasoning_effort)
        if profile.reasoning_effort == "low":
            raise api_error(400, "Unknown parameter: reasoning_effort")
        return Outcome(usage=(2, 3), parsed=Payload(value="好"))

    router, original, records = fake_router(monkeypatch, invoke)
    policy = TeardownPolicy()
    for _ in range(2):
        assert (
            await router.structured("teardown", Payload, "", "", purpose="拆书", teardown_policy=policy)
        ).value == "好"
    assert seen == ["low", None, None]
    assert policy.ignore_reasoning is True and original.reasoning_effort == "high"
    assert [r["ok"] for r in records] == [False, True, True]
    await router.aclose()


async def test_inflight_low_rejection_is_safe_after_another_batch_disables_it(monkeypatch):
    both_started = asyncio.Event()
    count = 0

    async def invoke(profile, *args):
        nonlocal count
        if profile.reasoning_effort == "low":
            count += 1
            if count == 2:
                both_started.set()
            await both_started.wait()
            raise api_error(400, "reasoning_effort is not supported")
        return Outcome(usage=(1, 1), parsed=Payload(value="好"))

    router, _, records = fake_router(monkeypatch, invoke)
    policy = TeardownPolicy()
    results = await asyncio.gather(
        *[router.structured("teardown", Payload, "", "", purpose="拆书", teardown_policy=policy) for _ in range(2)]
    )
    assert [result.value for result in results] == ["好", "好"]
    assert policy.ignore_reasoning and len(records) == 4
    await router.aclose()


async def test_teardown_429_waits_and_reduces_shared_parallel(monkeypatch):
    calls, waits = [], []

    async def invoke(profile, *args):
        calls.append(profile)
        if len(calls) <= 4:
            raise api_error(429, "rate limit")
        return Outcome(usage=(1, 1), parsed=Payload(value="好"))

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    router, original, records = fake_router(monkeypatch, invoke)
    policy = TeardownPolicy()
    await router.structured("teardown", Payload, "", "", purpose="拆书", teardown_policy=policy)
    assert waits == [5, 10, 20, 40]
    assert policy.parallel == 1 and len(policy.rate_limits) == 4
    assert all(p.reasoning_effort == "low" for p in calls) and original.reasoning_effort == "high"
    assert len(records) == 5
    await router.aclose()


async def test_teardown_429_stops_at_six_attempts(monkeypatch):
    waits = []

    async def invoke(*args):
        raise api_error(429, "rate limit")

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    router, _, records = fake_router(monkeypatch, invoke)
    with pytest.raises(LLMError, match="调用模型失败"):
        await router.structured("teardown", Payload, "", "", purpose="拆书", teardown_policy=TeardownPolicy())
    assert len(records) == 6 and waits == [5, 10, 20, 40, 40]
    await router.aclose()


async def test_writing_keeps_original_retry_and_reasoning(monkeypatch):
    seen = []

    async def invoke(profile, *args):
        seen.append(profile.reasoning_effort)
        raise api_error(429, "rate limit")

    async def forbidden_sleep(*args):
        pytest.fail("写书不增加拆书的限流等待")

    monkeypatch.setattr(module.asyncio, "sleep", forbidden_sleep)
    router, original, records = fake_router(monkeypatch, invoke)
    with pytest.raises(LLMError):
        await router.structured("chief", Payload, "", "", purpose="写书")
    assert seen == ["high"] * 3 and len(records) == 3 and original.reasoning_effort == "high"
    await router.aclose()


def test_rate_limit_window_expires_without_restoring_parallel(monkeypatch):
    policy = TeardownPolicy(parallel=2, rate_limits=[10.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: 71.0)
    policy.rate_limited()
    assert policy.parallel == 2 and policy.rate_limits == [71.0]


def test_teardown_schema_ast_is_verbatim_from_task():
    root = Path(__file__).resolve().parents[2]
    task = (root / "docs/codex任务/拆书第二批/1-后台-拆大纲.md").read_text(encoding="utf-8")
    expected = []
    for block in re.findall(r"^[ \t]*```python\n(.*?)^[ \t]*```", task, re.M | re.S):
        expected.extend(ast.parse(textwrap.dedent(block)).body)
    actual = {
        node.name: node
        for node in ast.parse((root / "backend/app/agents/schemas.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef)
    }
    assert len(expected) == 11
    for node in expected:
        assert ast.dump(actual[node.name]) == ast.dump(node), node.name


PROMPT_HASHES = {
    "persona_teardown": "94275d6a51f329a8294995c7a0e25a720739c041d2396e8faa725c7a12105db3",
    "teardown_read": "c1183b1fcc4892842c79d2f510778ae1c86c7d38cafcff75eea252910b5acf79",
    "teardown_units": "c01abb24b399d420f3c40da4b26d248753da65bffed086a3ecd97a095462a3ac",
    "teardown_volumes": "7c0e4199493703b8ddd3e1bc3179d62f33848abd35cf69a1953205544fd356f1",
    "teardown_volume_text": "592f1542a49ae3876f2478d0a8766f6bc414dff3d780ef95fda4ad529bb05c6d",
    # 拆书第五批 §1：作者已改好的提示词基线，仍逐字保护，不由实现改写。
    "chat_teardown": "a6974a02ade607ca30ab057f0533817614c6be9714393a53dfb87499e9ca42e3",
}


def test_prompt_bytes_unchanged_and_all_variables_registered():
    root = Path(__file__).resolve().parents[1] / "app/prompts"
    for name, digest in PROMPT_HASHES.items():
        assert hashlib.sha256((root / f"{name}.md").read_bytes()).hexdigest() == digest
        assert catalog.entry(name)[2:4] == ("拆书", "teardown")
        assert [v["name"] for v in catalog.variables(name)] == list(
            dict.fromkeys(VARIABLE.findall(default_content(name)))
        )


def template(name, **values):
    return VARIABLE.sub(lambda m: str(values[m[1]]), default_content(name))


async def test_demo_new_schemas_follow_supplied_chapter_numbers(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    read = await demo.respond(
        schemas.TeardownRead,
        "",
        template(
            "teardown_read",
            title="书",
            first=37,
            last=38,
            roster="（还没有）",
            chapters="「第 37 章 出门」\n人物出门。\n\n「第 38 章」\n人物回来。",
        ),
    )
    assert [c.index for c in read.chapters] == [37, 38]
    assert read.chapters[-1].summary == "人物回来。"
    units = await demo.respond(
        schemas.TeardownUnits,
        "",
        template(
            "teardown_units",
            title="书",
            first=37,
            done_units="（还没有）",
            chapters="\n".join(f"第 {i} 章：摘要｜看点｜钩子" for i in range(37, 61)),
            tail_rule="这是全书最后几章：全部归完，不留 open_from。",
        ),
    )
    assert units.units[0].first == 37 and units.units[-1].last == 60 and units.open_from is None
    volumes = await demo.respond(
        schemas.TeardownVolumes,
        "",
        template(
            "teardown_volumes",
            title="书",
            first=37,
            done_volumes="（还没有）",
            units="\n".join(f"第 {u.first}–{u.last} 章「{u.title}」：{u.text}" for u in units.units),
            tail_rule="这是全书最后几个单元：全部归完，不留 open_from。",
        ),
    )
    assert volumes.volumes[0].first == 37 and volumes.volumes[-1].last == 60 and volumes.open_from is None
    text = await demo.respond(
        schemas.TeardownVolumeText,
        "",
        template(
            "teardown_volume_text",
            title="书",
            index=1,
            volume_title="第一卷",
            first=37,
            last=60,
            done_volumes="（还没有）",
            units="",
            tail_rule="这是文件里最后一卷，原书可能还没写完：卷末要是没收在一次大高潮上，照读到的写，最后一句写「到第 60 章还没收住」。",
        ),
    )
    assert text.text.endswith("到第 60 章还没收住。")
