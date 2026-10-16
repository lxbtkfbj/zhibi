"""第一包任务 2b：铁钉修改授权的快照、来源与一次性生命周期。"""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import schemas
from app.agents.setup_puzzle import merge_nodes
from app.graphs import book_setup
from app.llm import demo


def node(node_id, kind="milestone", status="pinned", origin="author"):
    return {
        "id": node_id,
        "kind": kind,
        "title": node_id,
        "event": f"{node_id}原事件",
        "prerequisite": "原前提",
        "consequence": "原后果",
        "volume": 2,
        "status": status,
        "origin": origin,
        "editor_note": "原批注",
        "techniques": [],
    }


def nodes():
    return [node("开篇", "opening", "pencil"), node("点名节点"), node("其他铁钉"), node("结局", "ending", "pencil")]


def drafts(current):
    return [
        {
            "ref": index,
            "kind": {"opening": "开篇", "milestone": "节点", "ending": "结局"}[item["kind"]],
            "title": f"新{item['title']}",
            "event": "按意见修改后的事件",
            "prerequisite": "新前提",
            "consequence": "新后果",
            "volume": 3,
            "editor_note": "新批注",
            "techniques": [],
        }
        for index, item in enumerate(current, 1)
    ]


def without_snapshot(item):
    return {key: value for key, value in item.items() if key not in {"_snapshot_ref", "segment"}}


@pytest.fixture
def env(monkeypatch):
    setup = {
        "concept": {"title": "铁钉测试"},
        "segment": {"core_conflict": "冲突", "theme": "主题", "protagonist_arc": "成长", "nodes": nodes()},
        "world": {"characters": []},
        "volumes": {"volumes": [], "threads": [{"name": "主线"}]},
        "first_volume": {"units": [{"index": 1}]},
    }
    session = SimpleNamespace(commit=AsyncMock(), get=AsyncMock(return_value=None))

    @asynccontextmanager
    async def sessions():
        yield session

    async def load_setup(*args):
        return deepcopy(setup)

    real_live_state = book_setup.live_state

    async def live_state(state, deps):
        return deepcopy(state)

    async def draft_segment(llm, concept, protagonist, world, requirements, current, instruction, **kwargs):
        return demo._segment("").model_copy(
            update={
                "nodes": [schemas.StoryNodeDraft.model_validate(item) for item in drafts(current["nodes"])],
                "remark": "主编完成本轮节点修改。",
            }
        )

    monkeypatch.setattr(book_setup, "live_state", live_state)
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    monkeypatch.setattr(book_setup, "_new_notes", AsyncMock(return_value=[]))
    monkeypatch.setattr(book_setup, "add_requirement", AsyncMock())
    monkeypatch.setattr(book_setup, "ingest_notes", AsyncMock())
    monkeypatch.setattr(book_setup, "playbook_text", lambda *args, **kwargs: "")
    monkeypatch.setattr(book_setup, "glossary_block", lambda: "")
    monkeypatch.setattr(book_setup.setup_store, "load_setup", load_setup)
    monkeypatch.setattr(book_setup.editorial, "draft_segment", draft_segment)
    monkeypatch.setattr("app.agents.glossary.terms", lambda: [])
    deps = SimpleNamespace(
        book_id="本书",
        job_id="开书任务",
        llm=object(),
        sessionmaker=sessions,
        check_cancel=AsyncMock(),
        emit=SimpleNamespace(say=AsyncMock(), status=AsyncMock(), artifact=AsyncMock()),
    )
    state = {
        **deepcopy(setup),
        "idea": "作者点子",
        "mode": "puzzle",
        "piece": "segment",
        "pieces": {"concept": "confirmed", "protagonist": "confirmed", "world": "confirmed", "segment": "waiting"},
        "queue": [],
        "instructions": {},
        "phase": "author_revise",
        "settings": {},
    }
    return SimpleNamespace(
        setup=setup, state=state, runtime=SimpleNamespace(context=deps), real_live_state=real_live_state
    )


def test_authorized_pin_changes_only_content_and_keeps_original_position(env):
    current = nodes()
    original = deepcopy(current)
    proposed = drafts(current)
    proposed[1].update(kind="结局", id="假ID", status="pencil", origin="ai")
    proposed = [proposed[0], proposed[2], proposed[1], proposed[3]]
    merged = merge_nodes(proposed, current, pinned_overrides={"点名节点"})
    assert current == original
    assert [item["id"] for item in merged] == [item["id"] for item in current]
    changed = merged[1]
    assert changed["event"] == "按意见修改后的事件"
    assert changed["title"] == "新点名节点" and changed["volume"] == 3
    assert {key: changed[key] for key in ("id", "kind", "status", "origin")} == {
        key: current[1][key] for key in ("id", "kind", "status", "origin")
    }
    assert without_snapshot(merged[2]) == current[2]
    assert changed["_snapshot_ref"] == 2


