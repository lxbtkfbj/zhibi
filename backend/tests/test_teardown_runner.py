"""拆书流水线：真实数据库落库，演示模型及可控失败验证边界。"""

import asyncio
import re
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.graphs.deps import JobCancelled, cancel_key
from app.llm import demo
from app.models import Book, BookSave, Chapter, Job, MeetingMessage, PlotUnit, Volume
from app.prompts import default_content
from app.services import book_saves
from app.services.teardown_roster import Roster
from app.services.teardown_runner import (
    Runner,
    TeardownStopped,
    chapter_text,
    check_groups,
    make_batches,
    unit_tail_rule,
)


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def fast_prompts_and_demo(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)


class DemoRouter:
    def __init__(self, hook=None):
        self.hook, self.calls, self.book_id = hook, [], None

    async def structured(self, role, schema, system, user, *, purpose, teardown_policy):
        entry = dict(schema=schema, purpose=purpose, user=user, role=role, policy=teardown_policy)
        self.calls.append(entry)
        if self.hook:
            result = await self.hook(entry)
            if result is not None:
                return result
        return await demo.respond(schema, system, user)


async def create_book(sm, *, count=12, upto=None, original=False, volume_size=6, read=False):
    async with sm() as session:
        book = Book(
            title="原书",
            source="teardown",
            status="writing",
            teardown={"stage": "queued", "original_volumes": original, "upto": upto},
        )
        session.add(book)
        await session.flush()
        volumes = []
        starts = list(range(1, count + 1, volume_size)) if original else [1]
        for index, first in enumerate(starts, 1):
            volume = Volume(
                book_id=book.id,
                index=index,
                title=f"原卷{index}" if original else "还没分卷",
                chapter_count=min(volume_size, count - first + 1) if original else count,
                status="done",
            )
            session.add(volume)
            await session.flush()
            volumes.append(volume)
        if not original:
            book.teardown = {**book.teardown, "open_volume_id": str(volumes[0].id)}
        for index in range(1, count + 1):
            volume = volumes[(index - 1) // volume_size] if original else volumes[0]
            chapter = Chapter(
                book_id=book.id,
                volume_id=volume.id,
                index=index,
                title=f"章名{index}",
                content=f"人物第 {index} 次出发。",
                source="imported",
                status="final",
                teardown={"raw_title": f"原第{index}章"},
            )
            if read:
                chapter.teardown = {
                    **chapter.teardown,
                    "read_version": 1,
                    "read": {"feel": "爽", "people": [], "things": [], "moments": [], "waits": [], "tropes": []},
                }
                chapter.summary = f"原摘要{index}"
                chapter.outline = {"goal": f"原章纲{index}", "cool_point": "看点", "hook": "钩子", "emotion": 1}
            session.add(chapter)
        job = Job(book_id=book.id, kind="teardown", thread_id="test-teardown", params={"upto": upto}, status="queued")
        session.add(job)
        await session.commit()
        return book.id, job.id


def test_batching_exact_character_boundary_and_single_oversize():
    rows = [{"text": "字" * 3000} for _ in range(5)] + [{"text": "字" * 12001}, {"text": "尾"}]
    assert [len(batch) for batch in make_batches(rows)] == [4, 1, 1, 1]
    assert [len(batch) for batch in make_batches([SimpleNamespace(content="字" * 4001)] * 3)] == [2, 1]
    assert (
        chapter_text(
            [SimpleNamespace(index=1, title="", content="原文"), SimpleNamespace(index=2, title="初见", content="正文")]
        )
        == "「第 1 章」\n原文\n\n「第 2 章 初见」\n正文"
    )


def test_roster_reconstruct_merge_alias_shared_top_twelve_and_first_seen():
    roster = Roster()
    roster.add(
        [
            {
                "index": i,
                "people": [{"name": f"人{i}", "shown": "初见" * 30, "also_called": ["校花" if i < 3 else f"别称{i}"]}],
            }
            for i in range(1, 16)
        ]
    )
    roster.add(
        [
            {
                "index": 16,
                "people": [
                    {"name": "人1", "shown": "后来的描写"},
                    {"name": "正式名", "was": "人15", "shown": "改名", "also_called": ["新别称"]},
                ],
            }
        ]
    )
    assert len(roster.people) == 15 and roster.find("校花") is None
    assert roster.find("人15")["name"] == "正式名" and roster.find("正式名")["note"] == ("初见" * 30)[:50]
    text = roster.text("本章正式名和别称14出现。")
    assert "人13｜" not in text and "人14｜" in text and "正式名｜" in text
    assert "校花" not in text and text.index("人1｜") < text.index("正式名｜")
    assert Roster().text("") == "（还没有）"


def test_roster_was_merge_keeps_earliest_note_and_counts_chapters_once():
    roster = Roster()
    roster.add(
        [
            {"index": 1, "people": [{"name": "旧名", "shown": "最早"}, {"name": "新名", "shown": "稍后"}]},
            {
                "index": 2,
                "people": [{"name": "新名", "was": "旧名", "shown": "已认出"}, {"name": "新名", "shown": "又写一遍"}],
            },
        ]
    )
    assert len(roster.people) == 1
    assert roster.people[0]["note"] == "最早" and roster.people[0]["chapters"] == {1, 2}
    assert "旧名" in roster.people[0]["aliases"]


def test_group_checks_gaps_overlaps_bounds_and_tail_rules():
    assert check_groups([{"first": 1, "last": 3}], 1, 5, 4) is None
    assert check_groups([], 1, 5, 1) is None
    assert check_groups([{"first": 1, "last": 6}], 1, 5, None)
    assert check_groups([{"first": 2, "last": 5}], 1, 5, None)
    assert check_groups([], 1, 5, 0) and check_groups([], 1, 5, 1, close=True)
    assert check_groups([{"first": 1, "last": 3}], 1, 5, 4, bounds={1, 3, 6}) == "卷的分界拆开了单元"
    assert unit_tail_rule(100, 100, True, 100) == "这是全书最后几章：全部归完，不留 open_from。"
    assert unit_tail_rule(50, 100, True, 50) == "这几章是原书这一卷的最后几章：全部归完，不留 open_from。"
    assert unit_tail_rule(50, 100, False, 50) == "后面还有没读到的章：最后一件事要是还没了结，就留着不归。"


async def test_full_demo_read_units_volumes_final_open_row_reused(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker)
    router = DemoRouter()
    runner = Runner(jid, sessionmaker, redis, router)
    await runner.run()
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        chapters = list(await session.scalars(select(Chapter).order_by(Chapter.index)))
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        units = list(await session.scalars(select(PlotUnit)))
        assert book.teardown["stage"] == "done" and book.teardown["open_volume_id"] is None
        assert len(volumes) == 1 and volumes[0].title != "还没收尾" and volumes[0].summary
        assert units and all(c.unit_id and c.teardown["read_version"] == 1 for c in chapters)
        assert all(c.outline["emotion"] == 0 for c in chapters)
        assert all(
            set(c.teardown["read"]) == {"feel", "people", "things", "moments", "waits", "tropes"} for c in chapters
        )
        assert (await session.scalar(select(BookSave))).title == "拆完了"
        messages = list(await session.scalars(select(MeetingMessage)))
        assert len(messages) == 1 and messages[0].speaker == "lorekeeper" and messages[0].content.startswith("拆完了：")
        assert (await session.get(Job, jid)).status == "succeeded"
    assert all(call["role"] == "teardown" and call["policy"] is runner.policy for call in router.calls)
    assert len([c for c in router.calls if c["schema"] is s.TeardownRead]) == 3


async def test_first_batch_alone_then_at_most_four_and_roster_at_start(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=24)
    first_done = False
    active = peak = 0
    four_inflight = asyncio.Event()

    async def hook(call):
        nonlocal first_done, active, peak
        if call["schema"] is not s.TeardownRead:
            return None
        numbers = list(map(int, re.findall(r"^「第 (\d+) 章", call["user"], re.M)))
        if numbers[0] == 1:
            assert active == 0
        else:
            assert first_done and "- 云澈｜别称：无｜初见" in call["user"]
        active += 1
        peak = max(peak, active)
        if numbers[0] != 1:
            if active == 4:
                four_inflight.set()
            await asyncio.wait_for(four_inflight.wait(), timeout=5)
        value = await demo.respond(s.TeardownRead, "", call["user"])
        active -= 1
        if numbers[0] == 1:
            value.chapters[0].people = [s.TeardownPerson(name="云澈", shown="初见")]
            first_done = True
        return value

    await Runner(jid, sessionmaker, redis, DemoRouter(hook)).run()
    assert peak == 4


async def test_missing_duplicate_outside_single_retry_failure_and_raw_fields_not_truncated(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=4)
    seen = []

    async def hook(call):
        if call["schema"] is not s.TeardownRead:
            return None
        nums = list(map(int, re.findall(r"^「第 (\d+) 章", call["user"], re.M)))
        seen.append(nums)
        result = await demo.respond(s.TeardownRead, "", call["user"])
        if len(nums) > 1:
            first = result.chapters[0]
            first.goal = "长" * 200
            result.chapters = [
                first,
                first.model_copy(update={"goal": "不可覆盖第一条"}),
                first.model_copy(update={"index": 999}),
                result.chapters[1],
            ]
        elif nums == [4]:
            raise RuntimeError("这一章仍然失败")
        return result

    await Runner(jid, sessionmaker, redis, DemoRouter(hook)).run()
    assert seen == [[1, 2, 3, 4], [3], [4]]
    async with sessionmaker() as session:
        chapters = list(await session.scalars(select(Chapter).order_by(Chapter.index)))
        assert chapters[0].outline["goal"] == "长" * 200 and chapters[2].teardown["read_version"] == 1
        assert "read_version" not in chapters[3].teardown and "仍然失败" in chapters[3].teardown["read_failed"]["error"]
        assert chapters[3].unit_id is not None and (await session.get(Book, bid)).teardown["stage"] == "done"
        assert "有 1 章没读成：第 4 章" in (await session.scalar(select(MeetingMessage))).content


async def test_first_three_two_whole_batch_failures_stop_model(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=40)

    async def fail(call):
        if call["schema"] is s.TeardownRead:
            raise RuntimeError("模型格式不支持")

    runner = Runner(jid, sessionmaker, redis, DemoRouter(fail))
    await runner.run()
    assert set(runner.initial_failures) >= {1, 2}
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == "model"
        assert book.teardown["stop_note"].startswith("开头几批模型连着出错（模型格式不支持）")
        assert not list(await session.scalars(select(PlotUnit)))


async def test_original_volumes_no_crossing_and_exact_tail_rules(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=12, original=True)
    router = DemoRouter()
    await Runner(jid, sessionmaker, redis, router).run()
    calls = [c for c in router.calls if c["schema"] is s.TeardownUnits]
    assert len(calls) == 2
    assert "这几章是原书这一卷的最后几章：全部归完，不留 open_from。" in calls[0]["user"]
    assert "这是全书最后几章：全部归完，不留 open_from。" in calls[1]["user"]
    async with sessionmaker() as session:
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        assert [v.title for v in volumes] == ["原卷1", "原卷2"] and all(v.summary for v in volumes)
        chapters = list(await session.scalars(select(Chapter)))
        assert all(
            len({c.volume_id for c in chapters if c.unit_id == uid}) == 1 for uid in {c.unit_id for c in chapters}
        )
        assert (await session.get(Book, bid)).teardown["stage"] == "done"
    assert "到第 12 章还没收住" in [c for c in router.calls if c["schema"] is s.TeardownVolumeText][-1]["user"]


async def test_group_repair_exact_problem_suffix_and_error_after_three(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=6, read=True)

    async def invalid(call):
        if call["schema"] is s.TeardownUnits:
            return s.TeardownUnits(units=[], open_from=1)

    router = DemoRouter(invalid)
    runner = Runner(jid, sessionmaker, redis, router)
    await runner.initialize()
    with pytest.raises(TeardownStopped, match="归了三次都对不上"):
        await runner.group_once(final=True)
    assert len(router.calls) == 3
    assert router.calls[1]["user"].endswith("【上次归得不对】这次必须全部归完，不留 open_from。请照要求重新归。")
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(PlotUnit)))


