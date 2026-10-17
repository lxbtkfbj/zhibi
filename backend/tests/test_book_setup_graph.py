"""第三包三步图的程序规则、重开与局部修改边界。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import schemas
from app.agents.setup_puzzle import ORDER, PIECE_ORDER, PIECES, piece_checks
from app.graphs import book_setup
from app.llm import demo_setup


def test_new_graph_has_only_three_steps_and_no_retired_nodes():
    assert ORDER == ["concept", "settings_focus", "settings_rest", "outline", "outline_chapters"]
    assert PIECE_ORDER == ["concept", "settings", "outline"]
    assert PIECES["settings"] == ["settings_focus", "settings_rest"]
    graph = book_setup.build_setup_graph()
    assert set(graph.nodes) == {
        "pitches",
        "pitches_gate",
        "intake",
        *ORDER,
        "piece_check",
        "piece_persist",
        "piece_gate",
        "finalize",
    }
    state = book_setup.initial_state("点子", ask=True, mode="oneshot")
    assert state["flow"] == 3 and "ask" not in state
    assert book_setup.route_start(state) == "pitches"
    assert len(book_setup.length_question()["options"]) == 5
    assert "400 万字" in book_setup.length_question()["options"][3]


def test_restart_remembers_only_old_chosen_direction_as_exact_previous():
    state = book_setup.restart_state(
        {"idea": "保留点子", "mode": "puzzle", "keep_concept": True},
        {"direction": {"name": "逆袭", "logline": "少年重生"}, "world": {"stale": True}},
        {"title": "旧书名"},
    )
    assert (
        state["previous"]
        == "【之前按旧流程选过的方向】\n逆袭：少年重生\n（作者之前选过它，三个短版里请保留它的好东西。）"
    )
    assert state["queue"] == ["concept"] and "world" not in state and "concept" not in state
    assert state["pieces"] == dict.fromkeys(PIECE_ORDER, "todo")


def test_program_checks_exact_wording_and_no_far_future_requirements():
    assert piece_checks("concept", {"concept": {"story": "短", "secret": "没有"}}) == [
        {"question": "story", "text": "定调要写成一段话，200-400 字，现在是 1 字。"}
    ]
    assert piece_checks("concept", {"concept": demo_setup.concept("").model_dump()}) == []
    focus, rest = demo_setup.focus("").model_dump(), demo_setup.rest("").model_dump()
    assert piece_checks("settings", {"settings_focus": focus, "settings_rest": rest}) == []
    invalid = deepcopy(rest)
    invalid["entries"] = [{"name": "境界", "category": "等级体系", "status": "现在要定", "content": "", "levels": []}]
    invalid["characters"] = []
    assert [item["text"] for item in piece_checks("settings", {"settings_rest": invalid})] == [
        "世界与地图的第一条要叫「世界概况」。",
        "「境界」是现在要定的，还没写一段话。",
        "「境界」还没写各级；没有正式等级就写一级「没有」。",
        "还没写第一卷登场的人物。",
    ]
    outline = demo_setup.outline("").model_dump()
    assert piece_checks("outline", {"outline": outline, "outline_chapters": {"chapters": [{"title": "开局"}]}}) == []
    outline["arcs"][1]["planned"] = True
    assert [item["text"] for item in piece_checks("outline", {"outline": outline})] == [
        "只有第一篇写细，后面的篇写到再定。",
        "第一个单元的章纲还没出来。",
    ]


@pytest.mark.parametrize(
    "piece,target", [("concept", "concept"), ("settings", "settings_rest"), ("outline", "outline_chapters")]
)
async def test_program_checks_retry_once_then_warn(monkeypatch, piece, target):
    async def live(state, deps, **kwargs):
        return state

    monkeypatch.setattr(book_setup, "live_state", live)
    state = {"piece": piece}
    rt = SimpleNamespace(context=SimpleNamespace())
    first = await book_setup.piece_check_node(state, rt)
    assert first.goto == "intake" and first.update["queue"] == [target]
    assert first.update["revised"][target]
    second = await book_setup.piece_check_node({**state, **first.update}, rt)
    assert second.goto == "piece_persist" and second.update["warnings"]


async def test_blank_secret_warns_without_rewrite(monkeypatch):
    async def live(state, deps, **kwargs):
        return state

    monkeypatch.setattr(book_setup, "live_state", live)
    concept = {**demo_setup.concept("").model_dump(), "secret": ""}
    result = await book_setup.piece_check_node({"piece": "concept", "concept": concept}, SimpleNamespace(context=None))
    assert result.goto == "piece_persist"
    assert result.update["warnings"] == ["底牌还没写；这本书没有大秘密就写「没有」。"]


async def test_outline_chapters_calls_writing_function_not_a_copy(monkeypatch):
    from contextlib import asynccontextmanager

    from app.graphs import write_book

    @asynccontextmanager
    async def sessionmaker():
        yield object()

    saved = {"outline": {"units": [{"id": "unit-id"}]}, "outline_chapters": {"chapters": [{"title": "首章"}]}}

    async def live(state, deps, **kwargs):
        return {**state, **saved}

    monkeypatch.setattr(book_setup, "live_state", live)
    monkeypatch.setattr(book_setup.setup_store, "load_new_setup", AsyncMock(return_value=saved))
    plan = AsyncMock()
    monkeypatch.setattr(write_book, "plan_chapters_node", plan)
    rt = SimpleNamespace(context=SimpleNamespace(sessionmaker=sessionmaker, book_id="book"))
    result = await book_setup.outline_chapters_node({"queue": ["outline_chapters"]}, rt)
    plan.assert_awaited_once_with({"unit_id": "unit-id"}, rt)
    assert result["outline_chapters"]["chapters"][0]["title"] == "首章"
    assert result["queue"] == []


def test_new_note_plan_does_not_offer_unlocks_or_old_targets():
    plan = schemas.SetupNotePlan(settings_instructions="只改境界", remark="已安排")
    assert plan.instructions() == {"settings": "只改境界"}
    assert "unlock_requests" not in schemas.SetupNotePlan.model_fields


@pytest.mark.parametrize("message,raises", [("主编没有给出章纲", False), ("模型连接失败", True)])
async def test_empty_chapter_plan_goes_to_retry_but_network_errors_raise(monkeypatch, message, raises):
    from contextlib import asynccontextmanager

    from app.graphs import write_book
    from app.llm.router import LLMError

    @asynccontextmanager
    async def sessionmaker():
        yield object()

    saved = {"outline": {"units": [{"id": "unit-id"}]}, "outline_chapters": {"chapters": []}}

    async def live(state, deps, **kwargs):
        return {**state, **saved}

    monkeypatch.setattr(book_setup, "live_state", live)
    monkeypatch.setattr(book_setup.setup_store, "load_new_setup", AsyncMock(return_value=saved))
    monkeypatch.setattr(write_book, "plan_chapters_node", AsyncMock(side_effect=LLMError(message)))
    rt = SimpleNamespace(context=SimpleNamespace(sessionmaker=sessionmaker, book_id="book"))
    if raises:
        with pytest.raises(LLMError, match=message):
            await book_setup.outline_chapters_node({"queue": ["outline_chapters"]}, rt)
    else:
        result = await book_setup.outline_chapters_node({"queue": ["outline_chapters"]}, rt)
        first = await book_setup.piece_check_node({**result, "piece": "outline"}, rt)
        assert first.goto == "intake" and first.update["queue"] == ["outline_chapters"]
        second = await book_setup.piece_check_node({**result, **first.update, "piece": "outline"}, rt)
        assert second.goto == "piece_persist" and "第一个单元的章纲还没出来。" in second.update["warnings"]


async def test_original_outline_warning_survives_storage_normalization(monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def sessionmaker():
        yield SimpleNamespace(commit=AsyncMock())

    draft = demo_setup.outline("")
    draft.arcs[1].planned = True
    normalized = demo_setup.outline("").model_dump()
    saved = {"outline": normalized, "outline_chapters": {"chapters": [{"title": "首章"}]}}

    async def live(state, deps, **kwargs):
        return state

    monkeypatch.setattr(book_setup, "live_state", live)
    monkeypatch.setattr(
        book_setup,
        "_library_blocks",
        AsyncMock(return_value={"concept": "", "library": "", "focus": "", "requirements": "", "genre_defaults": ""}),
    )
    monkeypatch.setattr(book_setup.setup_store, "save_outline", AsyncMock())
    monkeypatch.setattr(book_setup.setup_store, "load_new_setup", AsyncMock(return_value=saved))
    call = AsyncMock(return_value=draft)
    monkeypatch.setattr(book_setup.editorial, "draft_setup_outline", call)
    rt = SimpleNamespace(
        context=SimpleNamespace(
            sessionmaker=sessionmaker,
            book_id="book",
            check_cancel=AsyncMock(),
            llm=object(),
            emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock()),
        )
    )
    update = await book_setup.outline_node({"queue": ["outline", "outline_chapters"]}, rt)
    assert call.await_count == 2 and update["outline_checks"]
    checked = await book_setup.piece_check_node({**update, "piece": "outline"}, rt)
    assert checked.goto == "piece_persist"
    assert "只有第一篇写细，后面的篇写到再定。" in checked.update["warnings"]
