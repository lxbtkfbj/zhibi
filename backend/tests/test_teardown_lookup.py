"""群聊翻拆过的书：目录快照、四样只读结果和逐字文案。"""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select, update

from app.models import Book, Chapter, Character, Foreshadowing, WorldEntry
from app.services import chat_tools
from app.services import teardown_lookup as lookup
from app.services.teardown_lookup import LookUpTeardown


def point(title="极限残局开局：用假废材与多重危机压出反弹力", **extra):
    return {
        "title": title,
        "steps": ["给主角扣上天生残废与地位卑微的明面耻辱标签", "开局当天叠加死局"],
        "evidence": "第2章玄脉残废且成婚晨遭弑心散毒杀，第7章揭开玄脉是被外力毁的。",
        "note": "第一波反击必须踩死直接下毒的仇人。",
        "chapters": [2, 7, 35],
        **extra,
    }


def essence():
    return {
        "upto": 40,
        "overview": {
            "genre": "玄幻复仇爽文。",
            "engine": "旧账兑现之前先立新因。",
            "points": [point("因果接力：旧账兑现前先立新因", note="")],
        },
        "sections": {
            "setting": {"points": [point()], "missing": ["没有家族谱系", "没有幼年记录"]},
            "cast": {
                "figures": [
                    {
                        "name": "茉莉",
                        "archetype": "傲娇毒舌师尊",
                        "build": "外形与狠绝杀戮战力形成反差。",
                        "role": "充当随身最高战力与眼界天花板。",
                        "arc": "从冷漠寄居到毒舌师徒。",
                        "chapters": [12, 41],
                    },
                    {
                        "name": "夏倾月",
                        "archetype": "高冷白月光",
                        "build": "以沉默立人。",
                        "role": "牵引主线。",
                        "arc": "",
                        "chapters": [1, 2],
                    },
                ],
                "points": [point("反差立人设：外在标签与核心行为剧烈对撞")],
                "missing": ["缺后半段人物转折"],
            },
            "opening": {"points": [point("分层揭示：开篇背景与秘密按步剥开")], "missing": []},
            "fresh": {"points": [], "missing": ["没看出来"]},
        },
        "rails": {"huge": "不应随书目载入" * 1000},
        "inputs": {"huge": "不用的调用缓存" * 1000},
    }


async def seed(sessionmaker, *, title="逆天邪神", chapters=40, source="teardown", data=None, day=1, waits=True):
    async with sessionmaker() as session:
        teardown = {"essence": deepcopy(data if data is not None else essence()), "unused": "不能整列读" * 1000}
        if waits:
            teardown["waits"] = {"upto": 40, "total": 3, "unused": "不应载入" * 1000}
        book = Book(
            title=title,
            source=source,
            created_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=day),
            teardown=teardown,
        )
        session.add(book)
        await session.flush()
        session.add_all(
            Chapter(book_id=book.id, index=index, title=f"原书{index}", status="final")
            for index in range(1, chapters + 1)
        )
        await session.commit()
        return book.id


async def query(sessionmaker, look, words=None, *, book="逆天邪神", catalog=None):
    args = LookUpTeardown(book=book, look=look, **({"words": words} if words is not None else {}))
    async with sessionmaker() as session:
        catalog = catalog if catalog is not None else await lookup.load_catalog(session)
        return await lookup.look_up(session, catalog, args)


def task_schema():
    task = Path(__file__).resolve().parents[2] / "docs/codex任务/主编查拆过的书/1-群聊里翻拆过的书.md"
    return json.loads(task.read_text(encoding="utf-8").split("```json\n", 1)[1].split("```", 1)[0])["function"]


