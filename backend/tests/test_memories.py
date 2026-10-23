"""Task 2: real ledger/API/migration boundaries, never real model calls."""

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
import sqlalchemy as sa
from redis.asyncio import Redis

from alembic import command
from app.agents.schemas import RequirementsTidy
from app.config import get_settings
from app.main import create_app
from app.models import AuthorRequirement, Book, Chapter, MeetingMessage, Memory, Volume
from app.services import book_saves
from app.services.memories import forget, remember, source_of, summary_of
from app.services.requirements import active_requirements, requirement_text, requirements_list
from tests.test_author_requirement_sequence import insert_legacy_row, legacy_database


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def books(sessionmaker):
    async with sessionmaker() as session:
        own, other, teardown = Book(title="这本书"), Book(title="别的书"), Book(title="拆的书", source="teardown")
        session.add_all([own, other, teardown])
        await session.commit()
        return own.id, other.id, teardown.id


def test_memory_migration_preserves_every_source_scope_time_and_global_number_order(migration_database_urls):
    sources = [
        "manual",
        "legacy",
        "unknown",
        "note",
        "private:chief",
        "chat:writer",
        "plan",
        "answer",
        "trial",
        "volume:2",
        "unit:x",
        "segment:3",
    ]
    with legacy_database(migration_database_urls) as (config, engine, _):
        command.upgrade(config, "0027")
        metadata = sa.MetaData()
        metadata.reflect(engine)
        book_ids = [uuid.uuid4(), uuid.uuid4()]
        moment = datetime(2024, 3, 4, tzinfo=UTC)
        with engine.begin() as connection:
            for book_id in book_ids:
                insert_legacy_row(connection, metadata.tables["books"], id=book_id, title="迁移", source="new")
            message = uuid.uuid4().int % 100000
            insert_legacy_row(
                connection,
                metadata.tables["meeting_messages"],
                id=message,
                book_id=book_ids[0],
                speaker="author",
                kind="note",
            )
            expected = []
            for index, source in enumerate(sources):
                detail = "记忆迁移的原文" * 9 + f"\n第 {index} 条"
                scope = ("always", "chapter", "volume")[index % 3]
                values = dict(
                    id=uuid.uuid4(),
                    book_id=book_ids[index % 2],
                    seq=100 - index,
                    text=detail,
                    source=source,
                    scope=scope,
                    chapter_index=7 if scope == "chapter" else None,
                    volume_index=2 if scope == "volume" else None,
                    created_at=moment,
                    updated_at=moment,
                    message_id=message,
                )
                insert_legacy_row(connection, metadata.tables["author_requirements"], **values)
                expected.append(values)
            receipt = {
                "kind": "requirement",
                "requirement_id": str(expected[0]["id"]),
                "change": [{"table": "author_requirements"}],
                "diff": [{"after": "旧对照"}],
            }
            connection.execute(
                sa.update(metadata.tables["meeting_messages"])
                .where(metadata.tables["meeting_messages"].c.id == message)
                .values(payload={"outcome": receipt, "steps": [receipt], "results": [receipt]})
            )
        command.upgrade(config, "0028")
        with engine.connect() as connection:
            rows = connection.execute(sa.text("SELECT * FROM memories ORDER BY id")).mappings().all()
            assert len(rows) == len(sources)
            for number, (row, old) in enumerate(
                zip(rows, sorted(expected, key=lambda item: item["seq"]), strict=True), 1
            ):
                assert row["id"] == number
                assert row["summary"] == summary_of(old["text"])
                assert row["detail"] == old["text"]
                assert row["source"] == source_of(old["source"])
                for key in (
                    "book_id",
                    "scope",
                    "chapter_index",
                    "volume_index",
                    "message_id",
                    "created_at",
                    "updated_at",
                ):
                    assert row[key] == old[key]
            assert connection.scalar(sa.text("SELECT count(*) FROM author_requirements")) == len(sources)
            payload = connection.scalar(sa.text("SELECT payload FROM meeting_messages WHERE id=:id"), {"id": message})
            for converted in [payload["outcome"], *payload["steps"], *payload["results"]]:
                assert converted["memory"]["id"] == len(sources)
                assert converted["memory"]["summary"] == summary_of(expected[0]["text"])
                assert "change" not in converted and "diff" not in converted
        command.downgrade(config, "0027")
        assert not sa.inspect(engine).has_table("memories")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT count(*) FROM author_requirements")) == len(sources)


async def test_writing_combines_global_then_book_without_expired_chat_deleted_or_other_book(sessionmaker):
    bid, other, _ = await books(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            [
                Chapter(book_id=bid, index=1, status="final"),
                Chapter(book_id=bid, index=2, status="planned"),
                Volume(book_id=bid, index=1, title="卷", status="done"),
            ]
        )
        await session.flush()
        local = await remember(session, bid, "本书", "第一行\n第二行", scope="next_chapter")
        global_row = await remember(session, None, "全局", "所有书都遵守")
        await remember(session, None, "聊天全局", kind="chat")
        await remember(session, bid, "聊天", kind="chat")
        await remember(session, other, "别的书")
        deleted = await remember(session, bid, "删掉")
        await forget(session, deleted)
        expired = await remember(session, bid, "过期")
        expired.scope, expired.chapter_index = "chapter", 1
        await session.commit()
        rows = await active_requirements(session, bid)
        assert [row.id for row in rows] == [global_row.id, local.id]
        assert requirements_list(rows) == "- 所有书都遵守\n- （只管第 2 章）第一行 第二行"
        assert requirement_text(local) == "（只管第 2 章）第一行 第二行"


