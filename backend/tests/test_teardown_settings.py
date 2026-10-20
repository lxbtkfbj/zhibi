"""第三批人物、增量、作者保护与分项落盘，只使用独立测试库。"""

import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.agents import schemas as s
from app.graphs.deps import JobCancelled
from app.models import Book, Chapter, Character, PlotUnit, Relationship, Volume, WorldEntry
from app.models.library import SettingVersion
from app.prompts import default_content, render
from app.services.desk import value_of
from app.services.teardown_settings import (
    SettingsIncomplete,
    accept_card_name,
    card_values,
    collect_settings,
    dossier_of,
    estimate_calls,
    input_unchanged,
    people_of,
    reuse_character_keys,
    spans,
    text_hash,
)


@pytest.fixture(autouse=True)
def default_prompts(monkeypatch):
    monkeypatch.setattr("app.prompts._load", default_content)


def person(name, shown="写出了性格", **values):
    return {"name": name, "shown": shown, "also_called": [], "was": "", "change": "", **values}


def read(index, people=None, **values):
    return {
        "index": index,
        "people": people or [],
        "moments": [],
        "things": [],
        "waits": [],
        "tropes": [],
        "feel": "平",
        **values,
    }


def card(name, **values):
    return s.TeardownCard(name=name, one_line=f"{name}的一句话", role_type="配角", **values)


def test_people_threshold_names_and_card_rename_rules():
    reads = [read(i, [person("甲"), person("红发少女", also_called=["茉莉"])]) for i in range(1, 6)]
    reads[0]["people"] += [person("路人"), person("老师"), person("配角")]
    reads[1]["people"] += [person("配角")]
    reads[0]["moments"] = [{"who": "老师", "what": "救人", "shows": "勇敢"}]
    roster, selected, protagonist = people_of(reads, {"红发少女": "茉莉"})
    assert protagonist == "甲"
    assert {p["name"] for p in selected if p["full"]} == {"甲", "茉莉", "老师"}
    assert [p["name"] for p in selected if not p["full"]] == ["配角"]
    girl = roster.find("红发少女")
    assert girl["name"] == "茉莉" and girl["key_name"] == "红发少女"
    hero = roster.find("甲")
    assert accept_card_name(hero, card("乙"), roster, []) == "甲"
    assert accept_card_name(hero, card("乙", aliases=["甲"]), roster, []) == "乙"
    missing = []
    assert accept_card_name(hero, card("茉莉", aliases=["甲"]), roster, missing) == "甲"
    assert missing == ["卡上写的名字和 茉莉 重名，没改"]
    many = [read(i, [person(f"人{j}") for j in range(45)]) for i in range(1, 6)]
    assert len(people_of(many)[1]) == 40


def test_card_names_merge_old_and_new_read_identity_without_was():
    reads = [
        read(
            1, [person("红发少女", shown="旧记录")], moments=[{"who": "红发少女", "what": "旧名救人", "shows": "果断"}]
        ),
        read(2, [person("茉莉", shown="新记录")], moments=[{"who": "茉莉", "what": "新名救人", "shows": "冷静"}]),
        read(3, [person("红发少女"), person("茉莉")]),
    ]
    before = deepcopy(reads)
    roster, selected, protagonist = people_of(reads, {"红发少女": "茉莉"})
    assert len(roster.people) == len(selected) == 1
    girl = roster.find("红发少女")
    assert roster.find("茉莉") is girl and girl["key_name"] == "红发少女"
    assert girl["chapters"] == {1, 2, 3} and girl["first"] == 1 and girl["note"] == "旧记录"
    assert girl["aliases"] == ["红发少女"] and len(girl["rows"]) == 4 and len(girl["moments"]) == 2
    assert protagonist == "茉莉" and girl["full"]
    assert reads == before


