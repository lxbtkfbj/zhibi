"""第三包写作上下文：配置排序、正文惯例与规划/写手底牌隔离。"""

from copy import deepcopy

from app.agents.context import format_concept, format_next_segment, format_spine, format_unit, format_volumes_part
from app.models import (
    Book,
    Chapter,
    Character,
    Foreshadowing,
    PlotUnit,
    Secret,
    SettingCategory,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.prompts import render
from app.services.library_context import load_context
from app.services.writing_context import (
    chapter_blocks,
    chapter_plan_blocks,
    clean_materials,
    material_blocks,
    pick_materials,
    planning_library,
    segment_blocks,
    segment_text,
    volume_blocks,
    world_text,
    writer_world,
)


async def library_story(session):
    book = Book(
        title="上下文测试",
        status="writing",
        concept={"story": "少年追查古灯旧案。", "target_length": 200},
        protagonist={"finger": "废弃主角卡哨兵"},
        world={"power": "废弃世界卡哨兵"},
    )
    session.add(book)
    await session.flush()
    node = StoryNode(
        book_id=book.id,
        position=1,
        kind="milestone",
        title="山门揭榜",
        segment={"title": "山城篇", "text": "先查山城，再赴山门。", "finale": True},
    )
    session.add(node)
    await session.flush()
    volume = Volume(
        book_id=book.id, index=1, title="山城", summary="主角在山城调查。", chapter_count=3, target_node_id=node.id
    )
    session.add(volume)
    await session.flush()
    unit = PlotUnit(
        book_id=book.id, volume_id=volume.id, index=1, title="灯巷", summary="进入灯巷找证人。", chapter_count=3
    )
    session.add(unit)
    await session.flush()
    chapter = Chapter(
        book_id=book.id,
        volume_id=volume.id,
        unit_id=unit.id,
        index=1,
        title="入巷",
        outline={"characters": ["主角"], "foreshadow_actions": [{"ref": "F1", "action": "埋下", "detail": "看见暗纹"}]},
        materials={"world": ["底牌原件", "引用底牌"], "characters": ["底牌角色"]},
    )
    secret = Secret(
        book_id=book.id, seq=1, title="底牌信息差", truth="绝不泄露真相甲", knowers=[{"name": "主角"}], status="hidden"
    )
    secret2 = Secret(
        book_id=book.id, seq=2, title="普通信息差", truth="证人在灯巷", knowers=[{"name": "主角"}], status="hidden"
    )
    session.add_all([chapter, secret, secret2])
    await session.flush()
    main = Character(
        book_id=book.id, name="主角", role_type="主角", tags=["金手指"], background="主角公开来历", want="找到证人"
    )
    rows = [
        WorldEntry(
            book_id=book.id,
            category="往事与秘密",
            name="底牌原件",
            tags=["底牌"],
            one_line="绝不泄露目录甲",
            content="绝不泄露真相甲",
            secret_id=secret.id,
        ),
        WorldEntry(
            book_id=book.id,
            category="往事与秘密",
            name="引用底牌",
            tags=[],
            one_line="绝不泄露目录乙",
            content="绝不泄露真相乙",
        ),
        WorldEntry(book_id=book.id, category="物品与功法", name="古灯", tags=["金手指"], content="公开的古灯机制"),
        WorldEntry(book_id=book.id, category="世界与地图", name="山城", content="全城依山而建"),
        WorldEntry(
            book_id=book.id, category="特殊规则", name="夜禁", status="one", one_line="入夜必须熄灯", content=""
        ),
        WorldEntry(
            book_id=book.id,
            category="等级体系",
            name="品级",
            style="ladder",
            content="逐级提升",
            levels=[{"name": "一品", "text": "初入门"}],
        ),
    ]
    session.add_all(
        [
            main,
            *rows,
            Character(book_id=book.id, name="底牌角色", role_type="配角", tags=["底牌"], background="绝不泄露角色丙"),
        ]
    )
    session.add(
        Foreshadowing(book_id=book.id, seq=1, description="古灯底部的纹路", plant_plan="看见暗纹", status="planned")
    )
    await session.flush()
    book.concept = {**book.concept, "secret_entry_id": str(rows[1].id)}
    await session.flush()
    return book, volume, unit, chapter, rows


def test_new_and_legacy_segment_text_and_spine_sequence_are_exact():
    nodes = [
        {"title": "开篇", "kind": "opening"},
        {"title": "旧终点", "status": "pinned", "segment": {"title": "山城篇", "text": "查清旧案。", "number": 99}},
        {"title": "远景", "status": "pencil"},
        {"title": "新终点", "segment": {"goal": "渡河", "number": 120}},
        {"title": "结局", "kind": "ending"},
    ]
    before = deepcopy(nodes)
    text = format_spine({"nodes": nodes})
    assert "这是第 1 篇「山城篇」的终点：查清旧案。" in text
    assert "这是第 2 篇的终点：目标：渡河" in text
    assert "已锁" in text and "没锁" in text and "这一篇写到再定" in text
    assert "核心矛盾：" not in text and "99" not in text and nodes == before
    assert segment_text({"title": "山城篇", "text": "查清旧案。", "finale": True, "goal": "渡河"}, 2).startswith(
        "第 2 篇「山城篇」：查清旧案。\n这是收尾篇：开始收线，揭开底牌，往结局方向走。\n第 2 篇"
    )
    assert (
        format_unit({"index": 1, "title": "入城", "summary": "进入山城。", "chapter_count": 3}).splitlines()[1]
        == "这一单元：进入山城。"
    )
    assert "定调：故事" in format_concept({"story": "故事", "secret_entry_id": "不可输出"})
    assert "不可输出" not in format_concept({"story": "故事", "secret_entry_id": "不可输出"})


async def test_planning_uses_library_full_text_and_category_order_not_retired_cards(sessionmaker):
    async with sessionmaker() as session:
        book, volume, _, _, rows = await library_story(session)
        context = await load_context(session, book)
        protagonist, world = planning_library(context)
        assert protagonist.count("角色卡片 · 主角") == 1
        assert (
            protagonist.index("角色卡片 · 主角")
            < protagonist.index("物品与功法 · 古灯")
            < protagonist.index("往事与秘密 · 引用底牌")
        )
        assert "绝不泄露真相乙" in protagonist
        assert "废弃主角卡哨兵" not in protagonist and "废弃世界卡哨兵" not in world
        must = world.split("现在要定的条目：\n")[1]
        assert must.index("等级体系 · 品级") < must.index("世界与地图 · 山城")
        assert "古灯" not in must and "引用底牌" not in must
        for blocks in (await volume_blocks(session, book, volume), await segment_blocks(session, book)):
            assert blocks["protagonist"] == protagonist and blocks["world"] == world
            assert blocks["concept"].startswith("书名：") and "底牌" not in blocks["concept"]
        volume_context = await volume_blocks(session, book, volume)
        assert volume_context["fixed"] == ""
        assert volume_context["segment"].startswith("第 1 篇「山城篇」：先查山城")
        assert "这一篇写了第 1-1 卷。" in (await segment_blocks(session, book))["last_segment"]
        book.concept = {"story": "新书明确没有秘密"}
        rows[0].tags = []
        assert (await segment_blocks(session, book))["no_secret"] == ""
        book.concept = {}
        assert (await segment_blocks(session, book))[
            "no_secret"
        ] == "【这本书还没有底牌】\n请从已经写出来的金手指、谜团里推一两句底牌，写在 secret 里，让作者确认。"


async def test_bottom_cards_and_linked_secrets_never_reach_chapter_side(sessionmaker):
    async with sessionmaker() as session:
        book, volume, unit, chapter, rows = await library_story(session)
        blocks = await chapter_blocks(session, book, chapter)
        materials = await material_blocks(session, book, chapter)
        chapters = await chapter_plan_blocks(session, book, volume, unit, 1)
        for context in (blocks, materials, chapters):
            for value in context.values():
                assert "绝不泄露" not in value
                assert "底牌原件" not in value and "引用底牌" not in value and "底牌角色" not in value
        assert "普通信息差" in blocks["secrets"] and "古灯底部的纹路" in blocks["ledger"]
        assert "夜禁：入夜必须熄灯" in blocks["world"]
        assert "- [特殊规则] 夜禁：入夜必须熄灯" in materials["world_catalog"]
        picked = await pick_materials(
            session, book.id, 1, {"world": ["底牌原件", "引用底牌", "山城"], "characters": ["底牌角色", "主角"]}
        )
        assert picked["world"] == ["山城"] and picked["characters"] == ["主角"]
        assert "绝不泄露真相甲" not in world_text(rows, "底牌原件", ["底牌原件"])
        assert clean_materials({"world": ["底牌原件"]}, [], rows, 1)["world"] == []
        # 逐个渲染真正的模型模板，不只检查中间字典；缺变量也由这些断言覆盖。
        for template in (
            "write_chapter",
            "extend_chapter",
            "rewrite_ending",
            "review_chapter",
            "check_consistency",
            "digest_chapter",
        ):
            values = {
                **blocks,
                "revision": "",
                "feedback": "",
                "missing": "",
                "target_words": "3000",
                "word_count": "0",
                "instructions": "",
                "ending": "",
                "prefix": "",
                "needed": "",
                "words": "0",
                "reason": "",
                "body": "",
                "ending_words": "200",
                "hook": "",
                "strictness": "",
            }
            prompt = render(template, **values)
            assert "绝不泄露" not in prompt


async def test_conventions_30_limit_category_order_source_and_selected_exclusions(sessionmaker):
    async with sessionmaker() as session:
        book, _, _, _, _ = await library_story(session)
        custom = SettingCategory(book_id=book.id, key="custom", name="自建规范", style="paragraph")
        session.add(custom)
        session.add_all(
            [
                *(
                    WorldEntry(
                        book_id=book.id,
                        category="世界与地图",
                        name=f"地点{i:02}",
                        status="one",
                        one_line=f"惯例{i}",
                        position=i,
                    )
                    for i in range(35)
                ),
                WorldEntry(book_id=book.id, category="custom:custom", name="自建惯例", status="one", one_line="靠后"),
                WorldEntry(
                    book_id=book.id,
                    category="世界与地图",
                    name="写作记下的",
                    status="one",
                    source="writing",
                    one_line="不是固定惯例",
                ),
            ]
        )
        await session.flush()
        text = writer_world(await load_context(session, book), "", ["地点00"])
        conventions = text.split("这本书的惯例：\n")[1]
        assert len(conventions.splitlines()) == 30
        assert "地点00" not in conventions and "地点01" in conventions
        assert "写作记下的" not in conventions and "底牌" not in conventions and "自建惯例" not in conventions


def test_new_arc_revision_text_and_split_appendix():
    assert format_next_segment(
        {
            "title": "山城篇",
            "text": "查旧案。",
            "end": {"ref": 2, "title": "揭榜", "event": "揭开旧案"},
            "fill_entries": [{"name": "山城", "content": "山中的城"}],
            "new_entries": [{"category": "势力划分", "name": "守灯会", "one_line": "守灯者"}],
            "new_characters": [{"name": "小甲", "role_type": "班底", "one_line": "带路者"}],
            "secret": "旧主人尚在",
            "ending_change": "归来",
        }
    ) == (
        "篇名：山城篇\n一段话：查旧案。\n终点：揭榜——揭开旧案（用已有的节点 2）\n写全的设定：山城：山中的城\n新设定：[势力划分] 守灯会：守灯者\n新人物：小甲（班底）：带路者\n推的底牌：旧主人尚在\n结局调整：归来"
    )
    assert "（新起一个节点）" in format_next_segment({"text": "查案", "end": {"ref": 0, "title": "新终点"}})
    split = format_volumes_part(
        {"wait": {"description": "读者等揭榜"}, "secrets": [{"seq": 1, "title": "旧事", "truth": "有隐情"}]}
    )
    assert "读者在等：读者等揭榜\n\n信息差：\n- S1" in split
