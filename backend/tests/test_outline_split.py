"""新书页大纲上的「编辑部帮拆」：单元出章纲、卷拆成单元。先出一版不存，收下才存，收下了能撤销。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Chapter, PlotUnit, Volume


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def outline_book(client):
    """一篇一卷两个单元：第一个单元有两章章纲，第二个单元还空着、章数没定。"""
    book = (await client.post("/api/books", json={"start_setup": False, "title": "万古邪帝", "genre": "玄幻"})).json()[
        "book"
    ]["id"]
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    first = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城"})).json()
    second = (
        await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "考核", "after_unit_id": first["id"]})
    ).json()
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "初入青阳"})
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "药铺"})
    return book, volume, first, second


async def titles(sessionmaker, unit_id) -> list[tuple[int, str]]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(Chapter).where(Chapter.unit_id == uuid.UUID(unit_id)).order_by(Chapter.index)
        )
        return [(row.index, row.title) for row in rows]


async def test_empty_unit_gets_a_draft_that_is_saved_only_when_accepted(client, sessionmaker):
    book, _, first, second = await outline_book(client)
    res = await client.post(f"/api/books/{book}/outline/split", json={"target_type": "unit", "target_id": second["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    # 章数没定：编辑部按剧情定（演示模型出 5 章），接在第一个单元的两章后面
    assert len(body["drafts"]) == 5 and body["first"] == 3
    assert body["keeps"] == [] and body["replaces"] == []
    assert set(body["drafts"][0]["sections"]) == {"发生什么", "看点", "结尾钩子"}
    assert body["drafts"][0]["raw"]["goal"] in body["drafts"][0]["sections"]["发生什么"]
    # 出一版不存
    assert await titles(sessionmaker, second["id"]) == []

    # 作者删了一条、改了一条再收下
    drafts = body["drafts"][:4]
    drafts[0] = {
        **drafts[0],
        "name": "考核前夜",
        "sections": {**drafts[0]["sections"], "发生什么": "老刘死了\n井边\n袖子里的丹壳"},
    }
    res = await client.post(
        f"/api/books/{book}/outline/split/accept",
        json={"target_type": "unit", "target_id": second["id"], "drafts": drafts},
    )
    assert res.status_code == 200, res.text
    undo = res.json()["undo"]
    assert [title for _, title in await titles(sessionmaker, second["id"])][0] == "考核前夜"
    assert [index for index, _ in await titles(sessionmaker, second["id"])] == [3, 4, 5, 6]
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == uuid.UUID(book), Chapter.index == 3))
        assert chapter.outline["goal"] == "老刘死了" and chapter.outline["scenes"] == ["井边", "袖子里的丹壳"]
        unit = await session.get(PlotUnit, uuid.UUID(second["id"]))
        assert unit.chapter_count == 4 and unit.status == "outlined"

    # 撤销：换回原来什么都没有
    res = await client.post(
        f"/api/books/{book}/outline/split/undo", json={"target_type": "unit", "target_id": second["id"], "undo": undo}
    )
    assert res.status_code == 200, res.text
    assert await titles(sessionmaker, second["id"]) == []
    assert [title for _, title in await titles(sessionmaker, first["id"])] == ["初入青阳", "药铺"]


async def test_replanning_replaces_only_unwritten_chapters_and_shifts_the_ones_after(client, sessionmaker):
    book, _, first, second = await outline_book(client)
    await client.post(f"/api/units/{second['id']}/chapters", json={"title": "考场"})
    # 第一章已经写了
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == uuid.UUID(book), Chapter.index == 1))
        chapter.content, chapter.status = "正文", "final"
        await session.commit()
    res = await client.post(
        f"/api/books/{book}/outline/split",
        json={"target_type": "unit", "target_id": first["id"], "request": "药铺那章拆成两章"},
    )
    body = res.json()
    assert body["first"] == 2
    assert body["keeps"] == ["第1章　初入青阳"] and body["replaces"] == ["第2章　药铺"]
    res = await client.post(
        f"/api/books/{book}/outline/split/accept",
        json={"target_type": "unit", "target_id": first["id"], "drafts": body["drafts"][:3]},
    )
    assert res.status_code == 200, res.text
    undo = res.json()["undo"]
    got = await titles(sessionmaker, first["id"])
    assert got[0] == (1, "初入青阳") and [index for index, _ in got] == [1, 2, 3, 4]
    # 后面单元的章跟着往后挪
    assert await titles(sessionmaker, second["id"]) == [(5, "考场")]

    # 再出一版：带上当前这一版
    res = await client.post(
        f"/api/books/{book}/outline/split",
        json={"target_type": "unit", "target_id": first["id"], "current": body["drafts"][:3]},
    )
    assert res.status_code == 200, res.text

    res = await client.post(
        f"/api/books/{book}/outline/split/undo", json={"target_type": "unit", "target_id": first["id"], "undo": undo}
    )
    assert res.status_code == 200, res.text
    assert await titles(sessionmaker, first["id"]) == [(1, "初入青阳"), (2, "药铺")]
    assert await titles(sessionmaker, second["id"]) == [(3, "考场")]


async def test_volume_without_units_is_split_into_units(client, sessionmaker):
    book = (await client.post("/api/books", json={"start_setup": False, "title": "空卷", "genre": "玄幻"})).json()[
        "book"
    ]["id"]
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    res = await client.post(
        f"/api/books/{book}/outline/split", json={"target_type": "volume", "target_id": volume["id"]}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["drafts"]) >= 2 and body["plan"] and "units" not in body["plan"]
    assert all(d["name"] and d["chapters"] >= 1 for d in body["drafts"])
    async with sessionmaker() as session:
        assert not await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == uuid.UUID(volume["id"])))

    drafts = [{**body["drafts"][0], "name": "入城", "chapters": 4}, *body["drafts"][1:]]
    res = await client.post(
        f"/api/books/{book}/outline/split/accept",
        json={"target_type": "volume", "target_id": volume["id"], "drafts": drafts, "plan": body["plan"]},
    )
    assert res.status_code == 200, res.text
    undo = res.json()["undo"]
    async with sessionmaker() as session:
        units = list(
            await session.scalars(
                select(PlotUnit).where(PlotUnit.volume_id == uuid.UUID(volume["id"])).order_by(PlotUnit.index)
            )
        )
        assert [u.title for u in units][0] == "入城" and units[0].chapter_count == 4
        row = await session.get(Volume, uuid.UUID(volume["id"]))
        assert row.status == "approved" and row.chapter_count == sum(u.chapter_count for u in units)

    # 已经有单元的卷不整个重拆
    res = await client.post(
        f"/api/books/{book}/outline/split", json={"target_type": "volume", "target_id": volume["id"]}
    )
    assert res.status_code == 409

    res = await client.post(
        f"/api/books/{book}/outline/split/undo", json={"target_type": "volume", "target_id": volume["id"], "undo": undo}
    )
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        assert not await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == uuid.UUID(volume["id"])))


async def test_locked_unit_and_other_books_are_refused(client, sessionmaker):
    book, _, _, second = await outline_book(client)
    async with sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(second["id"]))
        unit.locked = True
        await session.commit()
    res = await client.post(f"/api/books/{book}/outline/split", json={"target_type": "unit", "target_id": second["id"]})
    assert res.status_code == 409 and "锁住" in res.json()["detail"]
    other = (await client.post("/api/books", json={"start_setup": False, "title": "别的书"})).json()["book"]["id"]
    res = await client.post(
        f"/api/books/{other}/outline/split", json={"target_type": "unit", "target_id": second["id"]}
    )
    assert res.status_code == 404
