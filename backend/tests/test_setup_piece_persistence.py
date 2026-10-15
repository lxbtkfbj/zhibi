"""填中间的跨块同步只允许更新本书已有非铁钉节点的卷号。"""

import uuid
from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import select

from app.graphs.book_setup import piece_persist_node
from app.models import Book, StoryNode, Volume
from app.services.setup_store import load_nodes, load_setup


async def test_fill_persistence_only_updates_existing_unpinned_volume(sessionmaker, monkeypatch):
    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr("app.graphs.book_setup.publish", noop)
    async with sessionmaker() as session:
        book, other = Book(title="本书"), Book(title="别的书")
        session.add_all([book, other])
        await session.flush()
        nodes = [
            StoryNode(
                book_id=book.id,
                position=index,
                kind=kind,
                title=title,
                event="作者事件",
                prerequisite="作者前提",
                consequence="作者后果",
                volume=index,
                status=status,
                origin="author",
                editor_note="作者批注",
            )
            for index, kind, title, status in (
                (1, "opening", "开篇", "pencil"),
                (2, "milestone", "可同步卷号", "pencil"),
                (3, "milestone", "铁钉", "pinned"),
                (4, "milestone", "检查点里漏掉的节点", "pencil"),
                (5, "ending", "结局", "pencil"),
            )
        ]
        foreign = StoryNode(book_id=other.id, position=1, kind="opening", title="另一书开篇", volume=1)
        session.add_all([*nodes, foreign])
        await session.flush()
        session.add(Volume(book_id=book.id, index=1, title="第一卷", target_node_id=nodes[1].id))
        await session.commit()
        before = await load_nodes(session, book.id)
        setup = await load_setup(session, book.id)
        book_id, other_id = book.id, other.id
        before_other = await load_nodes(session, other_id)
        proposed = [
            {
                **deepcopy(before[1]),
                "volume": 4,
                "title": "不能覆盖名称",
                "event": "不能覆盖事件",
                "status": "pinned",
                "origin": "ai",
            },
            {**deepcopy(before[2]), "volume": 99, "status": "pencil", "title": "不能改铁钉"},
            {"id": str(foreign.id), "volume": 99},
            {"id": str(uuid.uuid4()), "kind": "milestone", "title": "不能新建", "volume": 99},
            {"id": None, "kind": "milestone", "title": "不能新建", "volume": 99},
        ]
    state = {
        **setup,
        "mode": "puzzle",
        "piece": "fill",
        "pieces": {"nodes": "confirmed", "fill": "drafting"},
        "spine": {**setup["spine"], "nodes": proposed},
    }
    deps = SimpleNamespace(
        book_id=book_id, job_id=None, redis=None, sessionmaker=sessionmaker, emit=SimpleNamespace(say=noop, status=noop)
    )
    update = await piece_persist_node(state, SimpleNamespace(context=deps))
    expected = deepcopy(before)
    expected[1]["volume"] = 4
    assert update["spine"]["nodes"] == expected
    assert update["pieces"]["fill"] == "waiting"
    async with sessionmaker() as session:
        assert await load_nodes(session, book_id) == expected
        assert await load_nodes(session, other_id) == before_other
        rows = list(
            await session.scalars(select(StoryNode).where(StoryNode.book_id == book_id).order_by(StoryNode.position))
        )
        assert [row.position for row in rows] == [1, 2, 3, 4, 5]