def test_authorized_pin_omitted_by_model_is_restored_unchanged(env):
    current = nodes()
    proposed = [item for item in drafts(current) if item["ref"] != 2]
    merged = merge_nodes(proposed, current, pinned_overrides={"点名节点"})
    assert without_snapshot(merged[1]) == current[1]
    assert without_snapshot(merged[2]) == current[2]


@pytest.mark.parametrize("change", ["omit_predecessors", "insert_before_ending"])
def test_authorized_position_survives_conflicting_ai_topology(env, change):
    current = [
        node("开篇", "opening", "pencil"),
        node("前置一", status="pencil"),
        node("前置二", status="pencil"),
        node("点名节点"),
        node("结局", "ending"),
    ]
    proposed = drafts(current)
    if change == "omit_predecessors":
        proposed = [item for item in proposed if item["ref"] not in {2, 3}]
        allowed = {"点名节点"}
    else:
        proposed.insert(1, {"ref": 0, "kind": "节点", "title": "AI顺带新增"})
        allowed = {"结局"}
    merged = merge_nodes(proposed, current, pinned_overrides=allowed)
    assert [item["id"] for item in merged] == [item["id"] for item in current]
    assert [item["kind"] for item in merged] == [item["kind"] for item in current]
    for index, item in enumerate(current):
        if item["id"] in allowed:
            assert merged[index]["event"] == "按意见修改后的事件"
            assert merged[index]["status"] == "pinned"
        elif item["status"] == "pinned":
            assert without_snapshot(merged[index]) == item


@pytest.mark.parametrize("status", ["pinned", "pencil"])
async def test_card_node_id_is_authority_even_when_triage_omits_override(env, monkeypatch, status):
    env.setup["segment"]["nodes"][1]["status"] = status
    monkeypatch.setattr(
        book_setup,
        "interrupt",
        lambda payload: {"action": "revise", "node_id": "点名节点", "feedback": "改为主动救出师父"},
    )
    triage = AsyncMock(return_value=schemas.RevisionTriage(remark="收到，按卡片里的意见修改。"))
    monkeypatch.setattr(book_setup.editorial, "triage_feedback", triage)
    command = await book_setup.piece_gate_node(env.state, env.runtime)
    assert command.goto == "intake"
    assert command.update["queue"] == ["segment", "volumes"]
    assert command.update["pinned_overrides"] == ["点名节点"]
    assert "只改节点 2" in command.update["instructions"]["segment"]
    update = await book_setup.segment_node({**env.state, **command.update}, env.runtime)
    changed, untouched = update["segment"]["nodes"][1:3]
    assert changed["event"] == "按意见修改后的事件" and changed["status"] == status
    assert without_snapshot(untouched) == env.setup["segment"]["nodes"][2]
    assert update["pinned_overrides"] == [] and update["pinned_override_sources"] == {}
    replies = [call.args[1] for call in env.runtime.context.emit.say.await_args_list]
    if status == "pinned":
        assert any("按你的意思改了铁钉节点 2「新点名节点」，它还是铁钉" in reply for reply in replies)
    else:
        assert not any("改了铁钉节点" in reply for reply in replies)


async def test_general_feedback_maps_only_valid_refs_from_its_prompt_snapshot(env, monkeypatch):
    env.state.update(mode="oneshot", feedback="把节点 2 改为救师父", node_snapshot=["错误的旧快照"])
    captured = []

    async def triage(llm, snapshot, requirements, feedback, **kwargs):
        captured.extend(item["id"] for item in snapshot["segment"]["nodes"])
        return schemas.RevisionTriage(
            segment_instructions="把节点 2 改为救师父",
            pinned_overrides=[2, 2, 0, -1, 99],
            remark="只改点名的节点。",
        )

    monkeypatch.setattr(book_setup.editorial, "triage_feedback", triage)
    update = await book_setup.triage_node(env.state, env.runtime)
    assert captured == [item["id"] for item in env.state["segment"]["nodes"]]
    assert update["pinned_overrides"] == ["点名节点"]
    # 分派后节点顺序变化，也按稳定 ID 授权，不能把「节点 2」的权限给另一个铁钉。
    current = deepcopy(env.state["segment"]["nodes"])
    current[1], current[2] = current[2], current[1]
    revised = await book_setup.segment_node(
        {**env.state, **update, "segment": {**env.state["segment"], "nodes": current}}, env.runtime
    )
    assert without_snapshot(revised["segment"]["nodes"][1]) == current[1]
    assert revised["segment"]["nodes"][2]["event"] == "按意见修改后的事件"


