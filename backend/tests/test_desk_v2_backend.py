"""装修的只读右栏、旧试整理灌入与两项写库修正。"""

import copy
import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, func, select

from app.agents import schemas as s
from app.main import create_app
from app.models import Book, Chapter, Character, Job, PlotUnit, Relationship, SettingVersion, Volume, WorldEntry
from app.services.teardown_digest import people_count
from app.services.teardown_settings import SettingsWriter, dossier_of, moment_shows
from app.services.teardown_trial import ensure_trial_database, seed_trial, trial_card, trial_world

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


def p(name, **values):
    return {"name": name, "shown": "出场", **values}


async def fixture_book(sm, source="teardown"):
    async with sm() as session:
        book, other = Book(title="范围书", source=source, teardown={"names": {"旧名": "主角"}}), Book(title="别书")
        session.add_all([book, other])
        await session.flush()
        volumes = [Volume(book_id=book.id, index=i, title=f"卷{i}") for i in (1, 2)]
        foreign = Volume(book_id=other.id, index=1, title="别书卷")
        session.add_all([*volumes, foreign])
        await session.flush()
        units = [PlotUnit(book_id=book.id, volume_id=v.id, index=1, title="单元") for v in volumes]
        session.add_all(units)
        await session.flush()
        records = [
            {
                "people": [p("甲"), p("旧名", change="变化1"), p("主角")],
                "things": [
                    {"kind": "地方", "name": " 城 ", "note": "首次"},
                    {"kind": "物品功法", "name": "城", "note": "同名不同类"},
                ],
                "waits": [{"action": "立下", "what": "等1"}],
            },
            {
                "people": [p("甲", also_called=["主角"], change="别名变化"), p("乙", was="旧名", change="旧名变化")],
                "things": [{"kind": "地方", "name": "城", "note": "不取第二次"}],
                "waits": [{"action": "兑现", "what": "等2"}],
            },
            {"people": [p("主角", also_called=["笔名"])]},
            {"people": [p("主角")]},
        ]
        for index, read in enumerate(records, 1):
            unit = units[0] if index <= 2 else units[1]
            session.add(
                Chapter(
                    book_id=book.id,
                    index=index,
                    unit_id=unit.id,
                    volume_id=unit.volume_id,
                    content="原文不应加载",
                    teardown={"read_version": 1, "read": read},
                )
            )
        session.add(
            Chapter(book_id=book.id, index=5, volume_id=volumes[0].id, teardown={"read": {"people": [p("未读幽灵")]}})
        )
        char = Character(book_id=book.id, name="主角", aliases=["旧名", "笔名"])
        other_char = Character(book_id=other.id, name="别书人")
        session.add_all([char, other_char])
        await session.commit()
        return book.id, units[0].id, volumes[0].id, foreign.id, char.id, other_char.id


async def test_digest_scope_global_hero_names_dedup_first_occurrences_readonly(client, sessionmaker):
    bid, uid, vid, _, _, _ = await fixture_book(sessionmaker)
    statements = []
    async with sessionmaker() as session:
        bind = session.bind.sync_engine

    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = await client.get(f"/api/books/{bid}/teardown/digest", params={"unit": str(uid)})
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json() == {
        "people": [
            {"name": "甲", "chapters": 2, "first": 1},
            {"name": "主角", "chapters": 1, "first": 1},
            {"name": "乙", "chapters": 1, "first": 2},
        ],
        "things": [
            {"chapter": 1, "kind": "地方", "name": "城", "note": "首次", "belongs": "", "secret": ""},
            {"chapter": 1, "kind": "物品功法", "name": "城", "note": "同名不同类", "belongs": "", "secret": ""},
        ],
        "waits": [{"chapter": 1, "action": "立下", "what": "等1"}, {"chapter": 2, "action": "兑现", "what": "等2"}],
        "hero": "主角",
        "changes": [
            {"chapter": 1, "change": "变化1"},
            {"chapter": 2, "change": "别名变化"},
            {"chapter": 2, "change": "旧名变化"},
        ],
    }
    assert (
        await client.get(f"/api/books/{bid}/teardown/digest", params={"volume": str(vid)})
    ).json() == response.json()
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert not any("chapters.content" in statement for statement in statements)
    assert "未读幽灵" not in response.text


