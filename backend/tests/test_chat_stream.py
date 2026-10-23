"""第五步第一批：聊天回答边写边显示、能停、能重新回答／重试；新书页群聊里 @ 点名由他来答。"""

import asyncio
import json

import httpx
import pytest
from fastapi import BackgroundTasks
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.api import jobs as jobs_api
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, MeetingMessage, Memory
from app.schemas import NoteIn
from app.services import chat, group_notes
from app.services.chat_context import dialogue
from tests.test_chat_task6 import final_message, seed


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


@pytest.fixture
async def redis():
    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield r
    await r.aclose()


async def meeting(client, bid):
    return (await client.get(f"/api/books/{bid}/meeting?limit=2000")).json()


async def events(redis, bid, name):
    return [json.loads(e[1]["data"]) for e in await redis.xrange(f"zhibi:events:{bid}") if e[1]["event"] == name]


async def test_reply_streams_into_one_message(client, sessionmaker, redis):
    bid = await seed(sessionmaker)
    note = (await client.post(f"/api/books/{bid}/notes", json={"content": "为什么楚风要找青灯？"})).json()
    reply = (await meeting(client, bid))[-1]
    assert reply["speaker"] == "chief" and reply["payload"]["reply_to"] == [note["id"]]
    assert reply["content"].startswith("（演示）主编回答") and "state" not in reply["payload"]
    # 先占一条空消息，一点点推字，最后整条换成写完的
    first = next(m for m in await events(redis, bid, "message") if m["id"] == reply["id"])
    assert first["content"] == "" and first["payload"]["state"] == "thinking"
    deltas = [d for d in await events(redis, bid, "chat_delta") if d["id"] == reply["id"]]
    assert deltas and reply["content"].startswith(deltas[-1]["text"].strip())
    final = [m for m in await events(redis, bid, "message_update") if m["id"] == reply["id"]][-1]
    assert final["content"] == reply["content"]


async def test_ask_picks_who_answers(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    # 明显的提问：不分流，直接由点了名的人答
    note = (await client.post(f"/api/books/{bid}/notes", json={"content": "你叫什么？", "ask": "writer"})).json()
    assert note["payload"]["ask"] == "writer"
    assert (await meeting(client, bid))[-1]["speaker"] == "writer"

    # 分流判断成闲聊：也照点的名，不照分流挑的人
    async def chat_intent(*args, **kwargs):
        return s.LibraryIntent(kind="提问闲聊", who="主编")

    monkeypatch.setattr(group_notes, "classify", chat_intent)
    await client.post(f"/api/books/{bid}/notes", json={"content": "随便聊聊", "ask": "reviewer"})
    last = (await meeting(client, bid))[-1]
    assert last["speaker"] == "reviewer" and last["content"].startswith("（演示）审稿回答")

    # 私聊的 to 和点名分开：私聊里不记点名
    note = (
        await client.post(f"/api/books/{bid}/notes", json={"content": "在吗？", "to": "chief", "ask": "writer"})
    ).json()
    assert "ask" not in note["payload"]


async def test_stop_keeps_what_was_written(client, sessionmaker, monkeypatch, redis):
    bid = await seed(sessionmaker)

    async def slow(book_id, role, template, **values):
        yield "写到一半"
        await asyncio.sleep(30)
        yield "不该出现"

    monkeypatch.setattr(chat, "stream_model", slow)
    background = BackgroundTasks()
    async with sessionmaker() as session:
        await jobs_api.add_note(
            NoteIn(content="为什么？", to="writer"), background, await session.get(Book, bid), session, redis
        )
    task = asyncio.create_task(background())
    for _ in range(200):
        if await events(redis, bid, "chat_delta"):
            break
        await asyncio.sleep(0.05)
    reply_id = (await events(redis, bid, "chat_delta"))[-1]["id"]
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply_id}/stop")).status_code == 200
    await asyncio.wait_for(task, 10)
    reply = await final_message(client, bid, reply_id)
    assert reply["content"] == "写到一半" and reply["payload"]["state"] == "stopped"
    # 停下的回答算说过的话，后面接着聊带得上
    async with sessionmaker() as session:
        assert reply_id in [m.id for m in await dialogue(session, bid, "writer")]
    # 写完的再点停，什么也不动
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply_id}/stop")).status_code == 200
    assert (await final_message(client, bid, reply_id))["payload"]["state"] == "stopped"


