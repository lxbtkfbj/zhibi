"""The supplied wording, schema ordering and defaults are executable contracts."""

import ast
import hashlib
import re
from pathlib import Path

import pytest

from app.agents import schemas
from app.book_settings import compile_rules, default_settings, merge_settings, settings_of
from app.llm import demo
from app.prompts.catalog import VARIABLE_LABELS, variables
from app.schemas import SegmentDecision

ROOT = Path(__file__).resolve().parents[2]
PROMPTS = {
    "plan_segment": "88ebcc65b4deecd962003315ff8a85dd0e56d8e4a1af09876c3157f7f0f33b7e",
    "split_segment": "3350f8ca910a8e45a5a2f085c508dbae4ef4e74b668c349adbfbe1ede89c4975",
    "plan_volume": "c7180d20aee1ff14901fe1f4fd89fa2f24f209b3bd487e46a378f9dd907fbe2b",
    "plan_chapters": "bfefd711e7c052a6b070e9a99a1ccbad0e4a602b20b0f03f574d979d147901b8",
    "digest_chapter": "ef93d91acc8caf034ed748bbe7750f82798fc361f84c6628c89c8e9d190fa3ae",
}


@pytest.mark.parametrize(("name", "expected"), PROMPTS.items())
def test_supplied_prompt_bytes_and_registered_variables(name, expected):
    path = ROOT / "backend/app/prompts" / f"{name}.md"
    # Git stores LF; Windows checkouts may materialize CRLF.
    assert hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected
    assert not (ROOT / "docs/codex任务/第三包/提示词" / f"{name}.md").exists()
    assert all(item["label"] for item in variables(name))


def test_schema_definitions_exactly_match_task_including_field_order():
    task = (ROOT / "docs/codex任务/第三包/5-写作接入.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", task, re.S)
    source = ast.parse(Path(schemas.__file__).read_text(encoding="utf-8"))
    actual = {node.name: node for node in source.body if isinstance(node, ast.ClassDef)}
    expected = ast.parse("\n".join(blocks[:2]))
    for node in expected.body:
        assert ast.dump(actual[node.name]) == ast.dump(node), node.name
    entry, fields = blocks[3].split("# ChapterDigest 新增，放在 new_secrets 后面：\n")
    assert ast.dump(actual["ChapterEntry"]) == ast.dump(ast.parse(entry).body[0])
    digest_fields = ast.parse("class Digest:\n" + fields).body[0].body
    body = actual["ChapterDigest"].body
    index = next(
        i for i, node in enumerate(body) if isinstance(node, ast.AnnAssign) and node.target.id == "new_secrets"
    )
    assert [ast.dump(node) for node in body[index + 1 : index + 3]] == [ast.dump(node) for node in digest_fields]
    summary = ast.parse("class Unit:\n" + blocks[2]).body[0].body[0]
    body = actual["PlotUnitDraft"].body
    assert ast.dump(body[2]) == ast.dump(summary)
    assert not hasattr(schemas, "NextSegmentDraft")


def test_chapters_approval_default_old_books_and_effort_independence():
    assert default_settings()["chapters_approval"] is False
    assert settings_of(type("Book", (), {"settings": {}})())["chapters_approval"] is False
    for preset in ("quick", "balanced", "premium"):
        value = merge_settings({"chapters_approval": True}, {"effort_preset": preset})
        assert value["chapters_approval"] is True
    assert compile_rules({"chapters_approval": True}) == ""
    assert SegmentDecision(action="redo").action == "redo"
    assert VARIABLE_LABELS["fixed"] == "已经定了的分卷或单元"


def test_demo_new_shapes_fixed_card_counts_and_no_secret_request():
    arc = demo._next_segment()
    assert arc.title == "天风国篇"
    assert 200 <= len(arc.text) <= 400
    assert arc.secret == ""
    assert demo._next_segment("【这本书还没有底牌】\n请推一句").secret
    split = demo._segment_volumes("【这一篇已经分好的卷】\n第 4 卷「作者卷」约 9 章（已锁）：作者原文\n\n【其他】\n")
    assert [(item.index, item.title, item.chapter_count, item.summary) for item in split.volumes] == [
        (4, "作者卷", 9, "作者原文")
    ]
    assert split.wait and len(split.secrets) == 2
    volume = demo._volume_plan(
        "【这一卷已经拆好的单元】\n单元 1「作者单元」3 章（已出章纲）（已锁）：作者一段话\n\n【其他】\n"
    )
    assert len(volume.units) == 1
    assert volume.units[0].summary == "作者一段话"
    digest = demo._digest("第 2 章《例》已经定稿\n【正文】\n测试冲突")
    assert digest.new_entries and digest.conflicts
