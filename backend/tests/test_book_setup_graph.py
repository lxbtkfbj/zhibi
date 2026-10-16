"""开书流程（演示模型）：起草 → 审稿自动修改 → 拍板 → 作者提意见 → 修改 → 批准。"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.graphs import book_setup
from app.graphs.book_setup import ORDER, cascade, intake_node, merge_plan
from app.llm import demo
from app.models import (
    Book,
    Character,
    DraftVersion,
    Foreshadowing,
    Job,
    LlmCall,
    MeetingMessage,
    PlotUnit,
    StoryThread,
    Volume,
)
from app.services.job_runner import execute_job
from app.services.setup_store import load_nodes, load_setup


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
            params={"flow": 2, "idea": idea, "ask": ask},
        )
        session.add(job)
        await session.commit()
        return book.id, job.id


async def job_status(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        return job.status, job.pending, job.error


def test_cascade_rules():
    assert cascade({"concept": "改书名"})[0] == ORDER
    assert cascade({"world": "加一个人"})[0] == ["world", "segment", "volumes", "first_volume"]
    assert cascade({"volumes": "女主早点登场"})[0] == ["volumes", "first_volume"]
    queue, instructions = cascade({"first_volume": "压缩第二单元", "world": " "})
    assert queue == ["first_volume"]
    assert instructions == {"first_volume": "压缩第二单元"}
    queue, instructions = cascade({"volumes": "第三卷换个舞台"})
    assert queue == ["volumes", "first_volume"]
    assert instructions["volumes"] == "第三卷换个舞台" and instructions["first_volume"]  # 下游自动同步


def test_merge_plan_keeps_order_and_combines_instructions():
    queue, instructions = merge_plan(
        ["volumes"], {"volumes": "压缩第二单元"}, ["world", "volumes"], {"world": "改名", "volumes": "同步"}
    )
    assert queue == ["world", "volumes"]
    assert instructions == {"world": "改名", "volumes": "压缩第二单元\n同步"}


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
            await session.scalar(select(func.count()).select_from(Character).where(Character.book_id == book_id)) == 6
        )
        volumes = (
            (await session.execute(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index)))
            .scalars()
            .all()
        )
        assert [v.status for v in volumes] == ["detailed", "planned"]
        # 先定主线骨架（开篇、结局、关键转折），分卷按篇幅分配章数
        nodes = await load_nodes(session, book_id)
        assert nodes[0]["kind"] == "opening" and nodes[-1]["kind"] == "ending"
        assert nodes[-1]["event"] and sum(n["kind"] == "milestone" for n in nodes) == 1
        assert not ({"opening", "ending", "milestones", "nodes"} & book.spine.keys())
        assert sum(v.chapter_count for v in volumes) == 61 < 333
        assert nodes[1]["segment"]["number"] == 1 and nodes[-1]["segment"] is None
        # 审稿要求压缩第二单元，演示模型的修改版是 6 章；各单元章数之和仍等于第一卷的 31 章
        units = (
            (
                await session.execute(
                    select(PlotUnit).where(PlotUnit.volume_id == volumes[0].id).order_by(PlotUnit.index)
                )
            )
            .scalars()
            .all()
        )
        assert units[1].chapter_count == 6
        assert sum(u.chapter_count for u in units) == volumes[0].chapter_count == 31
        # 线索、卷卡片与伏笔台账
        threads = (await session.execute(select(StoryThread).where(StoryThread.book_id == book_id))).scalars().all()
        assert {t.kind for t in threads} >= {"主线", "感情线", "反派线"}
        assert volumes[1].antagonist and volumes[1].thread_beats
        ledger = (
            (
                await session.execute(
                    select(Foreshadowing).where(Foreshadowing.book_id == book_id).order_by(Foreshadowing.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [f.seq for f in ledger] == list(range(1, len(ledger) + 1))
        assert len([f for f in ledger if f.kind == "伏笔" and f.span == "长"]) == 0
        assert len([f for f in ledger if f.kind == "期待" and f.span == "长"]) == 1
        assert ledger[0].span == "长"
        # 第一卷新埋的伏笔：写进对应单元的伏笔动作
        short = [f for f in ledger if f.kind == "伏笔" and f.span != "长"]
        assert {"ref": f"F{short[0].seq}", "action": "回收", "detail": "执法堂对质时成为关键证据"} in units[
            1
        ].foreshadow_actions
        assert short[1].payoff_volume == 2
        speakers = (
            (await session.execute(select(MeetingMessage.speaker).where(MeetingMessage.book_id == book_id)))
            .scalars()
            .all()
        )
        assert {"chief", "lorekeeper", "reviewer", "system"} <= set(speakers)
        # 概念、设定、主线骨架、线索、总纲、第一卷卷纲、审稿、自动修改第一卷卷纲 共 8 次调用；没开提问就不问
        assert await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.job_id == job_id)) == 8

    # 作者手动改了主角，再提意见：修改应基于作者改过的版本
    async with sessionmaker() as session:
        hero = (
            await session.execute(select(Character).where(Character.book_id == book_id, Character.name == "陆远"))
        ).scalar()
        hero.goal = "作者改过的目标"
        hero.notes = "作者的备注"
        hero.aliases = ["远哥"]
        hero_id = hero.id
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
        # 重存方案不会丢掉作者单独维护的字段，人物 ID 也不变
        assert hero.id == hero_id and hero.notes == "作者的备注" and hero.aliases == ["远哥"]

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
        if calls["n"] == 3:  # 新顺序第三次调用（设定师建人物）时模型挂了
            raise RuntimeError("模型接口超时")
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", flaky)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "failed"
    assert "模型接口超时" in error

    await execute_job(job_id)  # 点「继续」：从检查点接着跑，不重做已完成的概念和节点
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    async with sessionmaker() as session:
        purposes = (
            (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id).order_by(LlmCall.id)))
            .scalars()
            .all()
        )
    assert purposes.count("开书·概念") == 1
    assert purposes.count("开书·主角卡") == 1
    assert purposes.count("开书·世界与人") == 2  # 失败调用也留记录；只重试尚未完成的设定步骤。


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
    for name in (
        "BookConcept",
        "ProtagonistDraft",
        "WorldDraft",
        "SegmentDraft",
        "SegmentVolumesDraft",
        "VolumePlanDraft",
        "SetupCritique",
    ):
        assert "主角叫什么名字？——云澈" in prompts[name], name


async def test_genre_playbook_goes_into_planning_prompts(sessionmaker, monkeypatch):
    """点子是后宫玄幻：概念的类型和标签选中「后宫玄幻爽文」打法，线索、总纲、卷纲、审稿都按它来。"""
    book_id, job_id = await make_job(sessionmaker, idea="后宫玄幻，一个能看见别人寿命的少年")
    prompts: dict[str, str] = {}
    original = demo.respond

    async def capture(schema, system, user):
        prompts.setdefault(schema.__name__, user)
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error

    assert "【题材打法：后宫玄幻爽文" in prompts["SegmentVolumesDraft"]
    assert "◆ 分卷" in prompts["SegmentVolumesDraft"]
    assert "◆ 分卷" in prompts["SegmentVolumesDraft"] and "宗门大比（全书最多 3 次）" in prompts["SegmentVolumesDraft"]
    volume = prompts["VolumePlanDraft"]
    assert "◆ 破局手法" in volume and "退婚打脸（全书最多 1 次）" in volume
    assert "【套路使用情况】\n（还没用过任何套路，这是第一卷）" in volume
    assert "◆ 套路上限" in prompts["SetupCritique"]
    async with sessionmaker() as session:
        statuses = (
            (
                await session.execute(
                    select(MeetingMessage.content).where(
                        MeetingMessage.job_id == job_id, MeetingMessage.kind == "status"
                    )
                )
            )
            .scalars()
            .all()
        )
        # 第一卷的单元标上了套路和破局手法，后面各卷据此统计、防重复
        units = (await session.execute(select(PlotUnit).where(PlotUnit.book_id == book_id))).scalars().all()
    assert any("第一段" in s for s in statuses)
    assert all(u.tropes and u.resolution for u in units)

    # 普通修仙文用通用打法
    _, plain_job = await make_job(sessionmaker)
    prompts.clear()
    await execute_job(plain_job)
    assert "【题材打法：通用" in prompts["SegmentVolumesDraft"]


@pytest.mark.parametrize("thread", [None, "lorekeeper"])
async def test_note_mid_run_revises_finished_parts(sessionmaker, monkeypatch, thread):
    book_id, job_id = await make_job(sessionmaker)
    prompts: list[tuple[str, str]] = []
    original = demo.respond

    async def interject(schema, system, user):
        prompts.append((schema.__name__, user))
        if schema.__name__ == "WorldDraft" and len(prompts) == 3:
            # 节点已经完成、设定师正在建人物时，作者插了一句话
            async with sessionmaker() as session:
                session.add(
                    MeetingMessage(
                        book_id=book_id,
                        job_id=job_id,
                        speaker="author",
                        kind="note",
                        content="主角名字改成云澈",
                        payload={"thread": thread} if thread else None,
                    )
                )
                await session.commit()
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", interject)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error

    names = [name for name, _ in prompts]
    # 设定做完后读到插话 → 改人物 → 总纲、线索、第一卷同步；已经在上游的节点不重做。
    assert names[:10] == [
        "BookConcept",
        "ProtagonistDraft",
        "WorldDraft",
        "RevisionTriage",
        "ProtagonistDraft",
        "WorldDraft",
        "SegmentDraft",
        "SegmentVolumesDraft",
        "VolumePlanDraft",
        "SetupCritique",
    ]
    assert "主角名字改成云澈" in prompts[4][1] and "【修改要求】" in prompts[4][1]
    assert names.count("SegmentDraft") == 1
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
        if thread:
            messages = (
                (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars().all()
            )
            private_replies = [m for m in messages if m.kind == "speech" and m.payload == {"thread": thread}]
            assert [(m.speaker, m.content) for m in private_replies] == [(thread, "收到，主编已经安排，按你说的改。")]
            assert "主角名字改成云澈" in (await session.get(Book, book_id)).requirements
    if thread:
        for name, user in prompts[3:]:
            assert "主角名字改成云澈" in user, name
    else:
        assert any("云澈" in r for r in replies)  # 主编在会上回应了作者


async def test_targeted_note_before_setup_reaches_every_prompt(sessionmaker, monkeypatch):
    book_id, job_id = await make_job(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        book.requirements = ["之前记下的要求不能丢"]
        session.add(
            MeetingMessage(
                book_id=book_id,
                job_id=job_id,
                speaker="author",
                kind="note",
                content="开篇节奏紧凑",
                payload={"thread": "writer"},
            )
        )
        await session.commit()
    prompts = []
    original = demo.respond

    async def capture(schema, system, user):
        prompts.append(user)
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)
    await execute_job(job_id)
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert all("开篇节奏紧凑" in user for user in prompts)
    async with sessionmaker() as session:
        assert "之前记下的要求不能丢" in (await session.get(Book, book_id)).requirements
        replies = (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars().all()
    assert any(
        m.speaker == "writer" and m.payload == {"thread": "writer"} and m.content == "收到，主编已经安排，按你说的改。"
        for m in replies
    )


async def test_approval_keeps_late_targeted_note_without_replanning(sessionmaker, monkeypatch):
    book_id, job_id = await make_job(sessionmaker)
    original = book_setup.persist_node
    late_content = "苏灵素改成 19 岁"

    async def insert_last_moment_note(state, runtime):
        result = await original(state, runtime)
        # 模拟最终存稿后、任务切换为 waiting_author 前 /notes 已成功接收的插话。
        async with sessionmaker() as session:
            assert (await session.get(Job, job_id)).status == "running"
            session.add(
                MeetingMessage(
                    book_id=book_id,
                    job_id=job_id,
                    speaker="author",
                    kind="note",
                    content=late_content,
                    payload={"thread": "lorekeeper"},
                )
            )
            await session.commit()
        return result

    monkeypatch.setattr(book_setup, "persist_node", insert_last_moment_note)
    await execute_job(job_id)
    status, pending, error = await job_status(sessionmaker, job_id)
    assert status == "waiting_author" and pending["kind"] == "setup_review", error
    async with sessionmaker() as session:
        before = await load_setup(session, book_id)
        book = await session.get(Book, book_id)
        assert late_content not in "\n".join(book.requirements)
        book.requirements = [*(book.requirements or []), "之前记下的要求"]
        calls_before = await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.job_id == job_id))
        await session.commit()

    await execute_job(job_id, {"action": "approve"})
    status, _, error = await job_status(sessionmaker, job_id)
    assert status == "succeeded", error
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.status == "ready"
        assert "之前记下的要求" in book.requirements
        assert late_content in book.requirements
        assert await load_setup(session, book_id) == before
        calls_after = await session.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.job_id == job_id))
        assert calls_after == calls_before  # 批准只保存要求，不再调用模型改动已经审阅的稿件。
        messages = (
            (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars().all()
        )
    replies = [
        message for message in messages if message.kind == "speech" and message.payload == {"thread": "lorekeeper"}
    ]
    assert [(message.speaker, message.content) for message in replies] == [
        ("lorekeeper", "收到，主编已经安排，按你说的改。")
    ]


async def test_current_flow_fills_missing_parts_in_new_order(sessionmaker, monkeypatch):
    """当前新流程缺项时按六个步骤补齐，旧流程由 runner 拦截。"""
    _, job_id = await make_job(sessionmaker)
    runtime = SimpleNamespace(context=SimpleNamespace(sessionmaker=sessionmaker, job_id=job_id))
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    update = await intake_node({"queue": ["world", "volumes"], "concept": {"title": "旧书"}}, runtime)
    assert update["queue"] == ["protagonist", "world", "segment", "volumes", "first_volume"]
    done = {
        "concept": {"title": "旧书"},
        "world": {"characters": []},
        "protagonist": {"name": "主角"},
        "segment": {"nodes": [{"kind": "ending"}]},
        "volumes": {"volumes": [{"index": 1}], "threads": [{"name": "主线"}]},
        "first_volume": {"units": [{"index": 1}]},
    }
    assert "queue" not in await intake_node({"queue": ["volumes"], **done}, runtime)
