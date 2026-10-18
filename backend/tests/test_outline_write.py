"""新书页大纲每一页的「编辑部帮写这一段」：只写名字和一段话（章写章纲），直接写进去，能撤销。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, SettingVersion, StoryNode


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
    book = (await client.post("/api/books", json={"start_setup": False, "title": "万古邪帝", "genre": "玄幻"})).json()["book"]["id"]
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    unit = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城"})).json()
    await client.post(f"/api/units/{unit['id']}/chapters", json={"title": "初入青阳"})
    await client.post(f"/api/units/{unit['id']}/chapters", json={})
    return book, arc, volume, unit


async def write(client, book, target_type, target_id, request=""):
    return await client.post(
        f"/api/books/{book}/outline/write",
        json={"target_type": target_type, "target_id": str(target_id), "request": request},
    )


async def test_volume_gets_a_name_and_a_paragraph_and_keeps_the_authors_name(client, sessionmaker):
    book, _, volume, unit = await outline_book(client)
    res = await write(client, book, "volume", volume["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "演示名字" and "剧情" in body["text"]
    assert body["before"] == {"name": "", "text": ""}
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert tree["arcs"][0]["volumes"][0]["summary"] == body["text"]
    async with sessionmaker() as session:
        latest = await session.scalar(
            select(SettingVersion)
            .where(SettingVersion.target_id == uuid.UUID(volume["id"]))
            .order_by(SettingVersion.version.desc())
            .limit(1)
        )
        assert latest.source == "ai" and latest.note == "编辑部帮写这一卷"

    # 作者起过名字的单元：名字不动，只写那段话；作者说换名字才换
    res = await write(client, book, "unit", unit["id"])
    assert res.json()["title"] == "入城"
    res = await write(client, book, "unit", unit["id"], "换个更响的名字")
    assert res.json()["title"] == "演示名字"


async def test_chapter_gets_an_outline_and_started_chapters_are_left_alone(client):
    book, _, _, unit = await outline_book(client)
    res = await write(client, book, "chapter", 2)
    assert res.status_code == 200, res.text
    assert res.json()["sections"]["发生什么"].startswith("（演示）")
    assert res.json()["before"] == {"name": "", "sections": {"发生什么": "", "看点": "", "结尾钩子": ""}}
    chapters = (await client.get(f"/api/books/{book}/chapters?with_outline=true")).json()
    assert chapters[1]["title"] == "演示章名"
    assert chapters[1]["outline"]["hook"] == "（演示）钩子"

    await client.patch(f"/api/books/{book}/chapters/1", json={"content": "正文"})
    res = await write(client, book, "chapter", 1)
    assert res.status_code == 409
    res = await write(client, book, "unit", unit["id"])
    assert res.status_code == 409


async def test_ending_and_locked_arcs(client, sessionmaker):
    book, arc, *_ = await outline_book(client)
    res = await write(client, book, "book", "book")
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        row = await session.get(Book, uuid.UUID(book))
        assert row.concept["ending"] == res.json()["text"]
        node = await session.get(StoryNode, uuid.UUID(arc["id"]))
        node.status = "pinned"
        await session.commit()
    res = await write(client, book, "segment", arc["id"])
    assert res.status_code == 409


async def test_the_editor_sees_where_the_paragraph_sits(client, monkeypatch):
    book, _, volume, unit = await outline_book(client)
    seen = {}

    async def fake_call(book_id, role, schema, template, **values):
        seen.update(values, template=template, schema=schema)
        return s.OutlineNodeWrite(title="x", text="写好的一段")

    monkeypatch.setattr("app.api.library_ai.call_model", fake_call)
    res = await write(client, book, "unit", unit["id"], "多点打脸")
    assert res.status_code == 200, res.text
    assert seen["template"] == "outline_write" and seen["schema"] is s.OutlineNodeWrite
    assert seen["node_name"] == "单元 1「入城」"
    lines = seen["outline"].splitlines()
    marked = [line for line in lines if "← 要写的就是这一段" in line]
    assert len(marked) == 1 and "单元 1「入城」" in marked[0]
    # 所在单元展开到章；书的结局在最后
    assert any("第 1 章「初入青阳」" in line for line in lines)
    assert lines[0].startswith("第 1 篇「青阳城篇」") and lines[-1].startswith("结局")
    assert "多点打脸" in seen["request"] and "章数还没定" in seen["write_rule"]


async def test_group_chat_writes_the_page_the_author_is_looking_at(client):
    from tests.test_chat_task6 import final_message

    book, _, volume, unit = await outline_book(client)
    viewing = {"target_type": "unit", "target_id": unit["id"], "label": "大纲 · 单元 1「入城」"}
    res = await client.post(f"/api/books/{book}/notes", json={"content": "帮我写一下这个单元的剧情概要", "viewing": viewing})
    assert res.status_code == 201, res.text
    assert res.json()["payload"]["viewing"] == viewing
    message = await final_message(client, book, res.json()["id"])
    outcome = message["payload"]["outcome"]
    assert outcome["kind"] == "outline" and outcome["target_type"] == "unit" and outcome["target_label"] == "单元 1「入城」"
    assert outcome["before"] == {"name": "入城", "text": ""}
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert tree["arcs"][0]["volumes"][0]["units"][0]["summary"].startswith("（演示）")
    messages = (await client.get(f"/api/books/{book}/meeting")).json()
    assert any(m["speaker"] == "chief" and "写好了" in m["content"] for m in messages)

    # 消息下面点撤销：换回原来的
    res = await client.post(
        f"/api/books/{book}/outline/restore",
        json={"target_type": "unit", "target_id": unit["id"], "before": outcome["before"]},
    )
    assert res.status_code == 200, res.text
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert tree["arcs"][0]["volumes"][0]["units"][0]["summary"] == ""

    # 说了第几卷的照说的找；没在看大纲又说「这一篇」的认不出，不乱写
    res = await client.post(f"/api/books/{book}/notes", json={"content": "帮我写一下第1卷"})
    outcome = (await final_message(client, book, res.json()["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "outline" and outcome["target_type"] == "volume" and outcome["target_id"] == volume["id"]
    res = await client.post(f"/api/books/{book}/notes", json={"content": "帮我写一下这一篇"})
    outcome = (await final_message(client, book, res.json()["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "not_found"


async def test_resolving_which_paragraph(client, sessionmaker):
    from app.services.outline_write import resolve_outline_target

    book, arc, volume, unit = await outline_book(client)
    async with sessionmaker() as session:
        row = await session.get(Book, uuid.UUID(book))

        async def find(words, viewing=None):
            found = await resolve_outline_target(session, row, words, viewing)
            return found and found[:2]

        assert await find("第一篇") == ("segment", arc["id"])
        assert await find("青阳城篇") == ("segment", arc["id"])
        assert await find("结局") == ("book", "book")
        assert await find("第 2 章") == ("chapter", "2")
        assert await find("初入青阳") == ("chapter", "1")
        assert await find("单元一", {"target_type": "volume", "target_id": volume["id"]}) == ("unit", unit["id"])
        assert await find("正在看的", {"target_type": "volume", "target_id": volume["id"]}) == ("volume", volume["id"])
        # 正在看的是设定卡，不是大纲：认不出
        assert await find("正在看的", {"target_type": "character", "target_id": str(uuid.uuid4())}) is None
        assert await find("第九卷") is None
