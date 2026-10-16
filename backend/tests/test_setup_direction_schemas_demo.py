"""任务 6：设计方 schema 原文、模板搬运与演示方向的回归。"""

import re
from pathlib import Path

import pytest

from app import prompts
from app.agents import schemas as s
from app.agents.context import format_concept, format_direction_choice, format_previous_directions, format_revision
from app.llm import demo
from app.prompts.catalog import VARIABLE_LABELS, variables

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def default_prompts(monkeypatch):
    monkeypatch.setattr(prompts, "_load", prompts.default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)


def test_task6_schema_descriptions_match_design_verbatim():
    task = ROOT / "docs/codex任务/第一包/6-开书方向质量调优.md"
    block = re.search(r"```python\n(.*?)\n```", task.read_text(encoding="utf-8"), re.S).group(1)
    namespace = {}
    exec(compile(block, str(task), "exec"), namespace)
    assert namespace["STAGE_LADDER_DESC"] == s.STAGE_LADDER_DESC
    for model in (s.BookDirection, s.BookConcept):
        assert model.model_fields["stage_ladder"].description == namespace["STAGE_LADDER_DESC"]
    for model, name in (
        (s.BookDirection, "name"),
        (s.BookDirection, "golden_finger"),
        (s.BookDirections, "directions"),
    ):
        expected = re.search(rf'#     {name} 描述改为 "([^"]+)"', block).group(1)
        assert model.model_fields[name].description == expected
    for model, name in ((s.BookDirection, "titles"), (s.BookDirections, "reference")):
        expected = re.search(rf'#     {name}: [^\n]*description="([^"]+)"', block).group(1)
        assert model.model_fields[name].description == expected
    focus = re.search(r'#     remark 改为 remark_field\("([^"]+)"\)', block).group(1)
    assert s.BookDirections.model_fields["remark"].description == s.remark_field(focus).description
    assert list(s.BookDirections.model_json_schema()["properties"])[:2] == ["reference", "directions"]
    assert list(s.BookDirection.model_json_schema()["properties"])[:2] == ["name", "titles"]


def test_direction_new_fields_accept_old_outputs_without_shared_defaults():
    old = demo._book_directions("").model_dump(exclude={"reference"})
    for direction in old["directions"]:
        direction.pop("titles")
    first, second = s.BookDirections.model_validate(old), s.BookDirections.model_validate(old)
    assert first.reference == ""
    assert all(direction.titles == [] for direction in first.directions)
    first.directions[0].titles.append("只改这一份")
    assert second.directions[0].titles == []


def test_task6_templates_are_moved_without_byte_changes_and_previous_is_registered():
    # 第二包已再次替换方向和概念，并退役设定；第一包的原文证据保持不动。
    # 第二包原文哈希在 test_setup_puzzle_prompts 中覆盖。
    assert not (ROOT / "backend/app/prompts/setup_lore.md").exists()
    assert VARIABLE_LABELS["previous"] == "上一轮的方向"
    assert {item["name"]: item["label"] for item in variables("setup_directions")}["previous"] == "上一轮的方向"


def direction_prompt(idea: str, previous: str = "", style: str = "") -> str:
    return prompts.render("setup_directions", idea=idea, previous=previous, style=style, requirements="", glossary="")


@pytest.mark.parametrize("idea", ["借用某部作品的设定", "像某部作品那样", "对标某部作品", "《某某》的设定"])
async def test_demo_reference_triggers_and_two_distinct_title_candidates(idea):
    result = await demo.respond(s.BookDirections, "", direction_prompt(idea))
    assert result.reference and "不确定" in result.reference
    assert len(result.directions) == 3
    for direction in result.directions:
        assert len(direction.titles) == len(set(direction.titles)) == 2
        assert not any("《" in title or "》" in title for title in direction.titles)
        assert 4 <= len(direction.name) <= 8
        assert direction.protagonist.split("，")[0] in direction.logline
    assert demo._book_directions(direction_prompt("一个少年靠判断改变命运")).reference == ""


def test_demo_redos_change_story_and_opening_but_preserve_borrowed_core():
    idea = "借用《我有一座恐怖屋》的设定，写一个不同剧情的小说"
    first = demo._book_directions(direction_prompt(idea))
    # 模板本身的第 8 条会提到 marker，不应把首轮误当成重出。
    assert first.directions[0].name == "旧案追凶流"
    previous_result = first
    for feedback in ("保留恐怖屋经营，换主线谜团", "换一个开局，不改金手指"):
        previous = format_previous_directions({**previous_result.model_dump(), "feedback": feedback})
        result = demo._book_directions(direction_prompt(idea, previous))
        assert {d.name for d in result.directions}.isdisjoint(d.name for d in previous_result.directions)
        assert {d.opening for d in result.directions}.isdisjoint(d.opening for d in previous_result.directions)
        assert {d.golden_finger for d in result.directions} == {d.golden_finger for d in first.directions}
        assert {d.protagonist for d in result.directions} == {d.protagonist for d in first.directions}
        assert {d.stage_ladder for d in result.directions} == {"老城区 → 整座城市 → 省城 → 全国"}
        assert all(d.protagonist.split("，")[0] in d.logline for d in result.directions)
        assert "换了主线冲突和开局" in result.remark
        previous_result = result


