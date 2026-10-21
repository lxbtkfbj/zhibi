"""要求自增号存进真实存档，但不在作者前后对照里展示；兼容没有该列的旧存档。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.models import AuthorRequirement, Book, Foreshadowing, Secret
from app.services import book_saves
from app.services.requirements import add_requirement, list_requirements


async def book_with_requirements(sessionmaker):
    """插入次序、UUID 次序和旧时间次序均不同，同时间的两行再用 UUID 决定旧序。"""
    async with sessionmaker() as session:
        book = Book(title="作者要求存档顺序")
        session.add(book)
        await session.flush()
        for number, words, year in (
            (30, "先加的要求", 2020),
            (10, "第二条要求", 2030),
            (20, "第三条要求", 2020),
        ):
            session.add(
                AuthorRequirement(
                    id=uuid.UUID(int=number),
                    book_id=book.id,
                    text=words,
                    source="manual",
                    created_at=datetime(year, 1, 1, tzinfo=UTC),
                )
            )
            # 分别 flush，确保 seq 明确反映上面的添加次序，而不是依赖批量插入行为。
            await session.flush()
        await session.commit()
        return book.id


async def stored_requirements(session, book_id, save):
    """通过真正存进 book_objects 的清单加载行，不借用 read_state 的临时对象。"""
    manifests = await book_saves.manifests(session, book_id, save.tree)
    manifest = manifests["author_requirements"]
    objects = await book_saves.load_objects(session, book_id, manifest.values())
    return [objects[row_hash] for row_hash in manifest.values()]


async def change_current_requirements(sessionmaker, book_id):
    async with sessionmaker() as session:
        await session.execute(delete(AuthorRequirement).where(AuthorRequirement.book_id == book_id))
        await add_requirement(session, book_id, "存档以后换成的新要求", source="note")
        await session.commit()


async def assert_views_then_append(sessionmaker, book_id, expected_ids, expected_texts, expected_sequences=None):
    # restore 的会话已结束：这里必须重新查询服务列表和 Book 关系，不能命中旧对象缓存。
    async with sessionmaker() as session:
        rows = await list_requirements(session, book_id)
        assert [row.id for row in rows] == expected_ids
        assert [row.text for row in rows] == expected_texts
        if expected_sequences is not None:
            assert [row.seq for row in rows] == expected_sequences
        else:
            assert all(isinstance(row.seq, int) for row in rows)
            assert [row.seq for row in rows] == sorted(row.seq for row in rows)
            assert len({row.seq for row in rows}) == len(rows)
        book = await session.get(Book, book_id)
        assert [row.id for row in book.author_requirements] == expected_ids
        assert book.requirements == expected_texts
        maximum = max(row.seq for row in rows)
        appended = await add_requirement(session, book_id, "回档后继续追加", source="answer")
        assert appended.seq > maximum
        appended_id = appended.id
        await session.commit()

    async with sessionmaker() as session:
        rows = await list_requirements(session, book_id)
        assert [row.id for row in rows] == [*expected_ids, appended_id]
        assert (await session.get(Book, book_id)).requirements == [*expected_texts, "回档后继续追加"]


async def test_new_save_round_trip_keeps_requirement_ids_sequences_and_order(sessionmaker):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        original = await list_requirements(session, book_id)
        ids = [row.id for row in original]
        sequences = [row.seq for row in original]
        words = [row.text for row in original]
        assert ids == [uuid.UUID(int=value) for value in (30, 10, 20)]
        assert [row.id for row in sorted(original, key=lambda row: (row.created_at, row.id))] != ids
        snapshot = await book_saves.read_state(session, book_id)
        saved_rows = snapshot.data["author_requirements"]
        save = await book_saves.checkpoint(session, book_id, "author", "有自增号的新存档", force=True)
        persisted = await stored_requirements(session, book_id, save)
        assert {row["id"]: row for row in persisted} == saved_rows
        assert {row["id"]: row["seq"] for row in persisted} == {str(row.id): row.seq for row in original}
        save_id = save.id

    await change_current_requirements(sessionmaker, book_id)
    async with sessionmaker() as session:
        landed, before = await book_saves.restore(session, book_id, save_id)
        assert landed.kind == "restore" and landed.restored_from == save_id
        assert before is not None
        restored = await book_saves.read_state(session, book_id)
        assert restored.data["author_requirements"] == saved_rows

    await assert_views_then_append(sessionmaker, book_id, ids, words, sequences)


async def test_old_save_without_sequences_restores_legacy_time_and_uuid_order(sessionmaker, monkeypatch):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        original = await list_requirements(session, book_id)
        legacy_order = sorted(original, key=lambda row: (row.created_at, row.id))
        ids = [row.id for row in legacy_order]
        words = [row.text for row in legacy_order]
        assert ids == [uuid.UUID(int=value) for value in (20, 30, 10)]
        real_row_data = book_saves.row_data

        def legacy_row_data(model, mapping):
            data = real_row_data(model, mapping)
            if model is AuthorRequirement:
                data.pop("seq", None)
            return data

        # 只在制造旧存档时移除新增列。之后的读取、恢复和重新存档都用真实实现。
        with monkeypatch.context() as patch:
            patch.setattr(book_saves, "row_data", legacy_row_data)
            save = await book_saves.checkpoint(session, book_id, "author", "没有自增号的旧存档", force=True)
        assert book_saves.row_data is real_row_data
        persisted = await stored_requirements(session, book_id, save)
        assert len(persisted) == 3
        assert all("seq" not in row for row in persisted)
        manifest_order = [uuid.UUID(row["id"]) for row in persisted]
        assert manifest_order != ids, {"manifest_order": manifest_order, "legacy_order": ids}
        assert [
            uuid.UUID(row["id"]) for row in sorted(persisted, key=lambda row: (row["created_at"], row["id"]))
        ] == ids
        old_content = {row["id"]: row for row in persisted}
        save_id = save.id

    await change_current_requirements(sessionmaker, book_id)
    async with sessionmaker() as session:
        await book_saves.restore(session, book_id, save_id)
        restored = await book_saves.read_state(session, book_id)
        assert {
            row_id: {key: value for key, value in row.items() if key != "seq"}
            for row_id, row in restored.data["author_requirements"].items()
        } == old_content

    await assert_views_then_append(sessionmaker, book_id, ids, words)


async def test_readable_parts_hide_requirement_sequence_but_snapshots_keep_it_and_other_numbers(sessionmaker):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        foreshadowing = Foreshadowing(book_id=book_id, seq=11, description="玉佩上的裂纹")
        secret = Secret(book_id=book_id, seq=22, title="来历", truth="并非普通玉佩")
        session.add_all([foreshadowing, secret])
        await session.commit()
        snap = await book_saves.read_state(session, book_id)
        requirement_id = uuid.UUID(int=30)
        table = AuthorRequirement.__table__
        mapping = (await session.execute(select(table).where(table.c.id == requirement_id))).mappings().one()
        serialized = book_saves.row_data(AuthorRequirement, mapping)
        assert serialized["seq"] == mapping["seq"]
        assert serialized["created_at"] == mapping["created_at"].isoformat()
        assert snap.data["author_requirements"][str(requirement_id)] == serialized
        visible = book_saves.parts("author_requirements", serialized)
        assert visible["原话"] == "先加的要求"
        assert "seq" not in visible and "created_at" not in visible
        assert visible == book_saves.parts(
            "author_requirements", {key: value for key, value in serialized.items() if key not in ("seq", "created_at")}
        )

        for name, row_id, expected in (
            ("foreshadowings", foreshadowing.id, "11"),
            ("secrets", secret.id, "22"),
        ):
            data = snap.data[name][str(row_id)]
            assert data["seq"] == int(expected)
            assert book_saves.parts(name, data)["编号"] == expected
