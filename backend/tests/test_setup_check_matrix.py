"""第二包任务 2 第 3.6 节：逐条核对程序检查的题目键和原文提醒。"""

from copy import deepcopy

import pytest

from app.agents.setup_puzzle import PIECE_ORDER, piece_checks
from tests.test_setup_puzzle_rules import valid_setup


@pytest.fixture
def setup():
    """每例从全部正常的五块出发，只改变该例需要触发的条件。"""
    value = valid_setup()
    for piece in PIECE_ORDER:
        assert piece_checks(piece, value) == []
    return value


def assert_check(setup, piece, question, text):
    assert {"question": question, "text": text} in piece_checks(piece, setup)


@pytest.mark.parametrize(
    ("field", "question", "text"),
    [
        ("target_reader", "positioning", "还没写写给谁看：男频还是女频、读者爱看什么、最讨厌什么。"),
        ("logline", "logline", "还没写一句话故事。"),
        ("core_loop", "core_loop", "还没写核心循环：主角每个单元反复做什么。"),
    ],
)
def test_concept_missing_required_answer(setup, field, question, text):
    setup["concept"][field] = ""
    assert_check(setup, "concept", question, text)


def test_concept_logline_over_sixty_characters(setup):
    setup["concept"]["logline"] = "故" * 61
    assert_check(setup, "concept", "logline", "一句话故事有 61 个字，超过 50 字太多了。")


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (0, "核心卖点现在有 0 个，建议 2-3 个，具体到场面。"),
        (1, "核心卖点现在有 1 个，建议 2-3 个，具体到场面。"),
        (4, "核心卖点现在有 4 个，建议 2-3 个，具体到场面。"),
    ],
)
def test_concept_selling_point_count_outside_two_to_three(setup, count, text):
    setup["concept"]["selling_points"] = [f"场面 {index}" for index in range(count)]
    assert_check(setup, "concept", "selling_points", text)


@pytest.mark.parametrize("count", [2, 3])
def test_concept_accepts_sixty_characters_and_two_or_three_selling_points(setup, count):
    setup["concept"]["logline"] = "故" * 60
    setup["concept"]["selling_points"] = [f"场面 {index}" for index in range(count)]
    assert piece_checks("concept", setup) == []


@pytest.mark.parametrize(
    ("field", "question", "text"),
    [
        ("start", "start", "还没写「起点」。"),
        ("trigger", "drive", "还没写「开局动机」。"),
        ("pursuit", "drive", "还没写「长线追求」。"),
        ("root", "drive", "还没写「情感根源」。"),
        ("personality", "person", "还没写「性格」。"),
        ("bottom_line", "person", "还没写「底线」。"),
        ("voice", "person", "还没写「说话方式」。"),
        ("finger", "finger", "还没写「金手指·现在」。"),
        ("flaw", "flaw_arc", "还没写「软肋」。"),
        ("arc_end", "flaw_arc", "还没写「成长的终点」。"),
        ("interlock", "interlock", "还没写「咬合检查」。"),
    ],
)
def test_protagonist_each_missing_required_answer(setup, field, question, text):
    setup["protagonist"][field] = ""
    assert_check(setup, "protagonist", question, text)


@pytest.mark.parametrize("pursuit", ["变强", "追" * 9])
def test_protagonist_pursuit_under_ten_characters(setup, pursuit):
    setup["protagonist"]["pursuit"] = pursuit
    assert_check(setup, "protagonist", "drive", "长线追求太短，写具体：找谁、向谁复仇、守护什么，不能只是「变强」。")


def test_protagonist_pursuit_exactly_ten_characters_is_not_too_short(setup):
    setup["protagonist"]["pursuit"] = "追" * 10
    assert piece_checks("protagonist", setup) == []


def test_protagonist_missing_cared_people(setup):
    setup["protagonist"]["cared"] = []
    assert_check(setup, "protagonist", "cared", "还没写开局在乎的人。")


