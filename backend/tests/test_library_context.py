"""第三包任务 2：模型上下文、原样 schema / 模板登记与无模型演示输出。"""

import ast
import uuid
from pathlib import Path

import pytest

from app.agents import schemas as s
from app.agents.context import format_concept
from app.library_config import BUILTIN_CATEGORIES, CHARACTER_CATEGORY, GENRE_DEFAULTS
from app.llm import demo
from app.models import Book, Character, PlotUnit, StoryNode, Volume, WorldEntry
from app.prompts import default_content
from app.prompts.catalog import BY_NAME, variables
from app.services.library_context import LibraryContext, genre_defaults, rewrite_mode
from app.services.splice import read_path


def entry(name="武道境界", **kwargs):
    values = dict(
        id=uuid.uuid4(),
        name=name,
        category="等级体系",
        style="ladder",
        content="吐纳可入门。",
        one_line="修士的境界。",
        levels=[{"name": "灵海", "text": "凝聚灵海。"}],
        fields=[],
        aliases=[],
        status="must",
        locked=False,
        parent_id=None,
    )
    values.update(kwargs)
    return WorldEntry(**values)


def character(name="楚风", **kwargs):
    values = dict(
        id=uuid.uuid4(),
        name=name,
        role_type="主角",
        aliases=["小风"],
        status="must",
        locked=True,
        one_line="敢拿命下注的少年。",
        want="救出母亲",
        gender="男",
        goal="终结寿元交易",
    )
    values.update(kwargs)
    return Character(**values)


@pytest.fixture
def context():
    hero = character()
    ladder = entry()
    country = entry(
        "天风国", category="世界与地图", style="paragraph", content="各城归皇室管。", one_line="", levels=[]
    )
    city = entry(
        "青阳城",
        category="世界与地图",
        style="paragraph",
        content="小风在城里遇见灵海修士。第二句。",
        parent_id=country.id,
        one_line="楚风出发的地方。",
        levels=[],
    )
    secret = entry(
        "底牌", category="往事与秘密", style="paragraph", content="寿元交易都是一场骗局。", one_line="骗局", levels=[]
    )
    ghost = entry(
        "末班车司机",
        category="custom:ghost",
        style="card",
        fields=[{"name": "外形", "value": "灰白"}, {"name": "规律", "value": "见红杀人"}],
        status="later",
        locked=True,
    )
    nodes = [
        StoryNode(id=uuid.uuid4(), kind="opening", position=0, title="出门", event="楚风离开家。", segment=None),
        StoryNode(
            id=uuid.uuid4(),
            kind="turn",
            position=1,
            title="旧名",
            event="楚风掌控城池。",
            segment={"title": "城中风雨", "text": "追查灵海。"},
        ),
        StoryNode(
            id=uuid.uuid4(),
            kind="turn",
            position=2,
            title="问道",
            event="查清旧事。",
            segment={"title": "往事", "text": ""},
        ),
        StoryNode(id=uuid.uuid4(), kind="ending", position=3, title="终局", event="终结寿元交易。", segment=None),
    ]
    volume = Volume(id=uuid.uuid4(), index=1, title="青阳", summary="去灵海。", target_node_id=nodes[1].id)
    unit = PlotUnit(id=uuid.uuid4(), index=1, title="夜路", summary="从夜路进城。")
    return LibraryContext(
        Book(id=uuid.uuid4(), genre="修仙", concept={"story": "楚风要改变命运。", "secret_entry_id": str(secret.id)}),
        [hero],
        [ladder, country, city, secret, ghost],
        [
            *[{**spec, "builtin": True} for spec in [CHARACTER_CATEGORY, *BUILTIN_CATEGORIES]],
            {
                "key": "custom:ghost",
                "name": "厉鬼",
                "style": "card",
                "hint": "说清规则。",
                "fields": ["外形", "规律"],
                "builtin": False,
            },
        ],
        nodes,
        [volume],
        [unit],
    )


