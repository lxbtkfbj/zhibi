"""精髓增量、并发、失败补跑和真实数据库落盘。"""

import asyncio
import re
from collections import Counter
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.agents import schemas as s
from app.config import get_settings
from app.graphs.deps import JobCancelled
from app.models import Book, Chapter, PlotUnit, Volume
from app.prompts import default_content, render
from app.services.teardown_essence import (
    EssenceIncomplete,
    collect_essence,
    collect_tags,
    collect_unitplot,
    estimate_calls,
    points_problem,
)
from app.services.teardown_runner import Runner
from tests.test_teardown_runner import create_book


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def prompts(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)


def point(title="招式：先压后扬", chapters=None):
    return {
        "title": title,
        "steps": ["先留难题", "再解难题"],
        "evidence": "第 1–3 章先压后扬",
        "note": "",
        "chapters": chapters or [1, 2, 3],
    }


class Router:
    def __init__(self, hook=None):
        self.calls, self.hook, self.active, self.peak = [], hook, 0, 0

    async def structured(self, role, schema, system, user, *, purpose, teardown_policy):
        call = {
            "role": role,
            "schema": schema,
            "system": system,
            "user": user,
            "purpose": purpose,
            "policy": teardown_policy,
        }
        self.calls.append(call)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.05)
            if self.hook:
                value = await self.hook(call)
                if value is not None:
                    return value
            if schema is s.TeardownTags:
                indices = [int(n) for n in re.findall(r"第 (\d+) 章（", user)]
                return schema(
                    chapters=[
                        {"index": n, "tags": [f"类别{(n - 1) % 3}", " ", f"类别{(n - 1) % 3}"], "crowd": "旁人惊讶"}
                        for n in indices
                    ]
                )
            if schema is s.TeardownUnitPlots:
                return schema(
                    units=[
                        {
                            "n": int(n),
                            "trigger_type": "前事的后果",
                            "trigger": "前事找来",
                            "shape": ["起", "承", "转", "合"],
                            "payoff": "反转：解围",
                            "stakes": "更大",
                        }
                        for n in re.findall(r"【单元 (\d+)】", user)
                    ]
                )
            payload = {"points": [point(purpose)], "missing": []}
            if schema in (s.EssenceCast, s.EssenceCastChecked):
                payload["figures"] = [
                    {
                        "name": "乙",
                        "archetype": "对手",
                        "build": "用一次争执立人",
                        "role": "推动剧情",
                        "arc": "",
                        "chapters": [1, 2],
                    }
                ]
            if schema in (s.EssenceSectionChecked, s.EssenceCastChecked):
                payload["fixes"] = ["核对后修改了证据"]
            if schema is s.EssenceOverview:
                payload.update(genre="冒险小说", engine="让问题接续起来")
            return schema(**payload)
        finally:
            self.active -= 1


async def seeded_runner(sm, redis, *, count=24, hook=None):
    bid, jid = await create_book(sm, count=count, upto=count, read=True, original=True, volume_size=12)
    async with sm() as session:
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == bid).order_by(Volume.index)))
        rows = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid).order_by(Chapter.index)))
        for volume in volumes:
            chapters = [row for row in rows if row.volume_id == volume.id]
            for n, start in enumerate(range(0, len(chapters), 4), 1):
                unit = PlotUnit(
                    book_id=bid, volume_id=volume.id, index=n, title=f"单元{volume.index}-{n}", summary="单元的一段话"
                )
                session.add(unit)
                await session.flush()
                for row in chapters[start : start + 4]:
                    row.unit_id = unit.id
        for chapter in rows:
            read = {
                **chapter.teardown["read"],
                "feel": "大爽" if chapter.index % 4 == 0 else "爽",
                "people": [
                    {"name": "甲", "shown": "甲聪明坚韧", "change": "与乙的关系变好", "also_called": [], "was": ""},
                    {"name": "乙", "shown": "乙与甲争执", "change": "", "also_called": [], "was": ""},
                ],
            }
            chapter.teardown = {**chapter.teardown, "read": read}
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "merits": {"old": "旧内容不读也不删"}}
        await session.commit()
    router = Router(hook)
    runner = Runner(jid, sm, redis, router)
    await runner.initialize()
    runner.progress, runner.refresh = AsyncMock(), AsyncMock()
    return runner, router


