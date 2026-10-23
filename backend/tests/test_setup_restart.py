"""旧任务只能显式重开：清空产物但保护历史，原始检查点只提供作者已选材料。"""

import asyncio
import json
import uuid
from copy import deepcopy
from typing import TypedDict

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.graphs.book_setup import restart_state, route_start
from app.llm import demo
from app.main import create_app
from app.models import (
    Book,
    Character,
    DraftVersion,
    Foreshadowing,
    Job,
    LlmCall,
    MeetingMessage,
    Memory,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    StoryNode,
    StoryThread,
    Volume,
    WorldEntry,
)
from app.services import jobs
from app.services.job_runner import execute_job
from app.services.meeting import stream_key
from app.services.setup_store import load_setup, save_setup
from tests.test_story_map_store import sample_setup


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, resume=None: calls.append((jid, resume)))
    return calls


async def old_job(sessionmaker, *, confirmed=True, status="waiting_author", book_status="setting_up", flow=None):
    async with sessionmaker() as session:
        book = Book(idea="寻找失踪妹妹", style_reference="短句", status=book_status)
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        book.setup_progress = {"pieces": {"concept": "confirmed" if confirmed else "waiting"}, "current": "nodes"}
        job = Job(
            book_id=book.id,
            kind="book_setup",
            thread_id=f"legacy-{uuid.uuid4()}",
            status=status,
            params={"mode": "puzzle", **({"flow": flow} if flow is not None else {})},
            pending={"kind": "setup_piece", "piece": "nodes"},
        )
        session.add(job)
        await session.flush()
        session.add_all(
            [
                Memory(book_id=book.id, text="妹妹不能失忆", source="answer"),
                MeetingMessage(book_id=book.id, job_id=job.id, speaker="author", content="旧会议记录"),
                DraftVersion(
                    book_id=book.id, job_id=job.id, note="作者旧稿", payload={"spine": {"opening": "不能删除的历史"}}
                ),
                LlmCall(book_id=book.id, job_id=job.id, role="chief", purpose="旧调用"),
            ]
        )
        await session.commit()
        return book.id, job.id


@pytest.mark.parametrize("confirmed", [True, False])
async def test_restart_is_atomic_preserves_author_history_and_other_book(client, queued, sessionmaker, confirmed):
    bid, jid = await old_job(sessionmaker, confirmed=confirmed)
    other_bid, _ = await old_job(sessionmaker)
    async with sessionmaker() as session:
        before = await load_setup(session, other_bid)
        old_concept = deepcopy((await session.get(Book, bid)).concept)
    response = await client.post(f"/api/jobs/{jid}/restart-setup")
    assert response.status_code == 200, response.text
    new_id = uuid.UUID(response.json()["id"])
    assert response.json()["setup_flow"] == 3 and queued == [(new_id, None)]
    async with Redis.from_url(get_settings().redis_url, decode_responses=True) as redis:
        events = [
            json.loads(fields["data"]) for _, fields in await redis.xrange(stream_key(bid)) if fields["event"] == "job"
        ]
    assert [(event["id"], event["status"]) for event in events] == [(str(jid), "cancelled"), (str(new_id), "queued")]
    async with sessionmaker() as session:
        old, new, book = await session.get(Job, jid), await session.get(Job, new_id), await session.get(Book, bid)
        assert old.status == "cancelled" and old.finished_at
        assert new.params == {
            "flow": 3,
            "idea": "寻找失踪妹妹",
            "style_reference": "短句",
            "mode": "puzzle",
            "restart_from": str(jid),
            "keep_concept": confirmed,
            "prefill": False,
        }
        assert book.title == old_concept["title"]
        assert book.concept == (old_concept if confirmed else {})
        assert book.protagonist == book.world == book.spine == book.setup_progress == {}
        pinned = list(await session.scalars(select(StoryNode).where(StoryNode.book_id == bid)))
        assert pinned and all(row.status == "pinned" for row in pinned)
        pinned_ids = {row.id for row in pinned}
        anchors = list(await session.scalars(select(NodeAnchor).where(NodeAnchor.book_id == bid)))
        assert all(row.node_id in pinned_ids for row in anchors)
        heroes = list(await session.scalars(select(Character).where(Character.book_id == bid)))
        assert {row.id for row in heroes} <= {row.character_id for row in anchors}
        for model in (Secret, Foreshadowing):
            rows = list(await session.scalars(select(model).where(model.book_id == bid)))
            assert all(row.node_id in pinned_ids for row in rows)
        for model in (Relationship, WorldEntry, PlotUnit, Volume, StoryThread):
            assert await session.scalar(select(func.count()).select_from(model).where(model.book_id == bid)) == 0
        for model in (Memory, DraftVersion, LlmCall):
            assert await session.scalar(select(func.count()).select_from(model).where(model.book_id == bid)) == 1
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.book_id == bid).order_by(MeetingMessage.id)
            )
        )
        assert [item.content for item in messages[:2]] == ["旧会议记录", "按新流程重开开书。"]
        assert ("和已确认的定调" in messages[-1].content) is confirmed
        assert await load_setup(session, other_bid) == before
    assert (await client.post(f"/api/jobs/{jid}/restart-setup")).status_code == 409
    assert len(queued) == 1


