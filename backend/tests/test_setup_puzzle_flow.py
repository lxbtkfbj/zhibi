"""真实接口与检查点跑完三步，演示模式只用隔离测试数据库。"""

import uuid
from collections import Counter

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import schemas
from app.config import get_settings
from app.graphs.book_setup import PIECE_ORDER
from app.llm import demo
from app.main import create_app
from app.models import Book, Chapter, Character, MeetingMessage, PlotUnit, Volume, WorldEntry
from app.services import jobs
from app.services.job_runner import execute_job


@pytest.fixture
async def flow(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, resume=None: queued.append((jid, resume)))
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:

        async def call(method, path, body=None, *, run=True):
            response = await client.request(method, "/api" + path, json=body)
            assert response.is_success, response.text
            while run and queued:
                jid, resume = queued.pop(0)
                await execute_job(jid, resume)
                status = (await client.get(f"/api/jobs/{jid}")).json()
                assert status["status"] != "failed", status["error"]
            return None if response.status_code == 204 else response.json()

        call.client = client
        yield call
    await application.state.redis.aclose()


async def new_puzzle(flow, idea="楚风重生，测试自建类别"):
    result = await flow("POST", "/books", {"idea": idea, "mode": "puzzle"})
    bid, jid = result["book"]["id"], result["job"]["id"]
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["kind"] == "setup_pitches" and gate["flow"] == 3 and len(gate["pitches"]) == 3
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1, "length": 300})
    return bid, jid


@pytest.fixture
def legacy_piece_gates(monkeypatch):
    """模拟补丁 2 之前已离开挑方向的检查点：没有 piece_gates 字段。"""
    from app.graphs import book_setup

    original = book_setup.pitches_gate_node

    async def old_gate(state, runtime):
        result = await original(state, runtime)
        result.update.pop("piece_gates", None)
        return result

    monkeypatch.setattr(book_setup, "pitches_gate_node", old_gate)


async def confirm(flow, jid):
    return await flow("POST", f"/jobs/{jid}/piece", {"action": "confirm"})


@pytest.mark.usefixtures("legacy_piece_gates")
async def test_complete_flow_focus_saved_first_and_write_reuses_first_unit(flow, sessionmaker, monkeypatch):
    calls, inspected = Counter(), []
    original = demo.respond

    async def respond(schema, system, user):
        calls[schema.__name__] += 1
        if schema is schemas.LibraryRest:
            async with sessionmaker() as session:
                heroes = list(await session.scalars(select(Character)))
                entries = list(await session.scalars(select(WorldEntry)))
                messages = list(await session.scalars(select(MeetingMessage.content)))
                assert [hero.name for hero in heroes] == ["楚风"]
                assert any(entry.name == "轮回镜" for entry in entries)
                assert not any(entry.name == "武道境界" for entry in entries)
                assert "重点先出来了：主角「楚风」和金手指「轮回镜」。其余设定正在补。" in messages
                inspected.append(True)
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", respond)
    bid, jid = await new_puzzle(flow)
    concept = (await flow("GET", f"/books/{bid}"))["concept"]
    assert concept["target_length"] == 300 and concept["story"] and concept["secret_entry_id"]
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["piece"] == "settings" and gate["summary"].startswith("主编建了 ")
    assert "另外有 " in gate["summary"] and inspected
    suggestions = await flow("GET", f"/books/{bid}/suggestions")
    custom = next(row for row in suggestions if row["payload"].get("op") == "create_category")
    assert custom["payload"]["category"]["entries"][0]["name"] == "末班车司机"
    assert gate["suggestion_count"] == len(suggestions)
    await flow("POST", f"/jobs/{jid}/piece", {"action": "revise", "feedback": "把境界改成九重天"})
    levels = next(entry for entry in gate["setup"]["settings"]["entries"] if entry["name"] == "武道境界")
    candidates = await flow("GET", f"/books/{bid}/candidates?target_type=entry&target_id={levels['id']}")
    assert not candidates  # 明确说了改成什么，直接改这一处。
    assert calls["LibraryRest"] == 1  # 提意见绝不整库重建。
    await confirm(flow, jid)
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["piece"] == "outline"
    outline = gate["setup"]["outline"]
    assert len(outline["arcs"]) == 4 and len(outline["volumes"]) == 2 and len(outline["units"]) == 4
    assert outline["chapters"] and outline["volumes"][0]["status"] == "approved"
    count = calls["ChapterPlanDraft"]
    await confirm(flow, jid)
    book = await flow("GET", f"/books/{bid}")
    assert book["status"] == "ready" and book["setup_progress"]["current"] is None
    assert book["setup_progress"]["pieces"] == dict.fromkeys(PIECE_ORDER, "confirmed")
    assert (await flow("GET", f"/jobs/{jid}"))["status"] == "succeeded"
    await flow("PATCH", f"/books/{bid}/settings", {"trial_read": False})
    await flow("POST", f"/books/{bid}/write", {"until": "count", "count": 3})
    async with sessionmaker() as session:
        chapters = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(bid), Chapter.status == "final"))
        )
        assert len(chapters) == 3
    assert calls["ChapterPlanDraft"] == count


