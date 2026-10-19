"""第五步第二批：整本书的存档（设计说明 9.13「第二批：存档」）。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import (
    AuthorRequirement,
    Book,
    BookObject,
    BookSave,
    Chapter,
    Character,
    Foreshadowing,
    Job,
    MeetingMessage,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    SettingCandidate,
    SettingCategory,
    SettingSuggestion,
    StoryNode,
    StoryThread,
    Volume,
    WorldEntry,
)
from app.services import book_saves


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


async def full_book(sessionmaker) -> uuid.UUID:
    """什么都有的一本书：各类设定、带上下级的地点、关系、出场、写了两章带正文和记进设定的变化、
    伏笔、信息差、写作要求、待处理建议、自定的类别和栏目。"""
    async with sessionmaker() as session:
        book = Book(
            title="青阳传",
            genre="玄幻",
            concept={"title": "青阳传", "pitch": "废柴逆袭"},
            card_layouts={"势力划分": {"facts": [], "sections": [{"key": "宗旨", "label": "宗旨"}]}},
            status="ready",
        )
        session.add(book)
        await session.flush()
        b = book.id
        hero = Character(
            book_id=b, name="林凡", role_type="主角", background="山村少年", extra={"实力与地位": "炼气一层"}
        )
        foe = Character(book_id=b, name="赵虎", role_type="对手")
        session.add_all([hero, foe])
        opening = StoryNode(book_id=b, position=0, kind="opening", title="开篇", event="林凡被退婚")
        arc = StoryNode(
            book_id=b, position=1, kind="node", title="青阳城", segment={"title": "青阳城篇", "text": "入城"}
        )
        ending = StoryNode(book_id=b, position=2, kind="ending", title="结局", event="林凡登顶")
        session.add_all([opening, arc, ending])
        await session.flush()
        secret = Secret(book_id=b, seq=1, title="身世", truth="林凡是帝子", node_id=arc.id)
        session.add(secret)
        await session.flush()
        city = WorldEntry(book_id=b, category="世界与地图", name="青阳城", content="边陲小城")
        session.add(city)
        await session.flush()
        session.add_all(
            [
                WorldEntry(book_id=b, category="世界与地图", name="药铺", content="城东", parent_id=city.id),
                WorldEntry(book_id=b, category="往事与秘密", name="帝子之谜", secret_id=secret.id),
                WorldEntry(
                    book_id=b,
                    category="custom:shops",
                    name="百宝阁",
                    style="card",
                    fields=[{"name": "店主", "value": "钱掌柜"}],
                ),
                SettingCategory(book_id=b, key="shops", name="店铺", style="card", fields=["店主"]),
                Relationship(book_id=b, source_id=hero.id, target_id=foe.id, kind="仇人"),
                NodeAnchor(book_id=b, node_id=arc.id, character_id=foe.id, kind="退场"),
                Foreshadowing(
                    book_id=b, seq=1, description="玉佩", status="planted", planted_chapter=1, node_id=arc.id
                ),
                StoryThread(book_id=b, name="主线", kind="主线", beats=[{"volume": 1, "beat": "入城"}]),
            ]
        )
        volume = Volume(book_id=b, index=1, title="入城", target_node_id=arc.id, status="approved")
        session.add(volume)
        await session.flush()
        unit = PlotUnit(book_id=b, volume_id=volume.id, index=1, title="退婚", status="outlined")
        session.add(unit)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    book_id=b,
                    volume_id=volume.id,
                    unit_id=unit.id,
                    index=1,
                    title="退婚",
                    content="林凡站在门口。" * 50,
                    word_count=300,
                    status="final",
                    summary="林凡被退婚",
                    bible_changes={"characters": {"林凡": {"condition": ""}}},
                ),
                Chapter(book_id=b, volume_id=volume.id, unit_id=unit.id, index=2, title="入城", status="planned"),
                AuthorRequirement(book_id=b, text="每章都要有打斗", source="manual"),
                SettingSuggestion(
                    book_id=b, kind="chat", title="补上赵虎的身世", payload={"op": "note", "content": "x"}
                ),
            ]
        )
        await session.commit()
        return b


async def rows_of(session, book_id):
    """每张表逐行（去掉 updated_at）：比较两次是不是一模一样。"""
    snap = await book_saves.read_state(session, book_id)
    return {table: dict(rows) for table, rows in snap.data.items()}


async def test_round_trip_restores_every_table(client, sessionmaker):
    b = await full_book(sessionmaker)
    async with sessionmaker() as session:
        first = await book_saves.checkpoint(session, b, "author", "开局定稿", kind="manual", force=True)
        saved = await rows_of(session, b)

    # 大改一通：改、加、删、再写一章
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == b, Character.name == "林凡"))
        hero.background = "其实是帝子转世"
        foe = await session.scalar(select(Character).where(Character.name == "赵虎"))
        await session.delete(foe)
        session.add(Character(book_id=b, name="苏瑶", role_type="女主"))
        city = await session.scalar(select(WorldEntry).where(WorldEntry.name == "青阳城"))
        await session.delete(city)
        ch2 = await session.scalar(select(Chapter).where(Chapter.book_id == b, Chapter.index == 2))
        ch2.content, ch2.status = "林凡进了城。" * 30, "final"
        session.add(Chapter(book_id=b, index=3, title="药铺", content="药香", status="final"))
        req = await session.scalar(select(AuthorRequirement).where(AuthorRequirement.book_id == b))
        await session.delete(req)
        book = await session.get(Book, b)
        book.title, book.concept = "青阳帝尊", {"title": "青阳帝尊"}
        session.add(
            SettingCandidate(
                book_id=b, target_type="character", target_id=hero.id, path="background", base="", options=[]
            )
        )
        await session.commit()
    async with sessionmaker() as session:
        changed = await rows_of(session, b)
        assert changed != saved

    res = await client.post(f"/api/books/{b}/saves/{first.id}/restore")
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        assert await rows_of(session, b) == saved
        assert (await session.get(Book, b)).title == "青阳传"
        # 三种写法的临时候选清掉了
        assert await session.scalar(select(func.count()).select_from(SettingCandidate)) == 0
        saves = list(await session.scalars(select(BookSave).where(BookSave.book_id == b).order_by(BookSave.id)))
        assert [s.title for s in saves][-2:] == ["回到「开局定稿」之前的样子", "回到了「开局定稿」"]
        assert saves[-1].kind == "restore" and saves[-1].restored_from == first.id
        assert saves[-1].tree == first.tree
        back = saves[-2]
        # 聊天里插了那一行
        line = await session.scalar(select(MeetingMessage).where(MeetingMessage.book_id == b))
        assert (
            line.speaker == "system" and "开局定稿" in line.content and line.payload["restore"]["save_id"] == first.id
        )

    # 再回到「回到之前的样子」那一档：又和大改后一样
    res = await client.post(f"/api/books/{b}/saves/{back.id}/restore")
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        assert await rows_of(session, b) == changed


async def test_same_state_is_not_saved_and_one_edit_adds_one_row(sessionmaker):
    b = await full_book(sessionmaker)
    async with sessionmaker() as session:
        assert await book_saves.checkpoint(session, b, "author") is not None
        before = await session.scalar(select(func.count()).select_from(BookObject))
        # 跟上一档一模一样就不存
        assert await book_saves.checkpoint(session, b, "chief") is None
        hero = await session.scalar(select(Character).where(Character.name == "林凡"))
        hero.goal = "报仇"
        await session.commit()
        save = await book_saves.checkpoint(session, b, "author")
        # 只多了主角那一行的新对象，和角色表的一张新清单
        assert await session.scalar(select(func.count()).select_from(BookObject)) == before + 2
        assert save.title == "你自己改的：改了林凡（想要什么）"
        assert save.summary["items"][0]["group"] == "设定"


async def test_cannot_restore_while_working_and_resumable_job_is_cancelled(client, sessionmaker):
    b = await full_book(sessionmaker)
    async with sessionmaker() as session:
        first = await book_saves.checkpoint(session, b, "author", "一档", kind="manual", force=True)
        job = Job(
            book_id=b, kind="write_book", thread_id="t", status="waiting_author", pending={"kind": "volume_review"}
        )
        session.add(job)
        await session.commit()
    res = await client.post(f"/api/books/{b}/saves/{first.id}/restore")
    assert res.status_code == 409 and "拍板" in res.json()["detail"]
    async with sessionmaker() as session:
        job = await session.get(Job, job.id)
        job.status = "failed"
        await session.commit()
    res = await client.post(f"/api/books/{b}/saves/{first.id}/restore")
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        assert (await session.get(Job, job.id)).status == "cancelled"


async def test_save_detail_compares_with_now(client, sessionmaker):
    b = await full_book(sessionmaker)
    async with sessionmaker() as session:
        first = await book_saves.checkpoint(session, b, "author", "一档", kind="manual", force=True)
        hero = await session.scalar(select(Character).where(Character.name == "林凡"))
        hero.background = "帝子"
        ch2 = await session.scalar(select(Chapter).where(Chapter.book_id == b, Chapter.index == 2))
        ch2.content, ch2.status = "林凡进了城，" * 100, "final"
        await session.commit()
    detail = (await client.get(f"/api/books/{b}/saves/{first.id}")).json()
    groups = {g["name"]: g["items"] for g in detail["groups"]}
    assert detail["now_final"] == 2 and detail["save"]["chapters_final"] == 1
    hero = next(i for i in groups["设定"] if i["name"] == "林凡")
    assert hero["parts"] == [
        {"label": "身世", "then": "山村少年", "now": "帝子", "then_words": 4, "now_words": 2, "long": False}
    ]
    chapter = groups["正文"][0]
    body = next(p for p in chapter["parts"] if p["label"] == "正文")
    assert body["then"] == "" and body["long"] and body["now_words"] == 600
    full = (
        await client.get(
            f"/api/books/{b}/saves/{first.id}/text", params={"table": "chapters", "row": chapter["id"], "label": "正文"}
        )
    ).json()
    assert full["now"] == "林凡进了城，" * 100


async def test_manual_and_auto_saves_api(client, sessionmaker):
    b = await full_book(sessionmaker)
    res = await client.post(f"/api/books/{b}/saves", json={"label": "开局定稿"})
    assert res.json()["save"]["title"] == "开局定稿" and res.json()["save"]["kind"] == "manual"
    # 手改以后自动存：一样就不存
    assert (await client.post(f"/api/books/{b}/saves", json={"auto": True})).json()["save"] is None
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.name == "林凡"))
        hero.notes = "爱吃面"
        await session.commit()
    res = (await client.post(f"/api/books/{b}/saves", json={"auto": True})).json()
    assert res["save"]["actor"] == "author" and res["save"]["title"] == "你自己改的：改了林凡（备注）"
    listing = (await client.get(f"/api/books/{b}/saves")).json()
    assert [s["title"] for s in listing["items"]] == ["你自己改的：改了林凡（备注）", "开局定稿"]
