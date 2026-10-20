"""合并同一个人、旧卡保护、稳定归属和拆书角色顺序。"""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app.agents import schemas as s
from app.models import Book, Character, Relationship
from app.prompts import render
from app.services.teardown_merge import collect_merge, estimate_calls, merge_batches, merge_material, valid_groups
from app.services.teardown_settings import collect_settings, people_of, text_hash, write_positions
from tests.test_teardown_settings import StubRunner, person, read, setup_book


def test_merge_material_exact_and_one_chapter_has_one_note():
    roster, _, _ = people_of(
        [
            read(1, [person("少年", "初见" + "字" * 70, also_called=["小云", "阿云"]), person("路人", "只有一句")]),
            read(2, [person("云澈", "最后的模样", was="少年")]),
        ]
    )
    assert merge_material(roster) == (
        "【云澈】出场 2 章（第 1–2 章）；别的叫法：小云、少年、阿云；第 1 章："
        + ("初见" + "字" * 70)[:60]
        + "；第 2 章：最后的模样\n【路人】出场 1 章（第 1–1 章）；别的叫法：没有；第 1 章：只有一句"
    )
    one, _, _ = people_of([read(1, [person("甲", "第一句"), person("甲", "同章第二句")])])
    assert merge_material(one).endswith("第 1 章：第一句")
    sparse, _, _ = people_of([read(1, [person("甲", "")]), read(2, [person("甲", "唯一非空")])])
    assert merge_material(sparse).endswith("；第 2 章：唯一非空")
    assert merge_material(sparse).count("唯一非空") == 1


def test_merge_validation_casefold_whitespace_and_bad_groups():
    roster, _, _ = people_of([read(1, [person("Alpha"), person("Beta"), person("Gamma")])])
    result = s.TeardownMerge(
        groups=[
            s.TeardownMergeGroup(names=[" ALPHA ", " beta "], keep=" BETA ", why="第 1 章揭开身份"),
            s.TeardownMergeGroup(names=["Alpha"], keep="Alpha", why="太少"),
            s.TeardownMergeGroup(names=["Alpha", "Beta"], keep="Gamma", why="不在组里"),
            s.TeardownMergeGroup(names=["Alpha", "不在名单"], keep="Alpha", why="无名"),
            s.TeardownMergeGroup(names=["Alpha", " alpha "], keep="Alpha", why="重复不算两人"),
        ]
    )
    assert valid_groups(result, roster) == [{"names": ["Alpha", "Beta"], "keep": "Beta", "why": "第 1 章揭开身份"}]


async def test_merge_batches_transitive_and_unchanged_cache(sessionmaker):
    people = [person(f"人{i:03}") for i in range(271)]
    book_id = await setup_book(sessionmaker, [read(1, people)])
    roster, _, _ = people_of([read(1, people)])
    batches = merge_batches(roster.people)
    assert [len(batch) for batch in batches] == [150, 150, 31]
    assert batches[0][-30:] == batches[1][:30] and batches[1][-30:] == batches[2][:30]
    responses = iter(
        [
            s.TeardownMerge(groups=[s.TeardownMergeGroup(names=["人125", "人126"], keep="人125", why="第 1 章认出")]),
            s.TeardownMerge(groups=[s.TeardownMergeGroup(names=["人126", "人245"], keep="人245", why="同一个人")]),
            s.TeardownMerge(groups=[s.TeardownMergeGroup(names=["人245", "人246"], keep="人246", why="也是同一个人")]),
        ]
    )
    runner = StubRunner(sessionmaker, book_id, {s.TeardownMerge: lambda _: next(responses)})
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert await estimate_calls(session, book) == 3
    result = await collect_merge(runner)
    assert result["groups"] == [{"names": ["人125", "人126", "人245", "人246"], "keep": "人125", "why": "第 1 章认出"}]
    assert result["inputs"] == text_hash(merge_material(roster))
    assert len(runner.calls) == 3
    assert runner.calls[0]["system"] == render(
        "persona_essence", title="原书", upto="1", total="1", rules=render("rules")
    )
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.teardown["names"] == {"人126": "人125", "人245": "人125", "人246": "人125"}
    # 合并后的名单变化会再检查一次；此后 inputs 完全相同，独立步骤与估数都不再调用。
    runner.responses[s.TeardownMerge] = s.TeardownMerge()
    await collect_merge(runner)
    runner.calls.clear()
    state = await collect_merge(runner)
    assert runner.calls == [] and state["groups"] == result["groups"]
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert await estimate_calls(session, book) == 0
        assert await estimate_calls(session, book, force=True) == 2


