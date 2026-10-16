"""第二包任务 2：新五步的原文契约、整理检查和单块审稿边界。"""

import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents import schemas
from app.agents.setup_puzzle import (
    ORDER,
    PIECE_ORDER,
    QUESTIONS,
    normalize_segment,
    normalize_volumes,
    normalize_world,
    piece_checks,
)
from app.graphs import book_setup
from app.llm import demo

TASK = Path(__file__).resolve().parents[2] / "docs/codex任务/第二包/2-开书新五步.md"


def test_schema_descriptions_and_order_match_task_source_verbatim():
    text = TASK.read_text(encoding="utf-8")
    block = re.search(r"```python\n(.*?)\n```", text, re.S).group(1)
    namespace = dict(vars(schemas))
    exec(compile(block, str(TASK), "exec"), namespace)
    for name in (
        "BookConcept",
        "CaredPerson",
        "ProtagonistDraft",
        "MapDraft",
        "FarMap",
        "WorldDraft",
        "OpeningPlan",
        "SegmentDraft",
        "SegmentVolumesDraft",
        "ReviewIssue",
        "UnlockRequest",
    ):
        expected, actual = namespace[name], getattr(schemas, name)
        assert list(actual.model_fields) == list(expected.model_fields), name
        for key, field in expected.model_fields.items():
            assert actual.model_fields[key].description == field.description, f"{name}.{key}"
    fields = namespace["RevisionTriage"].model_fields
    assert list(schemas.RevisionTriage.model_fields)[: len(fields)] == list(fields)
    for key, field in fields.items():
        assert schemas.RevisionTriage.model_fields[key].description == field.description
    assert tuple(ORDER) == schemas.SETUP_PARTS
    for name in ("StorySpine", "LoreDraft", "OutlineDraft", "ThreadsDraft"):
        assert not hasattr(schemas, name)
    assert "protagonist_hook" not in schemas.BookConcept.model_fields
    assert (
        schemas.BookConcept.model_validate({**demo._concept("").model_dump(), "target_length": "200万"}).target_length
        == 200
    )


def test_questions_and_review_focus_match_task_verbatim():
    text = TASK.read_text(encoding="utf-8")
    expected = {}
    for line in text.split("## 2. 必答题表")[1].split("## 3.")[0].splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) > 3 and parts[1] in PIECE_ORDER:
            expected.setdefault(parts[1], []).append((parts[2], parts[3]))
    assert expected == QUESTIONS
    focus = re.findall(r"  ```\n(  【这次审什么】.*?)  ```", text, re.S)
    for piece, block in zip(("protagonist", "segment", "first_volume"), focus, strict=True):
        assert book_setup.REVIEW_FOCUS[piece] == "\n".join(line[2:] for line in block.rstrip().splitlines())


def test_world_reconciles_protagonist_and_cared_people_without_mutation():
    card = {
        "name": "阿甲",
        "personality": "谨慎",
        "start": "底层",
        "finger": "读记忆",
        "pursuit": "寻亲",
        "trigger": "家人失踪",
        "cared": [{"name": "阿乙", "relation": "妹妹", "why": "相依为命"}],
    }
    raw = {
        "first_map": {"name": "小城"},
        "characters": [{"name": "错名", "role_type": "主角"}, {"name": "对手", "role_type": "反派"}],
        "relationships": [{"source": "错名", "target": "对手"}, {"source": "错名", "target": "不存在"}],
        "mystery_answer": "作者已定谜底",
    }
    before = deepcopy(raw)
    result, notes = normalize_world(raw, card)
    assert raw == before
    assert result["characters"][0]["name"] == "阿甲"
    assert result["relationships"] == [{"source": "阿甲", "target": "对手"}]
    assert result["maps"] == [{"name": "小城"}] and "first_map" not in result
    assert result["mystery_answer"] == "作者已定谜底"
    assert notes == [
        {"question": "people", "text": "人物表里的主角已改回主角卡上的名字「阿甲」。"},
        {"question": "people", "text": "已按主角卡补上在乎的人：阿乙。"},
    ]
    empty, notes = normalize_world({"characters": []}, card)
    hero = empty["characters"][0]
    assert [hero[key] for key in ("name", "role_type", "personality", "background", "abilities", "goal", "want")] == [
        "阿甲",
        "主角",
        "谨慎",
        "底层",
        "读记忆",
        "寻亲",
        "家人失踪",
    ]
    assert notes[0]["text"] == "人物表里没有主角，已按主角卡补上「阿甲」。"


