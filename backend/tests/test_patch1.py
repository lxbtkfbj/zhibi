"""第三包补丁 1：异步分流、显式方案落地与合并开书关的回归合同。"""

import ast
import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo_setup
from app.models import (
    Book,
    Chapter,
    Character,
    Job,
    LlmCall,
    LlmProfile,
    MeetingMessage,
    Memory,
    PlotUnit,
    RoleAssignment,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.schemas import NoteIn
from app.services import group_notes, jobs
from app.services.chat_context import accepts_plan, dialogue, obvious_question, wants_plan
from app.services.library_context import existing_text, load_context
from app.services.meeting import post_message
from app.services.setup_store_v3 import save_library_focus, save_library_rest
from tests.later_changes import with_later_changes
from tests.test_chat_task6 import client as _client  # noqa: F401
from tests.test_chat_task6 import final_message, seed
from tests.test_setup_puzzle_flow import flow as _flow
from tests.test_setup_puzzle_flow import legacy_piece_gates  # noqa: F401

client = _client
flow = _flow


@pytest.mark.parametrize("text", ["总结一下！", "归纳前面", "整理成方案", "出个方案", "列个方案", "汇总"])
def test_wants_plan(text):
    assert wants_plan(text)
    assert not wants_plan("长" * 41 + text)


@pytest.mark.parametrize("text", ["就按这个来。", "照这个办", "就这么定", "按方案来", "就按方案", "照方案"])
def test_accepts_plan(text):
    assert accepts_plan(text)
    assert not accepts_plan("长" * 21 + text)


@pytest.mark.parametrize(
    "text,asked",
    [
        ("楚风现在什么境界？", True),
        ("第三个单元为什么这样安排？", True),
        ("怎么写？", True),
        ("有什么漏洞？", True),
        ("下一章节奏快一点，行吗？", False),
        ("把境界名称换一套好不好？", False),
        ("以后慢点？", False),
        ("记住了吗？", False),
        ("帮我查设定？", False),
        ("这一段还行", False),
    ],
)
def test_question_shortcuts(text, asked):
    assert obvious_question(text) is asked


async def plan_for(sessionmaker, redis, bid, items, *, thread="group", status="open"):
    async with sessionmaker() as session:
        return await post_message(
            session,
            redis,
            book_id=bid,
            job_id=None,
            speaker="chief" if thread == "group" else thread,
            kind="plan",
            content="方案",
            payload={
                "plan": {
                    "title": "回归方案",
                    "summary": "按作者商量的完整内容落实，不丢细节。",
                    "items": [s.PlanItem(**item).model_dump() for item in items],
                    "open_questions": ["将来再定"],
                },
                "status": status,
                "results": [],
                **({"thread": thread} if thread != "group" else {}),
            },
        )


@pytest.fixture
async def redis():
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield client
    await client.aclose()


async def test_router_default_and_separate_model_and_shortcut(client, sessionmaker):
    from app.llm.router import LLMRouter

    async with sessionmaker() as session:
        default = LlmProfile(name="默认演示", provider="demo", model="default-demo")
        chief = LlmProfile(name="主编演示", provider="demo", model="chief-demo")
        session.add_all([default, chief])
        await session.flush()
        session.add_all(
            [RoleAssignment(role="default", profile_id=default.id), RoleAssignment(role="chief", profile_id=chief.id)]
        )
        await session.commit()
        assert (await LLMRouter(sessionmaker).resolve("router")).model == "default-demo"
        rid = str(default.id)
    assert (await client.put("/api/llm/roles", json={"router": rid})).status_code == 200
    assert (await client.get("/api/llm/roles")).json()["router"] == rid
    bid = await seed(sessionmaker)
    await client.post(f"/api/books/{bid}/notes", json={"content": "楚风现在什么境界？"})
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(LlmCall).where(LlmCall.role == "router")))
    await client.post(f"/api/books/{bid}/notes", json={"content": "下一章节奏快一点"})
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall).where(LlmCall.role == "router"))
        assert call.model == "default-demo" and call.purpose == "群聊分流"
        assert "主编" in call.request["system"]