async def test_catalog_filter_deduplicate_order_and_partial(sessionmaker):
    await seed(sessionmaker, title="没有精髓", data={})
    await seed(sessionmaker, title="空核心要点", data={"overview": {"points": []}})
    await seed(sessionmaker, title="不是拆书", source="new")
    await seed(sessionmaker, title="作者导入", source="imported")
    await seed(sessionmaker, title="逆天邪神", chapters=2, day=1)
    await seed(sessionmaker, title="逆天邪神", chapters=4, day=2)
    await seed(sessionmaker, title="惊悚乐园", chapters=3, day=3)
    newest = await seed(sessionmaker, title="逆天邪神", chapters=4, day=4)
    await seed(sessionmaker, title="逆天邪神", chapters=1, day=5)
    partial = essence()
    partial["upto"] = 2
    await seed(sessionmaker, title="我有一座冒险屋", chapters=5, day=6, data=partial)
    async with sessionmaker() as session:
        catalog = await lookup.load_catalog(session)
    assert [book.title for book in catalog] == ["惊悚乐园", "逆天邪神", "我有一座冒险屋"]
    assert catalog[1].id == newest and catalog[1].chapters == 4
    text = lookup.catalog_text(catalog)
    assert "《我有一座冒险屋》5 章，精髓只整理到第 2 章。玄幻复仇爽文。" in text
    assert "- 保持新鲜：" not in text
    assert (
        "- 配角与对手：茉莉（傲娇毒舌师尊）、夏倾月（高冷白月光）；「反差立人设：外在标签与核心行为剧烈对撞」" in text
    )
    assert text.index("- 设定设计：") < text.index("- 配角与对手：") < text.index("- 开篇：")
    spec = lookup.tool_spec(catalog)["function"]
    assert spec["parameters"]["properties"]["book"]["enum"] == [book.title for book in catalog]
    assert spec["description"] == lookup.DESCRIPTION + "\n拆过的书和它们精髓的目录：\n" + text


async def test_catalog_queries_only_json_paths_and_is_a_turn_snapshot(sessionmaker):
    bid = await seed(sessionmaker)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async with sessionmaker() as session:
        engine = session.bind.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            catalog = await lookup.load_catalog(session)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert len(statements) == 1
        statement = statements[0]
        assert "books.teardown[" in statement and "books.teardown," not in statement
        assert set(catalog[0].essence) == {"upto", "overview", "sections"}
        assert catalog[0].waits == {"upto": 40, "total": 3}
        await session.execute(update(Book).where(Book.id == bid).values(title="新名字", teardown={}))
        await session.commit()
    assert lookup.resolve_book(catalog, "逆天邪神").id == bid
    assert lookup.resolve_book(catalog, "新名字") is None
    label, text = await query(sessionmaker, "精髓", catalog=catalog)
    assert label == "《逆天邪神》精髓「核心要点」" and "旧账兑现之前先立新因。" in text
    async with sessionmaker() as session:
        assert await lookup.load_catalog(session) == []


async def test_empty_catalog_no_tool_and_schema_wording_matches_task(sessionmaker):
    async with sessionmaker() as session:
        assert lookup.tool_spec(await lookup.load_catalog(session)) is None
    example = task_schema()
    assert example["description"].split("\n拆过的书", 1)[0] == lookup.DESCRIPTION
    await seed(sessionmaker)
    async with sessionmaker() as session:
        spec = lookup.tool_spec(await lookup.load_catalog(session))["function"]
    actual = deepcopy(spec["parameters"])
    actual["properties"]["book"]["enum"] = example["parameters"]["properties"]["book"]["enum"]
    assert actual == example["parameters"]


@pytest.mark.parametrize("value", ["开篇", '["开篇"]', ["开篇"]])
def test_words_string_or_json_array(value):
    args = LookUpTeardown(book="逆天邪神", look="精髓", words=value)
    assert args.words == ["开篇"]


def test_words_trim_drop_empty_and_keep_first_five():
    args = LookUpTeardown(
        book="逆天邪神", look="精髓", words=["  「 核心要点 」  ", "《》", " ", "《开篇》", "甲", "乙", "丙", "丁"]
    )
    assert args.words == ["核心要点", "开篇", "甲", "乙", "丙"]


async def test_exact_title_precedes_normalized_and_unknown_is_soft_error(sessionmaker):
    first = await seed(sessionmaker)
    second = await seed(sessionmaker, title="逆天 邪神", day=2)
    async with sessionmaker() as session:
        catalog = await lookup.load_catalog(session)
        assert lookup.resolve_book(catalog, "逆天 邪神").id == second
        assert lookup.resolve_book(catalog, " 《 逆天邪神 》 ").id == first
    label, text = await query(sessionmaker, "精髓", book="没拆过的书", catalog=catalog)
    assert label == "拆过的书「没拆过的书」"
    assert text == "没有这本拆过的书：「没拆过的书」。拆过的有：《逆天邪神》《逆天 邪神》，book 照工具说明里的书名写。"
    assert lookup.doing_of(LookUpTeardown(book="没拆过的书", look="精髓"), catalog) == "在查拆过的书……"


