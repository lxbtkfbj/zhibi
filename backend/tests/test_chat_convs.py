"""第五步第四批：群聊分成一段段对话（新对话、以前的对话），从这里重来（只退聊天，书不动）。"""

import importlib.util
import uuid
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Character, ChatConversation, ChatThread, MeetingMessage
from app.services import chat_convs
from app.services.chat_context import dialogue
from app.services.meeting import post_message
from tests.test_chat_agent import messages, reply_of, say
from tests.test_chat_task6 import seed


@pytest.fixture(autouse=True)
def tools_on(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    monkeypatch.setattr("app.services.jobs.enqueue", lambda job_id: None)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


@pytest.fixture
async def redis():
    connection = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield connection
    await connection.aclose()


async def convs(client, book) -> list[dict]:
    return (await client.get(f"/api/books/{book}/chat/conversations")).json()


async def test_each_conversation_keeps_its_own_dialogue(client, sessionmaker, redis):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "楚风现在什么境界？")
    a = first["payload"]["conv"]
    assert (await reply_of(client, bid, first["id"]))["payload"]["conv"] == a
    # 新对话：最近那一段说过话了，开一段新的；再点一次还是这一段（不开一堆空的）
    b = (await client.post(f"/api/books/{bid}/chat/conversations")).json()["id"]
    assert b != a and (await client.post(f"/api/books/{bid}/chat/conversations")).json()["id"] == b
    listing = await convs(client, bid)
    assert [(c["id"], c["title"], c["notes"], c["current"]) for c in listing] == [
        (b, "", 0, True),
        (a, "楚风现在什么境界？", 1, False),
    ]
    second = await say(client, bid, "楚风的性格改成冷静沉稳", conv=b)
    assert second["payload"]["conv"] == b
    # 编辑部干活的进度记在最近聊的那一段
    async with sessionmaker() as session:
        line = await post_message(
            session, redis, book_id=bid, job_id=None, speaker="system", kind="decision", content="写完了"
        )
        assert line["payload"] == {"conv": b}
        rows_a = await dialogue(session, bid, "group", conv=a)
        rows_b = await dialogue(session, bid, "group", conv=b)
    assert [m.content for m in rows_a if m.speaker == "author"] == ["楚风现在什么境界？"]
    assert [m.content for m in rows_b if m.speaker == "author"] == ["楚风的性格改成冷静沉稳"]
    # 回到以前那一段接着聊：它又成了最近聊的，按第一句话起名的名字不变
    third = await say(client, bid, "那他下一步该突破了吧？", conv=a)
    assert third["payload"]["conv"] == a
    listing = await convs(client, bid)
    assert [(c["id"], c["title"], c["notes"]) for c in listing] == [
        (a, "楚风现在什么境界？", 2),
        (b, "楚风的性格改成冷静沉稳", 1),
    ]
    async with sessionmaker() as session:
        assert [m.content for m in await dialogue(session, bid, "group", conv=a) if m.speaker == "author"] == [
            "楚风现在什么境界？",
            "那他下一步该突破了吧？",
        ]
    bad = await client.post(f"/api/books/{bid}/notes", json={"content": "你好", "conv": str(uuid.uuid4())})
    assert bad.status_code == 422


async def test_summary_belongs_to_the_conversation(client, sessionmaker):
    bid = await seed(sessionmaker)
    for i in range(16):
        await say(client, bid, f"旧话题第{i}个问题是什么？")
    async with sessionmaker() as session:
        conv = await session.scalar(select(ChatConversation).where(ChatConversation.book_id == bid))
        assert conv.summary and conv.summarized_until
        # 群聊的摘要不再记在 chat_threads 上
        group = await session.scalar(select(ChatThread).where(ChatThread.book_id == bid, ChatThread.thread == "group"))
        assert group is None or not group.summary
    fresh = (await client.post(f"/api/books/{bid}/chat/conversations")).json()["id"]
    await say(client, bid, "新话题是什么？", conv=fresh)
    async with sessionmaker() as session:
        row = await session.get(ChatConversation, uuid.UUID(fresh))
        assert not row.summary
        rows = await dialogue(session, bid, "group", conv=fresh)
        assert "旧话题" not in "".join(m.content for m in rows)


