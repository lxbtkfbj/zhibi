"""第三包三步开书保存规则，不使用真实模型。"""

from copy import deepcopy

from sqlalchemy import select

from app.api.library import _apply_suggestion
from app.models import (
    Book,
    Chapter,
    Character,
    PlotUnit,
    SettingCategory,
    SettingSuggestion,
    SettingVersion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.services.setup_store import (
    load_new_setup,
    save_library_focus,
    save_library_rest,
    save_outline,
    save_story_concept,
)


def concept(**changes):
    return {
        "story": "少年借轮回镜重修，追查旧日背叛。",
        "secret": "轮回镜藏着前世真相。幕后人仍在等他。",
        "title": "逆世帝尊",
        "genre": "玄幻·修仙",
        "target_length": 400,
        "chapter_words": 3000,
        **changes,
    }


def focus(**changes):
    return {
        "protagonist": {
            "name": "楚风",
            "role_type": "主角",
            "status": "现在要定",
            "one_line": "失去修为的少年",
            "personality": "倔强",
            "background": "楚家少年",
            "goal": "夺回自己的命",
            "abilities": "淬体",
        },
        "finger": {"place": "物品与功法", "name": "轮回镜", "one_line": "照见旧世", "content": "一天只能使用一次。"},
        **changes,
    }


def rest():
    return {
        "characters": [
            {
                "name": "凝霜",
                "role_type": "女主",
                "status": "现在要定",
                "one_line": "携婚约而来的少女",
                "personality": "外冷内热",
                "background": "古族来客",
                "goal": "找到真相",
            }
        ],
        "entries": [
            {
                "category": "世界与地图",
                "name": "青阳城",
                "status": "现在要定",
                "one_line": "开篇之地",
                "content": "两族争斗。",
                "parent": "天风国",
            },
            {
                "category": "世界与地图",
                "name": "世界概况",
                "status": "现在要定",
                "one_line": "以武为尊",
                "content": "武道决定秩序。",
            },
            {
                "category": "世界与地图",
                "name": "天风国",
                "status": "以后再说",
                "one_line": "青阳城所属国",
                "content": "",
            },
            {
                "category": "等级体系",
                "name": "武道境界",
                "status": "现在要定",
                "one_line": "六层境界",
                "content": "依次提升",
                "levels": [{"name": "淬体", "text": "打磨筋骨"}],
            },
            {"category": "不存在", "name": "未知设定", "status": "一句话就好", "one_line": "未知归入特殊规则"},
            {
                "category": "厉鬼",
                "name": "末班车司机",
                "status": "一句话就好",
                "one_line": "只在午夜出现",
                "fields": [{"name": "规则", "value": "不可答话"}],
            },
        ],
        "categories": [{"name": "厉鬼", "style": "卡片", "fields": ["规则"], "hint": "说清规则", "why": "核心敌人"}],
    }


def outline():
    return {
        "arcs": [
            {"title": "青阳城篇", "text": "楚风在青阳城夺回尊严。", "planned": True},
            {"title": "天风国篇", "text": "走向天风国。", "planned": False},
        ],
        "ending": "查明前世真相。",
        "volumes": [
            {"title": "废物", "summary": "从退婚走到族比。", "chapter_count": 20},
            {"title": "秦家", "summary": "面对秦家。", "chapter_count": 10},
        ],
        "units": [
            {"title": "退婚", "summary": "未婚妻上门，楚风立誓。", "chapter_count": 3},
            {"title": "识宝", "summary": "轮回镜认主。", "chapter_count": 4},
        ],
        "new_names": [
            {"category": "角色卡片", "name": "楚雄", "one_line": "楚家族长"},
            {"category": "错类", "name": "神桥", "one_line": "通往上界"},
        ],
    }


async def new_book(session):
    book = Book(title="未命名", concept={"legacy": "旧键保留"})
    session.add(book)
    await session.flush()
    return book


async def test_concept_secret_merge_version_and_author_protection(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        await save_story_concept(session, book.id, concept(pitches=[{"name": "逆袭"}], benchmark="读者爱看逆袭"))
        secret = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == book.id))
        assert secret.locked and secret.tags == ["底牌"] and secret.status == "must"
        assert secret.one_line == "轮回镜藏着前世真相。"
        assert book.title == "逆世帝尊" and book.genre == "玄幻·修仙"
        assert book.concept["legacy"] == "旧键保留"
        assert book.concept["secret_entry_id"] == str(secret.id)
        assert "secret" not in book.concept
        secret.source, secret.content = "ai_edited", "作者自己的真相"
        await session.flush()
        await save_story_concept(session, book.id, concept(secret="AI 想覆盖的真相"))
        assert secret.content == "作者自己的真相"
        assert (await load_new_setup(session, book.id))["concept"]["secret"] == "作者自己的真相"
        await save_story_concept(session, book.id, concept(secret="没有"))
        assert book.concept["secret_entry_id"] is None
        assert (await load_new_setup(session, book.id))["concept"]["secret"] == "没有"
        assert await session.scalar(select(SettingVersion).where(SettingVersion.target_type == "concept"))