async def test_author_stop_drains_inflight_batches_without_grouping_and_resume_does_not_reread(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=60)
    first_calls = []

    async def hook(call):
        if call["schema"] is not s.TeardownRead:
            return None
        nums = list(map(int, re.findall(r"^「第 (\d+) 章", call["user"], re.M)))
        first_calls.extend(nums)
        if nums[0] > 4:
            await redis.set(cancel_key(jid), "1")
            await asyncio.sleep(0.01)

    await Runner(jid, sessionmaker, redis, DemoRouter(hook)).run()
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stage"] == "stopped" and book.teardown["stop_reason"] == "author"
        assert (
            not list(await session.scalars(select(PlotUnit)))
            and (await session.scalar(select(BookSave))).title == "停下拆书"
        )
        before = {c.index for c in await session.scalars(select(Chapter)) if c.teardown.get("read_version")}
        assert book.teardown["stop_note"] == f"已手动停下，停在第 {max(before)} 章。"
        assert before == set(first_calls) and 4 < len(before) <= 20
        book.teardown = {**book.teardown, "stage": "queued", "upto": 40}
        new = Job(book_id=bid, kind="teardown", thread_id="resumed", status="queued")
        session.add(new)
        await session.commit()
        new_id = new.id
    resumed = DemoRouter()
    await Runner(new_id, sessionmaker, redis, resumed).run()
    actual = {
        int(n)
        for c in resumed.calls
        if c["schema"] is s.TeardownRead
        for n in re.findall(r"^「第 (\d+) 章", c["user"], re.M)
    }
    assert not (actual & before) and actual == set(range(1, 41)) - before
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert (
            book.teardown["stop_reason"] == "upto" and book.teardown["stop_note"] == "已按开拆时定的范围拆到第 40 章。"
        )


