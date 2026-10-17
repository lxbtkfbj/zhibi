"""版本快照、首改补初版、回退与事务级并发序号。"""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.models import Book, Character, PlotUnit, StoryNode, Volume, WorldEntry
from app.models.library import SettingVersion
from app.services.versions import apply_snapshot, record_version, snapshot_of


async def make_entry(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="版本测试")
        session.add(book)
        await session.flush()
        entry = WorldEntry(book_id=book.id, category="特殊规则", name="原名", content="原文", source="ai")
        session.add(entry)
        await session.commit()
        return book.id, entry.id


async def read_versions(session, target_id):
    return list(
        await session.scalars(
            select(SettingVersion).where(SettingVersion.target_id == target_id).order_by(SettingVersion.version)
        )
    )


async def test_first_edit_records_original_then_each_edit_adds_one(sessionmaker):
    book_id, entry_id = await make_entry(sessionmaker)
    async with sessionmaker() as session:
        target = await session.get(WorldEntry, entry_id)
        before = snapshot_of(target)
        target.content = "第一次修改"
        target.source = "ai_edited"
        await record_version(session, book_id, "entry", target, "ai_edited", before=before, previous_source="ai")
        before["content"] = "调用方后来改变快照，不得污染初版"
        second_before = snapshot_of(target)
        target.content = "第二次修改"
        latest = await record_version(session, book_id, "entry", target, "author", "作者调整", before=second_before)
        versions = await read_versions(session, entry_id)
        assert [row.version for row in versions] == [1, 2, 3]
        assert [row.snapshot["content"] for row in versions] == ["原文", "第一次修改", "第二次修改"]
        assert versions[0].source == "ai" and versions[0].note == "初版"
        assert latest.note == "作者调整"
        await session.commit()


async def test_creation_is_one_version_and_revert_is_a_new_version(sessionmaker):
    book_id, entry_id = await make_entry(sessionmaker)
    async with sessionmaker() as session:
        target = await session.get(WorldEntry, entry_id)
        target.source = "author"
        first = await record_version(session, book_id, "entry", target, "author")
        assert first.version == 1
        before = snapshot_of(target)
        target.content = "改后"
        await record_version(session, book_id, "entry", target, "author", before=before)
        before = snapshot_of(target)
        apply_snapshot(target, first.snapshot)
        reverted = await record_version(session, book_id, "entry", target, "revert", "退回到第 1 版", before=before)
        assert reverted.version == 3
        assert reverted.snapshot == first.snapshot
        assert reverted.source == "revert" and reverted.note == "退回到第 1 版"
        assert target.source == "author"  # 来源由调用方明确决定，快照不恢复系统来源。


def test_character_snapshot_excludes_live_state_and_restores_only_author_fields():
    target = Character(
        name="阿青",
        aliases=["青子"],
        tags=["金手指"],
        personality="谨慎",
        want="救人",
        location="青阳城",
        condition="受伤",
        is_alive=True,
        source="writing",
    )
    saved = snapshot_of(target)
    assert saved["aliases"] == ["青子"]
    assert set(saved).isdisjoint({"want", "location", "condition", "is_alive", "source", "book_id", "id"})
    target.aliases.append("新别名")
    target.location = "江城"
    target.is_alive = False
    apply_snapshot(target, saved)
    assert target.aliases == ["青子"]
    assert target.location == "江城" and target.is_alive is False
    target.aliases.append("再改")
    assert saved["aliases"] == ["青子"]


def test_snapshot_uuid_is_json_safe_and_restored_to_uuid():
    parent_id, secret_id = uuid.uuid4(), uuid.uuid4()
    target = WorldEntry(
        name="城", parent_id=parent_id, secret_id=secret_id, fields=[{"name": "规矩", "value": "夜不出门"}]
    )
    saved = snapshot_of(target)
    assert json.loads(json.dumps(saved))["parent_id"] == str(parent_id)
    target.parent_id = None
    target.fields[0]["value"] = "改过"
    apply_snapshot(target, saved)
    assert target.parent_id == parent_id and target.secret_id == secret_id
    assert target.fields[0]["value"] == "夜不出门"


def test_concept_snapshot_is_the_whole_concept_not_the_book():
    target = Book(title="书名不动", source="imported", concept={"story": "定调", "old": {"key": ["旧字段"]}})
    saved = snapshot_of(target)
    assert saved == target.concept and "concept" not in saved
    target.concept["old"]["key"].append("后来改")
    apply_snapshot(target, saved)
    assert target.concept["old"]["key"] == ["旧字段"]
    target.concept["old"]["key"].append("再次改")
    assert saved["old"]["key"] == ["旧字段"]
    assert target.title == "书名不动" and target.source == "imported"


