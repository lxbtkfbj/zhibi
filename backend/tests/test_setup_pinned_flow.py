"""铁钉点名修改的真实接口、持久化与 PostgreSQL 检查点集成验收。"""

import uuid

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agents import editorial, schemas
from app.config import get_settings
from app.graphs.book_setup import build_setup_graph
from app.llm import demo
from app.models import Book, Job, StoryNode
from tests import test_setup_puzzle_flow as puzzle_flow

flow = puzzle_flow.flow


@pytest.fixture
def aggressive_node_rewrite(monkeypatch):
    """首次起草用演示模型；修改时故意改写所有节点，检验程序而非模型自觉保护铁钉。"""
    original = editorial.draft_segment
    calls = []

    async def rewrite(llm, concept, protagonist, world, requirements, current, instruction, **kwargs):
        if not current:
            return await original(llm, concept, protagonist, world, requirements, current, instruction, **kwargs)
        calls.append(instruction)
        items = [
            schemas.StoryNodeDraft(
                ref=index,
                kind={"opening": "开篇", "milestone": "节点", "ending": "结局"}[node["kind"]],
                title=node["title"],
                event=f"第 {len(calls)} 轮改写：主角主动救出师父。",
                prerequisite=node["prerequisite"],
                consequence=node["consequence"],
                volume=node["volume"] or 1,
                editor_note=node["editor_note"],
                techniques=node["techniques"],
            )
            for index, node in enumerate(current["nodes"], 1)
        ]
        return demo._segment("").model_copy(
            update={
                "core_conflict": current["core_conflict"],
                "theme": current["theme"],
                "protagonist_arc": current["protagonist_arc"],
                "nodes": items,
                "remark": "节点修改完成。",
            }
        )

    monkeypatch.setattr(editorial, "draft_segment", rewrite)
    return calls


async def setup_waiting(flow, mode):
    if mode == "puzzle":
        book_id, job_id = await puzzle_flow.new_puzzle(flow)
        for piece in ("concept", "protagonist", "world"):
            await puzzle_flow.confirm(flow, job_id, piece)
    else:
        result = await flow("POST", "/books", {"idea": "一个少年捡到青灯", "mode": "oneshot"})
        book_id, job_id = result["book"]["id"], result["job"]["id"]
        assert (await flow("GET", f"/jobs/{job_id}"))["pending"]["kind"] == "setup_review"
    before = await flow("GET", f"/books/{book_id}/nodes")
    for index in range(4):
        await flow(
            "POST",
            f"/books/{book_id}/nodes",
            {
                "title": f"作者远景{index}",
                "event": "作者已经想到的远景",
                "status": "pencil",
                "after_node_id": before[1]["id"],
            },
        )
    before = await flow("GET", f"/books/{book_id}/nodes")
    for item in before[1:3]:
        await flow("PATCH", f"/nodes/{item['id']}", {"status": "pinned"})
    return book_id, job_id, await flow("GET", f"/books/{book_id}/nodes")


async def assert_checkpoint_consumed(sessionmaker, job_id):
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        assert job.status == "waiting_author", job.error
        thread_id = job.thread_id
        book = await session.get(Book, job.book_id)
        for value in (book.settings, book.setup_progress, book.spine):
            assert "pinned_overrides" not in value and "pinned_override_sources" not in value
    async with AsyncPostgresSaver.from_conn_string(get_settings().checkpoint_dsn) as saver:
        graph = build_setup_graph().compile(checkpointer=saver)
        checkpoint = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert checkpoint.values["pinned_overrides"] == []
    assert checkpoint.values["pinned_override_sources"] == {}


async def assert_pinned_result(flow, sessionmaker, book_id, before, expected_event):
    after = await flow("GET", f"/books/{book_id}/nodes")
    assert [item["id"] for item in after] == [item["id"] for item in before]
    changed, untouched = after[1:3]
    assert changed["event"] == expected_event
    for key in ("id", "kind", "status", "origin", "index"):
        assert changed[key] == before[1][key]
    # 下游设定可能重建锚点；节点本身的全部内容和状态都必须原样保留。
    assert {key: value for key, value in untouched.items() if key != "anchors"} == {
        key: value for key, value in before[2].items() if key != "anchors"
    }
    async with sessionmaker() as session:
        persisted = list(
            await session.scalars(
                select(StoryNode).where(StoryNode.book_id == uuid.UUID(book_id)).order_by(StoryNode.position)
            )
        )
        assert [str(item.id) for item in persisted] == [item["id"] for item in before]
        assert persisted[1].position == before[1]["index"]
        assert persisted[1].event == expected_event and persisted[1].status == "pinned"
    return after


async def test_demo_without_node_model_substitution_revises_named_pin(flow, sessionmaker):
    book_id, job_id, before = await setup_waiting(flow, "puzzle")
    await flow(
        "POST",
        f"/jobs/{job_id}/piece",
        {
            "action": "revise",
            "piece": "segment",
            "node_id": before[1]["id"],
            "feedback": "发生什么改为主角主动救出师父",
        },
    )
    await assert_pinned_result(flow, sessionmaker, book_id, before, "主角主动救出师父")
    await assert_checkpoint_consumed(sessionmaker, job_id)