@pytest.mark.parametrize("author_changed", [False, True])
async def test_merge_rewrites_keep_card_deletes_only_unedited_loser(sessionmaker, author_changed):
    reads = [read(i, [person("甲", f"甲的记录{i}"), person("乙", f"乙的记录{i}")]) for i in range(1, 6)]
    book_id = await setup_book(sessionmaker, reads)
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        ids = {row.name: row.id for row in rows}
        if author_changed:
            next(row for row in rows if row.name == "乙").one_line = "作者亲手改过的乙"
        await session.commit()
    runner.calls.clear()
    runner.responses[s.TeardownMerge] = s.TeardownMerge(
        groups=[s.TeardownMergeGroup(names=["甲", "乙"], keep="甲", why="第 5 章揭开身份")]
    )
    result = await collect_settings(runner, force=True)
    card_calls = [call for call in runner.calls if call["schema"] == s.TeardownCard]
    assert len(card_calls) == 1 and "乙的记录5" in card_calls[0]["user"]
    assert result["characters"] == (2 if author_changed else 1)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.teardown["names"] == {"乙": "甲"}
        roster, _, _ = people_of(reads, book.teardown["names"])
        assert len(roster.people) == 1 and len(roster.people[0]["rows"]) == 10
        rows = list(
            await session.scalars(select(Character).where(Character.book_id == book_id).order_by(Character.position))
        )
        assert rows[0].id == ids["甲"] and rows[0].position == 0 and rows[0].aliases == ["乙"]
        group = book.teardown["merges"]["groups"][0]
        if author_changed:
            assert group["kept_card"] is True
            assert rows[1].id == ids["乙"] and rows[1].one_line == "作者亲手改过的乙"
        else:
            assert "kept_card" not in group
            assert await session.get(Character, ids["乙"]) is None
        # 第二次整理主卡仍认原行，不能因为 key_name 是被并旧名而复活/覆盖作者卡。
        state = deepcopy(book.teardown["settings"])
        assert state["rows"]["character:乙"]["id"] == str(ids["甲"])
    runner.responses[s.TeardownMerge] = s.TeardownMerge()
    await collect_settings(runner)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert {row.id for row in rows} == ({ids["甲"], ids["乙"]} if author_changed else {ids["甲"]})
        book = await session.get(Book, book_id)
        assert book.teardown["merges"]["groups"][0] == group


async def test_positions_include_simple_characters_ties_and_do_not_touch_author_book(sessionmaker):
    reads = [
        read(i, [person("主角"), *([person("早出场")] if i <= 3 else []), *([person("晚出场")] if i >= 3 else [])])
        for i in range(1, 6)
    ]
    book_id = await setup_book(sessionmaker, reads)
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    async with sessionmaker() as session:
        rows = list(
            await session.scalars(select(Character).where(Character.book_id == book_id).order_by(Character.position))
        )
        assert [(row.name, row.position) for row in rows] == [("主角", 0), ("早出场", 1), ("晚出场", 2)]
        assert rows[1].one_line and rows[2].one_line
        book = await session.get(Book, book_id)
        book.source = "original"
        rows[0].position, rows[1].position = 20, 10
        await write_positions(session, book, reads)
        assert rows[0].position == 20 and rows[1].position == 10


async def test_settings_reaches_eight_but_not_more_parallel_model_calls(sessionmaker):
    book_id = await setup_book(sessionmaker, [read(i, [person(f"人物{j}") for j in range(12)]) for i in range(1, 6)])
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    assert runner.maximum == 8
    assert not any(call["purpose"] == "拆书：这本书好在哪" for call in runner.calls)


async def test_card_choosing_merged_alias_does_not_split_identity_again(sessionmaker):
    from tests.test_teardown_settings import card

    reads = [read(i, [person("甲"), person("乙")]) for i in range(1, 6)]
    book_id = await setup_book(sessionmaker, reads)
    runner = StubRunner(
        sessionmaker,
        book_id,
        {
            s.TeardownMerge: s.TeardownMerge(
                groups=[s.TeardownMergeGroup(names=["甲", "乙"], keep="甲", why="第 1 章认出")]
            ),
            s.TeardownCard: card("乙", aliases=["甲"]),
        },
    )
    await collect_settings(runner)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        roster, _, protagonist = people_of(reads, book.teardown["names"])
        assert len(roster.people) == 1 and protagonist == "乙"
        assert book.teardown["names"] == {"甲": "乙"}
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert len(rows) == 1 and rows[0].name == "乙"


