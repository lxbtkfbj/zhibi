"""开书不排队：真实接口、演示模型与持久化检查点的回归合同。"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.agents import schemas
from app.api.library_ai import RewriteIn, rewrite_target
from app.config import get_settings
from app.graphs import book_setup
from app.llm import demo
from app.models import Book, Character, Job, LlmCall, SettingSuggestion
from app.schemas import NoteIn
from app.services import group_notes, jobs
from app.services.chat_context import wants_new_pitches
from tests.test_chat_task6 import final_message, seed
from tests.test_patch1 import plan_for
from tests.test_patch1 import redis as _redis
from tests.test_setup_puzzle_flow import flow as _flow

flow, redis = _flow, _redis


@pytest.mark.parametrize(
    "text",
    [
        "都不满意，第一个的主角配第二个的金手指",
        "再来三个，别写穿越",
        "再出三个",
        "重出",
        "重新出！",
        "换三个",
        "换一批",
        "换几个方向",
        "都不要",
        "都不喜欢",
        "长" * 196 + "再来三个",
    ],
)
def test_new_pitch_phrases(text):
    assert wants_new_pitches(text)


@pytest.mark.parametrize("text", ["主角不要像云澈那么冲动", "把老怪的设定写进设定库", "长" * 197 + "再来三个"])
def test_not_new_pitch_phrases(text):
    assert not wants_new_pitches(text)


def test_open_wait_uses_job_not_pending_open_flag():
    job = SimpleNamespace(
        kind="book_setup", params={"flow": 3}, status="waiting_author", pending={"kind": "setup_pitches"}
    )
    assert jobs.open_wait(job) and not group_notes.waiting_feedback(job)
    for field, value in [
        ("params", {"flow": 2}),
        ("kind", "write_book"),
        ("status", "running"),
        ("pending", {"kind": "setup_piece"}),
    ]:
        assert not jobs.open_wait(SimpleNamespace(**{**vars(job), field: value}))
    assert not jobs.open_wait(None)


async def open_book(flow, **options):
    created = await flow("POST", "/books", {"idea": "楚风重生", "mode": "puzzle", **options})
    bid, jid = created["book"]["id"], created["job"]["id"]
    pending = (await flow("GET", f"/jobs/{jid}"))["pending"]
    assert pending["kind"] == "setup_pitches" and pending["open"] is True
    return bid, jid


async def test_open_group_edit_undo_requirement_question_and_redo(flow, sessionmaker, redis):
    bid, jid = await open_book(flow, prefill=True)
    hero = await flow(
        "POST", f"/books/{bid}/characters", {"name": "楚风", "role_type": "主角", "personality": "原来的性格"}
    )
    # 旧 setup_pitches 等待没有 open 标记，升级后同样敞开；先存再判断。
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(jid))
        job.pending = {k: v for k, v in job.pending.items() if k != "open"}
        await session.commit()
        tasks = BackgroundTasks()
        message = await group_notes.receive_note(
            NoteIn(content="把主角的性格改成冷静隐忍"),
            tasks,
            await session.get(Book, uuid.UUID(bid)),
            session,
            redis,
        )
        assert message.payload["outcome"]["kind"] == "pending" and message.job_id is None
    await tasks()
    outcome = (await final_message(flow.client, bid, message.id))["payload"]["outcome"]
    assert outcome["kind"] == "edit" and outcome["target_id"] == hero["id"]
    library = await flow("GET", f"/books/{bid}/library")
    assert library["characters"][0]["personality"] != "原来的性格"
    await flow("POST", f"/versions/{outcome['revert_version_id']}/revert")
    assert (await flow("GET", f"/books/{bid}/library"))["characters"][0]["personality"] == "原来的性格"
    note = await flow("POST", f"/books/{bid}/notes", {"content": "下一章节奏快一点"})
    assert (await final_message(flow.client, bid, note["id"]))["payload"]["outcome"]["kind"] == "requirement"
    question = await flow("POST", f"/books/{bid}/notes", {"content": "楚风现在什么境界？"})
    assert question["payload"]["outcome"] == {"kind": "chat", "shortcut": True}
    before = len(await flow("GET", f"/books/{bid}/meeting"))
    response = await flow.client.post(f"/api/books/{bid}/notes", json={"content": "都不满意，再来三个"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "use_feedback"
    assert len(await flow("GET", f"/books/{bid}/meeting")) == before
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "redo", "feedback": "都不满意，再来三个"})
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["round"] == 2
    assert await flow("GET", f"/books/{bid}/memories")


async def test_open_plan_applies_items_not_feedback_and_all_can_undo(flow, sessionmaker, redis):
    bid, jid = await open_book(flow)
    # 实际生成方案卡，再把作者在卡片上改过的定调和新条目交回接口。
    await flow("POST", f"/books/{bid}/notes", {"content": "楚风的设定是什么？"})
    await flow("POST", f"/books/{bid}/notes", {"content": "总结一下"})
    card = next(m for m in await flow("GET", f"/books/{bid}/meeting") if m["kind"] == "plan")
    items = [
        {"where": "定调", "change": "楚风持镜重生，追查前世真相。"},
        {"where": "设定库", "target": "老怪", "category": "角色卡片", "change": "导师想夺舍主角。"},
        {"where": "设定库", "target": "旧案", "category": "往事与秘密", "change": "旧案牵连古镜。"},
        {"where": "写作要求", "change": "开篇快一点"},
    ]
    response = await flow.client.post(f"/api/plans/{card['id']}/apply", json={"items": items})
    assert response.status_code == 202
    results = (await final_message(flow.client, bid, card["id"]))["payload"]["results"]
    assert [r["kind"] for r in results] == ["edit", "created", "created", "requirement"]
    assert (await flow("GET", f"/books/{bid}"))["concept"]["story"]
    messages = await flow("GET", f"/books/{bid}/meeting")
    assert any(
        m["content"]
        == "照方案办好了。要我按现在的定调和设定把开书稿补齐吗？点底部的「补齐开书稿」就行；想先看看三个故事方向也可以，挑一个，我按那个方向写。"
        for m in messages
    )
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["kind"] == "setup_pitches"
    async with sessionmaker() as session:
        assert len(list(await session.scalars(select(LlmCall).where(LlmCall.purpose == "开书·三个故事方向")))) == 1
    await flow("POST", f"/versions/{results[0]['revert_version_id']}/revert")
    # 第五步第三批起方案卡照办的每一条和聊天里改的一样：新建的用「换回原来的」删掉
    await flow("POST", f"/books/{bid}/notes/{card['id']}/revert", {"step": 1})
    await flow("DELETE", f"/books/{bid}/memories/{results[3]['requirement_id']}")
    assert not (await flow("GET", f"/books/{bid}/library"))["characters"]
    # 没有定调/设定成功落地时，不发补齐邀请。
    another = await plan_for(sessionmaker, redis, uuid.UUID(bid), [{"where": "写作要求", "change": "不要拖沓"}])
    await flow.client.post(f"/api/plans/{another['id']}/apply")
    assert sum("照方案办好了。要我按现在" in m["content"] for m in await flow("GET", f"/books/{bid}/meeting")) == 1


async def test_fill_validation_and_exact_story_live_state_not_auto_write(flow, sessionmaker, monkeypatch):
    bid, jid = await open_book(flow)
    for empty in (None, " \n\t"):
        await flow("PATCH", f"/books/{bid}", {"concept": {} if empty is None else {"story": empty}})
        response = await flow.client.post(f"/api/jobs/{jid}/pitches", json={"action": "fill"})
        assert response.status_code == 422
        assert response.json()["detail"] == "还没有定调。先挑一个故事方向，或者在群聊里聊定了让我照方案办。"
    await flow("PATCH", f"/books/{bid}", {"concept": {"story": "最初的定调"}})
    for body in ({"action": "fill", "length": 400}, {"action": "fill", "title": "   "}):
        assert (await flow.client.post(f"/api/jobs/{jid}/pitches", json=body)).status_code == 422
    hero = await flow(
        "POST", f"/books/{bid}/characters", {"name": "楚风", "role_type": "主角", "personality": "作者亲写性格"}
    )
    await flow(
        "POST",
        f"/books/{bid}/world-entries",
        {"category": "往事与秘密", "name": "底牌", "content": "作者底牌", "locked": True},
    )
    locked = await flow(
        "POST",
        f"/books/{bid}/world-entries",
        {"category": "物品与功法", "name": "轮回镜", "content": "锁住的镜子", "locked": True, "tags": ["金手指"]},
    )
    prompts = []
    pitch_blocks = []
    original = demo.respond
    draft_story = book_setup.editorial.draft_story

    async def draft(llm, blocks):
        pitch_blocks.append(blocks["pitch"])
        return await draft_story(llm, blocks)

    async def respond(schema, system, user):
        result = await original(schema, system, user)
        if schema is schemas.StoryConcept:
            prompts.append(user)
            result.story = "模型试图改掉作者定调"
            result.secret = ""
            result.decisions = [
                schemas.AuthorChoice(topic="开局", chosen="追凶", alternatives=["复仇", "经营"], why="测试")
            ]
        if schema is schemas.OutlineDraft:
            result.arcs[1].planned = True  # 留下不会自动重写掉的大纲提醒。
            result.decisions = [schemas.AuthorChoice(topic="舞台", chosen="青阳城", alternatives=[], why="测试")]
        return result

    monkeypatch.setattr(demo, "respond", respond)
    monkeypatch.setattr(book_setup.editorial, "draft_story", draft)
    story = "  作者逐字定调：楚风找回旧镜。\n保留换行、空格与标点！ \n"
    await flow("PATCH", f"/books/{bid}", {"concept": {"story": story}})
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "fill", "length": 100, "title": "作者书名"})
    book = await flow("GET", f"/books/{bid}")
    assert book["status"] == "ready" and book["concept"]["story"] == story
    assert book["title"] == "作者书名" and book["concept"]["target_length"] == 100
    assert book["setup_progress"]["pieces"] == dict.fromkeys(book_setup.PIECE_ORDER, "confirmed")
    job = await flow("GET", f"/jobs/{jid}")
    assert job["status"] == "succeeded" and not job["pending"]
    assert pitch_blocks == ["作者已经定好了定调的一段话，一个字都不要改，照着它补齐其余各项：\n" + story] * 2
    assert len(prompts) == 2  # 作者短定调也只重试一次，始终还原原文。
    library = await flow("GET", f"/books/{bid}/library")
    assert next(c for c in library["characters"] if c["id"] == hero["id"])["personality"] == "作者亲写性格"
    assert next(e for e in library["entries"] if e["id"] == locked["id"])["content"] == "锁住的镜子"
    assert next(e for e in library["entries"] if e["name"] == "底牌")["content"] == "作者底牌"
    suggestions = await flow("GET", f"/books/{bid}/suggestions")
    assert any(
        s["title"] == "底牌还没写；这本书没有大秘密就写「没有」。"
        and s["payload"]["op"] == "note"
        and s["status"] == "pending"
        for s in suggestions
    )
    assert any(s["title"] == "只有第一篇写细，后面的篇写到再定。" for s in suggestions)
    messages = await flow("GET", f"/books/{bid}/meeting")
    assert any(
        m["content"] == "替你做了这几个决定，想换哪个就在群聊里说：\n· 开局：用了「追凶」（也可以：复仇、经营）"
        for m in messages
    )
    assert any(m["content"] == "替你做了这几个决定，想换哪个就在群聊里说：\n· 舞台：用了「青阳城」" for m in messages)
    total = len(library["characters"]) + len(library["entries"])
    assert (
        messages[-1]["content"]
        == f"开书稿齐了：定调、设定 {total} 条、大纲排到第一个单元的章纲。哪里不对，直接在群聊里说，或者在页面上改；满意了点「开写」。"
    )
    requirements = await flow("GET", f"/books/{bid}/memories")
    assert any(
        r["detail"] == "开书不挑故事方向，用已经写好的定调和设定补齐。" and r["source"] == "开书时答的"
        for r in requirements
    )
    assert any(m["content"] == "不挑方向了，用现在的定调和设定补齐开书稿。" for m in messages)
    async with sessionmaker() as session:
        assert [j.kind for j in await session.scalars(select(Job).where(Job.book_id == uuid.UUID(bid)))] == [
            "book_setup"
        ]
    outline = await flow("GET", f"/books/{bid}/outline")
    assert outline  # 章纲在独立 pick/write 复用测试中进一步检查。


@pytest.mark.parametrize("mode", ["puzzle", "oneshot"])
async def test_new_prefill_ignored_pick_and_oneshot_finish(flow, mode):
    created = await flow("POST", "/books", {"idea": "楚风重生", "mode": mode, "prefill": True})
    bid, jid = created["book"]["id"], created["job"]["id"]
    if mode == "puzzle":
        assert (await flow("GET", f"/jobs/{jid}"))["pending"]["kind"] == "setup_pitches"
        await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1})
    assert (await flow("GET", f"/jobs/{jid}"))["status"] == "succeeded"
    assert (await flow("GET", f"/books/{bid}"))["status"] == "ready"
    assert (await flow.client.post(f"/api/jobs/{jid}/pitches", json={"action": "start"})).status_code == 422
    await flow("PATCH", f"/books/{bid}/settings", {"trial_read": False})
    await flow("POST", f"/books/{bid}/write", {"until": "count", "count": 3})
    chapters = await flow("GET", f"/books/{bid}/chapters")
    assert sum(c["status"] == "final" for c in chapters) == 3


async def test_rewrite_idle_open_allowed_outline_wait_blocked(flow, sessionmaker, redis):
    bid = await seed(sessionmaker, "waiting_author", "book_setup")
    async with sessionmaker() as session:
        hero = await session.scalar(select(Character).where(Character.book_id == bid))
        body = RewriteIn(
            target_type="character", target_id=hero.id, path="personality", mode="instruction", instruction="冷静隐忍"
        )
        job = await session.scalar(select(Job).where(Job.book_id == bid))
        job.pending = {"kind": "setup_pitches"}
        await session.commit()
        await rewrite_target(session, redis, await session.get(Book, bid), body, require_idle=True)
        job = await session.scalar(select(Job).where(Job.book_id == bid))
        job.pending = {"kind": "setup_piece", "piece": "outline"}
        await session.commit()
        with pytest.raises(HTTPException) as exc:
            await rewrite_target(session, redis, await session.get(Book, bid), body, require_idle=True)
        assert exc.value.status_code == 409


async def test_notice_dedup_only_pending_same_book(sessionmaker):
    bid = await seed(sessionmaker)
    other = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            [
                SettingSuggestion(book_id=bid, kind="review", title="旧提醒", payload={}, status="accepted"),
                SettingSuggestion(book_id=other, kind="review", title="新提醒", payload={}),
            ]
        )
        await session.commit()
        for _ in range(2):
            await book_setup._save_warnings(session, bid, ["旧提醒", "新提醒", "新提醒"])
            await session.commit()
        rows = list(
            await session.scalars(
                select(SettingSuggestion).where(SettingSuggestion.book_id == bid, SettingSuggestion.status == "pending")
            )
        )
        assert sorted(r.title for r in rows) == ["新提醒", "旧提醒"]


async def test_saved_checkpoint_without_piece_gates_still_waits_and_confirms(flow, sessionmaker, monkeypatch):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    original = book_setup.pitches_gate_node

    async def old_gate(state, runtime):
        command = await original(state, runtime)
        command.update.pop("piece_gates", None)
        return command

    monkeypatch.setattr(book_setup, "pitches_gate_node", old_gate)
    bid, jid = await open_book(flow)
    await flow("POST", f"/jobs/{jid}/pitches", {"action": "pick", "index": 1})
    monkeypatch.setattr(book_setup, "pitches_gate_node", original)
    async with sessionmaker() as session:
        thread = (await session.get(Job, uuid.UUID(jid))).thread_id
    async with AsyncPostgresSaver.from_conn_string(get_settings().checkpoint_dsn) as saver:
        graph = book_setup.build_setup_graph().compile(checkpointer=saver)
        checkpoint = await graph.aget_state({"configurable": {"thread_id": thread}})
        assert "piece_gates" not in checkpoint.values
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "settings"
    await flow("POST", f"/jobs/{jid}/piece", {"action": "revise", "feedback": "故事更偏复仇"})
    await flow("POST", f"/jobs/{jid}/piece", {"action": "confirm"})
    assert (await flow("GET", f"/jobs/{jid}"))["pending"]["piece"] == "outline"
    await flow("POST", f"/jobs/{jid}/piece", {"action": "confirm"})
    assert (await flow("GET", f"/books/{bid}"))["status"] == "ready"
