"""第三包只读树、原有编辑入口记版本和旧流程设定兼容。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents.context import format_lore, format_world
from app.config import get_settings
from app.main import create_app
from app.models import Book, Chapter, PlotUnit, SettingVersion, StoryNode, Volume, WorldEntry
from app.services.setup_store import _save_world, load_setup
from app.services.writing_context import ALL_WORLD_UNDER, world_text


@pytest.fixture
async def client():
    app = create_app()
    async with Redis.from_url(get_settings().redis_url) as redis:
        app.state.redis = redis
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def test_outline_tree_four_states_legacy_and_read_only(client, sessionmaker):
    async with sessionmaker() as session:
        book, old = Book(title="四种篇", status="writing"), Book(title="旧书", status="ready")
        session.add_all([book, old])
        await session.flush()
        nodes = [
            StoryNode(
                book_id=book.id,
                position=i,
                kind="opening" if i == 0 else "ending" if i == 4 else "milestone",
                title=f"节点{i}",
                event=f"事件{i}",
                status="pinned" if i == 1 else "pencil",
                segment={"title": f"第{i}篇", "text": f"篇文{i}"} if 0 < i < 4 else None,
            )
            for i in range(5)
        ]
        session.add_all(nodes)
        await session.flush()
        volumes = [
            Volume(book_id=book.id, index=i, title=f"卷{i}", target_node_id=nodes[i].id, chapter_count=99)
            for i in range(1, 4)
        ]
        legacy_volume = Volume(book_id=old.id, index=1, title="旧卷", chapter_count=2)
        session.add_all([*volumes, legacy_volume])
        await session.flush()
        units = [
            PlotUnit(
                book_id=book.id,
                volume_id=v.id,
                index=1,
                title="单元",
                summary="一段话",
                chapter_count=2,
                status="done" if i == 0 else "outlined",
                locked=True,
            )
            for i, v in enumerate(volumes)
        ]
        session.add_all(units)
        await session.flush()
        for index, (volume_index, status) in enumerate([(0, "final"), (0, "final"), (1, "drafting")], 1):
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volumes[volume_index].id,
                    unit_id=units[volume_index].id,
                    index=index,
                    title=f"章{index}",
                    status=status,
                )
            )
        await session.commit()
        bid, old_id = book.id, old.id
        untouched = [(node.id, node.updated_at, node.segment) for node in nodes]
    data = (await client.get(f"/api/books/{bid}/outline-tree")).json()
    assert data["segmented"] is True
    assert [arc["status"] for arc in data["arcs"]] == ["done", "writing", "planned", "later"]
    assert [arc["planned"] for arc in data["arcs"]] == [True, True, True, False]
    assert data["arcs"][0]["locked"] is True
    assert data["arcs"][0]["title"] == "第1篇"
    assert data["arcs"][-1]["text"] == "事件4"
    assert data["ending"]["title"] == "节点4"
    first_unit = data["arcs"][0]["volumes"][0]["units"][0]
    assert (first_unit["summary"], first_unit["locked"], first_unit["status"]) == ("一段话", True, "done")
    assert [c["index"] for c in first_unit["chapters"]] == [1, 2]
    old_data = (await client.get(f"/api/books/{old_id}/outline-tree")).json()
    assert old_data["segmented"] is False and old_data["arcs"][0]["title"] == "全书"
    assert old_data["arcs"][0]["volumes"][0]["title"] == "旧卷"
    async with sessionmaker() as session:
        now = list(
            await session.scalars(select(StoryNode).where(StoryNode.book_id == bid).order_by(StoryNode.position))
        )
        assert [(node.id, node.updated_at, node.segment) for node in now] == untouched
        assert not list(await session.scalars(select(SettingVersion)))
        # 第二包规则：保留 done 的旧卷正在重写时，不准显示完成。
        volume = await session.get(Volume, volumes[1].id)
        volume.status = "done"
        await session.commit()
    assert (await client.get(f"/api/books/{bid}/outline-tree")).json()["arcs"][1]["status"] == "writing"


async def test_existing_outline_and_concept_patches_record_complete_versions(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="定调", concept={"title": "定调", "story": "原故事", "legacy": "原字段"}, status="ready")
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="卷", want="原目标", pressure="原压力")
        node = StoryNode(
            book_id=book.id,
            position=2,
            kind="milestone",
            title="节点",
            event="节点事件",
            segment={"number": 1, "map": "旧地图", "status": "confirmed"},
        )
        session.add_all([volume, node])
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="单元", loop="原循环")
        session.add(unit)
        await session.commit()
    edits = [
        (
            "concept",
            book.id,
            f"/books/{book.id}",
            {"concept": {"story": "新故事", "pitches": [], "secret_entry_id": None}},
        ),
        ("volume", volume.id, f"/volumes/{volume.id}", {"summary": "卷段落", "locked": True}),
        ("unit", unit.id, f"/units/{unit.id}", {"summary": "单元段落", "locked": True}),
        (
            "segment",
            node.id,
            f"/nodes/{node.id}",
            {"segment": {"title": "新篇名", "text": "篇段落"}, "status": "pinned"},
        ),
    ]
    for kind, target_id, path, body in edits:
        response = await client.patch("/api" + path, json=body)
        assert response.status_code == 200, response.text
        versions = (
            await client.get(
                f"/api/books/{book.id}/versions", params={"target_type": kind, "target_id": str(target_id)}
            )
        ).json()
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[1]["note"] == "初版"
        response = await client.post(f"/api/versions/{versions[1]['id']}/revert")
        assert response.status_code == 200, response.text
        async with sessionmaker() as session:
            stored = list(
                await session.scalars(
                    select(SettingVersion).where(SettingVersion.target_id == target_id).order_by(SettingVersion.version)
                )
            )
            assert len(stored) == 3 and stored[2].snapshot == stored[0].snapshot
            assert stored[2].source == "revert"


async def test_legacy_world_normalization_and_structured_context(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="旧开书", status="ready")
        session.add(book)
        await session.flush()
        await _save_world(
            session,
            book,
            {
                "world_entries": [
                    {"category": "力量体系", "name": "境界", "content": "总说明"},
                    {"category": "地理", "name": "地图", "content": "地理内容"},
                    {"category": "未知", "name": "规矩", "content": "未知内容"},
                ]
            },
        )
        rows = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id)))
        by_name = {row.name: row for row in rows}
        assert (by_name["境界"].category, by_name["境界"].style) == ("等级体系", "ladder")
        assert by_name["地图"].category == "世界与地图"
        assert by_name["规矩"].category == "特殊规则"
        by_name["境界"].levels = [{"name": "筑基", "text": "初成"}, {"name": "金丹", "text": ""}]
        await session.commit()
        setup = await load_setup(session, book.id)
        assert "筑基：初成\n金丹" in format_world(setup["world"])
    entries = [
        {
            "category": "等级体系",
            "style": "ladder",
            "name": "境界",
            "content": "总说明",
            "levels": [{"name": "筑基", "text": "初成"}, {"name": "金丹", "text": ""}],
        },
        {
            "category": "custom:ghost",
            "style": "card",
            "name": "厉鬼",
            "content": "简介",
            "fields": [{"name": "规律", "value": "回头"}, {"name": "空项", "value": ""}],
        },
    ]
    for rendered in (format_world({"world_entries": entries}), format_lore({"world_entries": entries})):
        assert "筑基：初成\n金丹" in rendered and "规律：回头" in rendered and "空项：" not in rendered
    rows = [WorldEntry(category="世界与地图", name=f"地点{i}", content="其它") for i in range(ALL_WORLD_UNDER + 1)]
    rows += [WorldEntry(**entries[0]), WorldEntry(category="特殊规则", name="代价", content="规则")]
    selected = world_text(rows, "")
    assert "境界" in selected and "代价" in selected and "地点" not in selected and "筑基：初成" in selected


async def test_world_save_roundtrip_keeps_same_name_in_different_categories(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="同名跨类", status="ready")
        session.add(book)
        await session.flush()
        entries = [
            WorldEntry(book_id=book.id, category="世界与地图", name="青山", content="山峰", source="migration"),
            WorldEntry(book_id=book.id, category="势力划分", name="青山", content="宗门", source="author"),
            WorldEntry(book_id=book.id, category="特殊规则", name="旧分类", content="原内容"),
        ]
        session.add_all(entries)
        await session.commit()
        original = [(entry.id, entry.category, entry.name, entry.content, entry.source) for entry in entries]
        setup = await load_setup(session, book.id)
        await _save_world(session, book, setup["world"])
        await session.commit()
        current = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id)))
        assert sorted(
            [(entry.id, entry.category, entry.name, entry.content, entry.source) for entry in current]
        ) == sorted(original)
        # 原来只有一条同名时仍允许换类，稳定 ID 不变。
        next(entry for entry in setup["world"]["world_entries"] if entry["name"] == "旧分类")["category"] = "物品"
        await _save_world(session, book, setup["world"])
        await session.commit()
        await session.refresh(entries[-1])
        assert entries[-1].category == "物品与功法" and entries[-1].id == original[-1][0]


async def test_revert_legacy_concept_with_empty_title_keeps_display_title(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="保留显示书名", status="ready", concept={"title": "", "story": "旧文"})
        session.add(book)
        await session.commit()
    response = await client.patch(f"/api/books/{book.id}", json={"concept": {"story": "新文"}})
    assert response.status_code == 200
    versions = (
        await client.get(f"/api/books/{book.id}/versions", params={"target_type": "concept", "target_id": str(book.id)})
    ).json()
    response = await client.post(f"/api/versions/{versions[-1]['id']}/revert")
    assert response.status_code == 200, response.text
    assert response.json()["concept"] == {"title": "", "story": "旧文"}
    assert (await client.get(f"/api/books/{book.id}")).json()["title"] == "保留显示书名"
