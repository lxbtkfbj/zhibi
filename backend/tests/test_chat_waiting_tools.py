"""任务 3 复核小修：等拍板时先分流，只有提问和记忆进只查只答。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import BookSave, Character, Job, LlmCall, MeetingMessage, Memory
from app.services import group_notes
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import final_message, seed


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


@pytest.fixture
def classified(monkeypatch):
    original = group_notes.classify
    calls = []

    async def observe(session, book_id, text, *args, **kwargs):
        intent = await original(session, book_id, text, *args, **kwargs)
        calls.append((text, intent.kind))
        return intent

    monkeypatch.setattr(group_notes, "classify", observe)
    return calls


async def waiting_book(sessionmaker):
    bid = await seed(sessionmaker, "waiting_author")
    async with sessionmaker() as session:
        session.add(Character(book_id=bid, name="女主", role_type="配角"))
        await session.commit()
    return bid


async def test_waiting_tools_changes_first_require_feedback(client, sessionmaker, classified):
    bid = await waiting_book(sessionmaker)
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "把女主改成师姐"})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "use_feedback", "message": "等你拍板时请直接提意见"}
    assert classified == [("把女主改成师姐", "改设定")]
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(MeetingMessage)) == 0
        assert await session.scalar(select(func.count()).select_from(Memory)) == 0
        assert await session.scalar(select(func.count()).select_from(BookSave)) == 0
        assert (await session.scalar(select(Job))).status == "waiting_author"
        calls = list(await session.scalars(select(LlmCall)))
        assert len(calls) == 1 and calls[0].purpose == "群聊分流" and calls[0].request["method"] != "tools"


async def test_waiting_tools_changes_after_chat_become_plan(client, sessionmaker, classified):
    bid = await waiting_book(sessionmaker)
    await say(client, bid, "楚风现在什么境界？")
    note = await say(client, bid, "把女主改成师姐")
    assert classified == [("楚风现在什么境界？", "提问闲聊"), ("把女主改成师姐", "改设定")]
    outcome = (await final_message(client, bid, note["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "plan_made"
    async with sessionmaker() as session:
        plan = await session.get(MeetingMessage, outcome["plan_id"])
        assert plan.kind == "plan" and plan.payload["status"] == "open" and plan.payload["plan"]["items"]
        assert (await session.scalar(select(Job))).status == "waiting_author"
        assert await session.scalar(select(func.count()).select_from(BookSave)) == 0
        assert await session.scalar(select(func.count()).select_from(Memory)) == 0
        assert (await session.scalar(select(Character).where(Character.name == "女主"))).name == "女主"
        calls = list(await session.scalars(select(LlmCall).order_by(LlmCall.id)))
        assert calls[-1].purpose == "总结方案" and calls[-1].request["method"] != "tools"


@pytest.mark.parametrize(
    "text,kind,remembers",
    [
        ("记住，以后每章结尾留钩子", "写作要求", True),
        ("楚风现在什么境界？", "提问闲聊", False),
    ],
)
async def test_waiting_tools_memory_and_questions_are_classified_read_only(
    client, sessionmaker, classified, text, kind, remembers
):
    bid = await waiting_book(sessionmaker)
    note = await say(client, bid, text)
    assert classified == [(text, kind)]
    assert note["payload"]["ask_only"] and note["payload"]["turn"] == "tools"
    assert not note["payload"].get("steps")
    reply = await reply_of(client, bid, note["id"])
    assert bool(reply["payload"].get("memories")) == remembers
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).order_by(LlmCall.id)))
        assert calls[0].purpose == "群聊分流"
        tools_calls = [call for call in calls if call.request["method"] == "tools"]
        assert tools_calls
        for call in tools_calls:
            names = {tool["function"]["name"] for tool in call.request["schema"]}
            assert "make_changes" not in names
            assert {"remember", "read_memory", "forget"} <= names
        memories = list(await session.scalars(select(Memory)))
        assert len(memories) == int(remembers)
        if remembers:
            assert memories[0].kind == "writing" and memories[0].book_id == bid
        assert (await session.scalar(select(Job))).status == "waiting_author"
        assert await session.scalar(select(func.count()).select_from(BookSave)) == 0
