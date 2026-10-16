"""第一段整块持久化：节点、信息差与分卷一起保存，不影响其他块或其他书。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.graphs.book_setup import piece_persist_node
from app.models import Book, DraftVersion, StoryNode
from app.services.setup_store import load_setup, save_setup
from tests.test_story_map_store import sample_setup


async def deps_for(sessionmaker, monkeypatch, book_id):
    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr("app.graphs.book_setup.publish", noop)
    return SimpleNamespace(
        book_id=book_id, job_id=None, redis=None, sessionmaker=sessionmaker, emit=SimpleNamespace(say=noop, status=noop)
    )


async def test_segment_persists_nodes_and_volumes_together_preserving_other_blocks(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book, other = Book(title="本书"), Book(title="别的书")
        session.add_all([book, other])
        await session.flush()
        for row in (book, other):
            await save_setup(session, row.id, sample_setup())
        await session.commit()
        before = await load_setup(session, book.id)
        before_other = await load_setup(session, other.id)
        book_id, other_id = book.id, other.id
    proposed = deepcopy(before)
    proposed["segment"]["nodes"][1]["segment"] = {
        "number": 1,
        "goal": "查明城中旧案",
        "opening": {"scene": "城门突遭封锁"},
    }
    proposed["volumes"]["volumes"][1]["want"] = "当众揭穿冒名的城主"
    state = {
        **proposed,
        "mode": "puzzle",
        "piece": "segment",
        "pieces": {"concept": "confirmed", "protagonist": "confirmed", "world": "confirmed", "segment": "drafting"},
    }
    deps = await deps_for(sessionmaker, monkeypatch, book_id)
    update = await piece_persist_node(state, SimpleNamespace(context=deps))
    assert update["pieces"]["segment"] == "waiting"
    assert set(update) >= {"segment", "volumes"}
    async with sessionmaker() as session:
        after = await load_setup(session, book_id)
        assert after["segment"] == proposed["segment"] and after["volumes"] == proposed["volumes"]
        for key in ("concept", "protagonist", "world", "first_volume"):
            assert after[key] == before[key]
        assert await load_setup(session, other_id) == before_other
        snapshot = await session.scalar(select(DraftVersion).where(DraftVersion.book_id == book_id))
        assert snapshot.note == "piece:segment" and snapshot.payload == after


async def test_segment_rejects_foreign_node_before_committing_any_changes(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book, other = Book(), Book()
        session.add_all([book, other])
        await session.flush()
        await save_setup(session, book.id, sample_setup())
        foreign = StoryNode(book_id=other.id, kind="milestone", position=1, title="外书节点")
        session.add(foreign)
        await session.commit()
        before = await load_setup(session, book.id)
        state = deepcopy(before)
        state["segment"]["nodes"][1]["id"] = str(foreign.id)
        state.update(mode="puzzle", piece="segment", pieces={"segment": "drafting"})
        book_id = book.id
    deps = await deps_for(sessionmaker, monkeypatch, book_id)
    with pytest.raises(ValueError, match="不属于本书"):
        await piece_persist_node(state, SimpleNamespace(context=deps))
    async with sessionmaker() as session:
        assert await load_setup(session, book_id) == before
        assert await session.scalar(select(DraftVersion).where(DraftVersion.book_id == book_id)) is None
