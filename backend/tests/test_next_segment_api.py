"""第二包任务四：手动规划和下一篇确认的接口事务边界。"""

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


async def book_fixture(sessionmaker, *, status="ready", segmented=True, ending=False, job_status=None):
    async with sessionmaker() as session:
        book = Book(title="规划测试", status=status)
        session.add(book)
        await session.flush()
        node = StoryNode(
            book_id=book.id,
            position=2,
            kind="ending" if ending else "milestone",
            title="第一段终点",
            segment={"number": 1} if segmented else None,
        )
        session.add(node)
        job = None
        if job_status:
            job = jobs.new_write_job(book, "book", 1)
            job.status = job_status
            job.pending = {"kind": "segment_review", "flow": 3, "number": 2, "split": {"volumes": [{"index": 3}]}}
            session.add(job)
        await session.commit()
        return book.id, job.id if job else None


@pytest.mark.parametrize(
    ("options", "detail"),
    [
        ({"status": "setting_up"}, "开书方案还没定稿"),
        ({"status": "completed"}, "全书已经写完了"),
        ({"segmented": False}, "这本书开书时没有分篇规划，不需要定下一篇"),
        ({"ending": True}, "全书已经规划到结局了"),
        ({"job_status": "waiting_author"}, "编辑部手上还有没做完的事，先处理完再规划下一篇"),
        ({"job_status": "running"}, "编辑部手上还有没做完的事，先处理完再规划下一篇"),
        ({"job_status": "queued"}, "编辑部手上还有没做完的事，先处理完再规划下一篇"),
    ],
)
async def test_manual_conflicts(client, sessionmaker, queued, options, detail):
    book_id, _ = await book_fixture(sessionmaker, **options)
    response = await client.post(f"/api/books/{book_id}/plan-segment")
    assert response.status_code == 409 and response.json()["detail"] == detail
    assert not queued


async def test_manual_planning_double_click_only_creates_one_job(client, sessionmaker, queued):
    book_id, _ = await book_fixture(sessionmaker)
    responses = await asyncio.gather(*(client.post(f"/api/books/{book_id}/plan-segment") for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    created = next(response.json() for response in responses if response.status_code == 201)
    assert len(queued) == 1
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(created["id"]))
        assert job.params == {"until": "segment", "count": 1}
        assert (await session.get(Book, book_id)).status == "writing"
        assert (
            await session.scalar(select(MeetingMessage.content).where(MeetingMessage.book_id == book_id))
            == "现在就规划下一篇。"
        )


@pytest.mark.parametrize("action", ["confirm", "delegate", "revise"])
async def test_segment_decisions_save_requirements_and_queue_once(client, sessionmaker, queued, action):
    book_id, job_id = await book_fixture(sessionmaker, status="writing", job_status="waiting_author")
    payload = {
        "action": action,
        "feedback": "这一篇不要赶路",
        "flips": [{"topic": "对手", "choice": "师兄"}],
        "pin_end": True,
    }
    response = await client.post(f"/api/jobs/{job_id}/segment", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert queued == [(job_id, {**payload, "requirement_saved": True})]
    assert (await client.post(f"/api/jobs/{job_id}/segment", json=payload)).status_code == 409
    async with sessionmaker() as session:
        requirements = {
            (row.text, row.source)
            for row in await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == book_id))
        }
        assert requirements == {("这一篇不要赶路", "segment:2"), ("「对手」改成：师兄", "answer")}
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.job_id == job_id))
        assert message.payload["requirement_saved"]
        if action == "confirm":
            assert message.content == "确认第 2 篇，开拆第 3 卷。终点锁住。"
        elif action == "delegate":
            assert message.content == "第 2 篇交给编辑部定。"
        else:
            assert message.content == "这一篇不要赶路"


async def test_revise_requires_feedback_or_flips_and_waiting_notes_rejected(client, sessionmaker, queued):
    book_id, job_id = await book_fixture(sessionmaker, job_status="waiting_author")
    assert BOOK_STATUS_WHILE_WAITING["segment_review"] == "writing"
    response = await client.post(f"/api/jobs/{job_id}/segment", json={"action": "revise", "feedback": "  "})
    assert response.status_code == 422
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "把这一篇改成更多反转"})
    assert response.status_code == 409
    response = await client.post(
        f"/api/jobs/{job_id}/segment", json={"action": "revise", "flips": [{"topic": "地图", "choice": "原地"}]}
    )
    assert response.status_code == 200
    async with sessionmaker() as session:
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.job_id == job_id))
        assert message.content == "「地图」改成：原地"


