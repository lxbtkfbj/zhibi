"""整本书收尾：真实隔离库验证增量边界、作者保护和分段原子性。"""

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo, demo_teardown
from app.models import Book, Chapter, Foreshadowing, Job, MeetingMessage, PlotUnit, StoryNode, Volume
from app.prompts import default_content, render
from app.services import teardown_closing as closing
from app.services import teardown_rerun
from app.services.teardown_runner import Runner, TeardownStopped
from tests.test_teardown_runner import DemoRouter, create_book


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def fast_prompts(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)


async def runner_for(sm, redis, *, volumes=4, per_volume=2, grouped=True):
    bid, jid = await create_book(sm, count=volumes * per_volume, volume_size=per_volume, original=True, read=True)
    runner = Runner(jid, sm, redis, DemoRouter())
    await runner.initialize()
    if grouped:
        while await runner.group_once(final=True):
            pass
    async with sm() as session:
        for volume in await session.scalars(select(Volume).where(Volume.book_id == bid)):
            volume.summary = f"卷{volume.index}起步；面临对手；高潮推进；离开舞台"
        await session.commit()
    runner.router.calls.clear()
    return runner


async def story_nodes(runner):
    async with runner.sm() as session:
        return list(
            await session.scalars(
                select(StoryNode).where(StoryNode.book_id == runner.book_id).order_by(StoryNode.position)
            )
        )


async def test_arcs_under_three_removes_arcs_and_links_not_ending(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=2)
    async with sessionmaker() as session:
        arc = StoryNode(
            book_id=runner.book_id,
            kind="milestone",
            title="旧篇",
            position=1,
            segment={"title": "旧篇", "text": "旧话"},
        )
        ending = StoryNode(book_id=runner.book_id, kind="ending", title="结局", event="结局原文", position=2)
        session.add_all([arc, ending])
        await session.flush()
        for volume in await session.scalars(select(Volume)):
            volume.target_node_id = arc.id
        book = await session.get(Book, runner.book_id)
        book.teardown = {**book.teardown, "arcs": {"old": True, "failed": True}}
        await session.commit()
    assert await closing.collect_arcs(runner, final=True) == {"count": 0}
    assert not runner.router.calls
    nodes = await story_nodes(runner)
    assert len(nodes) == 1 and nodes[0].kind == "ending" and nodes[0].event == "结局原文" and nodes[0].position == 2
    book, _, _, volumes = await runner.snapshot()
    assert "arcs" not in book.teardown and all(v.target_node_id is None for v in volumes)


async def test_arcs_nonfinal_final_cache_repair_reuse_and_ending_last(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis)
    async with sessionmaker() as session:
        session.add(StoryNode(book_id=runner.book_id, position=1, kind="ending", title="结局", event="旧结局"))
        await session.commit()
    await closing.collect_arcs(runner, final=False)
    _, _, _, volumes = await runner.snapshot()
    assert volumes[-1].target_node_id is None and all(v.target_node_id for v in volumes[:-1])
    first_ids = [n.id for n in await story_nodes(runner) if n.kind == "milestone"]
    assert len(first_ids) == 2
    await closing.collect_arcs(runner, final=True)
    nodes = await story_nodes(runner)
    assert [n.id for n in nodes if n.kind == "milestone"] == first_ids
    assert nodes[-1].kind == "ending" and nodes[-1].position == 3
    _, _, _, volumes = await runner.snapshot()
    assert all(v.target_node_id for v in volumes)
    async with sessionmaker() as session:
        (await session.get(Volume, volumes[0].id)).target_node_id = None
        book = await session.get(Book, runner.book_id)
        book.teardown = {**book.teardown, "arcs": {**book.teardown["arcs"], "failed": True}}
        await session.commit()
    runner.router.calls.clear()
    await closing.collect_arcs(runner, final=True)
    assert not runner.router.calls
    assert (await runner.snapshot())[3][0].target_node_id == first_ids[0]
    assert "failed" not in (await runner.snapshot())[0].teardown["arcs"]