async def test_rewind_only_rolls_back_the_chat(client, sessionmaker):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "楚风的性格改成冷静沉稳")
    conv = first["payload"]["conv"]
    second = await say(client, bid, "他现在什么境界？")
    assert first["payload"]["steps"][0]["kind"] == "edit"
    # 从第一句重来：这一句和后面的聊天都收起来，改过的这一句照常答
    again = await say(client, bid, "楚风现在是什么境界？", conv=conv, rewind_from=first["id"])
    rows = {m["id"]: m for m in await messages(client, bid)}
    gone = [first["id"], second["id"]]
    gone += [m["id"] for m in rows.values() if set((m["payload"] or {}).get("reply_to") or []) & set(gone)]
    assert len(gone) == 4 and all(rows[i]["payload"]["dropped"] for i in gone)
    assert "dropped" not in rows[again["id"]]["payload"]
    async with sessionmaker() as session:
        said = [m.content for m in await dialogue(session, bid, "group", conv=conv)]
        assert said[0] == "楚风现在是什么境界？" and "他现在什么境界？" not in said
        # 只退聊天：书不跟着退，第一句改的那一处照样在
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.personality
    # 第一句收起来了：这一段按改过的那一句起名
    assert [c["title"] for c in await convs(client, bid)] == ["楚风现在是什么境界？"]
    # 收起来的那句不能再拿来重来；还在回答的时候不能重来
    res = await client.post(
        f"/api/books/{bid}/notes", json={"content": "再来", "conv": conv, "rewind_from": first["id"]}
    )
    assert res.status_code == 404
    async with sessionmaker() as session:
        reply = await session.get(MeetingMessage, (await reply_of(client, bid, again["id"]))["id"])
        reply.payload = {**reply.payload, "state": "thinking"}
        await session.commit()
    res = await client.post(
        f"/api/books/{bid}/notes", json={"content": "再来", "conv": conv, "rewind_from": again["id"]}
    )
    assert res.status_code == 409 and "先停下" in res.json()["detail"]


async def test_rewind_first_line_clears_title_and_summary(client, sessionmaker, redis):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "第一句是什么？")
    conv_id = first["payload"]["conv"]
    async with sessionmaker() as session:
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        conv.summary, conv.summarized_until = "聊过第一句", first["id"]
        await session.commit()
        await chat_convs.rewind(session, redis, bid, conv, first["id"])
        conv = await session.get(ChatConversation, uuid.UUID(conv_id))
        assert (conv.title, conv.summary, conv.summarized_until) == ("", "", 0)
        assert not await dialogue(session, bid, "group", conv=conv_id)


async def test_archive_hides_and_speaking_restores(client, sessionmaker):
    bid = await seed(sessionmaker)
    a = (await say(client, bid, "楚风现在什么境界？"))["payload"]["conv"]
    b = (await client.post(f"/api/books/{bid}/chat/conversations")).json()["id"]
    await say(client, bid, "主角叫什么？", conv=b)
    # 归档现在聊的那一段：现在聊的换成另一段，归档的还列着、带 archived
    assert (await client.post(f"/api/books/{bid}/chat/conversations/{b}/archive")).status_code == 200
    listing = await convs(client, bid)
    assert [(c["id"], c["current"], c["archived"]) for c in listing] == [(b, False, True), (a, True, False)]
    # 编辑部干活的进度、旧版不给 conv 的话都记在没归档的那一段
    assert (await say(client, bid, "他下一步干什么？"))["payload"]["conv"] == a
    # 在归档的那一段再说话：自动取消归档，又成了最近聊的
    assert (await say(client, bid, "主角多大？", conv=b))["payload"]["conv"] == b
    listing = await convs(client, bid)
    assert [(c["id"], c["current"], c["archived"]) for c in listing] == [(b, True, False), (a, False, False)]
    # 全都归档了：开一段新的当现在聊的
    for conv in (a, b):
        await client.post(f"/api/books/{bid}/chat/conversations/{conv}/archive")
    listing = await convs(client, bid)
    assert listing[0]["current"] and listing[0]["id"] not in (a, b) and not listing[0]["archived"]
    assert (await client.post(f"/api/books/{bid}/chat/conversations/{a}/unarchive")).status_code == 200
    assert not next(c for c in await convs(client, bid) if c["id"] == a)["archived"]
    assert (await client.post(f"/api/books/{bid}/chat/conversations/{uuid.uuid4()}/archive")).status_code == 404


async def test_delete_removes_the_chat_not_the_book(client, sessionmaker):
    bid = await seed(sessionmaker)
    first = await say(client, bid, "楚风的性格改成冷静沉稳")
    a = first["payload"]["conv"]
    b = (await client.post(f"/api/books/{bid}/chat/conversations")).json()["id"]
    kept = await say(client, bid, "主角叫什么？", conv=b)
    # 这一段还在回答：不能删
    async with sessionmaker() as session:
        reply = await session.get(MeetingMessage, (await reply_of(client, bid, first["id"]))["id"])
        reply.payload = {**reply.payload, "state": "streaming"}
        await session.commit()
    res = await client.delete(f"/api/books/{bid}/chat/conversations/{a}")
    assert res.status_code == 409 and "先停下" in res.json()["detail"]
    async with sessionmaker() as session:
        reply = await session.get(MeetingMessage, reply.id)
        reply.payload = {**reply.payload, "state": "done"}
        await session.commit()
    res = await client.delete(f"/api/books/{bid}/chat/conversations/{a}")
    assert res.status_code == 200 and res.json()["removed"] >= 2
    left = await messages(client, bid)
    assert all((m["payload"] or {}).get("conv") != a for m in left)
    assert any(m["id"] == kept["id"] for m in left)
    assert [c["id"] for c in await convs(client, bid)] == [b]
    async with sessionmaker() as session:
        # 只删聊天：书不动，那句话改的地方照样在
        hero = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "楚风"))
        assert hero.personality
    assert (await client.delete(f"/api/books/{bid}/chat/conversations/{a}")).status_code == 404


