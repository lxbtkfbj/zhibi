"""新工作台：角色卡新栏目、条目按栏目改、每本书自己调栏目、空书能自己搭大纲。"""

import httpx
import pytest
from redis.asyncio import Redis

from app.config import get_settings
from app.main import create_app


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


async def test_character_extra_fields_merge_and_clear(client):
    book = await blank_book(client)
    res = await client.post(
        f"/api/books/{book}/characters", json={"name": "陈默", "role_type": "主角", "extra": {"软肋": " 怕死 "}}
    )
    assert res.status_code == 201, res.text
    person = res.json()
    assert person["extra"] == {"软肋": "怕死"}

    res = await client.patch(f"/api/characters/{person['id']}", json={"extra": {"所属": "青冥宗外门"}})
    assert res.json()["extra"] == {"软肋": "怕死", "所属": "青冥宗外门"}
    res = await client.patch(f"/api/characters/{person['id']}", json={"extra": {"软肋": ""}})
    assert res.json()["extra"] == {"所属": "青冥宗外门"}

    library = (await client.get(f"/api/books/{book}/library")).json()
    assert library["characters"][0]["extra"] == {"所属": "青冥宗外门"}


async def test_entry_field_values_merge_into_fields(client):
    book = await blank_book(client)
    res = await client.post(
        f"/api/books/{book}/world-entries",
        json={"category": "势力划分", "name": "青冥宗", "content": "东荒第一宗门", "fields": [{"name": "领头的", "value": "青冥老祖"}]},
    )
    entry = res.json()
    res = await client.patch(f"/api/world-entries/{entry['id']}", json={"field_values": {"对主角": "敌", "领头的": "宗主"}})
    assert res.status_code == 200, res.text
    assert res.json()["fields"] == [{"name": "领头的", "value": "宗主"}, {"name": "对主角", "value": "敌"}]
    res = await client.patch(f"/api/world-entries/{entry['id']}", json={"field_values": {"领头的": ""}})
    assert res.json()["fields"] == [{"name": "对主角", "value": "敌"}]
    assert res.json()["content"] == "东荒第一宗门"


async def test_card_layout_rename_moves_content_and_drop_clears_it(client):
    book = await blank_book(client)
    person = (
        await client.post(
            f"/api/books/{book}/characters",
            json={"name": "陈默", "role_type": "主角", "appearance": "瘦", "extra": {"软肋": "怕死", "口头禅": "稳住"}},
        )
    ).json()
    layout = {
        "facts": [{"key": "定位", "label": "定位"}],
        "sections": [{"key": "外貌", "label": "长相"}, {"key": "软肋", "label": "弱点"}],
        "dropped": ["口头禅"],
    }
    res = await client.put(f"/api/books/{book}/card-layouts/角色列表", json=layout)
    assert res.status_code == 200, res.text
    # 有专门一列的只改显示名；放在 extra 里的连内容一起改名
    assert res.json()["sections"] == [{"key": "外貌", "label": "长相"}, {"key": "弱点", "label": "弱点"}]
    library = (await client.get(f"/api/books/{book}/library")).json()
    saved = next(c for c in library["characters"] if c["id"] == person["id"])
    assert saved["appearance"] == "瘦"
    assert saved["extra"] == {"弱点": "怕死"}
    detail = (await client.get(f"/api/books/{book}")).json()
    assert detail["card_layouts"]["角色列表"]["sections"][1] == {"key": "弱点", "label": "弱点"}

    res = await client.put(
        f"/api/books/{book}/card-layouts/角色列表",
        json={"facts": [], "sections": [], "dropped": ["定位"]},
    )
    assert res.status_code == 422

    res = await client.delete(f"/api/books/{book}/card-layouts/角色列表")
    assert res.status_code == 204
    assert "角色列表" not in (await client.get(f"/api/books/{book}")).json()["card_layouts"]


async def test_entry_layout_only_touches_its_own_category(client):
    book = await blank_book(client)
    place = (
        await client.post(
            f"/api/books/{book}/world-entries",
            json={"category": "世界与地图", "name": "后山", "content": "禁地", "fields": [{"name": "归谁管", "value": "老祖"}]},
        )
    ).json()
    overview = (
        await client.post(
            f"/api/books/{book}/world-entries",
            json={"category": "世界与地图", "name": "世界概况", "content": "九天大陆", "fields": [{"name": "归谁管", "value": "x"}]},
        )
    ).json()
    res = await client.put(
        f"/api/books/{book}/card-layouts/地点列表",
        json={"facts": [], "sections": [{"key": "内容", "label": "写点什么"}], "dropped": ["归谁管"]},
    )
    assert res.status_code == 200, res.text
    assert res.json()["sections"] == [{"key": "内容", "label": "写点什么"}]
    entries = {e["id"]: e for e in (await client.get(f"/api/books/{book}/library")).json()["entries"]}
    assert entries[place["id"]]["fields"] == []
    assert entries[place["id"]]["content"] == "禁地"
    # 世界概况不算地点，不跟着清
    assert entries[overview["id"]]["fields"] == [{"name": "归谁管", "value": "x"}]


async def test_custom_ladder_category_and_card_fields_follow_layout(client):
    book = await blank_book(client)
    ladder = await client.post(f"/api/books/{book}/setting-categories", json={"name": "厉鬼等级", "style": "ladder"})
    assert ladder.status_code == 201, ladder.text
    card = (
        await client.post(
            f"/api/books/{book}/setting-categories", json={"name": "厉鬼", "style": "card", "fields": ["杀人规律"]}
        )
    ).json()
    res = await client.put(
        f"/api/books/{book}/card-layouts/custom:{card['key']}",
        json={"facts": [{"key": "等级", "label": "等级"}], "sections": [{"key": "杀人规律", "label": "杀人规律"}]},
    )
    assert res.status_code == 200, res.text
    categories = (await client.get(f"/api/books/{book}/setting-categories")).json()
    assert next(c for c in categories if c["id"] == card["id"])["fields"] == ["等级", "杀人规律"]
    res = await client.put(
        f"/api/books/{book}/card-layouts/custom:{ladder.json()['key']}", json={"facts": [], "sections": []}
    )
    assert res.status_code == 422


async def test_blank_book_builds_outline_by_hand(client):
    book = await blank_book(client)
    res = await client.post(f"/api/books/{book}/volumes", json={})
    assert res.status_code == 201, res.text
    volume = res.json()
    assert volume["title"] == ""
    res = await client.post(f"/api/volumes/{volume['id']}/units", json={"chapter_count": 6})
    assert res.status_code == 201, res.text
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    saved = tree["arcs"][0]["volumes"][0]
    assert [u["chapter_count"] for u in saved["units"]] == [6]
    assert saved["chapter_count"] == 6


async def test_editing_blurb_on_new_page_does_not_call_editorial(client, sessionmaker):
    from sqlalchemy import func, select

    from app.models import LlmCall

    book = await blank_book(client)
    await client.post(f"/api/books/{book}/characters", json={"name": "陈默", "role_type": "主角"})
    res = await client.patch(f"/api/books/{book}", json={"concept": {"story": "改过的简介"}, "review_changes": False})
    assert res.status_code == 200, res.text
    assert res.json()["concept"]["story"] == "改过的简介"
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(LlmCall)) == 0
