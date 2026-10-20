"""七类设定的选材、逐字材料、章号和栏目，以及程序计算的 merits 事实。"""

import re
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event, select

from app.agents import schemas as s
from app.models import Book, Chapter, WorldEntry
from app.prompts import default_content
from app.services.teardown_facts import build_facts
from app.services.teardown_roster import Roster
from app.services.teardown_settings import SettingsWriter
from app.services.teardown_world import (
    KIND_RULES,
    WorldJob,
    count_occurrences,
    evenly,
    merge_world_overviews,
    prepare_world_jobs,
    resolve_place_parents,
    thing_line,
    world_context,
    world_rows,
)


def read(index, **values):
    return {"index": index, "people": [], "things": [], "moments": [], "waits": [], "tropes": [], **values}


async def test_world_counts_raw_text_per_name_and_keeps_three_rules(sessionmaker, monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    async with sessionmaker() as session:
        book = Book(title="原书", source="teardown")
        session.add(book)
        await session.flush()
        for index, text in enumerate(
            ("流云城中见一次茶碗，天玄大陆。", "流云城又见。", "一方隐居。", "流云城 茶碗"), 1
        ):
            session.add(Chapter(book_id=book.id, index=index, content=text))
        await session.commit()
        reads = [
            read(
                1,
                things=[
                    {"kind": "地方", "name": " 流云城 ", "note": "城", "belongs": "天玄大陆"},
                    {"kind": "地方", "name": "天玄大陆", "note": "大陆"},
                    {"kind": "地方", "name": "隐居地", "note": "一次"},
                    {"kind": "物品功法", "name": "茶碗", "note": "一次"},
                    {"kind": "金手指", "name": "天毒珠", "note": "珠"},
                    {"kind": "等级", "name": "初玄境", "note": "境界"},
                    {"kind": "秘密", "name": "身世", "note": "有疑"},
                    {"kind": "规矩", "name": "一", "note": "单字"},
                ],
            ),
            read(2, things=[{"kind": "规矩", "name": "一", "note": "又记"}]),
            read(4, things=[{"kind": "物品功法", "name": "茶碗", "note": "范围外"}]),
        ]
        statements = []

        def collect(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(session.bind.sync_engine, "before_cursor_execute", collect)
        try:
            jobs = await prepare_world_jobs(session, book, 3, reads, "云澈", [])
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", collect)
        assert {job.kind for job in jobs} == {"地方", "金手指", "等级", "秘密", "规矩"}
        place = next(job for job in jobs if job.kind == "地方")
        assert place.values["things"] == (
            "- 流云城（原文里出现过 2 章，第一次在第 1 章）：第 1 章：城（属于 天玄大陆）\n"
            "- 天玄大陆（原文里出现过 1 章，第一次在第 1 章）：第 1 章：大陆"
        )
        assert "隐居地" not in place.user
        assert "单字" in next(job.user for job in jobs if job.kind == "规矩")
        # 只有计数投影，一次一名；单字不查原文，范围外的记录不会进入模型材料。
        assert len(statements) == 7
        assert all(
            "count(chapters.id)" in statement and "strpos(chapters.content" in statement for statement in statements
        )
        assert all("chapters.content AS" not in statement for statement in statements)
        for job in jobs:
            assert job.values["kind_rule"] == KIND_RULES[job.kind]
            assert job.values["last"] == "3"


async def test_world_sixty_sorted_batches_short_name_counts_once_per_chapter(sessionmaker, monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    async with sessionmaker() as session:
        book = Book(title="原书", source="teardown")
        session.add(book)
        await session.flush()
        reads = [read(i, things=[{"kind": "秘密", "name": f"秘密{i}", "note": f"线索{i}"}]) for i in range(61, 0, -1)]
        jobs = await prepare_world_jobs(session, book, 61, reads, "主角", [])
        assert [job.key for job in jobs] == ["world:秘密:1", "world:秘密:2"]
        assert jobs[0].values["things"].count("\n") == 59
        assert jobs[0].values["things"].startswith("- 秘密1（")
        assert jobs[1].values["things"].startswith("- 秘密61（")
        assert await count_occurrences(session, book.id, "一", 61, [(1, {}), (1, {}), (2, {})]) == 2


def test_world_things_six_records_context_and_exact_rules():
    records = [(i, {"note": f"记录{i}", "belongs": "上级", "secret": "埋下"}) for i in range(1, 9)]
    assert thing_line("物件", 9, records) == (
        "- 物件（原文里出现过 9 章，第一次在第 1 章）："
        "第 1 章：记录1（属于 上级）（埋下）；第 2 章：记录2（属于 上级）（埋下）；第 3 章：记录3（属于 上级）（埋下）；"
        "……；第 6 章：记录6（属于 上级）（埋下）；第 7 章：记录7（属于 上级）（埋下）；第 8 章：记录8（属于 上级）（埋下）"
    )
    reads = [read(i, people=[{"name": "主角", "shown": "出场", "change": f"升{i}"}]) for i in range(1, 201)]
    context = world_context("等级", reads, "主角", [])
    assert context.startswith("主角各章的变化：\n- 第 1 章：升1\n")
    assert context.endswith("- 第 200 章：升200") and len(context.splitlines()) == 121
    assert world_context("等级", [], "主角", []) == "主角各章的变化：（没有）"
    assert (
        world_context("势力", [], "主角", [{"name": "张三", "belongs": "宗门"}, {"name": "李四", "belongs": ""}])
        == "角色卡上写的所属：\n- 张三：宗门"
    )
    assert world_context("势力", [], "主角", []) == "角色卡上写的所属：（没有）"
    assert world_context("地方", [], "主角", []) == ""
    assert len(KIND_RULES) == 7
    task = (Path(__file__).resolve().parents[2] / "docs/codex任务/拆书第三批/1-后台-拆设定和好在哪.md").read_text(
        encoding="utf-8"
    )
    expected = dict(re.findall(r"- (等级|金手指|地方|势力|物品功法|秘密|规矩)：「([^\n]+)」", task))
    assert expected == KIND_RULES


async def test_same_name_across_kinds_uses_raw_count_but_keeps_independent_notes(sessionmaker, monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)
    async with sessionmaker() as session:
        book = Book(title="同名原书", source="teardown", teardown={"names": {"红发少女": "茉莉"}})
        session.add(book)
        await session.flush()
        for index, content in enumerate(("青云门山门", "青云门来人", "青云门 青云门"), 1):
            session.add(Chapter(book_id=book.id, index=index, content=content))
        await session.commit()
        reads = [
            read(
                1,
                things=[
                    {"kind": "地方", "name": "青云门", "note": "山上建筑"},
                    {"kind": "势力", "name": "青云门", "note": "门派"},
                ],
            )
        ]
        jobs = await prepare_world_jobs(session, book, 2, reads, "茉莉", [{"name": "茉莉", "belongs": "青云门"}])
        place, faction = jobs
        assert place.kind == "地方" and faction.kind == "势力"
        assert place.values["things"] == "- 青云门（原文里出现过 2 章，第一次在第 1 章）：第 1 章：山上建筑"
        assert faction.values["things"] == "- 青云门（原文里出现过 2 章，第一次在第 1 章）：第 1 章：门派"
        assert faction.values["context"] == "角色卡上写的所属：\n- 茉莉：青云门"


def test_world_level_context_resolves_roster_alias_and_accepted_card_name():
    reads = [
        read(1, people=[{"name": "红发少女", "shown": "相识", "also_called": ["茉莉"], "change": "恢复"}]),
        read(
            2,
            people=[
                {"name": "茉莉", "shown": "身份揭开", "change": "授功"},
                {"name": "茉莉", "shown": "再出现", "change": "授功"},
            ],
        ),
    ]
    assert (
        world_context("等级", reads, "茉莉", [], names={"红发少女": "茉莉"})
        == "主角各章的变化：\n- 第 1 章：恢复\n- 第 2 章：授功"
    )


def test_split_world_overviews_merge_in_batch_order_without_last_result_overwrite():
    parts = {
        "world:地方:10": "遥远外域",
        "world:地方:2": "以金币交易",
        "world:地方:1": "超凡公开",
        "world:地方:3": "超凡公开",
        "world:地方:4": "",
    }
    assert merge_world_overviews(parts) == "超凡公开\n以金币交易\n遥远外域"
    assert merge_world_overviews({}) == ""
    assert merge_world_overviews({"world:地方:2": "超凡公开", "world:地方:1": "超凡公开"}) == "超凡公开"


async def test_writer_split_overview_survives_restart_and_incremental_batch_updates(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="分片原书", source="teardown")
        session.add(book)
        await session.commit()
        book_id = book.id

    async def cancelled():
        return False

    runner = SimpleNamespace(sm=sessionmaker, book_id=book_id, cancelled=cancelled)
    writer = SettingsWriter(runner, 100)

    def job(number):
        return WorldJob(
            f"world:地方:{number}", "地方", f"材料{number}", s.TeardownPlaces, {"title": "分片原书", "last": "100"}
        )

    # 并发的第二片先回来，第一片后回来，全文仍按批次排列、只存一条概况。
    await writer.world(job(2), s.TeardownPlaces(world="以金币交易"))
    await writer.world(job(1), s.TeardownPlaces(world="超凡公开"))
    async with sessionmaker() as session:
        overview = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book_id)))
        assert len(overview) == 1 and overview[0].content == "超凡公开\n以金币交易"

    # 模拟 worker 重启或接着拆：只有第二片有新记录，不能丢掉未调用的第一片。
    next_writer = SettingsWriter(runner, 200)
    await next_writer.world(job(2), s.TeardownPlaces(world="以灵石交易"))
    async with sessionmaker() as session:
        overview = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book_id)))
        current = await session.get(Book, book_id)
        assert len(overview) == 1 and overview[0].content == "超凡公开\n以灵石交易"
        assert current.teardown["settings"]["overviews"] == {"world:地方:1": "超凡公开", "world:地方:2": "以灵石交易"}
        # 作者手改后再有新片，概况整条受保护，不改作者正文。
        overview[0].content = "作者核订的世界概况"
        await session.commit()
    await next_writer.world(job(3), s.TeardownPlaces(world="有银币"))
    async with sessionmaker() as session:
        overview = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == book_id))
        assert overview.content == "作者核订的世界概况"
    assert next_writer.skipped == ["世界概况"]