async def test_digest_queries_appearance_cross_book_and_author_empty(client, sessionmaker):
    bid, uid, vid, foreign, cid, foreign_char = await fixture_book(sessionmaker)
    assert (await client.get(f"/api/books/{bid}/teardown/appearances", params={"character": str(cid)})).json() == {
        "chapters": [1, 2, 3, 4]
    }
    for params, status in [
        ({}, 422),
        ({"unit": str(uid), "volume": str(vid)}, 422),
        ({"volume": str(foreign)}, 404),
        ({"unit": str(uuid.uuid4())}, 404),
    ]:
        assert (await client.get(f"/api/books/{bid}/teardown/digest", params=params)).status_code == status
    assert (
        await client.get(f"/api/books/{bid}/teardown/appearances", params={"character": str(foreign_char)})
    ).status_code == 404
    assert (
        await client.get(f"/api/books/{uuid.uuid4()}/teardown/digest", params={"unit": str(uid)})
    ).status_code == 404
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.source = "new"
        await session.commit()
    assert (await client.get(f"/api/books/{bid}/teardown/digest", params={"unit": str(uid)})).json() == {
        "people": [],
        "things": [],
        "waits": [],
        "hero": None,
        "changes": [],
    }
    assert (await client.get(f"/api/books/{bid}/teardown/appearances", params={"character": str(cid)})).json() == {
        "chapters": []
    }


def test_people_count_ties_keep_record_order_after_name_mapping():
    rows = [
        {"index": 1, "read": {"people": [p(" 旧名 "), p("新名"), p("乙"), p("甲")]}},
        {"index": 2, "read": {"people": [p("甲"), p("乙")]}},
    ]
    assert people_count(rows, {"旧名": "新名"}) == [
        {"name": "乙", "chapters": 2, "first": 1},
        {"name": "甲", "chapters": 2, "first": 1},
        {"name": "新名", "chapters": 1, "first": 1},
    ]


@pytest.mark.parametrize("prefix", ["", "立住了", "立住", "立住了：", "立住：", "立住了: ", "立住了立住了"])
def test_shows_prefix_normalizes_without_changing_body(prefix):
    assert moment_shows(prefix + "冷傲与担当") == "冷傲与担当"
    assert moment_shows("没有立住的戏") == "没有立住的戏"
    person = {"rows": [(1, {"shown": "出现"})], "moments": [(1, {"what": "出手", "shows": prefix + "冷傲与担当"})]}
    assert dossier_of(person) == "第 1 章：出现\n第 1 章名场面：出手——立住了冷傲与担当"


async def test_card_model_alias_only_names_mapping_and_moment_storage(sessionmaker):
    bid, *_ = await fixture_book(sessionmaker)

    async def cancelled():
        return False

    runner = SimpleNamespace(sm=sessionmaker, book_id=bid, cancelled=cancelled)
    writer = SettingsWriter(runner, 50)
    from app.services.teardown_roster import Roster

    roster = Roster()
    roster.add([{"index": 1, "people": [p("少女", also_called=["茉莉", "姐夫", "爷爷", "少爷", "前辈"])]}])
    person = {**roster.people[0], "key_name": "少女"}
    card = s.TeardownCard(
        name="茉莉",
        aliases=["小茉莉"],
        one_line="少女",
        role_type="配角",
        moments=[s.TeardownCardMoment(chapter=1, what="出手", shows="立住了：冷傲")],
    )
    await writer.character(person, card, roster=roster)
    async with sessionmaker() as session:
        row = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "茉莉"))
        book = await session.get(Book, bid)
        assert row.aliases == ["小茉莉"]
        assert row.extra["名场面"] == "第 1 章：出手——立住了冷傲"
        assert book.teardown["names"]["少女"] == "茉莉"


