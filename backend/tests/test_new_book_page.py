"""新建页：作者先填书名、简介、类别、标签、篇幅，建好书编辑部不开工。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.main import create_app
from app.models import Job, MeetingMessage
from app.services import jobs


@pytest.fixture
def queued(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: calls.append(job_id))
    return calls


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def count(sessionmaker, model) -> int:
    async with sessionmaker() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_blank_book_saves_what_author_filled_and_starts_nothing(client, queued, sessionmaker):
    res = await client.post(
        "/api/books",
        json={
            "start_setup": False,
            "title": "  寿命簿 ",
            "blurb": "一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营。",
            "genre": "玄幻",
            "tags": ["苟道", " 宗门", "苟道", ""],
            "target_length": 200,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["job"] is None
    book = body["book"]
    assert book["title"] == "寿命簿"
    assert book["genre"] == "玄幻"
    assert book["idea"].startswith("一个能看见")
    assert book["concept"] == {
        "title": "寿命簿",
        "story": "一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营。",
        "genre": "玄幻",
        "tags": ["苟道", "宗门"],
        "target_length": 200,
    }
    assert book["active_job"] is None
    assert queued == []
    assert await count(sessionmaker, Job) == 0
    assert await count(sessionmaker, MeetingMessage) == 0


async def test_blank_book_can_be_completely_empty(client, queued):
    res = await client.post("/api/books", json={"start_setup": False})
    assert res.status_code == 201, res.text
    book = res.json()["book"]
    assert book["title"] == "未命名"
    assert book["concept"] == {}
    assert queued == []


@pytest.mark.parametrize(
    "extra",
    [{"target_length": 400}, {"tags": ["一" * 21]}, {"tags": ["标签"] * 21}],
)
async def test_blank_book_rejects_bad_fields(client, queued, extra):
    res = await client.post("/api/books", json={"start_setup": False, **extra})
    assert res.status_code == 422


async def test_old_entry_still_needs_an_idea_and_starts_the_setup(client, queued):
    res = await client.post("/api/books", json={"idea": "末世"})
    assert res.status_code == 422
    res = await client.post("/api/books", json={"idea": "末世里开奶茶店"})
    assert res.status_code == 201, res.text
    assert res.json()["job"] is not None
    assert len(queued) == 1