async def test_full_pipeline_checked_sections_top_three_scenes_rails_incremental_and_policy(sessionmaker, redis):
    runner, router = await seeded_runner(sessionmaker, redis)
    result = await collect_essence(runner)
    assert result == {"sections": 12, "points": 15}
    counts = Counter(call["schema"].__name__ for call in router.calls)
    assert counts == {
        "TeardownTags": 1,
        "TeardownUnitPlots": 1,
        "EssenceSection": 13,
        "EssenceCast": 1,
        "EssenceSectionChecked": 10,
        "EssenceCastChecked": 1,
        "EssenceOverview": 1,
    }
    assert router.peak == 8 and router.active == 0
    system = render("persona_essence", title="原书", upto="24", total="24", rules=render("rules"))
    assert all(
        call["system"] == system and call["role"] == "teardown" and call["policy"] is runner.policy
        for call in router.calls
    )
    async with sessionmaker() as session:
        book = await session.get(Book, runner.book_id)
        essence = book.teardown["essence"]
        assert essence["failed"] is False and essence["upto"] == 24 and essence["at"]
        assert book.teardown["merits"] == {"old": "旧内容不读也不删"}
        assert essence["sections"]["source"]["points"][0]["title"] == "拆书精髓：核对·情节怎么想"
        assert essence["sections"]["source"]["fixes"] == ["核对后修改了证据"]
        assert essence["sections"]["cast"]["figures"][0]["name"] == "乙"
        assert [p["title"] for p in essence["sections"]["scene"]["points"]] == [
            f"拆书精髓：爽点戏怎么写·类别{i}" for i in range(3)
        ]
        assert list(essence["scene_parts"]) == [f"类别{i}" for i in range(3)]
        assert len(essence["rails"]) == 15 and len(essence["rails"]["units"]) == 6
        assert essence["rails"]["crowd"] == 24 and essence["rails"]["hero"] == "甲"
        assert await estimate_calls(session, book) == 0
        assert await estimate_calls(session, book, "tags") == 0
        assert await estimate_calls(session, book, "unitplot") == 0
        assert await estimate_calls(session, book, "essence:source", force=True) == 2
    router.calls.clear()
    assert await collect_essence(runner) == result
    assert not router.calls
    await collect_essence(runner, only="source", force=True)
    assert [call["purpose"] for call in router.calls] == [
        "拆书精髓：情节怎么想",
        "拆书精髓：核对·情节怎么想",
    ]
    now = [call.kwargs["essence"]["now"] for call in runner.progress.await_args_list]
    assert "爽点分类" in now and "逐单元拆剧情" in now and "核对·情节怎么想" in now and now[-1] == "情节怎么想"


async def test_tags_only_changed_and_non_good_tags_removed_and_missing_batch_retried(sessionmaker, redis):
    first = True

    async def hook(call):
        nonlocal first
        if call["schema"] is s.TeardownTags and first:
            first = False
            return s.TeardownTags(chapters=[])

    runner, router = await seeded_runner(sessionmaker, redis, hook=hook)
    assert (await collect_tags(runner))["chapters"] == 24
    assert len(router.calls) == 2 and "【上次写得不对】漏了第" in router.calls[1]["user"]
    router.calls.clear()
    await collect_tags(runner)
    assert not router.calls
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == runner.book_id).order_by(Chapter.index))
        )
        rows[0].summary = "摘要改了"
        rows[1].teardown = {**rows[1].teardown, "read": {**rows[1].teardown["read"], "feel": "平"}}
        await session.commit()
    assert (await collect_tags(runner))["chapters"] == 23
    assert (
        len(router.calls) == 1 and "第 1 章（" in router.calls[0]["user"] and "第 2 章（" not in router.calls[0]["user"]
    )
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == runner.book_id).order_by(Chapter.index))
        )
        assert rows[0].teardown["tags"]["tags"] == ["类别0"]
        assert "tags" not in rows[1].teardown