def trial_files(directory):
    directory.mkdir(exist_ok=True)
    cards = [
        {
            "name": "旧名",
            "chapters": 2,
            "card": {
                "name": "旧名",
                "aliases": ["主角"],
                "gender": "男",
                "age": "（记录里没有）",
                "relation": "主角本人",
                "power": "初玄",
                "now": {"location": "城", "alive": True},
                "moments": [{"chapter": 1, "what": "出手", "shows": "立住了冷傲"}],
            },
        }
    ]
    world = {
        "factions": [{"name": "宗门", "what": "组织", "first_chapter": 1}],
        "places": [
            {"name": "城", "note": "城池", "parent": "大陆", "first_chapter": 1},
            {"name": "大陆", "note": "大地", "first_chapter": 1},
        ],
        "ladders": [
            {"name": "境界", "how_up": "苦修", "levels": [{"name": "初玄", "note": "初始", "protagonist_chapter": 1}]}
        ],
    }
    merits = {"merits": {"points": [{"topic": "开头", "text": "第1章抓人"}], "missing": []}}
    for name, value in [("cards", cards), ("world", world), ("merits", merits)]:
        (directory / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


async def test_seed_trial_reuses_writes_only_listed_rows_no_model_protects_author(sessionmaker, tmp_path, monkeypatch):
    bid, *_ = await fixture_book(sessionmaker)
    directory = tmp_path / "trial"
    trial_files(directory)

    def forbidden(*args, **kwargs):
        raise AssertionError("不能调模型")

    monkeypatch.setattr("app.llm.router.LLMRouter.structured", forbidden)
    result = await seed_trial(sessionmaker, bid, directory)
    assert result["cards"] == 1 and result["upto"] == 50
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["settings"]["upto"] == 50 and book.teardown["merits"]["points"][0]["text"] == "第1章抓人"
        row = await session.scalar(select(Character).where(Character.book_id == bid, Character.name == "旧名"))
        assert (
            row.age == ""
            and row.one_line == "主角本人"
            and row.role_type == "主角"
            and row.extra["实力与地位"] == "初玄"
        )
        assert await session.scalar(select(func.count()).select_from(WorldEntry).where(WorldEntry.book_id == bid)) == 4
        assert not await session.scalar(
            select(WorldEntry.id).where(WorldEntry.book_id == bid, WorldEntry.name == "世界概况")
        )
        city = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid, WorldEntry.name == "城"))
        assert city.parent_id is not None
        row.one_line = "作者手改"
        await session.commit()
    result = await seed_trial(sessionmaker, bid, directory)
    assert "旧名" in result["skipped"]
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(Character.one_line).where(Character.book_id == bid, Character.name == "旧名"))
            == "作者手改"
        )