async def test_no_secret_does_not_create_entry(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        await save_story_concept(session, book.id, concept(secret="没有"))
        assert await session.scalar(select(WorldEntry).where(WorldEntry.book_id == book.id)) is None


async def test_library_incremental_parent_category_suggestion_and_accept(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        await save_library_focus(session, book.id, focus())
        first = await load_new_setup(session, book.id)
        assert len(first["settings"]["characters"]) == 1 and len(first["settings"]["entries"]) == 1
        await save_library_rest(session, book.id, rest())
        entries = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id)))
        by_name = {entry.name: entry for entry in entries}
        assert "末班车司机" not in by_name
        assert by_name["青阳城"].parent_id == by_name["天风国"].id
        assert by_name["世界概况"].position == 0
        assert by_name["武道境界"].style == "ladder"
        assert by_name["武道境界"].levels == [{"name": "淬体", "text": "打磨筋骨"}]
        assert by_name["未知设定"].category == "特殊规则"
        suggestion = await session.scalar(select(SettingSuggestion).where(SettingSuggestion.book_id == book.id))
        assert suggestion.title == "建一个自建类别「厉鬼」，放进1条设定——核心敌人"
        await _apply_suggestion(session, suggestion)
        category = await session.scalar(select(SettingCategory).where(SettingCategory.book_id == book.id))
        ghost = await session.scalar(select(WorldEntry).where(WorldEntry.name == "末班车司机"))
        assert ghost.category == f"custom:{category.key}" and ghost.source == "suggestion" and ghost.status == "one"
        assert ghost.fields == [{"name": "规则", "value": "不可答话"}]
        assert await session.scalar(select(SettingVersion).where(SettingVersion.target_id == ghost.id))
        assert (await load_new_setup(session, book.id))["settings"][
            "summary"
        ] == "主编建了 9 条：现在要定 6 条，一句话 2 条，以后再说 1 条。先看「重点」就行。"


