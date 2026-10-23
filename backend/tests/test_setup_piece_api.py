"""开书拼图接口的等待状态、作者要求与跨书边界；不调用模型。"""

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import Book, Job, Memory, StoryNode
from app.services import jobs
from app.services.job_runner import BOOK_STATUS_WHILE_WAITING


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


@pytest.fixture
def queued(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: calls.append((job_id, resume)))
    return calls


async def gate(sessionmaker, *, kind="setup_piece", piece="outline", confirmed=("concept",), status="waiting_author"):
    async with sessionmaker() as session:
        book = Book(
            title="接口拼图测试",
            status="setting_up",
            settings={"setup_mode": "puzzle"},
            setup_progress={"mode": "puzzle", "current": piece, "pieces": {p: "confirmed" for p in confirmed}},
        )
        other = Book(title="另一部书")
        session.add_all([book, other])
        await session.flush()
        nodes = [
            StoryNode(book_id=book.id, kind="opening", position=1, title="开篇", status="pencil"),
            StoryNode(book_id=book.id, kind="milestone", position=2, title="待补", status="empty"),
            StoryNode(book_id=book.id, kind="milestone", position=3, title="作者铁钉", status="pinned"),
            StoryNode(book_id=other.id, kind="milestone", position=1, title="外书节点"),
        ]
        job = jobs.new_setup_job(book, mode="puzzle")
        job.status = status
        job.pending = {
            "kind": kind,
            "piece": piece,
            "pitches": [{"name": "帝尊重生流", "titles": ["逆世帝尊"]}, {"name": "丹道碾压流"}],
        }
        session.add_all([job, *nodes])
        await session.commit()
        return book.id, job.id, [node.id for node in nodes]


async def requirements(sessionmaker, book_id):
    async with sessionmaker() as session:
        return {
            (row.text, row.source) for row in await session.scalars(select(Memory).where(Memory.book_id == book_id))
        }


async def test_create_new_setup_uses_flow3_and_ignores_ask(client, queued, sessionmaker):
    result = (
        await client.post("/api/books", json={"idea": "少年携古镜寻找身世", "mode": "oneshot", "ask": True})
    ).json()
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(result["job"]["id"]))
        assert job.params["flow"] == 3 and job.params["mode"] == "oneshot"
        assert not job.params.get("ask")


@pytest.mark.parametrize("action", ["confirm", "delegate"])
async def test_confirm_without_piece_and_duplicate_queue_guard(client, queued, sessionmaker, action):
    _, jid, _ = await gate(sessionmaker)
    responses = await asyncio.gather(
        *[client.post(f"/api/jobs/{jid}/piece", json={"action": action}) for _ in range(2)]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(queued) == 1 and queued[0][1]["piece"] == "outline"


@pytest.mark.parametrize("action", ["reopen", "unlock", "candidates", "fill", "approve"])
async def test_retired_actions_are_422_without_writes(client, queued, sessionmaker, action):
    _, jid, _ = await gate(sessionmaker)
    response = await client.post(f"/api/jobs/{jid}/piece", json={"action": action, "piece": "outline"})
    assert response.status_code == 422
    assert not queued


async def test_piece_revision_uses_feedback_and_flips_without_auto_memory(client, queued, sessionmaker):
    bid, jid, _ = await gate(sessionmaker, piece="settings")
    body = {"action": "revise", "feedback": "把境界改成九重天", "flips": [{"topic": "感情线", "choice": "单女主"}]}
    assert (await client.post(f"/api/jobs/{jid}/piece", json=body)).status_code == 200
    assert ("把境界改成九重天", "note") not in await requirements(
        sessionmaker, bid
    )  # 在合成关分块处理，不把整段存成要求。
    assert await requirements(sessionmaker, bid) == set()
    assert queued[0][1]["feedback"] == body["feedback"]
    assert queued[0][1]["flips"] == body["flips"]
    assert queued[0][1]["requirement_saved"]


@pytest.mark.parametrize("body,code", [({"action": "revise"}, 422), ({"action": "confirm", "piece": "concept"}, 409)])
async def test_piece_validation(client, queued, sessionmaker, body, code):
    _, jid, _ = await gate(sessionmaker)
    assert (await client.post(f"/api/jobs/{jid}/piece", json=body)).status_code == code
    assert not queued


async def test_pitch_pick_uses_one_based_index_custom_title_and_300(client, queued, sessionmaker):
    bid, jid, _ = await gate(sessionmaker, kind="setup_pitches")
    response = await client.post(
        f"/api/jobs/{jid}/pitches", json={"action": "pick", "index": 1, "length": 300, "title": "作者自己起的书名"}
    )
    assert response.status_code == 200, response.text
    assert queued[0][1]["index"] == 1 and queued[0][1]["length"] == 300
    assert ("书名用《作者自己起的书名》", "开书时答的") in await requirements(sessionmaker, bid)
    assert BOOK_STATUS_WHILE_WAITING["setup_pitches"] == "setting_up"


@pytest.mark.parametrize(
    "body",
    [
        {"action": "pick", "index": 0},
        {"action": "pick", "index": 3},
        {"action": "pick", "index": 1, "length": 123},
        {"action": "redo", "feedback": "  "},
    ],
)
async def test_pitch_invalid_inputs(client, queued, sessionmaker, body):
    _, jid, _ = await gate(sessionmaker, kind="setup_pitches")
    assert (await client.post(f"/api/jobs/{jid}/pitches", json=body)).status_code == 422
    assert not queued


async def test_redo_keeps_feedback_local_and_old_directions_are_retired(client, queued, sessionmaker):
    bid, jid, _ = await gate(sessionmaker, kind="setup_pitches")
    response = await client.post(
        f"/api/jobs/{jid}/pitches", json={"action": "redo", "feedback": "保留主角，换个金手指"}
    )
    assert response.status_code == 200, response.text
    assert await requirements(sessionmaker, bid) == set()
    assert queued[0][1]["feedback"] == "保留主角，换个金手指"
    old = await client.post(f"/api/jobs/{jid}/directions", json={})
    assert old.status_code == 409 and old.json()["detail"] == "这个任务用的是旧流程，请按新流程重开"