async def test_old_page_reset_starts_a_new_conversation(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "楚风现在什么境界？")
    res = await client.post(f"/api/books/{bid}/chat/group/reset")
    assert res.status_code == 200
    listing = await convs(client, bid)
    assert len(listing) == 2 and listing[0]["id"] != note["payload"]["conv"] and listing[0]["current"]
    # 旧版不给 conv：发在最近聊的那一段
    later = await say(client, bid, "主角叫什么？")
    assert later["payload"]["conv"] == listing[0]["id"]
    # 私聊不分段
    private = await client.post(f"/api/books/{bid}/notes", json={"content": "你好", "to": "chief"})
    assert "conv" not in private.json()["payload"]


@pytest.mark.parametrize("reset", [0, 3])
async def test_migration_backfills_old_group_chat(sessionmaker, reset):
    spec = importlib.util.spec_from_file_location("conv_migration", Path("alembic/versions/0019_chat_conversations.py"))
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0019" and migration.down_revision == "0018"
    book = uuid.uuid4()
    async with sessionmaker() as session:
        connection = await session.connection()

        def migrate(sync):
            sync.execute(sa.text("CREATE SCHEMA conv_migration_test"))
            sync.execute(sa.text("SET LOCAL search_path TO conv_migration_test"))
            sync.execute(sa.text("CREATE TABLE books (id uuid PRIMARY KEY)"))
            sync.execute(
                sa.text(
                    "CREATE TABLE meeting_messages (id bigint PRIMARY KEY, book_id uuid, speaker text, kind text, "
                    "content text, payload jsonb, job_id uuid, created_at timestamptz DEFAULT now())"
                )
            )
            sync.execute(
                sa.text(
                    "CREATE TABLE chat_threads (book_id uuid, thread text, reset_after bigint, summary text, "
                    "summarized_until bigint)"
                )
            )
            sync.execute(sa.text("INSERT INTO books VALUES (:b)"), {"b": book})
            rows = [
                (1, "author", "note", "换话题之前说的第一句话，比较长比较长比较长", None),
                (2, "chief", "speech", "答", '{"reply_to": [1]}'),
                (3, "system", "status", "进度", "null"),
                (4, "author", "note", "后来的话", None),
                (5, "chief", "speech", "私聊", '{"thread": "chief"}'),
            ]
            for i, speaker, kind, content, payload in rows:
                sync.execute(
                    sa.text("INSERT INTO meeting_messages VALUES (:i, :b, :s, :k, :c, CAST(:p AS jsonb))"),
                    {"i": i, "b": book, "s": speaker, "k": kind, "c": content, "p": payload},
                )
            sync.execute(
                sa.text("INSERT INTO chat_threads VALUES (:b, 'group', :r, '摘要', 4)"), {"b": book, "r": reset}
            )
            migration.op = Operations(MigrationContext.configure(sync))
            migration.upgrade()
            convs = sync.execute(
                sa.text(
                    "SELECT id, title, summary, summarized_until FROM chat_conversations ORDER BY created_at, title"
                )
            ).all()
            stamped = dict(sync.execute(sa.text("SELECT id, payload FROM meeting_messages")).all())
            assert "conv" not in stamped[5]
            if reset:
                assert len(convs) == 2
                long = migration.title_of(rows[0][3])
                assert long.endswith("…") and len(long) == migration.TITLE_LIMIT + 1
                old, new = sorted(convs, key=lambda c: c.title != long)
                assert (old.title, old.summary, new.title, new.summary) == (
                    long,
                    "",
                    "后来的话",
                    "摘要",
                )
                assert [stamped[i]["conv"] for i in (1, 2, 3)] == [str(old.id)] * 3
                assert stamped[4]["conv"] == str(new.id)
            else:
                assert len(convs) == 1 and convs[0].summary == "摘要"
                assert {stamped[i]["conv"] for i in (1, 2, 3, 4)} == {str(convs[0].id)}
            # 原来是 JSON null 的也补成了对象
            assert stamped[3] == {"conv": stamped[3]["conv"]} and stamped[2]["reply_to"] == [1]
            migration.downgrade()
            assert all(
                "conv" not in (p or {}) for p in sync.execute(sa.text("SELECT payload FROM meeting_messages")).scalars()
            )

        await connection.run_sync(migrate)
        await session.rollback()