def test_all_world_rows_columns_chapter_checks_and_world_overview():
    result = s.TeardownGoldfingers(
        items=[
            s.TeardownGoldfinger(
                name="珠",
                aliases=["宝珠", "宝珠"],
                what="珠子",
                knowers="主角",
                can="解毒",
                rules="限一次",
                cost="体力",
                grows="第 4 章吸毒",
                origin="不明",
                first_chapter=101,
            )
        ]
    )
    row = world_rows(result, "金手指", 100)[0]
    assert row.values == {
        "是什么": "珠子",
        "谁知道": "主角",
        "能做什么": "解毒",
        "规矩和限制": "限一次",
        "代价": "体力",
        "怎么变强": "第 4 章吸毒",
        "来历": "不明",
    }
    assert row.key == "entry:金手指:珠" and row.aliases == ["宝珠"] and row.created_chapter is None
    ladder = world_rows(
        s.TeardownLadders(
            ladders=[
                s.TeardownLadder(
                    name="境界",
                    how_up="苦修",
                    levels=[
                        s.TeardownLevel(name="初玄", note="初步", protagonist_chapter=5),
                        s.TeardownLevel(name="神玄", note="未知", protagonist_chapter=101),
                        s.TeardownLevel(name="凡", note="原点", protagonist_chapter=0),
                    ],
                )
            ]
        ),
        "等级",
        100,
    )[0]
    assert ladder.values == {"总说明": "苦修"} and ladder.category == "等级体系"
    assert ladder.levels == [
        {"name": "初玄", "text": "初步（主角第 5 章到）", "protagonist_chapter": 5},
        {"name": "神玄", "text": "未知", "protagonist_chapter": None},
        {"name": "凡", "text": "原点", "protagonist_chapter": None},
    ]
    places = world_rows(
        s.TeardownPlaces(
            world="公开修炼，以金币交易",
            items=[s.TeardownPlace(name="小城", aliases=["城"], parent="大陆", note="小城", first_chapter=1)],
        ),
        "地方",
        100,
    )
    assert places[0].category == "世界与地图" and places[0].values == {"内容": "小城"} and places[0].parent == "大陆"
    assert places[1].name == "世界概况" and places[1].values == {"内容": "公开修炼，以金币交易"}
    faction = world_rows(
        s.TeardownFactions(
            items=[
                s.TeardownFaction(
                    name="萧门",
                    note="家族",
                    leader="萧烈",
                    stance="友",
                    turf="流云城",
                    members=["云澈", "萧泠汐"],
                    first_chapter=2,
                )
            ]
        ),
        "势力",
        100,
    )[0]
    assert faction.category == "势力划分" and faction.values == {
        "领头的": "萧烈",
        "对主角": "友",
        "地盘": "流云城",
        "内容": "家族\n成员：云澈、萧泠汐",
    }
    item = world_rows(
        s.TeardownItems(items=[s.TeardownItem(name="剑", note="斩敌", grade="初级", holder="云澈", first_chapter=3)]),
        "物品功法",
        100,
    )[0]
    assert item.category == "物品与功法" and item.values == {"品阶": "初级", "在谁手里": "云澈", "内容": "斩敌"}
    rule = world_rows(
        s.TeardownRules(items=[s.TeardownRule(name="禁飞", note="城内禁飞", first_chapter=100)]), "规矩", 100
    )[0]
    assert rule.category == "特殊规则" and rule.values == {"内容": "城内禁飞"} and rule.created_chapter == 100


