"""第五步第二批：聊天里的改动改完当场看前后对照、换回原来的、再改一版；聊天里说「存个档」；写章一章一档。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import BookSave, Chapter, Character, Job, StoryNode
from app.services import book_saves, group_notes
from app.services.job_runner import execute_job
from tests.test_book_saves import full_book
from tests.test_chat_task6 import final_message, seed


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def say(client, book, text) -> dict:
    res = await client.post(f"/api/books/{book}/notes", json={"content": text})
    assert res.status_code == 201, res.text
    return await final_message(client, book, res.json()["id"])


async def titles(client, book) -> list[str]:
    return [row["title"] for row in (await client.get(f"/api/books/{book}/saves")).json()["items"]]


async def test_chat_edit_shows_before_and_after_and_can_go_back_or_redo(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风的性格改成冷静沉稳")
    mid = note["id"]
    outcome = note["payload"]["outcome"]
    assert outcome["kind"] == "edit", outcome
    assert [d["label"] for d in outcome["diff"]] == ["楚风 · 性格与说话方式"]
    assert outcome["diff"][0]["before"] == "" and outcome["diff"][0]["after"]
    assert (await titles(client, bid))[0] == "设定师照你的话改了楚风（性格与说话方式）"
    assert (await client.get(f"/api/books/{bid}/note-changes")).json() == {str(mid): True}

    # 再改一版：先换回，再照同一句话改一遍，前后对照换成新的
    res = await client.post(f"/api/books/{bid}/notes/{mid}/redo", json={})
    assert res.status_code == 202, res.text
    again = (await final_message(client, bid, mid))["payload"]["outcome"]
    assert again["kind"] == "edit" and again["diff"][0]["before"] == "" and again["change"]
    # 演示模型每次写得一样：再改一版以后和上一档一模一样，就不多存一档
    assert (await titles(client, bid))[0] == "设定师照你的话改了楚风（性格与说话方式）"

    # 作者后来手改了这一栏：按钮不能用，换回去返回 409
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        hero.personality = "作者自己写的"
        await session.commit()
    assert (await client.get(f"/api/books/{bid}/note-changes")).json() == {str(mid): False}
    res = await client.post(f"/api/books/{bid}/notes/{mid}/revert", json={})
    assert res.status_code == 409 and "后来又改过" in res.json()["detail"]


async def test_chat_fill_created_and_outline_can_be_taken_back(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    real_classify = group_notes.classify

    async def fill_intent(session, book_id, text, viewing=None):
        if text.startswith("把楚风补齐"):
            return s.LibraryIntent(kind="改设定", target_name="楚风", mode="补齐空着的", instruction=text)
        return await real_classify(session, book_id, text, viewing)

    monkeypatch.setattr(group_notes, "classify", fill_intent)
    # 补齐：每一栏补了什么都摆出来
    note = await say(client, bid, "把楚风补齐")
    outcome = note["payload"]["outcome"]
    assert outcome["kind"] == "fill" and len(outcome["diff"]) == len(outcome["filled"]) > 1
    assert all(d["before"] == "" and d["after"] for d in outcome["diff"])
    res = await client.post(f"/api/books/{bid}/notes/{note['id']}/revert", json={})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.background == "" and hero.abilities == "凝气境"
    assert (await titles(client, bid))[0] == "你换回了：楚风"

    # 新建：换回原来的就是删掉建的那一条
    async def fake_call(book_id, role, schema, template, **values):
        return s.DraftSet(entries=[s.DraftEntry(name="封不觉", values=[s.FieldValue(name="身世", value="推理作家")])])

    monkeypatch.setattr("app.api.workspace.call_model", fake_call)
    note = await say(client, bid, "写一张封不觉的角色卡")
    outcome = note["payload"]["outcome"]
    assert outcome["kind"] == "created" and outcome["diff"][0]["label"] == "新建 · 封不觉"
    assert "身世：推理作家" in outcome["diff"][0]["after"]
    assert (await client.post(f"/api/books/{bid}/notes/{note['id']}/revert", json={})).status_code == 200
    async with sessionmaker() as session:
        assert await session.scalar(select(Character).where(Character.name == "封不觉")) is None

    # 写大纲：还没有的那一篇先新建再写；换回原来的就是整篇删掉
    note = await say(client, bid, "帮我写一下第 1 篇")
    outcome = note["payload"]["outcome"]
    assert outcome["kind"] == "outline", outcome
    assert outcome["diff"][0]["label"].startswith("新建 · 第 1 篇")
    assert (await client.post(f"/api/books/{bid}/notes/{note['id']}/revert", json={})).status_code == 200
    async with sessionmaker() as session:
        assert await session.get(StoryNode, uuid.UUID(outcome["created_id"])) is None
    # 写作要求没有「再改一版」
    note = await say(client, bid, "以后每章都要有一场打斗")
    assert note["payload"]["outcome"]["kind"] == "requirement"
    assert (await client.post(f"/api/books/{bid}/notes/{note['id']}/redo", json={})).status_code == 422


async def test_save_by_saying_it_in_chat(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "存个档，叫开局定稿")
    assert note["payload"]["outcome"]["kind"] == "saved" and note["payload"]["outcome"]["title"] == "开局定稿"
    listing = (await client.get(f"/api/books/{bid}/saves")).json()["items"]
    assert listing[0]["title"] == "开局定稿" and listing[0]["kind"] == "manual"
    note = await say(client, bid, "存一档")
    assert note["payload"]["outcome"]["title"].endswith("存的")
    # 不是存档的话照常走
    assert group_notes.SAVE_WORDS.fullmatch("存档在哪看？") is None
    assert group_notes.SAVE_WORDS.fullmatch("帮我存个档，名字叫「第一卷写完」")["name"] == "第一卷写完"


async def test_written_chapters_each_save_and_restore_takes_chapters_back(client, sessionmaker):
    res = await client.post("/api/books", json={"start_setup": False, "title": "写三章", "genre": "玄幻"})
    book = res.json()["book"]["id"]
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "主角在青阳城崛起"})).json()
    volume = (await client.post(f"/api/books/{book}/volumes", json={"target_node_id": arc["id"]})).json()
    unit = (await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "入城", "chapter_count": 3})).json()
    for title in ("初入青阳", "药铺", "考核"):
        await client.post(f"/api/units/{unit['id']}/chapters", json={"title": title})
    await client.patch(f"/api/books/{book}/settings", json={"trial_read": False})

    res = await client.post(f"/api/books/{book}/write", json={"until": "count", "count": 3})
    assert res.status_code == 201, res.text
    await execute_job(uuid.UUID(res.json()["id"]))
    listing = (await client.get(f"/api/books/{book}/saves")).json()["items"]
    done = [row for row in listing if row["title"].startswith("写完第")]
    assert [row["title"] for row in done][::-1] == [
        "写完第 1 章「初入青阳」",
        "写完第 2 章「药铺」",
        "写完第 3 章「考核」",
    ]
    first = done[-1]
    assert first["chapters_final"] == 1 and first["actor"] == "writer"

    # 回到「写完第 1 章」：第 2、3 章的正文没了，设定里记的变化也回到第 1 章写完时
    res = await client.post(f"/api/books/{book}/saves/{first['id']}/restore")
    assert res.status_code == 200, res.text
    b = uuid.UUID(book)
    async with sessionmaker() as session:
        saved = await session.get(BookSave, first["id"])
        assert (await book_saves.read_state(session, b)).tree == saved.tree
        rows = list(await session.scalars(select(Chapter).where(Chapter.book_id == b).order_by(Chapter.index)))
        assert [(c.index, c.status, bool(c.content)) for c in rows] == [
            (1, "final", True),
            (2, "planned", False),
            (3, "planned", False),
        ]
    # 接着写：能正常写出第 2 章
    res = await client.post(f"/api/books/{book}/write", json={"until": "count", "count": 1})
    assert res.status_code == 201, res.text
    await execute_job(uuid.UUID(res.json()["id"]))
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(res.json()["id"]))
        assert job.status == "succeeded", (job.status, job.error)
        second = await session.scalar(select(Chapter).where(Chapter.book_id == b, Chapter.index == 2))
        assert second.status == "final" and second.content


async def test_restore_line_is_in_the_dialogue(client, sessionmaker):
    from app.services.chat_context import dialogue, dialogue_text

    b = await full_book(sessionmaker)
    async with sessionmaker() as session:
        first = await book_saves.checkpoint(session, b, "author", "开局定稿", kind="manual", force=True)
    await client.post(f"/api/books/{b}/saves/{first.id}/restore")
    async with sessionmaker() as session:
        text = dialogue_text(await dialogue(session, b, "group"))
    assert "你把书换回了存档「开局定稿」" in text


async def test_half_a_column_name_is_enough(sessionmaker):
    """真模型试出来的：「沈九的性格改成……」只说了「性格」，要认成「性格与说话方式」，不能退到补齐。"""
    from app.models import Book
    from app.services.desk import column_in

    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        hero = await session.scalar(select(Character).where(Character.book_id == bid))
        assert await column_in(session, book, hero, "性格", "楚风的性格改成冷静") == "性格与说话方式"
        assert await column_in(session, book, hero, "身世", "") == "身世"
        assert await column_in(session, book, hero, "", "楚风再厉害一点") is None
