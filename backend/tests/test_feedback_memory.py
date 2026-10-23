"""看稿原话只管眼前；独立主编判断、去重、权限和三种撤销。"""

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents.schemas import FeedbackMemory, FeedbackMemoryItem
from app.config import get_settings
from app.main import create_app
from app.models import Book, Chapter, Job, MeetingMessage, Memory, PlotUnit, Volume
from app.services import feedback_memory, jobs
from app.services.chat_memories import snapshot
from app.services.memories import forget, remember


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


@pytest.fixture(autouse=True)
def isolated_demo(monkeypatch):
    monkeypatch.setattr("app.llm.demo.DELAY_S", 0)


def item(**values):
    return FeedbackMemoryItem(
        summary="以后每章留悬念", detail="作者要求以后每章结尾都留悬念。", lasts="一直有效", **values
    )


async def seed(sm, kind="volume_review", **pending):
    async with sm() as session:
        book = Book(title="看稿意见合成书", status="writing")
        session.add(book)
        await session.flush()
        job = Job(
            book_id=book.id,
            kind="book_setup" if kind.startswith("setup_") else "write_book",
            status="waiting_author",
            thread_id=str(uuid.uuid4()),
            params={"flow": 3},
            pending={"kind": kind, **pending},
        )
        session.add(job)
        await session.commit()
        return book.id, job.id


@pytest.mark.parametrize(
    "kind,pending,endpoint,body,where,what",
    [
        ("volume_review", {"volume": 3}, "decision", {"action": "revise"}, "第 3 卷的卷纲", feedback_memory.REVISE),
        ("volume_review", {"volume": 3}, "decision", {"action": "approve"}, "第 3 卷的卷纲", feedback_memory.CONFIRM),
        ("chapters_review", {}, "decision", {"action": "revise"}, "单元「雨夜追灯」的章纲", feedback_memory.REVISE),
        ("trial_read", {}, "decision", {"action": "approve"}, "试读前 3 章", feedback_memory.TRIAL),
        (
            "segment_review",
            {"number": 2, "flow": 3},
            "segment",
            {"action": "revise"},
            "第 2 篇",
            feedback_memory.REVISE,
        ),
        (
            "segment_review",
            {"number": 2, "flow": 3},
            "segment",
            {"action": "confirm"},
            "第 2 篇",
            feedback_memory.CONFIRM,
        ),
        ("setup_piece", {"piece": "concept"}, "piece", {"action": "revise"}, "定调", feedback_memory.REVISE),
        ("setup_piece", {"piece": "settings"}, "piece", {"action": "confirm"}, "设定库", feedback_memory.CONFIRM),
        (
            "setup_piece",
            {"piece": "settings"},
            "piece",
            {"action": "revise", "piece": "concept"},
            "定调",
            feedback_memory.REVISE,
        ),
        ("setup_piece", {"piece": "outline"}, "piece", {"action": "revise"}, "大纲", feedback_memory.REVISE),
        ("setup_prefill", {}, "pitches", {"action": "start"}, "三个故事方向", feedback_memory.REVISE),
        (
            "setup_pitches",
            {"pitches": [{"name": "追灯"}]},
            "pitches",
            {"action": "redo"},
            "三个故事方向",
            feedback_memory.REVISE,
        ),
        (
            "setup_pitches",
            {"pitches": [{"name": "追灯"}]},
            "pitches",
            {"action": "pick", "index": 1},
            "三个故事方向",
            feedback_memory.CONFIRM,
        ),
    ],
)
async def test_review_entry_uses_original_feedback_and_background_context(
    client, sessionmaker, monkeypatch, kind, pending, endpoint, body, where, what
):
    bid, jid = await seed(sessionmaker, kind, **pending)
    if kind == "chapters_review":
        async with sessionmaker() as session:
            volume = Volume(book_id=bid, index=1, title="合成卷")
            session.add(volume)
            await session.flush()
            unit = PlotUnit(book_id=bid, volume_id=volume.id, index=1, title="雨夜追灯")
            session.add(unit)
            await session.flush()
            (await session.get(Job, jid)).pending = {"kind": kind, "unit_id": str(unit.id)}
            await session.commit()
    calls, queued = [], []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: queued.append(resume))

    async def judge_model(book_id, role, schema, template, **values):
        calls.append(values)
        assert queued and queued[0]["feedback"] == "眼前这一处加点打斗"
        assert role == "chief" and schema is FeedbackMemory and template == "feedback_memory"
        assert values["purpose"] == "看稿意见要不要记"
        return FeedbackMemory(items=[], reply="这段意见只改眼前这一处。")

    monkeypatch.setattr(feedback_memory, "model", judge_model)
    response = await client.post(f"/api/jobs/{jid}/{endpoint}", json={**body, "feedback": "眼前这一处加点打斗"})
    assert response.status_code == 200, response.text
    assert len(calls) == 1 and calls[0]["where"] == where and calls[0]["what_happens"] == what
    async with sessionmaker() as session:
        assert not list(
            await session.scalars(select(Memory).where(Memory.book_id == bid, Memory.source == "看稿时说的"))
        )
        rows = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.book_id == bid)))
        author = next(m for m in rows if m.speaker == "author")
        if "眼前这一处加点打斗" not in author.content:
            assert author.payload["author_feedback"] == "眼前这一处加点打斗"
        else:
            assert "author_feedback" not in author.payload
        assert next(m for m in rows if m.speaker == "chief").content == "这段意见只改眼前这一处。"
        if what in (feedback_memory.CONFIRM, feedback_memory.TRIAL):
            assert queued[0]["feedback_memory_id"] == author.id
        else:
            assert "feedback_memory_id" not in queued[0]
    await feedback_memory.judge(author.id, client._transport.app.state.redis)
    assert len(calls) == 1
    assert (
        await client.post(f"/api/jobs/{jid}/{endpoint}", json={**body, "feedback": "眼前这一处加点打斗"})
    ).status_code == (422 if kind == "setup_prefill" else 409)
    assert len(calls) == len(queued) == 1