def test_segment_near_plan_and_global_ledger_numbers():
    raw = demo._segment("").model_dump()
    world, _ = normalize_world(demo._world("").model_dump(), demo._protagonist("").model_dump())
    raw["secrets"][0]["knowers"].append("不存在")
    previous = {"expectations": [{"seq": 3, "kind": "期待", "description": raw["wait"]["description"]}]}
    segment, notes = normalize_segment(raw, [], world["characters"], previous, world=world)
    assert [node["kind"] for node in segment["nodes"]] == ["opening", "milestone", "ending"]
    assert [node["segment"] is not None for node in segment["nodes"]] == [False, True, False]
    info = segment["nodes"][1]["segment"]
    assert info["number"] == 1 and info["planned_at"] == 0 and not info["finale"]
    assert info["map"] == world["maps"][0]["name"]
    assert info["opening"] == raw["opening"] and info["goal"] == raw["goal"]
    assert segment["expectations"][0]["seq"] == 3
    assert notes == [{"question": "reveal", "text": "已丢弃 1 个不在人物表里的知情人。"}]
    raw["wait"]["description"] = "新的期待"
    segment, _ = normalize_segment(
        raw,
        [],
        world["characters"],
        previous,
        existing_ledger=[*previous["expectations"], {"kind": "期待", "seq": 7, "description": "卷内期待"}],
    )
    assert segment["expectations"][0]["seq"] == 8
    raw["nodes"].pop(1)
    segment, notes = normalize_segment(raw, [], [], {})
    assert all(node["segment"] is None for node in segment["nodes"])
    assert {"question": "end", "text": "开篇后面还没有这一段的终点。"} in notes


def test_split_limits_beats_and_anchors_to_current_segment():
    part = {
        "volumes": [
            {"index": 9, "target_node": 99, "chapter_count": -2},
            {"index": 3, "target_node": 4, "chapter_count": "12"},
        ],
        "threads": [
            {
                "name": "  主线 ",
                "beats": [{"volume": 99, "beat": "远处"}, {"volume": 4, "beat": "后"}, {"volume": 3, "beat": "前"}],
            },
            {"name": "主线", "beats": []},
        ],
        "anchors": [
            {"character": "甲", "node": 4, "kind": "登场"},
            {"character": "不存在", "node": 4},
            {"character": "甲", "node": 99},
        ],
    }
    segment = {
        "nodes": [{"title": str(i), "status": "pencil"} for i in range(1, 6)],
        "expectations": [{"node": 4, "plant_volume": 1, "payoff_volume": 9}],
    }
    result, changed, notes = normalize_volumes(part, segment, [{"name": "甲"}], 3, end_index=4)
    assert [v["index"] for v in result["volumes"]] == [3, 4]
    assert [v["chapter_count"] for v in result["volumes"]] == [12, 0]
    assert [v["reaches_node"] for v in result["volumes"]] == [False, True]
    assert all(v["target_node"] == 4 for v in result["volumes"])
    assert changed["nodes"][3]["volume"] == 4
    assert changed["expectations"] == [{"node": 4, "plant_volume": 3, "payoff_volume": 4}]
    assert len(result["threads"]) == 1 and [b["volume"] for b in result["threads"][0]["beats"]] == [3, 4]
    assert result["volumes"][0]["thread_beats"] == [{"thread": "主线", "beat": "前"}]
    assert len(result["anchors"]) == 1
    assert {"question": "cast", "text": "已丢弃 2 条不合法的人物锚点。"} in notes
    assert "volume" not in segment["nodes"][3]


@pytest.mark.parametrize("piece", PIECE_ORDER)
def test_checks_are_grouped_by_known_questions_and_empty_input_is_actionable(piece):
    checks = piece_checks(piece, {})
    assert checks
    assert all(item["question"] in dict(QUESTIONS[piece]) for item in checks)
    assert all(item["text"].endswith("。") for item in checks)


