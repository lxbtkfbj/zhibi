"""第三包任务 4：结构修改、顺延章号、作者保护与版本。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.graphs.write_book import _next_step
from app.main import create_app
from app.models import Book, Chapter, PlotUnit, SettingVersion, StoryNode, Volume
from app.services.arc_store import fill_units
from app.services.splice import read_path, splice
from app.services.writing_store import create_chapters, unit_next_chapter_index


@pytest.fixture
async def client():
    app = create_app()
    async with Redis.from_url(get_settings().redis_url) as redis:
        app.state.redis = redis
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def make_outline(sessionmaker, *, status="planned"):
    async with sessionmaker() as session:
        book = Book(title="大纲编辑", status="ready")
        session.add(book)
        await session.flush()
        endpoint = StoryNode(book_id=book.id, position=1, kind="milestone", title="终点", event="走出旧城")
        session.add(endpoint)
        await session.flush()
        volumes = [
            Volume(
                book_id=book.id, index=i, title=f"卷{i}", chapter_count=4, status="approved", target_node_id=endpoint.id
            )
            for i in (1, 2)
        ]
        session.add_all(volumes)
        await session.flush()
        units = [
            PlotUnit(
                book_id=book.id, volume_id=v.id, index=i, title=f"{v.index}-{i}", chapter_count=2, status="outlined"
            )
            for v in volumes
            for i in (1, 2)
        ]
        session.add_all(units)
        await session.flush()
        chapters = [
            Chapter(
                book_id=book.id,
                volume_id=unit.volume_id,
                unit_id=unit.id,
                index=2 * i + n,
                title=f"第{2 * i + n}章",
                outline={"index": 2 * i + n, "goal": "保留原章纲"},
                status=status if i == 0 else "planned",
                content="作者正文" if i == 0 and status != "planned" else "",
            )
            for i, unit in enumerate(units)
            for n in (1, 2)
        ]
        session.add_all(chapters)
        await session.commit()
        return book, volumes, units, chapters, endpoint


async def indices(sessionmaker, book_id):
    async with sessionmaker() as session:
        rows = await session.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index))
        return {row.id: row.index for row in rows}


async def test_add_delete_unit_reindexes_chapters_and_versions(client, sessionmaker):
    book, volumes, units, chapters, _ = await make_outline(sessionmaker)
    added = await client.post(
        f"/api/volumes/{volumes[0].id}/units",
        json={"title": "新单元", "summary": "作者补一段剧情", "chapter_count": 3, "after_unit_id": str(units[0].id)},
    )
    assert added.status_code == 201, added.text
    new_id = uuid.UUID(added.json()["id"])
    assert added.json()["index"] == 2
    after = await indices(sessionmaker, book.id)
    assert [after[c.id] for c in chapters] == [1, 2, 6, 7, 8, 9, 10, 11]
    async with sessionmaker() as session:
        assert (await session.get(Volume, volumes[0].id)).chapter_count == 7
        for target in (volumes[0], volumes[1], units[1], units[2], units[3]):
            versions = list(await session.scalars(select(SettingVersion).where(SettingVersion.target_id == target.id)))
            assert len(versions) == 2, target.title
        version = await session.scalar(select(SettingVersion).where(SettingVersion.target_id == new_id))
        assert version.version == 1 and version.snapshot["summary"] == "作者补一段剧情"
        assert (await session.get(Chapter, chapters[2].id)).outline["index"] == 6
    deleted = await client.delete(f"/api/units/{new_id}")
    assert deleted.status_code == 204, deleted.text
    assert list((await indices(sessionmaker, book.id)).values()) == list(range(1, 9))
    assert (await client.delete(f"/api/units/{units[1].id}")).status_code == 204
    after = await indices(sessionmaker, book.id)
    assert chapters[2].id not in after and chapters[3].id not in after
    assert [after[c.id] for c in chapters[4:]] == [3, 4, 5, 6]


async def test_units_order_moves_planned_chapters_without_losing_outlines(client, sessionmaker):
    book, volumes, units, chapters, _ = await make_outline(sessionmaker)
    response = await client.post(
        f"/api/volumes/{volumes[0].id}/units/order", json={"ids": [str(units[1].id), str(units[0].id)]}
    )
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == [str(units[1].id), str(units[0].id)]
    after = await indices(sessionmaker, book.id)
    assert [after[c.id] for c in chapters] == [3, 4, 1, 2, 5, 6, 7, 8]
    for ids in ([str(units[0].id)], [str(units[0].id)] * 2, [str(units[0].id), str(units[2].id)]):
        response = await client.post(f"/api/volumes/{volumes[0].id}/units/order", json={"ids": ids})
        assert response.status_code == 422


async def test_delete_middle_of_five_units_avoids_deleted_temporary_index(client, sessionmaker):
    book, volumes, units, _, _ = await make_outline(sessionmaker)
    created = []
    for number in range(3):
        response = await client.post(
            f"/api/volumes/{volumes[0].id}/units",
            json={"title": f"追加{number}", "chapter_count": 2, "after_unit_id": str(units[0].id)},
        )
        assert response.status_code == 201, response.text
        created.append(response.json()["id"])
    response = await client.delete(f"/api/units/{created[-1]}")
    assert response.status_code == 204, response.text
    async with sessionmaker() as session:
        current = list(
            await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == volumes[0].id).order_by(PlotUnit.index))
        )
        assert [row.index for row in current] == [1, 2, 3, 4]
    assert list((await indices(sessionmaker, book.id)).values()) == [1, 2, 7, 8, 9, 10, 11, 12]


@pytest.mark.parametrize("status", ["drafting", "final"])
async def test_written_guards_are_atomic(client, sessionmaker, status):
    book, volumes, units, chapters, _ = await make_outline(sessionmaker, status=status)
    checks = [
        ("DELETE", f"/api/units/{units[0].id}", None, "这个单元已经开写了，不能删"),
        ("DELETE", f"/api/volumes/{volumes[0].id}", None, "这一卷已经开写了，不能删"),
        ("PATCH", f"/api/units/{units[0].id}", {"chapter_count": 3}, "不能改章数"),
        ("PATCH", f"/api/volumes/{volumes[0].id}", {"chapter_count": 3}, "不能改章数"),
        ("POST", f"/api/volumes/{volumes[0].id}/units", {"title": "不能插在正文前", "chapter_count": 2}, "已经开写"),
        ("POST", f"/api/books/{book.id}/volumes", {"title": "不能插在正文前", "chapter_count": 2}, "已经开写"),
        (
            "POST",
            f"/api/volumes/{volumes[0].id}/units/order",
            {"ids": [str(units[1].id), str(units[0].id)]},
            "已经开写的单元不能挪到没开写的单元后面",
        ),
    ]
    for method, path, body, detail in checks:
        response = await client.request(method, path, json=body)
        assert response.status_code == 409 and detail in response.text, response.text
    assert [*(await indices(sessionmaker, book.id)).values()] == list(range(1, 9))
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(SettingVersion)))
        assert (await session.get(Chapter, chapters[0].id)).content == "作者正文"
    # 写过的前缀不动，后面的单元仍可添加和删改。
    response = await client.post(
        f"/api/volumes/{volumes[0].id}/units",
        json={"title": "追加剧情", "chapter_count": 2, "after_unit_id": str(units[0].id)},
    )
    assert response.status_code == 201, response.text


async def test_add_delete_volume_and_foreign_references(client, sessionmaker):
    book, volumes, units, chapters, endpoint = await make_outline(sessionmaker)
    response = await client.post(
        f"/api/books/{book.id}/volumes",
        json={
            "title": "中间的一卷",
            "chapter_count": 3,
            "target_node_id": str(endpoint.id),
            "after_volume_id": str(volumes[0].id),
        },
    )
    assert response.status_code == 201, response.text
    volume = response.json()
    assert volume["index"] == 2 and volume["units"] == []
    after = await indices(sessionmaker, book.id)
    assert [after[c.id] for c in chapters] == [1, 2, 3, 4, 8, 9, 10, 11]
    response = await client.post(f"/api/volumes/{volume['id']}/units", json={"title": "空卷的第一个单元"})
    assert response.status_code == 201, response.text
    assert (await client.delete(f"/api/volumes/{volume['id']}")).status_code == 204
    assert list((await indices(sessionmaker, book.id)).values()) == list(range(1, 9))
    assert (await client.delete(f"/api/volumes/{volumes[0].id}")).status_code == 204
    after = await indices(sessionmaker, book.id)
    assert [after[c.id] for c in chapters[4:]] == [1, 2, 3, 4]
    async with sessionmaker() as session:
        assert await session.get(PlotUnit, units[0].id) is None
        assert await session.get(Chapter, chapters[0].id) is None
        assert (await session.get(Volume, volumes[1].id)).index == 1
    response = await client.post(
        f"/api/books/{book.id}/volumes", json={"title": "不正确", "target_node_id": str(uuid.uuid4())}
    )
    assert response.status_code == 422
    response = await client.post(
        f"/api/books/{book.id}/volumes", json={"title": "不正确", "after_volume_id": str(uuid.uuid4())}
    )
    assert response.status_code == 422


async def test_chapter_count_preserves_prefix_and_reserves_tail(client, sessionmaker):
    book, volumes, units, chapters, _ = await make_outline(sessionmaker)
    response = await client.patch(f"/api/units/{units[0].id}", json={"chapter_count": 3})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "planned"
    after = await indices(sessionmaker, book.id)
    assert [after[c.id] for c in chapters] == [1, 2, 4, 5, 6, 7, 8, 9]
    async with sessionmaker() as session:
        unit = await session.get(PlotUnit, units[0].id)
        assert await unit_next_chapter_index(session, book.id, unit) == 3
        rows = await create_chapters(session, book.id, unit, [{"title": "追加的一章", "goal": "新增"}])
        await session.commit()
        assert rows[0].index == 3 and unit.chapter_count == 3
        assert (await session.get(Chapter, chapters[0].id)).outline["goal"] == "保留原章纲"
    response = await client.patch(f"/api/units/{units[0].id}", json={"chapter_count": 1})
    assert response.status_code == 200, response.text
    after = await indices(sessionmaker, book.id)
    assert chapters[1].id not in after and after[chapters[0].id] == 1
    assert after[chapters[2].id] == 2
    response = await client.patch(f"/api/volumes/{volumes[0].id}", json={"chapter_count": 5})
    assert response.status_code == 200, response.text
    assert sum(u["chapter_count"] for u in response.json()["units"]) == 5
    assert (await indices(sessionmaker, book.id))[chapters[4].id] == 6


async def test_inserted_first_unit_is_planned_before_existing_later_chapters(client, sessionmaker):
    book, volumes, _, _, _ = await make_outline(sessionmaker)
    response = await client.post(f"/api/volumes/{volumes[0].id}/units", json={"title": "新的开头", "chapter_count": 2})
    assert response.status_code == 201, response.text
    new_id = uuid.UUID(response.json()["id"])
    async with sessionmaker() as session:
        book = await session.get(Book, book.id)
        decision = await _next_step(session, book, {})
        assert decision["step"] == "fill_volume"
        await fill_units(session, book.id, await session.get(Volume, volumes[0].id), [], [])
        decision = await _next_step(session, book, {})
        assert decision["step"] == "plan_chapters" and decision["unit_id"] == str(new_id)
        unit = await session.get(PlotUnit, new_id)
        assert await unit_next_chapter_index(session, book.id, unit) == 1
        rows = await create_chapters(session, book.id, unit, [{"title": "新1"}, {"title": "新2"}])
        await session.commit()
        assert [c.index for c in rows] == [1, 2]
        decision = await _next_step(session, book, {})
        assert decision["step"] == "write" and decision["chapter_index"] == 1


@pytest.mark.parametrize("old_text", ["", "  \n\t　"])
def test_legacy_arc_rewrite_uses_displayed_endpoint_without_changing_it(old_text):
    node = StoryNode(title="旧篇", event="主角走出旧城，第一次看见大海。", segment={"number": 1, "text": old_text})
    assert read_path(node, "text@2:6") == "走出旧城"
    before, after = splice(node, "text@2:6", "离开故乡", base="走出旧城")
    assert before == node.event == "主角走出旧城，第一次看见大海。"
    assert after == node.segment["text"] == "主角离开故乡，第一次看见大海。"
    assert node.segment["number"] == 1


def test_nonempty_arc_text_keeps_original_character_offsets_and_whitespace():
    node = StoryNode(title="篇", event="不能采用终点", segment={"text": "  第一行。\n第二行。　"})
    assert read_path(node, "text") == "  第一行。\n第二行。　"
    assert read_path(node, "text@2:5") == "第一行"
    _, after = splice(node, "text@2:5", "换一行", base="第一行")
    assert after == "  换一行。\n第二行。　"


async def test_reverting_chapter_count_reflows_following_chapters(client, sessionmaker):
    book, _, units, chapters, _ = await make_outline(sessionmaker)
    assert (await client.patch(f"/api/units/{units[0].id}", json={"chapter_count": 3})).status_code == 200
    versions = (
        await client.get(
            f"/api/books/{book.id}/versions", params={"target_type": "unit", "target_id": str(units[0].id)}
        )
    ).json()
    response = await client.post(f"/api/versions/{versions[-1]['id']}/revert")
    assert response.status_code == 200, response.text
    assert response.json()["chapter_count"] == 2
    assert [*(await indices(sessionmaker, book.id)).values()] == list(range(1, 9))
    async with sessionmaker() as session:
        chapter = await session.get(Chapter, chapters[0].id)
        chapter.status = "drafting"
        await session.commit()
    response = await client.post(f"/api/versions/{versions[0]['id']}/revert")
    assert response.status_code == 409 and "已经开写" in response.text


async def test_concept_genre_keeps_library_context_and_revert_in_sync(client, sessionmaker):
    book, *_ = await make_outline(sessionmaker)
    response = await client.patch(f"/api/books/{book.id}", json={"concept": {"genre": "都市悬疑"}})
    assert response.status_code == 200 and response.json()["genre"] == "都市悬疑"
    response = await client.patch(f"/api/books/{book.id}", json={"concept": {"genre": None}})
    assert response.status_code == 422
    assert (await client.get(f"/api/books/{book.id}")).json()["genre"] == "都市悬疑"
