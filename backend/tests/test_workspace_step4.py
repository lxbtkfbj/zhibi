"""新书页第四步：新书页建的书（不走开书流程）也能开写；大纲空着不行；「写完这个单元」写完就停。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, Chapter, Job, Volume
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    # 只测接口和流程，不真的派给后台任务
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def new_book(client, title="新书页的书") -> str:
    return (await client.post("/api/books", json={"start_setup": False, "title": title, "genre": "玄幻"})).json()[
        "book"
    ]["id"]


async def test_empty_outline_cannot_start_writing(client, sessionmaker):
    book = await new_book(client)
    res = await client.post(f"/api/books/{book}/write", json={"until": "count", "count": 3})
    assert res.status_code == 409 and "大纲还空着" in res.json()["detail"]
    # 篇只有名字、没写那段话也不行
    await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": ""})
    res = await client.post(f"/api/books/{book}/write", json={"until": "count", "count": 3})
    assert res.status_code == 409
    async with sessionmaker() as session:
        assert (await session.get(Book, uuid.UUID(book))).status == "setting_up"


async def test_write_this_unit_stops_when_the_unit_is_done(client, sessionmaker):
    book = await new_book(client)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    first = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城"})).json()
    await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "考核", "after_unit_id": first["id"]})
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "初入青阳"})
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "药铺"})

    res = await client.post(f"/api/books/{book}/write", json={"until": "unit", "count": 1})
    assert res.status_code == 201, res.text
    job_id = uuid.UUID(res.json()["id"])
    async with sessionmaker() as session:
        assert (await session.get(Book, uuid.UUID(book))).status == "writing"
        assert (await session.get(Job, job_id)).params["until"] == "unit"

    await execute_job(job_id)
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.status == "succeeded", (job.status, job.pending, job.error)
        rows = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(book)).order_by(Chapter.index))
        )
        # 入城的两章写完就停，考核那个单元还没出章纲
        assert [(c.index, c.title, c.status) for c in rows] == [(1, "初入青阳", "final"), (2, "药铺", "final")]


async def test_unit_added_after_the_volume_is_done_still_gets_written(client, sessionmaker):
    book = await new_book(client)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    first = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城"})).json()
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "初入青阳"})
    await client.patch(f"/api/books/{book}/settings", json={"trial_read": False})

    async def write_unit() -> Job:
        res = await client.post(f"/api/books/{book}/write", json={"until": "unit", "count": 1})
        assert res.status_code == 201, res.text
        await execute_job(uuid.UUID(res.json()["id"]))
        async with sessionmaker() as session:
            return await session.get(Job, uuid.UUID(res.json()["id"]))

    job = await write_unit()
    assert job.status == "succeeded", (job.status, job.pending, job.error)
    async with sessionmaker() as session:
        assert (await session.get(Volume, uuid.UUID(volume["id"]))).status == "done"

    # 卷写完以后作者又加了一个单元：接着写的时候不能跳过它去拆下一卷
    second = (
        await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "考核", "after_unit_id": first["id"]})
    ).json()
    res = await client.post(f"/api/units/{second['id']}/chapters", json={"title": "考核开始"})
    assert res.status_code == 201, res.text
    job = await write_unit()
    assert job.status == "succeeded", (job.status, job.pending, job.error)
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(book)).order_by(Chapter.index))
        )
        # 主编给新单元补了单元纲，可能再添几章；都写完、都在这一卷里
        assert [(c.title, c.status) for c in rows[:2]] == [("初入青阳", "final"), ("考核开始", "final")]
        assert all(c.status == "final" and str(c.volume_id) == volume["id"] for c in rows)
        assert {str(c.unit_id) for c in rows[1:]} == {second["id"]}
        assert (await session.get(Volume, uuid.UUID(volume["id"]))).status == "done"
        assert (await session.get(Volume, uuid.UUID(volume["id"]))).recap.strip()


async def test_unit_with_fewer_outlined_chapters_than_planned_gets_topped_up(client, sessionmaker):
    book = await new_book(client)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    first = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城", "chapter_count": 3})).json()
    await client.post(f"/api/units/{first['id']}/chapters", json={"title": "初入青阳"})
    await client.patch(f"/api/books/{book}/settings", json={"trial_read": False})

    # 作者定了 3 章、只列了 1 章：写完这一章不算单元写完，编辑部补出剩下 2 章再停
    res = await client.post(f"/api/books/{book}/write", json={"until": "unit", "count": 1})
    assert res.status_code == 201, res.text
    await execute_job(uuid.UUID(res.json()["id"]))
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(res.json()["id"]))
        assert job.status == "succeeded", (job.status, job.pending, job.error)
        rows = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(book)).order_by(Chapter.index))
        )
        assert [c.index for c in rows] == [1, 2, 3]
        assert rows[0].title == "初入青阳"
        assert all(c.status == "final" and str(c.unit_id) == first["id"] for c in rows)
