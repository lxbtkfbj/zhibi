"""下一篇的纯整理、事务保存、篇幅上下文及逐章 want 撤销。"""

from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.agents.context import format_next_segment
from app.agents.glossary import terms
from app.agents.schemas import ChapterDigest
from app.agents.setup_puzzle import normalize_volumes
from app.models import (
    Book,
    Chapter,
    Character,
    Foreshadowing,
    NodeAnchor,
    PlotUnit,
    Relationship,
    Secret,
    StoryNode,
    StoryThread,
    Volume,
)
from app.services.segment_planning import normalize_next_segment, segment_checks
from app.services.setup_store import load_nodes
from app.services.writing_context import (
    chapter_blocks,
    chapter_plan_blocks,
    segment_blocks,
    segment_lengths,
    volume_blocks,
)
from app.services.writing_store import apply_digest, revert_chapter, save_segment


def draft(ref=0):
    return {
        "carried": "E3 带进这一篇，查案时一并兑现。",
        "pursuit": "由洗清罪名升级为找出幕后主使。",
        "finger_next": "能读出三日前留下的记忆。",
        "answers": "幕后主使是掌门。",
        "map": "北境寒原",
        "new_map": {
            "name": "北境寒原",
            "powers": "守北军",
            "ceiling": "金丹",
            "rules": "宵禁",
            "start": "驿站",
            "gains": "卷宗",
        },
        "power": "元婴可远隔千里御剑。",
        "trouble": "关卡禁止出城。",
        "opponent": "守将要掩盖罪证，先封死所有出路。",
        "new_characters": [{"name": "苏晚晴", "role_type": "女主", "goal": "洗清家族罪名", "want": "今晚拿回账本"}],
        "relationships": [{"source": "林岚", "target": "苏晚晴", "kind": "伙伴", "description": "携手查案"}],
        "goal": "三日内找到旧卷宗。",
        "goal_link": "卷宗记着幕后主使的线索。",
        "wait": {
            "description": "当众洗清罪名",
            "plant_plan": "立下约定",
            "payoff_plan": "公堂对证",
            "plant_volume": 1,
            "payoff_volume": 99,
        },
        "reveal": "找出伪造命令的人，却发现他已经死了。",
        "secrets": [
            {
                "title": "北境旧案",
                "truth": "账本是伪造的",
                "knowers": ["苏晚晴", "不存在的人"],
                "reader_knows": "不知道",
            }
        ],
        "end": {
            "ref": ref,
            "title": "寒原追查",
            "event": "拿回卷宗，打败守将",
            "prerequisite": "查清密道",
            "consequence": "掌门的身份暴露",
            "volume": 3,
        },
        "ending": "主角揭穿掌门，重建门派。",
        "decisions": [],
        "remark": "从旧案自然接上北境。",
    }


def split_draft(start=2):
    return {
        "volumes": [
            {"index": start, "title": "北境来客", "chapter_count": 3, "want": "找到旧案线人", "target_node": 3},
            {"index": start + 1, "title": "寒原追查", "chapter_count": 3, "want": "拿回卷宗", "target_node": 3},
        ],
        "threads": [
            {
                "name": "旧案",
                "kind": "主线",
                "summary": "不覆盖已有概要",
                "characters": ["林岚"],
                "beats": [{"volume": start, "beat": "新线人"}, {"volume": start + 1, "beat": "取证"}],
            },
            {
                "name": "同盟",
                "kind": "感情线",
                "summary": "彼此信任",
                "characters": ["林岚", "苏晚晴"],
                "beats": [{"volume": start, "beat": "结盟"}],
            },
        ],
        "anchors": [
            {"character": "苏晚晴", "node": 3, "kind": "登场", "note": "共同取证"},
            {"character": "林岚", "node": 4, "kind": "转折", "note": "保留结局ID映射"},
        ],
    }