async def test_tags_three_missing_failures_do_not_write_batch(sessionmaker, redis):
    async def hook(call):
        return s.TeardownTags(chapters=[])

    runner, router = await seeded_runner(sessionmaker, redis, hook=hook)
    with pytest.raises(EssenceIncomplete):
        await collect_tags(runner)
    assert len(router.calls) == 3
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Chapter).where(Chapter.book_id == runner.book_id)))
        assert all("tags" not in row.teardown for row in rows)


@pytest.mark.parametrize("step", ["tags", "unitplot"])
async def test_force_failure_invalidates_old_of_so_nonforce_really_retries(sessionmaker, redis, step):
    runner, router = await seeded_runner(sessionmaker, redis)
    collect = collect_tags if step == "tags" else collect_unitplot
    await collect(runner)

    async def hook(call):
        if call["schema"] is s.TeardownTags:
            return s.TeardownTags(chapters=[])
        return s.TeardownUnitPlots(units=[])

    router.hook = hook
    router.calls.clear()
    with pytest.raises(EssenceIncomplete):
        await collect(runner, force=True)
    assert len(router.calls) == 3
    router.hook = None
    router.calls.clear()
    await collect(runner)
    assert len(router.calls) == 1
    async with sessionmaker() as session:
        essence = (await session.get(Book, runner.book_id)).teardown["essence"]
        assert step not in essence["failures"]


async def test_unitplot_incremental_changed_material_and_new_ids(sessionmaker, redis):
    runner, router = await seeded_runner(sessionmaker, redis)
    assert await collect_unitplot(runner) == {"units": 6}
    router.calls.clear()
    await collect_unitplot(runner)
    assert not router.calls
    async with sessionmaker() as session:
        row = await session.scalar(
            select(PlotUnit).where(PlotUnit.book_id == runner.book_id).order_by(PlotUnit.index).limit(1)
        )
        row.summary = "单元话变了"
        await session.commit()
    await collect_unitplot(runner)
    assert len(router.calls) == 1 and router.calls[0]["user"].count("【单元 ") == 1
    async with sessionmaker() as session:
        row = await session.scalar(
            select(PlotUnit).where(PlotUnit.book_id == runner.book_id).order_by(PlotUnit.index).limit(1)
        )
        old_id = row.id
        replacement = PlotUnit(
            book_id=row.book_id, volume_id=row.volume_id, index=99, title=row.title, summary=row.summary
        )
        session.add(replacement)
        await session.flush()
        for chapter in await session.scalars(select(Chapter).where(Chapter.unit_id == old_id)):
            chapter.unit_id = replacement.id
        await session.execute(delete(PlotUnit).where(PlotUnit.id == old_id))
        await session.commit()
    router.calls.clear()
    await collect_unitplot(runner)
    assert len(router.calls) == 1 and router.calls[0]["user"].count("【单元 ") == 1


async def test_bad_section_and_bad_figure_retry_leave_old_and_other_sections_continue_then_supplement(
    sessionmaker, redis
):
    runner, router = await seeded_runner(sessionmaker, redis)
    await collect_essence(runner)
    async with sessionmaker() as session:
        old = (await session.get(Book, runner.book_id)).teardown["essence"]["sections"]["source"]

    async def hook(call):
        if call["purpose"] == "拆书精髓：情节怎么想":
            return s.EssenceSection(points=[point("坏知识点", [999])])
        if call["schema"] is s.EssenceCast:
            return s.EssenceCast(
                points=[point()],
                figures=[{"name": "乙", "archetype": "对手", "build": "写争执", "role": "推动剧情", "chapters": [999]}],
            )

    router.hook = hook
    router.calls.clear()
    with pytest.raises(EssenceIncomplete) as exc:
        await collect_essence(runner, force=True)
    assert exc.value.result["sections"] == 12
    counts = Counter(call["purpose"] for call in router.calls)
    assert counts["拆书精髓：情节怎么想"] == counts["拆书精髓：配角与对手"] == 3
    assert counts["拆书精髓：核心要点"] == 1
    async with sessionmaker() as session:
        essence = (await session.get(Book, runner.book_id)).teardown["essence"]
        assert essence["failed"] is True and essence["sections"]["source"] == old
        assert set(essence["failures"]) == {"source", "cast"}
        assert "source" not in essence["inputs"] and "cast" not in essence["inputs"]
    router.hook = None
    router.calls.clear()
    await collect_essence(runner, only="source")
    async with sessionmaker() as session:
        essence = (await session.get(Book, runner.book_id)).teardown["essence"]
        assert essence["failed"] is True and set(essence["failures"]) == {"cast"}
    router.calls.clear()
    await collect_essence(runner)
    assert [call["purpose"] for call in router.calls] == ["拆书精髓：配角与对手", "拆书精髓：核对·配角与对手"]
    async with sessionmaker() as session:
        assert (await session.get(Book, runner.book_id)).teardown["essence"]["failed"] is False