@pytest.mark.parametrize("mode", ["puzzle", "oneshot"])
async def test_named_pin_http_persistence_and_one_round_permission(flow, sessionmaker, aggressive_node_rewrite, mode):
    book_id, job_id, before = await setup_waiting(flow, mode)
    if mode == "puzzle":
        path = f"/jobs/{job_id}/piece"
        body = {
            "action": "revise",
            "piece": "segment",
            "node_id": before[1]["id"],
            "feedback": "改成主角主动救出师父",
        }
    else:
        path = f"/jobs/{job_id}/decision"
        body = {"action": "revise", "feedback": "请把节点 2 改成主角主动救出师父"}
    await flow("POST", path, body)
    after = await assert_pinned_result(flow, sessionmaker, book_id, before, "第 1 轮改写：主角主动救出师父。")
    assert len(aggressive_node_rewrite) == 1
    await assert_checkpoint_consumed(sessionmaker, job_id)
    messages = await flow("GET", f"/books/{book_id}/meeting")
    receipts = [
        item["content"]
        for item in messages
        if item["speaker"] == "chief" and item["content"].startswith("按你的意思改了铁钉节点")
    ]
    assert receipts == [f"按你的意思改了铁钉节点 2「{before[1]['title']}」，它还是铁钉。"]

    if mode == "puzzle":
        # 再次调用节点模型，但只修改暂定卡片；上轮铁钉授权不得复用。
        body = {
            "action": "revise",
            "piece": "segment",
            "node_id": before[3]["id"],
            "feedback": "只调整这张暂定卡片的铺垫",
        }
    else:
        # 演示分派仍读到历史作者要求里的点名句，但本轮没有点名，不能重新授权。
        body = {"action": "revise", "feedback": "第一卷的节奏再紧凑一点"}
    await flow("POST", path, body)
    await assert_pinned_result(flow, sessionmaker, book_id, after, after[1]["event"])
    assert len(aggressive_node_rewrite) == (2 if mode == "puzzle" else 1)
    await assert_checkpoint_consumed(sessionmaker, job_id)
    messages = await flow("GET", f"/books/{book_id}/meeting")
    assert sum(item["content"].startswith("按你的意思改了铁钉节点") for item in messages) == 1


async def test_running_author_note_http_is_absorbed_for_named_pin(
    flow, sessionmaker, monkeypatch, aggressive_node_rewrite
):
    book_id, job_id, before = await setup_waiting(flow, "oneshot")
    original = editorial.plan_volume
    delivered = []

    async def interject(*args, **kwargs):
        if not delivered:
            delivered.append(
                await flow(
                    "POST",
                    f"/books/{book_id}/notes",
                    {"content": "把节点 2 改成主角主动救出师父"},
                    run=False,
                )
            )
        return await original(*args, **kwargs)

    monkeypatch.setattr(editorial, "plan_volume", interject)
    await flow("POST", f"/jobs/{job_id}/decision", {"action": "revise", "feedback": "第一卷节奏再紧凑一点"})
    assert len(delivered) == 1 and delivered[0]["job_id"] == job_id
    await assert_pinned_result(flow, sessionmaker, book_id, before, "第 1 轮改写：主角主动救出师父。")
    assert len(aggressive_node_rewrite) == 1
    await assert_checkpoint_consumed(sessionmaker, job_id)
    messages = await flow("GET", f"/books/{book_id}/meeting")
    assert any(
        item["speaker"] == "chief"
        and item["content"] == f"按你的意思改了铁钉节点 2「{before[1]['title']}」，它还是铁钉。"
        for item in messages
    )


async def test_pencil_revision_keeps_author_inserted_pins_after_delete_and_reorder(flow, sessionmaker):
    book_id, job_id, before = await setup_waiting(flow, "puzzle")
    inserted = await flow(
        "POST",
        f"/books/{book_id}/nodes",
        {"title": "作者新增铁钉", "event": "救回师父", "status": "pinned", "after_node_id": before[2]["id"]},
    )
    await flow("DELETE", f"/nodes/{before[4]['id']}")
    nodes = await flow("GET", f"/books/{book_id}/nodes")
    ids = [item["id"] for item in nodes]
    index = ids.index(inserted["id"])
    # 把后面的暂定节点移到旧铁钉前，快照顺序故意与演示初稿不同。
    ids[index - 1], ids[index + 1] = ids[index + 1], ids[index - 1]
    await flow("POST", f"/books/{book_id}/nodes/order", {"ids": ids})
    snapshot = await flow("GET", f"/books/{book_id}/nodes")
    selected = next(item for item in snapshot if item["kind"] == "milestone" and item["status"] == "pencil")
    await flow(
        "POST",
        f"/jobs/{job_id}/piece",
        {
            "action": "revise",
            "piece": "segment",
            "node_id": selected["id"],
            "feedback": "发生什么改为先救下被困的同门",
        },
    )
    after = await flow("GET", f"/books/{book_id}/nodes")
    for item in snapshot:
        if item["status"] == "pinned":
            assert next(node for node in after if node["id"] == item["id"]) == item
    assert next(item for item in after if item["id"] == selected["id"])["event"] == "先救下被困的同门"
    await assert_checkpoint_consumed(sessionmaker, job_id)