async def test_segment_wrong_gate_and_not_found(client, sessionmaker, queued):
    _, job_id = await book_fixture(sessionmaker, job_status="waiting_author")
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        job.pending = {"kind": "volume_review"}
        await session.commit()
    response = await client.post(f"/api/jobs/{job_id}/segment", json={"action": "confirm"})
    assert response.status_code == 409 and response.json()["detail"] == "当前没有等待你确认的下一篇"
    assert (await client.post(f"/api/jobs/{uuid.uuid4()}/segment", json={"action": "confirm"})).status_code == 404
    assert not queued


@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("active_status", ["queued", "running", "waiting_author"])
async def test_old_task_resume_cannot_overlap_new_segment_task(client, sessionmaker, queued, status, active_status):
    book_id, old_job = await book_fixture(sessionmaker, job_status=status)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        current = jobs.new_write_job(book, "segment", 1)
        current.status = active_status
        session.add(current)
        await session.commit()
    response = await client.post(f"/api/jobs/{old_job}/resume")
    assert response.status_code == 409
    assert response.json()["detail"] == "编辑部手上还有没做完的事，先处理完再继续"
    assert not queued
    async with sessionmaker() as session:
        assert (await session.get(Job, old_job)).status == status


async def test_manual_planning_and_old_task_resume_serialize(client, sessionmaker, queued):
    book_id, old_job = await book_fixture(sessionmaker, job_status="failed")
    responses = await asyncio.gather(
        client.post(f"/api/books/{book_id}/plan-segment"),
        client.post(f"/api/jobs/{old_job}/resume"),
    )
    assert sum(response.status_code == 409 for response in responses) == 1
    assert sum(response.status_code in (200, 201) for response in responses) == 1
    assert len(queued) == 1
    async with sessionmaker() as session:
        active = list(
            await session.scalars(select(Job).where(Job.book_id == book_id, Job.status.in_(jobs.ACTIVE_STATUSES)))
        )
        assert len(active) == 1


async def test_flow2_only_accepts_redo_without_saving_requirements(client, sessionmaker, queued):
    bid, jid = await book_fixture(sessionmaker, job_status="waiting_author")
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.pending = {**job.pending, "flow": 2}
        await session.commit()
    for action in ("confirm", "delegate", "revise"):
        response = await client.post(f"/api/jobs/{jid}/segment", json={"action": action, "feedback": "旧意见"})
        assert response.status_code == 422 and response.json()["detail"] == "这一篇要先按新写法重出"
    response = await client.post(f"/api/jobs/{jid}/segment", json={"action": "redo", "feedback": "不得记为要求"})
    assert response.status_code == 200
    assert queued == [(jid, {"action": "redo", "requirement_saved": True})]
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == bid)))
        assert (
            await session.scalar(select(MeetingMessage).where(MeetingMessage.job_id == jid))
        ).content == "按新写法重出这一篇"


@pytest.mark.parametrize("kind", ["volume_review", "chapters_review"])
async def test_decision_across_tabs_is_queued_exactly_once(client, sessionmaker, queued, kind):
    bid, jid = await book_fixture(sessionmaker, job_status="waiting_author")
    unit_id = str(uuid.uuid4())
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.pending = {"kind": kind, "volume": 2, "unit_id": unit_id}
        await session.commit()
    responses = await asyncio.gather(
        *(client.post(f"/api/jobs/{jid}/decision", json={"action": "revise", "feedback": "加强悬念"}) for _ in range(2))
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert len(queued) == 1
    async with sessionmaker() as session:
        requirements = list(await session.scalars(select(AuthorRequirement).where(AuthorRequirement.book_id == bid)))
        assert len(requirements) == 1
        assert requirements[0].source == ("volume:2" if kind == "volume_review" else f"unit:{unit_id}")
        assert len(list(await session.scalars(select(MeetingMessage).where(MeetingMessage.job_id == jid)))) == 1
