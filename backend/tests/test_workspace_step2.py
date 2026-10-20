"""新书页第二步：写到多细自动算、金手指成类、全书结局给模型看、实力与地位每章更新、作者加篇加章、章纲能改。"""

import uuid

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from redis.asyncio import Redis
from sqlalchemy import select

from alembic import command
from app.agents import schemas as s
from app.agents.context import format_character_state, format_concept
from app.config import get_settings
from app.graphs.write_book import decide
from app.main import create_app
from app.models import Book, Chapter, Character, StoryNode, Volume
from app.services import arc_store, writing_store
from app.services.library_context import load_context
from tests.test_settings_library_migration import _insert, _rows


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def blank_book(client) -> str:
    res = await client.post("/api/books", json={"start_setup": False, "title": "寿命簿", "genre": "玄幻"})
    assert res.status_code == 201, res.text
    return res.json()["book"]["id"]


# ---------- 写到多细自动算 ----------


async def test_status_follows_how_much_is_written(client):
    book = await blank_book(client)
    person = (await client.post(f"/api/books/{book}/characters", json={"name": "陈默", "role_type": "配角"})).json()
    assert person["status"] == "later"
    # 定位、所属这类短字段不算写了内容
    res = await client.patch(f"/api/characters/{person['id']}", json={"gender": "男", "extra": {"所属": "青冥宗"}})
    assert res.json()["status"] == "later"
    res = await client.patch(f"/api/characters/{person['id']}", json={"appearance": "左脸一道疤"})
    assert res.json()["status"] == "one"
    res = await client.patch(f"/api/characters/{person['id']}", json={"extra": {"软肋": "怕死"}})
    assert res.json()["status"] == "must"
    # 只锁住不重算；作者明确给了状态就照给的
    await client.patch(f"/api/characters/{person['id']}", json={"status": "later"})
    res = await client.patch(f"/api/characters/{person['id']}", json={"locked": True})
    assert res.json()["status"] == "later"

    entry = (
        await client.post(f"/api/books/{book}/world-entries", json={"category": "特殊规则", "name": "夺舍"})
    ).json()
    assert entry["status"] == "later"
    res = await client.patch(f"/api/world-entries/{entry['id']}", json={"content": "只能夺舍神识比自己弱的人。"})
    assert res.json()["status"] == "one"
    res = await client.patch(
        f"/api/world-entries/{entry['id']}",
        json={"content": "1. 只能夺舍神识比自己弱的人\n2. 一辈子只能夺舍一次"},
    )
    assert res.json()["status"] == "must"
    res = await client.patch(
        f"/api/world-entries/{entry['id']}", json={"content": "", "field_values": {"代价": "折寿十年"}}
    )
    assert res.json()["status"] == "one"
    ladder = await client.post(
        f"/api/books/{book}/world-entries",
        json={
            "category": "等级体系",
            "name": "境界",
            "levels": [{"name": "炼气", "text": ""}, {"name": "筑基", "text": ""}],
        },
    )
    assert ladder.json()["status"] == "must"


# ---------- 金手指 ----------


async def test_goldfinger_is_its_own_category(client, sessionmaker):
    book = await blank_book(client)
    res = await client.post(
        f"/api/books/{book}/world-entries",
        json={"category": "金手指", "name": "寿命簿", "content": "能看见每个人还剩多少寿命", "tags": ["金手指"]},
    )
    assert res.status_code == 201, res.text
    finger = res.json()
    assert finger["category"] == "金手指" and finger["style"] == "paragraph"
    # 老数据：特殊规则里带标签的，也算在金手指里调栏目
    old = (
        await client.post(
            f"/api/books/{book}/world-entries",
            json={
                "category": "特殊规则",
                "name": "系统",
                "tags": ["金手指"],
                "fields": [{"name": "来源", "value": "天外"}],
            },
        )
    ).json()
    rule = (await client.post(f"/api/books/{book}/world-entries", json={"category": "特殊规则", "name": "货币"})).json()
    layout = {
        "facts": [{"key": "是什么", "label": "是什么"}],
        "sections": [{"key": "能做什么", "label": "能做什么"}, {"key": "来源", "label": "来历"}],
    }
    res = await client.put(f"/api/books/{book}/card-layouts/金手指", json=layout)
    assert res.status_code == 200, res.text
    library = (await client.get(f"/api/books/{book}/library")).json()
    entries = {row["id"]: row for row in library["entries"]}
    assert entries[old["id"]]["fields"] == [{"name": "来历", "value": "天外"}]
    assert entries[rule["id"]]["fields"] == []
    assert [row["key"] for row in library["categories"]][:3] == ["角色卡片", "金手指", "等级体系"]

    async with sessionmaker() as session:
        ctx = await load_context(session, await session.get(Book, uuid.UUID(book)))
        assert "【金手指】\n- 寿命簿" in ctx.library