async def test_memory_crud_duplicate_sources_time_undo_id_and_delete_book(client, sessionmaker):
    bid, other, _ = await books(sessionmaker)
    url = f"/api/books/{bid}/memories"
    first = (await client.post(url, json={"book_id": str(bid), "summary": "保留编号", "detail": "详细\n原文"})).json()
    assert first["source"] == "你加的"
    async with sessionmaker() as session:
        duplicate = await remember(session, bid, "保留编号", "更新详细", source="plan")
        await session.commit()
        assert duplicate.id == first["id"] and duplicate.source == "方案卡"
        assert duplicate.version > first["version"] and duplicate.created_at.isoformat() != first["created_at"]
    changed = await client.post(f"{url}/{first['id']}/undo", json={"version": first["version"]})
    assert changed.status_code == 409 and changed.json()["detail"] == "这条后来又改过，去「记忆」里改"
    assert (await client.delete(f"{url}/{first['id']}")).status_code == 204
    assert (await client.get(url)).json() == []
    assert (await client.post(f"{url}/{first['id']}/undo", json={"version": first["version"]})).json()[
        "detail"
    ] == "这条后来删掉了"
    restored = (await client.post(f"{url}/{first['id']}/restore")).json()
    assert restored["id"] == first["id"]
    global_row = (await client.post(url, json={"book_id": None, "summary": "全局一直有效"})).json()
    assert global_row["id"] > restored["id"]
    assert (await client.get(f"/api/books/{other}/memories/{restored['id']}")).status_code == 404
    async with sessionmaker() as session:
        await session.delete(await session.get(Book, bid))
        await session.commit()
        assert await session.get(Memory, first["id"]) is None
        assert await session.get(Memory, global_row["id"]) is not None
        assert await session.scalar(sa.select(sa.func.count()).select_from(AuthorRequirement)) == 0


@pytest.mark.parametrize("scope", ["next_chapter", "this_volume", "next_volume"])
async def test_global_scope_rejected_with_exact_error(client, sessionmaker, scope):
    bid, _, _ = await books(sessionmaker)
    response = await client.post(
        f"/api/books/{bid}/memories", json={"book_id": None, "summary": "全局", "scope": scope}
    )
    assert response.status_code == 422 and response.json()["detail"] == "全局的只能一直有效"


async def test_edit_can_move_library_kind_preserves_resolved_scope_and_blank_detail(client, sessionmaker):
    bid, _, _ = await books(sessionmaker)
    url = f"/api/books/{bid}/memories"
    row = (await client.post(url, json={"book_id": str(bid), "summary": "原文", "scope": "next_chapter"})).json()
    async with sessionmaker() as session:
        session.add(Chapter(book_id=bid, index=1, status="final"))
        await session.commit()
    edited = (await client.patch(f"{url}/{row['id']}", json={"summary": "改简述", "detail": ""})).json()
    assert edited["chapter_index"] == 1 and edited["detail"] == "改简述" and not edited["active"]
    edited = (await client.patch(f"{url}/{row['id']}", json={"book_id": None, "kind": "chat"})).json()
    assert edited["scope"] == "always" and edited["chapter_index"] is None
    assert edited["book_id"] is None and edited["kind"] == "chat"
    assert (await client.post(url, json={"book_id": str(bid), "summary": "  "})).status_code == 422


async def test_same_summary_only_deduplicates_in_same_library_and_kind_and_serializes(sessionmaker):
    bid, other, _ = await books(sessionmaker)

    async def add():
        async with sessionmaker() as session:
            row = await remember(session, bid, "同一句")
            await session.commit()
            return row.id

    ids = await asyncio.gather(add(), add())
    assert ids[0] == ids[1]
    async with sessionmaker() as session:
        rows = [
            await remember(session, None, "同一句"),
            await remember(session, other, "同一句"),
            await remember(session, bid, "同一句", kind="chat"),
        ]
        assert len({ids[0], *(r.id for r in rows)}) == 4