async def test_seed_trial_positions_keep_each_source_array_order_on_repeated_seed(client, sessionmaker, tmp_path):
    bid, *_ = await fixture_book(sessionmaker)
    directory = tmp_path / "trial"
    trial_files(directory)
    cards = json.loads((directory / "cards.json").read_text(encoding="utf-8"))
    cards.append({"name": "后者", "chapters": 1, "card": {"name": "后者", "relation": "配角"}})
    (directory / "cards.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    world = {
        "ladders": [{"name": f"{x}等级", "levels": []} for x in ("乙", "甲")],
        "goldfingers": [{"name": f"{x}机缘", "what": "机缘"} for x in ("乙", "甲")],
        "places": [{"name": f"{x}地方", "note": "地点"} for x in ("乙", "甲")],
        "factions": [{"name": f"{x}势力", "what": "势力"} for x in ("乙", "甲")],
        "items": [{"name": f"{x}宝物", "note": "物品"} for x in ("乙", "甲")],
        "secrets": [{"name": f"{x}秘密", "truth": "真相"} for x in ("乙", "甲")],
        "rules": [{"name": f"{x}规矩", "note": "规矩"} for x in ("乙", "甲")],
    }
    (directory / "world.json").write_text(json.dumps(world, ensure_ascii=False), encoding="utf-8")
    categories = {
        "等级体系": "ladders",
        "金手指": "goldfingers",
        "世界与地图": "places",
        "势力划分": "factions",
        "物品与功法": "items",
        "往事与秘密": "secrets",
        "特殊规则": "rules",
    }
    for repeat in range(2):
        await seed_trial(sessionmaker, bid, directory)
        library = (await client.get(f"/api/books/{bid}/library")).json()
        assert [row["name"] for row in library["characters"] if row["source"] == "teardown"] == ["旧名", "后者"]
        for category, key in categories.items():
            rows = [row for row in library["entries"] if row["category"] == category]
            assert [row["name"] for row in rows] == [item["name"] for item in world[key]]
            assert [row["position"] for row in rows] == [0, 1]
        if not repeat:
            # 模拟以前的无序灌入结果；重灌不能继续依赖同批 created_at/UUID 的偶然先后。
            async with sessionmaker() as session:
                for model in (Character, WorldEntry):
                    for row in await session.scalars(
                        select(model).where(model.book_id == bid, model.source == "teardown")
                    ):
                        row.position = 100 - row.position
                await session.commit()


def test_seed_conversion_does_not_mutate_source_and_daily_database_rejected():
    raw = {
        "name": "人",
        "aliases": [],
        "age": "（记录里没有）",
        "relation": "关系",
        "power": "实力",
        "now": {"location": "（记录里没有）"},
    }
    before = copy.deepcopy(raw)
    got = trial_card(raw, "人")
    assert got.age == "" and got.now.location == "" and got.one_line == "关系" and got.now.power == "实力"
    assert raw == before
    for url in ("postgresql+psycopg://u:p@127.0.0.1:5551/zhibi", "postgresql://u:p@remote/zhibi"):
        with pytest.raises(ValueError, match="日常库"):
            ensure_trial_database(url)
    ensure_trial_database("postgresql+psycopg://u:p@127.0.0.1:5551/zhibi_deskv2_accept")


async def test_seed_refuses_running_job_and_invalid_file_before_any_writes(sessionmaker, tmp_path):
    bid, *_ = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        session.add(Job(book_id=bid, kind="teardown", thread_id="test", status="running"))
        await session.commit()
    with pytest.raises(ValueError, match="有任务在跑"):
        await seed_trial(sessionmaker, bid, tmp_path)


async def test_existing_book_library_bible_readonly_projections(client, sessionmaker):
    bid, *_, cid, _ = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {
            **book.teardown,
            "settings": {
                "upto": 50,
                "inputs": {"secret": "do not return"},
                "rows": {"x": {"hash": "hidden"}},
                "pending_ties": {},
            },
            "merits": {
                "upto": 50,
                "points": [{"topic": "开头", "text": "第1章抓人"}],
                "missing": ["缺数字"],
                "at": "时间不必暴露",
            },
        }
        character = await session.get(Character, cid)
        character.first_appearance_chapter = 12
        second = Character(book_id=bid, name="对方")
        session.add(second)
        await session.flush()
        session.add(
            Relationship(
                book_id=bid, source_id=cid, target_id=second.id, kind="师徒", description="关系", since_chapter=44
            )
        )
        session.add(
            WorldEntry(
                book_id=bid,
                category="等级体系",
                name="境界",
                style="ladder",
                created_chapter=2,
                levels=[{"name": "初玄", "text": "基础", "protagonist_chapter": 46}],
            )
        )
        await session.commit()
    book = (await client.get(f"/api/books/{bid}")).json()["teardown"]
    assert book["settings"] == {"upto": 50}
    assert "merits" not in book and book["essence"] is None
    assert book["names"] == {"旧名": "主角"}
    assert not {"inputs", "rows", "pending_ties"}.intersection(book)
    library = (await client.get(f"/api/books/{bid}/library")).json()
    assert next(c for c in library["characters"] if c["id"] == str(cid))["first_appearance_chapter"] == 12
    assert library["entries"][0]["created_chapter"] == 2
    assert library["entries"][0]["levels"][0]["protagonist_chapter"] == 46
    bible = (await client.get(f"/api/books/{bid}/bible")).json()
    assert bible["relationships"][0]["since_chapter"] == 44
    assert bible["world_entries"][0]["levels"][0]["protagonist_chapter"] == 46