async def test_refresh_throttles_read_but_groups_force_events(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.refresh()
    await runner.refresh()
    runner.last_refresh -= 60
    await runner.refresh()
    await runner.refresh(force=True)
    events = await redis.xrange(f"zhibi:events:{bid}")
    assert len(events) == 3 and all(e[1]["event"] == "teardown_saved" for e in events)


async def test_units_rerun_from_inside_unit_preserves_chapter_outlines(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=12, read=True)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.group_once(final=True)
    _, chapters, units, _ = await runner.snapshot()
    before, old_ids = {c.index: c.outline for c in chapters}, {u.id for u in units}
    await runner.regroup_units(first=2)
    _, chapters, units, _ = await runner.snapshot()
    assert before == {c.index: c.outline for c in chapters}
    assert not old_ids & {u.id for u in units} and all(c.unit_id for c in chapters)


async def test_volumes_rerun_merges_back_and_reuses_final_open_row(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=120, read=True)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    await runner.regroup_units()
    await runner.regroup_volumes()
    _, before_chapters, _, before_volumes = await runner.snapshot()
    before = {c.index: c.outline for c in before_chapters}
    assert len(before_volumes) >= 2
    await runner.regroup_volumes()
    book, chapters, units, volumes = await runner.snapshot()
    assert book.teardown["open_volume_id"] is None
    assert len(volumes) >= 2 and all(v.summary and v.title != "还没收尾" for v in volumes)
    assert before == {c.index: c.outline for c in chapters}
    assert all(u.volume_id in {v.id for v in volumes} for u in units)
    assert [v.index for v in volumes] == list(range(1, len(volumes) + 1))


async def test_cancel_after_group_response_discards_structure_and_rerun_raises(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=6, read=True)

    async def cancel(call):
        if call["schema"] is s.TeardownUnits:
            await redis.set(cancel_key(jid), "1")

    runner = Runner(jid, sessionmaker, redis, DemoRouter(cancel))
    await runner.initialize()
    assert not await runner.group_once(final=True)
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(PlotUnit)))
    with pytest.raises(JobCancelled):
        await runner.regroup_units()
    with pytest.raises(JobCancelled):
        await runner.read_range(1, 2)


