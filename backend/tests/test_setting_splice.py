"""改一处的路径边界、原文校验与 JSON 独立性。"""

import uuid
from copy import deepcopy

import pytest

from app.models import Book, Character, PlotUnit, StoryNode, Volume, WorldEntry
from app.services.splice import STALE_TEXT, read_path, set_field, splice


def entry(**changes):
    return WorldEntry(
        **{
            "name": "青阳城",
            "content": "城外有海。海里有龙。",
            "one_line": "海边城池",
            "fields": [{"name": "规矩", "value": "夜不出门"}, {"name": "代价", "value": "十年寿命"}],
            "levels": [{"name": "灵海", "text": "神识如海"}, {"name": "化神", "text": "神游天地"}],
            "tags": ["第一卷"],
            "status": "must",
            "style": "paragraph",
            "locked": False,
            **changes,
        }
    )


def test_whole_field_and_selected_text_do_not_change_neighbors():
    target = entry()
    saved_fields = deepcopy(target.fields)
    assert splice(target, "one_line", "靠海的城", base="海边城池") == ("海边城池", "靠海的城")
    assert splice(target, "content@5:9", "水里有蛟", base="海里有龙") == (
        "城外有海。海里有龙。",
        "城外有海。水里有蛟。",
    )
    assert target.name == "青阳城"
    assert target.fields == saved_fields


def test_shifted_range_only_replaces_first_matching_occurrence():
    target = entry(content="新增。灵海与灵海，其他不变。")
    splice(target, "content@0:2", "灵渊", base="灵海")
    assert target.content == "新增。灵渊与灵海，其他不变。"
    splice(target, "content@100:102", "识海", base="灵渊")
    assert target.content == "新增。识海与灵海，其他不变。"


@pytest.mark.parametrize("path", ["content", "content@0:2"])
def test_stale_base_is_atomic(path):
    target = entry()
    before = target.content
    with pytest.raises(ValueError, match=STALE_TEXT):
        splice(target, path, "不该写入", base="已经没有的原文")
    assert target.content == before


def test_missing_card_field_appends_and_existing_field_is_isolated():
    target = entry()
    original = target.fields
    assert splice(target, "fields.规矩", "白天也别出门") == ("夜不出门", "白天也别出门")
    assert original[0]["value"] == "夜不出门"
    splice(target, "fields.来历", "来自前朝", base="")
    assert target.fields == [
        {"name": "规矩", "value": "白天也别出门"},
        {"name": "代价", "value": "十年寿命"},
        {"name": "来历", "value": "来自前朝"},
    ]


def test_level_edit_preserves_other_levels_and_original_json():
    target = entry()
    original = target.levels
    assert splice(target, "levels.0.name", "灵渊") == ("灵海", "灵渊")
    assert target.levels[0]["text"] == original[0]["text"]
    assert target.levels[1] == original[1]
    assert original[0]["name"] == "灵海"
    with pytest.raises(ValueError, match="这个等级不存在"):
        splice(target, "levels.2.text", "不能自动增加等级")


@pytest.mark.parametrize(
    "path",
    [
        "id",
        "book_id",
        "source",
        "created_at",
        "__dict__",
        "fields.",
        "levels.-1.name",
        "levels.0.id",
        "content@-1:2",
        "content@5:2",
        "content@a:2",
        "content@0:2@1:2",
        "content@0:999",
    ],
)
def test_invalid_paths_are_rejected_without_mutating_target(path):
    target = entry()
    before = (target.content, deepcopy(target.fields), deepcopy(target.levels))
    with pytest.raises(ValueError):
        splice(target, path, "越权内容")
    assert (target.content, target.fields, target.levels) == before


def test_all_target_types_use_only_their_documented_container():
    character = Character(name="阿青", personality="沉默", want="活下去")
    splice(character, "personality", "谨慎")
    assert character.want == "活下去"
    for protected in ("want", "location", "condition", "is_alive", "first_appearance_chapter"):
        with pytest.raises(ValueError):
            set_field(character, protected, "不该动")

    concept = {"story": "原故事", "pitches": [{"name": "甲", "text": "短版", "titles": ["书名"]}], "old": "保留"}
    book = Book(title="不改书名", concept=concept)
    splice(book, "story", "新故事")
    assert concept["story"] == "原故事"
    assert book.concept["old"] == "保留" and book.title == "不改书名"

    original_segment = {"title": "原篇名", "text": "原文", "number": 1, "opening": {"hook": "钩子"}}
    node = StoryNode(title="终点不变", event="终点事件", status="pencil", segment=original_segment)
    splice(node, "title", "青阳城篇")
    splice(node, "text", "从这里开始。")
    assert node.title == "终点不变" and node.event == "终点事件"
    assert node.segment["opening"] == original_segment["opening"]
    assert original_segment["title"] == "原篇名"
    for protected in ("segment", "number", "status", "position", "event", "kind"):
        with pytest.raises(ValueError):
            set_field(node, protected, "不该动")
    for target in (Volume(summary="原卷纲", status="approved"), PlotUnit(summary="原单元纲", status="done")):
        splice(target, "summary", "新的一段话")
        with pytest.raises(ValueError):
            set_field(target, "status", "planned")
        with pytest.raises(ValueError):
            set_field(target, "target_node_id", str(uuid.uuid4()))


def test_unplanned_segment_cannot_be_silently_created():
    node = StoryNode(segment=None)
    with pytest.raises(ValueError, match="这一篇还没规划"):
        splice(node, "text", "不能偷偷规划")
    assert node.segment is None


def test_read_path_returns_detached_data_and_checks_ranges():
    target = entry()
    assert read_path(target, "content@5:9") == "海里有龙"
    assert read_path(target, "fields.未填") == ""
    tags = read_path(target, "tags")
    tags.append("外部修改")
    assert target.tags == ["第一卷"]
    with pytest.raises(ValueError):
        read_path(target, "content@0:100")
    with pytest.raises(ValueError):
        read_path(target, "tags@0:1")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("locked", "true"),
        ("position", True),
        ("position", -1),
        ("status", "writing"),
        ("style", "unknown"),
        ("tags", "金手指"),
        ("aliases", [1]),
        ("name", None),
        ("fields", [{"name": "规矩", "value": 1}]),
        ("fields", [{"name": "", "value": "空名"}]),
        ("levels", [{"name": "灵海", "text": [], "id": "不能加结构"}]),
        ("parent_id", "not-uuid"),
    ],
)
def test_set_field_validates_types_before_write(path, value):
    target = entry()
    before = deepcopy(getattr(target, path))
    with pytest.raises(ValueError):
        set_field(target, path, value)
    assert getattr(target, path) == before


def test_set_field_accepts_valid_editable_values_and_detaches_json():
    target = entry()
    tags = ["金手指"]
    assert set_field(target, "tags", tags) == (["第一卷"], ["金手指"])
    tags.append("外部修改")
    assert target.tags == ["金手指"]
    assert set_field(target, "locked", True) == (False, True)
    parent_id = uuid.uuid4()
    set_field(target, "parent_id", str(parent_id))
    assert target.parent_id == parent_id
    set_field(target, "parent_id", None)
    assert target.parent_id is None
    assert set_field(target, "content@0:2", "城内") == ("城外有海。海里有龙。", "城内有海。海里有龙。")


def test_text_replacement_cannot_change_non_text_fields():
    target = entry()
    for path in ("tags", "locked", "levels"):
        with pytest.raises(ValueError):
            splice(target, path, "不该把结构变成文字")