async def test_ladder_level_edit_delete_roundtrip_preserves_chapters_and_versions(client, sessionmaker):
    bid, *_ = await fixture_book(sessionmaker)
    original = [
        {"name": "初玄", "text": "初始", "protagonist_chapter": 46},
        {"name": "入玄", "text": "进阶", "protagonist_chapter": 56},
        {"name": "真玄", "text": "尚未到", "protagonist_chapter": None},
    ]
    async with sessionmaker() as session:
        row = WorldEntry(
            book_id=bid, category="等级体系", name="玄力", style="ladder", source="teardown", levels=original
        )
        session.add(row)
        await session.commit()
        eid = row.id
    edited = [
        {**original[0], "name": "初玄境"},
        {**original[1], "text": "作者补的说明"},
        original[2],
    ]
    for levels in (edited, edited[1:]):
        response = await client.patch(f"/api/world-entries/{eid}", json={"levels": levels})
        assert response.status_code == 200
        assert response.json()["levels"] == levels
        for route, key in (("library", "entries"), ("bible", "world_entries")):
            book = (await client.get(f"/api/books/{bid}/{route}")).json()
            assert next(item for item in book[key] if item["id"] == str(eid))["levels"] == levels
        async with sessionmaker() as session:
            saved = await session.get(WorldEntry, eid)
            assert saved.levels == levels
            assert saved.source == "ai_edited"
            version = await session.scalar(
                select(SettingVersion)
                .where(SettingVersion.target_type == "entry", SettingVersion.target_id == eid)
                .order_by(SettingVersion.version.desc())
            )
            assert version.snapshot["levels"] == levels


async def test_legacy_ladder_without_chapter_create_patch_keeps_old_storage(client, sessionmaker):
    bid, *_ = await fixture_book(sessionmaker)
    levels = [{"name": "初级", "text": "旧格式"}, {"name": "中级", "text": "尚未标章号"}]
    response = await client.post(
        f"/api/books/{bid}/world-entries", json={"category": "等级体系", "name": "普通等级", "levels": levels}
    )
    assert response.status_code == 201
    eid = uuid.UUID(response.json()["id"])
    assert response.json()["levels"] == [{**item, "protagonist_chapter": None} for item in levels]
    edited = [{**levels[0], "text": "旧级修改"}, levels[1]]
    response = await client.patch(f"/api/world-entries/{eid}", json={"levels": edited})
    assert response.status_code == 200
    assert response.json()["levels"] == [{**item, "protagonist_chapter": None} for item in edited]
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, eid)).levels == edited
        version = await session.scalar(
            select(SettingVersion)
            .where(SettingVersion.target_type == "entry", SettingVersion.target_id == eid)
            .order_by(SettingVersion.version.desc())
        )
        assert version.snapshot["levels"] == edited


