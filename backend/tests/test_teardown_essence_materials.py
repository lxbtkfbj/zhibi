"""材料逐字对照试验脚本；不执行脚本里的作者库连接和模型入口。"""

import ast
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import teardown_essence_materials as product

ROOT = Path(__file__).resolve().parents[2]


def reference():
    source = (ROOT / "docs/拆书/精髓试验/analyze.py").read_text(encoding="utf-8")
    nodes = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "ctype",
            "spans",
            "tag_facts",
            "tag_examples",
            "unit_block",
            "plot_line",
            "materials",
            "top_tags",
            "scene_material",
            "section_text",
        }:
            nodes.append(node)
        if isinstance(node, ast.ClassDef) and node.name == "Book":
            node.body = [
                child for child in node.body if not isinstance(child, ast.FunctionDef) or child.name != "__init__"
            ]
            nodes.append(node)
    namespace = {"re": __import__("re"), "Counter": Counter, "defaultdict": defaultdict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "reference-analyze", "exec"), namespace)
    rail_source = (ROOT / "docs/拆书/精髓试验/render_page.py").read_text(encoding="utf-8")
    rail_node = next(
        node for node in ast.parse(rail_source).body if isinstance(node, ast.FunctionDef) and node.name == "rail_data"
    )
    exec(compile(ast.Module(body=[rail_node], type_ignores=[]), "reference-rails", "exec"), namespace)
    return namespace


def sample():
    chapters = []
    for index in range(1, 25):
        person = {
            "name": "旧名" if index == 1 else "甲",
            "was": "旧名" if index == 2 else "",
            "also_called": [],
            "shown": f"甲在第{index}章写出来的身份、本事和说话样子" * 5,
            "change": f"关系和实力变化{index}" if index % 3 == 0 else "",
        }
        people = [person]
        if index in (1, 2, 3, 20, 24):
            people.append(
                {"name": "乙", "shown": f"乙的样子{index}", "change": "与甲交好", "also_called": [], "was": ""}
            )
        feel = ("憋屈", "平", "爽", "大爽")[index % 4]
        chapter = SimpleNamespace(
            id=index,
            index=index,
            title=f"章名{index}",
            content=f"原文{index}：甲和乙的对话与动作。" * 250,
            summary=f"甲在第{index}章用铜镜解围，来到青城，认识乙。" * 20,
            outline={
                "goal": f"章纲{index}",
                "scenes": ["青城 / 茶楼", "解围"],
                "cool_point": f"反转：铜镜制敌{index}",
                "hook": "悬念：何时相认",
            },
            unit_id=(index - 1) // 8 + 1 if index <= 16 else None,
            teardown={
                "read_version": 1,
                "read": {
                    "feel": feel,
                    "people": people,
                    "moments": [{"who": "甲", "what": f"场面{index}", "shows": "聪明"}] if index % 5 == 0 else [],
                    "things": [
                        {
                            "kind": "物品功法",
                            "name": "铜镜",
                            "note": "铜镜的作用" * 30,
                            "secret": "埋下",
                            "belongs": "甲",
                        },
                        {"kind": "地方", "name": "青城", "note": "城中地理", "secret": "", "belongs": "青国"},
                    ],
                    "waits": [{"action": "立下", "what": "何时相认"}] if index == 1 else [],
                    "tropes": ["拍卖会"],
                },
                "tags": {"tags": ["反转", "智取"] if index % 3 else ["打脸"], "crowd": "乙震惊" if index % 5 else ""},
            },
        )
        chapters.append(chapter)
    units = [
        SimpleNamespace(
            id=n,
            title=f"单元{n}",
            summary=f"单元话{n}",
            teardown={
                "plot": {
                    "trigger_type": "前事的后果",
                    "trigger": "前事发作",
                    "shape": ["起", "承", "转", "合"],
                    "payoff": "反转：铜镜制敌",
                    "new": ["铜镜"],
                    "changed": ["舞台"],
                    "stakes": "更大",
                    "stakes_note": "牵涉青城",
                    "hook_out": "有人追来",
                    "seeds": "信物",
                }
            },
        )
        for n in (1, 2)
    ]
    waits = [
        SimpleNamespace(
            kind="期待",
            seq=1,
            description="何时相认",
            planted_chapter=1,
            hint_chapters=[3],
            resolved_chapter=8,
            payoff_plan="第 8 章：终于相认",
        ),
        SimpleNamespace(
            kind="伏笔",
            seq=1,
            description="铜镜来历",
            planted_chapter=3,
            hint_chapters=[12],
            resolved_chapter=None,
            payoff_plan="",
        ),
    ]
    cards = [
        SimpleNamespace(
            name=name,
            one_line=f"{name}一句话",
            personality="坚韧",
            background="生于青城",
            want="寻人",
            goal="解谜",
            abilities="铜镜",
        )
        for name in ("甲", "乙")
    ]
    merges = [{"names": ["旧名", "甲"], "keep": "甲", "why": "第2章相认", "kept_card": True}]
    book = SimpleNamespace(title="小书", teardown={"names": {"旧名": "甲"}, "merges": {"groups": merges}})
    return book, chapters, units, waits, cards