def test_secret_reveal_before_plant_cleared_and_missing_exact():
    result = s.TeardownSecrets(
        items=[
            s.TeardownSecret(name="身世", truth="真相", knowers="老人", planted_chapter=8, revealed_chapter=3),
            s.TeardownSecret(name="远古", truth="未知", planted_chapter=0, revealed_chapter=101),
            s.TeardownSecret(name="揭开", truth="已知", planted_chapter=1, revealed_chapter=2),
        ]
    )
    rows = world_rows(result, "秘密", 100)
    assert rows[0].category == "往事与秘密" and rows[0].values == {
        "谁知道": "老人",
        "打算何时揭开": "到第 100 章还没揭开",
        "内容": "真相\n第 8 章埋下",
    }
    assert rows[0].created_chapter == 8 and rows[1].created_chapter is None
    assert rows[1].values["内容"] == "未知" and rows[2].values["打算何时揭开"] == "第 2 章揭开"
    assert result.missing == ["身世：揭开的章号早于埋下，没写揭开"]
    world_rows(result, "秘密", 100)
    assert result.missing == ["身世：揭开的章号早于埋下，没写揭开"]


def test_place_tree_alias_unknown_and_cycles():
    places = world_rows(
        s.TeardownPlaces(
            items=[
                s.TeardownPlace(name="大陆", aliases=["大地"], note="大陆"),
                s.TeardownPlace(name="城", parent="大地", note="城"),
                s.TeardownPlace(name="院", parent="城", note="院"),
                s.TeardownPlace(name="孤岛", parent="未知", note="岛"),
                s.TeardownPlace(name="自环", parent="自环", note="循环"),
                s.TeardownPlace(name="甲", parent="乙", note="甲"),
                s.TeardownPlace(name="乙", parent="甲", note="乙"),
            ]
        ),
        "地方",
        100,
    )
    parents = resolve_place_parents(places)
    assert parents["entry:地点列表:大陆"] is None
    assert parents["entry:地点列表:城"] == "entry:地点列表:大陆"
    assert parents["entry:地点列表:院"] == "entry:地点列表:城"
    assert parents["entry:地点列表:孤岛"] is None and parents["entry:地点列表:自环"] is None
    assert parents["entry:地点列表:甲"] is None or parents["entry:地点列表:乙"] is None


