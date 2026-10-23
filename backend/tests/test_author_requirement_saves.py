"""记忆的统一编号不随存档回退；旧存档的写作要求一律忽略。"""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Book, Foreshadowing, Memory, Secret
from app.services import book_saves
from app.services.memories import forget, remember
from app.services.requirements import add_requirement, list_requirements


async def book_with_requirements(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="记忆与存档")
        session.add(book)
        await session.flush()
        for words, year in (("先加的要求", 2030), ("第二条要求", 2020), ("第三条要求", 2020)):
            row = await add_requirement(session, book.id, words)
            row.created_at = datetime(year, 1, 1, tzinfo=UTC)
        await session.commit()
        return book.id


async def test_new_save_round_trip_keeps_current_memory_ids_sequences_and_order(sessionmaker):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        original = await list_requirements(session, book_id)
        ids = [row.id for row in original]
        assert ids == sorted(ids)
        assert [row.id for row in sorted(original, key=lambda row: (row.created_at, row.id))] != ids
        saved = await book_saves.checkpoint(session, book_id, "author", "不含记忆的存档", force=True)
        assert "memories" not in saved.tree and "author_requirements" not in saved.tree
        await forget(session, original[0])
        original[1].summary = original[1].detail = "存档以后改的"
        added = await remember(session, None, "全局新记忆")
        await session.commit()
        expected = [(r.id, r.summary, r.deleted_at) for r in await session.scalars(select(Memory).order_by(Memory.id))]
        landed, _ = await book_saves.restore(session, book_id, saved.id)
        assert landed.restored_from == saved.id
        assert [
            (r.id, r.summary, r.deleted_at) for r in await session.scalars(select(Memory).order_by(Memory.id))
        ] == expected
        appended = await add_requirement(session, book_id, "回档后继续追加")
        assert appended.id > added.id


async def test_old_save_without_sequences_ignores_legacy_requirements_and_other_rules(sessionmaker):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        saved = await book_saves.checkpoint(session, book_id, "author", "旧存档", force=True)
        manifests = await book_saves.manifests(session, book_id, saved.tree)
        book_hash = manifests["books"][str(book_id)]
        old_book = dict((await book_saves.load_objects(session, book_id, [book_hash]))[book_hash])
        old_book["settings"] = {**old_book["settings"], "other_rules": "旧存档的其他规矩不复活"}
        snap = book_saves.Snapshot()
        snap.add("books", str(book_id), old_book)
        new_manifest = snap.put("manifest", snap.rows["books"])
        legacy_row = snap.put("row", {"text": "旧写作要求不复活", "source": "manual"})
        legacy_manifest = snap.put("manifest", {"旧 UUID": legacy_row})
        await book_saves.store_objects(session, book_id, snap, snap.objects)
        saved.tree = {**saved.tree, "books": new_manifest, "author_requirements": legacy_manifest}
        await session.commit()
        expected = [(row.id, row.detail) for row in await list_requirements(session, book_id)]
        await book_saves.restore(session, book_id, saved.id)
        assert [(row.id, row.detail) for row in await list_requirements(session, book_id)] == expected
        assert (await session.get(Book, book_id)).settings["other_rules"] == ""
        comparison = await book_saves.compare(session, book_id, saved)
        assert all(group["name"] != "写作要求" for group in comparison["groups"])


async def test_memory_changes_create_no_snapshot_diff_but_other_numbers_are_preserved(sessionmaker):
    book_id = await book_with_requirements(sessionmaker)
    async with sessionmaker() as session:
        foreshadowing = Foreshadowing(book_id=book_id, seq=11, description="玉佩上的裂纹")
        secret = Secret(book_id=book_id, seq=22, title="来历", truth="并非普通玉佩")
        session.add_all([foreshadowing, secret])
        await session.commit()
        saved = await book_saves.checkpoint(session, book_id, "author", force=True)
        before = await book_saves.read_state(session, book_id)
        await remember(session, book_id, "只加记忆")
        await session.commit()
        after = await book_saves.read_state(session, book_id)
        assert after.tree == before.tree
        assert book_saves.row_changes(before, after) == []
        assert await book_saves.checkpoint(session, book_id, "author") is None
        assert (await book_saves.compare(session, book_id, saved))["groups"] == []
        for name, row_id, expected in (("foreshadowings", foreshadowing.id, "11"), ("secrets", secret.id, "22")):
            data = after.data[name][str(row_id)]
            assert data["seq"] == int(expected)
            assert book_saves.parts(name, data)["编号"] == expected