def test_reuse_owned_keys_does_not_claim_shared_alias_or_another_person_name():
    reads = [
        read(i, [person("张三", also_called=["黑衣人"]), person("李四", also_called=["黑衣人"])]) for i in range(1, 6)
    ]
    roster, _, _ = people_of(reads)
    reuse_character_keys(roster, {"rows": {"character:黑衣人": {"id": "owned"}}})
    assert {p["name"]: p["key_name"] for p in roster.people} == {"张三": "张三", "李四": "李四"}
    roster, _, _ = people_of([read(1, [person("李四"), person("张三", also_called=["李四"])])])
    reuse_character_keys(roster, {"rows": {"character:李四": {"id": "owned"}}})
    assert roster.find("张三")["key_name"] == "张三"
    assert roster.find("李四")["key_name"] == "李四"


def test_dossier_exact_order_and_priority_truncation():
    reads = [
        read(
            1, [person("甲", shown="第一回", change="变强")], moments=[{"who": "甲", "what": "救人", "shows": "勇敢"}]
        ),
        read(2, [person("甲", shown="第二回")]),
    ]
    _, selected, _ = people_of(reads)
    assert dossier_of(selected[0]) == "第 1 章：第一回（变化：变强）\n第 1 章名场面：救人——立住了勇敢\n第 2 章：第二回"
    long_reads = [
        read(i, [person("甲", shown=f"记录{i}：" + "字" * 150, change="重要变化" if i == 50 else "")])
        for i in range(1, 151)
    ]
    long_reads[79]["moments"] = [{"who": "甲", "what": "关键救人", "shows": "勇敢"}]
    entry = people_of(long_reads)[1][0]
    text = dossier_of(entry)
    assert len(text) <= 12000
    assert "第 80 章名场面：关键救人——立住了勇敢" in text
    assert "第 50 章：记录50" in text
    assert "第 1 章：记录1" in text and "第 150 章：记录150" in text
    assert text.endswith("章的记录没列出）")
    assert text.index("第 50 章：") < text.index("第 80 章：")
    assert spans([10, 1, 2, 3, 7, 9]) == "1–3、7、9–10"


def test_card_input_raw_hash_and_stable_context_for_multiple_extensions():
    entry = people_of([read(i, [person("甲")]) for i in range(1, 6)])[1][0]
    values = card_values("原书", 10, entry, "甲")
    user = render("teardown_card", **values)
    state = {
        "upto": 20,
        "inputs": {"card:甲": text_hash(user)},
        "contexts": {"card:甲": {"title": "原书", "last": "10", "evidence": values["_evidence"]}},
    }
    later = card_values("改过书名", 30, entry, "甲")
    assert input_unchanged(state, "card:甲", "teardown_card", later)
    entry["rows"].append((30, person("甲", shown="新的样子")))
    assert not input_unchanged(state, "card:甲", "teardown_card", card_values("原书", 30, entry, "甲"))
    assert not input_unchanged(state, "card:甲", "teardown_card", later, force=True)


class StubRunner:
    def __init__(self, sm, book_id, responses=None):
        self.sm, self.book_id = sm, book_id
        self.responses = responses or {}
        self.calls, self.progresses = [], []
        self.cancel = False
        self.active = self.maximum = 0

    async def snapshot(self):
        async with self.sm() as session:
            book = await session.get(Book, self.book_id)
            chapters = list(
                await session.scalars(select(Chapter).where(Chapter.book_id == self.book_id).order_by(Chapter.index))
            )
            units = list(await session.scalars(select(PlotUnit).where(PlotUnit.book_id == self.book_id)))
            volumes = list(await session.scalars(select(Volume).where(Volume.book_id == self.book_id)))
        return book, chapters, units, volumes

    async def cancelled(self):
        return self.cancel

    async def refresh(self, **kwargs):
        pass

    async def progress(self, doing, **kwargs):
        self.progresses.append({"doing": doing, **deepcopy(kwargs)})

    async def call_user(self, schema, user, purpose):
        self.calls.append({"schema": schema, "user": user, "purpose": purpose})
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0.005)
            result = self.responses.get(schema)
            if callable(result):
                result = result(user)
            if isinstance(result, Exception):
                raise result
            if result is not None:
                return result.model_copy(deep=True)
            if schema == s.TeardownCard:
                name = user.split("【这个人】")[1].split("（也叫")[0]
                return card(name)
            if schema == s.TeardownMerits:
                return s.TeardownMerits(points=[s.TeardownPoint(topic="开头", text="第 1 章立住主角。")])
            return schema()
        finally:
            self.active -= 1


