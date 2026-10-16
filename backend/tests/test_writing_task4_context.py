"""第一包任务 4：信息差上下文、期待原文与卷纲程序检查。"""

from app.agents.planning import expectation_issues, relevant_ledger, schedule_issues
from app.models import Book, Chapter, Character, PlotUnit, Secret, StoryNode, Volume
from app.services.writing_context import (
    chapter_blocks,
    chapter_plan_blocks,
    foreshadow_tasks,
    material_blocks,
    writer_secrets,
)


def secret(seq, *, names=(), truth="不涉及出场人物", status="hidden", **extra):
    return {
        "seq": seq,
        "title": f"秘密{seq}",
        "truth": truth,
        "knowers": [{"name": name, "since_chapter": None} for name in names],
        "reader_knows": "知道",
        "status": status,
        **extra,
    }


def test_writer_secret_selection_and_reveal_format():
    rows = [
        secret(1, names=["林岚"]),
        secret(2, truth="柳如烟是来寻找钥匙的人"),
        secret(3),
        secret(4, names=["林岚"], status="public"),
        secret(5),
    ]
    text = writer_secrets(rows, ["林岚", "柳如烟", "赵无极"], [{"ref": "S3", "to": "柳如烟", "how": "看穿伪装"}])
    assert text.startswith("【本章的信息差】")
    assert all(f"S{index}「" in text for index in (1, 2, 3))
    assert all(f"S{index}「" not in text for index in (4, 5))
    assert "知道的人：林岚（开书时）；本章出场但还不知道：柳如烟、赵无极" in text
    assert "真相：柳如烟是来寻找钥匙的人" in text
    assert "本章揭晓：S3 揭给 柳如烟——看穿伪装" in text
    assert "不知道的人不能说出、想到或按这些信息行动" in text
    assert writer_secrets([secret(1)], ["林岚"], []) == ""


def test_writer_secret_limit_prioritizes_this_chapter_reveals():
    rows = [secret(index, names=["林岚"]) for index in range(1, 12)]
    text = writer_secrets(rows, ["林岚"], [{"ref": "S11", "to": "读者", "how": "揭开真相"}])
    assert text.count("（读者：") == 8
    assert "S11「秘密11」" in text and "本章揭晓：S11" in text
    assert "S8「" not in text


async def writing_fixture(session):
    book = Book(idea="测试信息差", settings={"playbook": "harem_xuanhuan"})
    session.add(book)
    await session.flush()
    node = StoryNode(book_id=book.id, position=1, kind="milestone", title="本卷目标", status="pencil")
    session.add(node)
    await session.flush()
    volume = Volume(
        book_id=book.id, index=1, title="本卷", target_node_id=node.id, new_characters=["柳如烟（商会掌柜）"]
    )
    session.add(volume)
    await session.flush()
    unit = PlotUnit(
        book_id=book.id,
        volume_id=volume.id,
        index=1,
        title="拍卖会",
        key_events=["赵无极前来试探"],
        reveals=[{"ref": "S4", "to": "读者", "how": "展示暗室"}],
    )
    characters = [
        Character(book_id=book.id, name="林岚", role_type="主角", aliases=["小岚"]),
        Character(book_id=book.id, name="赵无极", role_type="配角"),
        Character(book_id=book.id, name="柳如烟", role_type="配角"),
        Character(book_id=book.id, name="段长老", role_type="配角"),
    ]
    session.add_all([unit, *characters])
    await session.flush()
    chapter = Chapter(
        book_id=book.id,
        volume_id=volume.id,
        unit_id=unit.id,
        index=1,
        title="竞价",
        outline={"characters": ["小岚"], "reveals": [{"ref": "S4", "to": "读者", "how": "展示暗室"}]},
        materials={"characters": ["柳如烟"]},
    )
    session.add(chapter)
    await session.flush()
    return book, volume, unit, chapter, node