async def test_arc_author_edit_protected_until_its_volume_membership_changes(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis)
    await closing.collect_arcs(runner, final=True)
    first = (await story_nodes(runner))[0]
    async with sessionmaker() as session:
        node = await session.get(StoryNode, first.id)
        node.title, node.segment = "作者篇名", {"title": "作者篇名", "text": "作者改的那段话"}
        await session.commit()
    await closing.collect_arcs(runner, final=True, force=True)
    assert (await story_nodes(runner))[0].segment == {"title": "作者篇名", "text": "作者改的那段话"}

    async def changed(call):
        return s.TeardownArcs(
            arcs=[
                s.TeardownArc(first=1, last=3, title="新一篇", text="新话一"),
                s.TeardownArc(first=4, last=4, title="新二篇", text="新话二"),
            ]
        )

    runner.router.hook = changed
    await closing.collect_arcs(runner, final=True, force=True)
    nodes = await story_nodes(runner)
    assert nodes[0].id == first.id and nodes[0].segment == {"title": "新一篇", "text": "新话一"}


@pytest.mark.parametrize("kind", ["gap", "count", "title"])
async def test_arc_validation_three_attempts(kind, sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=3)

    async def invalid(call):
        if kind == "gap":
            arcs = [s.TeardownArc(first=2, last=3, title="断开的篇", text="话")]
        elif kind == "count":
            arcs = [s.TeardownArc(first=n, last=n, title="太碎的篇", text="话") for n in range(1, 4)]
        else:
            arcs = [s.TeardownArc(first=1, last=3, title=" ", text="话")]
        return s.TeardownArcs(arcs=arcs)

    runner.router.hook = invalid
    with pytest.raises(TeardownStopped, match="归了三次都对不上"):
        await closing.collect_arcs(runner, final=True)
    assert len(runner.router.calls) == 3 and "【上次归得不对】" in runner.router.calls[-1]["user"]
    if kind == "count":
        assert "分了 3 篇，最多 2 篇" in runner.router.calls[-1]["user"]
    assert not await story_nodes(runner)


def test_closed_volume_prefix_never_crosses_gap_or_open_volume():
    volumes = [SimpleNamespace(index=n, id=str(n), summary="收住") for n in range(1, 5)]
    assert len(closing.closed_volumes(SimpleNamespace(teardown={"open_volume_id": "3"}), volumes)) == 2
    assert (
        len(
            closing.closed_volumes(SimpleNamespace(teardown={"original_volumes": True, "open_volume_id": "3"}), volumes)
        )
        == 4
    )
    volumes[1].summary = ""
    assert len(closing.closed_volumes(SimpleNamespace(teardown={}), volumes)) == 1


def test_ending_hints_exact_sources_and_non_bonus_tail():
    book = SimpleNamespace(teardown={"excluded": []})
    chapter = SimpleNamespace(title="普通章名", content="未完的故事", teardown={"raw_title": "第1章"})
    assert closing.ending_hint(book, [chapter])[0] == ""
    chapter.content = "全书完" + "字" * 300
    assert closing.ending_hint(book, [chapter])[0] == ""
    chapter.content = "字" * 300 + "全书完"
    bonus = SimpleNamespace(title="番外", content="正文不用于判断：完结", teardown={"flags": ["番外"]})
    assert closing.ending_hint(book, [chapter, bonus])[0] == "全书完"
    chapter.content = "未完的故事"
    book.teardown = {"excluded": [{"title": "完本感言"}]}
    assert closing.ending_hint(book, [chapter])[0] == "完本"


async def test_ending_build_cache_then_false_deletes(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=3)
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).order_by(Chapter.index.desc()).limit(1))
        chapter.title = "大结局"
        await session.commit()
    await closing.collect_arcs(runner, final=True)
    first = await closing.collect_ending(runner)
    assert first["ended"] and first["hint"] == "大结局"
    ending = (await story_nodes(runner))[-1]
    assert ending.kind == "ending" and ending.segment is None and ending.event.count("；") == 3
    runner.router.calls.clear()
    assert await closing.collect_ending(runner) == first
    assert not runner.router.calls
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).order_by(Chapter.index.desc()).limit(1))
        chapter.title = "新的未完章"
        await session.commit()
    second = await closing.collect_ending(runner)
    assert not second["ended"] and all(n.kind != "ending" for n in await story_nodes(runner))