async def setup_book(sm, reads, *, layouts=None):
    async with sm() as session:
        book = Book(title="原书", source="teardown", teardown={"stage": "stopped"}, card_layouts=layouts or {})
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="还没收尾", chapter_count=len(reads))
        session.add(volume)
        await session.flush()
        for row in reads:
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=row["index"],
                    title="章名",
                    content="青城、城外、门派和宝物",
                    summary="摘要",
                    outline={"hook": "期待", "cool_point": "智取"},
                    teardown={"read_version": 1, "read": row},
                )
            )
        await session.commit()
        return book.id


async def test_collect_names_collision_relationships_layout_and_incremental(sessionmaker):
    reads = [read(i, [person("红发少女", also_called=["茉莉"]), person("朋友")]) for i in range(1, 6)]
    book_id = await setup_book(sessionmaker, reads)
    async with sessionmaker() as session:
        session.add(Character(book_id=book_id, name="茉莉", source="author", one_line="作者角色"))
        await session.commit()

    def cards(user):
        if "【这个人】红发少女" in user:
            return card(
                "茉莉",
                aliases=["红发少女"],
                belongs="门派",
                now=s.TeardownNow(power="很强", location="青城", condition="藏身", want="求生", alive=False),
                moments=[s.TeardownCardMoment(chapter=1, what="救人", shows="果断")],
                ties=[s.TeardownTie(who="朋友/没出现的人", relation="互相帮助", since_chapter=2)],
            )
        return card("朋友", ties=[s.TeardownTie(who="红发少女", relation="信任", since_chapter=1)])

    runner = StubRunner(sessionmaker, book_id, {s.TeardownCard: cards})
    result = await collect_settings(runner)
    assert result["characters"] == 2
    assert len(runner.calls) == 3 and runner.maximum <= 4
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        own = next(row for row in rows if row.source == "author")
        girl = next(row for row in rows if row.name == "茉莉（第 1 章起）")
        assert own.one_line == "作者角色"
        assert girl.location == "青城" and girl.condition == "藏身" and girl.want == "求生" and not girl.is_alive
        assert value_of(girl, "所属") == "门派"
        assert value_of(girl, "名场面") == "第 1 章：救人——立住了果断"
        assert book.teardown["names"] == {"红发少女": "茉莉"}
        assert book.card_layouts["角色列表"]["sections"][-1] == {"key": "名场面", "label": "名场面"}
        relationships = list(await session.scalars(select(Relationship).where(Relationship.book_id == book_id)))
        assert all({r.source_id, r.target_id} <= {row.id for row in rows} for r in relationships)
        assert relationships
        assert all(r.kind in ("互相帮助", "信任") for r in relationships)
        versions = list(await session.scalars(select(SettingVersion).where(SettingVersion.book_id == book_id)))
        assert len(versions) == 2 and all(v.source == "teardown" and v.note == "拆书整理设定" for v in versions)
        for call in runner.calls:
            key = (
                "merits"
                if call["schema"] == s.TeardownMerits
                else "card:" + ("红发少女" if "【这个人】红发少女" in call["user"] else "朋友")
            )
            assert book.teardown["settings"]["inputs"][key] == text_hash(call["user"])
    runner.calls.clear()
    await collect_settings(runner)
    assert runner.calls == []