async def test_library_regeneration_preserves_authored_fields_and_unrelated_entries(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        await save_library_focus(session, book.id, focus())
        await save_library_rest(session, book.id, rest())
        character = await session.scalar(select(Character).where(Character.name == "楚风"))
        entry = await session.scalar(select(WorldEntry).where(WorldEntry.name == "武道境界"))
        character.source, character.abilities, character.notes = "author", "作者能力", "作者备注"
        entry.source, entry.content, entry.levels = "ai_edited", "作者等级", [{"name": "九重天", "text": "作者定义"}]
        unrelated = WorldEntry(book_id=book.id, name="作者条目", category="特殊规则", source="author", content="不要删")
        session.add(unrelated)
        await session.flush()
        await save_library_focus(
            session,
            book.id,
            focus(finger={"place": "角色卡片", "name": "楚风", "content": "不可追加", "one_line": "新能力"}),
        )
        await save_library_rest(session, book.id, rest())
        assert character.abilities == "作者能力" and character.notes == "作者备注"
        assert entry.content == "作者等级" and entry.levels == [{"name": "九重天", "text": "作者定义"}]
        assert await session.get(WorldEntry, unrelated.id) is unrelated
        assert len(list(await session.scalars(select(SettingSuggestion)))) == 1


async def test_outline_saves_tree_versions_names_and_preserves_first_chapters(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        # Alias resolution is across characters and world entries, not only literal names.
        session.add(Character(book_id=book.id, name="楚家家主", aliases=["楚雄"]))
        await session.flush()
        await save_outline(session, book.id, outline())
        setup = await load_new_setup(session, book.id)
        assert len(setup["outline"]["arcs"]) == 2
        assert setup["outline"]["arcs"][0]["planned"]
        assert not setup["outline"]["arcs"][1]["planned"]
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        units = list(await session.scalars(select(PlotUnit).order_by(PlotUnit.index)))
        assert [row.chapter_count for row in volumes] == [7, 10]
        assert [row.status for row in volumes] == ["approved", "planned"]
        assert all(row.target_node_id == volumes[0].target_node_id for row in volumes)
        chapter = Chapter(
            book_id=book.id,
            volume_id=volumes[0].id,
            unit_id=units[0].id,
            index=1,
            title="退婚之日",
            outline={"goal": "宣告决心"},
        )
        units[0].status = "outlined"
        session.add(chapter)
        await session.flush()
        await save_outline(session, book.id, outline())
        assert await session.get(Chapter, chapter.id) is not None
        assert (await load_new_setup(session, book.id))["outline_chapters"]["chapters"][0]["title"] == "退婚之日"
        suggestions = list(await session.scalars(select(SettingSuggestion)))
        assert len(suggestions) == 1 and suggestions[0].payload["entry"]["category"] == "特殊规则"
        kinds = set(await session.scalars(select(SettingVersion.target_type)))
        assert {"segment", "volume", "unit"} <= kinds
        changed = deepcopy(outline())
        changed["units"][0]["summary"] = "新的开局"
        await save_outline(session, book.id, changed)
        assert await session.scalar(select(Chapter.id).where(Chapter.id == chapter.id)) is None
        assert units[0].status == "planned"


async def test_outline_locked_omitted_nodes_and_units_remain_unchanged(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        await save_outline(session, book.id, outline())
        nodes = list(await session.scalars(select(StoryNode).order_by(StoryNode.position)))
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        units = list(await session.scalars(select(PlotUnit).order_by(PlotUnit.index)))
        nodes[1].status = "pinned"
        volumes[1].locked = True
        units[0].locked = True
        await session.flush()
        old_arc = (nodes[1].title, nodes[1].event, deepcopy(nodes[1].segment))
        revised = outline()
        revised["arcs"] = [{"title": "改名的篇", "text": "不许覆盖锁住篇", "planned": True}]
        revised["volumes"] = revised["volumes"][:1]
        revised["units"] = [{"title": "不许覆盖", "summary": "新的单元", "chapter_count": 9}]
        await save_outline(session, book.id, revised)
        assert (nodes[1].title, nodes[1].event, nodes[1].segment) == old_arc
        assert await session.get(Volume, volumes[1].id) is volumes[1] and volumes[1].title == "秦家"
        assert await session.get(PlotUnit, units[0].id) is units[0] and units[0].summary == "未婚妻上门，楚风立誓。"
        assert (await load_new_setup(session, book.id))["locked_names"] == ["青阳城篇", "秦家", "退婚"]


async def test_restart_removes_unwritten_outlines_but_preserves_authored_tree_and_links(sessionmaker):
    from app.models import Relationship
    from app.services.setup_store import reset_for_restart

    async with sessionmaker() as session:
        book = await new_book(session)
        await save_outline(session, book.id, outline())
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        units = list(await session.scalars(select(PlotUnit).order_by(PlotUnit.index)))
        written = Chapter(
            book_id=book.id,
            volume_id=volumes[0].id,
            unit_id=units[0].id,
            index=1,
            title="正文",
            content="作者已经写了正文",
            status="final",
        )
        planned = Chapter(book_id=book.id, volume_id=volumes[0].id, unit_id=units[1].id, index=2, title="未确认章纲")
        author = Character(book_id=book.id, name="作者角色", source="author")
        ai = Character(book_id=book.id, name="与作者角色相连", source="ai")
        discard = Character(book_id=book.id, name="丢弃旧角色", source="ai")
        parent = WorldEntry(book_id=book.id, name="作者地方的上级", category="世界与地图", source="ai")
        session.add_all([written, planned, author, ai, discard, parent])
        await session.flush()
        relation = Relationship(book_id=book.id, source_id=author.id, target_id=ai.id, kind="朋友")
        child = WorldEntry(
            book_id=book.id, name="作者地方", category="世界与地图", source="author", parent_id=parent.id
        )
        session.add_all([relation, child])
        await session.flush()
        book.setup_progress = {
            "pieces": {"concept": "confirmed", "world": "waiting", "segment": "waiting", "first_volume": "waiting"}
        }
        await reset_for_restart(session, book.id, keep_concept=True)
        assert await session.scalar(select(Chapter.id).where(Chapter.id == planned.id)) is None
        assert await session.scalar(select(PlotUnit.id).where(PlotUnit.id == units[1].id)) is None
        assert await session.scalar(select(Chapter.id).where(Chapter.id == written.id)) == written.id
        assert await session.scalar(select(Volume.id).where(Volume.id == volumes[0].id)) == volumes[0].id
        assert await session.scalar(select(PlotUnit.id).where(PlotUnit.id == units[0].id)) == units[0].id
        assert await session.scalar(select(Relationship.id).where(Relationship.id == relation.id)) == relation.id
        assert await session.scalar(select(Character.id).where(Character.id == discard.id)) is None
        assert await session.scalar(select(WorldEntry.parent_id).where(WorldEntry.id == child.id)) == parent.id
        assert book.concept == {"legacy": "旧键保留"} and book.setup_progress == {}


async def test_restart_retains_confirmed_volume_plan(sessionmaker):
    from app.services.setup_store import reset_for_restart

    async with sessionmaker() as session:
        book = await new_book(session)
        await save_outline(session, book.id, outline())
        book.setup_progress = {"pieces": {"segment": "confirmed", "first_volume": "waiting"}}
        await reset_for_restart(session, book.id, keep_concept=True)
        assert len(list(await session.scalars(select(Volume)))) == 2
        assert len(list(await session.scalars(select(PlotUnit)))) == 0
        assert len(list(await session.scalars(select(StoryNode)))) == 4


async def test_outline_new_name_resolves_existing_custom_category(sessionmaker):
    async with sessionmaker() as session:
        book = await new_book(session)
        session.add(SettingCategory(book_id=book.id, key="ghosts", name="厉鬼", style="paragraph"))
        await session.flush()
        draft = outline()
        draft["new_names"] = [{"category": "厉鬼", "name": "送信人", "one_line": "深夜送信的鬼"}]
        await save_outline(session, book.id, draft)
        suggestion = await session.scalar(select(SettingSuggestion).where(SettingSuggestion.book_id == book.id))
        assert suggestion.payload["entry"]["category"] == "custom:ghosts"
        assert suggestion.title == "大纲里出现了「送信人」，要给它建一条厉鬼吗？"
        await _apply_suggestion(session, suggestion)
        entry = await session.scalar(select(WorldEntry).where(WorldEntry.name == "送信人"))
        assert entry.category == "custom:ghosts" and entry.status == "one"


async def test_shared_chapter_planning_receives_new_story_and_unit_paragraph(sessionmaker):
    from app.services.writing_context import chapter_plan_blocks

    async with sessionmaker() as session:
        book = await new_book(session)
        await save_story_concept(session, book.id, concept())
        await save_library_focus(session, book.id, focus())
        await save_outline(session, book.id, outline())
        volume = await session.scalar(select(Volume).where(Volume.book_id == book.id, Volume.index == 1))
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == volume.id, PlotUnit.index == 1))
        blocks = await chapter_plan_blocks(session, book, volume, unit, 1)
        assert concept()["story"] in blocks["concept"]
        assert outline()["units"][0]["summary"] in blocks["unit"]
        assert outline()["volumes"][0]["summary"] in blocks["volume"]
        assert blocks["chapter_count"] == "3" and blocks["first_chapter"] == "1"


def test_new_paragraph_context_keeps_legacy_fields_unchanged():
    from app.agents.context import format_concept, format_unit

    old = format_concept({"title": "旧书", "logline": "旧的一句话", "selling_points": ["旧卖点"]})
    assert "一句话简介：旧的一句话" in old and "旧卖点" in old and "定调：" not in old
    old_unit = format_unit(
        {
            "index": 1,
            "title": "旧单元",
            "chapter_count": 3,
            "goal": "旧目标",
            "conflict": "旧冲突",
            "climax": "旧高潮",
            "outcome": "旧结果",
        }
    )
    assert old_unit == "单元1「旧单元」约 3 章\n目标：旧目标\n冲突：旧冲突\n高潮：旧高潮\n结果：旧结果\n关键事件："


async def test_outline_reordering_first_unit_clears_old_unwritten_chapters(sessionmaker):
    from app.services.writing_store import next_chapter_index

    async with sessionmaker() as session:
        book = await new_book(session)
        await save_outline(session, book.id, outline())
        volume = await session.scalar(select(Volume).where(Volume.book_id == book.id, Volume.index == 1))
        units = list(
            await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index))
        )
        session.add(Chapter(book_id=book.id, volume_id=volume.id, unit_id=units[0].id, index=1, title="旧第一单元章纲"))
        units[0].status = "outlined"
        await session.flush()
        draft = outline()
        draft["units"] = list(reversed(draft["units"]))
        await save_outline(session, book.id, draft)
        assert await session.scalar(select(Chapter.id).where(Chapter.book_id == book.id)) is None
        assert await next_chapter_index(session, book.id) == 1
        assert (await load_new_setup(session, book.id))["outline"]["units"][0]["title"] == "识宝"