def test_wait_batches_two_limits_at_least_one_and_skip_unread():
    def chapter(index, count=0, read=True):
        return SimpleNamespace(
            index=index, teardown={"read_version": 1 if read else None, "read": {"waits": [{}] * count}}
        )

    assert [len(b) for b in closing.wait_batches([chapter(n) for n in range(1, 163)])] == [80, 80, 2]
    assert [len(b) for b in closing.wait_batches([chapter(1, 100), chapter(2, 51), chapter(3, 99)])] == [1, 2]
    assert [len(b) for b in closing.wait_batches([chapter(1, 151), chapter(2)])] == [1, 1]
    assert [
        [c.index for c in b] for b in closing.wait_batches([chapter(1), chapter(2, read=False), chapter(3)], after=1)
    ] == [[3]]


@pytest.mark.parametrize(
    "bad",
    [
        {"new": [{"ref": "bad", "chapter": 2, "kind": "期待", "what": "事情"}]},
        {"new": [{"ref": "N1", "chapter": 2, "kind": "期待", "what": "事情"}] * 2},
        {"new": [{"ref": "N1", "chapter": 99, "kind": "期待", "what": "事情"}]},
        {"new": [{"ref": "N1", "chapter": 2, "kind": "期待", "what": "字" * 41}]},
        {"hinted": [{"code": "F99", "chapter": 2}]},
        {"hinted": [{"code": "E1", "chapter": 1}]},
        {"resolved": [{"code": "E1", "chapter": 3, "how": "了结"}] * 2},
    ],
)
async def test_wait_invalid_rows_retry_without_partial_write(bad, sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=1, per_volume=3)
    async with sessionmaker() as session:
        session.add(
            Foreshadowing(
                book_id=runner.book_id, seq=1, kind="期待", description="已有期待", planted_chapter=2, status="planted"
            )
        )
        await session.commit()
    seen = 0

    async def invalid_once(call):
        nonlocal seen
        seen += 1
        return s.TeardownWaitLedger.model_validate(bad) if seen == 1 else s.TeardownWaitLedger()

    runner.router.hook = invalid_once
    result = await closing.collect_waits(runner)
    assert seen == 2 and result["upto"] == 3 and result["total"] == 1
    assert "【上次记得不对】" in runner.router.calls[-1]["user"]


async def test_wait_three_bad_attempts_stops_at_prior_batch_and_does_not_jump(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=1, per_volume=162, grouped=False)

    async def invalid_second(call):
        if "【这一段：第 1–80 章】" in call["user"]:
            return s.TeardownWaitLedger(new=[s.TeardownWaitNew(ref="N1", chapter=1, kind="期待", what="等待赴约")])
        return s.TeardownWaitLedger(hinted=[s.TeardownWaitHint(code="E999", chapter=81)])

    runner.router.hook = invalid_second
    with pytest.raises(ValueError, match="第 81–160 章记了三次都对不上"):
        await closing.collect_waits(runner)
    book, _, _, _ = await runner.snapshot()
    assert book.teardown["waits"]["upto"] == 80
    assert len(runner.router.calls) == 4 and not any("第 161–162 章】" in c["user"] for c in runner.router.calls)
    async with sessionmaker() as session:
        assert len(list(await session.scalars(select(Foreshadowing)))) == 1


async def test_wait_zero_read_version_is_included_and_used_as_open_span_endpoint(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=1, per_volume=1)
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == runner.book_id))
        chapter.teardown = {
            **chapter.teardown,
            "read_version": 0,
            "read": {**chapter.teardown["read"], "waits": [{"action": "立下", "what": "等待赴约"}]},
        }
        await session.commit()
    state = await closing.collect_waits(runner)
    assert (state["upto"], state["total"], state["open"]) == (1, 1, 1)
    async with sessionmaker() as session:
        row = await session.scalar(select(Foreshadowing).where(Foreshadowing.book_id == runner.book_id))
        assert row.description == "等待赴约" and row.planted_chapter == 1 and row.span == "短"