async def test_author_changed_rows_simple_upgrade_and_partial_failures(sessionmaker):
    reads = [read(1, [person("甲"), person("乙")]), read(2, [person("甲"), person("乙")])]
    book_id = await setup_book(
        sessionmaker, reads, layouts={"角色列表": {"facts": [], "sections": [{"key": "作者栏", "label": "作者栏"}]}}
    )
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    assert len(runner.calls) == 1
    async with sessionmaker() as session:
        characters = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        first_ids = {row.name: row.id for row in characters}
        next(row for row in characters if row.name == "乙").one_line = "作者手改"
        volume = await session.scalar(select(Volume).where(Volume.book_id == book_id))
        for i in range(3, 6):
            session.add(
                Chapter(
                    book_id=book_id,
                    volume_id=volume.id,
                    index=i,
                    title="后续",
                    content="青城",
                    teardown={"read_version": 1, "read": read(i, [person("甲"), person("乙")])},
                )
            )
        await session.commit()
    runner.calls.clear()
    result = await collect_settings(runner)
    assert result["skipped"] == ["乙"]
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.card_layouts["角色列表"]["sections"] == [{"key": "作者栏", "label": "作者栏"}]
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert {row.name: row.id for row in rows} == first_ids
        assert next(row for row in rows if row.name == "乙").one_line == "作者手改"
    runner.responses[s.TeardownMerits] = ValueError("模型失败")
    with pytest.raises(SettingsIncomplete) as failed:
        await collect_settings(runner, force=True)
    assert failed.value.result["characters"] == 2
    assert "这本书好在哪" in str(failed.value)
    runner.responses.pop(s.TeardownMerits)
    runner.calls.clear()
    await collect_settings(runner)
    assert [call["schema"] for call in runner.calls] == [s.TeardownMerits]


async def test_world_writing_tree_protection_factions_after_cards_and_estimate(sessionmaker):
    things = [
        {"kind": kind, "name": name, "note": "记录", "belongs": belongs, "secret": ""}
        for kind, name, belongs in [
            ("金手指", "奇物", ""),
            ("等级", "境界", ""),
            ("地方", "青城", ""),
            ("地方", "城外", "青城"),
            ("势力", "门派", ""),
            ("秘密", "身世", ""),
        ]
    ]
    reads = [
        read(i, [person("甲", change="突破" if i == 2 else "")], things=things if i == 1 else []) for i in range(1, 6)
    ]
    book_id = await setup_book(sessionmaker, reads)
    responses = {
        s.TeardownCard: card("甲", belongs="门派"),
        s.TeardownGoldfingers: s.TeardownGoldfingers(
            items=[s.TeardownGoldfinger(name="奇物", what="是什么", can="能做什么", first_chapter=1)]
        ),
        s.TeardownLadders: s.TeardownLadders(
            ladders=[
                s.TeardownLadder(
                    name="境界",
                    how_up="修炼",
                    levels=[s.TeardownLevel(name="一层", note="入门", protagonist_chapter=2)],
                )
            ]
        ),
        s.TeardownPlaces: s.TeardownPlaces(
            world="世界概况正文",
            items=[
                s.TeardownPlace(name="城外", parent="青城", note="郊外", first_chapter=2),
                s.TeardownPlace(name="青城", note="城市", first_chapter=1),
            ],
        ),
        s.TeardownFactions: s.TeardownFactions(
            items=[s.TeardownFaction(name="门派", note="组织", leader="甲", members=["甲"], first_chapter=1)]
        ),
        s.TeardownSecrets: s.TeardownSecrets(
            items=[s.TeardownSecret(name="身世", truth="真相", planted_chapter=4, revealed_chapter=2)]
        ),
    }
    runner = StubRunner(sessionmaker, book_id, responses)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert await estimate_calls(session, book) == 7
    result = await collect_settings(runner)
    assert result["entries"] == 7
    assert "身世：揭开的章号早于埋下，没写揭开" in result["missing"]
    factions = next(call for call in runner.calls if call["schema"] == s.TeardownFactions)
    assert "角色卡上写的所属：\n- 甲：门派" in factions["user"]
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book_id)))
        city = next(row for row in rows if row.name == "青城")
        outside = next(row for row in rows if row.name == "城外")
        assert outside.parent_id == city.id
        assert next(row for row in rows if row.name == "世界概况").content == "世界概况正文"
        ladder = next(row for row in rows if row.name == "境界")
        assert ladder.style == "ladder" and ladder.levels[0]["protagonist_chapter"] == 2
        assert "主角第 2 章到" in ladder.levels[0]["text"]
        assert "成员：甲" in next(row for row in rows if row.name == "门派").content
        secret = next(row for row in rows if row.name == "身世")
        assert value_of(secret, "打算何时揭开") == "到第 5 章还没揭开"
        book = await session.get(Book, book_id)
        assert "身世：揭开的章号早于埋下，没写揭开" in book.teardown["settings"]["missing"]
        assert "身世：揭开的章号早于埋下，没写揭开" in book.teardown["settings"]["contexts"]["world:秘密:1"]["missing"]
        outside.content = "作者改的郊外"
        await session.commit()
    result = await collect_settings(runner, force=True)
    assert "城外" in result["skipped"]
    runner.calls.clear()
    await collect_settings(runner, merits_only=True)
    assert [call["schema"] for call in runner.calls] == [s.TeardownMerits]
    runner.cancel = True
    with pytest.raises(JobCancelled):
        await collect_settings(runner)