def test_merits_facts_exact_format_program_counts_names_and_no_out_of_scope():
    reads = [
        read(
            1,
            summary="主角被逐",
            hook="悬念：出路",
            feel="憋屈",
            people=[{"name": "旧名", "shown": "少年", "change": "失势"}],
            waits=[{"action": "立下", "what": "复仇"}],
            tropes=["退婚", "退婚"],
            moments=[{"who": "旧名", "what": "立誓", "shows": "不服"}],
        ),
        read(
            2,
            hook="期待：反击",
            feel="憋屈",
            people=[{"name": "旧名", "shown": "少年", "change": "获珠"}],
            things=[{"kind": "金手指", "name": "天毒珠"}],
            tropes=["退婚"],
        ),
        read(
            3,
            hook="平收",
            feel="大爽",
            cool_point="打脸：反击",
            people=[{"name": "旧名", "shown": "少年", "change": "扬眉"}],
            waits=[{"action": "兑现", "what": "反击"}],
            moments=[{"who": "旧名", "what": "反击", "shows": "勇气"}],
        ),
        read(4, feel="平", things=[{"kind": "金手指", "name": "范围外"}]),
    ]
    roster = Roster()
    roster.add(reads)
    facts = build_facts(
        reads,
        [{"first": 1, "last": 3, "title": "退婚"}],
        [{"index": 1, "first": 1, "last": 4, "title": "还没收尾"}],
        roster,
        "旧名",
        {"旧名": "正式名"},
        3,
    )
    assert facts == (
        "读到第 3 章，共 3 章。\n主角：正式名。\n第 1 章摘要：主角被逐\n"
        "前三章的结尾钩子：第 1 章「悬念：出路」；第 2 章「期待：反击」；第 3 章「平收」\n"
        "金手指第一次出现：第 2 章「天毒珠」。\n第一次爽：第 3 章，看点「打脸：反击」。\n"
        "读者感觉（模型判的）：憋屈 2 章，平 0 章，爽 0 章，大爽 1 章。\n大爽在第 3 章。\n"
        "最长连着憋屈：第 1–2 章，2 章。\n单元：1 个，平均 3.0 章，最短 3 章，最长 3 章。\n"
        "各单元：第 1–3 章「退婚」\n卷：第 1 卷「还没收尾」第 1–3 章\n"
        "主角各章的变化：\n- 第 1 章：失势\n- 第 2 章：获珠\n- 第 3 章：扬眉\n"
        "读者在等的事（各章立下、提起、兑现的）：\n- 第 1 章立下：复仇\n- 第 3 章兑现：反击\n"
        "用过的桥段（用了几章、第一次在第几章）：退婚 2 章（第 1 章起）\n"
        "名场面最多的人：\n- 正式名（2 场）：第 1 章 立誓——不服；第 3 章 反击——勇气"
    )