async def test_chapter_plan_context_selects_secrets_by_knower_reveal_or_target(sessionmaker):
    async with sessionmaker() as session:
        book, volume, unit, chapter, node = await writing_fixture(session)
        rows = [
            secret(1, names=["林岚"]),
            secret(2, names=["赵无极"]),
            secret(3, names=["柳如烟"]),
            secret(4),
            secret(5, node_id=node.id),
            secret(6, truth="林岚这个名字只在真相里，章纲阶段不算相关"),
            secret(7, names=["林岚"], status="public"),
            secret(8, names=["段长老"]),
        ]
        session.add_all([Secret(book_id=book.id, **row) for row in rows])
        await session.flush()
        blocks = await chapter_plan_blocks(session, book, volume, unit, 1)
        assert all(f"S{index}「" in blocks["secrets"] for index in (1, 2, 3, 4, 5))
        assert all(f"S{index}「" not in blocks["secrets"] for index in (6, 7, 8))
        assert blocks["revision"] == ""
        assert "最多 3 章" in blocks["rhythm"] and "三分之一" in blocks["rhythm"]
        assert "本单元开始时没有开着的中长线期待" in blocks["ledger"]
        chapter_context = await chapter_blocks(session, book, chapter)
        # 列表版保留全部编号，写手版只给章纲与备资料点名的人物相关秘密。
        assert all(f"S{index}「" in chapter_context["secrets"] for index in range(1, 9))
        assert all(f"S{index}「" in chapter_context["secrets_for_writer"] for index in (1, 3, 4, 6))
        assert all(f"S{index}「" not in chapter_context["secrets_for_writer"] for index in (2, 5, 7, 8))
        assert "知道的人：林岚（开书时）" in chapter_context["secrets_for_writer"]
        # 截断时本单元揭晓仍优先，且总数最多 10 条。
        session.add_all([Secret(book_id=book.id, **secret(index, names=["林岚"])) for index in range(9, 22)])
        await session.flush()
        limited = await chapter_plan_blocks(session, book, volume, unit, 1)
        assert limited["secrets"].count("［隐藏") == 10 and "S4「" in limited["secrets"]


async def test_material_secret_priority_and_empty_context(sessionmaker):
    async with sessionmaker() as session:
        book, _, _, chapter, _ = await writing_fixture(session)
        empty = await chapter_blocks(session, book, chapter)
        assert empty["secrets"] == "（暂无）" and empty["secrets_for_writer"] == ""
        rows = [secret(index) for index in range(1, 24)]
        rows[21] = secret(22, truth="林岚曾亲手封住这扇门")
        rows[22] = secret(23, names=["林岚"])
        rows.append(secret(24, names=["林岚"], status="public"))
        session.add_all([Secret(book_id=book.id, **row) for row in rows])
        await session.flush()
        blocks = await material_blocks(session, book, chapter)
        assert blocks["secrets"].count("［隐藏") == 20
        assert blocks["secrets"].index("S22「") < blocks["secrets"].index("S1「")
        assert blocks["secrets"].index("S23「") < blocks["secrets"].index("S1「")
        assert "S24「" not in blocks["secrets"] and "S21「" not in blocks["secrets"]


async def test_expectation_tasks_all_actions_have_required_text_and_original_excerpt(sessionmaker):
    async with sessionmaker() as session:
        book = Book(idea="三年之约")
        session.add(book)
        await session.flush()
        session.add_all(
            [
                Chapter(
                    book_id=book.id, index=1, title="立约", content="林岚说，三年之约就在山门见。柳如烟记住了这一幕。"
                ),
                Chapter(book_id=book.id, index=5, title="提醒", content="三年之约只剩下十天，山门前的榜文已经贴上了。"),
            ]
        )
        await session.flush()
        ledger = [
            {
                "seq": 3,
                "kind": "期待",
                "description": "三年之约",
                "plant_plan": "山门立约",
                "payoff_plan": "提前十天胜过对手",
                "status": "planted",
                "planted_chapter": 1,
                "hint_chapters": [5],
            }
        ]
        output = {}
        for action in ("埋下", "提醒", "回收"):
            output[action] = await foreshadow_tasks(session, book.id, ledger, [{"ref": "E3", "action": action}], 8)
            assert output[action].startswith("【本章要处理的伏笔和期待】")
        assert "立下E3" in output["埋下"] and "立法：山门立约" in output["埋下"]
        assert "写清楚让读者开始期待的那一幕（约定、狠话、倒计时）" in output["埋下"]
        assert "让角色或旁人自然地提起，让读者想起还在等这件事。" in output["提醒"]
        assert "第1章《立约》（立下）原文" in output["提醒"]
        assert "兑现E3" in output["回收"] and "兑现方式：提前十天胜过对手" in output["回收"]
        assert "第1章《立约》（立下）原文" in output["回收"] and "第5章《提醒》（提醒）原文" in output["回收"]
        assert "兑现要超出读者的预期：比读者以为的更大、更快，或者换个角度。" in output["回收"]
        assert await foreshadow_tasks(session, book.id, ledger, [{"ref": "F3", "action": "回收"}], 8) == ""


