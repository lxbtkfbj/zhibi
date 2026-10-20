"""第三批恢复边界审查：已写入输入不能让未完成的派生关系丢失。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents import schemas as s
from app.graphs.deps import JobCancelled
from app.models import Relationship, WorldEntry
from app.prompts import default_content
from app.services.teardown_runner import Runner
from app.services.teardown_settings import SettingsWriter, collect_settings, people_of
from app.services.teardown_world import WorldJob
from tests.test_teardown_settings import StubRunner, card, person, read, setup_book


@pytest.fixture(autouse=True)
def default_prompts(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)


@pytest.mark.parametrize("interrupted_at", ["link_parents", "link_relationships"])
async def test_resume_repairs_committed_cards_and_places_links_without_model_reread(
    sessionmaker, monkeypatch, interrupted_at
):
    things = [
        {"kind": "地方", "name": "青城", "note": "城市", "belongs": "", "secret": ""},
        {"kind": "地方", "name": "城外", "note": "郊外", "belongs": "青城", "secret": ""},
    ]
    reads = [read(i, [person("甲"), person("乙")], things=things if i == 1 else []) for i in range(1, 6)]
    bid = await setup_book(sessionmaker, reads)
    responses = {
        s.TeardownCard: lambda user: card(
            "甲" if "【这个人】甲" in user else "乙",
            ties=[s.TeardownTie(who="乙" if "【这个人】甲" in user else "甲", relation="相互帮助")],
        ),
        s.TeardownPlaces: s.TeardownPlaces(
            items=[
                s.TeardownPlace(name="青城", note="城市", first_chapter=1),
                s.TeardownPlace(name="城外", parent="青城", note="郊外", first_chapter=1),
            ]
        ),
    }
    original = getattr(SettingsWriter, interrupted_at)

    async def interrupted(self):
        raise JobCancelled()

    monkeypatch.setattr(SettingsWriter, interrupted_at, interrupted)
    with pytest.raises(JobCancelled):
        await collect_settings(StubRunner(sessionmaker, bid, responses))
    monkeypatch.setattr(SettingsWriter, interrupted_at, original)
    resumed = StubRunner(sessionmaker, bid, responses)
    await collect_settings(resumed)
    assert not any(call["schema"] in {s.TeardownCard, s.TeardownPlaces} for call in resumed.calls)
    async with sessionmaker() as session:
        places = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == bid)))
        city = next(row for row in places if row.name == "青城")
        outside = next(row for row in places if row.name == "城外")
        assert outside.parent_id == city.id
        assert await session.scalar(select(Relationship.id).where(Relationship.book_id == bid)) is not None


async def test_levels_keep_old_records_changes_after_accepted_protagonist_rename(sessionmaker):
    reads = [
        read(
            i,
            [person("少年", change="达到初阶" if i == 2 else "")],
            things=[{"kind": "等级", "name": "初阶", "note": "入门", "belongs": "", "secret": ""}] if i == 1 else [],
        )
        for i in range(1, 6)
    ]
    bid = await setup_book(sessionmaker, reads)
    responses = {s.TeardownCard: card("甲", aliases=["少年"])}
    await collect_settings(StubRunner(sessionmaker, bid, responses))
    resumed = StubRunner(sessionmaker, bid, responses)
    await collect_settings(resumed, force=True)
    levels = next(call for call in resumed.calls if call["schema"] is s.TeardownLadders)
    assert "主角各章的变化：\n- 第 2 章：达到初阶" in levels["user"]


async def test_incremental_second_place_batch_preserves_first_batch_world_overview(sessionmaker):
    bid = await setup_book(sessionmaker, [read(1)])
    runner = StubRunner(sessionmaker, bid)
    first = WorldJob("world:地方:1", "地方", "第一批", s.TeardownPlaces)
    second = WorldJob("world:地方:2", "地方", "第二批", s.TeardownPlaces)
    writer = SettingsWriter(runner, 1)
    await writer.world(first, s.TeardownPlaces(world="甲世界概况"))
    await writer.world(second, s.TeardownPlaces(world="乙世界概况"))
    resumed = SettingsWriter(runner, 1)
    await resumed.world(second, s.TeardownPlaces(world="乙新世界概况"))
    async with sessionmaker() as session:
        overview = await session.scalar(
            select(WorldEntry).where(WorldEntry.book_id == bid, WorldEntry.name == "世界概况")
        )
        assert overview.content == "甲世界概况\n乙新世界概况"


async def test_resumed_read_batch_sends_accepted_card_name_with_old_name_alias(monkeypatch):
    runner = Runner(None, None, None, None)
    book = SimpleNamespace(teardown={"names": {"红发少女": "茉莉"}})
    previous = [
        SimpleNamespace(index=i, teardown={"read_version": 1, "read": read(i, [person("红发少女")])})
        for i in range(1, 6)
    ]
    chapter = SimpleNamespace(index=6, id="new", content="茉莉再次出现。")
    monkeypatch.setattr(runner, "snapshot", AsyncMock(return_value=(book, previous, [], [])))
    monkeypatch.setattr(runner, "progress", AsyncMock())
    monkeypatch.setattr(runner, "refresh", AsyncMock())
    monkeypatch.setattr(runner, "store_chapter", AsyncMock())
    read_call = AsyncMock(return_value=({6: {"index": 6}}, ""))
    monkeypatch.setattr(runner, "read_call", read_call)
    await runner.read_batch(4, [chapter])
    assert read_call.call_args.args[1] == "- 茉莉｜别称：红发少女｜写出了性格"


def test_roster_merges_future_canonical_name_with_older_alias_records():
    reads = [read(i, [person("红发少女")]) for i in range(1, 6)]
    reads.append(read(6, [person("茉莉")]))
    roster, selected, protagonist = people_of(reads, {"红发少女": "茉莉"})
    assert len(roster.people) == 1
    assert protagonist == "茉莉" and selected[0]["key_name"] == "红发少女"
    assert selected[0]["chapters"] == {1, 2, 3, 4, 5, 6}