async def test_pending_immediate_and_ordered_routing(sessionmaker, redis, monkeypatch):
    bid = await seed(sessionmaker, "running")
    tasks, ids = [], []
    original = group_notes.call_model
    ordered = []

    async def model(*args, **kwargs):
        ordered.append(kwargs["note"])
        return await original(*args, **kwargs)

    monkeypatch.setattr(group_notes, "call_model", model)
    for text in ("下一章快一点", "下一卷慢一点"):
        async with sessionmaker() as session:
            task = BackgroundTasks()
            result = await group_notes.receive_note(
                NoteIn(content=text), task, await session.get(Book, bid), session, redis
            )
            assert result.payload["outcome"] == {"kind": "pending"} and result.job_id is None
            ids.append(result.id)
            tasks.append(task)
    assert not ordered
    await asyncio.gather(*(task() for task in reversed(tasks)))
    assert ordered == ["下一章快一点", "下一卷慢一点"]
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(select(MeetingMessage).where(MeetingMessage.id.in_(ids)).order_by(MeetingMessage.id))
        )
        assert all(r.job_id and r.payload["outcome"]["kind"] == "to_job" for r in rows)
        requirements = list(await session.scalars(select(Memory).order_by(Memory.seq)))
        assert [r.message_id for r in requirements] == ids
    assert any(e[1]["event"] == "message_update" for e in await redis.xrange(f"zhibi:events:{bid}"))


async def test_routing_state_changed_too_late_failed_cleanup(client, sessionmaker, redis, monkeypatch):
    bid = await seed(sessionmaker)
    original = group_notes.call_model

    async def model(*args, **kwargs):
        result = await original(*args, **kwargs)
        async with sessionmaker() as session:
            session.add(
                Job(
                    book_id=bid,
                    kind="write_book",
                    thread_id="late",
                    status="waiting_author",
                    pending={"kind": "volume_review"},
                )
            )
            await session.commit()
        return result

    monkeypatch.setattr(group_notes, "call_model", model)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "下一章快一点"})
    assert (await final_message(client, bid, result.json()["id"]))["payload"]["outcome"]["kind"] == "requirement"
    async with sessionmaker() as session:
        assert [r.summary for r in await session.scalars(select(Memory))] == ["下一章快一点"]
        job = await session.scalar(select(Job))
        job.status = "succeeded"
        await session.commit()
    monkeypatch.setattr(group_notes, "call_model", original)
    result = await client.post(f"/api/books/{bid}/notes", json={"content": "测试分流出错，下一章快一点"})
    assert (await final_message(client, bid, result.json()["id"]))["payload"]["outcome"]["kind"] == "failed"
    async with sessionmaker() as session:
        row = MeetingMessage(
            book_id=bid,
            speaker="author",
            kind="note",
            content="遗留",
            payload={"outcome": {"kind": "pending"}},
            created_at=datetime.now(UTC) - timedelta(minutes=3),
        )
        session.add(row)
        await session.commit()
        mid = row.id
    await group_notes.clean_pending(redis)
    assert (await final_message(client, bid, mid))["payload"]["outcome"] == {"kind": "failed", "reason": "判断中断"}


@pytest.mark.parametrize("thread", [None, "lorekeeper"])
async def test_plan_generation_supersede_and_accepts_without_plan(client, sessionmaker, thread):
    bid = await seed(sessionmaker, "waiting_author")
    body = {"to": thread} if thread else {}
    before = await client.post(f"/api/books/{bid}/notes", json={"content": "就按这个来", **body})
    assert before.status_code == 201
    assert any(
        m["content"] == "还没有方案可以照办。想让我把前面聊的整理成方案，就说「总结一下」。"
        for m in (await client.get(f"/api/books/{bid}/meeting")).json()
    )
    await client.post(f"/api/books/{bid}/notes", json={"content": "帮我想想开篇", **body})
    for _ in range(2):
        result = await client.post(f"/api/books/{bid}/notes", json={"content": "总结一下前面聊的", **body})
        assert result.status_code == 201
    rows = (await client.get(f"/api/books/{bid}/meeting")).json()
    cards = [m for m in rows if m["kind"] == "plan"]
    assert [m["payload"]["status"] for m in cards] == ["superseded", "open"]
    async with sessionmaker() as session:
        assert not list(await session.scalars(select(Memory)))
        assert len([m for m in await dialogue(session, bid, thread or "group") if m.kind == "plan"]) == 2
    await client.post(f"/api/books/{bid}/chat/{thread or 'group'}/reset")
    await client.post(f"/api/books/{bid}/notes", json={"content": "总结一下新想法", **body})
    cards = [m for m in (await client.get(f"/api/books/{bid}/meeting")).json() if m["kind"] == "plan"]
    assert [m["payload"]["status"] for m in cards] == ["superseded", "superseded", "open"]