async def test_concurrent_restart_creates_and_enqueues_only_once(client, queued, sessionmaker):
    bid, jid = await old_job(sessionmaker)
    responses = await asyncio.gather(*[client.post(f"/api/jobs/{jid}/restart-setup") for _ in range(2)])
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(queued) == 1
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Job).where(Job.book_id == bid)) == 2


@pytest.mark.parametrize(
    ("status", "book_status", "flow", "message"),
    [
        ("queued", "setting_up", None, "编辑部正在工作，先停止再重开"),
        ("running", "setting_up", None, "编辑部正在工作，先停止再重开"),
        ("waiting_author", "ready", None, "这本书已经开完了，不需要重开"),
        ("failed", "writing", None, "这本书已经开完了，不需要重开"),
        ("waiting_author", "setting_up", 3, "这个任务不需要重开"),
    ],
)
async def test_restart_rejects_wrong_state_without_writes(
    client, queued, sessionmaker, status, book_status, flow, message
):
    bid, jid = await old_job(sessionmaker, status=status, book_status=book_status, flow=flow)
    async with sessionmaker() as session:
        before = await load_setup(session, bid)
    response = await client.post(f"/api/jobs/{jid}/restart-setup")
    assert response.status_code == 409 and response.json()["detail"] == message
    assert not queued
    async with sessionmaker() as session:
        assert await load_setup(session, bid) == before


@pytest.mark.parametrize(
    ("path", "pending", "body"),
    [
        ("decision", {"kind": "setup_review"}, {"action": "approve"}),
        ("directions", {"kind": "setup_directions"}, {"action": "redo", "feedback": "换一轮"}),
        ("piece", {"kind": "setup_piece", "piece": "nodes"}, {"action": "confirm", "piece": "concept"}),
        ("answers", {"kind": "setup_questions"}, {"answers": []}),
    ],
)
async def test_legacy_gate_rejects_before_any_queue(client, queued, sessionmaker, path, pending, body):
    _, jid = await old_job(sessionmaker)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.pending = pending
        await session.commit()
    response = await client.post(f"/api/jobs/{jid}/{path}", json=body)
    assert response.status_code == 409
    assert "按新流程重开" in response.json()["detail"]
    assert not queued


async def test_legacy_worker_never_builds_graph_and_waiting_redelivery_is_noop(sessionmaker, monkeypatch):
    bid, jid = await old_job(sessionmaker)

    def forbidden():
        raise AssertionError("旧任务不得建图或恢复检查点")

    monkeypatch.setitem(
        __import__("app.services.job_runner", fromlist=["GRAPHS"]).GRAPHS, "book_setup", (forbidden, forbidden)
    )
    await execute_job(jid, checkpoint_dsn="postgresql://invalid/never-connect")
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "waiting_author"
    await execute_job(jid, {"action": "confirm"}, checkpoint_dsn="postgresql://invalid/never-connect")
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "failed" and job.error == jobs.LEGACY_SETUP_MESSAGE
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.book_id == bid).order_by(MeetingMessage.id)
            )
        )
        assert messages[-1].content == jobs.LEGACY_SETUP_MESSAGE


