"""开书拼图接口的等待状态、作者要求与跨书边界；不调用模型。"""

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import AuthorRequirement, Book, Job, MeetingMessage, StoryNode
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


async def gate(sessionmaker, *, kind="setup_piece", piece="segment", confirmed=("concept",), status="waiting_author"):
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
        job.pending = {"kind": kind, "piece": piece, "directions": [{"name": "青灯寿命"}, {"name": "古镜追凶"}]}
        session.add_all([job, *nodes])
        await session.commit()
        return book.id, job.id, [node.id for node in nodes]


async def requirements(sessionmaker, book_id):
    async with sessionmaker() as session:
        return {
            (row.text, row.source)
            for row in await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == book_id))
        }


async def test_create_book_mode_defaults_override_and_immutable(client, sessionmaker, queued):
    assert (await client.get("/api/settings/new-book-defaults")).json()["settings"]["setup_mode"] == "puzzle"
    await client.put("/api/settings/new-book-defaults", json={"setup_mode": "puzzle"})
    inherited = (await client.post("/api/books", json={"idea": "少年携古镜寻找身世"})).json()
    explicit = (
        await client.post("/api/books", json={"idea": "少年携青灯逆天改命", "mode": "oneshot", "ask": True})
    ).json()
    async with sessionmaker() as session:
        for result, expected in [(inherited, "puzzle"), (explicit, "oneshot")]:
            book = await session.get(Book, uuid.UUID(result["book"]["id"]))
            job = await session.get(Job, uuid.UUID(result["job"]["id"]))
            assert book.settings["setup_mode"] == job.params["mode"] == expected
    path = f"/api/books/{inherited['book']['id']}/settings"
    assert (await client.patch(path, json={"setup_mode": "oneshot"})).status_code == 409
    assert (await client.patch(path, json={"setup_mode": "puzzle", "chapter_words": 2400})).status_code == 200
    assert (await client.post("/api/books", json={"idea": "少年携古镜寻找身世", "mode": "wrong"})).status_code == 422
    assert BOOK_STATUS_WHILE_WAITING["setup_directions"] == BOOK_STATUS_WHILE_WAITING["setup_piece"] == "setting_up"


async def test_choose_direction_records_length_direction_mix_and_resume(client, sessionmaker, queued):
    book_id, job_id, _ = await gate(sessionmaker, kind="setup_directions")
    response = await client.post(
        f"/api/jobs/{job_id}/directions",
        json={"action": "choose", "choice": 1, "length": "100 万字", "mix": "保留青灯的代价"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert queued[-1][1] == {
        "action": "choose",
        "choice": 1,
        "title": None,
        "mix": "保留青灯的代价",
        "length": "100 万字",
        "feedback": "",
        "requirement_saved": True,
    }
    assert await requirements(sessionmaker, book_id) == {
        ("这本书打算写多长？——100 万字", "answer"),
        ("开书方向：选用「古镜追凶」；混搭：保留青灯的代价", "answer"),
    }
    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    assert messages[-1]["content"] == "选方向「古镜追凶」。\n混搭：保留青灯的代价"
    assert messages[-1]["payload"]["requirement_saved"]
    assert (
        await client.post(f"/api/jobs/{job_id}/directions", json={"action": "redo", "feedback": "改方向"})
    ).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"action": "choose", "choice": 99, "length": "100 万字"},
        {"action": "choose", "length": "100 万字"},
        {"action": "choose", "choice": 0, "length": "  "},
        {"action": "choose", "choice": 0, "length": "100 万字", "title": "旧方向没有这个候选"},
        {"action": "redo", "feedback": "  "},
    ],
)
async def test_direction_invalid_input_is_atomic(client, sessionmaker, queued, body):
    book_id, job_id, _ = await gate(sessionmaker, kind="setup_directions")
    assert (await client.post(f"/api/jobs/{job_id}/directions", json=body)).status_code == 422
    assert not queued and not await requirements(sessionmaker, book_id)
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "waiting_author"


async def test_direction_redo_and_wrong_legacy_endpoint(client, sessionmaker, queued):
    book_id, job_id, _ = await gate(sessionmaker, kind="setup_directions")
    assert (await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})).status_code == 409
    assert (await client.post(f"/api/books/{book_id}/notes", json={"content": "换个方向"})).status_code == 409
    response = await client.post(
        f"/api/jobs/{job_id}/directions", json={"action": "redo", "feedback": "  换成女主视角  "}
    )
    assert response.status_code == 200
    assert await requirements(sessionmaker, book_id) == {("换成女主视角", "note")}
    assert queued[-1][1]["feedback"] == "换成女主视角"


async def test_choose_direction_validates_title_in_selected_card_and_saves_answer(client, sessionmaker, queued):
    book_id, job_id, _ = await gate(sessionmaker, kind="setup_directions")
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        job.pending = {
            **job.pending,
            "directions": [
                {"name": "青灯寿命", "titles": ["青灯渡命", "借命少年"]},
                {"name": "古镜追凶", "titles": ["镜中追凶", "捕快照夜"]},
            ],
        }
        await session.commit()
    path = f"/api/jobs/{job_id}/directions"
    body = {"action": "choose", "choice": 1, "length": "约 200 万字（长篇，约 670 章）"}
    for invalid in ("青灯渡命", "不存在的书名", "", " 镜中追凶 "):
        response = await client.post(path, json={**body, "title": invalid})
        assert response.status_code == 422, response.text
        assert not queued and not await requirements(sessionmaker, book_id)
        assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "waiting_author"
    response = await client.post(path, json={**body, "title": "镜中追凶"})
    assert response.status_code == 200, response.text
    assert ("书名用《镜中追凶》", "answer") in await requirements(sessionmaker, book_id)
    assert queued[-1][1]["title"] == "镜中追凶"
    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    assert messages[-1]["content"] == "选方向「古镜追凶」，书名用《镜中追凶》。"