@pytest.mark.parametrize("invalid", ["blank", "absent", "global", "chat", "other", "deleted", "expired", "valid"])
async def test_judgment_item_ids_sources_and_undo(client, sessionmaker, invalid):
    bid, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        other = Book(title="另一本")
        session.add(other)
        await session.flush()
        old = await remember(
            session,
            None if invalid == "global" else other.id if invalid == "other" else bid,
            "旧简述",
            "旧详情",
            kind="chat" if invalid == "chat" else "writing",
            source="你加的",
        )
        if invalid == "deleted":
            await forget(session, old)
        if invalid == "expired":
            old.scope, old.chapter_index = "chapter", 1
            session.add(Chapter(book_id=bid, index=1, status="final"))
        before = snapshot(old)
        code = "" if invalid == "blank" else "记99999" if invalid == "absent" else f"记{old.id}"
        author = MeetingMessage(book_id=bid, speaker="author", kind="decision", content="以后每章都留悬念")
        session.add(author)
        await session.flush()
        new_item = item(id=code)
        if invalid == "expired":
            new_item.summary = "旧简述"
        outcomes = await feedback_memory.apply_items(session, bid, author.id, [new_item])
        reply = MeetingMessage(
            book_id=bid, speaker="chief", kind="speech", content="记住了", payload={"memories": outcomes}
        )
        session.add(reply)
        await session.commit()
        receipt = outcomes[0]["memory"]
        current = await session.get(Memory, receipt["id"])
        assert current.book_id == bid and current.kind == "writing" and current.source == "看稿时说的"
        assert current.message_id == author.id
        assert receipt["action"] == ("update" if invalid == "valid" else "create")
        assert (receipt["id"] == old.id) == (invalid == "valid")
        if invalid == "valid":
            assert receipt["before"] == before
    response = await client.post(
        f"/api/books/{bid}/memories/{receipt['id']}/undo", json={"version": receipt["version"]}
    )
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        row = await session.get(Memory, receipt["id"])
        if invalid == "valid":
            assert snapshot(row) == before
        else:
            assert row.deleted_at is not None