async def test_scene_partial_failure_reuses_successes_and_keeps_old_combined_section(sessionmaker, redis):
    runner, router = await seeded_runner(sessionmaker, redis)
    await collect_essence(runner)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Chapter).where(Chapter.book_id == runner.book_id)))
        for row in rows:
            row.content += "原文变化"
        await session.commit()

    async def hook(call):
        if call["purpose"] == "拆书精髓：爽点戏怎么写·类别1":
            return s.EssenceSection(points=[])

    router.hook = hook
    router.calls.clear()
    with pytest.raises(EssenceIncomplete):
        await collect_essence(runner, only="scene")
    assert Counter(call["purpose"] for call in router.calls) == {
        "拆书精髓：爽点戏怎么写·类别0": 1,
        "拆书精髓：爽点戏怎么写·类别1": 3,
        "拆书精髓：爽点戏怎么写·类别2": 1,
    }
    router.hook = None
    router.calls.clear()
    await collect_essence(runner, only="scene")
    assert [call["purpose"] for call in router.calls] == ["拆书精髓：爽点戏怎么写·类别1"]


async def test_unit_and_tag_batches_limit_parallel_eight(sessionmaker, redis):
    runner, router = await seeded_runner(sessionmaker, redis, count=660)
    await collect_tags(runner)
    assert len(router.calls) == 9 and router.peak == 8
    router.calls.clear()
    router.peak = 0
    await collect_unitplot(runner)
    assert len(router.calls) == 21 and router.peak == 8


async def test_cancellation_escapes_and_joins_siblings(sessionmaker, redis):
    async def hook(call):
        if call["schema"] is s.EssenceSection:
            raise JobCancelled()

    runner, router = await seeded_runner(sessionmaker, redis, hook=hook)
    with pytest.raises(JobCancelled):
        await collect_essence(runner)
    assert router.active == 0


async def test_only_one_section_does_not_call_overview_or_claim_other_sections_complete(sessionmaker, redis):
    runner, router = await seeded_runner(sessionmaker, redis)
    await collect_essence(runner, only="source")
    assert [call["purpose"] for call in router.calls] == ["拆书精髓：情节怎么想", "拆书精髓：核对·情节怎么想"]
    async with sessionmaker() as session:
        essence = (await session.get(Book, runner.book_id)).teardown["essence"]
        assert essence["upto"] == 0 and set(essence["sections"]) == {"source"}
        assert "overview" not in essence


async def test_sparse_old_reads_and_empty_people_can_collect_without_crashing(sessionmaker, redis):
    runner, _ = await seeded_runner(sessionmaker, redis)
    async with sessionmaker() as session:
        for chapter in await session.scalars(select(Chapter).where(Chapter.book_id == runner.book_id)):
            chapter.teardown = {"read_version": 1, "read": {"people": []}}
        await session.commit()
    result = await collect_essence(runner)
    assert result["sections"] == 11
    async with sessionmaker() as session:
        essence = (await session.get(Book, runner.book_id)).teardown["essence"]
        assert not essence["failed"] and not essence["rails"]["people"]


def test_points_reject_unread_figure_and_empty_points():
    book = type("Data", (), {"by_index": {1: {}}, "last": 1})()
    assert points_problem(book, s.EssenceSection(points=[])) == "至少写一个知识点"
    value = s.EssenceCast(
        points=[point(chapters=[1])],
        figures=[{"name": "乙", "archetype": "对手", "build": "争执", "role": "推动", "chapters": [2]}],
    )
    assert "「乙」里的章号 [2]" in points_problem(book, value)