async def test_piece_revise_flips_and_feedback_are_durable(client, sessionmaker, queued):
    book_id, job_id, nodes = await gate(sessionmaker)
    body = {
        "action": "revise",
        "piece": "segment",
        "node_id": str(nodes[1]),
        "feedback": "  转折提前  ",
        "flips": [{"topic": "感情线", "choice": "单女主"}],
    }
    response = await client.post(f"/api/jobs/{job_id}/piece", json=body)
    assert response.status_code == 200, response.text
    assert await requirements(sessionmaker, book_id) == {("转折提前", "note"), ("「感情线」改成：单女主", "answer")}
    assert queued[-1][1] == {**body, "feedback": "转折提前", "requirement_saved": True}


@pytest.mark.parametrize("action", ["confirm", "delegate", "candidates", "fill", "revise"])
async def test_piece_supported_actions(client, sessionmaker, queued, action):
    book_id, job_id, nodes = await gate(sessionmaker)
    body = {"action": action, "piece": "segment"}
    if action in ("candidates", "fill", "revise"):
        body["node_id"] = str(nodes[1])
    if action == "fill":
        body["feedback"] = "中间要有一场宗门大比"
    response = await client.post(f"/api/jobs/{job_id}/piece", json=body)
    assert response.status_code == 200, response.text
    assert queued[-1][1]["requirement_saved"]
    assert not await requirements(sessionmaker, book_id)  # fill 的一句话不变成全书作者要求
    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    assert (
        messages[-1]["content"]
        == {
            "confirm": "确认「第一段」，下一块。",
            "delegate": "「第一段」交给编辑部定。",
            "candidates": "给节点 2 出 3 个候选。",
            "fill": "节点 2：中间要有一场宗门大比",
            "revise": "请修改节点 2「待补」。",
        }[action]
    )


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"action": "confirm", "piece": "world"}, 409),
        ({"action": "revise", "piece": "segment", "feedback": " "}, 422),
        ({"action": "candidates", "piece": "segment"}, 422),
        ({"action": "fill", "piece": "segment"}, 422),
        ({"action": "reopen", "piece": "segment"}, 422),
        ({"action": "unlock", "piece": "world"}, 422),
        ({"action": "revise", "piece": "segment", "flips": [{"topic": " ", "choice": "x"}]}, 422),
    ],
)
async def test_piece_rejects_invalid_and_stale_requests(client, sessionmaker, queued, body, expected):
    book_id, job_id, _ = await gate(sessionmaker)
    response = await client.post(f"/api/jobs/{job_id}/piece", json=body)
    assert response.status_code == expected, response.text
    assert not queued and not await requirements(sessionmaker, book_id)


async def test_piece_cross_book_current_piece_and_pinned_guards(client, sessionmaker, queued):
    _, job_id, nodes = await gate(sessionmaker)
    path = f"/api/jobs/{job_id}/piece"
    assert (
        await client.post(path, json={"action": "fill", "piece": "segment", "node_id": str(nodes[3])})
    ).status_code == 422
    assert (
        await client.post(path, json={"action": "fill", "piece": "segment", "node_id": str(nodes[2])})
    ).status_code == 409
    _, cast_job, cast_nodes = await gate(sessionmaker, piece="world", confirmed=("concept", "segment"))
    assert (
        await client.post(
            f"/api/jobs/{cast_job}/piece",
            json={"action": "candidates", "piece": "world", "node_id": str(cast_nodes[1])},
        )
    ).status_code == 422
    assert not queued


@pytest.mark.parametrize("action", ["reopen", "unlock"])
async def test_reopen_previously_confirmed_piece(client, sessionmaker, queued, action):
    book_id, job_id, _ = await gate(
        sessionmaker, piece="first_volume", confirmed=("concept", "protagonist", "world", "segment")
    )
    response = await client.post(
        f"/api/jobs/{job_id}/piece", json={"action": action, "piece": "segment", "feedback": "节点顺序按作者新想法调整"}
    )
    assert response.status_code == 200, response.text
    assert await requirements(sessionmaker, book_id) == {("节点顺序按作者新想法调整", "note")}
    assert queued[-1][1]["piece"] == "segment"


async def test_unconfirmed_piece_cannot_reopen_and_wrong_gate_is_409(client, sessionmaker, queued):
    _, job_id, _ = await gate(sessionmaker, piece="first_volume", confirmed=("concept",))
    assert (
        await client.post(f"/api/jobs/{job_id}/piece", json={"action": "reopen", "piece": "segment"})
    ).status_code == 422
    assert (
        await client.post(f"/api/jobs/{job_id}/directions", json={"action": "redo", "feedback": "换方向"})
    ).status_code == 409
    _, wrong, _ = await gate(sessionmaker, status="running")
    assert (
        await client.post(f"/api/jobs/{wrong}/piece", json={"action": "confirm", "piece": "segment"})
    ).status_code == 409
    assert not queued


async def test_double_submit_only_enqueues_once(client, sessionmaker, queued):
    book_id, job_id, _ = await gate(sessionmaker)
    responses = await asyncio.gather(
        *[client.post(f"/api/jobs/{job_id}/piece", json={"action": "confirm", "piece": "segment"}) for _ in range(2)]
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(queued) == 1
    async with sessionmaker() as session:
        messages = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.book_id == book_id)))
    assert len(messages) == 1
