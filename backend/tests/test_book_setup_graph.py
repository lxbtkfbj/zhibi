"""开书流程（演示模型）：起草 → 审稿自动修改 → 拍板 → 作者提意见 → 修改 → 批准。"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.graphs.book_setup import cascade, intake_node, merge_plan
from app.llm import demo
from app.models import Book, Character, DraftVersion, Job, LlmCall, MeetingMessage, PlotUnit, Volume
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


async def make_job(sessionmaker, idea="一个能看见别人寿命的少年", ask=False) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as session:
        book = Book(idea=idea)
        session.add(book)
        await session.flush()
        job = Job(
            book_id=book.id,
            kind="book_setup",
            thread_id=f"test-{uuid.uuid4()}",
            params={"idea": idea, "ask": ask},
        )
        session.add(job)
        await session.commit()
        return book.id, job.id


async def job_status(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        return job.status, job.pending, job.error


def test_cascade_rules():
    assert cascade({"concept": "改书名"})[0] == ["concept", "lore", "spine", "outline"]
    assert cascade({"lore": "加一个人"})[0] == ["lore", "spine", "outline"]
    assert cascade({"spine": "结局改成开放式"})[0] == ["spine", "outline"]
    queue, instructions = cascade({"outline": "压缩第二单元", "lore": " "})
    assert queue == ["outline"]
    assert instructions == {"outline": "压缩第二单元"}


def test_merge_plan_keeps_order_and_combines_instructions():
    queue, instructions = merge_plan(
        ["outline"], {"outline": "压缩第二单元"}, ["lore", "outline"], {"lore": "改名", "outline": "同步"}
    )
    assert queue == ["lore", "outline"]
    assert instructions == {"lore": "改名", "outline": "压缩第二单元\n同步"}


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
        # 先定主线骨架（开篇、结局、关键转折），分卷按篇幅分配章数
        assert book.spine["ending"] and len(book.spine["milestones"]) == 6
        assert sum(v.chapter_count for v in volumes) == 333
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
        # 概念、设定、主线骨架、大纲、审稿、自动修改大纲 共 6 次调用；没开提问就不问
        assert await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.job_id == job_id)) == 6

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


async def test_interview_answers_become_requirements(sessionmaker, monkeypatch):
    book_id, job_id = await make_job(sessionmaker, ask=True)
    prompts: dict[str, str] = {}
    original = demo.respond

    async def capture(schema, system, user):
        prompts[schema.__name__] = user
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)

    await execute_job(job_id)
    status, pending, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == "setup_questions"
    assert pending["questions"][0]["question"] == "这本书打算写多长？"  # 篇幅固定先问
    assert len(pending["questions"]) == 5
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).status == "setting_up"  # 方案还没出来，不是等拍板

    brief = ["这本书打算写多长？——约 200 万字", "主角叫什么名字？——云澈"]
    await execute_job(job_id, {"action": "answer", "brief": brief})
    status, pending, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == "setup_review"
    # 作者的回答进入之后每一步的提示词
    for name in ("BookConcept", "LoreDraft", "StorySpine", "OutlineDraft", "SetupCritique"):
        assert "主角叫什么名字？——云澈" in prompts[name], name


async def test_note_mid_run_revises_finished_parts(sessionmaker, monkeypatch):
    book_id, job_id = await make_job(sessionmaker)
    prompts: list[tuple[str, str]] = []
    original = demo.respond

    async def interject(schema, system, user):
        prompts.append((schema.__name__, user))
        if schema.__name__ == "StorySpine" and len(prompts) == 3:
            # 设定已经做完、主编正在定主线时，作者插了一句话
            async with sessionmaker() as session:
                session.add(
                    MeetingMessage(
                        book_id=book_id, job_id=job_id, speaker="author", kind="note", content="主角名字改成云澈"
                    )
                )
                await session.commit()
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", interject)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error

    names = [name for name, _ in prompts]
    # 主线做完后主编读到插话 → 设定师改人物 → 主线同步 → 再写大纲 → 审稿
    assert names[:8] == [
        "BookConcept",
        "LoreDraft",
        "StorySpine",
        "RevisionTriage",
        "LoreDraft",
        "StorySpine",
        "OutlineDraft",
        "SetupCritique",
    ]
    assert "主角名字改成云澈" in prompts[4][1] and "【修改要求】" in prompts[4][1]
    assert "【修改要求】" in prompts[5][1]  # 主线跟着同步，而不是从零重写
    for name, user in prompts[6:]:
        assert "主角名字改成云澈" in user, name  # 之后每一步都带着作者的话
    async with sessionmaker() as session:
        replies = (
            (
                await session.execute(
                    select(MeetingMessage.content).where(
                        MeetingMessage.job_id == job_id,
                        MeetingMessage.speaker == "chief",
                        MeetingMessage.kind == "speech",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert any("云澈" in r for r in replies)  # 主编在会上回应了作者


async def test_old_checkpoint_gets_spine_step(sessionmaker):
    """旧版流程的检查点没有主线骨架：继续执行时补到大纲之前。"""
    _, job_id = await make_job(sessionmaker)
    runtime = SimpleNamespace(context=SimpleNamespace(sessionmaker=sessionmaker, job_id=job_id))
    update = await intake_node({"queue": ["lore", "outline"], "concept": {"title": "旧书"}}, runtime)
    assert update == {"queue": ["lore", "spine", "outline"]}
    assert await intake_node({"queue": ["outline"], "spine": {"ending": "已有骨架"}}, runtime) == {}
