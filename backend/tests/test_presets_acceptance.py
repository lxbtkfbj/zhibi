"""预设任务 1：通过真实 notes/API 与演示模型留下可复查的调用证据。"""

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.llm.router import LLMRouter
from app.main import create_app
from app.models import LlmCall, LlmProfile, RoleAssignment
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed


@pytest.fixture
async def client(sessionmaker, monkeypatch):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)

    def forbid_remote(*args, **kwargs):
        raise AssertionError("预设验收禁止真实模型")

    monkeypatch.setattr(LLMRouter, "_chat_model", forbid_remote)
    async with sessionmaker() as session:
        profile = LlmProfile(name="预设验收专用演示模型", provider="demo", model="demo")
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def first_call(sessionmaker, book_id):
    async with sessionmaker() as session:
        calls = list(
            await session.scalars(
                select(LlmCall).where(LlmCall.book_id == book_id, LlmCall.purpose == "聊天·主编").order_by(LlmCall.id)
            )
        )
    assert calls and all(call.ok and call.model == "demo" for call in calls)
    return calls[0].request


async def test_system_then_edited_mine_and_blocked_activation(client, sessionmaker):
    # 两本独立的测试书证明全局生效；请求是 notes 真路径，不直接调用拼接函数。
    first_book = await seed(sessionmaker)
    note = await say(client, first_book, "聊聊这本书")
    reply = await reply_of(client, first_book, note["id"])
    assert reply["content"] and "state" not in reply["payload"]
    system = await first_call(sessionmaker, first_book)
    assert system["preset"]["source"] == "system" and system["preset"]["version"] == 1
    assert system["preset"]["name"] == "主编群聊·系统默认"
    assert [message["role"] for message in system["messages"]] == ["system", "user"]
    assert system["messages"] == [
        {"role": "system", "content": system["system"]},
        {"role": "user", "content": system["user"]},
    ]

    copied = await client.post("/api/presets/mine", json={"name": "验收：直说的主编"})
    assert copied.status_code == 201, copied.text
    mine = copied.json()
    blocks = mine["blocks"]
    old_voice = next(block["content"] for block in blocks if block["id"] == "voice")
    reply_style = next(block["content"] for block in blocks if block["id"] == "reply_style")
    new_voice = "用简短白话直说判断，不使用老编辑的称呼。"
    for block in blocks:
        if block["id"] == "reply_style":
            block["enabled"] = False
        elif block["id"] == "voice":
            block["content"] = new_voice
    saved = await client.put(f"/api/presets/mine/{mine['id']}", json={"name": mine["name"], "blocks": blocks})
    assert saved.status_code == 200, saved.text
    active = await client.put("/api/presets/active", json={"kind": "chief_group", "source": "mine", "id": mine["id"]})
    assert active.status_code == 200, active.text

    second_book = await seed(sessionmaker)
    await say(client, second_book, "聊聊这本书")
    edited = await first_call(sessionmaker, second_book)
    assert edited["preset"]["source"] == "mine" and edited["preset"]["id"] == mine["id"]
    assert edited["preset"]["version"] == 2
    assert "reply_style" not in [block["id"] for block in edited["preset"]["blocks"]]
    assert edited["system"] == system["system"].replace(old_voice, new_voice).replace(reply_style + "\n\n", "")

    # 保存未完成的草稿不拦；设为正在用才拦，失败不能替换当前活动项。
    broken = await client.post("/api/presets/mine", json={"name": "验收：不完整草稿"})
    assert broken.status_code == 201, broken.text
    broken = broken.json()
    broken_blocks = [block for block in broken["blocks"] if block["id"] != "note"]
    check = await client.post("/api/presets/check", json={"kind": "chief_group", "blocks": broken_blocks})
    assert check.status_code == 200, check.text
    draft = await client.put(
        f"/api/presets/mine/{broken['id']}", json={"name": broken["name"], "blocks": broken_blocks}
    )
    assert draft.status_code == 200, draft.text
    blocked = await client.put(
        "/api/presets/active", json={"kind": "chief_group", "source": "mine", "id": broken["id"]}
    )
    assert blocked.status_code == 422, blocked.text
    assert "没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。" in blocked.text
    listing = (await client.get("/api/presets?kind=chief_group")).json()
    assert listing["active"] == {"source": "mine", "id": mine["id"]}

    evidence = {
        "system": system,
        "mine": edited,
        "changes": {"disabled": "reply_style", "voice_before": old_voice, "voice_after": new_voice},
        "check": check.json(),
        "blocked_activation": {"status": blocked.status_code, "body": blocked.json()},
        "demo_only": True,
    }
    if destination := os.environ.get("ZHIBI_PRESET_EVIDENCE"):
        await asyncio.to_thread(
            Path(destination).write_text, json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
