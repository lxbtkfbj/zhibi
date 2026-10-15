"""写书主循环（演示模型）：章纲 → 写 → 审稿与设定检查并行 → 退稿重写 → 定稿入库 → 试读 → 卷纲拍板。"""

import uuid

import pytest
from sqlalchemy import func, select

from app.graphs.write_book import clean_text
from app.llm import demo
from app.models import Book, Chapter, Character, Foreshadowing, Job, LlmCall, MeetingMessage, PlotUnit, Volume
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


async def approved_book(sessionmaker) -> uuid.UUID:
    """跑完开书流程并批准，返回书的 ID。"""
    async with sessionmaker() as session:
        book = Book(idea="一个能看见别人寿命的少年")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="book_setup", thread_id=f"setup-{uuid.uuid4()}", params={"idea": book.idea})
        session.add(job)
        await session.commit()
        book_id, job_id = book.id, job.id
    await execute_job(job_id)
    await execute_job(job_id, {"action": "approve"})
    return book_id


async def write_job(sessionmaker, book_id, until="count", count=3) -> uuid.UUID:
    async with sessionmaker() as session:
        job = Job(
            book_id=book_id,
            kind="write_book",
            thread_id=f"write-{uuid.uuid4()}",
            params={"until": until, "count": count},
        )
        session.add(job)
        await session.commit()
        return job.id


async def job_state(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        return job.status, job.pending, job.error


async def chapters(sessionmaker, book_id) -> list[Chapter]:
    async with sessionmaker() as session:
        return list(
            (await session.execute(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index)))
            .scalars()
            .all()
        )


def test_clean_text():
    assert clean_text("第一章 捡灯\n\n正文第一段。\n\n（本章完）") == "正文第一段。"
    assert clean_text("正文。") == "正文。"


async def test_first_chapters_then_trial_read(sessionmaker):
    book_id = await approved_book(sessionmaker)
    job_id = await write_job(sessionmaker, book_id, count=3)

    await execute_job(job_id)
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == "trial_read"  # 新书写完前 3 章，请作者试读

    rows = await chapters(sessionmaker, book_id)
    # 第一个单元出了 6 章章纲，前 3 章定稿
    assert [c.index for c in rows] == [1, 2, 3, 4, 5, 6]
    assert [c.status for c in rows] == ["final"] * 3 + ["planned"] * 3
    assert all(c.outline.get("hook") and c.outline.get("scenes") for c in rows)
    assert all(c.content and c.summary and c.word_count > 0 for c in rows[:3])
    # 第 2 章初稿被审稿退回，重写一次后通过
    assert rows[1].attempts == 1 and "重写稿" in rows[1].content
    assert rows[1].review["review"]["verdict"] == "pass"

    async with sessionmaker() as session:
        # 第一单元的伏笔 F1 写进了第 1 章，设定师把它记为已埋下
        f1 = (
            await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id, Foreshadowing.seq == 1))
        ).scalar()
        assert f1.status == "planted" and f1.planted_chapter == 1
        hero = (
            await session.execute(select(Character).where(Character.book_id == book_id, Character.name == "陆远"))
        ).scalar()
        assert hero.condition == "伤势好转，心事更重"
        purposes = (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id))).scalars().all()
        assert purposes.count("写作·章纲") == 1
        assert purposes.count("写作·正文") == 4  # 3 章，其中一章重写一次
        assert purposes.count("写作·审稿") == 4 and purposes.count("写作·设定检查") == 4
        assert purposes.count("写作·更新设定库") == 3
        kinds = {
            m.payload["type"]
            for m in (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars()
            if m.kind == "artifact"
        }
        assert kinds >= {"chapter_plan", "chapter_draft", "chapter_review", "chapter_final"}

    await execute_job(job_id, {"action": "revise", "feedback": "打斗再多一点"})
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error  # 这一轮写够 3 章就停
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.trial_read_done
        assert "前 3 章试读意见：打斗再多一点" in book.requirements


async def test_whole_volume_then_next_volume_plan(sessionmaker, monkeypatch):
    book_id = await approved_book(sessionmaker)
    job_id = await write_job(sessionmaker, book_id, count=3)
    await execute_job(job_id)
    await execute_job(job_id, {"action": "approve"})

    # 写完第一卷：剩下的章节按单元逐个出章纲、逐章写
    job_id = await write_job(sessionmaker, book_id, until="volume")
    await execute_job(job_id)
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    rows = await chapters(sessionmaker, book_id)
    assert len(rows) == 31 and all(c.status == "final" for c in rows)
    async with sessionmaker() as session:
        first = (await session.execute(select(Volume).where(Volume.book_id == book_id, Volume.index == 1))).scalar()
        assert first.status == "done"
        units = (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == first.id))).scalars().all()
        assert {u.status for u in units} == {"done"}
        # 每个单元的章节数就是章纲给出的章数
        for unit in units:
            count = await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.unit_id == unit.id))
            assert count == unit.chapter_count

    # 再写一章：先拆第二卷卷纲，等作者拍板
    prompts: list[str] = []
    original = demo.respond

    async def capture(schema, system, user):
        prompts.append(user)
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)
    job_id = await write_job(sessionmaker, book_id, count=1)
    await execute_job(job_id)
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending == {"kind": "volume_review", "volume": 2, "title": "生死擂"}
    # 拆第二卷时看得到前情和前面用过的破局方式，避免套路重复
    plan_prompt = next(p for p in prompts if "请为第 2 卷写「卷纲」" in p)
    assert "前面已经用过的高潮与破局方式" in plan_prompt and "外门考核" in plan_prompt
    assert "第31章" in plan_prompt

    async with sessionmaker() as session:
        second = (await session.execute(select(Volume).where(Volume.book_id == book_id, Volume.index == 2))).scalar()
        assert second.status == "detailed"
        units = (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == second.id))).scalars().all()
        assert sum(u.chapter_count for u in units) == 90

    # 作者提意见 → 主编改卷纲 → 再次拍板 → 批准后开写
    await execute_job(job_id, {"action": "revise", "feedback": "苏晚晴的戏份再多一点"})
    status, pending, _ = await job_state(sessionmaker, job_id)
    assert pending["kind"] == "volume_review"
    assert "【修改要求】\n苏晚晴的戏份再多一点" in [p for p in prompts if "请为第 2 卷写「卷纲」" in p][-1]
    await execute_job(job_id, {"action": "approve"})
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    rows = await chapters(sessionmaker, book_id)
    assert rows[31].status == "final" and rows[31].index == 32
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert "第2卷卷纲的修改意见：苏晚晴的戏份再多一点" in book.requirements