async def test_wait_new_hint_resolve_codes_plans_spans_and_force_reset(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=2, per_volume=3)
    async with sessionmaker() as session:
        chapters = list(await session.scalars(select(Chapter).order_by(Chapter.index)))
        volume = await session.get(Volume, chapters[0].volume_id)
        extra = PlotUnit(
            book_id=runner.book_id, volume_id=volume.id, index=2, title="第二单元", summary="话", chapter_count=1
        )
        session.add(extra)
        await session.flush()
        chapters[2].unit_id = extra.id
        await session.commit()

    async def ledger(call):
        return s.TeardownWaitLedger(
            new=[
                s.TeardownWaitNew(ref=f"N{n}", chapter=1, kind="期待" if n == 1 else "伏笔", what=f"等待事情{n}")
                for n in range(1, 4)
            ],
            hinted=[s.TeardownWaitHint(code="n1", chapter=2)] * 2,
            resolved=[
                s.TeardownWaitDone(code="N1", chapter=2, how="赴约"),
                s.TeardownWaitDone(code="N2", chapter=3, how="真相揭开"),
            ],
        )

    runner.router.hook = ledger
    result = await closing.collect_waits(runner)
    assert (result["total"], result["open"], result["upto"]) == (3, 1, 6)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Foreshadowing).order_by(Foreshadowing.seq)))
        assert [closing.wait_code(row) for row in rows] == ["E1", "F2", "F3"]
        assert [row.span for row in rows] == ["短", "中", "长"]
        assert rows[0].hint_chapters == [2] and rows[0].payoff_plan == "第 2 章：赴约"
        assert rows[0].plant_plan == "第 1 章" and rows[0].plant_volume == rows[0].payoff_volume == 1
        assert rows[-1].node_id is None and rows[-1].resolved_chapter is None
    runner.router.calls.clear()
    await closing.collect_waits(runner)
    assert not runner.router.calls
    await closing.collect_waits(runner, force=True)
    assert len(runner.router.calls) == 1
    async with sessionmaker() as session:
        assert len(list(await session.scalars(select(Foreshadowing)))) == 3


async def test_settings_only_groups_unfinished_final_chapters_without_read_and_closes_all_four(
    sessionmaker, redis, monkeypatch
):
    runner = await runner_for(sessionmaker, redis, volumes=3, grouped=False)
    seen = []
    async with sessionmaker() as session:
        job = await session.get(Job, runner.job_id)
        job.params = {"settings_only": True}
        book = await session.get(Book, runner.book_id)
        book.teardown = {**book.teardown, "stage": "stopped"}
        for volume in await session.scalars(select(Volume)):
            volume.summary = ""
        await session.commit()
    originals = {name: getattr(closing, name) for name in ("collect_arcs", "collect_ending", "collect_waits")}
    for name, original in originals.items():

        async def wrapped(runner, _name=name, _original=original, **kwargs):
            seen.append(_name)
            _, chapters, _, volumes = await runner.snapshot()
            assert all(c.unit_id for c in chapters) and all(v.summary for v in volumes)
            return await _original(runner, **kwargs)

        monkeypatch.setattr(closing, name, wrapped)

    async def settings(runner):
        seen.append("settings")
        return {"characters": 0, "entries": 0}

    monkeypatch.setattr("app.services.teardown_settings.collect_settings", settings)
    await runner.run()
    book, chapters, _, _ = await runner.snapshot()
    assert book.teardown["stage"] == "done" and all(c.unit_id for c in chapters)
    assert seen == ["collect_arcs", "collect_ending", "settings", "collect_waits"]
    assert not any(c["schema"] is s.TeardownRead for c in runner.router.calls)


async def test_settings_only_ai_volume_finishes_unassigned_tail_and_clears_open_volume(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=12, original=False, read=True)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.params = {"settings_only": True}
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stage": "stopped", "stop_reason": "author"}
        await session.commit()
    router = DemoRouter()
    runner = Runner(jid, sessionmaker, redis, router)
    await runner.run()
    book, chapters, _, volumes = await runner.snapshot()
    assert book.teardown["stage"] == "done" and book.teardown["open_volume_id"] is None
    assert all(c.unit_id for c in chapters) and all(v.summary for v in volumes)
    assert book.teardown["ending"]["upto"] == book.teardown["settings"]["upto"] == book.teardown["waits"]["upto"] == 12
    schemas = [call["schema"] for call in router.calls]
    assert s.TeardownRead not in schemas and s.TeardownUnits in schemas and s.TeardownVolumes in schemas
    from app.services.teardown_info import needs_closing

    assert not needs_closing(book.teardown, 12, 12)


