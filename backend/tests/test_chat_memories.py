"""聊天改进任务 3：逐字契约、工具权限、目录、三种回执及撤销。"""

import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, BookSave, Chapter, Job, LlmCall, MeetingMessage, Memory
from app.services import chat_tools
from app.services.chat_agent import ACT_RULE, Turn, agent_values, run_tool
from app.services.chat_context import done_text, reply_values
from app.services.chat_memories import Forget, ReadMemory, Remember, execute, memory_directory, snapshot
from app.services.memories import remember
from tests.test_chat_agent import reply_of, say
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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


def args(**changes):
    return Remember(
        kind="写书时照做", scope="这本书", summary="每章留钩子", detail="作者说每章结尾留一个钩子。", **changes
    )


async def invoke(sm, bid, tool):
    async with sm() as session:
        result = await execute(session, bid, None, tool)
        await session.commit()
        return result


def test_tool_definitions_are_verbatim_design_94():
    design = (Path(__file__).parents[2] / "docs/主编聊天/记忆系统.md").read_text(encoding="utf-8")
    section = design.split("### 9.4", 1)[1].split("### 9.5", 1)[0]
    specs = {spec["function"]["name"]: spec["function"] for spec in chat_tools.tool_specs(True)}
    for name in ("remember", "read_memory", "forget"):
        expected = re.search(rf"\*\*{name}\*\*：「(.*?)」", section)[1]
        assert specs[name]["description"] == expected
    descriptions = dict(re.findall(r"\| (id|kind|scope|summary|detail|lasts) \| (.*?) \|", section))
    assert {
        key: val["description"] for key, val in specs["remember"]["parameters"]["properties"].items()
    } == descriptions
    assert specs["read_memory"]["parameters"]["properties"]["ids"]["description"] == "要翻的编号，比如「记12」。"
    assert specs["forget"]["parameters"]["properties"]["id"]["description"] == "要删的编号。"
    with pytest.raises(ValidationError):
        ReadMemory(ids=["记1"] * 6)
    with pytest.raises(ValidationError):
        Remember(kind="写书时照做", scope="这本书", summary="字" * 31, detail="原话")
    assert chat_tools.doing_of("remember", args()) == "在记"
    assert chat_tools.doing_of("read_memory", ReadMemory(ids=[])) == "在翻记忆"
    assert chat_tools.doing_of("forget", Forget(id="记1")) == "在删一条记忆"
    read_only = {spec["function"]["name"] for spec in chat_tools.tool_specs(True)}
    assert {"remember", "read_memory", "forget"} <= read_only and "make_changes" not in read_only
    assert not {"remember", "read_memory", "forget"} & {
        spec["function"]["name"] for spec in chat_tools.tool_specs(True, memories=False)
    }
    assert "写作要求" not in str(chat_tools.MakeChanges.model_json_schema())
    assert "requirement" not in chat_tools.ChangeItem.model_fields and "scope" not in chat_tools.ChangeItem.model_fields
    assert re.search(r"### 9\.5.*?改成：\n\n```\n(.*?)\n```", design, re.S)[1] == ACT_RULE