async def test_essence_section_exact_text_missing_and_order(sessionmaker):
    await seed(sessionmaker)
    label, text = await query(sessionmaker, "精髓", ["设定设计"])
    assert label == "《逆天邪神》精髓「设定设计」"
    assert text == (
        "《逆天邪神》精髓：拆书时从前 40 章整理的，章号是原书的。\n"
        "【设定设计】极限残局开局：用假废材与多重危机压出反弹力\n"
        "怎么用：\n1. 给主角扣上天生残废与地位卑微的明面耻辱标签\n2. 开局当天叠加死局\n"
        "书里的证据：第2章玄脉残废且成婚晨遭弑心散毒杀，第7章揭开玄脉是被外力毁的。\n"
        "要注意：第一波反击必须踩死直接下毒的仇人。\n见第 2、7、35 章\n\n"
        "这一节拆书时没看出来的：没有家族谱系；没有幼年记录"
    )
    _, cast = await query(sessionmaker, "精髓", ["配角与对手"])
    assert (
        cast.index("【配角与对手】茉莉") < cast.index("【配角与对手】夏倾月") < cast.index("【配角与对手】反差立人设")
    )
    assert cast.endswith("这一节拆书时没看出来的：缺后半段人物转折")


async def test_essence_core_and_figure_optional_lines(sessionmaker):
    await seed(sessionmaker)
    label, text = await query(sessionmaker, "精髓")
    assert label == "《逆天邪神》精髓「核心要点」"
    assert text.startswith(
        "《逆天邪神》精髓：拆书时从前 40 章整理的，章号是原书的。\n【核心要点】\n这是一本什么书：玄幻复仇爽文。\n靠什么让人一直追：旧账兑现之前先立新因。\n\n【核心要点】因果接力"
    )
    assert "要注意：" not in text
    _, figure = await query(sessionmaker, "精髓", ["茉莉"])
    assert figure.split("\n", 1)[1] == (
        "【配角与对手】茉莉：傲娇毒舌师尊\n怎么立起来：外形与狠绝杀戮战力形成反差。\n"
        "在剧情里起什么作用：充当随身最高战力与眼界天花板。\n怎么变：从冷漠寄居到毒舌师徒。\n见第 12、41 章"
    )
    _, archetype = await query(sessionmaker, "精髓", ["毒舌"])
    assert archetype == figure
    _, no_arc = await query(sessionmaker, "精髓", ["夏倾月"])
    assert "怎么变：" not in no_arc


async def test_essence_title_substring_precedence_and_deduplicate(sessionmaker):
    data = essence()
    duplicate = point("因果接力：旧账兑现前先立新因", note="换了注意事项")
    data["sections"]["source"] = {"points": [duplicate, point("因果：另一种招式")]}
    data["sections"]["opening"]["points"].append(point("毒舌：标题先于人物模板"))
    await seed(sessionmaker, data=data)
    _, found = await query(sessionmaker, "精髓", ["因果"])
    assert found.count("因果接力：旧账兑现前先立新因") == 1
    assert found.index("【核心要点】因果接力") < found.index("【情节怎么想】因果：另一种招式")
    _, title_first = await query(sessionmaker, "精髓", ["毒舌"])
    assert "【开篇】毒舌：" in title_first and "【配角与对手】茉莉" not in title_first
    _, match = await query(sessionmaker, "精髓", ["假废材"])
    assert "【设定设计】极限残局开局" in match
    _, missing = await query(sessionmaker, "精髓", ["没有的招式"])
    assert missing.endswith("精髓里没有「没有的招式」：写目录里的节名、招式名，或者人物名。")


async def test_essence_clips_each_word_to_3000_once_and_only_five_words(sessionmaker):
    data = essence()
    data["sections"]["setting"]["points"][0]["evidence"] = "证" * 6000
    await seed(sessionmaker, data=data)
    words = ["设定设计", "极限残局", "假废材", "反弹力", "核心要点", "不会出现"]
    label, text = await query(sessionmaker, "精髓", words)
    assert label == "《逆天邪神》精髓" + "".join(f"「{word}」" for word in words[:5])
    assert "不会出现" not in text and text.count("截掉了）") == 4
    expected = [chat_tools.clip(lookup.essence_text(data, word), 3000) for word in words[:5]]
    assert text.split("\n", 1)[1] == "\n\n".join(expected)