async def test_closing_errors_do_not_block_following_steps_and_use_done_retry_label(sessionmaker, redis, monkeypatch):
    runner = await runner_for(sessionmaker, redis, volumes=3)
    seen = []

    async def fail_arcs(*args, **kwargs):
        seen.append("arcs")
        raise ValueError("篇格式错")

    async def fail_ending(*args, **kwargs):
        seen.append("ending")
        raise ValueError("结局格式错")

    async def settings(runner):
        seen.append("settings")
        return {"characters": 0, "entries": 0}

    async def fail_waits(*args, **kwargs):
        seen.append("waits")
        raise ValueError("账格式错")

    monkeypatch.setattr(closing, "collect_arcs", fail_arcs)
    monkeypatch.setattr(closing, "collect_ending", fail_ending)
    monkeypatch.setattr(closing, "collect_waits", fail_waits)
    monkeypatch.setattr("app.services.teardown_settings.collect_settings", settings)
    await runner.finish()
    book, _, _, _ = await runner.snapshot()
    expected = "归篇没做完（篇格式错），写全书结局没做完（结局格式错），整理读者在等的事没做完（账格式错），点「补上整理」再试一次。"
    assert seen == ["arcs", "ending", "settings", "waits"] and book.teardown["stage"] == "done"
    assert book.teardown["stop_note"] == expected
    assert book.teardown["arcs"]["failed"] is True
    async with sessionmaker() as session:
        assert expected in (await session.scalar(select(MeetingMessage))).content


async def test_only_arc_failure_keeps_closing_available_then_success_clears_explicit_error(sessionmaker, redis):
    from app.services.teardown_info import needs_closing

    runner = await runner_for(sessionmaker, redis, volumes=3)
    await closing.collect_arcs(runner, final=True)
    old_arcs = dict((await runner.snapshot())[0].teardown["arcs"])
    async with sessionmaker() as session:
        volume = await session.scalar(select(Volume).order_by(Volume.index).limit(1))
        volume.summary += "；这一卷的记录有了变化"
        await session.commit()

    async def bad_arcs(call):
        if call["schema"] is s.TeardownArcs:
            return s.TeardownArcs(arcs=[])

    runner.router.hook = bad_arcs
    await runner.finish()
    book, _, _, _ = await runner.snapshot()
    assert book.teardown["stage"] == "done" and book.teardown["arcs"]["failed"] is True
    assert book.teardown["arcs"] == {**old_arcs, "failed": True}
    assert book.teardown["settings"]["upto"] == book.teardown["waits"]["upto"] == book.teardown["ending"]["upto"] == 6
    assert needs_closing(book.teardown, 6, 6)
    old_ending = dict(book.teardown["ending"])
    runner.router.hook = None
    runner.router.calls.clear()
    async with sessionmaker() as session:
        job = Job(
            book_id=book.id, kind="teardown", thread_id="arc-retry", status="queued", params={"settings_only": True}
        )
        session.add(job)
        await session.commit()
        jid = job.id
    retry = Runner(jid, sessionmaker, redis, runner.router)
    await retry.run()
    book, _, _, _ = await retry.snapshot()
    assert book.teardown["stage"] == "done" and "failed" not in book.teardown["arcs"]
    assert not needs_closing(book.teardown, 6, 6)
    # 篇成功后结局输入因新增篇而变化，可重写判断；无需重读或重记已经完成的账。
    assert book.teardown["ending"]["upto"] == old_ending["upto"]
    assert all(c["schema"] not in (s.TeardownRead, s.TeardownWaitLedger) for c in runner.router.calls)


def test_demo_new_schemas_and_exact_literal_wait_matching():
    user = render(
        "teardown_waits",
        title="书",
        first="2",
        last="4",
        open="E9｜期待｜第 1 章立下｜等待赴约｜还没提起过",
        chapters="第 2 章：起步\n  立下：身世真相\n  提起：等待赴约\n第 3 章：揭开\n  兑现：身世真相\n第 4 章：赴约\n  兑现：等待赴约",
    )
    result = demo_teardown.respond(s.TeardownWaitLedger, user)
    assert result.new[0].what == "身世真相" and result.new[0].kind == "伏笔"
    assert [(h.code, h.chapter) for h in result.hinted] == [("E9", 2)]
    assert [(r.code, r.chapter) for r in result.resolved] == [("N1", 3), ("E9", 4)]