async def test_directory_and_both_chat_contexts(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        other = Book(title="别本书")
        session.add(other)
        await session.flush()
        assert await memory_directory(session, bid) == "还没有记忆"
        gchat = await remember(session, None, "喜欢传统爽文", kind="chat")
        gw = await remember(session, None, "不写床戏")
        bookchat = await remember(session, bid, "女主身世先不定", kind="chat")
        bw = await remember(session, bid, "下一章节奏加快", scope="next_chapter")
        expired = await remember(session, bid, "已定稿", scope="next_chapter")
        expired.chapter_index = 1
        session.add(Chapter(book_id=bid, index=1, status="final"))
        gone = await remember(session, bid, "已经删了")
        from app.services.memories import forget

        await forget(session, gone)
        await remember(session, other.id, "不属于本书")
        await session.commit()
        expected = f"全局 · 写书时照做\n- 记{gw.id}：不写床戏\n全局 · 聊天时记得\n- 记{gchat.id}：喜欢传统爽文\n这本书 · 写书时照做\n- 记{bw.id}（只管第 2 章）：下一章节奏加快\n这本书 · 聊天时记得\n- 记{bookchat.id}：女主身世先不定"
        # The scope was resolved before the extra final chapter was added above.
        bw.chapter_index = 2
        await session.commit()
        assert await memory_directory(session, bid) == expected
        author = MeetingMessage(book_id=bid, speaker="author", kind="note", content="这本书怎么写？")
        session.add(author)
        await session.flush()
        for values in [
            await agent_values(session, await session.get(Book, bid), "chief", author, [], "", False, False),
            await reply_values(session, await session.get(Book, bid), "chief", "chief", [], [author], ""),
        ]:
            assert values["memory"] == expected and "requirements" not in values
        private = await reply_values(session, await session.get(Book, bid), "chief", "chief", [], [author], "")
        assert private["how_to_apply"].endswith("作者要你记住什么，私聊里记不了，请作者到群聊里说「记住……」。")


async def test_create_update_duplicate_and_forced_local_words(sessionmaker):
    bid = await seed(sessionmaker)
    text, created, _ = await invoke(sessionmaker, bid, args())
    rid = created["memory"]["id"]
    assert text == f"做成了：记住了「每章留钩子」，编号记{rid}。"
    changed_args = args(id=f"记{rid}").model_copy(
        update={"summary": "结尾留悬念", "detail": "具体原话", "scope": "全局", "kind": "聊天时记得"}
    )
    text, changed, _ = await invoke(sessionmaker, bid, changed_args)
    assert text == f"做成了：记{rid} 改成了「结尾留悬念」。"
    assert changed["memory"]["before"]["summary"] == "每章留钩子"
    assert changed["memory"]["action"] == "update"
    text, duplicate, _ = await invoke(sessionmaker, bid, changed_args.model_copy(update={"id": ""}))
    assert text == f"做成了：目录里已经有这一条（记{rid}），没有重记。"
    assert duplicate["memory"]["id"] == rid
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Memory)) == 1
    for lasts in ("只管下一章", "只管这一卷", "只管下一卷"):
        tool = args().model_copy(update={"scope": "全局", "lasts": lasts, "summary": lasts})
        text, receipt, _ = await invoke(sessionmaker, bid, tool)
        assert receipt["memory"]["book_id"] == str(bid)
        assert (
            text
            == f"做成了：记住了「{lasts}」，编号记{receipt['memory']['id']}。只管下一章、这一卷、下一卷的只能放这本书，已经放进这本书。"
        )


@pytest.mark.parametrize("missing_kind", ["other_book", "deleted", "expired", "absent"])
async def test_ineligible_ids_for_update_forget_and_read(sessionmaker, missing_kind):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        other = Book(title="别的书")
        session.add(other)
        await session.flush()
        row = await remember(session, other.id if missing_kind == "other_book" else bid, "不可操作")
        if missing_kind == "deleted":
            from app.services.memories import forget

            await forget(session, row)
        if missing_kind == "expired":
            row.scope, row.chapter_index = "chapter", 1
            session.add(Chapter(book_id=bid, index=1, status="final"))
        await session.commit()
        code = f"记{row.id}" if missing_kind != "absent" else "记99999"
    for tool in [args(id=code), Forget(id=code)]:
        text, outcome, _ = await invoke(sessionmaker, bid, tool)
        assert text == f"没做成：没有这条记忆（{code}），只能改、删 <记忆> 目录里有的。" and outcome is None
    text, _, proof = await invoke(sessionmaker, bid, ReadMemory(ids=[code]))
    assert text == f"没有这条记忆：{code}" and proof[0][1] == text


