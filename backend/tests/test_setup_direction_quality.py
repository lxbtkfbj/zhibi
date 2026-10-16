"""任务 6：最近一轮上下文、作者选名兜底与按本书设置估算篇幅。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents.context import format_direction_choice, format_previous_directions
from app.graphs import book_setup
from app.graphs.book_setup import length_question
from app.llm import demo
from app.models import AuthorRequirement, Book
from app.services.requirements import add_requirement, suppress_legacy_text


@pytest.mark.parametrize(
    "words,counts",
    [(3000, [170, 330, 670, 1000, 1670]), (2000, [250, 500, 1000, 1500, 2500])],
)
def test_length_question_five_options(words, counts):
    question = length_question(words)
    assert question == {
        "question": "这本书打算写多长？",
        "options": [
            f"约 50 万字（短篇，约 {counts[0]} 章）",
            f"约 100 万字（中篇，约 {counts[1]} 章）",
            f"约 200 万字（长篇，约 {counts[2]} 章）",
            f"约 300 万字（长篇，约 {counts[3]} 章）",
            f"500 万字以上（超长篇，约 {counts[4]} 章起）",
        ],
        "recommended": 2,
        "chapter_words": words,
    }


def test_length_question_fallback_and_half_up_rounding():
    assert length_question() == length_question(None) == length_question(3000)
    assert length_question(4000)["options"][0] == "约 50 万字（短篇，约 130 章）"


def test_direction_context_new_fields_and_old_data():
    assert format_previous_directions(None) == format_previous_directions({}) == ""
    direction = {
        "name": "旧案追凶流",
        "logline": "少年用古镜寻找旧案真相",
        "golden_finger": "映出现场遗漏的线索",
        "stage_ladder": "老城区 → 整座城市 → 省城",
        "titles": ["镜中追凶", "捕快照夜"],
        "title": "镜中追凶",
    }
    chosen = format_direction_choice(direction)
    assert "书名候选：《镜中追凶》《捕快照夜》" in chosen
    assert "作者选定的书名：《镜中追凶》" in chosen
    assert "作者选定的书名" not in format_direction_choice({"name": "旧方向"})
    previous = format_previous_directions(
        {"reference": "对标作品以追凶和经营结合", "directions": [direction], "feedback": "保留经营"}
    )
    assert previous == (
        "【上一轮的方向（作者不满意）】\n"
        "你对对标作品的理解：对标作品以追凶和经营结合\n"
        "1. 方向「旧案追凶流」：少年用古镜寻找旧案真相；金手指：映出现场遗漏的线索；"
        "舞台阶梯：老城区 → 整座城市 → 省城；书名候选：《镜中追凶》《捕快照夜》\n"
        "作者的意见：保留经营"
    )
    legacy = format_previous_directions({"directions": [{"name": "旧方向"}], "feedback": "换一个"})
    assert "旧方向" in legacy and "作者的意见：换一个" in legacy
    assert "对标作品的理解" not in legacy and "书名候选" not in legacy


@pytest.fixture
async def runtime(sessionmaker):
    async with sessionmaker() as session:
        book = Book(idea="一个追凶故事", settings={"chapter_words": 2000})
        session.add(book)
        await session.commit()
    return SimpleNamespace(
        context=SimpleNamespace(
            sessionmaker=sessionmaker,
            book_id=book.id,
            job_id=None,
            llm=None,
            check_cancel=AsyncMock(),
            emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
        )
    )


async def test_redo_replaces_only_latest_round_and_preserves_legacy_checkpoint(runtime, monkeypatch):
    pending = []
    monkeypatch.setattr(
        book_setup,
        "interrupt",
        lambda value: (
            pending.append(value) or {"action": "redo", "feedback": "  保留经营  ", "requirement_saved": True}
        ),
    )
    state = {
        "directions": [{"name": "本轮方向"}],
        "reference": "本轮理解",
        "previous_directions": {"directions": [{"name": "更早方向"}], "feedback": "之前的意见"},
    }
    result = await book_setup.directions_gate_node(state, runtime)
    assert result.goto == "directions"
    assert result.update == {
        "previous_directions": {
            "reference": "本轮理解",
            "directions": [{"name": "本轮方向"}],
            "feedback": "保留经营",
        }
    }
    assert pending[0]["reference"] == "本轮理解"
    assert pending[0]["length"] == length_question(2000)
    state["directions"][0]["name"] = "之后修改不能污染快照"
    assert result.update["previous_directions"]["directions"][0]["name"] == "本轮方向"
    legacy = await book_setup.directions_gate_node({"directions": [{"name": "旧方向"}]}, runtime)
    assert pending[1]["reference"] == legacy.update["previous_directions"]["reference"] == ""


async def test_legacy_resume_without_requirement_saved_records_selected_title(runtime, monkeypatch):
    monkeypatch.setattr(
        book_setup,
        "interrupt",
        lambda value: {"action": "choose", "choice": 0, "title": "选中书名", "length": "约 200 万字"},
    )
    result = await book_setup.directions_gate_node(
        {"directions": [{"name": "追凶流", "titles": ["选中书名", "另一本书"]}]}, runtime
    )
    assert result.update["direction"]["title"] == "选中书名"
    async with runtime.context.sessionmaker() as session:
        rows = list(await session.scalars(select(AuthorRequirement)))
    assert ("书名用《选中书名》", "answer") in {(row.text, row.source) for row in rows}


async def test_directions_first_round_empty_and_latest_round_reaches_editorial(runtime, monkeypatch):
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda state, deps: state))
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    draft = AsyncMock(
        return_value=SimpleNamespace(reference="新理解", directions=[], recommended=0, remark="请看看理解是否准确。")
    )
    monkeypatch.setattr(book_setup.editorial, "draft_directions", draft)
    state = {"idea": "对标作品"}
    first = await book_setup.directions_node(state, runtime)
    assert first["reference"] == "新理解"
    assert draft.await_args.kwargs["previous"] == ""
    previous = {"reference": "上轮理解", "directions": [{"name": "上轮方向"}], "feedback": "保留经营"}
    await book_setup.directions_node({**state, "previous_directions": previous}, runtime)
    assert draft.await_args.kwargs["previous"] == format_previous_directions(previous)


@pytest.mark.parametrize("selected", ["作者选名", None])
async def test_concept_enforces_title_without_losing_model_alternatives(runtime, monkeypatch, selected):
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda state, deps: state))
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    result = demo._concept("").model_copy(
        update={"title": "模型起的书名", "alt_titles": ["另一个备选", "作者选名", "模型起的书名"]}
    )
    monkeypatch.setattr(book_setup.editorial, "draft_concept", AsyncMock(return_value=result))
    state = {
        "idea": "追凶故事",
        "mode": "puzzle",
        "queue": ["concept"],
        "direction": {"name": "追凶流", "title": selected},
        "settings": {"chapter_words": 2000},
    }
    update = await book_setup.concept_node(state, runtime)
    assert update["concept"]["title"] == (selected or "模型起的书名")
    assert update["concept"]["chapter_words"] == 2000
    if selected:
        assert update["concept"]["alt_titles"] == ["模型起的书名", "另一个备选"]
    else:
        assert update["concept"]["alt_titles"] == result.alt_titles


async def test_oneshot_interview_uses_book_chapter_words(runtime, monkeypatch):
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda state, deps: state))
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    monkeypatch.setattr(
        book_setup.editorial, "interview", AsyncMock(return_value=SimpleNamespace(questions=[], remark="请选择篇幅。"))
    )
    for words in (None, 2000):
        update = await book_setup.interview_node({"idea": "点子", "settings": {"chapter_words": words}}, runtime)
        assert update["questions"][0] == length_question(words)


@pytest.mark.parametrize("replacement", [None, "书名用《后来定的新书名》"])
async def test_revoked_title_answer_and_redo_feedback_do_not_return_from_checkpoint(runtime, monkeypatch, replacement):
    original_title = "书名用《原先选中的书名》"
    feedback = "已经撤销的重出意见"
    async with runtime.context.sessionmaker() as session:
        for text in (original_title, feedback):
            row = await add_requirement(session, runtime.context.book_id, text, "answer")
            await suppress_legacy_text(session, runtime.context.book_id, text)
            await session.delete(row)
        if replacement:
            await add_requirement(session, runtime.context.book_id, replacement, "answer")
        await session.commit()
    state = {
        "requirements_ledger_ready": True,
        "idea": "一个追凶故事",
        "mode": "puzzle",
        "queue": ["concept"],
        "direction": {"name": "追凶流", "title": "原先选中的书名"},
        "previous_directions": {"reference": "上轮理解", "directions": [{"name": "上轮方向"}], "feedback": feedback},
    }
    current = await book_setup.live_state(state, runtime.context)
    assert "title" not in current["direction"]
    assert current["previous_directions"] == {**state["previous_directions"], "feedback": ""}
    assert state["direction"]["title"] == "原先选中的书名" and state["previous_directions"]["feedback"] == feedback
    assert current["live_requirements"] == ([replacement] if replacement else [])
    result = demo._concept("").model_copy(update={"title": "按当前要求生成的新书名"})
    draft = AsyncMock(return_value=result)
    monkeypatch.setattr(book_setup.editorial, "draft_concept", draft)
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    update = await book_setup.concept_node(state, runtime)
    assert update["concept"]["title"] == "按当前要求生成的新书名"
    assert "作者选定的书名" not in draft.await_args.kwargs["chosen_direction"]


@pytest.mark.parametrize("saved_title", [None, "原选书名", "作者手改的新书名"])
async def test_title_guard_prefers_saved_author_title_but_preserves_initial_choice(runtime, monkeypatch, saved_title):
    async with runtime.context.sessionmaker() as session:
        book = await session.get(Book, runtime.context.book_id)
        book.title = saved_title or "未命名新书"
        book.concept = {"title": saved_title} if saved_title else {}
        await add_requirement(session, book.id, "书名用《原选书名》", "answer")
        await session.commit()
    state = {
        "requirements_ledger_ready": True,
        "idea": "一个追凶故事",
        "mode": "puzzle",
        "queue": ["concept"],
        "direction": {"name": "追凶流", "title": "原选书名"},
        "concept": {"title": "原选书名"} if saved_title else {},
        "instructions": {"concept": "调整简介，不改书名"} if saved_title else {},
    }
    draft = AsyncMock(return_value=demo._concept("").model_copy(update={"title": "模型擅自改名"}))
    monkeypatch.setattr(book_setup.editorial, "draft_concept", draft)
    monkeypatch.setattr(book_setup, "mark_progress", AsyncMock())
    update = await book_setup.concept_node(state, runtime)
    expected = saved_title or "原选书名"
    assert update["concept"]["title"] == expected
    assert "模型擅自改名" in update["concept"]["alt_titles"]
    assert f"作者选定的书名：《{expected}》" in draft.await_args.kwargs["chosen_direction"]
    if saved_title:
        assert draft.await_args.args[4]["title"] == saved_title
    # 修复只改变本次上下文，不擅自编辑或删除作者保存的要求。
    async with runtime.context.sessionmaker() as session:
        rows = list(await session.scalars(select(AuthorRequirement)))
    assert [row.text for row in rows] == ["书名用《原选书名》"]
