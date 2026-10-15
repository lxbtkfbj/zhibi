"""通过真实接口和检查点走完整拼图流程；不使用作者数据库或外部模型。"""

import uuid

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import editorial, schemas
from app.config import get_settings
from app.graphs.book_setup import PIECE_ORDER, build_setup_graph
from app.llm import demo
from app.main import create_app
from app.models import AuthorRequirement, Book, Job, MeetingMessage, Volume
from app.services import jobs
from app.services.job_runner import execute_job


@pytest.fixture
async def flow(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, resume=None: queued.append((jid, resume)))
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:

        async def call(method, path, body=None, *, run=True):
            response = await client.request(method, "/api" + path, json=body)
            assert response.is_success, response.text
            while run and queued:
                jid, resume = queued.pop(0)
                await execute_job(jid, resume)
                status = (await client.get(f"/api/jobs/{jid}")).json()
                assert status["status"] != "failed", status["error"]
            return None if response.status_code == 204 else response.json()

        yield call
    await application.state.redis.aclose()


async def new_puzzle(flow, idea="一个少年捡到青灯"):
    created = await flow("POST", "/books", {"idea": idea, "mode": "puzzle"})
    bid, jid = created["book"]["id"], created["job"]["id"]
    gate = await flow("GET", f"/jobs/{jid}")
    assert gate["pending"]["kind"] == "setup_directions"
    assert len(gate["pending"]["directions"]) == 3
    await flow(
        "POST",
        f"/jobs/{jid}/directions",
        {"action": "choose", "choice": 0, "length": "约 100 万字", "mix": "加入古镜追凶的悬念"},
    )
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "concept"
    return bid, jid


async def confirm(flow, jid, piece):
    return await flow("POST", f"/jobs/{jid}/piece", {"action": "confirm", "piece": piece})


async def test_puzzle_complete_api_path_and_author_nodes(flow, sessionmaker, monkeypatch):
    original = editorial.critique_setup

    async def critique(*args, **kwargs):
        setup = args[3]
        if setup.get("first_volume", {}).get("units"):
            return schemas.SetupCritique(
                verdict="pass",
                highlights=[],
                issues=[
                    schemas.ReviewIssue(
                        target="concept", problem="目标读者可以更具体", suggestion="明确偏好智斗的读者", severity="low"
                    )
                ],
                remark="第一卷可交作者，锁定概念只提建议。",
            )
        return await original(*args, **kwargs)

    monkeypatch.setattr(editorial, "critique_setup", critique)
    bid, jid = await new_puzzle(flow)
    await confirm(flow, jid, "concept")
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["piece"] == "nodes" and not gate["warnings"]
    nodes = await flow("GET", f"/books/{bid}/nodes")
    await flow("PATCH", f"/nodes/{nodes[1]['id']}", {"status": "pinned"})
    await flow("PATCH", f"/nodes/{nodes[2]['id']}", {"event": "作者亲手改的暂定事件"})
    author = await flow(
        "POST",
        f"/books/{bid}/nodes",
        {"title": "作者亲定的告别", "event": "向故乡告别", "volume": 2, "after_node_id": nodes[2]["id"]},
    )
    assert author["status"] == "pinned" and author["origin"] == "author"
    await flow("PATCH", f"/nodes/{nodes[3]['id']}", {"status": "empty", "event": ""})
    await flow("POST", f"/jobs/{jid}/piece", {"action": "candidates", "piece": "nodes", "node_id": nodes[2]["id"]})
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert len(gate["candidates"]["nodes"]) == 3
    candidate = gate["candidates"]["nodes"][0]
    await flow(
        "PATCH",
        f"/nodes/{nodes[2]['id']}",
        {
            k: v
            for k, v in candidate.items()
            if k in {"title", "event", "prerequisite", "consequence", "volume", "editor_note"}
        },
    )
    await flow(
        "POST",
        f"/jobs/{jid}/piece",
        {"action": "fill", "piece": "nodes", "node_id": nodes[3]["id"], "feedback": "中间要有一场宗门大比"},
    )
    after = await flow("GET", f"/books/{bid}/nodes")
    filled = next(n for n in after if n["id"] == nodes[3]["id"])
    assert filled["status"] == "pinned" and filled["origin"] == "author" and filled["event"]
    for piece in ("nodes", "cast", "fill"):
        await confirm(flow, jid, piece)
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["piece"] == "first_volume" and gate["suggestions"][0]["target"] == "concept"
    await confirm(flow, jid, "first_volume")
    book = await flow("GET", f"/books/{bid}")
    assert book["status"] == "ready" and book["setup_progress"]["current"] is None
    assert book["setup_progress"]["pieces"] == dict.fromkeys(PIECE_ORDER, "confirmed")
    bible = await flow("GET", f"/books/{bid}/bible")
    assert len(bible["secrets"]) >= 4
    assert any(f["code"].startswith("E") for f in bible["foreshadowings"])
    nodes_after = await flow("GET", f"/books/{bid}/nodes")
    assert any(n["anchors"] for n in nodes_after)
    pinned = next(n for n in nodes_after if n["id"] == nodes[1]["id"])
    assert pinned["event"] == nodes[1]["event"]
    async with sessionmaker() as session:
        volumes = list(
            await session.scalars(select(Volume).where(Volume.book_id == uuid.UUID(bid)).order_by(Volume.index))
        )
        assert volumes[0].status == "approved" and all(v.target_node_id for v in volumes)
        requirements = list(
            await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == uuid.UUID(bid)))
        )
        assert any("100 万字" in r.text and r.source == "answer" for r in requirements)
        assert any("混搭" in r.text and r.source == "answer" for r in requirements)
        assert not any(r.text == "中间要有一场宗门大比" for r in requirements)


