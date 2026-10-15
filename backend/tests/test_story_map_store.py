"""第一包数据底座：稳定 ID、旧检查点、分块边界与台账往返。"""

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
    return {
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
        "lore": {"secrets": [{"node": 1}, {"node": 2}, {"node": 3}], "anchors": [{"node": 2, "node_title": "旧名称"}]}
    }
    original = deepcopy(setup)
    previous = [{"id": None}, {"id": "kept"}, {"id": "deleted"}]
    current = [{"id": None}, {"id": None}, {"id": "kept", "title": "新名称"}]
    remapped = remap_node_refs(setup, previous, current)
    assert remapped["lore"]["secrets"] == [{"node": 0}, {"node": 3}, {"node": 0}]
    assert remapped["lore"]["anchors"] == [{"node": 3, "node_title": "新名称"}]
    assert setup == original


async def test_roundtrip_preserves_ids_author_fields_and_four_groups(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        result = await save_setup(session, book.id, sample_setup())
        assert result == {"dropped_anchors": 2, "dropped_knowers": 1}
        original = await load_setup(session, book.id)
        assert len(original["spine"]["nodes"][1]["techniques"]) == 1
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
        assert original["outline"]["foreshadowings"][0]["seq"] == 1
        assert original["outline"]["expectations"][0]["seq"] == 2
        assert original["first_volume"]["new_foreshadowings"][0]["seq"] == 3
        assert original["first_volume"]["new_expectations"][0]["seq"] == 4
        assert original["outline"]["volumes"][0]["target_node"] == 2
        assert original["lore"]["secrets"][0]["node"] == 2


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
        assert saved["outline"]["volumes"][0]["target_node"] == 0
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


async def test_legacy_resave_keeps_node_ids_and_converts_character_secrets(sessionmaker):
    setup = sample_setup()
    setup["spine"] = {
        "opening": "入城",
        "ending": "回家",
        "milestones": [
            {"index": 1, "title": "身份揭晓", "event": "当众亮牌", "volume": 2, "change": "离城"},
        ],
    }
    setup["lore"]["secrets"] = []
    setup["lore"]["characters"][0]["secrets"] = ["身份其实是皇族。", "", "  "]
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, setup)
        first = await load_setup(session, book.id)
        await save_setup(session, book.id, setup)
        assert await load_setup(session, book.id) == first
        assert "secrets" not in first["lore"]["characters"][0]
        assert first["lore"]["secrets"][0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
        node = await session.scalar(
            select(StoryNode).where(StoryNode.book_id == book.id, StoryNode.kind == "milestone")
        )
        node.prerequisite, node.editor_note, node.origin = "作者补充的前提", "作者批注", "author"
        node_id = str(node.id)
        await session.flush()
        setup["spine"]["milestones"].insert(0, {"index": 0, "title": "新增转折", "event": "准备", "volume": 1})
        await save_setup(session, book.id, setup)
        current = await load_nodes(session, book.id)
        assert current[2]["id"] == node_id
        assert node.prerequisite == "作者补充的前提" and node.editor_note == "作者批注" and node.origin == "author"
        node.status, node.event = "pinned", "作者钉死的事件"
        await session.flush()
        setup["spine"]["milestones"][1]["event"] = "AI 想覆盖"
        await save_setup(session, book.id, setup)
        assert node.event == "作者钉死的事件" and node.status == "pinned"


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
        assert current["outline"] == before["outline"]
        assert [item["seq"] for item in current["first_volume"]["new_expectations"]] == [4, 5]
        await save_piece(session, book.id, "fill", {"outline": before["outline"], "threads": before["threads"]})
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
        assert snapshot["lore"]["anchors"][0]["node"] == 3
        assert snapshot["lore"]["anchors"][0]["node_title"] == "身份揭晓"
        assert snapshot["lore"]["secrets"][0]["node"] == 3
        assert snapshot["outline"]["volumes"][0]["target_node"] == 3
        assert snapshot["outline"]["foreshadowings"][0]["node"] == 3
        await save_setup(session, book.id, snapshot)
        assert await load_setup(session, book.id) == snapshot


async def test_old_lore_and_plans_keep_structured_author_data(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        secret = await session.scalar(select(Secret).where(Secret.book_id == book.id))
        secret.status, secret.reader_knows, secret.reveal_plan = "public", "部分", "作者安排的揭晓"
        anchor = await session.scalar(select(NodeAnchor).where(NodeAnchor.book_id == book.id))
        expectation = await session.scalar(
            select(Foreshadowing).where(Foreshadowing.book_id == book.id, Foreshadowing.seq == 2)
        )
        expectation.status, expectation.planted_chapter = "planted", 3
        await session.flush()
        before = await load_setup(session, book.id)
        old = deepcopy(before)
        old["lore"].pop("anchors")
        old["lore"].pop("secrets")
        old["lore"]["characters"][0]["secrets"] = ["皇族后裔", "旧 schema 新补的秘密", "旧 schema 新补的秘密"]
        old["outline"].pop("expectations")
        old["first_volume"].pop("new_expectations")
        for volume in old["outline"]["volumes"]:
            for key in ("target_node", "target_node_title", "reaches_node", "editor_note", "techniques"):
                volume.pop(key)
        for item in [*old["outline"]["foreshadowings"], *old["first_volume"]["new_foreshadowings"]]:
            item.pop("kind")
            item.pop("node")
        for unit in old["first_volume"]["units"]:
            for key in ("reveals", "editor_note", "techniques"):
                unit.pop(key)
        old["first_volume"]["new_foreshadowings"].append({"description": "后补伏笔", "span": "中"})
        for _ in range(2):
            await save_setup(session, book.id, old)
            after = await load_setup(session, book.id)
            assert after["lore"]["anchors"] == before["lore"]["anchors"]
            assert after["lore"]["secrets"][0] == before["lore"]["secrets"][0]
            assert len(after["lore"]["secrets"]) == 2
            assert after["lore"]["secrets"][1]["truth"] == "旧 schema 新补的秘密"
            assert after["outline"]["expectations"] == before["outline"]["expectations"]
            assert after["first_volume"]["new_expectations"] == before["first_volume"]["new_expectations"]
            assert after["outline"]["volumes"] == before["outline"]["volumes"]
            assert after["first_volume"]["units"] == before["first_volume"]["units"]
            assert after["first_volume"]["new_foreshadowings"][-1]["seq"] == 5
        assert (await session.get(Secret, secret.id)).status == "public"
        assert await session.get(NodeAnchor, anchor.id) is anchor
        # 新形状显式空列表确实表示删除；新形状人物不再带旧 secrets 字段。
        old["lore"].update(anchors=[], secrets=[])
        for character in old["lore"]["characters"]:
            character.pop("secrets", None)
        old["outline"]["expectations"] = []
        old["first_volume"]["new_expectations"] = []
        await save_setup(session, book.id, old)
        after = await load_setup(session, book.id)
        assert after["lore"]["anchors"] == [] and after["lore"]["secrets"] == []
        assert after["outline"]["expectations"] == [] and after["first_volume"]["new_expectations"] == []


async def test_old_lore_preservation_filters_removed_characters_and_stays_in_book(sessionmaker):
    async with sessionmaker() as session:
        books = [Book(), Book()]
        session.add_all(books)
        await session.flush()
        for book in books:
            await save_setup(session, book.id, sample_setup())
        before_other = await load_setup(session, books[1].id)
        setup = await load_setup(session, books[0].id)
        setup["lore"].pop("anchors")
        setup["lore"].pop("secrets")
        setup["lore"]["characters"] = [item for item in setup["lore"]["characters"] if item["name"] == "赵青"]
        result = await save_setup(session, books[0].id, setup)
        assert result["dropped_knowers"] == 1
        after = await load_setup(session, books[0].id)
        assert after["lore"]["anchors"] == []
        assert after["lore"]["secrets"][0]["truth"] == "皇族后裔"
        assert after["lore"]["secrets"][0]["knowers"] == []
        assert await load_setup(session, books[1].id) == before_other


async def test_legacy_spine_insertion_and_reordering_keep_reference_identity(sessionmaker):
    async with sessionmaker() as session:
        book = Book()
        session.add(book)
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        # 暂定节点允许调整顺序；铁钉顺序另由纯函数测试覆盖。
        node = await session.scalar(
            select(StoryNode).where(StoryNode.book_id == book.id, StoryNode.kind == "milestone")
        )
        node.status = "pencil"
        await session.flush()
        for milestones, target_index in (
            (
                [
                    {"index": 1, "title": "新转折", "event": "准备", "volume": 1},
                    {"index": 2, "title": "身份揭晓", "event": "对质", "volume": 2},
                ],
                3,
            ),
            (
                [
                    {"index": 1, "title": "身份揭晓", "event": "对质", "volume": 2},
                    {"index": 2, "title": "新转折", "event": "准备", "volume": 2},
                ],
                2,
            ),
        ):
            snapshot = await load_setup(session, book.id)
            target_id = next(item["id"] for item in snapshot["spine"]["nodes"] if item["title"] == "身份揭晓")
            snapshot["spine"] = {"opening": "入城", "ending": "回家", "milestones": milestones}
            original = deepcopy(snapshot)
            await save_setup(session, book.id, snapshot)
            assert snapshot == original
            after = await load_setup(session, book.id)
            assert after["spine"]["nodes"][target_index - 1]["id"] == target_id
            assert after["lore"]["anchors"][0]["node"] == target_index
            assert after["lore"]["secrets"][0]["node"] == target_index
            assert after["outline"]["volumes"][0]["target_node"] == target_index
            assert after["outline"]["foreshadowings"][0]["node"] == target_index
