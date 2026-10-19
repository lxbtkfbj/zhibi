"""新书页第三步：选中文字的小按钮（局部改写能改角色自定栏目、带回撤销用的版本）、编辑部帮写几条候选。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import MeetingMessage


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def blank_book(client) -> str:
    res = await client.post("/api/books", json={"start_setup": False, "title": "寿命簿", "genre": "玄幻"})
    assert res.status_code == 201, res.text
    return res.json()["book"]["id"]


async def messages(sessionmaker) -> int:
    async with sessionmaker() as session:
        return await session.scalar(select(func.count()).select_from(MeetingMessage))


# ---------- 选中文字的小按钮 ----------


async def test_rewrite_character_extra_quietly_and_undo(client, sessionmaker):
    book = await blank_book(client)
    hero = (
        await client.post(
            f"/api/books/{book}/characters",
            json={"name": "陈默", "role_type": "主角", "extra": {"软肋": "怕死，更怕妹妹死"}},
        )
    ).json()
    before = await messages(sessionmaker)
    res = await client.post(
        f"/api/books/{book}/library/rewrite",
        json={
            "target_type": "character",
            "target_id": hero["id"],
            "path": "extra.软肋@3:8",
            "mode": "expand",
            "quiet": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["applied"]["before"] == "怕死，更怕妹妹死"
    assert body["applied"]["after"] == "怕死，更怕妹妹死（已按要求修改）"
    assert body["revert_version_id"]
    # 新书页上改：不在群聊里再说一遍
    assert await messages(sessionmaker) == before

    res = await client.post(f"/api/versions/{body['revert_version_id']}/revert")
    assert res.status_code == 200, res.text
    library = (await client.get(f"/api/books/{book}/library")).json()
    assert library["characters"][0]["extra"] == {"软肋": "怕死，更怕妹妹死"}


async def test_options_quietly_then_choose_returns_undo(client, sessionmaker):
    book = await blank_book(client)
    entry = (
        await client.post(
            f"/api/books/{book}/world-entries",
            json={"category": "特殊规则", "name": "借寿", "content": "寿命能借，三年后收回。"},
        )
    ).json()
    before = await messages(sessionmaker)
    res = await client.post(
        f"/api/books/{book}/library/rewrite",
        json={
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "content@0:5",
            "mode": "options",
            "quiet": True,
        },
    )
    assert res.status_code == 200, res.text
    candidate = res.json()["candidate"]
    assert [o["label"] for o in candidate["options"]] == ["稳妥", "大胆", "出格"]
    assert await messages(sessionmaker) == before
    res = await client.post(f"/api/candidates/{candidate['id']}/choose", json={"index": 1})
    assert res.status_code == 200, res.text
    assert res.json()["revert_version_id"]
    assert res.json()["target"]["content"].startswith("（大胆）")


# ---------- 编辑部帮写 ----------


async def test_draft_characters_follow_the_book_columns_and_skip_taken_names(client):
    book = await blank_book(client)
    await client.post(f"/api/books/{book}/characters", json={"name": "演示角色1", "role_type": "配角"})
    res = await client.post(
        f"/api/books/{book}/drafts",
        json={
            "category": "角色列表",
            "request": "写两个对手",
            "count": 3,
            "facts": [{"key": "定位", "label": "定位"}, {"key": "所属", "label": "门派"}],
            "sections": [{"key": "外貌", "label": "外貌"}, {"key": "软肋", "label": "软肋"}],
        },
    )
    assert res.status_code == 200, res.text
    entries = res.json()["entries"]
    # 名字撞了已有的就不要
    assert [e["name"] for e in entries] == ["演示角色2", "演示角色3"]
    # 栏目按显示名写，交回来按存内容时认的名字
    assert entries[0]["values"] == {
        "定位": "配角",
        "所属": "（演示）第2条的门派",
        "外貌": "（演示）第2条的外貌",
        "软肋": "（演示）第2条的软肋",
        "实力与地位": "（演示）第2条的实力与地位",
    }
    # 什么都没存
    library = (await client.get(f"/api/books/{book}/library")).json()
    assert [c["name"] for c in library["characters"]] == ["演示角色1"]

    # 收下一条：按新增一条存，来源记成从候选里收下的
    res = await client.post(
        f"/api/books/{book}/characters",
        json={
            "name": entries[0]["name"],
            "role_type": "配角",
            "appearance": entries[0]["values"]["外貌"],
            "source": "candidate",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["source"] == "candidate"


async def test_draft_ladder_and_goldfinger_and_custom(client):
    book = await blank_book(client)
    res = await client.post(f"/api/books/{book}/drafts", json={"category": "等级体系", "count": 1})
    assert res.status_code == 200, res.text
    ladder = res.json()["entries"][0]
    assert ladder["values"] == {"总说明": "一级一级往上走，越级要付代价。"}
    assert [level["name"] for level in ladder["levels"]] == ["第1套一阶", "第1套二阶"]

    res = await client.post(
        f"/api/books/{book}/drafts",
        json={
            "category": "金手指",
            "count": 2,
            "facts": [{"key": "是什么", "label": "是什么"}],
            "sections": [{"key": "能做什么", "label": "能做什么"}],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["entries"][1]["values"] == {
        "是什么": "（演示）第2条的是什么",
        "能做什么": "（演示）第2条的能做什么",
    }

    res = await client.post(f"/api/books/{book}/drafts", json={"category": "custom:nothing", "count": 1})
    assert res.status_code == 404
    res = await client.post(f"/api/books/{book}/drafts", json={"category": "胡写的类别", "count": 1})
    assert res.status_code == 422


async def test_rewrite_finds_the_quote_when_offsets_drift(client):
    book = await blank_book(client)
    entry = (
        await client.post(
            f"/api/books/{book}/world-entries",
            json={"category": "特殊规则", "name": "借寿", "content": "前言。寿命能借，三年后收回。"},
        )
    ).json()
    # 页面算的位置偏了三个字：按选中的原字重新找
    res = await client.post(
        f"/api/books/{book}/library/rewrite",
        json={
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "content@0:5",
            "mode": "expand",
            "quote": "寿命能借，",
            "quiet": True,
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["applied"]["after"] == "前言。寿命能借，（已按要求修改）三年后收回。"
    # 原字已经不在了：不改
    res = await client.post(
        f"/api/books/{book}/library/rewrite",
        json={
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "content@0:3",
            "mode": "expand",
            "quote": "没有这句",
            "quiet": True,
        },
    )
    assert res.status_code == 409


# ---------- 补齐一条 ----------


async def test_fill_entry_only_fills_empty_columns_and_can_be_undone(client):
    book = await blank_book(client)
    hero = (
        await client.post(
            f"/api/books/{book}/characters", json={"name": "封不觉", "role_type": "主角", "gender": "男", "age": "19"}
        )
    ).json()
    assert hero["status"] == "later"
    res = await client.post(f"/api/books/{book}/fill-entry", json={"target_type": "character", "target_id": hero["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    # 定位、性别、年龄写过了不补；所属、别名和正文栏目补上
    assert body["filled"] == [
        "所属",
        "别名",
        "外貌",
        "性格与说话方式",
        "身世",
        "想要什么",
        "软肋",
        "能力",
        "成长与结局",
        "备注",
        "实力与地位",
    ]
    library = (await client.get(f"/api/books/{book}/library")).json()
    person = library["characters"][0]
    assert person["gender"] == "男" and person["age"] == "19" and person["role_type"] == "主角"
    assert person["appearance"] == "（演示）补上的外貌" and person["extra"]["软肋"] == "（演示）补上的软肋"
    assert person["aliases"] == ["（演示）补上的别名"] and person["status"] == "must"
    res = await client.post(f"/api/versions/{body['revert_version_id']}/revert")
    assert res.status_code == 200, res.text
    library = (await client.get(f"/api/books/{book}/library")).json()
    assert library["characters"][0]["appearance"] == ""

    # 每一栏都写了：什么也不补
    rule = (
        await client.post(
            f"/api/books/{book}/world-entries", json={"category": "特殊规则", "name": "借寿", "content": "寿命能借。"}
        )
    ).json()
    res = await client.post(f"/api/books/{book}/fill-entry", json={"target_type": "entry", "target_id": rule["id"]})
    assert res.json()["filled"] == []
    # 锁住的不补
    await client.patch(f"/api/characters/{hero['id']}", json={"locked": True})
    res = await client.post(f"/api/books/{book}/fill-entry", json={"target_type": "character", "target_id": hero["id"]})
    assert res.status_code == 409


async def test_group_chat_fill_and_unclear_part_never_renames(client, sessionmaker, monkeypatch):
    from app.agents import schemas as s
    from app.services import group_notes
    from tests.test_chat_task6 import final_message

    book = await blank_book(client)
    hero = (await client.post(f"/api/books/{book}/characters", json={"name": "封不觉", "role_type": "主角"})).json()

    async def fill_intent(*args, **kwargs):
        return s.LibraryIntent(kind="改设定", target_name="封不觉", mode="补齐空着的", reply="好")

    monkeypatch.setattr(group_notes, "call_model", fill_intent)
    res = await client.post(f"/api/books/{book}/notes", json={"content": "帮我把封不觉的设定补齐"})
    outcome = (await final_message(client, book, res.json()["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "fill" and outcome["target_label"] == "封不觉" and "外貌" in outcome["filled"]

    # 上一回的情形：说不清改哪一栏、模式是给几个写法，卡又是空的——以前会给名字出改名方案
    other = (await client.post(f"/api/books/{book}/characters", json={"name": "苏小蝶", "role_type": "女主"})).json()

    async def unclear_intent(*args, **kwargs):
        return s.LibraryIntent(kind="改设定", target_name="苏小蝶", part="角色卡各字段", mode="给几个写法")

    monkeypatch.setattr(group_notes, "call_model", unclear_intent)
    res = await client.post(f"/api/books/{book}/notes", json={"content": "苏小蝶写全一点"})
    outcome = (await final_message(client, book, res.json()["id"]))["payload"]["outcome"]
    assert outcome["kind"] == "fill"
    library = (await client.get(f"/api/books/{book}/library")).json()
    assert {c["name"] for c in library["characters"]} == {"封不觉", "苏小蝶"}
    assert other["id"] in {c["id"] for c in library["characters"]}
    assert hero["id"] in {c["id"] for c in library["characters"]}