async def test_first_arc_is_always_planned_even_if_model_flag_is_wrong(sessionmaker):
    from app.llm.demo_setup import outline
    from app.services.setup_store_v3 import save_outline

    async with sessionmaker() as session:
        book = Book(title="第一篇必须写细")
        session.add(book)
        await session.flush()
        draft = outline("").model_dump()
        draft["arcs"][0]["planned"] = False
        await save_outline(session, book.id, draft)
        nodes = list(
            await session.scalars(
                select(StoryNode)
                .where(StoryNode.book_id == book.id, StoryNode.kind == "milestone")
                .order_by(StoryNode.position)
            )
        )
        assert nodes[0].segment == {"title": draft["arcs"][0]["title"], "text": draft["arcs"][0]["text"]}
        assert all(node.segment is None for node in nodes[1:])


async def test_outline_swapping_volumes_restarts_new_first_volume_at_chapter_one(sessionmaker):
    from app.services.writing_store import create_chapters

    async with sessionmaker() as session:
        book = await new_book(session)
        await save_outline(session, book.id, outline())
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index)))
        first_unit = await session.scalar(
            select(PlotUnit).where(PlotUnit.volume_id == volumes[0].id, PlotUnit.index == 1)
        )
        await create_chapters(session, book.id, first_unit, [{"title": f"旧第{i}章"} for i in range(1, 4)])
        old_first_id, new_first_id = volumes[0].id, volumes[1].id
        draft = outline()
        draft["volumes"] = list(reversed(draft["volumes"]))
        await save_outline(session, book.id, draft)
        saved = await load_new_setup(session, book.id)
        assert saved["outline"]["volumes"][0]["id"] == str(new_first_id)
        assert saved["outline"]["volumes"][1]["id"] == str(old_first_id)
        assert await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == old_first_id)) is None
        assert await session.scalar(select(Chapter.id).where(Chapter.book_id == book.id)) is None
        new_unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == new_first_id, PlotUnit.index == 1))
        chapters = await create_chapters(session, book.id, new_unit, [{"title": "新的开篇"}])
        assert chapters[0].index == 1 and chapters[0].volume_id == new_first_id


async def test_outline_volume_swap_preserves_locked_and_written_units(sessionmaker):
    from app.services.writing_store import create_chapters

    async with sessionmaker() as session:
        for guard in ("locked_unit", "locked_volume", "written"):
            book = await new_book(session)
            await save_outline(session, book.id, outline())
            volume = await session.scalar(select(Volume).where(Volume.book_id == book.id, Volume.index == 1))
            unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == volume.id, PlotUnit.index == 1))
            chapter = (await create_chapters(session, book.id, unit, [{"title": "必须保留"}]))[0]
            if guard == "locked_unit":
                unit.locked = True
            elif guard == "locked_volume":
                volume.locked = True
            else:
                chapter.content, chapter.status = "作者已写正文", "final"
            await session.flush()
            draft = outline()
            draft["volumes"] = list(reversed(draft["volumes"]))
            await save_outline(session, book.id, draft)
            assert await session.scalar(select(Chapter.id).where(Chapter.id == chapter.id)) == chapter.id
            assert await session.scalar(select(PlotUnit.id).where(PlotUnit.id == unit.id)) == unit.id
            if guard == "written":
                assert chapter.content == "作者已写正文"