async def test_confirm_fills_empty_and_reopen_resync(flow):
    bid, jid = await new_puzzle(flow)
    await confirm(flow, jid, "concept")
    nodes = await flow("GET", f"/books/{bid}/nodes")
    await flow("PATCH", f"/nodes/{nodes[2]['id']}", {"status": "empty", "event": ""})
    await confirm(flow, jid, "nodes")
    after = await flow("GET", f"/books/{bid}/nodes")
    assert next(n for n in after if n["id"] == nodes[2]["id"])["status"] == "pencil"
    await confirm(flow, jid, "cast")
    await flow("POST", f"/jobs/{jid}/piece", {"action": "reopen", "piece": "nodes"})
    progress = (await flow("GET", f"/books/{bid}"))["setup_progress"]
    assert (
        progress["pieces"]["nodes"] == "waiting" and progress["pieces"]["cast"] == progress["pieces"]["fill"] == "todo"
    )
    await confirm(flow, jid, "nodes")
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "cast"
    await confirm(flow, jid, "cast")
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "fill"


async def test_locked_notes_request_unlock_then_resync(flow, sessionmaker, monkeypatch):
    bid, jid = await new_puzzle(flow)
    await confirm(flow, jid, "concept")
    before = (await flow("GET", f"/books/{bid}"))["concept"]
    draft = editorial.draft_lore

    async def inject(*args, **kwargs):
        async with sessionmaker() as session:
            session.add(
                MeetingMessage(
                    book_id=uuid.UUID(bid),
                    job_id=uuid.UUID(jid),
                    speaker="author",
                    kind="note",
                    content="把已确认的概念改成追凶",
                )
            )
            await session.commit()
        return await draft(*args, **kwargs)

    async def absorb(*args, **kwargs):
        assert "定调" in kwargs["locked"]
        return schemas.RevisionTriage(
            concept_instructions="改成追凶",
            unlock_requests=[schemas.UnlockRequest(target="concept", reason="需要改概念的核心卖点")],
            remark="需要作者解锁概念",
        )

    monkeypatch.setattr(editorial, "draft_lore", inject)
    monkeypatch.setattr(editorial, "absorb_notes", absorb)
    await confirm(flow, jid, "nodes")
    pending = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert pending["piece"] == "cast" and pending["unlock_requests"]
    assert (await flow("GET", f"/books/{bid}"))["concept"] == before
    monkeypatch.setattr(editorial, "draft_lore", draft)
    await flow("POST", f"/jobs/{jid}/piece", {"action": "unlock", "piece": "concept", "feedback": "核心卖点改成追凶"})
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "concept"
    for piece in ("concept", "nodes", "cast", "fill", "first_volume"):
        await confirm(flow, jid, piece)
    assert (await flow("GET", f"/books/{bid}"))["status"] == "ready"


async def test_old_checkpoint_without_mode_and_with_legacy_spine(sessionmaker, monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    async with sessionmaker() as session:
        book = Book(idea="旧书检查点")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="book_setup", thread_id=f"legacy-{uuid.uuid4()}", params={"idea": book.idea})
        session.add(job)
        await session.commit()
    state = {
        "idea": "旧书检查点",
        "concept": {"title": "旧书", "target_volumes": 8, "target_length": 100, "chapter_words": 3000},
        "spine": {
            "opening": "旧开篇",
            "ending": "旧结局",
            "milestones": [{"index": 1, "title": "旧转折", "event": "出城", "change": "成长", "volume": 2}],
        },
        "queue": ["lore", "threads", "outline", "first_volume"],
        "instructions": {},
        "phase": "draft",
        "round": 0,
    }
    async with AsyncPostgresSaver.from_conn_string(get_settings().checkpoint_dsn) as saver:
        await saver.setup()
        graph = build_setup_graph().compile(checkpointer=saver)
        await graph.aupdate_state({"configurable": {"thread_id": job.thread_id}}, state, as_node="concept")
    await execute_job(job.id)
    async with sessionmaker() as session:
        stored = await session.get(Job, job.id)
        assert stored.status == "waiting_author", stored.error
        assert stored.pending["kind"] == "setup_review"
        assert (await session.get(Book, book.id)).setup_progress["mode"] == "oneshot"
