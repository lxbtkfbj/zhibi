"""新五步存储：稳定 ID、旧书读取、分块边界与台账往返。"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app.agents.glossary import terms
from app.models import Book, Character, Foreshadowing, NodeAnchor, PlotUnit, Secret, StoryNode, Volume
from app.services.setup_store import (
    assign_seqs,
    ledger_of,
    load_nodes,
    load_setup,
    merge_legacy_spine,
    remap_node_refs,
    save_nodes,
    save_piece,
    save_setup,
    spine_from_legacy,
)


def sample_setup():
    technique = terms()[0][0]
    legacy = {
        "concept": {"title": "测试开书", "genre": "玄幻"},
        "spine": {
            "core_conflict": "明暗身份冲突",
            "theme": "选择",
            "protagonist_arc": "学会承担",
            "nodes": [
                {"kind": "opening", "title": "开篇", "event": "入城", "volume": 1},
                {
                    "kind": "milestone",
                    "title": "身份揭晓",
                    "event": "当众亮牌",
                    "volume": 2,
                    "status": "pinned",
                    "origin": "author",
                    "prerequisite": "找齐证据",
                    "consequence": "离城",
                    "editor_note": "先压后扬",
                    "techniques": [technique, "表外技巧", technique],
                },
                {"kind": "ending", "title": "结局", "event": "回家"},
            ],
        },
        "lore": {
            "characters": [{"name": "林岚", "goal": "回家"}, {"name": "赵青"}],
            "world_entries": [{"name": "青城", "category": "地理", "content": "故事舞台"}],
            "relationships": [{"source": "林岚", "target": "赵青", "kind": "朋友", "description": "相识"}],
            "anchors": [
                {"character": "林岚", "node": 2, "kind": "高光", "note": "亮牌"},
                {"character": "不存在", "node": 2, "kind": "登场"},
                {"character": "赵青", "node": 90, "kind": "登场"},
            ],
            "secrets": [
                {
                    "title": "身份",
                    "truth": "皇族后裔",
                    "reader_knows": "知道",
                    "node": 2,
                    "reveal_plan": "对质",
                    "knowers": [
                        {"name": "林岚", "since_chapter": None, "how": "开书设定"},
                        {"name": "不存在", "since_chapter": 3, "how": "误报"},
                    ],
                }
            ],
        },
        "threads": {"threads": [{"name": "归途", "kind": "主线"}]},
        "outline": {
            "volumes": [
                {
                    "index": 1,
                    "title": "入城",
                    "target_node": 2,
                    "reaches_node": False,
                    "editor_note": "铺垫",
                    "techniques": [technique],
                },
                {"index": 2, "title": "亮牌", "target_node": 2, "reaches_node": True},
            ],
            "foreshadowings": [{"description": "旧玉佩", "node": 2}],
            "expectations": [{"description": "找到亲人", "node": 3}],
        },
        "first_volume": {
            "units": [
                {
                    "index": 1,
                    "title": "进城",
                    "reveals": [{"ref": "S1", "to": "赵青", "how": "偷听"}],
                    "editor_note": "先埋疑问",
                    "techniques": [technique],
                }
            ],
            "new_foreshadowings": [{"description": "遗失的信", "span": "短"}],
            "new_expectations": [{"description": "赢下比试", "span": "中"}],
        },
    }

    return {
        "concept": legacy["concept"],
        "protagonist": {"name": "林岚", "pursuit": "找到亲人"},
        "world": {
            **{key: value for key, value in legacy["lore"].items() if key not in {"secrets", "anchors"}},
            "maps": [{"name": "青城"}],
            "mystery_answer": "作者已经定下的谜底",
        },
        "segment": {
            **legacy["spine"],
            "secrets": legacy["lore"]["secrets"],
            "foreshadowings": legacy["outline"]["foreshadowings"],
            "expectations": legacy["outline"]["expectations"],
        },
        "volumes": {
            "volumes": legacy["outline"]["volumes"],
            "threads": legacy["threads"]["threads"],
            "anchors": legacy["lore"]["anchors"],
        },
        "first_volume": {**legacy["first_volume"], "want": "进城寻找线人", "pressure": "通缉令贴满城门"},
    }


@pytest.mark.parametrize(
    ("legacy", "kinds"),
    [
        ({}, []),
        ({"opening": "开始"}, ["opening"]),
        ({"ending": "收尾"}, ["ending"]),
        ({"milestones": [{"title": "转折"}]}, ["milestone"]),
    ],
)
def test_legacy_spine_missing_boundaries(legacy, kinds):
    result = spine_from_legacy({"theme": "初心", **legacy})
    assert result["theme"] == "初心"
    assert [item["kind"] for item in result["nodes"]] == kinds
    assert not {"opening", "milestones", "ending"} & result.keys()
    assert spine_from_legacy(result) == result


def test_legacy_spine_sort_and_fields():
    result = spine_from_legacy(
        {
            "opening": "开始",
            "ending": "结束",
            "milestones": [
                {"index": 2, "title": "二", "event": "事二", "change": "变二", "volume": 3},
                {"index": 1, "title": "一", "event": "事一", "change": "变一", "volume": 2},
            ],
        }
    )
    assert [item["title"] for item in result["nodes"]] == ["开篇", "一", "二", "结局"]
    assert result["nodes"][1]["consequence"] == "变一"
    assert all(item["status"] == "pencil" and item["origin"] == "ai" for item in result["nodes"])


def test_ledger_number_space():
    items = ledger_of(sample_setup())
    assert [(item["seq"], item["kind"]) for item in items] == [(1, "伏笔"), (2, "期待"), (3, "伏笔"), (4, "期待")]
    assert assign_seqs([{"description": "新"}, {"seq": 2, "description": "保留"}], [])[0]["seq"] == 3
    assert (
        assign_seqs([{"description": "相同", "kind": "期待"}], [{"seq": 8, "kind": "期待", "description": "相同"}])[0][
            "seq"
        ]
        == 8
    )


@pytest.mark.parametrize("titles", [["转折丙", "新转折", "转折乙", "转折甲"], ["转折乙"], ["改过的名称", "转折乙"], []])
def test_legacy_merge_restores_pinned_content_and_original_positions(titles):
    previous = [
        {"id": "open", "kind": "opening", "title": "开篇", "event": "作者开篇", "status": "pinned"},
        {"id": "a", "kind": "milestone", "title": "转折甲", "event": "作者甲", "status": "pinned"},
        {"id": "b", "kind": "milestone", "title": "转折乙", "event": "暂定乙", "status": "pencil"},
        {"id": "c", "kind": "milestone", "title": "转折丙", "event": "作者丙", "status": "pinned"},
        {"id": "end", "kind": "ending", "title": "结局", "event": "作者结局", "status": "pinned"},
    ]
    old = {
        "milestones": [
            {"index": index, "title": title, "event": "AI 想改", "volume": 2} for index, title in enumerate(titles, 1)
        ]
    }
    saved_old, saved_previous = deepcopy(old), deepcopy(previous)
    merged = merge_legacy_spine(old, previous)["nodes"]
    assert old == saved_old and previous == saved_previous
    assert merged[0]["id"] == "open" and merged[-1]["id"] == "end"
    assert merged[1]["id"] == "a"
    assert merged[min(3, len(merged) - 2)]["id"] == "c"
    for id_, event in (("a", "作者甲"), ("c", "作者丙"), ("open", "作者开篇"), ("end", "作者结局")):
        assert next(item for item in merged if item["id"] == id_)["event"] == event


def test_reference_remap_ignores_unassigned_ids():
    setup = {
        "segment": {"secrets": [{"node": 1}, {"node": 2}, {"node": 3}]},
        "volumes": {"anchors": [{"node": 2, "node_title": "旧名称"}]},
    }
    original = deepcopy(setup)
    previous = [{"id": None}, {"id": "kept"}, {"id": "deleted"}]
    current = [{"id": None}, {"id": None}, {"id": "kept", "title": "新名称"}]
    remapped = remap_node_refs(setup, previous, current)
    assert remapped["segment"]["secrets"] == [{"node": 0}, {"node": 3}, {"node": 0}]
    assert remapped["volumes"]["anchors"] == [{"node": 3, "node_title": "新名称"}]
    assert setup == original


async def test_roundtrip_preserves_ids_author_fields_and_four_groups(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        result = await save_setup(session, book.id, sample_setup())
        assert result == {"dropped_anchors": 2, "dropped_knowers": 1}
        original = await load_setup(session, book.id)
        assert len(original["segment"]["nodes"][1]["techniques"]) == 1
        assert "nodes" not in book.spine and "opening" not in book.spine
        character = await session.scalar(
            select(Character).where(Character.book_id == book.id, Character.name == "林岚")
        )
        character.aliases, character.notes, character.is_alive = ["小岚"], "作者备注", False
        volume = await session.scalar(select(Volume).where(Volume.book_id == book.id, Volume.index == 1))
        volume.status = "approved"
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.book_id == book.id))
        unit.status, unit.recap, unit.plan_issues = "done", "已有单元回顾", ["保留的计划提醒"]
        ledger = await session.scalar(
            select(Foreshadowing).where(Foreshadowing.book_id == book.id, Foreshadowing.seq == 2)
        )
        ledger.status, ledger.planted_chapter, ledger.hint_chapters = "planted", 1, [3]
        await session.flush()
        original = await load_setup(session, book.id)
        ids = {
            model: list((await session.scalars(select(model.id).where(model.book_id == book.id))).all())
            for model in (StoryNode, Character, NodeAnchor, Secret, Volume, Foreshadowing)
        }
        assert await save_setup(session, book.id, original) == {"dropped_anchors": 0, "dropped_knowers": 0}
        assert await load_setup(session, book.id) == original
        for model, expected in ids.items():
            assert set((await session.scalars(select(model.id).where(model.book_id == book.id))).all()) == set(expected)
        assert character.aliases == ["小岚"] and character.notes == "作者备注" and not character.is_alive
        assert volume.status == "approved"
        assert unit.status == "done" and unit.recap == "已有单元回顾" and unit.plan_issues == ["保留的计划提醒"]
        assert ledger.status == "planted" and ledger.planted_chapter == 1 and ledger.hint_chapters == [3]
        assert original["segment"]["foreshadowings"][0]["seq"] == 1
        assert original["segment"]["expectations"][0]["seq"] == 2
        assert original["first_volume"]["new_foreshadowings"][0]["seq"] == 3
        assert original["first_volume"]["new_expectations"][0]["seq"] == 4
        assert original["volumes"]["volumes"][0]["target_node"] == 2
        assert original["segment"]["secrets"][0]["node"] == 2


async def test_nodes_reorder_constraints_deletion_and_id_update(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        nodes = await load_nodes(session, book.id)
        for bad in ([nodes[1], nodes[0], nodes[2]], [nodes[0], nodes[2], nodes[1]], [nodes[0], nodes[0]]):
            with pytest.raises(ValueError):
                await save_nodes(session, book.id, bad)
        nodes[1]["title"] = "作者新名称"
        await save_nodes(session, book.id, nodes)
        assert (await load_nodes(session, book.id))[1]["id"] == nodes[1]["id"]
        assert (await load_nodes(session, book.id))[1]["title"] == "作者新名称"
        # 删除前故意加载引用对象，验证同一 Session 不会读到 SET NULL 之前的旧 ID。
        volume = await session.scalar(select(Volume).where(Volume.book_id == book.id, Volume.index == 1))
        secret = await session.scalar(select(Secret).where(Secret.book_id == book.id))
        ledger = await session.scalar(
            select(Foreshadowing).where(Foreshadowing.book_id == book.id, Foreshadowing.seq == 1)
        )
        await save_nodes(session, book.id, [nodes[0], nodes[2]])
        assert volume.target_node_id is None and secret.node_id is None and ledger.node_id is None
        saved = await load_setup(session, book.id)
        assert saved["volumes"]["volumes"][0]["target_node"] == 0
        await save_setup(session, book.id, saved)
        await session.commit()
        book_id = book.id
    async with sessionmaker() as session:
        assert [
            n.position
            for n in await session.scalars(
                select(StoryNode).where(StoryNode.book_id == book_id).order_by(StoryNode.position)
            )
        ] == [1, 2]
        assert not list(await session.scalars(select(NodeAnchor).where(NodeAnchor.book_id == book_id)))
        assert all(
            row.target_node_id is None for row in await session.scalars(select(Volume).where(Volume.book_id == book_id))
        )
        assert (await session.scalar(select(Secret).where(Secret.book_id == book_id))).node_id is None
        assert (
            await session.scalar(select(Foreshadowing).where(Foreshadowing.book_id == book_id, Foreshadowing.seq == 1))
        ).node_id is None


async def test_save_piece_changes_only_selected_block(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        before = await load_setup(session, book.id)
        await save_piece(session, book.id, "concept", {"concept": {"title": "只改标题"}})
        after = await load_setup(session, book.id)
        assert after["concept"] == {"title": "只改标题"}
        for key in set(before) - {"concept"}:
            assert after[key] == before[key]
        first = deepcopy(before["first_volume"])
        first["new_expectations"].append({"description": "新期待"})
        await save_piece(session, book.id, "first_volume", {"first_volume": first})
        current = await load_setup(session, book.id)
        assert current["segment"] == before["segment"]
        assert current["volumes"] == before["volumes"]
        assert [item["seq"] for item in current["first_volume"]["new_expectations"]] == [4, 5]
        await save_piece(session, book.id, "segment", {"segment": before["segment"], "volumes": before["volumes"]})
        assert (await load_setup(session, book.id))["first_volume"] == current["first_volume"]
        with pytest.raises(ValueError, match="未知"):
            await save_piece(session, book.id, "invalid", {})


async def test_reorder_remaps_snapshot_numbers_without_retargeting_ids(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        nodes = await load_nodes(session, book.id)
        await save_nodes(session, book.id, [nodes[0], {"kind": "milestone", "title": "新增转折"}, nodes[1], nodes[2]])
        snapshot = await load_setup(session, book.id)
        assert snapshot["volumes"]["anchors"][0]["node"] == 3
        assert snapshot["volumes"]["anchors"][0]["node_title"] == "身份揭晓"
        assert snapshot["segment"]["secrets"][0]["node"] == 3
        assert snapshot["volumes"]["volumes"][0]["target_node"] == 3
        assert snapshot["segment"]["foreshadowings"][0]["node"] == 3
        await save_setup(session, book.id, snapshot)
        assert await load_setup(session, book.id) == snapshot


@pytest.mark.parametrize("key", ["spine", "lore", "outline", "threads"])
async def test_legacy_setup_shape_is_rejected_without_mutation(sessionmaker, key):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        before = await load_setup(session, book.id)
        with pytest.raises(ValueError, match="按新流程重开"):
            await save_setup(session, book.id, {**before, key: {}})
        assert await load_setup(session, book.id) == before


async def test_world_and_protagonist_piece_boundaries(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        before = await load_setup(session, book.id)
        await save_piece(
            session, book.id, "protagonist", {"protagonist": {"name": "林岚", "pursuit": "找到失散的家人"}}
        )
        after = await load_setup(session, book.id)
        assert after["protagonist"]["pursuit"] == "找到失散的家人"
        for key in set(before) - {"protagonist"}:
            assert after[key] == before[key]
        world = deepcopy(after["world"])
        world["opponent"] = "城主想独占线索"
        await save_piece(session, book.id, "world", {"world": world})
        current = await load_setup(session, book.id)
        assert current["world"]["opponent"] == "城主想独占线索"
        for key in set(after) - {"world"}:
            assert current[key] == after[key]