@pytest.mark.parametrize("step", ["arcs", "ending", "waits"])
async def test_rerun_new_step_estimate_force_only_selected_and_checkpoint(step, sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=4)
    async with sessionmaker() as session:
        (await session.get(Job, runner.job_id)).status = "succeeded"
        book = await session.get(Book, runner.book_id)
        book.teardown = {**book.teardown, "stage": "done", **({"arcs": {"failed": True}} if step == "arcs" else {})}
        if step == "arcs":
            chapter = await session.scalar(
                select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index).limit(1)
            )
            chapter.teardown = {**chapter.teardown, "read_version": 0}
        if step == "waits":
            session.add(
                Foreshadowing(
                    book_id=book.id,
                    seq=90,
                    kind="期待",
                    description="旧账必须先清空",
                    planted_chapter=1,
                    status="planted",
                )
            )
        await session.commit()
        info = await teardown_rerun.plan(session, runner.book_id, step, None, None)
        assert info["calls"] == 1
        with pytest.raises(Exception, match="不接受 --from 或 --to"):
            await teardown_rerun.plan(session, runner.book_id, step, 1, None)
        job = await teardown_rerun.prepare(session, runner.book_id, step, None, None, force=True)
        jid = job.id
    await teardown_rerun.run_rerun(jid, sessionmaker, redis, runner.router)
    schema = {"arcs": s.TeardownArcs, "ending": s.TeardownEnding, "waits": s.TeardownWaitLedger}[step]
    assert [call["schema"] for call in runner.router.calls] == [schema]
    if step == "arcs":
        assert "这是全书最后几卷：全部归完，open_from 写 null。" in runner.router.calls[0]["user"]
        assert all(volume.target_node_id for volume in (await runner.snapshot())[3])
    async with sessionmaker() as session:
        from app.models import BookSave

        assert (await session.get(Job, jid)).status == "succeeded"
        assert (await session.get(Book, runner.book_id)).teardown["stage"] == "done"
        if step == "arcs":
            assert "failed" not in (await session.get(Book, runner.book_id)).teardown["arcs"]
        assert await session.scalar(select(BookSave.title)) == f"重跑：{step}"
        if step == "waits":
            assert not list(await session.scalars(select(Foreshadowing)))


async def test_rerun_arcs_and_ending_preconditions_exact_errors(sessionmaker, redis):
    runner = await runner_for(sessionmaker, redis, volumes=2, grouped=False)
    async with sessionmaker() as session:
        (await session.get(Job, runner.job_id)).status = "succeeded"
        await session.commit()
        from fastapi import HTTPException

        for step, message in [("arcs", "收住的卷不到 3 卷，不用归篇"), ("ending", "还没拆到最后一章，写不了结局")]:
            with pytest.raises(HTTPException) as caught:
                await teardown_rerun.plan(session, runner.book_id, step, None, None)
            assert caught.value.status_code == 422 and caught.value.detail == message


def test_new_prompt_bytes_and_schema_field_order_descriptions_match_task_verbatim():
    root = Path(__file__).resolve().parents[2]
    expected = {
        "teardown_arcs": "bfa6e94e292d8925ab0caca9d6c6f1fad0d023e4ffbec8457f8fe05165789987",
        "teardown_ending": "930f929cd720cb9f53a829f00af125ef9d350d41470da6d2438332f76ea4eee5",
        "teardown_waits": "1b5ca882b7eb7333a31261f99760f174f02893bdf8eb8315eee214311f1a32fe",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((root / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == digest
        assert not (root / f"docs/codex任务/拆书第五批/提示词/{name}.md").exists()
    task = (root / "docs/codex任务/拆书第五批/1-篇结局和读者在等的事.md").read_text(encoding="utf-8")
    supplied = ast.parse(task.split("```python\n", 1)[1].split("```", 1)[0])
    implemented = ast.parse((root / "backend/app/agents/schemas.py").read_text(encoding="utf-8"))
    actual = {node.name: node for node in implemented.body if isinstance(node, ast.ClassDef)}
    for node in supplied.body:
        assert ast.dump(node) == ast.dump(actual[node.name])