async def test_author_gate_to_triage_supports_oneshot_named_pin(env, monkeypatch):
    env.state["mode"] = "oneshot"
    monkeypatch.setattr(
        book_setup, "interrupt", lambda payload: {"action": "revise", "feedback": "把节点 2 改为救师父"}
    )
    monkeypatch.setattr(
        book_setup.editorial,
        "triage_feedback",
        AsyncMock(
            return_value=schemas.RevisionTriage(
                segment_instructions="把节点 2 改为救师父", pinned_overrides=[2], remark="只改这一处。"
            )
        ),
    )
    gate = await book_setup.author_gate_node(env.state, env.runtime)
    assert gate.goto == "triage"
    state = {**env.state, **gate.update}
    triage = await book_setup.triage_node(state, env.runtime)
    update = await book_setup.segment_node({**state, **triage}, env.runtime)
    assert update["segment"]["nodes"][1]["event"] == "按意见修改后的事件"
    assert update["segment"]["nodes"][1]["status"] == "pinned"
    assert without_snapshot(update["segment"]["nodes"][2]) == env.setup["segment"]["nodes"][2]
    assert update["pinned_overrides"] == []


async def test_interjection_maps_absorb_snapshot_and_preserves_unnamed_pin(env, monkeypatch):
    env.state.update(node_snapshot=["错误的旧快照"])
    monkeypatch.setattr(book_setup, "_new_notes", AsyncMock(return_value=[(8, "把节点 2 改为救师父", None)]))

    async def absorb(llm, done, todo, requirements, fresh, **kwargs):
        assert [item["id"] for item in done["segment"]["nodes"]] == [item["id"] for item in nodes()]
        return schemas.RevisionTriage(
            segment_instructions="把节点 2 改为救师父", pinned_overrides=[2, 99], remark="按这次插话修改。"
        )

    monkeypatch.setattr(book_setup.editorial, "absorb_notes", absorb)
    intake = await book_setup.intake_node(env.state, env.runtime)
    assert intake["notes_seen"] == 8 and intake["pinned_overrides"] == ["点名节点"]
    revised = await book_setup.segment_node({**env.state, **intake}, env.runtime)
    assert revised["segment"]["nodes"][1]["event"] == "按意见修改后的事件"
    assert without_snapshot(revised["segment"]["nodes"][2]) == env.setup["segment"]["nodes"][2]


@pytest.mark.parametrize("origin", ["triage", "notes"])
async def test_sync_only_plan_never_grants_model_reported_override(env, monkeypatch, origin):
    env.state.update(mode="oneshot", feedback="只改概念")
    result = schemas.RevisionTriage(concept_instructions="只改书名", pinned_overrides=[2], remark="同步下游。")
    if origin == "triage":
        monkeypatch.setattr(book_setup.editorial, "triage_feedback", AsyncMock(return_value=result))
        update = await book_setup.triage_node(env.state, env.runtime)
    else:
        monkeypatch.setattr(book_setup, "_new_notes", AsyncMock(return_value=[(9, "只改书名", None)]))
        monkeypatch.setattr(book_setup.editorial, "absorb_notes", AsyncMock(return_value=result))
        update = await book_setup.intake_node(env.state, env.runtime)
    assert update["instructions"]["segment"] == book_setup.SYNC_INSTRUCTIONS["segment"]
    assert not update.get("pinned_overrides")
    revised = await book_setup.segment_node({**env.state, **update}, env.runtime)
    assert without_snapshot(revised["segment"]["nodes"][1]) == env.setup["segment"]["nodes"][1]


