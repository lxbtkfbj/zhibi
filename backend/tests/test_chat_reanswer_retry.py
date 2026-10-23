"""无工具重答本身断了，重试也只能重写，不能重新记忆。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Memory
from app.services import chat, chat_agent
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


@pytest.mark.parametrize("undone", [False, True])
async def test_failed_reanswer_retry_never_returns_to_tools(client, sessionmaker, monkeypatch, undone):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda *args: None)
    bid = await seed(sessionmaker)
    note = await say(client, bid, "记住，以后每章结尾都留悬念")
    reply = await reply_of(client, bid, note["id"])
    memory = reply["payload"]["memories"][0]["memory"]
    if undone:
        result = await client.post(
            f"/api/books/{bid}/memories/{memory['id']}/undo", json={"version": memory["version"]}
        )
        assert result.status_code == 200
        reply = await reply_of(client, bid, note["id"])
    async with sessionmaker() as session:
        before = (await session.execute(select(Memory.id, Memory.version, Memory.deleted_at))).all()
    streams = []

    async def rewrite(*args, **kwargs):
        streams.append(True)
        if len(streams) == 1:
            raise RuntimeError("演示重答中断")
        return "只是重写回答，记忆没有重做。", "done"

    async def forbidden(*args, **kwargs):
        raise AssertionError("重新回答的重试不该回到工具路径")

    monkeypatch.setattr(chat, "stream_reply", rewrite)
    monkeypatch.setattr(chat_agent, "answer_note", forbidden)
    url = f"/api/books/{bid}/chat/replies/{reply['id']}/again"
    assert (await client.post(url)).status_code == 202
    assert (await reply_of(client, bid, note["id"]))["payload"]["state"] == "failed"
    assert (await client.post(url)).status_code == 202
    fresh = await reply_of(client, bid, note["id"])
    assert streams == [True, True] and "state" not in fresh["payload"]
    assert fresh["payload"]["memories"] == reply["payload"]["memories"]
    async with sessionmaker() as session:
        assert (await session.execute(select(Memory.id, Memory.version, Memory.deleted_at))).all() == before