async def test_redo_exact_previous_latest_round_title_and_requirements(flow, monkeypatch):
    captured = []
    original = demo.respond

    async def respond(schema, system, user):
        result = await original(schema, system, user)
        if schema is schemas.PitchSet:
            captured.append(user)
            result.pitches[0].name = f"仅第{len(captured)}轮故事方向"
        return result

    monkeypatch.setattr(demo, "respond", respond)
    created = await flow("POST", "/books", {"idea": "对标一部传统玄幻", "mode": "puzzle"})
    bid, jid = created["book"]["id"], created["job"]["id"]
    assert "【上一轮的故事方向】\n" not in captured[0]
    for feedback in ("保留经营", "加入追凶"):
        await flow("POST", f"/jobs/{jid}/pitches", {"action": "redo", "feedback": feedback})
    assert "【上一轮的故事方向】\n1. 仅第2轮故事方向：" in captured[2]
    assert "【作者的意见】\n加入追凶" in captured[2] and "仅第1轮故事方向" not in captured[2]
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert gate["round"] == 3
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1, "title": "作者自己起名", "length": 300})
    concept = (await flow("GET", f"/books/{bid}"))["concept"]
    assert concept["title"] == "作者自己起名" and concept["target_length"] == 300
    requirements = await flow("GET", f"/books/{bid}/requirements")
    assert {"保留经营", "加入追凶"} <= {row["text"] for row in requirements}


async def test_oneshot_finishes_without_piece_waits(flow):
    result = await flow("POST", "/books", {"idea": "楚风带着轮回镜重生", "mode": "oneshot", "ask": True})
    bid, jid = result["book"]["id"], result["job"]["id"]
    assert (await flow("GET", f"/jobs/{jid}"))["status"] == "succeeded"
    book = await flow("GET", f"/books/{bid}")
    assert book["setup_progress"]["pieces"] == dict.fromkeys(PIECE_ORDER, "confirmed")
    assert (await flow("GET", f"/books/{bid}"))["status"] == "ready"


@pytest.mark.usefixtures("legacy_piece_gates")
async def test_concept_length_retry_once_and_empty_secret_warning(flow, monkeypatch):
    prompts = []
    original = demo.respond

    async def respond(schema, system, user):
        result = await original(schema, system, user)
        if schema is schemas.StoryConcept:
            prompts.append(user)
            result.story = "短"
            result.secret = ""
        return result

    monkeypatch.setattr(demo, "respond", respond)
    _, jid = await new_puzzle(flow)
    assert len(prompts) == 2 and "定调要写成一段话，200-400 字，现在是 1 字。" in prompts[1]
    gate = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert len(gate["concept_warnings"]) == 2
    assert gate["piece"] == "settings"


@pytest.mark.usefixtures("legacy_piece_gates")
async def test_live_author_edits_are_not_overwritten_on_confirm(flow, sessionmaker):
    bid, jid = await new_puzzle(flow)
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(bid))
        book.concept = {**book.concept, "story": "作者在确认前亲自保存的一段话。"}
        secret = await session.get(WorldEntry, uuid.UUID(book.concept["secret_entry_id"]))
        secret.content, secret.source = "作者改过的底牌", "ai_edited"
        await session.commit()
    await confirm(flow, jid)
    assert (await flow("GET", f"/books/{bid}"))["concept"]["story"] == "作者在确认前亲自保存的一段话。"
    async with sessionmaker() as session:
        secret = await session.get(WorldEntry, secret.id)
        assert secret.content == "作者改过的底牌"


