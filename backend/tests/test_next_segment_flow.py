"""第二包任务四：下一篇的真实图暂停、恢复、修改和旧检查点兼容。"""

import uuid

import pytest
from sqlalchemy import func, select

from app.graphs import write_book as graph
from app.llm import demo
from app.models import Book, Chapter, Character, Job, LlmCall, MeetingMessage, Memory, StoryNode, Volume
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


async def seed(sessionmaker, *, approval=True, ending=False, segmented=True, finals=0):
    async with sessionmaker() as session:
        book = Book(
            title="测试短段",
            idea="测试短段",
            status="writing",
            concept={"title": "测试短段", "core_loop": "调查旧案找到证人", "protagonist_hook": "能看到寿命的陆远"},
            protagonist={"name": "陆远", "pursuit": "查出父母死亡的真相"},
            world={"maps": [{"name": "青石镇"}]},
            settings={"segment_approval": approval, "trial_read": False, "pitches": 1, "volume_audit": False},
        )
        session.add(book)
        await session.flush()
        opening = StoryNode(book_id=book.id, position=1, kind="opening", title="捡灯", status="pinned")
        endpoint = StoryNode(
            book_id=book.id,
            position=2,
            kind="ending" if ending else "milestone",
            title="走出青石镇",
            event="携证据北上",
            segment={"number": 1, "status": "confirmed", "planned_at": 0, "map": "青石镇", "goal": "找到师兄"}
            if segmented
            else None,
        )
        session.add_all(
            [opening, endpoint, Character(book_id=book.id, name="陆远", role_type="主角", want="查清师兄之死")]
        )
        if not ending:
            session.add(
                StoryNode(
                    book_id=book.id,
                    position=3,
                    kind="ending",
                    title="摧毁寿元交易",
                    event="摧毁长明灯",
                    prerequisite="找到幕后人",
                    consequence="村民重获自由",
                )
            )
        await session.flush()
        volume = Volume(
            book_id=book.id,
            index=1,
            title="青石镇",
            status="done",
            chapter_count=6,
            recap="找到通往北境的线索。",
            target_node_id=endpoint.id,
        )
        session.add(volume)
        await session.flush()
        session.add_all(
            [
                Chapter(book_id=book.id, volume_id=volume.id, index=i, title=f"旧章{i}", status="final", summary="旧事")
                for i in range(1, finals + 1)
            ]
        )
        await session.commit()
        return book.id


async def job_for(sessionmaker, book_id, until="segment"):
    async with sessionmaker() as session:
        job = Job(
            book_id=book_id,
            kind="write_book",
            thread_id=f"next-segment-{uuid.uuid4()}",
            params={"until": until, "count": 1},
        )
        session.add(job)
        await session.commit()
        return job.id


async def get_job(sessionmaker, job_id):
    async with sessionmaker() as session:
        return await session.get(Job, job_id)


@pytest.mark.parametrize(
    ("state", "step"),
    [
        ({"until": "book"}, "plan_segment"),
        ({"until": "volume"}, "plan_segment"),
        ({"until": "volume", "start_volume": 1}, "done"),
        ({"until": "count", "target": 6, "written": 6}, "done"),
    ],
)
async def test_segment_boundary_trigger_priority(sessionmaker, state, step):
    book_id = await seed(sessionmaker)
    async with sessionmaker() as session:
        result = await graph.decide(session, book_id, state)
        assert result["step"] == step
        assert (await session.get(Book, book_id)).status == "writing"
        if state.get("start_volume"):
            assert result["reason"] == "第 1 卷写完了。下一篇还没定，下次开写时主编先来定下一篇。"


@pytest.mark.parametrize(("ending", "segmented"), [(False, False), (True, True)])
async def test_legacy_and_ending_complete_without_new_checkpoint_fields(sessionmaker, ending, segmented):
    book_id = await seed(sessionmaker, ending=ending, segmented=segmented)
    async with sessionmaker() as session:
        result = await graph.decide(session, book_id, {"until": "book"})
        assert result == {"step": "done", "reason": "全书写完了！"}
        assert (await session.get(Book, book_id)).status == "completed"


