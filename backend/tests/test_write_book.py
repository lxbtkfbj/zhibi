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


async def skip_first_volume(sessionmaker, book_id) -> None:
    """跳过第一卷的写作：直接标成写完，下一步就是拆第二卷。"""
    async with sessionmaker() as session:
        first = (await session.execute(select(Volume).where(Volume.book_id == book_id, Volume.index == 1))).scalar()
        first.status = "done"
        for u in (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == first.id))).scalars():
            u.status = "done"
        await session.commit()


async def purposes_of(sessionmaker, job_id) -> list[str]:
    async with sessionmaker() as session:
        return list(
            (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id).order_by(LlmCall.id)))
            .scalars()
            .all()
        )


def capture_prompts(monkeypatch) -> list[tuple[str, str]]:
    prompts: list[tuple[str, str]] = []
    original = demo.respond

    async def capture(schema, system, user):
        prompts.append((schema.__name__, user))
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", capture)
    return prompts


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
        assert "打斗再多一点" in book.requirements


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
        # 每个单元写完都有单元回顾，一卷写完有卷回顾
        assert all(u.recap for u in units)
        assert first.recap.startswith("第1卷经历了「捡灯」、「执法堂」")
        purposes = (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id))).scalars().all()
        assert purposes.count("写作·单元回顾") == 4 and purposes.count("写作·卷回顾") == 1

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
    # 分层前情：第一卷的卷回顾 + 最近几章
    assert "◆ 前面各卷回顾\n第1卷《杂役》：第1卷经历了" in plan_prompt and "◆ 最近几章" in plan_prompt

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
        assert "苏晚晴的戏份再多一点" in book.requirements


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


@pytest.mark.parametrize("thread", [None, "lorekeeper"])
async def test_notes_while_writing_become_requirements(sessionmaker, monkeypatch, thread):
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
                        book_id=book_id,
                        job_id=job_id,
                        speaker="author",
                        kind="note",
                        content="苏晚晴早点出场",
                        payload={"thread": thread} if thread else None,
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
    requirement = "苏晚晴早点出场"
    assert requirement in prompts[-1][1]  # 下一章开始照办
    async with sessionmaker() as session:
        assert requirement in (await session.get(Book, book_id)).requirements
        if thread:
            messages = (
                (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars().all()
            )
            replies = [m for m in messages if m.kind == "speech" and m.payload == {"thread": thread}]
            assert [(m.speaker, m.content) for m in replies] == [(thread, "收到，已经记下，之后的规划和章节都会照办。")]


async def artifacts_of(sessionmaker, job_id) -> list[MeetingMessage]:
    async with sessionmaker() as session:
        return list(
            (
                await session.execute(
                    select(MeetingMessage)
                    .where(MeetingMessage.job_id == job_id, MeetingMessage.kind == "artifact")
                    .order_by(MeetingMessage.id)
                )
            )
            .scalars()
            .all()
        )


async def test_volume_pitches_then_special_review(sessionmaker, monkeypatch):
    """拆第二卷：三个方向并行各拆一份 → 审稿比稿（选方案 2，融合方案 3）→ 专项审稿 → 自动改一轮 → 拍板。"""
    book_id = await approved_book(sessionmaker)
    # This scenario specifically covers three-way competition; balanced now defaults to two.
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        book.settings = {**book.settings, "effort_preset": "premium", "pitches": 3}
        await session.commit()
    await skip_first_volume(sessionmaker, book_id)
    prompts = capture_prompts(monkeypatch)

    job_id = await write_job(sessionmaker, book_id, count=1)
    await execute_job(job_id)
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "waiting_author", error
    assert pending == {"kind": "volume_review", "volume": 2, "title": "生死擂"}  # 问题都改掉了，没有遗留

    purposes = await purposes_of(sessionmaker, job_id)
    assert purposes[0] == "写作·第2卷比稿方向"
    assert sorted(purposes[1:4]) == ["写作·第2卷方案1", "写作·第2卷方案2", "写作·第2卷方案3"]  # 三份并行起草
    assert purposes[4:] == ["写作·第2卷比稿", "写作·第2卷融合方案", "写作·第2卷专项审稿", "写作·第2卷按专项审稿修改"]

    by_kind: dict[str, list[str]] = {}
    for name, user in prompts:
        by_kind.setdefault(name, []).append(user)
    # 想方向时看得到题材打法和前面用过的套路
    assert "【题材打法：通用" in by_kind["VolumeDirections"][0]
    assert "以弱胜强 1/8 次" in by_kind["VolumeDirections"][0]
    # 每份方案沿着自己的方向拆
    directions = {demo._match(r"【这一稿的方向：(.+?)】", u) for u in by_kind["VolumePlanDraft"][:3]}
    assert directions == {"步步为营", "借刀杀人", "并肩查案"}
    judge = by_kind["PitchJudgement"][0]
    assert all(f"【方案{i}：" in judge for i in (1, 2, 3)) and "◆ 套路上限" in judge
    # 方案 2 第一个单元接着用了第一卷最后一个单元的「比试竞赛」，程序先查出来，交给审稿和主编
    audit = by_kind["VolumeAudit"][0]
    assert "第1单元和上一个单元的核心套路都是「比试竞赛」" in audit
    fix = by_kind["VolumePlanDraft"][-1]
    assert "[反派智商] 第3单元：" in fix and "[套路重复] 第1单元：" in fix

    # 会议室：方向 → 三份方案 → 比稿结果 → 专项审稿 → 定稿的卷纲
    artifacts = await artifacts_of(sessionmaker, job_id)
    types = [m.payload["type"] for m in artifacts]
    assert types == ["volume_directions", *["volume_pitch"] * 3, "pitch_scores", "volume_audit", "volume_plan"]
    assert [d["name"] for d in artifacts[0].payload["data"]["directions"]] == ["步步为营", "借刀杀人", "并肩查案"]
    assert all(u["tropes"] and u["resolution"] for u in artifacts[1].payload["data"]["units"])
    scores = artifacts[4].payload["data"]
    assert scores["winner"] == 2 and "方案3" in scores["merge"]
    assert [row["total"] for row in scores["scores"]] == [24, 32, 28]
    assert artifacts[4].content == "比稿结果：方案2「借刀杀人」胜出，再融合其他方案的长处"
    report = artifacts[5].payload["data"]
    assert report["verdict"] == "revise"
    assert {c["aspect"]: c["ok"] for c in report["checks"]}["repetition"] is False  # 程序查出重复，这一项不算过关
    assert {i["aspect"] for i in report["issues"]} == {"villain", "repetition"}

    # 存库的是方案 2：融进了方案 3 的感情戏，对手补了后手，重复的套路换掉了
    async with sessionmaker() as session:
        second = (await session.execute(select(Volume).where(Volume.book_id == book_id, Volume.index == 2))).scalar()
        units = (
            (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == second.id).order_by(PlotUnit.index)))
            .scalars()
            .all()
        )
    assert second.status == "detailed" and sum(u.chapter_count for u in units) == 90
    assert [u.title for u in units[:2]] == ["交锋·其1", "夜探·其2"]
    assert units[0].tropes == ["对质揭穿"] and units[0].resolution == "算计设局"
    assert units[0].goal == "在比试中站稳脚跟"  # 两轮修改后各字段仍是原样，没有混进别的内容
    assert units[1].key_events == ["起因", "苏晚晴暗中提醒陆远小心长老", "试探", "冲突升级", "高潮", "收尾与钩子"]
    assert units[2].key_events[2] == "对手提前布下假账册当诱饵，陆远将计就计"
    assert all(u.tropes and u.resolution for u in units)
    assert all("\n" not in f for u in units for f in (u.goal, u.conflict, u.climax, u.outcome, u.resolution))


