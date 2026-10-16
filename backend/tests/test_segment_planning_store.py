"""第二包任务 1：新字段只做加法，旧方案与写作卷纲不会清掉作者数据。"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app.models import Book, Character, PlotUnit, StoryNode, Volume
from app.services.setup_store import load_nodes, load_setup, save_nodes, save_piece, save_setup
from app.services.writing_context import _char_dict
from app.services.writing_store import save_volume_plan


async def seed(session):
    book = Book(protagonist={"name": "林岚", "pursuit": "找回妹妹"}, world={"surface": "超凡藏在暗处"})
    session.add(book)
    await session.flush()
    await save_setup(
        session,
        book.id,
        {
            "concept": {"title": "归途"},
            "spine": {
                "nodes": [
                    {"kind": "opening", "title": "失踪"},
                    {
                        "kind": "milestone",
                        "title": "找到线索",
                        "segment": {
                            "number": 1,
                            "status": "confirmed",
                            "planned_at": 0,
                            "goal": "找到妹妹留下的信",
                            "opening": {"scene": "回家发现门锁被撬", "pressure": "被催债"},
                            "finale": False,
                        },
                    },
                    {"kind": "ending", "title": "团圆"},
                ]
            },
            "lore": {"characters": [{"name": "林岚", "goal": "找回妹妹", "want": "先找到城里的线人"}]},
            "outline": {
                "volumes": [
                    {
                        "index": 1,
                        "title": "入城",
                        "want": "找到妹妹留下的信",
                        "pressure": "盘缠只够三天",
                        "target_node": 2,
                    }
                ]
            },
            "first_volume": {"units": [{"index": 1, "title": "接委托", "loop": "接案、查案、得到新线索"}]},
        },
    )
    await session.flush()
    return book


async def test_setup_roundtrip_preserves_new_fields_ids_and_existing_shape(sessionmaker):
    async with sessionmaker() as session:
        book = await seed(session)
        character = await session.scalar(select(Character).where(Character.book_id == book.id))
        character.aliases, character.notes, character.is_alive = ["小岚"], "作者备注", False
        identities = {
            model: list(await session.scalars(select(model.id).where(model.book_id == book.id).order_by(model.id)))
            for model in (StoryNode, Character, Volume, PlotUnit)
        }
        original = deepcopy(await load_setup(session, book.id))
        assert set(original) == {"concept", "spine", "lore", "threads", "outline", "first_volume"}
        await save_setup(session, book.id, original)
        await session.commit()
        assert await load_setup(session, book.id) == original
        assert book.protagonist == {"name": "林岚", "pursuit": "找回妹妹"}
        assert book.world == {"surface": "超凡藏在暗处"}
        assert (character.aliases, character.notes, character.is_alive) == (["小岚"], "作者备注", False)
        for model, ids in identities.items():
            assert (
                list(await session.scalars(select(model.id).where(model.book_id == book.id).order_by(model.id))) == ids
            )
        assert _char_dict(character)["want"] == "先找到城里的线人"


@pytest.mark.parametrize("missing", [True, False])
@pytest.mark.parametrize("whole_setup", [True, False])
async def test_setup_missing_or_null_text_fields_preserve_existing_values(sessionmaker, missing, whole_setup):
    async with sessionmaker() as session:
        book = await seed(session)
        original = deepcopy(await load_setup(session, book.id))
        payload = deepcopy(original)
        for item, fields in (
            (payload["lore"]["characters"][0], ("want",)),
            (payload["outline"]["volumes"][0], ("want", "pressure")),
            (payload["first_volume"]["units"][0], ("loop",)),
        ):
            for field in fields:
                if missing:
                    item.pop(field)
                else:
                    item[field] = None
        for node in payload["spine"]["nodes"]:
            node.pop("segment")
        if whole_setup:
            await save_setup(session, book.id, payload)
        else:
            for piece in ("nodes", "cast", "fill", "first_volume"):
                await save_piece(session, book.id, piece, payload)
        await session.commit()
        assert await load_setup(session, book.id) == original


async def test_setup_empty_text_fields_explicitly_clear_values(sessionmaker):
    async with sessionmaker() as session:
        book = await seed(session)
        payload = await load_setup(session, book.id)
        payload["lore"]["characters"][0]["want"] = ""
        payload["outline"]["volumes"][0].update(want="", pressure="")
        payload["first_volume"]["units"][0]["loop"] = ""
        await save_setup(session, book.id, payload)
        await session.commit()
        loaded = await load_setup(session, book.id)
        assert loaded["lore"]["characters"][0]["want"] == ""
        assert loaded["outline"]["volumes"][0]["want"] == ""
        assert loaded["outline"]["volumes"][0]["pressure"] == ""
        assert loaded["first_volume"]["units"][0]["loop"] == ""


async def test_node_segment_missing_preserves_and_null_clears_sql_value(sessionmaker):
    async with sessionmaker() as session:
        book = await seed(session)
        nodes = deepcopy(await load_nodes(session, book.id))
        original = deepcopy(nodes[1]["segment"])
        assert nodes[0]["segment"] is None and nodes[-1]["segment"] is None
        nodes[1].pop("segment")
        await save_nodes(session, book.id, nodes)
        await session.commit()
        nodes = deepcopy(await load_nodes(session, book.id))
        assert nodes[1]["segment"] == original
        nodes[1]["segment"] = None
        await save_nodes(session, book.id, nodes)
        await session.commit()
        assert (await load_nodes(session, book.id))[1]["segment"] is None
        assert await session.scalar(
            select(StoryNode.segment.is_(None)).where(StoryNode.book_id == book.id, StoryNode.position == 2)
        )


@pytest.mark.parametrize("loop", [None, "", "查案后救人，再得到新线索"])
async def test_writing_volume_plan_preserves_missing_loop_and_supports_updates(sessionmaker, loop):
    async with sessionmaker() as session:
        book = await seed(session)
        volume = await session.scalar(select(Volume).where(Volume.book_id == book.id))
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.book_id == book.id))
        original_id, original_loop = unit.id, unit.loop
        payload = {"index": 1, "title": "新的单元名称"}
        await save_volume_plan(session, book.id, volume, [payload], [], replace_new=False)
        assert unit.id == original_id and unit.loop == original_loop
        await save_volume_plan(session, book.id, volume, [{**payload, "loop": loop}], [], replace_new=False)
        await session.commit()
        assert unit.loop == (original_loop if loop is None else loop)
        assert (volume.want, volume.pressure) == ("找到妹妹留下的信", "盘缠只够三天")