async def story(session):
    book = Book(
        title="下一篇",
        status="writing",
        concept={"target_length": 5.4},
        protagonist={"escalation": "先洗冤", "finger_later": "有限读取"},
        world={
            "power": "筑基",
            "mystery": "谁伪造卷宗？",
            "mystery_answer": "",
            "maps": [{"name": "青山镇"}],
            "far_maps": [{"name": "北境寒原", "line": "新线索"}, {"name": "王都", "line": "幕后"}],
        },
    )
    session.add(book)
    await session.flush()
    nodes = [
        StoryNode(book_id=book.id, position=1, kind="opening", title="遭诬", event="被追杀"),
        StoryNode(
            book_id=book.id,
            position=2,
            kind="milestone",
            title="离开青山镇",
            event="拿到线索",
            segment={
                "number": 1,
                "status": "confirmed",
                "planned_at": 0,
                "goal": "洗冤",
                "opening": {
                    "scene": "雨夜追杀",
                    "pressure": "被逐出宗门",
                    "first_win": "夺回证物",
                    "finger": "读取记忆",
                    "hook": "证物指向掌门",
                },
            },
        ),
        StoryNode(
            book_id=book.id,
            position=3,
            kind="ending",
            title="终局",
            event="打败幕后黑手",
            prerequisite="揭开真相",
            consequence="重建门派",
            origin="author",
        ),
    ]
    session.add_all(nodes)
    await session.flush()
    volume = Volume(
        book_id=book.id, index=1, title="青山镇", chapter_count=99, target_node_id=nodes[1].id, reaches_node=True
    )
    session.add(volume)
    await session.flush()
    units = [PlotUnit(book_id=book.id, volume_id=volume.id, index=i, title=f"单元{i}", chapter_count=3) for i in (1, 2)]
    protagonist = Character(book_id=book.id, name="林岚", role_type="主角", want="拿到考核资格")
    session.add_all(
        [
            *units,
            protagonist,
            Foreshadowing(book_id=book.id, seq=3, kind="期待", span="长", description="洗冤", status="planted"),
            Secret(book_id=book.id, seq=7, title="旧秘密", truth="不动"),
            StoryThread(
                book_id=book.id,
                index=1,
                name="旧案",
                kind="主线",
                summary="作者的概要",
                beats=[{"volume": 1, "beat": "旧线索"}],
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            Chapter(
                book_id=book.id, volume_id=volume.id, unit_id=units[0].id, index=i, title=f"第{i}章", status="final"
            )
            for i in (1, 2, 3)
        ]
    )
    await session.flush()
    return book, nodes, volume, units, protagonist


async def normalized(session, book, ref=0):
    nodes = await load_nodes(session, book.id)
    plan, notes = normalize_next_segment(
        draft(ref), nodes, [{"name": "林岚"}], lengths=await segment_lengths(session, book)
    )
    split, segment, split_notes = normalize_volumes(
        split_draft(),
        {"nodes": plan["nodes_view"], "expectations": [plan["wait"]]},
        [{"name": "林岚"}, *plan["new_characters"]],
        start=2,
        end_index=plan["end_index"],
    )
    plan["nodes_view"] = segment["nodes"]
    plan["end"]["volume"] = segment["nodes"][plan["end_index"] - 1].get("volume")
    plan["wait"] = segment["expectations"][0]
    return plan, split, [*notes, *split_notes]


@pytest.mark.parametrize(
    "ref,adopt,index",
    [(0, False, 3), (1, False, 3), (2, False, 3), (3, True, 3), (4, False, 3), (5, True, 5), (99, False, 3)],
)
def test_normalize_only_adopts_immediately_following_or_ending(ref, adopt, index):
    nodes = [
        {
            "id": str(i),
            "kind": "ending" if i == 5 else "milestone",
            "segment": {"number": 1} if i == 2 else None,
            "title": f"节点{i}",
        }
        for i in range(1, 6)
    ]
    raw = draft(ref)
    raw["new_characters"].append({"name": "林岚"})
    before = deepcopy(nodes)
    plan, notes = normalize_next_segment(raw, nodes, [{"name": "林岚"}], lengths={"last_one": True})
    assert bool(plan["adopt"]) is adopt and plan["end_index"] == index
    assert nodes == before
    assert len(plan["new_characters"]) == 1
    assert plan["wait"]["node"] == index and plan["wait"]["kind"] == "期待" and plan["wait"]["span"] == "长"
    assert [person["name"] for person in plan["secrets"][0]["knowers"]] == ["苏晚晴"]
    assert any(item["question"] == "people" for item in notes)
    assert any(item["text"] == "篇幅只够一篇了，这一篇的终点应该是结局。" for item in notes) is (ref != 5)
    if adopt:
        assert plan["adopt"]["node_id"] == str(ref)
    elif ref:
        assert any(item["text"] == "终点引用的节点不是紧接着的远景节点，已改为新起一个。" for item in notes)


def test_checks_use_exact_expectation_codes_and_required_messages():
    plan = draft()
    plan.update(carried="处理 E30，不是另一条。", answers="", finale=True, new_map=None)
    warnings, flags = segment_checks(
        plan,
        {},
        {},
        [{"seq": 3, "kind": "期待", "status": "planted", "description": "洗冤"}],
        [{"kind": "ending", "status": "pinned"}],
        [{"question": "end", "text": "整理说明"}],
    )
    assert flags["carried"] == ["E3「洗冤」还开着，这一篇没说怎么处理。"]
    assert "快写完了，核心谜团还没定谜底。" in warnings
    assert "换到了新地图「北境寒原」，但还没写这张地图的详情。" in warnings
    assert flags["direction"] == ["结局是锁住，新的结局方向没有采用。"]
    assert flags["end"] == ["整理说明"]
    assert flags["volumes"] == ["这一篇还没有分卷。"]
    plan["carried"] = "接续 E3。"
    warnings, _ = segment_checks(
        plan, {}, {"mystery_answer": "已有答案"}, [{"seq": 3, "kind": "期待", "status": "planted"}], []
    )
    assert not any("还开着" in item or "还没定谜底" in item for item in warnings)


def test_format_next_segment_exact_order_and_current_full_content():
    plan, _ = normalize_next_segment(draft(), [{"segment": {"number": 1}}], [{"name": "林岚"}])
    text = format_next_segment(plan)
    labels = [
        "上一篇留下的线头",
        "主角的追求",
        "金手指下一阶段",
        "定下的谜底",
        "地图：",
        "新地图「",
        "力量规则往上",
        "开头的小麻烦",
        "大对手",
        "新登场的人物",
        "这一篇的目标",
        "读者在等",
        "这一篇揭开什么",
        "新的信息差",
        "终点：节点",
        "结局方向",
    ]
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "此刻想要今晚拿回账本" in text and "（新起）发生：拿回卷宗" in text


@pytest.mark.parametrize(
    "length,total,suffix",
    [
        (0, 0, "按正常的一篇来规划。"),
        (30, 100, "篇幅还宽裕，按正常的一篇来规划。"),
        (5.4, 18, "只够两篇左右"),
        (3.6, 12, "只够一篇了"),
    ],
)
async def test_lengths_count_units_use_book_words_and_exact_length_modes(sessionmaker, length, total, suffix):
    async with sessionmaker() as session:
        book, _, _, _, _ = await story(session)
        book.concept = {"target_length": length, "chapter_words": 6000}
        book.settings = {**book.settings, "chapter_words": 3000}
        lengths = await segment_lengths(session, book)
        assert lengths["planned_so_far"] == 6 and lengths["avg"] == 6 and lengths["planned_total"] == total
        assert lengths["final_chapters"] == 3 and lengths["next_volume"] == 2
        assert suffix in lengths["text"]
        assert lengths["volume_hint"].startswith("卷号从第 2 卷开始（前面已经规划了 1 卷、约 6 章）。")
        if not length:
            assert lengths["text"] == "这本书没有定全书篇幅。\n按正常的一篇来规划。"
            assert "全书计划" not in lengths["volume_hint"]


async def test_segment_context_and_opening_only_first_unit(sessionmaker):
    async with sessionmaker() as session:
        book, _, volume, units, _ = await story(session)
        blocks = await segment_blocks(session, book)
        assert "终点：节点 2「离开青山镇」：拿到线索\n这一篇写了第 1-1 卷。" in blocks["last_segment"]
        assert "此刻想要：拿到考核资格" in blocks["characters"]
        assert "E3" in blocks["ledger"] and "S7" in blocks["secrets"]
        assert blocks["revision"] == ""
        first = await chapter_plan_blocks(session, book, volume, units[0], 1)
        second = await chapter_plan_blocks(session, book, volume, units[1], 4)
        assert "雨夜追杀" in first["opening"] and second["opening"] == ""
        volume.index = 2
        assert (await chapter_plan_blocks(session, book, volume, units[0], 7))["opening"] == ""


async def test_penultimate_finale_segment_still_has_future_volumes(sessionmaker):
    async with sessionmaker() as session:
        book, nodes, volume, _, _ = await story(session)
        nodes[1].segment = {**nodes[1].segment, "finale": True}
        assert "下一卷：无（后面的卷写到再定）" in (await volume_blocks(session, book, volume))["neighbors"]
        nodes[-1].segment = {"number": 2, "finale": True}
        volume.target_node_id = nodes[-1].id
        assert "下一卷：无（这是最后一卷）" in (await volume_blocks(session, book, volume))["neighbors"]


async def test_save_segment_all_ten_parts_are_incremental_and_idempotent(sessionmaker):
    async with sessionmaker() as session:
        book, nodes, _, _, _ = await story(session)
        plan, split, _ = await normalized(session, book)
        stats = await save_segment(session, book, plan, split, number=2, pin_end=True)
        assert stats["volumes"] == 2 and stats["chapters"] == 6 and stats["new_characters"] == stats["new_secrets"] == 1
        saved_nodes = list(
            await session.scalars(select(StoryNode).where(StoryNode.book_id == book.id).order_by(StoryNode.position))
        )
        endpoint = saved_nodes[2]
        assert [node.id for node in saved_nodes[:2]] == [node.id for node in nodes[:2]]
        assert (
            endpoint.segment["number"] == 2
            and endpoint.segment["planned_at"] == 3
            and endpoint.segment["opening"] is None
        )
        assert endpoint.status == "pinned" and endpoint.origin == "ai"
        assert saved_nodes[-1].id == nodes[-1].id and saved_nodes[-1].event == plan["ending"]
        assert [item["name"] for item in book.world["maps"]] == ["青山镇", "北境寒原"]
        assert book.world["far_maps"] == [{"name": "王都", "line": "幕后"}]
        assert book.world["power"] == "筑基\n（第 2 段）元婴可远隔千里御剑。"
        assert book.world["mystery_answer"] == plan["answers"]
        assert book.protagonist["escalation"] == "先洗冤\n第 2 段：" + plan["pursuit"]
        assert book.protagonist["finger_later"] == "有限读取\n第 2 段：" + plan["finger_next"]
        person = await session.scalar(select(Character).where(Character.name == "苏晚晴"))
        assert person.want == "今晚拿回账本"
        assert await session.scalar(select(func.count(Relationship.id))) == 1
        new_secret = await session.scalar(select(Secret).where(Secret.seq == 8))
        assert new_secret.node_id == endpoint.id and [item["name"] for item in new_secret.knowers] == ["苏晚晴"]
        expectation = await session.scalar(select(Foreshadowing).where(Foreshadowing.seq == 4))
        assert expectation.node_id == endpoint.id and expectation.kind == "期待" and expectation.span == "长"
        assert expectation.plant_volume == 2 and expectation.payoff_volume == 3
        volumes = list(await session.scalars(select(Volume).where(Volume.index > 1).order_by(Volume.index)))
        assert [volume.index for volume in volumes] == [2, 3] and [volume.reaches_node for volume in volumes] == [
            False,
            True,
        ]
        assert all(volume.target_node_id == endpoint.id and volume.status == "planned" for volume in volumes)
        assert volumes[0].thread_beats == [{"thread": "旧案", "beat": "新线人"}, {"thread": "同盟", "beat": "结盟"}]
        thread = await session.scalar(select(StoryThread).where(StoryThread.name == "旧案"))
        assert thread.summary == "作者的概要" and [beat["volume"] for beat in thread.beats] == [1, 2, 3]
        anchors = list(await session.scalars(select(NodeAnchor).order_by(NodeAnchor.created_at)))
        assert {anchor.node_id for anchor in anchors} == {endpoint.id, nodes[-1].id}
        assert any(anchor.character_id == person.id and anchor.node_id == endpoint.id for anchor in anchors)
        before = deepcopy(book.protagonist)
        again = await save_segment(session, book, plan, split, number=2)
        assert again["already_saved"] and book.protagonist == before
        assert await session.scalar(select(func.count(Volume.id))) == 3
        assert await session.scalar(select(func.count(Foreshadowing.id))) == 2


@pytest.mark.parametrize("change", ["unchanged", "pinned", "author_changed", "deleted"])
async def test_adopted_endpoint_rechecks_current_author_version(sessionmaker, change):
    async with sessionmaker() as session:
        book, nodes, _, _, _ = await story(session)
        plan, split, _ = await normalized(session, book, ref=3)
        plan["ending"] = ""
        original_id = nodes[-1].id
        if change == "pinned":
            nodes[-1].status = "pinned"
        elif change == "author_changed":
            nodes[-1].event = "作者等待时改的新结局"
        elif change == "deleted":
            await session.delete(nodes[-1])
        await session.flush()
        stats = await save_segment(session, book, plan, split, number=2, status="auto")
        endpoint = await session.scalar(select(StoryNode).where(StoryNode.segment["number"].as_integer() == 2))
        assert endpoint.segment["status"] == "auto" and endpoint.segment["finale"] is True
        if change == "deleted":
            assert endpoint.id != original_id and endpoint.kind == "milestone" and endpoint.position == 3
        else:
            assert endpoint.id == original_id and endpoint.origin == "author"
        if change == "pinned":
            assert endpoint.event == "打败幕后黑手" and endpoint.status == "pinned"
        elif change == "author_changed":
            assert endpoint.event == "作者等待时改的新结局" and stats["preserved_end"]
        else:
            assert endpoint.event == plan["end"]["event"]


async def test_save_keeps_existing_answer_and_rolls_back_as_a_single_transaction(sessionmaker):
    async with sessionmaker() as session:
        book, _, _, _, _ = await story(session)
        book.world = {**book.world, "mystery_answer": "作者早已确定的答案"}
        await session.commit()
        book_id = book.id
        plan, split, _ = await normalized(session, book)
        await save_segment(session, book, plan, split, number=2)
        assert book.world["mystery_answer"] == "作者早已确定的答案"
        await session.rollback()
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert len(book.world["maps"]) == 1
        for model, expected in (
            (StoryNode, 3),
            (Volume, 1),
            (Character, 1),
            (Secret, 1),
            (Foreshadowing, 1),
            (Relationship, 0),
            (NodeAnchor, 0),
            (StoryThread, 1),
        ):
            assert await session.scalar(select(func.count(model.id))) == expected


async def test_waiting_snapshot_is_refreshed_after_another_session_edits(sessionmaker):
    async with sessionmaker() as writer:
        book, nodes, _, _, _ = await story(writer)
        await writer.commit()
        plan, split, _ = await normalized(writer, book, ref=3)
        plan["ending"] = "不要盖掉作者刚改的结局"
        async with sessionmaker() as author:
            current = await author.get(StoryNode, nodes[-1].id)
            current.event = "作者在地图里亲自改的结局"
            current_book = await author.get(Book, book.id)
            current_book.world = {**current_book.world, "mystery_answer": "作者在等待期间定下的谜底"}
            await author.commit()
        assert nodes[-1].event == "打败幕后黑手"  # writer 的身份映射仍然是旧快照
        stats = await save_segment(writer, book, plan, split, number=2)
        assert stats["preserved_end"]
        assert nodes[-1].event == "作者在地图里亲自改的结局"
        assert book.world["mystery_answer"] == "作者在等待期间定下的谜底"


async def test_want_digest_log_revert_and_later_chapter_protection(sessionmaker):
    async with sessionmaker() as session:
        book, _, _, _, person = await story(session)
        chapter = await session.scalar(select(Chapter).where(Chapter.index == 3))
        digest = ChapterDigest(
            summary="拿到资格", remark="状态已更新", character_updates=[{"name": "林岚", "want": "查清师兄的死因"}]
        )
        await apply_digest(session, book.id, chapter, digest)
        change = chapter.bible_changes["characters"][0]
        assert change["before"]["want"] == "拿到考核资格" and change["after"]["want"] == "查清师兄的死因"
        assert "此刻想要：查清师兄的死因" in (await chapter_blocks(session, book, chapter))["characters"]
        await revert_chapter(session, book.id, chapter)
        assert person.want == "拿到考核资格"
        await apply_digest(session, book.id, chapter, digest)
        later = Chapter(book_id=book.id, index=4, status="final")
        session.add(later)
        await session.flush()
        await apply_digest(
            session,
            book.id,
            later,
            ChapterDigest(summary="查到线索", remark="更新", character_updates=[{"name": "林岚", "want": "赶到北境"}]),
        )
        await revert_chapter(session, book.id, chapter)
        assert person.want == "赶到北境"
        await apply_digest(session, book.id, chapter, digest)
        assert person.want == "赶到北境" and chapter.bible_changes["characters"] == []


@pytest.mark.parametrize("adopt", [False, True])
async def test_endpoint_editorial_metadata_new_saved_existing_author_preserved(sessionmaker, adopt):
    async with sessionmaker() as session:
        book, nodes, _, _, _ = await story(session)
        known = [name for name, _ in terms()]
        nodes[-1].editor_note = "作者亲写的批注"
        nodes[-1].techniques = [known[-1]]
        plan, split, _ = await normalized(session, book, ref=3 if adopt else 0)
        plan["end"].update(editor_note="通过公开对质兑现期待", techniques=[known[0], "不在术语表", known[0]])
        await save_segment(session, book, plan, split, number=2)
        endpoint = await session.scalar(select(StoryNode).where(StoryNode.book_id == book.id, StoryNode.position == 3))
        assert endpoint.editor_note == ("作者亲写的批注" if adopt else "通过公开对质兑现期待")
        assert endpoint.techniques == ([known[-1]] if adopt else [known[0]])
