"""第三批静态契约、演示 schema 与群聊整理进度。"""

import ast
import hashlib
import inspect
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents import schemas as s
from app.library_config import SOURCES
from app.llm import demo, demo_teardown
from app.prompts import catalog, default_content, render
from app.services.teardown_chat import book_info

ROOT = Path(__file__).resolve().parents[2]
HASHES = {
    "teardown_card": "3d98bf9ec95a7234e3370625944d4e360a2573c35fcdd4870c773d9e6ae92ea1",
    "teardown_world": "1554d585462b19503f0090bcc08d5eb705e9002cc41aa947aab149c7a63241e2",
    "teardown_merits": "11075ae0400a0155dfce7838b7e743f7e27fb8d990f358fa6c2ac60a7afa6129",
}


@pytest.fixture(autouse=True)
def fast_default_prompts(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.prompts._load", default_content)


def test_three_prompt_bytes_sources_catalog_and_variables():
    for name, expected in HASHES.items():
        assert hashlib.sha256((ROOT / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == expected
        assert not (ROOT / f"docs/codex任务/拆书第三批/提示词/{name}.md").exists()
        assert catalog.entry(name)[2:4] == ("拆书", "teardown")
        variables = catalog.variables(name)
        assert variables and all(item["label"] for item in variables)
        catalog.validate_content(name, default_content(name))
    assert SOURCES["teardown"] == "拆书拆出来的"


def test_all_twenty_one_schema_classes_are_verbatim_including_field_order():
    task = (ROOT / "docs/codex任务/拆书第三批/1-后台-拆设定和好在哪.md").read_text(encoding="utf-8")
    blocks = [textwrap.dedent(block).strip() for block in re.findall(r"```python\n(.*?)\n\s*```", task, re.S)]
    actual_source = inspect.getsource(s)
    names = []
    for block in blocks:
        assert block in actual_source
        for node in ast.parse(block).body:
            names.append(node.name)
            actual = getattr(s, node.name)
            expected = [item.target.id for item in node.body if isinstance(item, ast.AnnAssign)]
            assert list(actual.model_fields) == expected
    assert len(names) == 21
    assert {getattr(s, name) for name in names} == demo_teardown.SCHEMAS


@pytest.mark.parametrize("stage", ["running", "queued", "stopped", "done"])
@pytest.mark.parametrize("upto", [None, 8])
def test_book_info_settings_progress_third_line_only(stage, upto):
    info = {"stage": stage, "settings": {"upto": upto}}
    book = SimpleNamespace(title="原书", teardown=info)
    chapters = [SimpleNamespace(index=8, word_count=10, teardown={"read_version": 1})]
    text = book_info(book, chapters, [], [])
    assert len(text.splitlines()) == 3
    assert ("设定还没整理" in text.splitlines()[2]) is (upto is None)
    assert ("设定整理到第 8 章" in text.splitlines()[2]) is (upto == 8)


def card_prompt():
    return render(
        "teardown_card",
        title="原书",
        last=3,
        name="红发少女",
        aliases="少女",
        count=3,
        chapters="1–3",
        protagonist="云澈",
        dossier="第 1 章：第一次相遇\n第 2 章名场面：答应帮忙——立住了有原则\n第 9 章名场面：未来事件——立住了越界",
    )


async def test_demo_card_only_uses_passed_records_and_in_range_moments():
    result = await demo.respond(s.TeardownCard, "", card_prompt())
    assert result.name == "红发少女" and result.aliases == ["少女"]
    assert result.one_line == "第一次相遇" and result.role_type == "配角"
    assert [moment.chapter for moment in result.moments] == [2]
    assert result.moments[0].what == "答应帮忙"


@pytest.mark.parametrize(
    "schema,kind",
    [
        (s.TeardownLadders, "等级"),
        (s.TeardownGoldfingers, "金手指"),
        (s.TeardownPlaces, "地方"),
        (s.TeardownFactions, "势力"),
        (s.TeardownItems, "物品功法"),
        (s.TeardownSecrets, "秘密"),
        (s.TeardownRules, "规矩"),
    ],
)
async def test_demo_all_world_wrappers_preserve_names_and_legal_chapter_numbers(schema, kind):
    user = render(
        "teardown_world",
        title="原书",
        last=3,
        protagonist="云澈",
        kind=kind,
        things="- 记录名字（原文里出现过 2 章，第一次在第 2 章）：第 2 章：原始记录（属于 上一级）（埋下）；第 3 章：真相（揭开）",
        context="角色卡上写的所属：\n- 云澈：记录名字",
        kind_rule="照记录写",
    )
    result = await demo.respond(schema, "", user)
    assert type(result) is schema
    item = (result.ladders if schema is s.TeardownLadders else result.items)[0]
    assert item.name == "记录名字"
    if schema is s.TeardownLadders:
        assert item.levels[0].name == "记录名字"
    elif schema is s.TeardownSecrets:
        assert (item.planted_chapter, item.revealed_chapter) == (2, 3)
    else:
        assert item.first_chapter == 2
    if schema is s.TeardownPlaces:
        assert item.parent == "上一级"
    if schema is s.TeardownFactions:
        assert item.members == ["云澈"]


async def test_demo_merits_only_uses_program_facts():
    user = render(
        "teardown_merits",
        title="原书",
        last=3,
        facts="第 1 章摘要：处境艰难\n单元：1 个，平均 3.0 章\n- 第 2 章：获得帮助\n读者在等的事：\n- 第 2 章立下：走出家门\n用过的桥段：退婚\n名场面最多的人：\n- 云澈（1 场）：第 2 章 答应帮忙",
    )
    result = await demo.respond(s.TeardownMerits, "", user)
    assert len(result.points) == 6 and not result.missing
    assert all("第 3 章" in point.text and len(point.text) <= 150 for point in result.points)
    assert "平均 3.0 章" in result.points[1].text


@pytest.mark.parametrize("schema", sorted(demo_teardown.SCHEMAS, key=lambda item: item.__name__))
async def test_demo_every_new_schema_has_a_handler_even_without_records(schema):
    assert type(await demo.respond(schema, "", "已经读到第 1 章")) is schema