async def test_waiting_after_chat_makes_plan_not_feedback(client, sessionmaker):
    bid = await seed(sessionmaker, "waiting_author")
    await client.post(f"/api/books/{bid}/notes", json={"content": "第三个单元为什么这样安排？"})
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "就用方向一"})
    assert response.status_code == 201, response.text
    final = await final_message(client, bid, response.json()["id"])
    assert final["payload"]["outcome"]["kind"] == "requirement"
    async with sessionmaker() as session:
        assert (await session.scalar(select(Job))).status == "waiting_author"
        assert [r.summary for r in await session.scalars(select(Memory))] == ["就用方向一"]


@pytest.mark.parametrize(
    "pending,label,action",
    [
        ({"kind": "setup_piece", "piece": "outline"}, "改大纲", "revise"),
        ({"kind": "segment_review", "flow": 3}, "重出这一篇", "revise"),
        ({"kind": "volume_review"}, "改卷纲", "revise"),
        ({"kind": "chapters_review"}, "重出章纲", "revise"),
    ],
)
async def test_plan_feedback_full_and_only_requirements_persist(
    client, sessionmaker, redis, monkeypatch, pending, label, action
):
    bid = await seed(
        sessionmaker, "waiting_author", "book_setup" if pending["kind"].startswith("setup") else "write_book"
    )
    async with sessionmaker() as session:
        job = await session.scalar(select(Job))
        job.pending = pending
        await session.commit()
    queued = []

    def enqueue(jid, resume=None):
        queued.append(resume)

    monkeypatch.setattr(jobs, "enqueue", enqueue)
    card = await plan_for(
        sessionmaker,
        redis,
        bid,
        [
            {"where": "定调", "change": "完整的新故事细节"},
            {"where": "写作要求", "change": "只影响下一章", "scope": "只管下一章"},
        ],
    )
    response = await client.post(f"/api/plans/{card['id']}/apply")
    assert response.status_code == 202, response.text
    assert queued[0]["action"] == action and "完整的新故事细节" in queued[0]["feedback"]
    assert (
        "【和作者商量定的方案：回归方案】" in queued[0]["feedback"]
        and "还没定的（先不用管）：将来再定" in queued[0]["feedback"]
    )
    result = (await final_message(client, bid, card["id"]))["payload"]
    assert result["status"] == "applied" and result["results"][0]["label"] == f"已交给编辑部：{label}"
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Memory)))
        assert [(r.text, r.source, r.scope) for r in rows] == [("只影响下一章", "方案卡", "chapter")]
    assert (await client.post(f"/api/plans/{card['id']}/apply")).status_code == 409


async def test_apply_each_kind_and_undo_created_guards(client, sessionmaker, redis):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        arc = StoryNode(book_id=bid, position=1, kind="milestone", title="第一篇", segment={"text": "旧篇"})
        session.add(arc)
        await session.flush()
        volume = Volume(book_id=bid, index=1, title="卷", summary="旧卷", target_node_id=arc.id)
        session.add(volume)
        await session.flush()
        session.add(PlotUnit(book_id=bid, volume_id=volume.id, index=1, title="试炼", summary="旧单元"))
        await session.commit()
    items = [
        {"where": "定调", "change": "改故事"},
        {"where": "设定库", "target": "境界", "part": "一段话", "change": "改境界"},
        {"where": "设定库", "target": "老怪", "category": "角色卡片", "change": "作者看过的师父。"},
        {"where": "设定库", "target": "旧钟", "category": "不存在", "change": "钟声能救命。"},
        {"where": "大纲", "target": "第 1 篇", "change": "改篇"},
        {"where": "大纲", "target": "第 1 卷", "change": "改卷"},
        {"where": "大纲", "target": "单元「试炼」", "change": "改单元"},
        {"where": "大纲", "target": "结局", "change": "改结局"},
        {"where": "写作要求", "change": "写快点", "scope": "只管这一卷"},
    ]
    card = await plan_for(sessionmaker, redis, bid, items)
    response = await client.post(f"/api/plans/{card['id']}/apply")
    assert response.status_code == 202, response.text
    results = (await final_message(client, bid, card["id"]))["payload"]["results"]
    # 第五步第三批起和聊天里动手同一套：大纲走「写大纲」（结局也能写），新建由设定师照这一类的栏目写，
    # 类别对不上的放进特殊规则；每一条都有前后对照，能换回原来的
    assert [r["kind"] for r in results] == [
        "edit",
        "edit",
        "created",
        "created",
        "outline",
        "outline",
        "outline",
        "outline",
        "requirement",
    ], results
    assert all(r["diff"] and r["change"] for r in results if r["kind"] != "requirement")
    assert results[8]["memory"]["summary"]
    assert "change" not in results[8]
    # 从后往前换回：结局和简介都在书那一行里，先换回后改的
    memory = results[8]["memory"]
    response = await client.post(f"/api/books/{bid}/memories/{memory['id']}/undo", json={"version": memory["version"]})
    assert response.status_code == 200
    for step in (7, 6, 5, 4, 2, 1, 0):
        response = await client.post(f"/api/books/{bid}/notes/{card['id']}/revert", json={"step": step})
        assert response.status_code == 200, (step, response.text)
    async with sessionmaker() as session:
        assert await session.scalar(select(Character).where(Character.name == "老怪")) is None
        assert (await session.get(Volume, volume.id)).summary == "旧卷"
    created = results[3]
    assert (
        await client.patch(f"/api/world-entries/{created['target_id']}", json={"content": "作者改过"})
    ).status_code == 200
    response = await client.post(f"/api/books/{bid}/notes/{card['id']}/revert", json={"step": 3})
    assert response.status_code == 409 and "后来又改过" in response.json()["detail"]