async def test_chapter_stuck_goes_to_author(sessionmaker, monkeypatch):
    book_id = await approved_book(sessionmaker)
    original = demo.respond

    async def harsh(schema, system, user):
        if schema.__name__ == "ChapterReview":
            return demo.s.ChapterReview(
                verdict="revise",
                issues=[demo.s.ChapterIssue(problem="不够爽", suggestion="再爽一点", severity="high")],
                remark="不行。",
            )
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", harsh)
    job_id = await write_job(sessionmaker, book_id, count=1)
    await execute_job(job_id)
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending["kind"] == "chapter_stuck" and pending["chapter"] == 1
    assert pending["issues"] == ["[审稿] 不够爽——再爽一点"]
    rows = await chapters(sessionmaker, book_id)
    assert rows[0].attempts == 2 and rows[0].status == "drafting"

    await execute_job(job_id, {"action": "approve"})  # 作者拍板：就这样定稿
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    assert (await chapters(sessionmaker, book_id))[0].status == "final"


async def test_notes_while_writing_become_requirements(sessionmaker, monkeypatch):
    book_id = await approved_book(sessionmaker)
    job_id = await write_job(sessionmaker, book_id, count=2)
    prompts: list[tuple[str, str]] = []
    original_stream = demo.stream_text

    async def stream(system, user):
        prompts.append(("write", user))
        if len(prompts) == 1:
            # 写第一章时作者插了一句话
            async with sessionmaker() as session:
                session.add(
                    MeetingMessage(
                        book_id=book_id, job_id=job_id, speaker="author", kind="note", content="苏晚晴早点出场"
                    )
                )
                await session.commit()
        async for chunk in original_stream(system, user):
            yield chunk

    monkeypatch.setattr(demo, "stream_text", stream)
    await execute_job(job_id)
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    assert "苏晚晴早点出场" not in prompts[0][1]
    assert "苏晚晴早点出场" in prompts[-1][1]  # 下一章开始照办
    async with sessionmaker() as session:
        assert "苏晚晴早点出场" in (await session.get(Book, book_id)).requirements