def test_goldfinger_migration_moves_tagged_paragraphs(migration_database_urls):
    name = f"zhibi_goldfinger_test_{uuid.uuid4().hex}"
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0016")
        tables = sa.MetaData()
        tables.reflect(bind=engine)
        book_id, place_id = uuid.uuid4(), uuid.uuid4()
        entry = tables.tables["world_entries"]
        with engine.begin() as connection:
            _insert(connection, tables.tables["books"], id=book_id, title="旧书", concept={}, card_layouts={})
            rows = [
                ("特殊规则", "系统", "paragraph", ["金手指"], None, uuid.uuid4()),
                ("物品与功法", "轮回镜", "paragraph", ["金手指", "底牌"], None, uuid.uuid4()),
                ("等级体系", "系统等级", "ladder", ["金手指"], None, uuid.uuid4()),
                ("特殊规则", "货币", "paragraph", [], None, uuid.uuid4()),
                ("世界与地图", "灵泉", "paragraph", ["金手指"], None, place_id),
                ("世界与地图", "泉眼", "paragraph", [], place_id, uuid.uuid4()),
            ]
            for category, title, style, tags, parent, row_id in rows:
                _insert(
                    connection,
                    entry,
                    id=row_id,
                    book_id=book_id,
                    category=category,
                    name=title,
                    style=style,
                    tags=tags,
                    parent_id=parent,
                    fields=[],
                    levels=[],
                )
        command.upgrade(config, "0017")
        with engine.connect() as connection:
            moved = {row["name"]: row["category"] for row in _rows(connection, "world_entries")}
        assert moved == {
            "系统": "金手指",
            "轮回镜": "金手指",
            "系统等级": "等级体系",
            "货币": "特殊规则",
            # 还有下级地方的不搬
            "灵泉": "世界与地图",
            "泉眼": "世界与地图",
        }
        command.downgrade(config, "0016")
        with engine.connect() as connection:
            back = {row["name"]: row["category"] for row in _rows(connection, "world_entries")}
        assert back["系统"] == back["轮回镜"] == "特殊规则"
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


# ---------- 全书结局 ----------


async def test_concept_ending_reaches_the_model_until_there_is_an_ending_node(client, sessionmaker):
    book = await blank_book(client)
    res = await client.patch(
        f"/api/books/{book}",
        json={"concept": {"story": "陈默看得见寿命。", "ending": "陈默改写生死簿。"}, "review_changes": False},
    )
    assert res.status_code == 200, res.text
    assert "全书结局：陈默改写生死簿。" in format_concept({"story": "x", "ending": "陈默改写生死簿。"})
    async with sessionmaker() as session:
        ctx = await load_context(session, await session.get(Book, uuid.UUID(book)))
        assert "全书结局：陈默改写生死簿。" in ctx.concept
        assert ctx.outline.endswith("结局：陈默改写生死簿。")
        node = StoryNode(book_id=uuid.UUID(book), position=1, kind="ending", title="结局", event="旧的结局")
        session.add(node)
        await session.commit()
        node_id = node.id
    async with sessionmaker() as session:
        ctx = await load_context(session, await session.get(Book, uuid.UUID(book)))
        assert "陈默改写生死簿" not in ctx.concept and ctx.outline.endswith("结局：旧的结局")
    # 有了结局节点，作者改结局写在节点上，概念里那句不再留
    res = await client.patch(f"/api/nodes/{node_id}", json={"event": "陈默合上生死簿。"})
    assert res.status_code == 200, res.text
    detail = (await client.get(f"/api/books/{book}")).json()
    assert "ending" not in detail["concept"]


# ---------- 实力与地位 ----------


async def test_digest_updates_power_and_rewrite_reverts_it(client, sessionmaker):
    book = await blank_book(client)
    async with sessionmaker() as session:
        hero = Character(book_id=uuid.UUID(book), name="陈默", role_type="主角", extra={"实力与地位": "炼气三层"})
        chapter = Chapter(book_id=uuid.UUID(book), index=1, title="开局", status="drafting", content="正文")
        session.add_all([hero, chapter])
        await session.commit()
        digest = s.ChapterDigest(
            summary="陈默突破。",
            remark="",
            character_updates=[s.CharacterUpdate(name="陈默", power="筑基初期", abilities="")],
        )
        await writing_store.apply_digest(session, uuid.UUID(book), chapter, digest)
        await session.commit()
        await session.refresh(hero)
        assert hero.extra == {"实力与地位": "筑基初期"}
        assert "实力与地位：筑基初期" in format_character_state({"name": "陈默", "extra": hero.extra})
        await writing_store.revert_chapter(session, uuid.UUID(book), chapter)
        await session.commit()
        await session.refresh(hero)
        assert hero.extra == {"实力与地位": "炼气三层"}