def test_facts_even_limits_empty_and_gaps_do_not_invent_continuous_chapters():
    reads = [
        read(
            i,
            feel="憋屈",
            people=[{"name": "主角", "shown": "人", "change": f"变{i}"}],
            waits=[{"action": "提起", "what": f"等{i}"}],
        )
        for i in range(1, 201)
    ]
    roster = Roster()
    roster.add(reads)
    facts = build_facts(reads, [], [], roster, "主角", {}, 200)
    changes, waits = facts.split("主角各章的变化：\n")[1].split("读者在等的事（各章立下、提起、兑现的）：\n")
    assert len(changes.strip().splitlines()) == 80
    assert len(waits.split("用过的桥段")[0].strip().splitlines()) == 80
    assert "- 第 1 章：变1\n" in changes and changes.rstrip().endswith("- 第 200 章：变200")
    assert evenly(list(range(200)), 80)[-1] == 199
    gaps = build_facts([read(1, feel="憋屈"), read(3, feel="憋屈")], [], [], Roster(), "", {}, 3)
    assert "最长连着憋屈：第 1–1 章，1 章。" in gaps
    empty = build_facts([read(1, feel="平")], [], [], Roster(), "", {}, 1)
    assert "记录里没有金手指。" in empty and "没有憋屈的章。" in empty
    assert "主角各章的变化：\n（没有）" in empty and "第一次爽：" not in empty


def test_facts_aliases_chronology_trope_chapter_count_and_unknown_moment():
    reads = [
        read(
            1,
            summary="相见",
            feel="平",
            people=[{"name": "少女", "shown": "相识", "also_called": ["茉莉"], "change": "恢复"}],
            tropes=["相遇", "相遇"],
            moments=[
                {"who": "茉莉", "what": "现身", "shows": "神秘"},
                {"who": "不存在的人", "what": "凭空", "shows": "不该记"},
            ],
        ),
        read(2, feel="爽", people=[{"name": "茉莉", "shown": "少女", "change": "授功"}], tropes=["相遇"]),
        read(3, feel="大爽", tropes=["未读桥段"]),
    ]
    roster = Roster()
    roster.add(reads)
    facts = build_facts(
        reads,
        [
            {"first": 2, "last": 2, "title": "后"},
            {"first": 1, "last": 1, "title": "前"},
            {"first": 3, "last": 3, "title": "范围外"},
        ],
        [
            {"index": 2, "first": 2, "last": 3, "title": "还没收尾"},
            {"index": 1, "first": 1, "last": 1, "title": "卷首"},
        ],
        roster,
        "少女",
        {"少女": "茉莉"},
        2,
    )
    assert "主角：茉莉。" in facts
    assert "主角各章的变化：\n- 第 1 章：恢复\n- 第 2 章：授功" in facts
    assert "各单元：第 1–1 章「前」；第 2–2 章「后」" in facts
    assert "卷：第 1 卷「卷首」第 1–1 章；第 2 卷「还没收尾」第 2–2 章" in facts
    assert "相遇 2 章（第 1 章起）" in facts
    assert "- 茉莉（1 场）：第 1 章 现身——神秘" in facts
    assert "不存在的人" not in facts and "凭空" not in facts and "未读桥段" not in facts and "范围外" not in facts