@pytest.mark.parametrize("protection", ["busy", "locked", "written"])
async def test_plan_protections_create_suggestions(client, sessionmaker, redis, protection):
    bid = await seed(sessionmaker, "running" if protection == "busy" else "idle")
    async with sessionmaker() as session:
        entry = await session.scalar(select(WorldEntry))
        entry.locked = protection == "locked"
        vol = Volume(book_id=bid, index=1, title="卷", summary="旧卷", locked=protection == "locked")
        session.add(vol)
        await session.flush()
        if protection == "written":
            session.add(Chapter(book_id=bid, index=1, volume_id=vol.id, status="drafting"))
        await session.commit()
    items = [
        {"where": "设定库", "target": "境界", "change": "改设定"},
        {"where": "大纲", "target": "第 1 卷", "change": "改卷"},
        {"where": "写作要求", "change": "节奏快"},
    ]
    card = await plan_for(sessionmaker, redis, bid, items)
    await client.post(f"/api/plans/{card['id']}/apply")
    results = (await final_message(client, bid, card["id"]))["payload"]["results"]
    # 编辑部正在写时，写作要求交给正在干活的编辑部（第五步第三批起和聊天里说的一样）
    assert [r["kind"] for r in results] == (
        ["edit", "suggestion", "requirement"]
        if protection == "written"
        else ["suggestion", "suggestion", "to_job" if protection == "busy" else "requirement"]
    )


async def test_apply_keeps_going_after_failure_and_rechecks_working(client, sessionmaker, redis, monkeypatch):
    from app.services import chat_plans

    bid = await seed(sessionmaker)
    original = chat_plans.apply_item
    seen = []

    async def applying(session, redis, book_id, message_id, title, item):
        seen.append(item["change"])
        if item["change"] == "这一条模型出错":
            raise RuntimeError("模型只调用一次就报错")
        result = await original(session, redis, book_id, message_id, title, item)
        if item["change"] == "先记要求":
            session.add(Job(book_id=bid, thread_id="new-work", kind="write_book", status="running"))
        return result

    monkeypatch.setattr(chat_plans, "apply_item", applying)
    card = await plan_for(
        sessionmaker,
        redis,
        bid,
        [
            {"where": "设定库", "target": "境界", "change": "这一条模型出错"},
            {"where": "写作要求", "change": "先记要求"},
            {"where": "设定库", "target": "另一条", "change": "不能在工作中建库"},
            {"where": "写作要求", "change": "工作中继续记要求"},
        ],
    )
    assert (await client.post(f"/api/plans/{card['id']}/apply")).status_code == 202
    result = (await final_message(client, bid, card["id"]))["payload"]
    assert result["status"] == "applied"
    assert [r["kind"] for r in result["results"]] == ["failed", "requirement", "suggestion", "to_job"]
    assert len(seen) == 4  # No retry, later items still run.


async def test_suggestion_is_not_consumed_before_async_routing_succeeds(client, sessionmaker):
    from app.models import SettingSuggestion

    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        row = SettingSuggestion(
            book_id=bid,
            kind="chat",
            title="保留失败的建议",
            payload={"op": "note", "content": "测试分流出错，下一章快一点"},
        )
        session.add(row)
        await session.commit()
        sid = row.id
    assert (await client.post(f"/api/suggestions/{sid}/run-chat")).status_code == 409
    async with sessionmaker() as session:
        assert (await session.get(SettingSuggestion, sid)).status == "pending"