# ---------- 作者加篇 ----------


async def test_author_adds_arcs_and_volumes_in_order(client):
    book = await blank_book(client)
    first = await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "陈默在青阳城站稳脚跟。"})
    assert first.status_code == 201, first.text
    second = (await client.post(f"/api/books/{book}/arcs", json={"title": "宗门篇", "text": ""})).json()
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert tree["segmented"] is True
    assert [(arc["title"], arc["text"], arc["planned"]) for arc in tree["arcs"]] == [
        ("青阳城篇", "陈默在青阳城站稳脚跟。", True),
        ("宗门篇", "", True),
    ]
    # 改篇名：作者的篇没写终点，终点名跟着走
    res = await client.patch(f"/api/nodes/{second['id']}", json={"segment": {"title": "天元宗篇"}})
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "天元宗篇"

    volume = await client.post(f"/api/books/{book}/volumes", json={"target_node_id": second["id"], "chapter_count": 30})
    assert volume.status_code == 201, volume.text
    res = await client.delete(f"/api/arcs/{second['id']}")
    assert res.status_code == 409
    await client.delete(f"/api/volumes/{volume.json()['id']}")
    res = await client.delete(f"/api/arcs/{second['id']}")
    assert res.status_code == 204
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert [arc["title"] for arc in tree["arcs"]] == ["青阳城篇"]


async def test_new_arc_goes_after_planned_arcs_and_later_arcs_plan_in_order(client, sessionmaker):
    book = await blank_book(client)
    book_id = uuid.UUID(book)
    async with sessionmaker() as session:
        session.add_all(
            [
                StoryNode(book_id=book_id, position=1, kind="opening", title="开篇"),
                StoryNode(
                    book_id=book_id,
                    position=2,
                    kind="milestone",
                    title="入城",
                    segment={"title": "第一篇", "text": "x"},
                ),
                StoryNode(book_id=book_id, position=3, kind="milestone", title="远景一", event="后来的事"),
                StoryNode(book_id=book_id, position=4, kind="milestone", title="远景二", event="更后来的事"),
                StoryNode(book_id=book_id, position=5, kind="ending", title="结局", event="大结局"),
            ]
        )
        await session.commit()
    res = await client.post(f"/api/books/{book}/arcs", json={"title": "作者的篇", "text": "作者写的"})
    assert res.status_code == 201, res.text
    nodes = (await client.get(f"/api/books/{book}/nodes")).json()
    assert [node["title"] for node in nodes] == ["开篇", "入城", "作者的篇", "远景一", "远景二", "结局"]

    far = next(node for node in nodes if node["title"] == "远景二")
    res = await client.post(f"/api/books/{book}/volumes", json={"target_node_id": far["id"]})
    assert res.status_code == 409
    near = next(node for node in nodes if node["title"] == "远景一")
    res = await client.post(f"/api/books/{book}/volumes", json={"target_node_id": near["id"]})
    assert res.status_code == 201, res.text
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    planned = [(arc["title"], arc["text"]) for arc in tree["arcs"] if arc["planned"]]
    assert planned == [("第一篇", "x"), ("作者的篇", "作者写的"), ("远景一", "后来的事")]

    ending = next(node for node in nodes if node["title"] == "结局")
    async with sessionmaker() as session:
        row = await session.get(StoryNode, uuid.UUID(ending["id"]))
        row.segment = {"title": "最后一篇", "text": ""}
        await session.commit()
    # 已经规划到结局也能再加：插在结局前面
    res = await client.post(f"/api/books/{book}/arcs", json={"title": "再加一篇"})
    assert res.status_code == 201, res.text
    nodes = (await client.get(f"/api/books/{book}/nodes")).json()
    assert [node["title"] for node in nodes][-2:] == ["再加一篇", "结局"]