async def test_manual_is_before_trial_and_stops_after_confirm(sessionmaker):
    book_id = await seed(sessionmaker, finals=3)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        book.settings = {**book.settings, "trial_read": True}
        await session.commit()
    job_id = await job_for(sessionmaker, book_id)
    await execute_job(job_id)
    job = await get_job(sessionmaker, job_id)
    assert job.status == "waiting_author", job.error
    assert job.pending["kind"] == "segment_review" and job.pending["number"] == 2
    assert job.pending["round"] == 1
    assert not job.pending["warnings"], job.pending["warnings"]
    assert job.pending["plan"]["end"]["adopted"] is False
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Volume).where(Volume.book_id == book_id)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(Character).where(Character.book_id == book_id)) == 1
        )
    await execute_job(job_id, {"action": "confirm", "pin_end": True})
    job = await get_job(sessionmaker, job_id)
    assert job.status == "succeeded", job.error
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.book_id == book_id)) == 3
        nodes = list(
            await session.scalars(select(StoryNode).where(StoryNode.book_id == book_id).order_by(StoryNode.position))
        )
        assert nodes[2].segment["number"] == 2 and nodes[2].status == "pinned"
        assert nodes[2].segment["planned_at"] == 3
        book = await session.get(Book, book_id)
        assert book.status == "writing" and not book.trial_read_done
        messages = list(await session.scalars(select(MeetingMessage.content).where(MeetingMessage.job_id == job_id)))
        assert any("开写时先拆第 2 卷卷纲。" in message for message in messages)
        assert any("下一篇定好了，开写时从第 2 卷接着写。" in message for message in messages)


async def test_revision_repeats_both_steps_with_current_version_and_flips(sessionmaker, monkeypatch):
    prompts = []
    original = demo.respond

    async def capture(schema, system, user):
        if schema.__name__ in {"NextArcDraft", "SegmentVolumesDraft"}:
            prompts.append((schema.__name__, user))
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)
    book_id = await seed(sessionmaker)
    job_id = await job_for(sessionmaker, book_id)
    await execute_job(job_id)
    first = await get_job(sessionmaker, job_id)
    assert first.status == "waiting_author", first.error
    # 等待期间改开关只影响下一篇，不能把本段已提交的修改意见当成自动确认。
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        book.settings = {**book.settings, "segment_approval": False}
        await session.commit()
    await execute_job(
        job_id, {"action": "revise", "feedback": "这一篇不要赶路", "flips": [{"topic": "目标", "choice": "先救出证人"}]}
    )
    revised = await get_job(sessionmaker, job_id)
    assert revised.status == "waiting_author", revised.error
    assert revised.pending["round"] == 2
    assert len(prompts) == 4
    assert "当前的下一篇" in prompts[2][1] and "当前的分卷与线索" in prompts[3][1]
    for _, prompt in prompts[2:]:
        assert "这一篇不要赶路" in prompt and "把「目标」改成「先救出证人」" in prompt
    async with sessionmaker() as session:
        requirements = {
            (row.text, row.source) for row in await session.scalars(select(Memory).where(Memory.book_id == book_id))
        }
        assert requirements == set()  # 本次意见和 flips 已直接传给重出，不能自动变成以后每章的规矩。
    await execute_job(job_id, {"action": "delegate"})
    assert (await get_job(sessionmaker, job_id)).status == "succeeded"
    # 下一篇则采用新设置，自动通过且手动规划任务仍然不开始写正文。
    next_job = await job_for(sessionmaker, book_id)
    await execute_job(next_job)
    finished = await get_job(sessionmaker, next_job)
    assert finished.status == "succeeded", finished.error
    async with sessionmaker() as session:
        endpoint = await session.scalar(
            select(StoryNode).where(StoryNode.book_id == book_id, StoryNode.segment["number"].as_integer() == 3)
        )
        assert endpoint.segment["status"] == "auto"
        assert await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.book_id == book_id)) == 0


@pytest.mark.parametrize("automatic", [True, False])
async def test_writing_enters_next_volume_gate_after_segment(sessionmaker, automatic):
    book_id = await seed(sessionmaker, approval=not automatic)
    job_id = await job_for(sessionmaker, book_id, until="book")
    await execute_job(job_id)
    job = await get_job(sessionmaker, job_id)
    assert job.status == "waiting_author", job.error
    if not automatic:
        assert job.pending["kind"] == "segment_review"
        await execute_job(job_id, {"action": "confirm"})
        job = await get_job(sessionmaker, job_id)
    assert job.pending["kind"] == "volume_review" and job.pending["volume"] == 2, job.error
    async with sessionmaker() as session:
        endpoint = await session.scalar(
            select(StoryNode).where(StoryNode.book_id == book_id, StoryNode.segment["number"].as_integer() == 2)
        )
        assert endpoint.segment["status"] == ("auto" if automatic else "confirmed")
        purposes = list(await session.scalars(select(LlmCall.purpose).where(LlmCall.job_id == job_id)))
        assert "写作·定下一篇" in purposes and "写作·下一篇分卷" in purposes
        if automatic:
            messages = list(
                await session.scalars(
                    select(MeetingMessage.content).where(
                        MeetingMessage.job_id == job_id, MeetingMessage.kind == "decision"
                    )
                )
            )
            assert any(
                "第 2 篇按设置自动通过" in message and "终点没锁，随时可以改。" in message for message in messages
            )