async def test_read_memory_exact_blocks_and_delete_words(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        global_row = await remember(session, None, "不写床戏", "感情戏点到为止")
        chat_row = await remember(session, bid, "偏爱传统爽文", "举例像逆天邪神", kind="chat")
        await session.commit()
        gid, cid = global_row.id, chat_row.id
    text, _, proof = await invoke(sessionmaker, bid, ReadMemory(ids=[f"记{gid}", f"记{cid}", "记99999"]))
    assert (
        text
        == f"记{gid}（全局 · 写书时照做 · 一直有效）\n简述：不写床戏\n详细：感情戏点到为止\n\n记{cid}（这本书 · 聊天时记得）\n简述：偏爱传统爽文\n详细：举例像逆天邪神\n\n没有这条记忆：记99999"
    )
    assert [p[0] for p in proof[:2]] == ["记忆「不写床戏」", "记忆「偏爱传统爽文」"]
    text, receipt, _ = await invoke(sessionmaker, bid, Forget(id=f"记{cid}"))
    assert text == f"做成了：删掉了记{cid}「偏爱传统爽文」。" and receipt["memory"]["action"] == "forget"


@pytest.mark.parametrize("action", ["create", "update", "forget"])
async def test_all_undos_restore_full_values_and_reject_stale(client, sessionmaker, action):
    bid = await seed(sessionmaker)
    _, first, _ = await invoke(sessionmaker, bid, args())
    rid = first["memory"]["id"]
    async with sessionmaker() as session:
        before = snapshot(await session.get(Memory, rid))
    outcome = first
    if action == "update":
        _, outcome, _ = await invoke(
            sessionmaker,
            bid,
            args(id=f"记{rid}").model_copy(
                update={"kind": "聊天时记得", "scope": "全局", "summary": "改后简述", "detail": "改后原话"}
            ),
        )
    if action == "forget":
        _, outcome, _ = await invoke(sessionmaker, bid, Forget(id=f"记{rid}"))
    async with sessionmaker() as session:
        response = MeetingMessage(
            book_id=bid, speaker="chief", kind="speech", content="已照办", payload={"memories": [outcome]}
        )
        session.add(response)
        await session.commit()
        mid = response.id
    res = await client.post(f"/api/books/{bid}/memories/{rid}/undo", json={"version": outcome["memory"]["version"]})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        current = await session.get(Memory, rid)
        assert bool(current.deleted_at) == (action == "create")
        if action != "create":
            assert snapshot(current) == before
        response = await session.get(MeetingMessage, mid)
        assert response.payload["memories"][0]["undone"]
        assert "（作者点了撤销）" in done_text(response.payload["memories"][0])
    again = await client.post(f"/api/books/{bid}/memories/{rid}/undo", json={"version": outcome["memory"]["version"]})
    assert again.status_code == 409 and again.json()["detail"] in ("这条后来删掉了", "这条后来又改过，去「记忆」里改")


@pytest.mark.parametrize("action", ["create", "update", "forget"])
@pytest.mark.parametrize("later", ["update", "delete"])
async def test_later_edit_delete_rejects_undo(client, sessionmaker, later, action):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "记住，以后每章结尾都留个钩子")
    reply = await reply_of(client, bid, note["id"])
    first = reply["payload"]["memories"][0]["memory"]
    if action != "create":
        text = f"把记{first['id']}改成更少套话" if action == "update" else f"记{first['id']}这条不用记了"
        note = await say(client, bid, text)
        reply = await reply_of(client, bid, note["id"])
    receipt = reply["payload"]["memories"][0]["memory"]
    url = f"/api/books/{bid}/memories/{receipt['id']}"
    if action == "forget":
        assert (await client.post(url + "/restore")).status_code == 200
    if later == "update":
        res = await client.patch(url, json={"summary": "后改"})
    else:
        res = await client.delete(url)
    assert res.status_code in (200, 204)
    res = await client.post(url + "/undo", json={"version": receipt["version"]})
    assert res.status_code == 409
    assert res.json()["detail"] == ("这条后来删掉了" if later == "delete" else "这条后来又改过，去「记忆」里改")