async def test_settings_same_full_text_alias_and_archetype_append(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            [
                Character(book_id=bid, name="茉莉", aliases=["师尊"], personality="毒舌", background="寄居珠内"),
                Character(book_id=bid, name="倾月", aliases=["夏倾月"], personality="高冷"),
                WorldEntry(book_id=bid, category="物品道具", name="天毒珠", content="能净毒", style="entry"),
            ]
        )
        await session.commit()
        book = await session.get(Book, bid)
        _, baseline = await chat_tools.look_up(
            session, book, "look_up_settings", chat_tools.LookUpSettings(names=["师尊"]), None
        )
    label, text = await query(sessionmaker, "设定", ["师尊", "天毒珠", "不存在", "倾月"])
    assert label == "《逆天邪神》设定「茉莉」「天毒珠」「不存在」「倾月」"
    assert text.startswith(
        "《逆天邪神》设定：拆书时从原文整理的卡片。\n"
        + baseline
        + "\n精髓里的人设模板：傲娇毒舌师尊（怎么立起来，查精髓「茉莉」）"
    )
    assert "精髓里的人设模板：高冷白月光（怎么立起来，查精髓「夏倾月」）" in text
    assert "设定里没有「不存在」：拆书时不是每个人、每样东西都写了卡，可以到原文里搜。" in text
    assert (await query(sessionmaker, "设定")) == (
        "《逆天邪神》设定",
        "《逆天邪神》设定：拆书时从原文整理的卡片。\n没说要查谁。",
    )


async def test_settings_clip_after_archetype_and_no_cross_book(sessionmaker):
    bid = await seed(sessionmaker)
    other = await seed(sessionmaker, title="另一书")
    async with sessionmaker() as session:
        session.add(Character(book_id=bid, name="茉莉", personality="字" * 3000))
        session.add(Character(book_id=other, name="只在另一本", personality="不能泄入查询结果"))
        await session.commit()
    label, text = await query(sessionmaker, "设定", ["茉莉", "只在另一本"])
    assert label == "《逆天邪神》设定「茉莉」「只在另一本」"
    assert text.count("截掉了）") == 1
    assert "不能泄入查询结果" not in text
    assert "设定里没有「只在另一本」" in text


async def seed_waits(sessionmaker, bid, count=10, status="resolved"):
    async with sessionmaker() as session:
        for seq in range(count, 0, -1):
            session.add(
                Foreshadowing(
                    book_id=bid,
                    seq=seq,
                    kind="期待",
                    description="下毒" if seq % 3 == 1 else f"仇{seq}",
                    plant_plan="下毒" if seq % 3 == 2 else "第 2 章",
                    payoff_plan="下毒" if seq % 3 == 0 else "第 35 章",
                    plant_volume=1,
                    payoff_volume=1,
                    status=status,
                )
            )
        await session.commit()


async def test_waits_code_keyword_order_overflow_and_no_match(sessionmaker):
    bid = await seed(sessionmaker)
    await seed_waits(sessionmaker, bid)
    label, text = await query(sessionmaker, "读者在等的事", ["e2", "F2", "下毒", "没有的关键词"])
    assert label == "《逆天邪神》读者在等的事「e2」「F2」「下毒」「没有的关键词」"
    assert text.startswith(
        "《逆天邪神》读者在等的事：拆书时整理到第 40 章，一共 3 件。\n- E2［期待·中·已兑现·第1卷立、第1卷兑现］读者在等：仇2（立：下毒；兑现：第 35 章）\n\n没有「F2」这一件。"
    )
    assert "还有 2 件也提到「下毒」：E9、E10（要细节写编号再查）" in text
    assert text.index("- E1［") < text.index("- E8［") < text.index("还有 2 件")
    assert text.endswith("没有提到「没有的关键词」的：换个说法，或者到原文里搜。")
    assert "- E9［" not in text and "- E10［" not in text


async def test_waits_default_open_twenty_overflow_and_none(sessionmaker):
    bid = await seed(sessionmaker)
    assert (await query(sessionmaker, "读者在等的事"))[1].endswith("没有还吊着的。")
    await seed_waits(sessionmaker, bid, 22, "planted")
    async with sessionmaker() as session:
        await session.execute(update(Foreshadowing).where(Foreshadowing.seq == 1).values(status="planned"))
        await session.execute(update(Foreshadowing).where(Foreshadowing.seq == 22).values(status="resolved"))
        await session.commit()
    label, text = await query(sessionmaker, "读者在等的事")
    assert label == "《逆天邪神》读者在等的事「还吊着的」"
    assert "\n到最后还吊着的：\n- E1［" in text
    assert "- E20［" in text and "- E21［" not in text and "E22" not in text
    assert text.endswith("还有 1 件：E21（要细节写编号再查）")