def test_outline_snapshots_preserve_progress_and_cover_legacy_fields():
    node = StoryNode(
        title="终点",
        event="事件",
        status="pinned",
        position=3,
        segment={"title": "篇名", "text": "篇文", "number": 2, "opening": {"hook": "钩子"}},
    )
    saved = snapshot_of(node)
    assert set(saved) == {"title", "event", "status", "segment"}
    node.position = 8
    node.segment["opening"]["hook"] = "改了"
    apply_snapshot(node, saved)
    assert node.segment["opening"]["hook"] == "钩子" and node.position == 8
    volume = Volume(
        title="卷",
        summary="卷纲",
        status="done",
        recap="卷回顾",
        target_node_id=uuid.uuid4(),
        want="欲望",
        pressure="压迫",
        thread_beats=[{"thread": "主线", "beat": "开局"}],
    )
    unit = PlotUnit(
        title="单元",
        summary="单元纲",
        status="done",
        recap="单元回顾",
        loop="核心循环",
        reveals=[{"ref": "S1", "method": "亲眼所见"}],
        plan_issues=["待处理问题"],
    )
    for target in (volume, unit):
        saved = snapshot_of(target)
        assert {"summary", "locked", "chapter_count", "editor_note", "techniques"} <= saved.keys()
        assert {"status", "recap", "plan_issues", "book_id", "index"}.isdisjoint(saved)
        target.summary = "修改后"
        apply_snapshot(target, saved)
        assert target.status == "done" and target.summary != "修改后"


def test_reverting_concept_keeps_the_display_title_in_sync():
    book = Book(title="新书名", concept={"title": "新书名", "story": "新定调"})
    apply_snapshot(book, {"title": "旧书名", "story": "旧定调"})
    assert book.title == book.concept["title"] == "旧书名"
    apply_snapshot(book, {"title": "", "story": "旧的无名定调"})
    assert book.title == "旧书名"
    with pytest.raises(ValueError, match="书名必须是文字"):
        apply_snapshot(book, {"title": ["不能变成列表"]})
    assert book.title == "旧书名" and book.concept["story"] == "旧的无名定调"


def test_apply_snapshot_rejects_protected_keys_and_bad_uuids_atomically():
    target = WorldEntry(name="原名", book_id=uuid.uuid4())
    with pytest.raises(ValueError, match="不可编辑"):
        apply_snapshot(target, {"name": "不应写入", "book_id": str(uuid.uuid4())})
    assert target.name == "原名"
    with pytest.raises(ValueError, match="引用无效"):
        apply_snapshot(target, {"name": "不应写入", "parent_id": "invalid"})
    assert target.name == "原名"
    with pytest.raises(ValueError):
        snapshot_of(object())


async def test_concept_initial_source_is_ai_not_book_origin(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="书", source="imported", concept={"story": "原文"})
        session.add(book)
        await session.flush()
        before = snapshot_of(book)
        book.concept = {"story": "改后"}
        await record_version(session, book.id, "concept", book, "author", before=before)
        versions = await read_versions(session, book.id)
        assert [version.source for version in versions] == ["ai", "author"]


async def test_record_version_rejects_wrong_target_book_and_source(sessionmaker):
    book_id, entry_id = await make_entry(sessionmaker)
    async with sessionmaker() as session:
        target = await session.get(WorldEntry, entry_id)
        for owner, kind, source in (
            (uuid.uuid4(), "entry", "ai"),
            (book_id, "character", "ai"),
            (book_id, "entry", "new"),
        ):
            with pytest.raises(ValueError):
                await record_version(session, owner, kind, target, source)
        assert await read_versions(session, entry_id) == []


async def test_recorded_versions_rollback_with_the_calling_transaction(sessionmaker):
    book_id, entry_id = await make_entry(sessionmaker)
    async with sessionmaker() as session:
        target = await session.get(WorldEntry, entry_id)
        await record_version(session, book_id, "entry", target, "author")
        await session.rollback()
    async with sessionmaker() as session:
        assert await read_versions(session, entry_id) == []


async def test_concurrent_version_numbers_are_unique_and_contiguous(sessionmaker):
    book_id, entry_id = await make_entry(sessionmaker)

    async def add_version():
        async with sessionmaker() as session:
            target = await session.get(WorldEntry, entry_id)
            await record_version(session, book_id, "entry", target, "candidate", before=snapshot_of(target))
            await session.commit()

    await asyncio.gather(*(add_version() for _ in range(8)))
    async with sessionmaker() as session:
        versions = await read_versions(session, entry_id)
        assert [version.version for version in versions] == list(range(1, 10))
        assert sum(version.note == "初版" for version in versions) == 1