async def test_plan_edit_stays_undoable_when_followup_review_fails(client, sessionmaker, redis, monkeypatch):
    from fastapi import HTTPException

    from app.api import library_ai
    from app.models import SettingSuggestion

    bid = await seed(sessionmaker)
    original = library_ai.call_model
    attempts = []

    async def model(book_id, role, schema, template, **kwargs):
        if schema is s.LibraryReview:
            attempts.append(kwargs.get("single_attempt"))
            raise HTTPException(502, "连带检查模型出错")
        return await original(book_id, role, schema, template, **kwargs)

    monkeypatch.setattr(library_ai, "call_model", model)
    card = await plan_for(
        sessionmaker,
        redis,
        bid,
        [{"where": "定调", "change": "故事更偏复仇"}, {"where": "写作要求", "change": "节奏快"}],
    )
    assert (await client.post(f"/api/plans/{card['id']}/apply")).status_code == 202
    results = (await final_message(client, bid, card["id"]))["payload"]["results"]
    assert [r["kind"] for r in results] == ["edit", "requirement"], results
    # 第五步第三批起方案卡和聊天里改简介是同一条路，连带检查照常重试几次
    assert attempts == [None]
    async with sessionmaker() as session:
        assert "已按要求修改" in (await session.get(Book, bid)).concept["story"]
        warning = await session.scalar(select(SettingSuggestion).where(SettingSuggestion.kind == "concept"))
        assert "连带检查没做成" in warning.title
    monkeypatch.setattr(library_ai, "call_model", original)
    assert (await client.post(f"/api/versions/{results[0]['revert_version_id']}/revert")).status_code == 200
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).concept["story"] == "楚风找回青灯。"


@pytest.mark.parametrize("mode", ["puzzle", "oneshot"])
@pytest.mark.usefixtures("legacy_piece_gates", "legacy_prefill")
async def test_legacy_prefill_start_only_here_and_chat_does_not_resume(flow, mode):
    created = await flow("POST", "/books", {"idea": "先写设定", "mode": mode, "prefill": True})
    bid, jid = created["book"]["id"], created["job"]["id"]
    await flow("POST", f"/books/{bid}/notes", {"content": "下一章快一点"})
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["kind"] == "setup_prefill"
    assert (await flow("GET", f"/books/{bid}/memories"))[-1]["detail"] == "下一章快一点"
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "start"})
    response = await flow.client.post(f"/api/jobs/{jid}/pitches", json={"action": "start"})
    assert response.status_code == 422
    job = await flow("GET", f"/jobs/{jid}")
    assert job["pending"]["kind"] == ("setup_pitches" if mode == "puzzle" else "setup_piece")
    if mode == "oneshot":
        assert job["pending"]["piece"] == "outline"


@pytest.fixture
def legacy_prefill(monkeypatch):
    """仅构造已经停在旧 setup_prefill 的检查点；新任务不再走这里。"""
    from app.graphs import book_setup

    monkeypatch.setattr(book_setup, "route_start", lambda state: "prefill_gate" if state.get("prefill") else "pitches")


