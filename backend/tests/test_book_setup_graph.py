"""开书流程（演示模型）：起草 → 审稿自动修改 → 拍板 → 作者提意见 → 修改 → 批准。"""

import uuid

import pytest
from sqlalchemy import func, select

from app.graphs.book_setup import cascade
from app.llm import demo
from app.models import Book, Character, DraftVersion, Job, LlmCall, MeetingMessage, PlotUnit, Volume
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


async def make_job(sessionmaker, idea="一个能看见别人寿命的少年") -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as session:
        book = Book(idea=idea)
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="book_setup", thread_id=f"test-{uuid.uuid4()}", params={"idea": idea})
        session.add(job)
        await session.commit()
        return book.id, job.id


async def job_status(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        return job.status, job.pending, job.error


def test_cascade_rules():
    assert cascade({"concept": "改书名"})[0] == ["concept", "lore", "outline"]
    assert cascade({"lore": "加一个人"})[0] == ["lore", "outline"]
    queue, instructions = cascade({"outline": "压缩第二单元", "lore": " "})
    assert queue == ["outline"]
    assert instructions == {"outline": "压缩第二单元"}


async def test_setup_flow_to_approval(sessionmaker):
    book_id, job_id = await make_job(sessionmaker)

    await execute_job(job_id)
    status, pending, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == "setup_review"

    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.title == "青灯问道"
        assert book.status == "awaiting_approval"
        assert (
            await session.scalar(select(func.count()).select_from(Character).where(Character.book_id == book_id)) == 5
        )
        volumes = (
            (await session.execute(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index)))
            .scalars()
            .all()
        )
        assert [v.status for v in volumes] == ["detailed", "planned", "planned", "planned"]
        # 审稿要求压缩第二单元，演示模型的修改版是 6 章
        unit2 = (
            await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volumes[0].id, PlotUnit.index == 2))
        ).scalar()
        assert unit2.chapter_count == 6
        speakers = (
            (await session.execute(select(MeetingMessage.speaker).where(MeetingMessage.book_id == book_id)))
            .scalars()
            .all()
        )
        assert {"chief", "lorekeeper", "reviewer", "system"} <= set(speakers)
        # 概念、设定、大纲、审稿、自动修改大纲 共 5 次调用
        assert await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.job_id == job_id)) == 5

    # 作者手动改了主角，再提意见：修改应基于作者改过的版本
    async with sessionmaker() as session:
        hero = (
            await session.execute(select(Character).where(Character.book_id == book_id, Character.name == "陆远"))
        ).scalar()
        hero.goal = "作者改过的目标"
        await session.commit()

    await execute_job(job_id, {"action": "revise", "feedback": "第三单元节奏再快一点"})
    status, pending, _ = await job_status(sessionmaker, job_id)
    assert status == "waiting_author"
    assert pending["round"] == 1
    async with sessionmaker() as session:
        hero = (
            await session.execute(select(Character).where(Character.book_id == book_id, Character.name == "陆远"))
        ).scalar()
        assert hero.goal == "作者改过的目标"

    await execute_job(job_id, {"action": "approve"})
    status, _, _ = await job_status(sessionmaker, job_id)
    assert status == "succeeded"
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.status == "ready"
        first = (await session.execute(select(Volume).where(Volume.book_id == book_id, Volume.index == 1))).scalar()
        assert first.status == "approved"
        versions = (
            (await session.execute(select(DraftVersion.source).where(DraftVersion.book_id == book_id))).scalars().all()
        )
        assert versions == ["ai", "ai", "author"]


async def test_failure_then_resume_from_checkpoint(sessionmaker, monkeypatch):
    book_id, job_id = await make_job(sessionmaker)
    original = demo.respond
    calls = {"n": 0}

    async def flaky(schema, system, user):
        calls["n"] += 1
        if calls["n"] == 3:  # 第三次调用（主编写大纲）时模型挂了
            raise RuntimeError("模型接口超时")
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", flaky)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "failed"
    assert "模型接口超时" in error

    await execute_job(job_id)  # 点「继续」：从检查点接着跑，不重做概念和设定
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    async with sessionmaker() as session:
        purposes = (
            (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id).order_by(LlmCall.id)))
            .scalars()
            .all()
        )
    assert purposes.count("开书·概念") == 1
    assert purposes.count("开书·设定") == 1