def pair():
    args = sample()
    data = product.BookData(*args)
    ns = reference()
    expected = ns["Book"].__new__(ns["Book"])
    for key in ("meta", "chapters", "units", "waits", "cards", "texts", "by_index", "last", "plots", "tags"):
        setattr(expected, key, deepcopy(getattr(data, key)))
    expected._people(data.merges)
    return data, expected, ns


@pytest.mark.parametrize(
    "key", ["source", "setting", "shuang", "cast", "skeleton", "link", "fresh", "longline", "hero", "rhythm", "opening"]
)
def test_materials_match_reference_byte_for_byte(key):
    data, expected, ns = pair()
    assert product.materials(data, key).encode("utf-8") == ns["materials"](expected, key).encode("utf-8")


def test_scene_and_unit_materials_match_reference_byte_for_byte():
    data, expected, ns = pair()
    assert product.top_tags(data) == ns["top_tags"](expected)
    for tag in product.top_tags(data):
        assert product.scene_material(data, tag).encode("utf-8") == ns["scene_material"](expected, tag).encode("utf-8")
    for unit in data.units:
        assert product.unit_block(data, unit).encode("utf-8") == ns["unit_block"](expected, unit).encode("utf-8")


def test_rails_match_reference_all_keys_and_database_mapping():
    data, expected, ns = pair()
    inputs = {"tags": {str(key): value for key, value in data.tags.items()}, "plots": data.plots, "merges": data.merges}
    actual = product.rail_data(data, inputs)
    assert actual == ns["rail_data"](expected, inputs)
    assert set(actual) == {
        "feel",
        "strip",
        "tags",
        "crowd",
        "hooks",
        "triggers",
        "stakes",
        "units",
        "tail",
        "waits",
        "open",
        "people",
        "things",
        "hero",
        "merges",
    }
    assert data.waits[0]["how"] == "终于相认"
    assert data.waits[0]["code"] == "E1" and data.waits[1]["code"] == "F1"
    assert actual["tail"] == [17, 24]
    assert actual["people"][0] == ("甲", 24)
    assert "kept_card" not in actual["merges"][0]


def test_checker_records_sort_filter_cap_expand_ranges_and_add_waits_things():
    data, _, _ = pair()
    section = {
        "points": [{"title": "第 19–24 章", "steps": ["第 1 章"], "evidence": "第 99 章", "chapters": [8, 3, 24]}],
        "figures": [{"name": "乙", "build": "2章", "role": "第4章回归", "arc": "", "chapters": [20]}],
    }
    text = product.cited_records(data, section, cap=6)
    assert [line.split("：", 1)[0] for line in text.splitlines()] == [
        "第 1 章",
        "第 2 章",
        "第 3 章",
        "第 4 章",
        "第 8 章",
        "第 19 章",
    ]
    assert "读者在等的事：立下：何时相认｜新冒出来的：物品功法「铜镜」、地方「青城」" in text
    assert "读者在等的事：没有" in text


def test_section_text_and_overview_match_reference_order():
    _, _, ns = pair()
    point = {
        "title": "招式",
        "steps": ["先压", "后扬"],
        "evidence": "证据" * 50,
        "note": "注意",
        "chapters": [1, 2, 3, 7],
    }
    section = {
        "name": "人物",
        "points": [point],
        "figures": [
            {"name": "乙", "archetype": "对手", "build": "用反差", "role": "推动剧情", "arc": "", "chapters": [1]}
        ],
    }
    assert product.section_text(section) == ns["section_text"](section)
    assert (
        product.overview_material({"cast": section}, ["source", "cast"])
        == f"【人物】招式｜怎么用：先压；后扬｜证据：{'证据' * 40}（第 1–3、7 章）"
    )


def test_empty_roster_does_not_invent_a_person_or_crash_opening():
    args = sample()
    for chapter in args[1]:
        chapter.teardown["read"]["people"] = []
        chapter.teardown["read"]["moments"] = []
    args[0].teardown = {}
    data = product.BookData(*args)
    assert "主角：（没有）。" in product.materials(data, "opening")
    product.materials(data, "hero")
    assert not data.appear


def test_real_unit_ranges_and_numbering_include_failed_chapters_and_sparse_reads():
    args = sample()
    for chapter in args[1][:8]:
        chapter.teardown = {"read_failed": "旧记录失败"}
    args[1][8].teardown = {"read_version": 1, "read": {"people": []}}
    args[1][15].teardown = {"read_failed": "另一章失败"}
    data = product.BookData(*args)
    assert [(unit["n"], unit["first"], unit["last"]) for unit in data.units] == [(1, 1, 8), (2, 9, 16)]
    assert data.by_index[9]["feel"] == "平" and data.by_index[9]["things"] == []
    assert "【单元 1】第 1–8 章" in product.unit_block(data, data.units[0])
    assert "第 1 章：" not in product.unit_block(data, data.units[0])