async def test_again_rewrites_latest_reply_in_place(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    calls = []

    async def numbered(book_id, role, template, **values):
        calls.append(values["note"])
        yield f"第{len(calls)}次回答"

    monkeypatch.setattr(chat, "stream_model", numbered)
    note = (await client.post(f"/api/books/{bid}/notes", json={"content": "为什么？"})).json()
    reply = (await meeting(client, bid))[-1]
    assert reply["content"] == "第1次回答"
    res = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
    assert res.status_code == 202 and res.json()["content"] == "" and res.json()["payload"]["state"] == "thinking"
    again = await final_message(client, bid, reply["id"])
    assert again["content"] == "第2次回答" and "state" not in again["payload"]
    assert again["payload"]["reply_to"] == [note["id"]] and calls == ["为什么？", "为什么？"]
    assert len([m for m in await meeting(client, bid) if m["speaker"] == "chief"]) == 1

    # 后面又聊了：前面那条不能重新回答
    await client.post(f"/api/books/{bid}/notes", json={"content": "还有呢？"})
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 409
    # 不是回答的消息不认
    assert (await client.post(f"/api/books/{bid}/chat/replies/{note['id']}/again")).status_code == 404


async def test_failure_marks_reply_and_retry_answers(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    tries = []

    async def flaky(book_id, role, template, **values):
        tries.append(values["note"])
        if len(tries) == 1:
            raise TimeoutError("模型 90 秒还没开口")
        yield "这回答上来了"

    monkeypatch.setattr(chat, "stream_model", flaky)
    first = (await client.post(f"/api/books/{bid}/notes", json={"content": "为什么？"})).json()
    failed = (await meeting(client, bid))[-1]
    assert failed["payload"]["state"] == "failed" and failed["payload"]["error"] == "模型 90 秒还没开口"
    # 没答上来的不算说过的话，也不自动再答：下一句只答下一句
    second = (await client.post(f"/api/books/{bid}/notes", json={"content": "那后面呢？"})).json()
    latest = (await meeting(client, bid))[-1]
    assert latest["payload"]["reply_to"] == [second["id"]] and latest["content"] == "这回答上来了"
    async with sessionmaker() as session:
        assert failed["id"] not in [m.id for m in await dialogue(session, bid, "group")]
    # 失败的那条后面又聊了，就不能再重试
    assert (await client.post(f"/api/books/{bid}/chat/replies/{failed['id']}/again")).status_code == 409
    assert tries == ["为什么？", "那后面呢？"] and first["id"] in failed["payload"]["reply_to"]


async def test_retry_after_failure(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    tries = []

    async def flaky(book_id, role, template, **values):
        tries.append(1)
        if len(tries) == 1:
            raise ValueError("中转站断了")
        yield "重试答上来了"

    monkeypatch.setattr(chat, "stream_model", flaky)
    await client.post(f"/api/books/{bid}/notes", json={"content": "为什么？"})
    failed = (await meeting(client, bid))[-1]
    assert failed["payload"]["state"] == "failed"
    assert (await client.post(f"/api/books/{bid}/chat/replies/{failed['id']}/again")).status_code == 202
    done = await final_message(client, bid, failed["id"])
    assert done["content"] == "重试答上来了" and "error" not in done["payload"] and "state" not in done["payload"]


async def test_restart_marks_half_written_replies(sessionmaker, redis):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        row = MeetingMessage(
            book_id=bid, speaker="chief", kind="speech", content="", payload={"reply_to": [1], "state": "streaming"}
        )
        session.add(row)
        await session.commit()
        rid = row.id
    await chat.clean_live_replies(redis)
    async with sessionmaker() as session:
        row = await session.scalar(select(MeetingMessage).where(MeetingMessage.id == rid))
        assert row.payload["state"] == "failed" and "重启" in row.payload["error"]


async def test_answer_knows_what_the_editors_did(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    seen = []

    async def capture(book_id, role, template, **values):
        seen.append(values)
        yield "好。"

    monkeypatch.setattr(chat, "stream_model", capture)
    # 演示分流：这句记成写作要求
    await client.post(f"/api/books/{bid}/notes", json={"content": "以后每章都要有一场打斗"})
    await client.post(f"/api/books/{bid}/notes", json={"content": "刚才那条记上了吗？"})
    recent, hint = seen[-1]["recent"], seen[-1]["how_to_apply"]
    assert "以后每章都要有一场打斗（编辑部照这句做了：记住了：以后每章都要有一场打斗（写书时照做））" in recent
    assert "已经照办了" in hint and "别说成没生效" in hint
    # 私聊照旧：聊的都还没生效
    await client.post(f"/api/books/{bid}/notes", json={"content": "为什么？", "to": "chief"})
    assert "聊天里说的都还没生效" in seen[-1]["how_to_apply"]


def test_done_note_lists_each_step():
    from types import SimpleNamespace

    from app.services.chat_context import done_note

    message = SimpleNamespace(
        speaker="author",
        payload={
            "steps": [
                {"kind": "outline", "target_label": "第 1 篇"},
                {"kind": "outline", "target_label": "全书结局"},
                {"kind": "chat"},
            ]
        },
    )
    assert (
        done_note(message)
        == "（编辑部照这句做了：写好了大纲里的第 1 篇，已经换上去；写好了大纲里的全书结局，已经换上去）"
    )
    assert done_note(SimpleNamespace(speaker="author", payload={"outcome": {"kind": "chat"}})) == ""
    assert done_note(SimpleNamespace(speaker="chief", payload={"outcome": {"kind": "edit"}})) == ""


async def test_revert_is_recorded_on_the_message(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    seen = []

    async def capture(book_id, role, template, **values):
        seen.append(values["recent"])
        yield "好。"

    monkeypatch.setattr(chat, "stream_model", capture)
    note = (await client.post(f"/api/books/{bid}/notes", json={"content": "以后每章都要有一场打斗"})).json()
    outcome = (await final_message(client, bid, note["id"]))["payload"]["outcome"]
    # 改完当场的前后对照：写作要求原来没有，改成这一句
    assert outcome["memory"]["summary"] == "以后每章都要有一场打斗"
    assert "change" not in outcome
    # 消息下面点「换回原来的」：删了这条要求，记到消息上
    marked = await client.post(
        f"/api/books/{bid}/memories/{outcome['memory']['id']}/undo", json={"version": outcome["memory"]["version"]}
    )
    assert marked.status_code == 200
    assert (await final_message(client, bid, note["id"]))["payload"]["outcome"]["undone"] is True
    async with sessionmaker() as session:
        assert (await session.get(Memory, int(outcome["requirement_id"]))).deleted_at is not None
    assert (
        await client.post(
            f"/api/books/{bid}/memories/{outcome['memory']['id']}/undo", json={"version": outcome["memory"]["version"]}
        )
    ).status_code == 409
    await client.post(f"/api/books/{bid}/notes", json={"content": "刚才那条还算数吗？"})
    assert "（编辑部照这句做了：记住了：以后每章都要有一场打斗（写书时照做）（作者点了撤销））" in seen[-1]

    # 拆成好几件事的：换回记在那一件上；没改过书的不能换
    async with sessionmaker() as session:
        row = MeetingMessage(
            book_id=bid,
            speaker="author",
            kind="note",
            content="开局和结局都写一下",
            payload={
                "steps": [
                    {"kind": "outline", "target_label": "第 1 篇"},
                    {"kind": "outline", "target_label": "全书结局"},
                ]
            },
        )
        session.add(row)
        await session.commit()
        sid = row.id
    assert (await client.post(f"/api/books/{bid}/notes/{sid}/revert", json={"step": 1})).status_code == 422
    assert (await client.post(f"/api/books/{bid}/notes/{sid}/revert", json={"step": 5})).status_code == 422
    # 编辑部的话、别的书的消息不认
    reply = next(m for m in await meeting(client, bid) if m["speaker"] != "author")
    assert (await client.post(f"/api/books/{bid}/notes/{reply['id']}/revert", json={})).status_code == 404