async def test_deleted_book_model_result_does_not_recreate_data(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=4)

    async def remove(call):
        if call["schema"] is s.TeardownRead:
            async with sessionmaker() as session:
                book = await session.get(Book, bid)
                if book:
                    await session.delete(book)
                    await session.commit()

    await Runner(jid, sessionmaker, redis, DemoRouter(remove)).run()
    async with sessionmaker() as session:
        assert await session.get(Book, bid) is None
        assert not list(await session.scalars(select(Chapter))) and not list(
            await session.scalars(select(MeetingMessage))
        )


async def test_units_rerun_invalidates_only_affected_ai_volumes_and_can_cross_old_boundary(sessionmaker, redis):
    _, jid = await create_book(sessionmaker, count=120, read=True)
    router = DemoRouter()
    runner = Runner(jid, sessionmaker, redis, router)
    await runner.initialize()
    await runner.regroup_units()
    await runner.regroup_volumes()
    _, original_chapters, _, volumes = await runner.snapshot()
    assert [v.chapter_count for v in volumes] == [100, 20]
    first_volume_id = volumes[0].id
    outlines = {c.index: c.outline for c in original_chapters}
    await runner.regroup_units(first=105)
    book, _, _, partial_volumes = await runner.snapshot()
    assert partial_volumes[0].id == first_volume_id and partial_volumes[0].summary
    assert partial_volumes[1].title == "还没收尾" and str(partial_volumes[1].id) == book.teardown["open_volume_id"]

    async def large_units(call):
        if call["schema"] is s.TeardownUnits:
            section = call["user"].split("【还没归单元的章】", 1)[1]
            indices = list(map(int, re.findall(r"^第 (\d+) 章：", section, re.M)))
            return s.TeardownUnits(
                units=[
                    s.TeardownUnit(first=min(indices), last=max(indices), title="重归事件", text="按当前章记录重新归")
                ]
            )

    router.calls.clear()
    router.hook = large_units
    await runner.regroup_units()
    book, chapters, _, volumes = await runner.snapshot()
    assert len(volumes) == 1 and volumes[0].title == "还没收尾" and not volumes[0].summary
    assert book.teardown["open_volume_id"] == str(volumes[0].id)
    by_index = {c.index: c for c in chapters}
    assert by_index[100].unit_id == by_index[101].unit_id
    assert outlines == {c.index: c.outline for c in chapters}
    assert all(call["schema"] is s.TeardownUnits for call in router.calls)


async def test_job_terminal_waits_until_boundary_checkpoint_exists(sessionmaker, redis, monkeypatch):
    _, jid = await create_book(sessionmaker, count=4)
    checkpoint_entered, release = asyncio.Event(), asyncio.Event()
    checkpoint = book_saves.checkpoint

    async def slow_checkpoint(*args, **kwargs):
        checkpoint_entered.set()
        await release.wait()
        return await checkpoint(*args, **kwargs)

    monkeypatch.setattr(book_saves, "checkpoint", slow_checkpoint)
    task = asyncio.create_task(Runner(jid, sessionmaker, redis, DemoRouter()).run())
    try:
        await asyncio.wait_for(checkpoint_entered.wait(), timeout=10)
        async with sessionmaker() as session:
            assert (await session.get(Job, jid)).status == "running"
            assert not list(await session.scalars(select(BookSave)))
    finally:
        release.set()
        await task
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "succeeded"
        assert (await session.scalar(select(BookSave))).title == "拆完了"