async def test_revise_is_queued_before_slow_or_failed_judgment(client, sessionmaker, monkeypatch):
    bid, jid = await seed(sessionmaker, volume=3)
    started, release = asyncio.Event(), asyncio.Event()
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: queued.append(resume))

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        raise TimeoutError()

    monkeypatch.setattr(feedback_memory, "model", slow)
    request = asyncio.create_task(
        client.post(f"/api/jobs/{jid}/decision", json={"action": "revise", "feedback": "以后每章都留悬念"})
    )
    await asyncio.wait_for(started.wait(), 5)
    assert queued[0]["feedback"] == "以后每章都留悬念"
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "queued"
    release.set()
    assert (await request).status_code == 200
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "queued"
        chief = await session.scalar(
            select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "chief")
        )
        assert chief.content == "这段意见没来得及判断要不要记（判断超时）。要以后都照做，在聊天里跟我说「记住……」。"


async def test_flips_without_words_do_not_invoke_judgment(client, sessionmaker, monkeypatch):
    bid, jid = await seed(sessionmaker, "setup_piece", piece="concept")
    monkeypatch.setattr(jobs, "enqueue", lambda *args: None)

    async def forbidden(*args, **kwargs):
        pytest.fail("只点改成，不应调用主编")

    monkeypatch.setattr(feedback_memory, "model", forbidden)
    result = await client.post(
        f"/api/jobs/{jid}/piece", json={"action": "revise", "flips": [{"topic": "感情线", "choice": "单女主"}]}
    )
    assert result.status_code == 200, result.text
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(Memory).where(Memory.book_id == bid)))


async def test_concurrent_background_claims_only_judge_once(sessionmaker, monkeypatch):
    bid, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        row = MeetingMessage(
            book_id=bid,
            speaker="author",
            kind="decision",
            content="眼前加打斗",
            payload={
                "feedback_memory": {
                    "state": "pending",
                    "where": "大纲",
                    "what_happens": feedback_memory.REVISE,
                    "feedback": "眼前加打斗",
                }
            },
        )
        session.add(row)
        await session.commit()
        mid = row.id
    calls = []

    async def judge_model(*args, **kwargs):
        calls.append(True)
        await asyncio.sleep(0.01)
        return FeedbackMemory(items=[], reply="只改眼前。")

    monkeypatch.setattr(feedback_memory, "model", judge_model)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await asyncio.gather(feedback_memory.judge(mid, redis), feedback_memory.judge(mid, redis))
    finally:
        await redis.aclose()
    assert calls == [True]


@pytest.mark.parametrize(
    "lasts,scope,index",
    [
        ("一直有效", "always", None),
        ("只管下一章", "chapter", 1),
        ("只管这一卷", "volume", 1),
        ("只管下一卷", "volume", 2),
    ],
)
async def test_judgment_duration_resolves_in_book(sessionmaker, lasts, scope, index):
    bid, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        value = item()
        value.lasts = lasts
        outcome = (await feedback_memory.apply_items(session, bid, None, [value]))[0]
        row = await session.get(Memory, outcome["memory"]["id"])
        assert row.scope == scope
        assert (row.chapter_index if scope == "chapter" else row.volume_index) == index


async def test_background_reply_stays_in_original_conversation(client, sessionmaker, monkeypatch):
    bid, jid = await seed(sessionmaker, volume=1)
    monkeypatch.setattr(jobs, "enqueue", lambda *args: None)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return FeedbackMemory(items=[item()], reply="记住了长期规矩。")

    monkeypatch.setattr(feedback_memory, "model", slow)
    request = asyncio.create_task(
        client.post(f"/api/jobs/{jid}/decision", json={"action": "revise", "feedback": "以后每章都留悬念"})
    )
    await asyncio.wait_for(started.wait(), 5)
    async with sessionmaker() as session:
        author = await session.scalar(
            select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "author")
        )
        original = author.payload["conv"]
        # 看稿 decision 不算群聊发言；原段有聊天，点新对话才会新开一段。
        session.add(
            MeetingMessage(
                book_id=bid, speaker="author", kind="note", content="原来聊过的一句", payload={"conv": original}
            )
        )
        await session.commit()
    try:
        fresh = await client.post(f"/api/books/{bid}/chat/conversations", json={})
    finally:
        release.set()
        response = await request
    assert response.status_code == 200
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["id"] != original
    async with sessionmaker() as session:
        chief = await session.scalar(
            select(MeetingMessage).where(MeetingMessage.book_id == bid, MeetingMessage.speaker == "chief")
        )
        assert chief.payload["conv"] == original and not chief.payload.get("reply_to")