async def test_two_extensions_only_rewrite_people_with_new_records_and_zero_read_version(sessionmaker):
    book_id = await setup_book(sessionmaker, [read(i, [person("甲"), person("乙")]) for i in range(1, 6)])
    async with sessionmaker() as session:
        first = await session.scalar(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == 1))
        first.teardown = {**first.teardown, "read_version": 0}
        await session.commit()
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        original_input = book.teardown["settings"]["inputs"]["card:乙"]
        assert book.teardown["settings"]["upto"] == 5
    for index in (6, 7):
        async with sessionmaker() as session:
            volume = await session.scalar(select(Volume).where(Volume.book_id == book_id))
            session.add(
                Chapter(
                    book_id=book_id,
                    volume_id=volume.id,
                    index=index,
                    title="新章",
                    content="原文",
                    teardown={"read_version": 1, "read": read(index, [person("甲", shown="新变化")])},
                )
            )
            await session.commit()
        runner.calls.clear()
        await collect_settings(runner)
        cards = [call for call in runner.calls if call["schema"] == s.TeardownCard]
        assert len(cards) == 1 and "【这个人】甲" in cards[0]["user"]
        assert runner.progresses[-1]["settings"]["done"] == runner.progresses[-1]["settings"]["total"]
        async with sessionmaker() as session:
            book = await session.get(Book, book_id)
            assert book.teardown["settings"]["inputs"]["card:乙"] == original_input
            assert book.teardown["settings"]["contexts"]["card:乙"]["last"] == "5"


async def test_author_deleted_character_and_entry_are_not_revived_and_inputs_stay_cached(sessionmaker):
    reads = [
        read(
            i,
            [person("甲")],
            things=[{"kind": "地方", "name": "青城", "note": "城市", "belongs": "", "secret": ""}] if i == 1 else [],
        )
        for i in range(1, 6)
    ]
    book_id = await setup_book(sessionmaker, reads)
    runner = StubRunner(
        sessionmaker,
        book_id,
        {
            s.TeardownPlaces: s.TeardownPlaces(items=[s.TeardownPlace(name="青城", note="城市", first_chapter=1)]),
        },
    )
    result = await collect_settings(runner)
    assert result["characters"] == 1 and result["entries"] == 1
    async with sessionmaker() as session:
        character = await session.scalar(select(Character).where(Character.book_id == book_id))
        entry = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == book_id))
        await session.delete(character)
        await session.delete(entry)
        await session.commit()
    result = await collect_settings(runner, force=True)
    assert set(result["skipped"]) == {"甲", "青城"}
    assert result["characters"] == result["entries"] == 0
    async with sessionmaker() as session:
        assert await session.scalar(select(Character.id).where(Character.book_id == book_id)) is None
        assert await session.scalar(select(WorldEntry.id).where(WorldEntry.book_id == book_id)) is None
        book = await session.get(Book, book_id)
        assert "card:甲" in book.teardown["settings"]["inputs"]
        assert "world:地方:1" in book.teardown["settings"]["inputs"]
    runner.calls.clear()
    await collect_settings(runner)
    assert runner.calls == []