def test_demo_concept_preserves_chosen_direction_and_title():
    idea = "借用《我有一座恐怖屋》的设定，写一个不同剧情的小说"
    direction = demo._book_directions(direction_prompt(idea)).directions[1].model_dump()
    direction["title"] = direction["titles"][1]
    user = prompts.render(
        "setup_concept",
        idea=idea,
        chosen_direction=format_direction_choice(direction),
        requirements="",
        style="",
        revision="",
    )
    result = demo._concept(user)
    assert result.title == direction["title"]
    assert result.alt_titles == [direction["titles"][0]]
    assert result.logline == direction["logline"]
    assert result.core_loop == direction["core_loop"]
    assert result.stage_ladder == direction["stage_ladder"]
    assert result.genre == "悬疑·灵异"


def test_demo_title_candidates_follow_long_title_setting():
    result = demo._book_directions(
        direction_prompt("一个落魄少年得到传承", style="【这本书的写作规矩】\n- 书名：番茄式长书名")
    )
    assert all(len(title) > 10 for direction in result.directions for title in direction.titles)


@pytest.fixture
def concept_revision_prompt():
    idea = "跨块审稿演示：少年持青灯查看寿元，追查自己的身世。"
    direction = demo._book_directions(direction_prompt(idea)).directions[0].model_dump()
    direction["title"] = direction["titles"][1]

    def render(*, current=None, instructions="", requirements=""):
        return prompts.render(
            "setup_concept",
            idea=idea,
            chosen_direction=format_direction_choice(direction),
            requirements=requirements,
            style="",
            revision=format_revision("当前概念", format_concept(current.model_dump()), instructions) if current else "",
        )

    return render, direction


@pytest.mark.parametrize("change", ["cost", "feeling", "both"])
def test_demo_revision_overrides_initial_direction_without_losing_selected_title(concept_revision_prompt, change):
    render, direction = concept_revision_prompt
    initial = demo._concept(render())
    cost = "调查寿元异常，追查父母旧案，每次搜证都要救回一个受害者"
    instructions = []
    if change in ("cost", "both"):
        instructions.append("核心循环补充：" + cost)
    if change in ("feeling", "both"):
        instructions.append("把「感情线」改成「从欢喜冤家开始」")
    revised = demo._concept(render(current=initial, instructions="\n".join(instructions)))
    assert revised.title == initial.title == direction["title"]
    assert revised.stage_ladder == initial.stage_ladder == direction["stage_ladder"]
    if change in ("cost", "both"):
        assert revised.core_loop == cost
    else:
        assert revised.core_loop == initial.core_loop
    if change in ("feeling", "both"):
        assert "宗门内斗与正邪两道的灰色地带；感情线：从欢喜冤家开始" in revised.selling_points
        assert revised.decisions[0].chosen == "从欢喜冤家开始"
        assert revised.selling_points[: len(initial.selling_points)] == initial.selling_points
    else:
        assert revised.selling_points == initial.selling_points
    # 下一次改别的内容，也不能把已采用的修订恢复成最初的方向。
    later = demo._concept(render(current=revised, instructions="开局节奏稍慢一些"))
    assert later.core_loop == revised.core_loop
    assert later.selling_points == revised.selling_points
    assert later.decisions[0].chosen == revised.decisions[0].chosen


def test_demo_historical_requirements_do_not_reapply_old_concept_edits(concept_revision_prompt):
    render, direction = concept_revision_prompt
    history = (
        "【作者的要求（以后面的为准）】\n"
        "- 历史意见：核心循环补充：调查寿元异常，追查父母旧案，每次搜证都要救回一个受害者\n"
        "- 历史意见：把「感情线」改成「从欢喜冤家开始」\n\n"
    )
    initial = demo._concept(render(requirements=history))
    assert initial.core_loop == direction["core_loop"]
    assert initial.selling_points == direction["selling_points"]
    assert initial.decisions[0].chosen == "并肩查案慢慢靠近"
    revised = demo._concept(
        render(current=initial, instructions="保留当前核心循环，开局节奏稍慢一些", requirements=history)
    )
    assert revised.core_loop == initial.core_loop
    assert revised.selling_points == initial.selling_points
    assert revised.decisions[0].chosen == initial.decisions[0].chosen
