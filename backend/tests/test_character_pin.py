"""角色置顶（2026-10-19，代替页面上的「定位」）：置顶的排最上面，编辑部每写一章都带上；没人置顶时退回旧的主角、再退回简介。"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from redis.asyncio import Redis

from app.config import get_settings
from app.main import create_app
from app.models import Book, Character
from app.services.book_saves import row_data
from app.services.library_context import main_cast
from app.services.writing_context import character_profiles


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def test_pin_and_unpin(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="置顶")
        session.add(book)
        await session.flush()
        people = [Character(book_id=book.id, name=name) for name in ("楚风", "苏晚晴", "老怪")]
        session.add_all(people)
        await session.commit()
        ids = [str(p.id) for p in people]
    for i in (0, 1):
        res = await client.post(f"/api/characters/{ids[i]}/pin", json={"pinned": True})
        assert res.status_code == 200 and res.json()["pinned_at"]
    rows = {c["id"]: c for c in (await client.get(f"/api/books/{book.id}/library")).json()["characters"]}
    assert rows[ids[1]]["pinned_at"] > rows[ids[0]]["pinned_at"] and rows[ids[2]]["pinned_at"] is None
    # 置顶的进「重点」
    focus = set((await client.get(f"/api/books/{book.id}/library")).json()["focus"]["characters"])
    assert focus == {ids[0], ids[1]}
    res = await client.post(f"/api/characters/{ids[0]}/pin", json={"pinned": False})
    assert res.json()["pinned_at"] is None
    assert (await client.post(f"/api/characters/{uuid.uuid4()}/pin", json={"pinned": True})).status_code == 404


def person(name, pinned=None, role="配角"):
    return SimpleNamespace(name=name, pinned_at=pinned, role_type=role, aliases=[])


def test_main_cast_order_and_fallbacks():
    now = datetime.now(UTC)
    hero, girl, old = person("楚风", role="主角"), person("苏晚晴", now), person("老怪", now + timedelta(seconds=5))
    # 后置顶的在前；有人置顶时旧的「主角」不算
    assert main_cast([hero, girl, old]) == [old, girl]
    # 没人置顶：旧数据里定位是主角的
    assert main_cast([hero, person("苏晚晴")]) == [hero]
    # 再没有：简介里提到的名字
    assert [c.name for c in main_cast([person("陆远"), person("苏晚晴")], "陆远借青灯看穿底牌")] == ["陆远"]
    assert main_cast([person("陆远")], "") == []


def test_every_chapter_brings_the_pinned(monkeypatch):
    now = datetime.now(UTC)
    people = [person("楚风", role="主角"), person("苏晚晴", now), person("老怪")]
    monkeypatch.setattr("app.services.writing_context._char_dict", lambda c: {"name": c.name})
    monkeypatch.setattr("app.services.writing_context.format_character", lambda d: d["name"])
    # 这一章只提到老怪：置顶的苏晚晴也带上；楚风没置顶（有人置顶时旧主角不算）就不带
    assert character_profiles(people, ["老怪"]).split("\n\n") == ["苏晚晴", "老怪"]


def test_saves_do_not_count_unpinned_as_a_change():
    assert "pinned_at" not in row_data(Character, {"name": "楚风", "pinned_at": None})
    assert row_data(Character, {"name": "楚风", "pinned_at": datetime(2026, 10, 19, tzinfo=UTC)})["pinned_at"]
