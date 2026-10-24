"""精髓提示词原字节、schema 原文、迁移与演示模型契约。"""

import ast
import hashlib
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.agents import schemas as s
from app.llm import demo, demo_teardown
from app.models import PlotUnit, Volume
from app.prompts import VARIABLE, catalog, default_content, render

ROOT = Path(__file__).resolve().parents[2]
HASHES = {
    "essence_cast": "4724ef49d8dd8fc8d457c66f7f2633b9cfd9f5d68e637791642570c9bb07e12b",
    "essence_check": "c27e50228843829ce75c9076f0aa64a38af82c1c627583d23b906ad4ed63bca3",
    "essence_fresh": "184452b2ee29da1beeae7deb05f8ef6ee6b8c83d73b73e763dd6eff0916a4558",
    "essence_hero": "dd94f5d29a2f8702e8c5138211402e3429160f73be82175a77369a584f95cc71",
    "essence_link": "9a1486cc4754492cab090f811d7d22ac09769b9b27d0459631964000fb87de86",
    "essence_longline": "42b50b5eae98d37023bbdb030554a12baecde06f1c83288857ee168a7ff0d05c",
    "essence_opening": "3333afc388f1b5d069debf0e88d815dba476d88080b12e54596fbb3959430108",
    "essence_overview": "94d4b4c9596f85f39d9401e695b7595e6ed25831c7bba94c921b762c964682c2",
    "essence_rhythm": "89975833095b8430f4f0041647720a9c1a49ad5766163fc8dc0136153b134c11",
    "essence_scene": "27edc05fea9737f93f0596094a85fec1d4a6bf1d3470a50be85b5877adcf6f84",
    "essence_setting": "0cb84e30da16782feaf0b9d254bb36d498a23b02d08357be9552dfcdd961074a",
    "essence_shuang": "a208cf76399680e7b251cc52689daaad3ea65772b54c84a5355893f5d8ec4d6d",
    "essence_skeleton": "cf50aeb848bc835bf4a2e419647567eb9b86b04cfafc85e30a3e64c7bd4b2a50",
    "essence_source": "e22a4c72cef15d86e6fee64f560c8ac9c4e0331726a5a92703e01ff7d951b2dc",
    "persona_essence": "529f749d8fb9884a0debaabf721e36d15487b9dbac2ed04e11c425bdacc5c001",
    "teardown_card": "d9319914f90177741ebfcb4c555cc457f01f9d530318a848987b58876d231faa",
    "teardown_merge": "b87afc3e0b25ca0f055b905e28931bdf61eac050ed2d38607d677f4f73e632c8",
    "teardown_read": "c1183b1fcc4892842c79d2f510778ae1c86c7d38cafcff75eea252910b5acf79",
    "teardown_tags": "5e4072f39de1fd8b1da38db3c960af826b397ba4683afb9c0fedc7d91fba9320",
    "teardown_unitplot": "7fe40c4265db7ce097ef393500023d9e28c0427828bf19e5fb521c9e3bc21ad3",
}
NEW_NAMES = [
    "persona_essence",
    "teardown_merge",
    "teardown_tags",
    "teardown_unitplot",
    "essence_source",
    "essence_skeleton",
    "essence_link",
    "essence_fresh",
    "essence_longline",
    "essence_setting",
    "essence_shuang",
    "essence_scene",
    "essence_hero",
    "essence_cast",
    "essence_rhythm",
    "essence_opening",
    "essence_overview",
    "essence_check",
]


@pytest.fixture(autouse=True)
def default_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    monkeypatch.setattr("app.prompts._load", default_content)


def schema_block():
    task = (ROOT / "docs/codex任务/拆书精髓/1-后台-精髓和拆书质量.md").read_text(encoding="utf-8")
    return re.search(r"```python\n(.*?)\n```", task.split("## 12. schema", 1)[1], re.S)[1]


def new_schemas():
    return [getattr(s, node.name) for node in ast.parse(schema_block()).body]


