"""第三包任务 2：直调演示模型、局部回填、群聊分流和失败边界。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.api import library_ai
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import AuthorRequirement, Book, Character, Job, MeetingMessage, SettingCandidate, WorldEntry
from app.services.versions import snapshot_of


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def seed(sessionmaker, *, locked=False):
    async with sessionmaker() as session:
        book = Book(title="测试书", genre="玄幻", concept={"story": "少年掌控灵海。"})
        session.add(book)
        await session.flush()
        entry = WorldEntry(
            book_id=book.id,
            name="境界",
            category="等级体系",
            style="ladder",
            locked=locked,
            content="灵海是修行根本。",
            one_line="由低到高",
            levels=[
                {"name": "灵海", "text": "灵海纳百川。旧句不动。"},
                {"name": "登天", "text": "下一层不动。"},
            ],
        )
        character = Character(book_id=book.id, name="楚风", role_type="主角", want="守住旧状态")
        session.add_all([entry, character])
        await session.commit()
        return book.id, entry.id, character.id


def rewrite_body(entry_id, **kwargs):
    return {"target_type": "entry", "target_id": str(entry_id), "path": "levels.0.text", "mode": "options", **kwargs}


async def test_options_preserve_target_and_all_option_fields(client, sessionmaker):
    book_id, entry_id, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        before = snapshot_of(await session.get(WorldEntry, entry_id))
    response = await client.post(f"/api/books/{book_id}/library/rewrite", json=rewrite_body(entry_id))
    assert response.status_code == 200, response.text
    candidate = response.json()["candidate"]
    assert candidate["base"] == "灵海纳百川。旧句不动。"
    assert [row["label"] for row in candidate["options"]] == ["稳妥", "大胆", "出格"]
    assert all(set(row) == {"label", "text", "renamed", "one_line"} for row in candidate["options"])
    assert candidate["options"][1]["renamed"] == [{"old": "灵海", "new": "灵渊"}]
    async with sessionmaker() as session:
        assert snapshot_of(await session.get(WorldEntry, entry_id)) == before
        messages = list(await session.scalars(select(MeetingMessage)))
        assert messages[-1].job_id is None and messages[-1].speaker == "lorekeeper"


@pytest.mark.parametrize("mode", ["instruction", "expand", "shorten"])
@pytest.mark.parametrize("path", ["levels.0.text", "levels.0.text@0:6"])
async def test_only_selected_text_changes_and_version_reverts(client, sessionmaker, mode, path):
    book_id, entry_id, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        before = snapshot_of(await session.get(WorldEntry, entry_id))
    response = await client.post(
        f"/api/books/{book_id}/library/rewrite",
        json=rewrite_body(entry_id, path=path, mode=mode, instruction="保持意思，写得清楚"),
    )
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        after = snapshot_of(await session.get(WorldEntry, entry_id))
    expected = before["levels"][0]["text"]
    expected = expected[:6] + "（已按要求修改）" + expected[6:] if "@" in path else expected + "（已按要求修改）"
    assert after["levels"][0]["text"] == expected
    after["levels"][0]["text"] = before["levels"][0]["text"]
    assert after == before
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={entry_id}")).json()
    assert len(versions) == 2 and versions[0]["source"] == "ai"
    assert (await client.post(f"/api/versions/{versions[-1]['id']}/revert")).status_code == 200
    async with sessionmaker() as session:
        assert snapshot_of(await session.get(WorldEntry, entry_id)) == before


async def test_validation_and_ownership(client, sessionmaker):
    book_id, entry_id, char_id = await seed(sessionmaker, locked=True)
    url = f"/api/books/{book_id}/library/rewrite"
    response = await client.post(url, json=rewrite_body(entry_id))
    assert response.status_code == 409 and response.json()["detail"] == "已锁：AI 不能改这一处，先解锁"
    response = await client.post(url, json=rewrite_body(entry_id, mode="instruction", instruction="  "))
    assert response.status_code == 422 and response.json()["detail"] == "先写一句你想怎么改"
    for path in ("want", "location", "condition", "is_alive", "book_id"):
        response = await client.post(url, json=rewrite_body(char_id, target_type="character", path=path))
        assert response.status_code == 422
    another_book, _, _ = await seed(sessionmaker)
    response = await client.post(f"/api/books/{another_book}/library/rewrite", json=rewrite_body(entry_id))
    assert response.status_code == 404


async def test_stale_and_relocked_during_model_call_do_not_overwrite(client, sessionmaker, monkeypatch):
    book_id, entry_id, _ = await seed(sessionmaker)

    async def changed(*args, **kwargs):
        async with sessionmaker() as session:
            entry = await session.get(WorldEntry, entry_id)
            entry.content = "作者已经改过"
            await session.commit()
        return s.RewriteOne(text="AI迟到的内容")

    monkeypatch.setattr(library_ai, "call_model", changed)
    response = await client.post(
        f"/api/books/{book_id}/library/rewrite", json=rewrite_body(entry_id, mode="expand", path="content")
    )
    assert response.status_code == 409 and "原文已经改过" in response.text
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, entry_id)).content == "作者已经改过"

    async def relocked(*args, **kwargs):
        async with sessionmaker() as session:
            (await session.get(WorldEntry, entry_id)).locked = True
            await session.commit()
        return s.RewriteOne(text="不能写入")

    monkeypatch.setattr(library_ai, "call_model", relocked)
    response = await client.post(
        f"/api/books/{book_id}/library/rewrite", json=rewrite_body(entry_id, mode="shorten", path="content")
    )
    assert response.status_code == 409 and "已锁" in response.text


async def test_router_closes_on_failure_and_returns_502(client, sessionmaker, monkeypatch):
    book_id, entry_id, _ = await seed(sessionmaker)
    closed = []

    class BrokenRouter:
        def __init__(self, *args, **kwargs):
            assert kwargs == {"book_id": book_id}

        async def structured(self, *args, **kwargs):
            raise RuntimeError("测试故障")

        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(library_ai, "LLMRouter", BrokenRouter)
    response = await client.post(f"/api/books/{book_id}/library/rewrite", json=rewrite_body(entry_id))
    assert response.status_code == 502 and response.json()["detail"] == "模型出错了：测试故障"
    assert closed == [True]


async def test_fill_and_review_demo_and_unknown_category(client, sessionmaker, monkeypatch):
    book_id, _, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add(WorldEntry(book_id=book_id, category="特殊规则", name="厉鬼规则", content="厉鬼有代价。第二句。"))
        await session.commit()
    result = await client.post(f"/api/books/{book_id}/library/fill-gaps")
    assert result.status_code == 200, result.text
    rows = result.json()["suggestions"]
    assert [row["payload"]["op"] for row in rows] == ["create_entry", "create_character", "create_category"]
    for row in rows:
        response = await client.post(f"/api/suggestions/{row['id']}/accept")
        assert response.status_code == 200, response.text
    response = await client.post(f"/api/books/{book_id}/library/review")
    assert response.status_code == 200, response.text
    assert {row["payload"]["op"] for row in response.json()["suggestions"]} == {"splice", "note"}

    async def unknown(*args, **kwargs):
        return s.GapReport(
            entries=[s.NewEntry(category="未知分类", name="另一个", status="一句话就好", one_line="一句", why="补漏")]
        )

    monkeypatch.setattr(library_ai, "call_model", unknown)
    result = await client.post(f"/api/books/{book_id}/library/fill-gaps")
    assert result.json()["suggestions"][0]["payload"]["entry"]["category"] == "特殊规则"


async def test_check_scope_and_quote_missing_becomes_note(client, sessionmaker, monkeypatch):
    book_id, entry_id, _ = await seed(sessionmaker)

    async def review(*args, **values):
        assert values["scope"] == "只查这一条：等级体系 · 境界；需要时对照别的条目。"
        return s.LibraryReview(
            issues=[
                s.LibraryIssue(kind="矛盾", title="问题", target_name="境界", quote="不存在", fix="修正", why="原因")
            ]
        )

    monkeypatch.setattr(library_ai, "call_model", review)
    response = await client.post(
        f"/api/books/{book_id}/library/check", json={"target_type": "entry", "target_id": str(entry_id)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"][0]["payload"]["op"] == "note"


async def test_idle_chat_routes_rewrite_not_requirement_and_other_persists(client, sessionmaker):
    book_id, _, _ = await seed(sessionmaker)
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "把境界名称重想一下"})
    assert response.status_code == 201, response.text
    async with sessionmaker() as session:
        assert list(await session.scalars(select(AuthorRequirement))) == []
        assert len(list(await session.scalars(select(SettingCandidate)))) == 1
        messages = list(await session.scalars(select(MeetingMessage).order_by(MeetingMessage.id)))
        assert [row.speaker for row in messages] == ["author", "lorekeeper", "chief"]
        assert all(row.job_id is None for row in messages)
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "下一章节奏快一点"})
    assert response.status_code == 201, response.text
    async with sessionmaker() as session:
        assert [row.text for row in await session.scalars(select(AuthorRequirement))] == ["下一章节奏快一点"]


async def test_chat_target_missing_not_saved_as_requirement(client, sessionmaker, monkeypatch):
    from app.api import jobs as jobs_api

    book_id, _, _ = await seed(sessionmaker)

    async def missing(*args, **kwargs):
        return s.LibraryIntent(kind="改设定", target_name="不在库里", reply="定位中")

    monkeypatch.setattr(jobs_api, "call_model", missing)
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "改一下"})
    assert response.status_code == 201, response.text
    async with sessionmaker() as session:
        assert list(await session.scalars(select(AuthorRequirement))) == []
        message = await session.scalar(select(MeetingMessage).order_by(MeetingMessage.id.desc()))
        assert message.content == "没找到「不在库里」这一条。去设定库点那一处改，或者告诉我它在哪一类。"


@pytest.mark.parametrize("status", ["queued", "running", "waiting_author"])
async def test_busy_chat_does_not_route_but_direct_rewrite_is_allowed(client, sessionmaker, monkeypatch, status):
    from app.api import jobs as jobs_api

    book_id, entry_id, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add(Job(book_id=book_id, kind="write_book", status=status, thread_id=f"test-{uuid.uuid4()}"))
        await session.commit()

    async def unexpected(*args, **kwargs):
        pytest.fail("忙碌时不应调用群聊路由")

    monkeypatch.setattr(jobs_api, "call_model", unexpected)
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "改境界"})
    assert response.status_code == 201, response.text
    response = await client.post(f"/api/books/{book_id}/library/rewrite", json=rewrite_body(entry_id, mode="expand"))
    assert response.status_code == 200, response.text


async def test_chat_started_during_routing_returns_to_normal_note_path(client, sessionmaker, monkeypatch):
    from app.api import jobs as jobs_api

    book_id, _, _ = await seed(sessionmaker)

    async def started(*args, **kwargs):
        async with sessionmaker() as session:
            session.add(Job(book_id=book_id, kind="write_book", status="queued", thread_id="started-during-route"))
            await session.commit()
        return s.LibraryIntent(kind="改设定", target_name="境界", reply="改一下")

    monkeypatch.setattr(jobs_api, "call_model", started)
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "把境界重想一下"})
    assert response.status_code == 201, response.text
    async with sessionmaker() as session:
        assert list(await session.scalars(select(SettingCandidate))) == []
        assert [row.text for row in await session.scalars(select(AuthorRequirement))] == ["把境界重想一下"]
        message = await session.scalar(select(MeetingMessage))
        assert message.job_id is not None
