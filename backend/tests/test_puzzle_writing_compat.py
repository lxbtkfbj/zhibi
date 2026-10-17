"""任务 2 只接通拆卷的新变量与新字段，不提前应用任务 4 的节点调整。"""

from types import SimpleNamespace

from sqlalchemy import select

from app.agents.planning import attach_new_foreshadowings
from app.graphs.write_book import save_volume_node
from app.models import Book, Foreshadowing, PlotUnit, Secret, StoryNode, Volume
from app.services.setup_store import assign_seqs
from app.services.writing_context import volume_blocks
from app.services.writing_store import save_volume_plan


async def create_book(session):
    book = Book(title="兼容测试", concept={"title": "兼容测试"})
    session.add(book)
    await session.flush()
    nodes = [
        StoryNode(
            book_id=book.id,
            position=index,
            kind=kind,
            title=title,
            event="事件",
            prerequisite="前提",
            consequence="后果",
            volume=volume,
            status="pinned" if index == 2 else "pencil",
        )
        for index, kind, title, volume in (
            (1, "opening", "开篇", 1),
            (2, "milestone", "飞升", 3),
            (3, "ending", "归家", 9),
        )
    ]
    session.add_all(nodes)
    await session.flush()
    volume = Volume(
        book_id=book.id, index=3, title="飞升卷", chapter_count=6, target_node_id=nodes[1].id, reaches_node=True
    )
    session.add(volume)
    await session.flush()
    return book, nodes, volume


async def test_writing_volume_blocks_target_secret_order_and_limit(sessionmaker):
    async with sessionmaker() as session:
        book, nodes, volume = await create_book(session)
        session.add_all(
            [
                Secret(book_id=book.id, seq=1, title="远处秘密", truth="远处", node_id=nodes[2].id),
                Secret(book_id=book.id, seq=2, title="近处秘密", truth="近处", node_id=nodes[1].id),
                Secret(book_id=book.id, seq=3, title="已经公开", truth="公开", node_id=nodes[1].id, status="public"),
                Secret(book_id=book.id, seq=15, title="尚未排期", truth="未排"),
            ]
        )
        session.add_all(
            [
                Secret(book_id=book.id, seq=index, title=f"近处{index}", truth="近处", node_id=nodes[1].id)
                for index in range(4, 15)
            ]
        )
        await session.flush()
        blocks = await volume_blocks(session, book, volume)
        assert "节点 2「飞升」［已锁］——本卷就要写到它" in blocks["target_node"]
        assert "再下一个节点：节点 3「归家」" in blocks["target_node"]
        assert "【术语表】可用的技巧名称：" in blocks["glossary"]
        assert blocks["secrets"].startswith("- S2「近处秘密」")
        assert blocks["secrets"].count("［隐藏") == 12
        assert (
            "远处秘密" not in blocks["secrets"]
            and "尚未排期" not in blocks["secrets"]
            and "已经公开" not in blocks["secrets"]
        )


async def test_save_plan_persists_expectations_reveals_techniques_and_legacy_replacement(sessionmaker):
    async with sessionmaker() as session:
        book, nodes, volume = await create_book(session)
        other = Book(title="别的书")
        session.add(other)
        await session.flush()
        session.add_all(
            [Secret(book_id=book.id, seq=1, title="身份"), Secret(book_id=other.id, seq=999, title="不可跨书")]
        )
        await session.flush()
        fresh = assign_seqs(
            [
                {"kind": "伏笔", "description": "旧玉佩", "plant_unit": 1, "payoff_unit": 2},
                {"kind": "期待", "description": "等待飞升", "plant_unit": 1, "payoff_unit": 2, "node": 2},
            ],
            [],
        )
        units, fresh = attach_new_foreshadowings(
            [
                {
                    "index": 1,
                    "title": "起",
                    "chapter_count": 3,
                    "editor_note": "留下期待",
                    "techniques": ["欲扬先抑", "非法术语"],
                    "reveals": [{"ref": "S1", "to": "读者", "how": "露出线索"}, {"ref": "S999", "to": "众人"}],
                },
                {"index": 2, "title": "承", "chapter_count": 3},
            ],
            fresh,
            3,
        )
        await save_volume_plan(session, book.id, volume, units, fresh, replace_new=False, replace_expectations=True)
        stored = list(
            await session.scalars(select(PlotUnit).where(PlotUnit.book_id == book.id).order_by(PlotUnit.index))
        )
        assert stored[0].reveals == [{"ref": "S1", "to": "读者", "how": "露出线索"}]
        assert stored[0].editor_note == "留下期待" and stored[0].techniques == ["欲扬先抑"]
        assert {action["ref"] for action in stored[0].foreshadow_actions} == {"F1", "E2"}
        expectation = await session.scalar(
            select(Foreshadowing).where(Foreshadowing.book_id == book.id, Foreshadowing.kind == "期待")
        )
        assert expectation.span == "中" and expectation.node_id == nodes[1].id and expectation.plant_volume == 3
        # 旧检查点没有 new_expectations：改伏笔时保留已有期待。
        await save_volume_plan(session, book.id, volume, units, [], replace_new=True)
        assert await session.get(Foreshadowing, expectation.id) is expectation
        # 新 schema 的显式空 new_expectations：允许删掉这卷还没立下的中线期待。
        await save_volume_plan(session, book.id, volume, units, [], replace_new=True, replace_expectations=True)
        assert list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id))) == []


async def test_write_graph_new_expectation_saved_and_legacy_node_conflict_reported(sessionmaker):
    async with sessionmaker() as session:
        book, nodes, volume = await create_book(session)
        session.add(Secret(book_id=book.id, seq=1, title="身份"))
        await session.commit()
        book_id, node_id, volume_id = book.id, nodes[1].id, volume.id
    artifacts = []
    speeches = []

    async def artifact(*args):
        artifacts.append(args)

    async def say(*args):
        speeches.append(args)

    deps = SimpleNamespace(book_id=book_id, sessionmaker=sessionmaker, emit=SimpleNamespace(artifact=artifact, say=say))
    plan = {
        "units": [
            {"index": 1, "title": "起", "chapter_count": 3, "reveals": [{"ref": "S1", "to": "读者", "how": "提示"}]},
            {"index": 2, "title": "承", "chapter_count": 3},
        ],
        "new_foreshadowings": [{"description": "旧玉佩", "plant_unit": 1, "payoff_unit": 2}],
        "new_expectations": [{"description": "等待飞升", "plant_unit": 1, "payoff_unit": 2, "node": 2}],
        "node_update": {"title": "不可提前应用", "event": "修改"},
        "node_conflict": "铁钉前提尚未成立",
    }
    await save_volume_node({"volume_id": str(volume_id), "volume_draft": plan}, SimpleNamespace(context=deps))
    async with sessionmaker() as session:
        ledger = list(
            await session.scalars(
                select(Foreshadowing).where(Foreshadowing.book_id == book_id).order_by(Foreshadowing.seq)
            )
        )
        assert [(item.seq, item.kind) for item in ledger] == [(1, "伏笔"), (2, "期待")]
        assert (await session.get(StoryNode, node_id)).title == "飞升"
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.book_id == book_id, PlotUnit.index == 1))
        assert unit.reveals[0]["ref"] == "S1" and any(action["ref"] == "E2" for action in unit.foreshadow_actions)
    assert artifacts[0][2]["data"]["new_expectations"][0]["kind"] == "期待"
    assert any("节点冲突：铁钉前提尚未成立" in message for _, message in speeches)