@pytest.mark.parametrize("author_changed", [False, True])
async def test_card_renamed_person_new_read_without_was_updates_original_key_and_protects_author(
    sessionmaker, author_changed
):
    reads = [read(i, [person("红发少女")]) for i in range(1, 6)]
    book_id = await setup_book(sessionmaker, reads)
    runner = StubRunner(sessionmaker, book_id, {s.TeardownCard: card("茉莉", aliases=["红发少女"])})
    await collect_settings(runner)
    async with sessionmaker() as session:
        row = await session.scalar(select(Character).where(Character.book_id == book_id))
        original_id = row.id
        if author_changed:
            row.one_line = "作者修改的茉莉"
        volume = await session.scalar(select(Volume).where(Volume.book_id == book_id))
        session.add(
            Chapter(
                book_id=book_id,
                volume_id=volume.id,
                index=6,
                title="新名出场",
                content="茉莉再次出现",
                teardown={
                    "read_version": 1,
                    "read": read(
                        6,
                        [person("茉莉", shown="新名的新记录")],
                        moments=[{"who": "茉莉", "what": "再次救人", "shows": "果断"}],
                    ),
                },
            )
        )
        await session.commit()
    runner.calls.clear()
    result = await collect_settings(runner)
    assert result["characters"] == 1
    assert result["skipped"] == (["茉莉"] if author_changed else [])
    card_calls = [call for call in runner.calls if call["schema"] == s.TeardownCard]
    assert len(card_calls) == 1 and "【这个人】茉莉" in card_calls[0]["user"]
    assert "出场 6 章：第 1–6 章" in card_calls[0]["user"]
    assert "第 6 章名场面：再次救人——立住了果断" in card_calls[0]["user"]
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert len(rows) == 1 and rows[0].id == original_id and rows[0].name == "茉莉"
        if author_changed:
            assert rows[0].one_line == "作者修改的茉莉"
        book = await session.get(Book, book_id)
        assert "character:红发少女" in book.teardown["settings"]["rows"]
        assert "character:茉莉" not in book.teardown["settings"]["rows"]
        assert "card:红发少女" in book.teardown["settings"]["inputs"]
        assert "card:茉莉" not in book.teardown["settings"]["inputs"]
        first = await session.scalar(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == 1))
        last = await session.scalar(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == 6))
        assert first.teardown["read"]["people"][0]["name"] == "红发少女"
        assert last.teardown["read"]["people"][0]["name"] == "茉莉"


async def test_conflicting_card_name_missing_is_persisted_across_skipped_calls_and_merits_only(sessionmaker):
    book_id = await setup_book(sessionmaker, [read(i, [person("甲"), person("乙")]) for i in range(1, 6)])

    def cards(user):
        if "【这个人】甲" in user:
            return card("乙", aliases=["甲"], missing=["年龄", "年龄"])
        return card("乙", missing=["性别"])

    runner = StubRunner(sessionmaker, book_id, {s.TeardownCard: cards})
    result = await collect_settings(runner)
    expected = {"卡上写的名字和 乙 重名，没改", "年龄", "性别"}
    assert set(result["missing"]) == expected
    runner.calls.clear()
    await collect_settings(runner)
    assert runner.calls == []
    await collect_settings(runner, merits_only=True)
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        state = book.teardown["settings"]
        assert set(state["missing"]) == expected
        assert len(state["missing"]) == 3
        assert state["contexts"]["card:甲"]["missing"] == ["卡上写的名字和 乙 重名，没改", "年龄"]
        assert state["contexts"]["card:乙"]["missing"] == ["性别"]