@pytest.mark.parametrize(
    ("field", "question", "text"),
    [
        ("surface", "surface", "还没写世界的表里：超凡的力量是公开的还是藏着的。"),
        ("power", "power", "还没写力量规则。"),
        ("trouble", "opponents", "还没写开篇的小麻烦。"),
        ("opponent", "opponents", "还没写这一段的大对手。"),
        ("mystery", "shadows", "还没写核心谜团的谜面。"),
    ],
)
def test_world_missing_required_answer(setup, field, question, text):
    setup["world"][field] = ""
    assert_check(setup, "world", question, text)


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("name", "第一张地图还没写「地图名」。"),
        ("powers", "第一张地图还没写「谁说了算」。"),
        ("ceiling", "第一张地图还没写「天花板」。"),
        ("start", "第一张地图还没写「主角从哪起步」。"),
        ("gains", "第一张地图还没写「能拿到什么」。"),
    ],
)
def test_world_each_missing_first_map_answer(setup, field, text):
    setup["world"]["maps"][0][field] = ""
    assert_check(setup, "world", "first_map", text)


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("trouble", "开篇的小麻烦里没有写是人物表里的谁。"),
        ("opponent", "这一段的大对手里没有写是人物表里的谁。"),
    ],
)
def test_world_opponent_must_name_someone_in_character_table(setup, field, text):
    setup["world"][field] = "一个没有名字的人在阻挠调查。"
    assert_check(setup, "world", "opponents", text)


def test_world_requires_a_villain_in_character_table(setup):
    for character in setup["world"]["characters"]:
        if character["role_type"] == "反派":
            character["role_type"] = "配角"
    assert_check(setup, "world", "opponents", "人物表里还没有反派。")


def add_important_people(setup, count):
    characters = setup["world"]["characters"]
    existing = sum(character.get("role_type") != "龙套" for character in characters)
    assert existing <= count
    characters.extend({"name": f"新伙伴{index}", "role_type": "配角"} for index in range(count - existing))


def test_world_more_than_nine_important_people(setup):
    add_important_people(setup, 10)
    assert_check(setup, "world", "people", "要紧人物有 10 个，第一张地图建议七八个以内，名字多了新读者记不住。")


def test_world_nine_important_people_plus_extras_is_allowed(setup):
    add_important_people(setup, 9)
    setup["world"]["characters"].extend({"name": f"路人{index}", "role_type": "龙套"} for index in range(4))
    assert piece_checks("world", setup) == []


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("scene", "开篇还没写「第一章的切入场面」。"),
        ("pressure", "开篇还没写「前 3 章压着主角的事」。"),
        ("first_win", "开篇还没写「第一个小爽点」。"),
        ("finger", "开篇还没写「金手指露头」。"),
        ("hook", "开篇还没写「第 3 章的钩子」。"),
    ],
)
def test_segment_each_missing_opening_answer(setup, field, text):
    setup["segment"]["nodes"][1]["segment"]["opening"][field] = ""
    assert_check(setup, "segment", "opening", text)


@pytest.mark.parametrize(
    ("field", "question", "text"),
    [
        ("goal", "goal", "还没写这一段的目标。"),
        ("goal_link", "goal", "还没写做成这一段的目标为什么离长线追求更近。"),
        ("reveal", "reveal", "还没写这一段揭开什么。"),
    ],
)
def test_segment_missing_goal_link_or_revelation(setup, field, question, text):
    setup["segment"]["nodes"][1]["segment"][field] = ""
    assert_check(setup, "segment", question, text)


@pytest.mark.parametrize(
    ("field", "question", "text"),
    [
        ("expectations", "wait", "还没写这一段让读者等什么。"),
        ("secrets", "reveal", "这一段还没有用得到的信息差。"),
    ],
)
def test_segment_missing_expectation_or_secret(setup, field, question, text):
    setup["segment"][field] = []
    assert_check(setup, "segment", question, text)


@pytest.mark.parametrize("kind", ["opening", "ending"])
@pytest.mark.parametrize("count", [0, 2])
def test_segment_requires_exactly_one_opening_and_one_ending(setup, kind, count):
    nodes = setup["segment"]["nodes"]
    target = next(node for node in nodes if node["kind"] == kind)
    if count == 0:
        target["kind"] = "milestone"
    else:
        nodes.append(deepcopy(target))
    assert_check(setup, "segment", "end", "需要且只能有一个开篇、一个结局。")


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("prerequisite", "这一段的终点还没写「之前得先有」。"),
        ("consequence", "这一段的终点还没写「之后变成」。"),
    ],
)
def test_segment_endpoint_missing_before_or_after(setup, field, text):
    setup["segment"]["nodes"][1][field] = ""
    assert_check(setup, "segment", "end", text)


def test_segment_missing_ending_direction(setup):
    ending = next(node for node in setup["segment"]["nodes"] if node["kind"] == "ending")
    ending["event"] = ""
    assert_check(setup, "segment", "direction", "还没写结局方向。")