def test_twenty_prompt_bytes_and_catalog_are_exact():
    assert len(HASHES) == 20
    for name, digest in HASHES.items():
        assert hashlib.sha256((ROOT / f"backend/app/prompts/{name}.md").read_bytes()).hexdigest() == digest
        assert not (ROOT / f"docs/codex任务/拆书精髓/提示词/{name}.md").exists()
        group = "拆书精髓" if name == "persona_essence" or name.startswith("essence_") else "拆书"
        assert catalog.entry(name)[2:4] == (group, "teardown")
        catalog.validate_content(name, default_content(name))
        assert [row["name"] for row in catalog.variables(name)] == list(
            dict.fromkeys(VARIABLE.findall(default_content(name)))
        )
    names = [row[0] for row in catalog.CATALOG]
    assert [name for name in names if name in NEW_NAMES] == [
        "teardown_merge",
        "teardown_tags",
        "teardown_unitplot",
        *[name for name in NEW_NAMES if name not in {"teardown_merge", "teardown_tags", "teardown_unitplot"}],
    ]
    assert "teardown_merits" not in catalog.BY_NAME
    assert not (ROOT / "backend/app/prompts/teardown_merits.md").exists()
    assert catalog.VARIABLE_LABELS["units"] == "各单元回顾"
    assert catalog.VARIABLE_LABELS["upto"] == "拆到第几章"
    assert catalog.VARIABLE_LABELS["total"] == "全书章数"


def test_schema_source_descriptions_and_field_order_are_verbatim():
    block = schema_block()
    assert block in inspect.getsource(s)
    source = {node.name: node for node in ast.parse(inspect.getsource(s)).body if isinstance(node, ast.ClassDef)}
    nodes = ast.parse(block).body
    assert len(nodes) == 13
    for node in nodes:
        assert ast.dump(source[node.name]) == ast.dump(node)
    assert set(new_schemas()) <= demo_teardown.SCHEMAS


async def test_unitplot_column_is_not_null_jsonb_with_empty_default(sessionmaker):
    column = PlotUnit.__table__.c.teardown
    assert not column.nullable and str(column.type) == "JSONB"
    assert column.default.arg(None) == {}
    assert "teardown" not in Volume.__table__.c
    async with sessionmaker() as session:
        result = await session.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'plot_units' AND column_name = 'teardown'"
            )
        )
        assert result.one() == ("jsonb", "NO", "'{}'::jsonb")


@pytest.mark.parametrize("schema", new_schemas(), ids=lambda schema: schema.__name__)
async def test_demo_every_essence_schema_returns_valid_structure_without_records(schema):
    assert type(await demo.respond(schema, "", "已经读到第 1 章")) is schema


async def test_demo_tags_and_unitplots_cover_supplied_indices():
    tags = await demo.respond(
        s.TeardownTags,
        "",
        render(
            "teardown_tags",
            title="原书",
            chapters="第 37 章（爽）看点：智商碾压：解开局面｜发现线索\n第 42 章（大爽）看点：收获：拿到奖励｜完成目标",
        ),
    )
    assert [row.index for row in tags.chapters] == [37, 42]
    assert tags.chapters[0].tags == ["智商碾压"]
    units = "【单元 3】第 37–38 章「出门」\n那段话：遇到阻碍；寻找办法\n第 37 章：出门｜铺垫｜悬念\n\n【单元 4】第 39–42 章「回来」\n那段话：办完事情；回到家里\n第 42 章：归来｜收获｜平收"
    plots = await demo.respond(s.TeardownUnitPlots, "", render("teardown_unitplot", title="原书", units=units))
    assert [row.n for row in plots.units] == [3, 4]
    assert plots.units[0].shape == ["出门"]


@pytest.mark.parametrize("schema", [s.EssenceSection, s.EssenceCast, s.EssenceOverview])
async def test_demo_essence_cites_only_in_range_material_chapters(schema):
    system = render("persona_essence", title="书", upto="42", total="100", rules=render("rules"))
    result = await demo.respond(schema, system, "第 37 章：出门\n第 42 章：归来\n第 99 章：未来的事")
    assert result.points and result.points[0].chapters == [37, 42]


@pytest.mark.parametrize("schema", [s.EssenceSectionChecked, s.EssenceCastChecked])
async def test_demo_check_returns_original_section_without_rewriting(schema):
    section = (
        "【人物】记录人名（导师）｜怎么立：行动立住｜作用：指路｜变化：（空）｜章：[37, 42]\n"
        "【第 1 条】原有招式：原有说法\n  steps 1：原有第一步\n  steps 2：原有第二步\n"
        "  evidence：原有证据\n  note：原有提醒\n  chapters：[37, 42]"
    )
    user = render(
        "essence_check",
        title="原书",
        section_name="情节怎么想",
        section=section,
        records="第 37 章：出门\n第 42 章：归来",
    )
    result = await demo.respond(schema, "", user)
    point = result.points[0]
    assert point.title == "原有招式：原有说法"
    assert point.steps == ["原有第一步", "原有第二步"]
    assert point.evidence == "原有证据" and point.note == "原有提醒"
    assert point.chapters == [37, 42] and result.fixes == []
    if schema is s.EssenceCastChecked:
        assert result.figures[0].name == "记录人名" and result.figures[0].arc == ""