async def test_rule_issues_force_revision_and_reach_author(sessionmaker, monkeypatch):
    """审稿放行，程序查出套路超限照样改一轮；改完还没解决的，拍板时一并告诉作者。只有一个方向就不比稿。"""
    book_id = await approved_book(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        book.settings = {**book.settings, "effort_preset": "custom", "pitches": 1}
        await session.commit()
    await skip_first_volume(sessionmaker, book_id)
    original = demo.respond

    async def stubborn(schema, system, user):
        if schema is demo.s.VolumeDirections:
            return demo.s.VolumeDirections(
                directions=[demo.s.VolumeDirection(name="一路比到底", idea="每个单元都是比试")], remark="就这一个方向。"
            )
        if schema is demo.s.VolumePlanDraft:
            plan = await original(schema, system, user)
            for u in plan.units:
                u.tropes, u.resolution = ["比试竞赛"], "临阵突破"
            return plan
        if schema is demo.s.VolumeAudit:
            return demo.s.VolumeAudit(verdict="pass", checks=[], issues=[], remark="挺好。")
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", stubborn)
    job_id = await write_job(sessionmaker, book_id, count=1)
    await execute_job(job_id)
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "waiting_author", error
    purposes = await purposes_of(sessionmaker, job_id)
    assert purposes == ["写作·第2卷方案1", "写作·第2卷专项审稿", "写作·第2卷按专项审稿修改"]
    assert pending["kind"] == "volume_review"
    assert any("套路「比试竞赛」全书最多用 4 次" in line for line in pending["issues"])
    assert any("破局手法「临阵突破」连着用了 2 个单元" in line for line in pending["issues"])
    types = [m.payload["type"] for m in await artifacts_of(sessionmaker, job_id)]
    assert types == ["volume_pitch", "volume_audit", "volume_plan"]

    # 作者看过后批准，问题不再挂着
    await execute_job(job_id, {"action": "approve"})
    status, pending, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error


async def test_chapter_plan_gets_only_the_unit_tropes(sessionmaker, monkeypatch):
    book_id = await approved_book(sessionmaker)
    prompts = capture_prompts(monkeypatch)
    job_id = await write_job(sessionmaker, book_id, count=1)
    await execute_job(job_id)
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    prompt = next(user for name, user in prompts if name == "ChapterPlanDraft")
    # 第一单元「捡灯」用的是以弱胜强：章纲只带这一个套路的写法
    assert "【题材打法：通用" in prompt and "以弱胜强（全书最多 8 次）" in prompt
    assert "比试竞赛（全书最多" not in prompt
    assert "套路：以弱胜强；破局：底牌显露" in prompt