async def test_locked_nodes_do_not_receive_interjection_permission(env, monkeypatch):
    env.state.update(
        piece="first_volume",
        pieces={
            "concept": "confirmed",
            "protagonist": "confirmed",
            "world": "confirmed",
            "segment": "confirmed",
            "first_volume": "waiting",
        },
    )
    monkeypatch.setattr(book_setup, "_new_notes", AsyncMock(return_value=[(9, "把节点 2 改为救师父", None)]))
    monkeypatch.setattr(
        book_setup.editorial,
        "absorb_notes",
        AsyncMock(
            return_value=schemas.RevisionTriage(
                segment_instructions="改节点 2", pinned_overrides=[2], remark="需要作者解锁。"
            )
        ),
    )
    update = await book_setup.intake_node(env.state, env.runtime)
    assert not update.get("pinned_overrides") and "segment" not in update.get("queue", [])
    assert any(item["target"] == "segment" for item in update["unlock_requests"])


async def test_consumed_permission_cannot_leak_to_next_revision(env):
    env.state.update(queue=["segment"], instructions={"segment": "按作者意见修改"}, pinned_overrides=["点名节点"])
    first = await book_setup.segment_node(env.state, env.runtime)
    state = {**env.state, **first, "queue": ["segment"], "instructions": {"segment": "下一轮只修改暂定节点"}}
    second = await book_setup.segment_node(state, env.runtime)
    assert without_snapshot(second["segment"]["nodes"][1]) == without_snapshot(first["segment"]["nodes"][1])
    assert first["pinned_overrides"] == second["pinned_overrides"] == []


@pytest.mark.parametrize("entry", ["critique", "piece_check"])
async def test_automatic_critique_discards_stale_author_permissions(env, monkeypatch, entry):
    env.state.update(pinned_overrides=["点名节点"], pinned_override_sources={"点名节点": ["上轮作者意见"]})
    monkeypatch.setattr(
        book_setup.editorial,
        "critique_setup",
        AsyncMock(
            return_value=schemas.SetupCritique(
                verdict="revise",
                issues=[
                    schemas.ReviewIssue(target="segment", severity="high", problem="铁钉不合理", suggestion="改铁钉")
                ],
                remark="建议调整。",
            )
        ),
    )
    if entry == "critique":
        env.state["mode"] = "oneshot"
        update = await book_setup.critique_node(env.state, env.runtime)
    else:
        update = (await book_setup.piece_check_node(env.state, env.runtime)).update
    assert update["pinned_overrides"] == [] and update["pinned_override_sources"] == {}
    revised = await book_setup.segment_node({**env.state, **update}, env.runtime)
    assert without_snapshot(revised["segment"]["nodes"][1]) == env.setup["segment"]["nodes"][1]


async def test_deleting_author_source_revokes_pending_permission(env, monkeypatch):
    env.state.update(
        instructions={"segment": "修改本轮授权的两个节点"},
        pinned_overrides=["点名节点", "其他铁钉"],
        pinned_override_sources={"点名节点": ["已删意见"], "其他铁钉": ["仍有效意见"]},
    )
    monkeypatch.setattr(book_setup, "import_legacy_checkpoint", AsyncMock())
    monkeypatch.setattr(book_setup, "list_requirements", AsyncMock(return_value=[]))
    monkeypatch.setattr(book_setup, "deleted_texts", AsyncMock(return_value={"已删意见"}))
    update = await env.real_live_state(env.state, env.runtime.context)
    assert update["pinned_overrides"] == ["其他铁钉"]
    assert update["pinned_override_sources"] == {"其他铁钉": ["仍有效意见"]}


async def test_deleted_merged_author_instruction_cannot_authorize_reviewer_fallback(env, monkeypatch):
    env.state.update(
        instructions={"segment": "合并两条作者意见后的修改"},
        instruction_sources={"segment": ["已删意见", "仍有效意见"]},
        instruction_fallbacks={"segment": "审稿建议改掉所有铁钉"},
        pinned_overrides=["点名节点", "其他铁钉"],
        pinned_override_sources={"点名节点": ["已删意见"], "其他铁钉": ["仍有效意见"]},
    )
    monkeypatch.setattr(book_setup, "import_legacy_checkpoint", AsyncMock())
    monkeypatch.setattr(book_setup, "list_requirements", AsyncMock(return_value=[]))
    monkeypatch.setattr(book_setup, "deleted_texts", AsyncMock(return_value={"已删意见"}))
    update = await env.real_live_state(env.state, env.runtime.context)
    assert update["instructions"]["segment"] == "审稿建议改掉所有铁钉"
    assert update["pinned_overrides"] == [] and update["pinned_override_sources"] == {}