def test_concept_new_secret_fallback_and_legacy(context):
    assert context.concept == "楚风要改变命运。\n底牌（只有作者和编辑部知道）：寿元交易都是一场骗局。"
    context.entries[3].content = ""
    assert context.concept.endswith("底牌（只有作者和编辑部知道）：骗局")
    context.book.concept["secret_entry_id"] = str(uuid.uuid4())
    assert context.concept == "楚风要改变命运。"
    context.book.concept = {"title": "旧书", "logline": "旧格式照旧"}
    assert context.concept == format_concept(context.book.concept)


def test_catalog_and_full_text_are_exact_and_category_ordered(context):
    assert context.library == (
        "【角色卡片】\n- 楚风（主角）（已锁）：敢拿命下注的少年。\n"
        "【等级体系】\n- 武道境界：修士的境界。\n"
        "【世界与地图】\n- 天风国\n- 青阳城（属于天风国）：楚风出发的地方。\n"
        "【往事与秘密】\n- 底牌：骗局\n【厉鬼】（自建类别）\n"
        "- 末班车司机（以后再说）（已锁）：修士的境界。"
    )
    assert context.entry_full_text(context.characters[0]) == (
        "角色卡片 · 楚风\n姓名：楚风\n别名：小风\n定位：主角\n性别：男\n想要什么：终结寿元交易\n此刻想要：救出母亲"
    )
    assert (
        context.entry_full_text(context.entries[0])
        == "等级体系 · 武道境界\n总说明：吐纳可入门。\n各级（从低到高）：\n1. 灵海：凝聚灵海。"
    )
    assert (
        context.entry_full_text(context.entries[2])
        == "世界与地图 · 青阳城\n一句话：楚风出发的地方。\n小风在城里遇见灵海修士。第二句。"
    )
    assert context.entry_full_text(context.entries[4]) == "厉鬼 · 末班车司机\n外形：灰白\n规律：见红杀人"
    assert context.library_full == "\n\n".join(context.entry_full_text(target) for target in context.targets)


def test_related_matches_names_and_aliases_by_appearance_and_limits_eight(context):
    city = context.entries[2]
    city.one_line = ""
    city.content = "底牌由小风查明，最后前往天风国。"
    assert context.related(city) == "\n\n".join(
        context.entry_full_text(target) for target in [context.entries[3], context.characters[0], context.entries[1]]
    )
    city.content = "没有提过任何人。"
    assert context.related(city) == "（没有）"
    many = [entry(f"路人{i}", category="特殊规则", style="paragraph") for i in range(10)]
    context.entries.extend(many)
    city.content = "、".join(target.name for target in reversed(many))
    assert context.related(city) == "\n\n".join(context.entry_full_text(target) for target in list(reversed(many))[:8])


def test_all_path_labels_hints_and_current_ranges(context):
    ladder, _, city, _, ghost = context.entries
    assert context.target_label(ladder, "content") == "等级体系 · 武道境界 · 总说明"
    assert context.target_label(ladder, "levels.0.name") == "等级体系 · 武道境界 · 第 1 级「灵海」的名称"
    assert (
        context.target_label(ladder, "levels.0.text@0:2") == "等级体系 · 武道境界 · 第 1 级「灵海」的介绍里选中的一句"
    )
    assert read_path(ladder, "levels.0.text@0:2") == "凝聚"
    assert context.target_label(city, "content") == "世界与地图 · 青阳城 · 一段话"
    assert context.target_label(city, "one_line") == "世界与地图 · 青阳城 · 一句话"
    assert context.target_label(city, "name") == "世界与地图 · 青阳城 · 名称"
    assert context.target_label(ghost, "fields.外形") == "厉鬼 · 末班车司机 · 外形"
    assert context.target_label(context.characters[0], "personality") == "角色卡片 · 楚风 · 性格与说话方式"
    assert context.target_label(context.book, "story") == "定调 · 一段话"
    assert context.target_label(context.nodes[1], "text") == "大纲 · 第 1 篇「城中风雨」 · 一段话"
    assert context.target_label(context.nodes[2], "title") == "大纲 · 第 2 篇「往事」 · 篇名"
    assert context.target_label(context.volumes[0], "summary") == "大纲 · 第 1 卷「青阳」 · 一段话"
    assert context.target_label(context.units[0], "summary") == "大纲 · 单元「夜路」 · 一段话"
    assert context.category_hint(context.characters[0]) == CHARACTER_CATEGORY["hint"]
    assert context.category_hint(ladder) == BUILTIN_CATEGORIES[0]["hint"]
    assert context.category_hint(ghost) == "说清规则。"
    assert context.category_hint(context.book) == "一段话说清这本小说主要讲什么故事"
    assert context.category_hint(context.nodes[1]) == "这一层的一段话要说清的事，见大纲的写法"


