"""新书页大纲：任意位置插入、上移下移、章数可以还没定（有几章算几章，写到那里编辑部再定）。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Chapter, PlotUnit, StoryNode, Volume


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


async def blank_book(client) -> str:
    res = await client.post("/api/books", json={"start_setup": False, "title": "万古邪帝", "genre": "玄幻"})
    assert res.status_code == 201, res.text
    return res.json()["book"]["id"]


async def titles(client, book) -> list[str]:
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    return [arc["title"] for arc in tree["arcs"]]


async def test_arcs_insert_anywhere_and_move(client):
    book = await blank_book(client)
    first = (await client.post(f"/api/books/{book}/arcs", json={"title": "开局"})).json()
    last = (await client.post(f"/api/books/{book}/arcs", json={"title": "大结局"})).json()
    # 先写了第一篇和最后一篇，中间想到哪插到哪
    await client.post(f"/api/books/{book}/arcs", json={"title": "中段", "before_node_id": last["id"]})
    middle2 = (await client.post(f"/api/books/{book}/arcs", json={"title": "中段二", "after_node_id": first["id"]})).json()
    assert await titles(client, book) == ["开局", "中段二", "中段", "大结局"]
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "arc", "id": middle2["id"], "direction": "down"})
    assert res.status_code == 200, res.text
    assert await titles(client, book) == ["开局", "中段", "中段二", "大结局"]
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "arc", "id": first["id"], "direction": "up"})
    assert res.status_code == 422


async def test_volumes_follow_their_arc_when_arcs_move(client):
    book = await blank_book(client)
    a = (await client.post(f"/api/books/{book}/arcs", json={"title": "甲"})).json()
    b = (await client.post(f"/api/books/{book}/arcs", json={"title": "乙"})).json()
    va = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": a["id"], "title": "甲卷"})).json()
    vb = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": b["id"], "title": "乙卷", "after_volume_id": va["id"]})).json()
    # 新建的卷章数先不定
    assert va["chapter_count"] == 0
    await client.post(f"/api/books/{book}/outline/move", json={"kind": "arc", "id": b["id"], "direction": "up"})
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert [(arc["title"], [v["title"] for v in arc["volumes"]]) for arc in tree["arcs"]] == [("乙", ["乙卷"]), ("甲", ["甲卷"])]
    assert [v["index"] for arc in tree["arcs"] for v in arc["volumes"]] == [1, 2]
    # 同一篇里的卷能挪
    vb2 = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": b["id"], "title": "乙卷二", "after_volume_id": vb["id"]})).json()
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "volume", "id": vb2["id"], "direction": "up"})
    assert res.status_code == 200, res.text
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert [v["title"] for v in tree["arcs"][0]["volumes"]] == ["乙卷二", "乙卷"]


async def test_inserting_after_a_later_arc_plans_the_ones_before(client, sessionmaker):
    book = await blank_book(client)
    book_id = uuid.UUID(book)
    async with sessionmaker() as session:
        session.add_all([
            StoryNode(book_id=book_id, position=1, kind="milestone", title="已定", segment={"title": "已定", "text": "x"}),
            StoryNode(book_id=book_id, position=2, kind="milestone", title="远景", event="以后的事"),
            StoryNode(book_id=book_id, position=3, kind="ending", title="结局", event="大结局"),
        ])
        await session.commit()
    nodes = (await client.get(f"/api/books/{book}/nodes")).json()
    far = next(n for n in nodes if n["title"] == "远景")
    res = await client.post(f"/api/books/{book}/arcs", json={"title": "新的", "after_node_id": far["id"]})
    assert res.status_code == 201, res.text
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    # 「远景」夹在两篇定下来的篇中间会被写作跳过：跟着定下来
    assert [(arc["title"], arc["planned"]) for arc in tree["arcs"]] == [("已定", True), ("远景", True), ("新的", True), ("结局", False)]
    ending = next(n for n in nodes if n["kind"] == "ending")
    res = await client.post(f"/api/books/{book}/arcs", json={"title": "结局后", "after_node_id": ending["id"]})
    assert res.status_code == 422


async def test_units_and_chapters_insert_move_and_undecided_counts(client, sessionmaker):
    book = await blank_book(client)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "甲"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    u1 = (await client.post(f"/api/volumes/{volume['id']}/units", json={})).json()
    assert u1["chapter_count"] == 0
    u0 = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "插在前面"})).json()
    assert u0["index"] == 1
    for title in ("一", "二"):
        await client.post(f"/api/units/{u1['id']}/chapters", json={"title": title})
    await client.post(f"/api/units/{u0['id']}/chapters", json={"title": "序"})
    # 章数没定：有几章算几章，不预留空位
    chapters = (await client.get(f"/api/books/{book}/chapters")).json()
    assert [(c["index"], c["title"]) for c in chapters] == [(1, "序"), (2, "一"), (3, "二")]
    async with sessionmaker() as session:
        counts = {u.title: u.chapter_count for u in await session.scalars(select(PlotUnit))}
    assert counts == {"插在前面": 0, "": 0}

    res = await client.post(f"/api/units/{u1['id']}/chapters", json={"title": "插一章", "before_index": 3})
    assert res.json()["index"] == 3
    chapters = (await client.get(f"/api/books/{book}/chapters")).json()
    assert [c["title"] for c in chapters] == ["序", "一", "插一章", "二"]
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "chapter", "id": "4", "direction": "up"})
    assert res.json() == {"id": "3"}
    chapters = (await client.get(f"/api/books/{book}/chapters")).json()
    assert [c["title"] for c in chapters] == ["序", "一", "二", "插一章"]
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "unit", "id": u1["id"], "direction": "up"})
    assert res.status_code == 200, res.text
    chapters = (await client.get(f"/api/books/{book}/chapters")).json()
    assert [c["title"] for c in chapters] == ["一", "二", "插一章", "序"]

    # 开写了的章前面不能插，也不能挪
    await client.patch(f"/api/books/{book}/chapters/1", json={"content": "正文"})
    res = await client.post(f"/api/units/{u1['id']}/chapters", json={"title": "插到开写的前面", "before_index": 1})
    assert res.status_code == 409
    res = await client.post(f"/api/books/{book}/outline/move", json={"kind": "chapter", "id": "2", "direction": "up"})
    assert res.status_code == 409


async def test_undecided_unit_lets_the_editor_decide_how_many_chapters(client, sessionmaker):
    book = await blank_book(client)
    book_id = uuid.UUID(book)
    async with sessionmaker() as session:
        volume = Volume(book_id=book_id, index=1, title="第一卷", chapter_count=0, status="approved")
        session.add(volume)
        await session.flush()
        unit = PlotUnit(book_id=book_id, volume_id=volume.id, index=1, title="入城", chapter_count=0, key_events=["进城"])
        session.add(unit)
        await session.commit()
        unit_id = unit.id
    # 旧版页面上的「提前出章纲」走同一条：章数没定时编辑部按剧情定（演示模式出 5 章）
    res = await client.post(f"/api/units/{unit_id}/expand")
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        unit = await session.get(PlotUnit, unit_id)
        rows = list(await session.scalars(select(Chapter).where(Chapter.unit_id == unit_id)))
        assert unit.chapter_count == len(rows) == 5


async def test_first_unit_takes_the_volume_count(client):
    book = await blank_book(client)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "甲"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    await client.patch(f"/api/volumes/{volume['id']}", json={"chapter_count": 12})
    # 卷上定的 12 章，拆出第一个单元时给它，不会一拆就变成「还没定」
    first = (await client.post(f"/api/volumes/{volume['id']}/units", json={})).json()
    assert first["chapter_count"] == 12
    second = (await client.post(f"/api/volumes/{volume['id']}/units", json={"after_unit_id": first["id"]})).json()
    assert second["chapter_count"] == 0