async def test_tidy_formats_details_and_applies_both_fields_only_when_selected(client, sessionmaker, monkeypatch):
    bid, _, _ = await books(sessionmaker)
    async with sessionmaker() as session:
        row = await remember(session, bid, "简述不同", "详细内容\n换行", source="note")
        await remember(session, None, "不整理全局")
        await remember(session, bid, "不整理聊天", kind="chat")
        await session.commit()
        rid = row.id

    async def model(book_id, role, schema, template, **values):
        assert book_id == bid and role == "chief" and schema is RequirementsTidy and template == "requirements_tidy"
        assert values["requirements"] == "1. 详细内容 换行（一直有效；来自聊天里记的）"
        return RequirementsTidy(items=[{"index": 1, "action": "改写", "reason": "说明白", "rewrite": "改写后的话"}])

    monkeypatch.setattr("app.services.chat.model", model)
    tidy = await client.post(f"/api/books/{bid}/memories/tidy")
    assert tidy.status_code == 200, tidy.text
    async with sessionmaker() as session:
        assert (await session.get(Memory, rid)).summary == "简述不同"
    result = await client.post(f"/api/books/{bid}/memories/apply", json={"rewrite": [{"id": rid, "text": "改写" * 30}]})
    assert result.status_code == 200, result.text
    row = next(r for r in result.json() if r["id"] == rid)
    assert row["detail"] == "改写" * 30 and row["summary"] == "改写" * 20 + "……"
    await client.post(f"/api/books/{bid}/memories/apply", json={"delete": [rid]})
    async with sessionmaker() as session:
        assert (await session.get(Memory, rid)).deleted_at is not None


async def test_teardown_and_other_book_library_are_rejected_and_old_routes_retired(client, sessionmaker):
    bid, other, teardown = await books(sessionmaker)
    assert (
        await client.post(f"/api/books/{teardown}/memories", json={"book_id": str(teardown), "summary": "不能记"})
    ).status_code == 409
    assert (
        await client.post(f"/api/books/{bid}/memories", json={"book_id": str(other), "summary": "不能串书"})
    ).status_code == 422
    assert (await client.get(f"/api/books/{bid}/requirements")).status_code == 404


async def test_undo_updates_plan_and_agent_receipts_and_never_creates_saves(client, sessionmaker):
    from app.services.memories import remembered_outcome

    bid, _, _ = await books(sessionmaker)
    async with sessionmaker() as session:
        row = await remember(session, bid, "撤销同一条")
        outcome = remembered_outcome(row)
        session.add_all(
            [
                MeetingMessage(
                    book_id=bid,
                    speaker="author",
                    kind="note",
                    content="记住",
                    payload={"steps": [outcome], "outcome": outcome},
                ),
                MeetingMessage(
                    book_id=bid, speaker="chief", kind="plan", content="方案", payload={"results": [outcome]}
                ),
            ]
        )
        await session.commit()
        saved = await book_saves.checkpoint(session, bid, "author", force=True)
        rid, version = row.id, row.version
    response = await client.post(f"/api/books/{bid}/memories/{rid}/undo", json={"version": version})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        for message in await session.scalars(sa.select(MeetingMessage).where(MeetingMessage.book_id == bid)):
            for key in ("steps", "results"):
                for result in (message.payload or {}).get(key, []):
                    assert result["undone"]
        assert await book_saves.checkpoint(session, bid, "author") is None
        assert (await book_saves.compare(session, bid, saved))["groups"] == []


@pytest.mark.parametrize("tools", [False, True])
async def test_only_remembering_from_chat_does_not_trigger_even_a_first_auto_save(
    client, sessionmaker, monkeypatch, tools
):
    from app.llm import demo
    from app.models import BookSave, LlmProfile, RoleAssignment

    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr(demo, "FAKE_TOOLS", tools)
    bid, _, _ = await books(sessionmaker)
    async with sessionmaker() as session:
        profile = LlmProfile(name="记忆离线测试", provider="demo", model="demo")
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "记住：以后不要套话"})
    assert response.status_code == 201, response.text
    async with sessionmaker() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(BookSave)) == 0
        row = await session.scalar(sa.select(Memory))
        assert row.summary == row.detail == "记住：以后不要套话" and row.source == "聊天里记的"


async def test_manual_memory_and_existing_book_writer_use_the_same_lock_order(sessionmaker):
    from app.services.library import lock_book

    bid, _, _ = await books(sessionmaker)
    started = asyncio.Event()

    async def manual():
        async with sessionmaker() as session:
            started.set()
            row = await remember(session, bid, "同时手工记的")
            await session.commit()
            return row.id

    async with sessionmaker() as session:
        await lock_book(session, bid)
        task = asyncio.create_task(manual())
        await started.wait()
        await asyncio.sleep(0.05)
        row = await asyncio.wait_for(remember(session, bid, "写作流程记的"), timeout=5)
        assert row.summary == "写作流程记的"
        await session.commit()
    assert await asyncio.wait_for(task, timeout=5) > row.id


async def test_deduped_detail_and_restored_memory_keep_legacy_tombstones_correct(client, sessionmaker):
    from app.services.requirements import deleted_texts

    bid, _, _ = await books(sessionmaker)
    async with sessionmaker() as session:
        row = await remember(session, bid, "同一简述", "旧作者原话")
        again = await remember(session, bid, "同一简述", "新作者原话")
        assert row.id == again.id
        assert "旧作者原话" in await deleted_texts(session, bid)
        await forget(session, again)
        await session.commit()
        rid = row.id
    response = await client.post(f"/api/books/{bid}/memories/{rid}/restore")
    assert response.status_code == 200
    async with sessionmaker() as session:
        assert await deleted_texts(session, bid) == {"旧作者原话"}