def test_outline_full_text_scope_and_ending_numbering(context):
    assert (
        context.outline
        == "第 1 篇「城中风雨」：追查灵海。\n  第 1 卷「青阳」：去灵海。\n第 2 篇「往事」：查清旧事。\n结局：终结寿元交易。"
    )
    assert context.entry_full_text(context.nodes[1]) == "大纲 · 第 1 篇「城中风雨」：追查灵海。"
    assert context.entry_full_text(context.volumes[0]) == "大纲 · 第 1 卷「青阳」：去灵海。"
    assert context.entry_full_text(context.units[0]) == "大纲 · 单元「夜路」：从夜路进城。"
    assert context.entry_full_text(context.book) == "定调：楚风要改变命运。"
    assert context.scope() == "查整个设定库。"
    assert context.scope(context.entries[0]) == "只查这一条：等级体系 · 武道境界；需要时对照别的条目。"
    context.nodes[-1].segment = {"title": "终篇", "text": "最后一战。"}
    assert "第 3 篇「终篇」：最后一战。" in context.outline
    context.nodes, context.volumes = [], []
    assert context.outline == "（还没有大纲）"


@pytest.mark.parametrize(
    "genre, group",
    [
        ("仙侠", "玄幻、仙侠"),
        ("修仙", "玄幻、仙侠"),
        ("都市异能", "都市"),
        ("游戏", "无限流、网游"),
        ("怪谈", "悬疑、灵异"),
        ("宅斗", "历史、宫斗、官场"),
    ],
)
def test_genre_defaults_exact_groups(genre, group):
    assert genre_defaults(genre) == "\n".join(
        [
            f"这本书的题材：{genre}",
            "这类书常建的条目（只是起点，按定调增减）：",
            *[
                f"- {category} · {name}（{'现在要定' if status == 'must' else '一句话就好'}）"
                for category, name, status in GENRE_DEFAULTS[group]
            ],
        ]
    )


def test_unknown_genre_lists_all_and_modes_are_verbatim():
    unknown = genre_defaults("")
    assert unknown.startswith("这本书的题材：没写\n这类书常建的条目（只是起点，按定调增减）：\n")
    assert [line for line in unknown.splitlines() if line.startswith("【")] == [
        f"【{group}】" for group in GENRE_DEFAULTS
    ]
    assert (
        rewrite_mode("options")
        == "给三种写法：稳妥、大胆、出格。稳妥的最贴近原来的意思，只把它写得更好；大胆的换一个更抓人的方向；出格的走一步险棋，但要和定调、底牌对得上。"
    )
    assert rewrite_mode("instruction", "要有代价") == "照作者的意思改：要有代价。作者没提到的意思，原样保留。"
    assert rewrite_mode("expand") == "写细一点：把这一处展开写具体，原来的意思一个都不能丢。"
    assert rewrite_mode("shorten") == "精简一点：把这一处压短，留下最要紧的意思。"


def test_route_name_precedence_and_path_resolution(context):
    hero, ladder, ghost = context.characters[0], context.entries[0], context.entries[4]
    assert context.find_target("楚风") is hero
    assert context.find_target("小风") is hero
    assert context.find_target("道境") is ladder
    assert context.find_target("没人") is None
    assert context.find_target("") is None
    assert context.route_path(hero, "性格与说话方式") == "personality"
    assert context.route_path(hero, "别名") == "aliases"
    assert context.route_path(hero, "此刻想要") == "want"
    assert context.route_path(hero, "location", "某地") == "location"
    assert context.route_path(ghost, "规律", "杀人") == "fields.规律@2:4"
    context.categories[-1]["fields"].append("声音")
    assert context.route_path(ghost, "声音") == "fields.声音"
    assert context.route_path(ghost, "不认识") == "fields.外形"
    assert context.route_path(ladder, "灵海") == "levels.0.text"
    assert context.route_path(ladder, "灵海的名称") == "levels.0.name"
    assert context.route_path(ladder, "一段话", "可入门") == "content@2:5"
    ladder.levels.append({"name": "真灵海", "text": "更高一级。"})
    assert context.route_path(ladder, "真灵海的名称") == "levels.1.name"