def test_actual_trial_files_all_convert_without_synthetic_rows():
    directory = ROOT / "data/拆书试验/逆天邪神前五十章/整理设定"
    if not directory.exists():
        pytest.skip("只在本机验收材料存在时检查真实旧格式")
    cards = json.loads((directory / "cards.json").read_text(encoding="utf-8"))
    world = json.loads((directory / "world.json").read_text(encoding="utf-8"))
    converted = [trial_card(item["card"], "萧澈") for item in cards]
    assert len(converted) == len(cards) == 8
    assert converted[0].one_line == cards[0]["card"]["relation"]
    results = dict(trial_world(world))
    assert len(results["地方"].items) == len(world["places"])
    assert results["地方"].world == ""
    assert results["势力"].items[0].note == world["factions"][0]["what"]


async def test_sample_data_script_main_keeps_name_map_after_card_appearances(
    client, sessionmaker, tmp_path, monkeypatch
):
    """执行完整 main；卡出场循环结束后还会调用闭包 people_count，不能遮蔽映射。"""
    path = ROOT / "docs/界面原型/取样张数据.py"
    spec = importlib.util.spec_from_file_location("desk_v2_sample_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trial = tmp_path / "trial"
    (trial / "整理设定").mkdir(parents=True)
    (trial / "read").mkdir()
    (tmp_path / "docs/界面原型").mkdir(parents=True)
    for name, value in {
        "cards": [{"chapters": 2, "card": {"name": "萧澈", "aliases": ["云澈"]}}],
        "world": {},
        "merits": {"points": []},
    }.items():
        (trial / f"整理设定/{name}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    (trial / "read/batch_001.json").write_text('{"chapters": [{"index": 1}, {"index": 2}]}', encoding="utf-8")
    records = {
        1: {"people": [p("云澈", change="苏醒"), p("萧澈")], "things": [], "waits": []},
        2: {"people": [p("云澈", change="启程")], "things": [], "waits": []},
    }
    async with sessionmaker() as session:
        book = Book(title="测试原书", source="teardown", teardown={"names": {"云澈": "萧澈"}})
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="卷")
        session.add(volume)
        await session.flush()
        for index, read in records.items():
            session.add(
                Chapter(book_id=book.id, index=index, volume_id=volume.id, teardown={"read_version": 1, "read": read})
            )
        await session.commit()
        bid, vid = book.id, volume.id
    public_book = (await client.get(f"/api/books/{bid}")).json()
    digest = (await client.get(f"/api/books/{bid}/teardown/digest", params={"volume": str(vid)})).json()

    def fake_get(route):
        if route == "":
            return public_book
        if route == "/outline-tree":
            return {
                "arcs": [
                    {
                        "volumes": [
                            {
                                "index": 1,
                                "title": "卷",
                                "chapter_count": 2,
                                "units": [{"title": "单元", "chapters": [{"index": 1}, {"index": 2}]}],
                            }
                        ]
                    }
                ]
            }
        if route == "/chapters?with_outline=true":
            return [{"index": i, "title": f"章{i}", "outline": {}} for i in (1, 2)]
        return {"teardown": {"read": records.get(int(route.rsplit("/", 1)[-1]), {})}}

    monkeypatch.setattr(module, "get", fake_get)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "TRIAL", trial)
    monkeypatch.setattr("sys.argv", [str(path), "--api", "http://unused.invalid/api", "--book", "fixture"])
    module.main()
    text = (tmp_path / "docs/界面原型/装修样张-数据.js").read_text(encoding="utf-8")
    data = json.loads(text.split("window.DATA = ", 1)[1])
    assert data["vol1"]["people"] == [["萧澈", 2, 1]]
    assert data["vol1"]["hero"] == "萧澈"
    assert data["vol1"]["changes"] == [[1, "苏醒"], [2, "启程"]]
    assert data["trial"]["appear"] == {"萧澈": [1, 2]}
    assert data["vol1"]["people"] == [[item["name"], item["chapters"], item["first"]] for item in digest["people"]]
    assert data["vol1"]["hero"] == digest["hero"]
    assert data["vol1"]["changes"] == [[item["chapter"], item["change"]] for item in digest["changes"]]