@pytest.mark.parametrize(
    "piece,audit,review_count",
    [
        ("concept", True, 0),
        ("protagonist", True, 1),
        ("world", True, 0),
        ("segment", True, 1),
        ("protagonist", False, 0),
        ("segment", False, 0),
        ("first_volume", False, 1),
    ],
)
async def test_piece_review_once_keeps_low_and_locked_suggestions(monkeypatch, piece, audit, review_count):
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda state, _: state))
    issue_target = "segment" if piece == "segment" else piece
    reviewer = AsyncMock(
        return_value=schemas.SetupCritique(
            verdict="revise",
            remark="审稿",
            issues=[
                schemas.ReviewIssue(
                    target=issue_target,
                    question=QUESTIONS[piece][0][0],
                    problem="本块问题",
                    suggestion="补足",
                    severity="medium",
                ),
                schemas.ReviewIssue(
                    target=issue_target,
                    question=QUESTIONS[piece][0][0],
                    problem="本块建议",
                    suggestion="作者微调",
                    severity="low",
                ),
                schemas.ReviewIssue(target="concept", problem="锁定建议", suggestion="解锁后修改", severity="medium"),
            ],
        )
    )
    monkeypatch.setattr(book_setup.editorial, "critique_setup", reviewer)
    deps = SimpleNamespace(
        llm=object(),
        check_cancel=AsyncMock(),
        emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
    )
    runtime = SimpleNamespace(context=deps)
    state = {
        **book_setup.initial_state("测试", mode="puzzle"),
        "piece": piece,
        "pieces": {"concept": "confirmed"},
        "settings": {"volume_audit": audit},
        "queue": [],
        "check_notes": [{"question": QUESTIONS[piece][0][0], "text": "程序整理说明。"}],
    }
    command = await book_setup.piece_check_node(state, runtime)
    assert reviewer.await_count == review_count
    assert command.update["warnings"][0] == "程序整理说明。"
    if review_count:
        assert command.goto == "intake" and command.update["piece_revised"][piece]
        assert command.update["review_notes"] == [
            {"question": QUESTIONS[piece][0][0], "problem": "本块建议", "suggestion": "作者微调"}
        ]
        assert "审稿：本块建议——作者微调" in command.update["flags"][QUESTIONS[piece][0][0]]
        assert command.update["suggestions"][0]["target"] == "concept"
        repeated = await book_setup.piece_check_node({**state, **command.update}, runtime)
        assert repeated.goto == "piece_persist" and reviewer.await_count == 1
        assert "审稿：本块建议——作者微调" in repeated.update["flags"][QUESTIONS[piece][0][0]]
    else:
        assert command.goto == "piece_persist"


def test_route_restart_skips_direction_and_new_mode_has_six_steps():
    assert book_setup.initial_state("点子")["flow"] == 2
    assert book_setup.initial_state("点子")["queue"] == ORDER
    assert book_setup.initial_state("点子", mode="puzzle")["queue"] == ["concept"]
    assert book_setup.route_start({"mode": "puzzle"}) == "directions"
    assert book_setup.route_start({"mode": "puzzle", "direction": {"name": "原方向"}}) == "intake"
    assert book_setup.route_start({"mode": "puzzle", "concept": {"title": "原定调"}}) == "intake"


async def test_oneshot_review_includes_five_piece_checks_and_retains_normalizer_notes(monkeypatch):
    monkeypatch.setattr(book_setup, "live_state", AsyncMock(side_effect=lambda state, _: state))
    reviewer = AsyncMock(return_value=schemas.SetupCritique(verdict="pass", remark="交给作者", issues=[]))
    monkeypatch.setattr(book_setup.editorial, "critique_setup", reviewer)
    deps = SimpleNamespace(
        llm=object(),
        check_cancel=AsyncMock(),
        emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
    )
    state = book_setup.initial_state("点子")
    first_notes = [{"question": "people", "text": "已按主角卡补上在乎的人：阿乙。"}]
    state.update(book_setup.normalization_update(state, "world", first_notes))
    state.update(
        book_setup.normalization_update(state, "segment", [{"question": "end", "text": "开篇后面还没有这一段的终点。"}])
    )
    state.update(book_setup.normalization_update(state, "volumes", []))
    update = await book_setup.critique_node(state, SimpleNamespace(context=deps))
    assert reviewer.await_count == 1
    requirements = reviewer.call_args.args[2]
    assert "【程序提醒】" in requirements
    for label in ("定调", "主角", "世界与人", "第一段", "第一卷"):
        assert f"【{label}】" in requirements
    assert "【世界与人】已按主角卡补上在乎的人：阿乙。" in update["warnings"]
    assert state["check_notes_by_step"]["world"] == first_notes
    assert reviewer.call_args.kwargs["focus"] == book_setup.REVIEW_FOCUS["first_volume"]