@pytest.mark.usefixtures("legacy_piece_gates", "legacy_prefill")
async def test_legacy_prefill_combined_and_existing_text(flow, sessionmaker):
    created = await flow("POST", "/books", {"idea": "作者已有主角和法宝", "mode": "puzzle", "prefill": True})
    bid, jid = created["book"]["id"], created["job"]["id"]
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["kind"] == "setup_prefill"
    await flow(
        "POST",
        f"/books/{bid}/characters",
        {
            "name": "楚风",
            "role_type": "主角",
            "personality": "作者亲写不可覆盖",
            "background": "作者身世",
            "goal": "找回故乡",
        },
    )
    await flow(
        "POST",
        f"/books/{bid}/world-entries",
        {"name": "故乡钟", "category": "物品与功法", "tags": ["金手指"], "content": "作者的独特法宝"},
    )
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "start"})
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == uuid.UUID(bid))))
        assert "【设定库里已经有的】" in calls[-1].request["user"] and "故乡钟" in calls[-1].request["user"]
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1})
    job = await flow("GET", f"/jobs/{jid}")
    assert job["pending"]["piece"] == "settings"
    book = await flow("GET", f"/books/{bid}")
    assert book["setup_progress"]["pieces"]["concept"] == "waiting"
    library = await flow("GET", f"/books/{bid}/library")
    assert len([c for c in library["characters"] if c["role_type"] == "主角"]) == 1
    assert next(c for c in library["characters"] if c["name"] == "楚风")["personality"] == "作者亲写不可覆盖"
    assert "故乡钟" in book["concept"]["story"]
    await flow("PATCH", f"/books/{bid}", {"concept": {"story": book["concept"]["story"] + "\n作者手改的结尾。"}})
    await flow(
        "POST", f"/jobs/{jid}/piece", {"action": "revise", "feedback": "故事更偏复仇一点，师父改成反派，大纲卷首要快"}
    )
    changed = await flow("GET", f"/books/{bid}")
    assert "已按要求修改" in changed["concept"]["story"]
    assert "作者手改的结尾。" in changed["concept"]["story"]
    changed_library = await flow("GET", f"/books/{bid}/library")
    # 定位不给编辑部看了，演示模型认不出「师父」；眼前意见也不再自动记成长期规矩。
    assert all("已按要求修改" not in c["background"] for c in changed_library["characters"])
    req = await flow("GET", f"/books/{bid}/memories")
    assert not any("大纲卷首要快" in r["detail"] for r in req)
    await flow("POST", f"/jobs/{jid}/piece", {"action": "confirm", "piece": "settings"})
    book = await flow("GET", f"/books/{bid}")
    assert book["setup_progress"]["pieces"]["concept"] == book["setup_progress"]["pieces"]["settings"] == "confirmed"
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == uuid.UUID(bid))))
        assert any(
            "setup_outline" in call.request.get("prompt_names", []) and "大纲卷首要快" in call.request["user"]
            for call in calls
        )
    assert not any("大纲卷首要快" in r["detail"] for r in await flow("GET", f"/books/{bid}/memories"))


async def test_focus_wrong_ai_name_fills_only_blanks_and_rest_alias_skip(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character))
        hero.source = "author"
        hero.personality = "作者性格"
        hero.background = ""
        hero.aliases = ["小风"]
        entry = await session.scalar(select(WorldEntry))
        entry.name = "旧镜"
        entry.tags = ["金手指"]
        entry.source = "author"
        entry.content = "作者内容"
        await session.commit()
        focus = demo_setup.focus("").model_dump()
        focus["protagonist"]["name"] = "模型乱起名"
        focus["finger"]["name"] = "模型另一法宝"
        await save_library_focus(session, bid, focus)
        await session.commit()
        assert hero.name == "楚风" and hero.personality == "作者性格" and hero.background and hero.source == "author"
        assert entry.name == "旧镜" and entry.content == "作者内容"
        rest = demo_setup.rest("").model_dump()
        rest["characters"] = [{**focus["protagonist"], "name": "小风"}]
        await save_library_rest(session, bid, rest)
        await session.commit()
        assert len(list(await session.scalars(select(Character)))) == 1
        ctx = await load_context(session, await session.get(Book, bid))
        assert existing_text(ctx).startswith("【设定库里已经有的】\n")
        assert "模型乱起名" not in existing_text(ctx)
        assert "角色卡片 · 楚风\n" not in existing_text(ctx, exclude=[hero])
        entry.content = "长" * 9000
        await session.flush()
        ctx = await load_context(session, await session.get(Book, bid))
        assert "（下面这些只列名字和一句话）" in existing_text(ctx)


def test_patch_verbatim_schemas_prompts_and_visible_names():
    root = Path(__file__).parents[2]
    doc = with_later_changes((root / "docs/codex任务/第三包/补丁1-群聊和开书改进.md").read_text(encoding="utf8"))
    actual = ast.parse((root / "backend/app/agents/schemas.py").read_text(encoding="utf8"))
    block = re.search(r"```python\n(class PlanItem[\s\S]*?)\n```", doc)[1]
    for expected in ast.parse(block).body:
        assert ast.dump(
            next(c for c in actual.body if isinstance(c, ast.ClassDef) and c.name == expected.name)
        ) == ast.dump(expected)
    for name, sha in json.loads(
        Path(__file__).with_name("patch1_prompt_hashes.json").read_text(encoding="utf8")
    ).items():
        assert hashlib.sha256((root / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == sha
        assert not (root / f"docs/codex任务/第三包/提示词/{name}.md").exists()
    for base in (root / "frontend/src", root / "backend/app"):
        for path in base.rglob("*"):
            if path.suffix in {".ts", ".tsx", ".py", ".md"}:
                assert "短版" not in path.read_text(encoding="utf8"), path