async def test_agent_cross_conversation_ask_only_and_reanswer(client, sessionmaker):
    bid = await seed(sessionmaker)
    note = await say(client, bid, "我喜欢传统爽文，你觉得这本书适合吗？")
    assert note["payload"]["ask_only"]
    reply = await reply_of(client, bid, note["id"])
    receipt = reply["payload"]["memories"][0]["memory"]
    assert receipt["kind"] == "chat" and not receipt["book_id"]
    async with sessionmaker() as session:
        row = await session.get(Memory, receipt["id"])
        assert row.source == "聊天里记的" and row.message_id == note["id"]
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))
        assert "make_changes" not in str(calls[-1].request["schema"])
    again = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
    assert again.status_code == 202
    fresh = await reply_of(client, bid, note["id"])
    assert len(fresh["payload"]["memories"]) == 1
    assert fresh["payload"]["memories"][0]["memory"]["id"] == receipt["id"]
    assert fresh["payload"]["memories"] == reply["payload"]["memories"]
    async with sessionmaker() as session:
        last = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id.desc()))
        assert last.request["method"] == "demo_stream" and not last.request.get("schema")
        assert "【记忆】\n" + reply["payload"]["memories"][0]["model_text"] in last.request["user"]
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(BookSave)) == 0
    conv = await client.post(f"/api/books/{bid}/chat/conversations", json={})
    assert conv.status_code == 201, conv.text
    question = await say(client, bid, "你记得我说过什么吗？", conv=conv.json()["id"])
    answer = await reply_of(client, bid, question["id"])
    assert "传统爽文" in answer["content"]
    assert answer["payload"]["tools"][0]["label"] == f"记忆「{receipt['summary']}」"


@pytest.mark.parametrize("state", ["running", "waiting_author"])
async def test_memory_tools_work_while_busy_without_budget_or_pending(client, sessionmaker, state):
    bid = await seed(sessionmaker, state=state)
    note = await say(client, bid, "记住，以后每章结尾都留个钩子")
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["memories"][0]["memory"]["working"] == (state == "running")
    assert not note["payload"].get("steps")
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Memory)) == 1
        assert (await session.scalar(select(Job).where(Job.book_id == bid))).status == state
        assert await session.scalar(select(func.count()).select_from(BookSave)) == 0


async def test_teardown_tools_absent_and_runtime_guard(client, sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        (await session.get(Book, bid)).source = "teardown"
        await session.commit()
    note = await say(client, bid, "记住，以后每章结尾都留个钩子")
    reply = await reply_of(client, bid, note["id"])
    assert not reply["payload"].get("memories")
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid)))
        assert all(
            not set(chat_tools.MEMORY_TOOLS) & {tool["function"]["name"] for tool in call.request.get("schema", [])}
            for call in calls
        )
        assert await session.scalar(select(func.count()).select_from(Memory)) == 0
    from app.llm.router import ToolCall

    turn = Turn(None, bid, 0, 0, "chief", True, None, allow_memories=False)
    assert await run_tool(turn, ToolCall("x", "remember", args().model_dump())) == "拆的书群聊不能用记忆。"


async def test_memory_tools_do_not_consume_make_changes_budget(sessionmaker):
    from app.llm.router import ToolCall

    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        note = MeetingMessage(book_id=bid, speaker="author", kind="note", content="记住")
        response = MeetingMessage(
            book_id=bid, speaker="chief", kind="speech", content="", payload={"state": "thinking"}
        )
        session.add_all([note, response])
        await session.commit()
        mid, rid = note.id, response.id
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        turn = Turn(redis, bid, mid, rid, "chief", True, None, acts=2)
        for index in range(3):
            tool = args().model_copy(update={"summary": f"第{index}条"})
            assert (await run_tool(turn, ToolCall(str(index), "remember", tool.model_dump()))).startswith("做成了：")
        first = turn.memory_actions[0]["memory"]["id"]
        assert (await run_tool(turn, ToolCall("forget", "forget", {"id": f"记{first}"}))).startswith("做成了：")
        assert turn.acts == 2 and not turn.touched and not turn.done_keys and not turn.book_changed
        async with sessionmaker() as session:
            response = await session.get(MeetingMessage, rid)
            assert [item["memory"]["action"] for item in response.payload["memories"]] == ["create"] * 3 + ["forget"]
            assert (await session.get(Memory, first)).message_id == mid
            assert await session.scalar(select(func.count()).select_from(BookSave)) == 0
    finally:
        await redis.aclose()


