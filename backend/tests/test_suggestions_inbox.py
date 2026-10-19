"""第四步第二批：新书页「待处理」。同意以后当场有改前改后、能换回原来的；只说了毛病的「让编辑部改」发到聊天里。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import Job, MeetingMessage, SettingSuggestion, WorldEntry
from tests.test_library_api import create_entry, make_book, make_suggestion


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


@pytest.fixture(autouse=True)
def no_worker(monkeypatch):
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


async def test_accept_shows_before_after_and_can_be_taken_back(client, sessionmaker):
    book = await make_book(sessionmaker)
    entry = await create_entry(client, book, one_line="旧的一句话")
    sid = await make_suggestion(
        sessionmaker,
        book,
        {
            "op": "set_field",
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "one_line",
            "value": "新的一句话",
        },
        target_type="entry",
        target_id=uuid.UUID(entry["id"]),
    )
    res = await client.post(f"/api/suggestions/{sid}/accept")
    assert res.status_code == 200, res.text
    result = res.json()["payload"]["result"]
    assert result["target_label"] and result["change"]
    # 改的就是那一条；前后对照里看得到原来、现在
    assert [row["table"] for row in result["change"]] == ["world_entries"]
    shown = " ".join(f"{d.get('before', '')}|{d.get('after', '')}" for d in result["diff"])
    assert "旧的一句话" in shown and "新的一句话" in shown
    assert (await client.get(f"/api/books/{book}/suggestion-changes")).json() == {str(sid): True}
    res = await client.post(f"/api/suggestions/{sid}/revert")
    assert res.status_code == 200, res.text
    assert res.json()["payload"]["result"]["undone"] and res.json()["status"] == "accepted"
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, uuid.UUID(entry["id"]))).one_line == "旧的一句话"
    assert (await client.get(f"/api/books/{book}/suggestion-changes")).json() == {str(sid): False}
    assert (await client.post(f"/api/suggestions/{sid}/revert")).status_code == 409


async def test_cannot_take_back_after_the_place_changed_again(client, sessionmaker):
    book = await make_book(sessionmaker)
    entry = await create_entry(client, book, one_line="旧")
    sid = await make_suggestion(
        sessionmaker,
        book,
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "one_line", "value": "新"},
    )
    assert (await client.post(f"/api/suggestions/{sid}/accept")).status_code == 200
    res = await client.patch(f"/api/world-entries/{entry['id']}", json={"one_line": "作者自己改的"})
    assert res.status_code == 200, res.text
    assert (await client.get(f"/api/books/{book}/suggestion-changes")).json() == {str(sid): False}
    res = await client.post(f"/api/suggestions/{sid}/revert")
    assert res.status_code == 409 and "后来又改过" in res.json()["detail"]


async def test_accept_all_only_changes_leaves_opinions(client, sessionmaker):
    book = await make_book(sessionmaker)
    entry = await create_entry(client, book, one_line="旧")
    change = await make_suggestion(
        sessionmaker,
        book,
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "one_line", "value": "新"},
    )
    opinion = await make_suggestion(sessionmaker, book, {"op": "note", "why": "名场面不够"})
    async with sessionmaker() as session:
        said = SettingSuggestion(book_id=book, kind="chat", title="群聊里说的", payload={"op": "note", "content": "改"})
        session.add(said)
        await session.commit()
        said = said.id
    res = await client.post(f"/api/books/{book}/suggestions/accept-all?only_changes=true")
    assert res.status_code == 200, res.text
    assert res.json()["accepted"] == [str(change)]
    pending = {row["id"] for row in (await client.get(f"/api/books/{book}/suggestions")).json()}
    assert pending == {str(opinion), str(said)}
    accepted = (await client.get(f"/api/books/{book}/suggestions?status=accepted")).json()
    assert accepted[0]["payload"]["result"]["diff"]


async def test_hand_over_sends_a_line_to_the_chat(client, sessionmaker):
    book = await make_book(sessionmaker)
    async with sessionmaker() as session:
        row = SettingSuggestion(
            book_id=book,
            kind="review",
            title="第 12 章：沈九说没见过柳三爷，第 3 章却见过",
            payload={"op": "note"},
        )
        session.add(row)
        await session.commit()
        sid = row.id
    conv = (await client.post(f"/api/books/{book}/chat/conversations")).json()["id"]
    res = await client.post(f"/api/suggestions/{sid}/to-chat", json={"conv": conv})
    assert res.status_code == 201, res.text
    note = res.json()
    assert note["content"] == "照这条意见改：第 12 章：沈九说没见过柳三爷，第 3 章却见过"
    assert note["payload"]["conv"] == conv and note["speaker"] == "author"
    async with sessionmaker() as session:
        row = await session.get(SettingSuggestion, sid)
        assert row.status == "accepted" and row.payload["result"] == {"to_chat": note["id"]}
        assert await session.scalar(select(MeetingMessage).where(MeetingMessage.id == note["id"]))
    assert (await client.post(f"/api/suggestions/{sid}/to-chat")).status_code == 409


async def test_hand_over_refuses_concrete_changes_and_busy_editorial(client, sessionmaker):
    book = await make_book(sessionmaker)
    entry = await create_entry(client, book)
    concrete = await make_suggestion(
        sessionmaker,
        book,
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "one_line", "value": "新"},
    )
    assert (await client.post(f"/api/suggestions/{concrete}/to-chat")).status_code == 422
    opinion = await make_suggestion(sessionmaker, book, {"op": "note"})
    async with sessionmaker() as session:
        session.add(Job(book_id=book, thread_id=str(uuid.uuid4()), kind="write_book", status="running", params={}))
        await session.commit()
    res = await client.post(f"/api/suggestions/{opinion}/to-chat")
    assert res.status_code == 409 and "等这一轮做完" in res.json()["detail"]
