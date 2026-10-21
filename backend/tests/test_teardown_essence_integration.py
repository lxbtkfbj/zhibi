"""精髓的产品接缝：收尾、摘要、只读接口、重跑和边读边记。"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.graphs.deps import cancel_key
from app.main import create_app
from app.models import Book, Chapter, Character, Job, MeetingMessage
from app.services import teardown_closing as closing
from app.services import teardown_essence as essence_module
from app.services import teardown_rerun
from app.services.teardown_chat import book_info
from app.services.teardown_info import needs_closing, teardown_summary
from app.services.teardown_runner import Runner
from tests.test_teardown_closing import fast_prompts, runner_for  # noqa: F401
from tests.test_teardown_runner import DemoRouter, create_book


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(redis):
    app = create_app()
    app.state.redis = redis
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def section():
    return {
        "name": "情节怎么想",
        "points": [
            {"title": "一招：接着来", "steps": ["先做", "再做"], "evidence": "第 1 章", "note": "", "chapters": [1]}
        ],
        "missing": [],
        "fixes": ["内部"],
    }


def test_needs_closing_and_summary_hide_old_merits_and_internal_state():
    meta = {"stage": "stopped", "settings": {"upto": 3}, "waits": {"upto": 3}}
    assert needs_closing(meta, 3, 8)
    data = {
        "upto": 3,
        "sections": {"source": section(), "cast": {"figures": [{"name": "甲"}], "points": []}},
        "failed": False,
    }
    meta["essence"] = data
    assert not needs_closing(meta, 3, 8)
    data["failed"] = True
    assert needs_closing(meta, 3, 8)
    data["failed"] = False
    data["upto"] = 2
    assert needs_closing(meta, 3, 8)
    meta["merits"] = {"points": ["旧数据留在库里"]}
    book = SimpleNamespace(source="teardown", teardown=meta)
    out = teardown_summary(book, read=3, last_read=3).model_dump()
    assert "merits" not in out and out["essence"] == {"upto": 2, "points": 2}
    assert meta["merits"] == {"points": ["旧数据留在库里"]}
    assert teardown_summary(SimpleNamespace(source="new")) is None


async def test_essence_api_exact_payload_and_character_order_only_teardown(sessionmaker, client):
    async with sessionmaker() as session:
        book = Book(source="teardown", title="原书", teardown={"stage": "stopped"})
        author = Book(source="new", title="作者书")
        session.add_all([book, author])
        await session.flush()
        for bid in (book.id, author.id):
            session.add_all(
                [Character(book_id=bid, name="先创建", position=8), Character(book_id=bid, name="主角", position=0)]
            )
        await session.commit()
        bid, aid = book.id, author.id
    assert (await client.get(f"/api/books/{bid}/teardown/essence")).json() == {"essence": None}
    assert (await client.get(f"/api/books/{aid}/teardown/essence")).status_code == 404
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {
            **book.teardown,
            "essence": {
                "upto": 3,
                "at": "时间",
                "overview": {"genre": "类型", "engine": "发动机", "points": []},
                "sections": {"source": section(), "empty": {"points": [], "missing": ["没有"]}},
                "rails": {"hero": "主角"},
                "inputs": {"secret": "不返回"},
                "failed": True,
                "scene_parts": {"内部": {}},
            },
        }
        await session.commit()
    response = (await client.get(f"/api/books/{bid}/teardown/essence")).json()["essence"]
    assert set(response) == {"upto", "at", "overview", "sections", "rails"}
    assert list(response["sections"]) == ["source"]
    assert set(response["sections"]["source"]) == {"name", "points", "missing"}
    assert [c["name"] for c in (await client.get(f"/api/books/{bid}/bible")).json()["characters"]] == ["主角", "先创建"]
    assert [c["name"] for c in (await client.get(f"/api/books/{aid}/bible")).json()["characters"]] == ["先创建", "主角"]
    assert (await client.get(f"/api/books/{uuid.uuid4()}/teardown/essence")).status_code == 404


def test_book_info_appends_exact_essence_block():
    book = SimpleNamespace(
        title="原书",
        teardown={
            "stage": "stopped",
            "essence": {
                "upto": 3,
                "overview": {
                    "genre": "这是什么书",
                    "engine": "靠什么追",
                    "points": [{"title": "第一招"}, {"title": "第二招"}],
                },
            },
        },
    )
    chapters = [SimpleNamespace(index=3, word_count=10, teardown={"read_version": 1})]
    assert book_info(book, chapters, [], []).endswith(
        "\n精髓（基于前 3 章）：这是什么书\n一句话：靠什么追\n核心要点：1. 第一招；2. 第二招"
    )


async def test_finish_exact_order_note_and_message(sessionmaker, redis, monkeypatch):
    runner = await runner_for(sessionmaker, redis, volumes=3)
    seen = []

    def fake(name, result):
        async def collect(*args, **kwargs):
            seen.append(name)
            return result

        return collect

    monkeypatch.setattr(closing, "collect_arcs", fake("arcs", {"count": 2}))
    monkeypatch.setattr(closing, "collect_ending", fake("ending", {"ended": False}))
    monkeypatch.setattr(
        "app.services.teardown_settings.collect_settings", fake("settings", {"characters": 1, "entries": 2})
    )
    monkeypatch.setattr(closing, "collect_waits", fake("waits", {"upto": 6, "total": 5, "open": 2}))
    monkeypatch.setattr(essence_module, "collect_essence", fake("essence", {"sections": 12, "points": 48}))
    await runner.finish()
    assert seen == ["arcs", "ending", "settings", "waits", "essence"]
    async with sessionmaker() as session:
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.job_id == runner.job_id))
        assert (
            "读者在等的事整理到第 6 章：一共 5 件，还吊着 2 件。整理了精髓：12 节、48 条知识点，在「精髓」那一页。"
            in message.content
        )
        assert "这本书好在哪" not in message.content
    monkeypatch.setattr(essence_module, "collect_essence", AsyncMock(side_effect=ValueError("格式错")))
    await runner.finish()
    book = (await runner.snapshot())[0]
    assert book.teardown["stop_note"] == "整理精髓没做完（格式错），点「补上整理」再试一次。"
    assert book.teardown["essence"]["failed"] is True and needs_closing(book.teardown, 6, 6)


async def test_author_stop_never_collects_essence(sessionmaker, redis, monkeypatch):
    runner = await runner_for(sessionmaker, redis)
    collect = AsyncMock(side_effect=AssertionError("停下不能整理"))
    monkeypatch.setattr(essence_module, "collect_essence", collect)
    await redis.set(cancel_key(runner.job_id), "1")
    await runner.finish()
    collect.assert_not_awaited()


@pytest.mark.parametrize("step", ["merge", "tags", "unitplot", "essence", "essence:source", "essence:scene"])
async def test_rerun_new_steps_only_selected_and_force(sessionmaker, redis, monkeypatch, step):
    from tests.test_teardown_rerun import seed

    bid = await seed(sessionmaker)
    module, func = (
        ("app.services.teardown_merge", "collect_merge")
        if step == "merge"
        else ("app.services.teardown_essence", "collect_" + (step if step in ("tags", "unitplot") else "essence"))
    )
    collect = AsyncMock(return_value={})
    monkeypatch.setattr(module + "." + func, collect)
    async with sessionmaker() as session:
        info = await teardown_rerun.plan(session, bid, step, None, None)
        assert info["calls"] >= 0
        with pytest.raises(Exception, match="不接受 --from 或 --to"):
            await teardown_rerun.plan(session, bid, step, 1, None)
        job = await teardown_rerun.prepare(session, bid, step, None, None, force=True)
        jid = job.id
    await teardown_rerun.run_rerun(jid, sessionmaker, redis, DemoRouter())
    expected = {"force": True}
    if step.startswith("essence"):
        expected["only"] = step.partition(":")[2] or None
    assert collect.await_args.kwargs == expected
    async with sessionmaker() as session:
        assert (await session.get(Job, jid)).status == "succeeded"
        for invalid in ("merits", "essence:unknown"):
            with pytest.raises(Exception, match="步骤只能是"):
                await teardown_rerun.plan(session, bid, invalid, None, None)


async def test_live_waits_same_batches_as_final_and_never_cross_unread_gap(sessionmaker, redis):
    bid, jid = await create_book(sessionmaker, count=172, read=True)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    original = closing.wait_batches((await runner.snapshot())[1])
    assert [(b[0].index, b[-1].index) for b in original] == [(1, 80), (81, 160), (161, 172)]
    attempted = set()
    await closing.collect_waits(runner, full_only=True, attempted=attempted)
    assert attempted == {(1, 80), (81, 160)}
    assert (await runner.snapshot())[0].teardown["waits"]["upto"] == 160
    await closing.collect_waits(runner)
    assert (await runner.snapshot())[0].teardown["waits"]["upto"] == 172
    assert len(runner.router.calls) == 3
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        meta = dict(book.teardown)
        meta.pop("waits")
        book.teardown = meta
        chapter = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 5))
        chapter.teardown = {}
        await session.commit()
    runner.router.calls.clear()
    await closing.collect_waits(runner, full_only=True, attempted=set())
    assert not runner.router.calls


async def test_live_wait_failure_does_not_retry_same_segment_until_finish(sessionmaker, redis, monkeypatch):
    bid, jid = await create_book(sessionmaker, count=85, read=True)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    calls = AsyncMock(side_effect=ValueError("坏账"))
    monkeypatch.setattr(runner, "call_user", calls)
    attempted = set()
    with pytest.raises(ValueError, match="三次都对不上"):
        await closing.collect_waits(runner, full_only=True, attempted=attempted)
    assert calls.await_count == 3
    await closing.collect_waits(runner, full_only=True, attempted=attempted)
    assert calls.await_count == 3
    assert "waits" not in (await runner.snapshot())[0].teardown
    monkeypatch.setattr(runner, "call_user", Runner.call_user.__get__(runner))
    await closing.collect_waits(runner)
    assert (await runner.snapshot())[0].teardown["waits"]["upto"] == 85


async def test_grouping_live_wait_error_is_logged_not_stopped(sessionmaker, redis, monkeypatch):
    bid, jid = await create_book(sessionmaker, count=85, read=True)
    runner = Runner(jid, sessionmaker, redis, DemoRouter())
    await runner.initialize()
    monkeypatch.setattr(runner, "volumes_once", AsyncMock(return_value=False))
    monkeypatch.setattr(runner, "group_once", AsyncMock(return_value=False))

    async def bad(*args, **kwargs):
        runner.reading_done = True
        runner.changed.set()
        raise ValueError("这段失败不阻止读原文")

    monkeypatch.setattr(closing, "collect_waits", bad)
    runner.changed.set()
    await asyncio.wait_for(runner.grouping(), timeout=10)
    assert runner.stop is None