async def test_undo_during_reply_is_not_overwritten_when_reply_finishes(client, sessionmaker, monkeypatch):
    from app.llm.router import LLMRouter, ToolCall

    bid = await seed(sessionmaker)

    async def rounds(self, role, system, user, specs, run, **kwargs):
        assert (await run(ToolCall("a", "remember", args().model_dump()))).startswith("做成了：")
        async with sessionmaker() as session:
            row = await session.scalar(select(Memory))
            rid, version = row.id, row.version
        res = await client.post(f"/api/books/{bid}/memories/{rid}/undo", json={"version": version})
        assert res.status_code == 200, res.text
        yield "text", "记好了，你又撤销了。"

    monkeypatch.setattr(LLMRouter, "tool_rounds", rounds)
    note = await say(client, bid, "记住，以后每章结尾都留个钩子")
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["memories"][0]["undone"] is True
    async with sessionmaker() as session:
        assert (await session.scalar(select(Memory))).deleted_at is not None


async def test_update_undo_after_original_source_message_is_deleted(client, sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        old = MeetingMessage(book_id=bid, speaker="author", kind="note", content="旧对话里说的")
        fresh = MeetingMessage(book_id=bid, speaker="author", kind="note", content="新对话里改的")
        session.add_all([old, fresh])
        await session.flush()
        _, created, _ = await execute(session, bid, old.id, args())
        rid = created["memory"]["id"]
        _, updated, _ = await execute(
            session, bid, fresh.id, args(id=f"记{rid}").model_copy(update={"summary": "新的规矩"})
        )
        response = MeetingMessage(
            book_id=bid, speaker="chief", kind="speech", content="已改", payload={"memories": [updated]}
        )
        session.add(response)
        await session.commit()
        await session.delete(old)
        await session.commit()
    res = await client.post(f"/api/books/{bid}/memories/{rid}/undo", json={"version": updated["memory"]["version"]})
    assert res.status_code == 200, res.text
    async with sessionmaker() as session:
        row = await session.get(Memory, rid)
        assert row.summary == "每章留钩子" and row.message_id is None


@pytest.mark.parametrize("action", ["create", "update", "forget"])
@pytest.mark.parametrize("undone", [False, True])
async def test_again_keeps_actual_memory_results_and_receipts(client, sessionmaker, monkeypatch, action, undone):
    from app.llm.router import LLMRouter, ToolCall

    bid = await seed(sessionmaker)
    rid = None
    if action != "create":
        _, existing, _ = await invoke(sessionmaker, bid, args())
        rid = existing["memory"]["id"]
    called, results = [], []

    async def rounds(self, role, system, user, specs, run, **kwargs):
        called.append(True)
        changed = await run(
            ToolCall(
                "edit",
                "make_changes",
                {"items": [{"kind": "改设定", "target": "楚风", "field": "personality", "instruction": "冷静沉稳"}]},
            )
        )
        assert "做成了：" in changed
        tool = (
            ToolCall("mem", "forget", {"id": f"记{rid}"})
            if action == "forget"
            else ToolCall("mem", "remember", args(id=f"记{rid}" if rid else "").model_dump())
        )
        results.append(await run(tool))
        yield "text", "改好也处理了记忆。"

    monkeypatch.setattr(LLMRouter, "tool_rounds", rounds)
    note = await say(client, bid, "把楚风的性格改成冷静，再处理记忆")
    reply = await reply_of(client, bid, note["id"])
    memory = reply["payload"]["memories"][0]["memory"]
    if undone:
        res = await client.post(f"/api/books/{bid}/memories/{memory['id']}/undo", json={"version": memory["version"]})
        assert res.status_code == 200, res.text
        reply = await reply_of(client, bid, note["id"])
    assert (await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")).status_code == 202
    fresh = await reply_of(client, bid, note["id"])
    assert called == [True] and fresh["payload"]["memories"] == reply["payload"]["memories"]
    async with sessionmaker() as session:
        last = await session.scalar(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id.desc()))
        assert last.request["method"] == "demo_stream" and not last.request.get("schema")
        material = last.request["user"]
        assert "【动手 1 处】" in material and "做成了：" in material
        assert "【记忆】\n" + results[0] + ("（作者点了撤销）" if undone else "") in material
    if not undone:
        res = await client.post(f"/api/books/{bid}/memories/{memory['id']}/undo", json={"version": memory["version"]})
        assert res.status_code == 200, res.text
        assert (await reply_of(client, bid, note["id"]))["payload"]["memories"][0]["undone"]