def expectation(seq=3, **extra):
    return {
        "seq": seq,
        "kind": "期待",
        "status": "planted",
        "span": "中",
        "description": "三年之约",
        "planted_chapter": 1,
        **extra,
    }


def test_volume_expectation_issues_separate_required_and_advisory():
    units = [{"index": 1}, {"index": 2}]
    ledger = [
        expectation(payoff_volume=2),
        expectation(4, status="planned", plant_volume=2),
        expectation(5, status="resolved", payoff_volume=2),
    ]
    found = expectation_issues(units, [], ledger, 2, 30)
    errors = [item["problem"] for item in found if item["severity"] == "medium"]
    hints = [item["problem"] for item in found if item["severity"] == "low"]
    assert any("E3" in text and "兑现" in text for text in errors)
    assert any("E4" in text and "立下" in text for text in errors)
    assert any("已经 29 章没提" in text for text in errors)
    assert not any("E5" in text for text in errors)
    assert hints == ["第 1 个单元没有任何期待动作", "第 2 个单元没有任何期待动作"]
    assert all(item["aspect"] == "expectation" for item in found)


def test_volume_expectation_threshold_valid_actions_and_new_plans():
    units = [{"index": 1, "foreshadow_actions": [{"ref": "E3", "action": "提醒"}]}]
    assert expectation_issues(units, [], [expectation()], 2, 30) == []
    units[0]["foreshadow_actions"] = [{"ref": "F3", "action": "提醒"}]
    assert any(item["severity"] == "medium" for item in expectation_issues(units, [], [expectation()], 2, 30))
    for span, first, overdue in (("中", 21, False), ("中", 22, True), ("长", 51, False), ("长", 52, True)):
        found = expectation_issues([{"index": 1}], [], [expectation(span=span)], 2, first)
        assert any(item["severity"] == "medium" for item in found) is overdue
    assert expectation_issues([{"index": 1}], [{"plant_unit": 1, "payoff_unit": 1, "span": "中"}], [], 2, 30) == []
    found = expectation_issues([{"index": 1}], [], [], 2, 30)
    assert all(item["severity"] == "low" for item in found)
    assert any("没有开着的中长线期待" in item["problem"] for item in found)


def test_past_due_unresolved_expectation_stays_in_volume_and_chapter_context():
    item = expectation(payoff_volume=1)
    assert relevant_ledger([item], 3) == [item]
    assert relevant_ledger([{**item, "status": "resolved"}], 3) == []
    assert relevant_ledger([{**item, "status": "abandoned"}], 3) == []


def test_foreshadow_schedule_does_not_accept_expectation_prefix_with_same_number():
    ledger = [{"seq": 3, "kind": "伏笔", "status": "planned", "plant_volume": 2}]
    invalid = [{"index": 1, "foreshadow_actions": [{"ref": "E3", "action": "埋下"}]}]
    assert len(schedule_issues(invalid, [], ledger, 2)) == 1
    valid = [{"index": 1, "foreshadow_actions": [{"ref": " f3 ", "action": "埋下"}]}]
    assert schedule_issues(valid, [], ledger, 2) == []
