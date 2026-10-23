"""看稿意见只改当前一步；拆给大纲的话只存在本轮开书状态。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents import schemas
from app.graphs import book_setup, write_book
from app.llm import demo_setup
from app.models import Book, Job, Memory, PlotUnit, Volume
from app.services import requirements as memory_requirements
from app.services.memories import forget


def runtime(sessionmaker=None, **values):
    return SimpleNamespace(
        context=SimpleNamespace(
            sessionmaker=sessionmaker,
            llm=object(),
            emit=SimpleNamespace(say=AsyncMock(), status=AsyncMock(), artifact=AsyncMock()),
            check_cancel=AsyncMock(),
            **values,
        )
    )


async def unchanged(state, *_args, **_kwargs):
    return state


async def test_combined_feedback_returns_outline_instruction_without_memory_write(monkeypatch):
    result = schemas.SetupNotePlan(outline_instructions="第一篇先找到失踪的师姐", remark="这次排大纲时会带上。")
    monkeypatch.setattr(book_setup.editorial, "absorb_notes", AsyncMock(return_value=result))
    rt = runtime()
    text = await book_setup._combined_feedback(rt.context, {}, "大纲先安排找师姐")
    assert text == "第一篇先找到失踪的师姐"
    rt.context.emit.say.assert_awaited_once_with("chief", result.remark)
    # 没有 sessionmaker，也能完成：该句不再调用持久化记忆接口。


def test_setup_requirements_append_transient_outline_after_memories_only_in_setup():
    state = {
        "live_requirements": ["全局的规矩", "这本书的规矩"],
        "outline_instructions": ["第一篇先找到失踪的师姐"],
    }
    text = book_setup.requirements(state)
    assert text.index("全局的规矩") < text.index("这本书的规矩") < text.index("第一篇先找到失踪的师姐")
    assert "outline_instructions" not in write_book.initial_state({})
    assert "setup_requirements" not in write_book.initial_state({})


async def test_settings_gate_keeps_and_deduplicates_outline_instructions(monkeypatch):
    monkeypatch.setattr(book_setup, "live_state", unchanged)
    monkeypatch.setattr(book_setup, "interrupt", lambda _: {"action": "revise", "feedback": "定调这一处改一下"})
    combined = AsyncMock(return_value="第一篇先找到失踪的师姐")
    monkeypatch.setattr(book_setup, "_combined_feedback", combined)
    state = {
        "piece": "settings",
        "library": {"summary": "设定库只改这一处。"},
        "outline_instructions": ["第一篇先找到失踪的师姐", "第二篇再回宗门"],
    }
    rt = runtime()
    result = await book_setup.piece_gate_node(state, rt)
    assert result.goto == "piece_gate"
    combined.assert_awaited_once_with(rt.context, state, "定调这一处改一下")
    assert rt.context.emit.say.await_count == 1
    assert result.update["outline_instructions"] == ["第一篇先找到失踪的师姐", "第二篇再回宗门"]


@pytest.mark.parametrize("piece", ["concept", "outline"])
async def test_piece_revision_keeps_raw_feedback_and_flips_without_memory(monkeypatch, piece):
    monkeypatch.setattr(book_setup, "live_state", unchanged)
    monkeypatch.setattr(
        book_setup,
        "interrupt",
        lambda _: {
            "action": "revise",
            "feedback": "眼前这一处先收紧节奏",
            "flips": [{"topic": "场景", "choice": "雨夜"}],
        },
    )
    result = await book_setup.piece_gate_node({"piece": piece}, runtime())
    assert result.goto == "intake"
    assert "眼前这一处先收紧节奏" in result.update["instructions"][piece]
    assert "把「场景」改成「雨夜」" in result.update["instructions"][piece]
    assert "instruction_sources" not in result.update


async def test_prefill_feedback_reaches_pitch_material_without_becoming_memory(monkeypatch):
    monkeypatch.setattr(book_setup, "interrupt", lambda _: {"action": "start", "feedback": "先按雨夜追凶来想方向"})
    result = await book_setup.prefill_gate_node({}, runtime())
    assert result == {
        "prefill": False,
        "previous": "【作者的意见】\n先按雨夜追凶来想方向",
        "previous_feedback": "先按雨夜追凶来想方向",
    }
    assert "先按雨夜追凶来想方向" not in book_setup.requirements(result)


async def test_outline_chapters_receives_transient_setup_requirements(monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield object()

    monkeypatch.setattr(book_setup, "live_state", unchanged)
    monkeypatch.setattr(book_setup.setup_store, "load_new_setup", AsyncMock(return_value={}))
    plan = AsyncMock()
    monkeypatch.setattr(write_book, "plan_chapters_node", plan)
    state = {
        "outline": {"units": [{"id": "first-unit"}]},
        "live_requirements": ["本书常驻规矩"],
        "outline_instructions": ["第一篇先找到失踪的师姐"],
    }
    rt = runtime(sessions, book_id="book")
    await book_setup.outline_chapters_node(state, rt)
    plan.assert_awaited_once_with({"unit_id": "first-unit", "setup_requirements": book_setup.requirements(state)}, rt)


async def test_confirm_preserves_transient_outline_but_finalize_clears_it(monkeypatch):
    book = SimpleNamespace(status="setting_up")

    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(get=AsyncMock(return_value=book), scalar=AsyncMock(return_value=0), commit=AsyncMock())

    monkeypatch.setattr(book_setup, "live_state", unchanged)
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    rt = runtime(sessions, book_id="book")
    state = {"piece": "settings", "outline_instructions": ["第一篇先找到失踪的师姐"]}
    confirmed = await book_setup._confirm_piece(state, rt.context)
    assert confirmed.goto == "intake" and confirmed.update["piece"] == "outline"
    assert "outline_instructions" not in confirmed.update
    finalized = await book_setup.finalize_node({**state, **confirmed.update}, rt)
    assert finalized["outline_instructions"] == []
    assert "第一篇先找到失踪的师姐" not in book_setup.requirements({**state, **finalized})


async def test_deleted_memory_does_not_cancel_current_feedback_or_outline_instructions(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="当次改稿独立于记忆")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="book_setup", thread_id="feedback-only", params={"flow": 3})
        session.add(job)
        memory = await memory_requirements.add_requirement(session, book.id, "眼前这一步照旧要改")
        await forget(session, memory)
        await session.commit()
        bid, jid = book.id, job.id
    state = {
        "requirements_ledger_ready": True,
        "feedback": "眼前这一步照旧要改",
        "feedback_sources": ["眼前这一步照旧要改"],
        "previous": "上一轮方向和作者原话",
        "previous_feedback": "眼前这一步照旧要改",
        "instructions": {"concept": "审稿要求修复逻辑。眼前这一步照旧要改"},
        "instruction_sources": {"concept": ["眼前这一步照旧要改"]},
        "instruction_fallbacks": {"concept": "审稿要求修复逻辑。"},
        "outline_instructions": ["第一篇先找到失踪的师姐"],
    }
    current = await book_setup.live_state(state, runtime(sessionmaker, book_id=bid, job_id=jid).context)
    assert current["feedback"] == state["feedback"]
    assert current["previous"] == state["previous"]
    assert current["instructions"] == state["instructions"]
    assert current["outline_instructions"] == state["outline_instructions"]
    assert current["live_requirements"] == []
    async with sessionmaker() as session:
        assert "第一篇先找到失踪的师姐" not in {
            row.detail for row in await session.scalars(select(Memory).where(Memory.book_id == bid))
        }


async def test_outline_prompt_gets_absorbed_instruction_after_live_memory_without_saving_it(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book = Book(title="只在当次大纲里带着")
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind="book_setup", thread_id="transient-outline", params={"flow": 3})
        session.add(job)
        await memory_requirements.add_requirement(session, book.id, "全书照做的常驻规矩")
        await session.commit()
        bid, jid = book.id, job.id
    absorbed = AsyncMock(
        return_value=schemas.SetupNotePlan(
            outline_instructions="第一篇先找到失踪的师姐", remark="只在这次开书排大纲时带上。"
        )
    )
    monkeypatch.setattr(book_setup.editorial, "absorb_notes", absorbed)
    rt = runtime(sessionmaker, book_id=bid, job_id=jid)
    instruction = await book_setup._combined_feedback(rt.context, {}, "大纲先安排找师姐")
    draft = demo_setup.outline("")
    monkeypatch.setattr(book_setup.editorial, "draft_setup_outline", planned := AsyncMock(return_value=draft))
    monkeypatch.setattr(book_setup.setup_store, "save_outline", AsyncMock())
    monkeypatch.setattr(
        book_setup.setup_store, "load_new_setup", AsyncMock(return_value={"outline": draft.model_dump()})
    )
    await book_setup.outline_node(
        {"requirements_ledger_ready": True, "queue": ["outline"], "outline_instructions": [instruction]}, rt
    )
    material = planned.await_args.args[1]["requirements"]
    assert material.index("全书照做的常驻规矩") < material.index("第一篇先找到失踪的师姐")
    async with sessionmaker() as session:
        assert [row.detail for row in await session.scalars(select(Memory).where(Memory.book_id == bid))] == [
            "全书照做的常驻规矩"
        ]


async def test_setup_chapter_planning_uses_transient_but_later_writing_does_not(sessionmaker, monkeypatch):
    async with sessionmaker() as session:
        book = Book(title="本轮开书排大纲")
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="第一卷")
        session.add(volume)
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="第一单元", chapter_count=1)
        session.add(unit)
        await memory_requirements.add_requirement(session, book.id, "全书照做的常驻规矩")
        await session.commit()
        bid, uid = book.id, unit.id
    draft = schemas.ChapterPlanDraft(
        chapters=[
            schemas.ChapterOutlineDraft(
                title="找到师姐", goal="找到线索", scenes=[], conflict="追兵", cool_point="脱身", hook="师姐失踪"
            )
        ],
        remark="安排好了。",
    )
    planned = AsyncMock(return_value=draft)
    monkeypatch.setattr(write_book.editorial, "plan_chapters", planned)
    monkeypatch.setattr(write_book, "_chapter_plan_issues", lambda *_: [])
    rt = runtime(sessionmaker, book_id=bid)
    temporary = book_setup.requirements(
        {"live_requirements": ["全书照做的常驻规矩"], "outline_instructions": ["第一篇先找到失踪的师姐"]}
    )
    await write_book.prepare_unit_chapters({"unit_id": str(uid), "setup_requirements": temporary}, rt, persist=False)
    assert "第一篇先找到失踪的师姐" in planned.await_args.args[1]["requirements"]
    await write_book.prepare_unit_chapters({"unit_id": str(uid)}, rt, persist=False)
    later = planned.await_args.args[1]["requirements"]
    assert "全书照做的常驻规矩" in later and "第一篇先找到失踪的师姐" not in later
    async with sessionmaker() as session:
        assert [row.detail for row in await session.scalars(select(Memory).where(Memory.book_id == bid))] == [
            "全书照做的常驻规矩"
        ]