async def test_writing_splits_an_author_arc_before_planning_the_next(client, sessionmaker):
    book = await blank_book(client)
    book_id = uuid.UUID(book)
    arc = (await client.post(f"/api/books/{book}/arcs", json={"title": "青阳城篇", "text": "陈默站稳脚跟。"})).json()
    async with sessionmaker() as session:
        decision = await decide(session, book_id, {"until": "book"})
        assert decision == {"step": "fill_segment", "arc_id": arc["id"]}
        # 只定下一篇时也是先给它分卷
        decision = await decide(session, book_id, {"until": "segment"})
        assert decision == {"step": "fill_segment", "arc_id": arc["id"]}

        nodes = list(await session.scalars(select(StoryNode).where(StoryNode.book_id == book_id)))
        split = {
            "volumes": [
                {"index": 1, "title": "入城", "summary": "进城", "chapter_count": 20},
                {"index": 2, "title": "立足", "summary": "立足", "chapter_count": 25},
            ],
            "threads": [],
            "anchors": [],
            "secrets": [],
        }
        view = [{"id": str(node.id), "kind": node.kind, "title": node.title} for node in nodes]
        stats = await arc_store.fill_arc(session, await session.get(Book, book_id), uuid.UUID(arc["id"]), split, view)
        await session.commit()
        assert stats["already_saved"] is False
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index)))
        assert [(v.index, v.title, v.chapter_count, str(v.target_node_id)) for v in volumes] == [
            (1, "入城", 20, arc["id"]),
            (2, "立足", 25, arc["id"]),
        ]
        assert volumes[-1].reaches_node is True
        node = await session.get(StoryNode, uuid.UUID(arc["id"]))
        assert node.segment["split"] is True and node.segment["title"] == "青阳城篇"
        decision = await decide(session, book_id, {"until": "book"})
        assert decision["step"] == "plan_volume"


async def test_writing_stops_when_an_empty_author_arc_sits_before_a_later_one(client, sessionmaker):
    book = await blank_book(client)
    book_id = uuid.UUID(book)
    await client.post(f"/api/books/{book}/arcs", json={"title": "空着的篇"})
    later = (await client.post(f"/api/books/{book}/arcs", json={"title": "后面的篇"})).json()
    await client.post(f"/api/books/{book}/volumes", json={"target_node_id": later["id"]})
    async with sessionmaker() as session:
        decision = await decide(session, book_id, {"until": "book"})
    assert decision["step"] == "done"
    assert "「空着的篇」这一篇还没有卷" in decision["reason"]


# ---------- 作者加章、章纲 ----------


async def test_author_adds_edits_and_deletes_chapters(client):
    book = await blank_book(client)
    volume = (await client.post(f"/api/books/{book}/volumes", json={"chapter_count": 6})).json()
    first_unit = (await client.post(f"/api/volumes/{volume['id']}/units", json={"chapter_count": 2})).json()
    second_unit = (
        await client.post(
            f"/api/volumes/{volume['id']}/units", json={"chapter_count": 3, "after_unit_id": first_unit["id"]}
        )
    ).json()
    res = await client.post(
        f"/api/units/{second_unit['id']}/chapters",
        json={"title": "夜路", "outline": {"goal": "陈默出城", "scenes": ["城门", " "], "hook": "身后有人"}},
    )
    assert res.status_code == 201, res.text
    # 第一个单元预留了两章，第二个单元的第一章是第 3 章
    assert res.json()["index"] == 3
    res = await client.post(f"/api/units/{first_unit['id']}/chapters", json={})
    assert res.json()["index"] == 1
    await client.post(f"/api/units/{first_unit['id']}/chapters", json={"title": "第二章"})
    res = await client.post(f"/api/units/{first_unit['id']}/chapters", json={"title": "多出来的一章"})
    assert res.json()["index"] == 3
    chapters = (await client.get(f"/api/books/{book}/chapters", params={"with_outline": True})).json()
    assert [(c["index"], c["title"]) for c in chapters] == [(1, ""), (2, "第二章"), (3, "多出来的一章"), (4, "夜路")]
    assert chapters[3]["outline"] == {"goal": "陈默出城", "scenes": ["城门"], "hook": "身后有人"}
    units = (await client.get(f"/api/books/{book}/outline")).json()["volumes"][0]["units"]
    assert [u["chapter_count"] for u in units] == [3, 3]

    res = await client.patch(
        f"/api/books/{book}/chapters/4", json={"outline": {"cool_point": "反杀", "goal": "陈默夜里出城"}}
    )
    assert res.status_code == 200, res.text
    assert res.json()["outline"] == {
        "goal": "陈默夜里出城",
        "scenes": ["城门"],
        "hook": "身后有人",
        "cool_point": "反杀",
    }

    res = await client.delete(f"/api/books/{book}/chapters/2")
    assert res.status_code == 204
    chapters = (await client.get(f"/api/books/{book}/chapters")).json()
    assert [(c["index"], c["title"]) for c in chapters] == [(1, ""), (2, "多出来的一章"), (3, "夜路")]
    assert chapters[0]["outline"] is None

    await client.patch(f"/api/books/{book}/chapters/3", json={"content": "开写了"})
    res = await client.patch(f"/api/books/{book}/chapters/3", json={"outline": {"hook": "改"}})
    assert res.status_code == 409
    res = await client.delete(f"/api/books/{book}/chapters/3")
    assert res.status_code == 409