@pytest.mark.usefixtures("legacy_piece_gates")
async def test_settings_failed_checks_retry_once_notes_review_and_flips(flow, monkeypatch):
    counts, scopes = Counter(), []
    original = demo.respond

    async def respond(schema, system, user):
        result = await original(schema, system, user)
        counts[schema.__name__] += 1
        if schema is schemas.LibraryRest:
            result.entries = []
            result.characters = []
        if schema is schemas.LibraryReview:
            scopes.append(user)
        if schema is schemas.LibraryIntent:
            result.kind = "其他"
        return result

    monkeypatch.setattr(demo, "respond", respond)
    bid, jid = await new_puzzle(flow)
    assert counts["LibraryRest"] == 2
    suggestions = await flow("GET", f"/books/{bid}/suggestions")
    assert any(
        row["payload"].get("op") == "note" and row["title"] == "世界与地图的第一条要叫「世界概况」。"
        for row in suggestions
    )
    assert any("这是开书时刚建好的设定库，查整个设定库。" in prompt for prompt in scopes)
    await flow(
        "POST",
        f"/jobs/{jid}/piece",
        {"action": "revise", "feedback": "查一下是否矛盾", "flips": [{"topic": "主角性格", "choice": "沉稳"}]},
    )
    assert any("按作者的意见查一遍：查一下是否矛盾" in prompt for prompt in scopes)
    assert any("按作者的意见查一遍：把「主角性格」改成「沉稳」" in prompt for prompt in scopes)
    assert counts["LibraryRest"] == 2


@pytest.mark.usefixtures("legacy_piece_gates")
async def test_outline_revise_keeps_locked_nodes_and_unchanged_chapters(flow, sessionmaker, monkeypatch):
    prompts = []
    original = demo.respond

    async def respond(schema, system, user):
        result = await original(schema, system, user)
        if schema is schemas.OutlineDraft:
            prompts.append(user)
        return result

    monkeypatch.setattr(demo, "respond", respond)
    bid, jid = await new_puzzle(flow)
    await confirm(flow, jid)
    async with sessionmaker() as session:
        volume = await session.scalar(select(Volume).where(Volume.book_id == uuid.UUID(bid)).order_by(Volume.index))
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index))
        volume.locked, unit.locked = True, True
        volume.summary, unit.summary = "作者锁住的卷", "作者锁住的单元"
        chapters = list(await session.scalars(select(Chapter.id).where(Chapter.unit_id == unit.id)))
        await session.commit()
    await flow("POST", f"/jobs/{jid}/piece", {"action": "revise", "feedback": "其余卷写得更紧凑"})
    assert "下面这些节点作者锁住了，原样保留：" in prompts[-1]
    async with sessionmaker() as session:
        assert (await session.get(Volume, volume.id)).summary == "作者锁住的卷"
        assert (await session.get(PlotUnit, unit.id)).summary == "作者锁住的单元"
        assert list(await session.scalars(select(Chapter.id).where(Chapter.unit_id == unit.id))) == chapters


@pytest.mark.parametrize("action", ["reopen", "unlock", "candidates", "fill"])
async def test_retired_piece_actions_return_422(flow, action):
    _, jid = await new_puzzle(flow)
    response = await flow.client.post(f"/api/jobs/{jid}/piece", json={"action": action})
    assert response.status_code == 422


@pytest.mark.parametrize("change", ["saved_title", "deleted_requirement", "edited_requirement"])
@pytest.mark.usefixtures("legacy_piece_gates")
async def test_concept_revision_uses_live_title_and_never_revives_old_title_requirement(flow, monkeypatch, change):
    from app.agents import editorial
    from app.llm import demo_setup

    blocks_seen = []
    model_title = "模型新书名"

    async def story(llm, blocks):
        blocks_seen.append(blocks)
        result = demo_setup.concept(blocks["idea"])
        result.title = model_title
        return result

    monkeypatch.setattr(editorial, "draft_story", story)
    created = await flow("POST", "/books", {"idea": "少年重生", "mode": "puzzle"})
    bid, jid = created["book"]["id"], created["job"]["id"]
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1, "title": "最初选名", "length": 300})
    assert (await flow("GET", f"/books/{bid}"))["concept"]["title"] == "最初选名"
    rows = await flow("GET", f"/books/{bid}/requirements")
    title_row = next(row for row in rows if row["text"] == "书名用《最初选名》")
    if change == "saved_title":
        await flow("PATCH", f"/books/{bid}", {"title": "作者手改名"})
        expected = "作者手改名"
    elif change == "deleted_requirement":
        await flow("DELETE", f"/requirements/{title_row['id']}")
        expected = "最初选名"
    else:
        await flow("PATCH", f"/requirements/{title_row['id']}", {"text": "书名用《要求里新书名》"})
        model_title = "要求里新书名"
        expected = "最初选名"
    await flow("POST", f"/jobs/{jid}/piece", {"action": "revise", "feedback": "只把故事写得更紧凑"})
    book = await flow("GET", f"/books/{bid}")
    assert book["title"] == book["concept"]["title"] == expected
    assert len(blocks_seen) == 1  # 合成确认后只局部改故事，不重生成整份定调。
    rows = await flow("GET", f"/books/{bid}/requirements")
    if change != "saved_title":
        assert "书名用《最初选名》" not in {row["text"] for row in rows}
    if change == "edited_requirement":
        assert "书名用《要求里新书名》" in {row["text"] for row in rows}