@pytest.mark.parametrize("mode", ["puzzle", "oneshot"])
def test_restart_state_only_carries_author_materials(mode):
    params = {"idea": "原点子", "style_reference": "原风格", "mode": mode, "keep_concept": True}
    old = {
        "direction": {"name": "作者选的方向", "logline": "少年找回妹妹"},
        "spine": {"ending": "弃用"},
        "queue": ["lore"],
        "brief": ["不能复制旧要求"],
    }
    concept = {"title": "作者书名", "protagonist_hook": "旧钩子"}
    state = restart_state(params, old, concept)
    assert state["flow"] == 3 and state["piece"] == "concept"
    assert (
        state["previous"]
        == "【之前按旧流程选过的方向】\n作者选的方向：少年找回妹妹\n（作者之前选过它，三个故事方向里请保留它的好东西。）"
    )
    assert state["queue"] == ["concept"] and state["brief"] == []
    assert "spine" not in state and state["pieces"]["concept"] != "confirmed"
    assert route_start(state) == "pitches"
    assert restart_state(params, {}, concept)["previous"] == ""


@pytest.mark.parametrize("checkpoint_exists", [True, False])
async def test_worker_reads_raw_old_checkpoint_or_gracefully_starts_without_it(
    client, queued, sessionmaker, monkeypatch, checkpoint_exists
):
    from app.graphs import book_setup

    monkeypatch.setattr(demo, "DELAY_S", 0)
    bid, jid = await old_job(sessionmaker)
    async with sessionmaker() as session:
        old = await session.get(Job, jid)
        thread_id = old.thread_id
    raw = {"direction": {"name": "旧检查点已选方向"}, "retired_only": {"never_decode_by_new_graph": True}}
    if checkpoint_exists:

        class OldState(TypedDict):
            direction: dict
            retired_only: dict

        graph = StateGraph(OldState)
        graph.add_node("old_setup", lambda state: state)
        graph.add_edge(START, "old_setup")
        graph.add_edge("old_setup", END)
        async with AsyncPostgresSaver.from_conn_string(get_settings().checkpoint_dsn) as saver:
            await saver.setup()
            await graph.compile(checkpointer=saver).ainvoke(raw, {"configurable": {"thread_id": thread_id}})
    captured = []
    original = book_setup.restart_state

    def capture(params, values, concept):
        captured.append(deepcopy(values))
        return original(params, values, concept)

    monkeypatch.setattr(book_setup, "restart_state", capture)
    response = await client.post(f"/api/jobs/{jid}/restart-setup")
    assert response.status_code == 200, response.text
    new_id = uuid.UUID(response.json()["id"])
    await execute_job(new_id)
    async with sessionmaker() as session:
        job = await session.get(Job, new_id)
        assert job.status == "waiting_author", job.error
        if checkpoint_exists:
            assert captured[0]["retired_only"] == raw["retired_only"]
            assert job.pending["kind"] == "setup_pitches" and job.pending["flow"] == 3
        else:
            assert captured == [{}]
            assert job.pending["kind"] == "setup_pitches"
        assert (await session.get(Book, bid)).idea == "寻找失踪妹妹"


@pytest.mark.parametrize("status", ["waiting_author", "failed", "cancelled", "running"])
async def test_legacy_private_note_only_chats_without_resuming_old_graph(client, sessionmaker, queued, status):
    bid, jid = await old_job(sessionmaker, status=status)
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "保留妹妹的记忆", "to": "lorekeeper"})
    assert response.status_code == 201, response.text
    assert response.json()["job_id"] is None
    assert response.json()["payload"]["thread"] == "lorekeeper"
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == status
        requirements = list((await session.scalars(select(Memory).where(Memory.book_id == bid))).all())
        assert all(row.text != "保留妹妹的记忆" for row in requirements)
        reply = await session.scalar(
            select(MeetingMessage).where(MeetingMessage.book_id == bid).order_by(MeetingMessage.id.desc())
        )
        assert reply.speaker == "lorekeeper" and "（演示）设定师回答：" in reply.content
        assert reply.job_id is None and reply.payload["reply_to"] == [response.json()["id"]]
    assert queued == []
    if status == "waiting_author":
        assert (await client.post(f"/api/books/{bid}/notes", json={"content": "下一章快一点"})).status_code == 201
        async with sessionmaker() as session:
            assert (await session.get(Job, jid)).status == status
            assert any(
                row.summary == "下一章快一点"
                for row in await session.scalars(select(Memory).where(Memory.book_id == bid))
            )
        assert queued == []


async def test_new_setup_waiting_private_note_only_chats(client, sessionmaker):
    bid, _ = await old_job(sessionmaker, flow=3)
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "按原流程提意见", "to": "chief"})
    assert response.status_code == 201
    assert response.json()["payload"]["outcome"] == {"kind": "chat"}
    assert response.json()["job_id"] is None