async def test_waits_uncollected_is_only_one_sentence(sessionmaker):
    await seed(sessionmaker, waits=False)
    label, text = await query(sessionmaker, "读者在等的事", ["下毒"])
    assert label == "《逆天邪神》读者在等的事「下毒」"
    assert text == "《逆天邪神》还没整理读者在等的事。"


@pytest.mark.parametrize("word", ["第 35 章", "第35章", "第 35章", "第35 章"])
async def test_original_chapter_without_status(sessionmaker, word):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        await session.execute(
            update(Chapter)
            .where(Chapter.book_id == bid, Chapter.index == 35)
            .values(
                title="星隐，以血祭恨(下)",
                outline={"goal": "复仇", "scenes": ["潜入房中"], "cool_point": "清算", "hook": "离去"},
                summary="萧澈找萧玉龙报仇。",
                content="不直接提供整章正文。",
            )
        )
        await session.commit()
    label, text = await query(sessionmaker, "原文", [word])
    assert label == f"《逆天邪神》原文「{word}」"
    assert (
        text
        == "《逆天邪神》原文：一共 40 章。\n第 35 章《星隐，以血祭恨(下)》\n章纲：\n发生什么：复仇\n潜入房中\n看点：清算\n结尾钩子：离去\n摘要：萧澈找萧玉龙报仇。"
    )
    assert "已定稿" not in text and "不直接提供整章正文" not in text
    assert (await query(sessionmaker, "原文", ["第 41 章"]))[1].endswith("没有第 41 章。")
    assert (await query(sessionmaker, "原文", ["第 1 章"]))[1] == "《逆天邪神》原文：一共 40 章。\n第 1 章《原书1》"


async def test_original_search_identical_to_existing_tool_and_only_one_clip(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        await session.execute(
            update(Chapter)
            .where(Chapter.book_id == bid)
            .values(title="章" * 100, content="前" * 70 + "萧玉龙" + "后" * 70)
        )
        await session.commit()
        book = await session.get(Book, bid)
        expected = await chat_tools.search_text(session, book, "萧玉龙")
    label, text = await query(sessionmaker, "原文", ["萧玉龙", "没人"])
    assert label == "《逆天邪神》原文「萧玉龙」「没人」"
    assert text == "《逆天邪神》原文：一共 40 章。\n" + expected + "\n\n原文里没有「没人」。"
    assert text.count("截掉了）") == 1
    assert (await query(sessionmaker, "原文")) == ("《逆天邪神》原文", "《逆天邪神》原文：一共 40 章。\n没说要搜什么。")


@pytest.mark.parametrize(
    ("look", "words", "doing", "label"),
    [
        (
            "精髓",
            ["设定设计", "极限残局开局"],
            "在翻《逆天邪神》的精髓……",
            "《逆天邪神》精髓「设定设计」「极限残局开局」",
        ),
        ("设定", ["茉莉"], "在查《逆天邪神》的设定……", "《逆天邪神》设定「茉莉」"),
        ("读者在等的事", ["下毒"], "在查《逆天邪神》读者在等的事……", "《逆天邪神》读者在等的事「下毒」"),
        ("原文", ["萧玉龙", "第 35 章"], "在翻《逆天邪神》的原文……", "《逆天邪神》原文「萧玉龙」「第 35 章」"),
    ],
)
async def test_exact_doing_and_result_labels(sessionmaker, look, words, doing, label):
    await seed(sessionmaker)
    async with sessionmaker() as session:
        catalog = await lookup.load_catalog(session)
        args = LookUpTeardown(book=" 《逆天邪神》 ", look=look, words=words)
        assert lookup.doing_of(args, catalog) == doing
        assert (await lookup.look_up(session, catalog, args))[0] == label


async def test_all_four_lookups_are_read_only(sessionmaker):
    bid = await seed(sessionmaker)
    await seed_waits(sessionmaker, bid)
    async with sessionmaker() as session:
        before = (await session.execute(select(Book.teardown).where(Book.id == bid))).scalar_one()
        catalog = await lookup.load_catalog(session)
        for look in lookup.LOOKS:
            await lookup.look_up(session, catalog, LookUpTeardown(book="逆天邪神", look=look, words=["茉莉"]))
        assert not session.dirty and not session.new and not session.deleted
        after = (await session.execute(select(Book.teardown).where(Book.id == bid))).scalar_one()
        assert after == before