async def test_second_interjection_adds_authorization_while_spine_revision_is_pending(env, monkeypatch):
    monkeypatch.setattr(
        book_setup,
        "_new_notes",
        AsyncMock(side_effect=[[(10, "把节点 2 改为救师父", None)], [(11, "节点 3 也改成主动出击", None)]]),
    )
    seen = []

    async def absorb(llm, done, todo, requirements, fresh, **kwargs):
        assert "segment" in done
        seen.append(fresh)
        ref = 2 if len(seen) == 1 else 3
        return schemas.RevisionTriage(
            segment_instructions=f"按这次插话修改节点 {ref}", pinned_overrides=[ref], remark="本轮一起修改。"
        )

    monkeypatch.setattr(book_setup.editorial, "absorb_notes", absorb)
    first = await book_setup.intake_node(env.state, env.runtime)
    assert first["queue"] == ["segment", "volumes"] and first["pinned_overrides"] == ["点名节点"]
    state = {**env.state, **first}
    second = await book_setup.intake_node(state, env.runtime)
    assert second["pinned_overrides"] == ["点名节点", "其他铁钉"]
    assert second["pinned_override_sources"] == {
        "点名节点": ["把节点 2 改为救师父"],
        "其他铁钉": ["节点 3 也改成主动出击"],
    }
    assert "节点 2" in second["instructions"]["segment"] and "节点 3" in second["instructions"]["segment"]
    revised = await book_setup.segment_node({**state, **second}, env.runtime)
    assert all(item["event"] == "按意见修改后的事件" for item in revised["segment"]["nodes"][1:3])
    assert revised["pinned_overrides"] == []


@pytest.mark.parametrize("action", ["reopen", "unlock"])
async def test_unlock_with_named_feedback_grants_only_the_named_pin(env, monkeypatch, action):
    env.state.update(
        piece="first_volume",
        pieces={
            "concept": "confirmed",
            "protagonist": "confirmed",
            "world": "confirmed",
            "segment": "confirmed",
            "first_volume": "waiting",
        },
        pinned_overrides=["其他铁钉"],
        pinned_override_sources={"其他铁钉": ["上轮旧意见"]},
    )
    monkeypatch.setattr(
        book_setup,
        "interrupt",
        lambda payload: {"action": action, "piece": "segment", "feedback": "把节点 2 改为救师父"},
    )

    async def triage(llm, setup, requirements, feedback, **kwargs):
        assert "第一段" not in kwargs["locked"]
        assert "节点 2" in feedback
        return schemas.RevisionTriage(
            segment_instructions="把节点 2 改为救师父", pinned_overrides=[2], remark="解锁后按点名意见修改。"
        )

    monkeypatch.setattr(book_setup.editorial, "triage_feedback", triage)
    command = await book_setup.piece_gate_node(env.state, env.runtime)
    assert command.goto == "intake" and command.update["piece"] == "segment"
    assert command.update["pieces"]["segment"] == "drafting" and command.update["pieces"]["first_volume"] == "todo"
    assert command.update["pinned_overrides"] == ["点名节点"]
    revised = await book_setup.segment_node({**env.state, **command.update}, env.runtime)
    assert revised["segment"]["nodes"][1]["event"] == "按意见修改后的事件"
    assert without_snapshot(revised["segment"]["nodes"][2]) == env.setup["segment"]["nodes"][2]


@pytest.mark.parametrize("change", ["move_pin", "omit_pin", "omit_predecessors", "insert_before_pinned_ending"])
def test_unnamed_pins_keep_latest_author_snapshot_positions(env, change):
    # 作者已插入铁钉、删除旧节点并手动重排；current 是这些操作之后的最新顺序。
    current = [
        node("开篇", "opening", "pencil"),
        node("已上移的暂定", status="pencil"),
        node("待修改暂定", status="pencil"),
        node("作者新增铁钉"),
        node("已有铁钉"),
        node("结局", "ending"),
    ]
    original = deepcopy(current)
    proposed = drafts(current)
    if change == "move_pin":
        proposed[1], proposed[3] = proposed[3], proposed[1]
    elif change == "omit_pin":
        proposed = [item for item in proposed if item["ref"] != 4]
    elif change == "omit_predecessors":
        proposed = [item for item in proposed if item["ref"] not in {2, 3}]
    else:
        proposed.insert(2, {"ref": 0, "kind": "节点", "title": "AI顺带新增"})
    merged = merge_nodes(proposed, current)
    assert current == original
    for index, item in enumerate(current):
        if item["status"] == "pinned":
            assert without_snapshot(merged[index]) == item
            assert merged[index]["_snapshot_ref"] == index + 1
    assert merged[0]["kind"] == "opening" and merged[-1]["kind"] == "ending"