def test_schemas_preserve_task_ast_and_prompt_catalog():
    root = Path(__file__).resolve().parents[2]
    task = (root / "docs/codex任务/第三包/2-设定库的AI操作.md").read_text(encoding="utf-8")
    expected = ast.parse(task.split("```python\n", 1)[1].split("\n```", 1)[0])
    actual = ast.parse((root / "backend/app/agents/schemas.py").read_text(encoding="utf-8"))
    classes = {node.name: node for node in actual.body if isinstance(node, ast.ClassDef)}
    for node in expected.body:
        assert ast.dump(classes[node.name]) == ast.dump(node)
    prompts = {
        "library_rewrite": (
            "lorekeeper",
            "concept library target_full related target_label current category_hint mode",
        ),
        "library_fill_gaps": ("chief", "concept genre_defaults library requirements"),
        "library_review": ("reviewer", "concept library_full outline scope"),
        "library_route": ("chief", "library note"),
    }
    for name, (role, keys) in prompts.items():
        assert BY_NAME[name][3] == role
        assert [row["name"] for row in variables(name)] == keys.split()
        assert default_content(name)


@pytest.mark.asyncio
async def test_library_demo_all_structured_outputs(context, monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    options = await demo.respond(s.RewriteOptions, "", "原文：\n灵海境")
    assert [option.model_dump() for option in options.options] == [
        {"label": "稳妥", "text": "（稳妥）灵海境", "renamed": [], "one_line": ""},
        {"label": "大胆", "text": "（大胆）灵渊境", "renamed": [{"old": "灵海", "new": "灵渊"}], "one_line": ""},
        {"label": "出格", "text": "（出格）灵海境", "renamed": [], "one_line": ""},
    ]
    one = await demo.respond(s.RewriteOne, "", "原文：\n原样保留")
    assert one.text == "原样保留（已按要求修改）"
    assert one.renamed == []
    assert (await demo.respond(s.RewriteOne, "", "没有原文")).text == "新写法（已按要求修改）"
    gaps = await demo.respond(s.GapReport, "", f"【设定库目录】\n{context.library}")
    assert [(item.category, item.name, item.status) for item in gaps.entries] == [
        ("物品与功法", "九叶还魂草", "一句话就好"),
        ("角色卡片", "楚雄", "现在要定"),
    ]
    assert gaps.entries[1].fields == [s.FieldValue(name="定位", value="对手")]
    assert gaps.categories[0].fields == ["外形", "杀人规律", "怎么应对", "现在在哪"]
    assert not (await demo.respond(s.GapReport, "", "【设定库目录】\n【等级体系】\n- 境界")).categories
    review = await demo.respond(
        s.LibraryReview, "", f"【设定库】\n{context.library_full}\n\n【大纲】\n{context.outline}"
    )
    assert [(item.kind, item.target_name, item.quote, item.fix) for item in review.issues] == [
        ("好看", "", "", ""),
        ("矛盾", "天风国", "各城归皇室管。", "各城归皇室管。（已改）"),
    ]
    intent_prompt = f"【设定库目录】\n{context.library}\n\n【作者的话】\n"
    intent = await demo.respond(s.LibraryIntent, "", intent_prompt + "重想武道境界\n\n要求：不要影响识别")
    assert (intent.kind, intent.target_name, intent.mode) == ("改设定", "武道境界", "给几个写法")
    fallback = await demo.respond(s.LibraryIntent, "", intent_prompt + "换个设定")
    assert fallback.target_name == "楚风"
    assert (await demo.respond(s.LibraryIntent, "", intent_prompt + "下一章节奏快一点")).kind == "其他"