def test_segment_missing_protagonist_arc(setup):
    setup["segment"]["protagonist_arc"] = ""
    assert_check(setup, "segment", "direction", "还没写主角最后变成什么样的人。")


def test_segment_empty_node_is_reported_with_its_position(setup):
    setup["segment"]["nodes"][1]["status"] = "empty"
    assert_check(setup, "segment", "direction", "节点 2 仍然留空，确认时需要补齐。")


def test_segment_missing_volume_cards(setup):
    setup["volumes"]["volumes"] = []
    assert_check(setup, "segment", "volumes", "这一段还没有分卷。")


def test_segment_more_than_three_volumes(setup):
    card = setup["volumes"]["volumes"][0]
    setup["volumes"]["volumes"] = [{**deepcopy(card), "index": index} for index in range(1, 5)]
    assert_check(setup, "segment", "volumes", "这一段分了 4 卷，通常一到三卷；远处的卷写到再定。")


@pytest.mark.parametrize(
    ("field", "value", "text"),
    [
        ("chapter_count", 0, "第 2 卷还没写预计章数。"),
        ("want", "", "第 2 卷还没写这一卷想做成什么。"),
    ],
)
def test_segment_volume_missing_chapter_count_or_want(setup, field, value, text):
    setup["volumes"]["volumes"][1][field] = value
    assert_check(setup, "segment", "volumes", text)


def test_segment_chapters_exceed_entire_book_plan(setup):
    setup["concept"].update(target_length=10, chapter_words=2000)
    setup["volumes"]["volumes"][0]["chapter_count"] = 31
    setup["volumes"]["volumes"][1]["chapter_count"] = 30
    assert_check(setup, "segment", "volumes", "这一段约 61 章，已经超过全书计划的 50 章。")


def test_segment_three_volumes_equal_to_book_plan_is_allowed(setup):
    setup["concept"].update(target_length=10, chapter_words=2000)
    card = setup["volumes"]["volumes"][0]
    setup["volumes"]["volumes"] = [
        {**deepcopy(card), "index": index, "chapter_count": chapters} for index, chapters in enumerate([20, 20, 10], 1)
    ]
    assert piece_checks("segment", setup) == []


def test_segment_missing_threads(setup):
    setup["volumes"]["threads"] = []
    assert_check(setup, "segment", "volumes", "这一段还没有线索。")


@pytest.mark.parametrize("other_anchor", [None, "高光"])
def test_segment_important_person_needs_an_arrival_anchor(setup, other_anchor):
    hero = next(character for character in setup["world"]["characters"] if character["role_type"] == "主角")
    hero["name"] = "待登场人物"
    if other_anchor:
        setup["volumes"]["anchors"].append({"character": "待登场人物", "node": 2, "kind": other_anchor})
    assert_check(setup, "segment", "cast", "「待登场人物」还没写什么时候登场。")


def test_segment_extra_person_does_not_require_an_arrival_anchor(setup):
    setup["world"]["characters"].append({"name": "无锚点路人", "role_type": "龙套"})
    assert piece_checks("segment", setup) == []


@pytest.mark.parametrize(
    ("field", "text"),
    [("want", "还没写这一卷想做成什么。"), ("pressure", "还没写卷首处境。")],
)
def test_first_volume_missing_want_or_pressure(setup, field, text):
    setup["first_volume"][field] = ""
    assert_check(setup, "first_volume", field, text)


@pytest.mark.parametrize("actions", [[], [{"ref": "F1", "action": "埋下"}], [{"ref": "E999", "action": "提醒"}]])
def test_first_volume_each_unit_needs_a_real_expectation_action(setup, actions):
    setup["first_volume"]["units"][0].update(index=2, title="查案", foreshadow_actions=actions)
    assert_check(setup, "first_volume", "units", "单元 2「查案」没有安排期待动作。")


def test_first_volume_unit_missing_core_loop(setup):
    setup["first_volume"]["units"][0].update(index=2, title="查案", loop="")
    assert_check(setup, "first_volume", "units", "单元 2「查案」还没写核心循环怎么转一圈。")


def test_first_volume_new_expectation_action_also_counts(setup):
    setup["first_volume"]["new_expectations"] = [{"seq": 999, "description": "等主角拿出证据"}]
    setup["first_volume"]["units"][0]["foreshadow_actions"] = [{"ref": "E999", "action": "立下"}]
    assert piece_checks("first_volume", setup) == []