@pytest.mark.parametrize("keep_card_exists", [False, True])
async def test_merge_keeps_author_edited_and_added_relationships_before_deleting_loser(sessionmaker, keep_card_exists):
    from tests.test_teardown_settings import card

    reads = [
        read(i, [person("乙"), person("丙"), *([person("甲")] if keep_card_exists or i == 1 else [])])
        for i in range(1, 6)
    ]
    book_id = await setup_book(sessionmaker, reads)

    def cards(user):
        name = user.split("【这个人】")[1].split("（也叫")[0]
        return card(
            name, ties=[s.TeardownTie(who="丙", relation="模型原来的关系", since_chapter=1)] if name == "乙" else []
        )

    runner = StubRunner(sessionmaker, book_id, {s.TeardownCard: cards})
    await collect_settings(runner)
    async with sessionmaker() as session:
        rows = {row.name: row for row in await session.scalars(select(Character).where(Character.book_id == book_id))}
        loser_id = rows["乙"].id
        edited = await session.scalar(select(Relationship).where(Relationship.book_id == book_id))
        edited.description = "作者亲手改过的关系"
        edited_id = edited.id
        added = Relationship(
            book_id=book_id,
            source_id=rows["丙"].id,
            target_id=loser_id,
            kind="作者新增",
            description="作者新增的反向关系",
        )
        session.add(added)
        await session.commit()
        added_id = added.id
    runner.responses[s.TeardownMerge] = s.TeardownMerge(
        groups=[s.TeardownMergeGroup(names=["甲", "乙"], keep="甲", why="第 5 章揭开")]
    )
    # 新主名若又返回同一条关系，也不能覆盖作者已经改过的描述。
    runner.responses[s.TeardownCard] = lambda _: card(
        "甲", ties=[s.TeardownTie(who="丙", relation="模型不应覆盖", since_chapter=1)]
    )
    await collect_settings(runner, force=True)
    async with sessionmaker() as session:
        keep = await session.scalar(select(Character).where(Character.book_id == book_id, Character.name == "甲"))
        assert keep is not None and await session.get(Character, loser_id) is None
        edited, added = await session.get(Relationship, edited_id), await session.get(Relationship, added_id)
        assert edited is not None and edited.description == "作者亲手改过的关系" and edited.source_id == keep.id
        assert added is not None and added.description == "作者新增的反向关系" and added.target_id == keep.id
        assert edited.source_id != edited.target_id and added.source_id != added.target_id


async def test_relation_between_merged_identities_is_fully_archived_not_left_as_self_loop(sessionmaker):
    from tests.test_teardown_settings import card

    book_id = await setup_book(sessionmaker, [read(i, [person("甲"), person("乙")]) for i in range(1, 6)])
    runner = StubRunner(
        sessionmaker,
        book_id,
        {
            s.TeardownCard: lambda user: card(
                user.split("【这个人】")[1].split("（也叫")[0],
                ties=[s.TeardownTie(who="甲", relation="原来的关系", since_chapter=2)]
                if "【这个人】乙" in user
                else [],
            )
        },
    )
    await collect_settings(runner)
    async with sessionmaker() as session:
        relation = await session.scalar(select(Relationship).where(Relationship.book_id == book_id))
        relation.description = "作者改过，必须完整保留"
        await session.commit()
        await session.refresh(relation)
        relation_id = relation.id
        expected = {
            column.name: value.isoformat()
            if hasattr(value, "isoformat")
            else str(value)
            if column.name in {"id", "book_id", "source_id", "target_id"}
            else value
            for column in relation.__table__.columns
            for value in [getattr(relation, column.name)]
        }
        book = await session.get(Book, book_id)
        old_state = deepcopy(book.teardown["settings"]["relationships"])
    runner.responses[s.TeardownMerge] = s.TeardownMerge(
        groups=[s.TeardownMergeGroup(names=["甲", "乙"], keep="甲", why="第 5 章认出")]
    )
    await collect_merge(runner, force=True)
    async with sessionmaker() as session:
        assert await session.get(Relationship, relation_id) is None
        book = await session.get(Book, book_id)
        assert book.teardown["settings"]["merged_relationships"] == [{"row": expected, "state": old_state}]
        assert book.teardown["settings"]["relationships"] == {}


async def test_merging_does_not_revive_author_deleted_keep_card_for_relationships(sessionmaker):
    book_id = await setup_book(sessionmaker, [read(i, [person("甲"), person("乙"), person("丙")]) for i in range(1, 6)])
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    async with sessionmaker() as session:
        rows = {r.name: r for r in await session.scalars(select(Character).where(Character.book_id == book_id))}
        session.add(
            Relationship(
                book_id=book_id,
                source_id=rows["乙"].id,
                target_id=rows["丙"].id,
                kind="作者关系",
                description="不能因为主名卡被删除而丢失",
            )
        )
        await session.delete(rows["甲"])
        await session.commit()
    runner.responses[s.TeardownMerge] = s.TeardownMerge(
        groups=[s.TeardownMergeGroup(names=["甲", "乙"], keep="甲", why="第 5 章认出")]
    )
    await collect_settings(runner, force=True)
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert [row.name for row in rows] == ["丙"]
        book = await session.get(Book, book_id)
        archive = book.teardown["settings"]["merged_relationships"]
        assert len(archive) == 1 and archive[0]["row"]["description"] == "不能因为主名卡被删除而丢失"