async def test_collect_cancel_joins_all_siblings_before_cancel_flag_can_be_cleared(sessionmaker):
    book_id = await setup_book(sessionmaker, [read(i, [person(f"人物{j}") for j in range(8)]) for i in range(1, 6)])

    class CancellingRunner(StubRunner):
        def __init__(self):
            super().__init__(sessionmaker, book_id)
            self.four_started = asyncio.Event()
            self.late_release = asyncio.Event()
            self.children = []
            self.finished = set()

        async def call_user(self, schema, user, purpose):
            call_index = len(self.calls)
            self.calls.append({"schema": schema, "user": user, "purpose": purpose})
            self.children.append(asyncio.current_task())
            if len(self.calls) == 4:
                self.four_started.set()
            try:
                if call_index == 0:
                    await self.four_started.wait()
                    self.cancel = True
                else:
                    await self.late_release.wait()
                return card(user.split("【这个人】")[1].split("（也叫")[0])
            finally:
                self.finished.add(call_index)

    runner = CancellingRunner()
    with pytest.raises(JobCancelled):
        await asyncio.wait_for(collect_settings(runner), timeout=5)
    # 模拟 Runner.finish 清 Redis cancel_key：collect 返回之前必须已回收所有调用。
    assert len(runner.calls) == 4
    assert len(runner.finished) == 4
    assert all(task.done() for task in runner.children)
    runner.cancel = False
    runner.late_release.set()
    await asyncio.sleep(0.02)
    assert len(runner.calls) == 4
    assert all(task.done() for task in runner.children)
    async with sessionmaker() as session:
        assert await session.scalar(select(Character.id).where(Character.book_id == book_id)) is None
        assert await session.scalar(select(WorldEntry.id).where(WorldEntry.book_id == book_id)) is None
        book = await session.get(Book, book_id)
        assert book.teardown["settings"]["inputs"] == {}


@pytest.mark.parametrize("author_changed", [False, True])
async def test_was_renamed_one_line_character_reuses_owned_row_and_respects_author(sessionmaker, author_changed):
    book_id = await setup_book(sessionmaker, [read(i, [person("黑衣人")]) for i in (1, 2)])
    runner = StubRunner(sessionmaker, book_id)
    await collect_settings(runner)
    async with sessionmaker() as session:
        row = await session.scalar(select(Character).where(Character.book_id == book_id))
        original_id = row.id
        if author_changed:
            row.one_line = "作者改过的黑衣人"
        book = await session.get(Book, book_id)
        assert book.teardown["names"] == {}
        assert set(book.teardown["settings"]["rows"]) == {"character:黑衣人"}
        volume = await session.scalar(select(Volume).where(Volume.book_id == book_id))
        for index in (3, 4, 5):
            session.add(
                Chapter(
                    book_id=book_id,
                    volume_id=volume.id,
                    index=index,
                    title="揭开真名",
                    content="张三又出现了",
                    teardown={
                        "read_version": 1,
                        "read": read(index, [person("张三", was="黑衣人" if index == 3 else "")]),
                    },
                )
            )
        await session.commit()
    runner.calls.clear()
    result = await collect_settings(runner)
    assert result["characters"] == 1
    assert result["skipped"] == (["黑衣人"] if author_changed else [])
    card_calls = [call for call in runner.calls if call["schema"] == s.TeardownCard]
    assert len(card_calls) == 1 and "【这个人】张三" in card_calls[0]["user"]
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(Character).where(Character.book_id == book_id)))
        assert len(rows) == 1 and rows[0].id == original_id
        assert rows[0].name == ("黑衣人" if author_changed else "张三")
        if author_changed:
            assert rows[0].one_line == "作者改过的黑衣人"
        book = await session.get(Book, book_id)
        assert set(book.teardown["settings"]["rows"]) == {"character:黑衣人"}
        assert "card:黑衣人" in book.teardown["settings"]["inputs"]
        assert "card:张三" not in book.teardown["settings"]["inputs"]
        assert book.teardown["names"] == ({} if author_changed else {"黑衣人": "张三"})
    runner.calls.clear()
    await collect_settings(runner)
    assert runner.calls == []
