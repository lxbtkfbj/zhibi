"""第二包数据底座接口：只加字段，保留旧流程与作者已保存内容。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import Book, Character, Job, MeetingMessage, PlotUnit, StoryNode, Volume
from app.schemas import JobOut
from app.services import jobs
from app.services.meeting import job_dict


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(jobs, "enqueue", lambda *args: None)
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


@pytest.fixture
async def story(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="旧书的数据底座", status="ready", settings={})
        session.add(book)
        await session.flush()
        node = StoryNode(book_id=book.id, position=1, kind="milestone", title="走出小镇")
        character = Character(book_id=book.id, name="林岚", goal="寻找故乡")
        volume = Volume(book_id=book.id, index=1, title="青石镇")
        session.add_all([node, character, volume])
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="拿回信物")
        session.add(unit)
        await session.commit()
        return {"book": book.id, "node": node.id, "character": character.id, "volume": volume.id, "unit": unit.id}


async def test_legacy_empty_cards_and_top_level_merge(client, story):
    path = f"/api/books/{story['book']}"
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json()["protagonist"] == response.json()["world"] == {}
    original = {
        "protagonist": {
            "name": "林岚",
            "pursuit": "找回故乡",
            "finger_later": "作者已定的成长",
            "cared": [{"name": "林小雨", "relation": "妹妹", "why": "相依为命"}],
        },
        "world": {
            "surface": "异能公开",
            "maps": [{"name": "青石镇", "powers": "镇守府", "ceiling": "初阶"}],
            "far_maps": [{"name": "北境", "line": "雪原"}],
            "mystery_answer": "作者已定的谜底",
        },
    }
    response = await client.patch(path, json=original)
    assert response.status_code == 200
    assert response.json()["protagonist"] == original["protagonist"]
    assert response.json()["world"] == original["world"]
    response = await client.patch(
        path,
        json={
            "protagonist": {"name": "林清岚", "cared": []},
            "world": {"maps": [{"name": "新城"}], "far_maps": []},
        },
    )
    assert response.status_code == 200
    expected = {
        "protagonist": {**original["protagonist"], "name": "林清岚", "cared": []},
        "world": {**original["world"], "maps": [{"name": "新城"}], "far_maps": []},
    }
    for key, value in expected.items():
        assert response.json()[key] == value
    await client.patch(path, json={"protagonist": {}, "world": {}, "title": "只改书名"})
    saved = (await client.get(path)).json()
    assert saved["protagonist"] == expected["protagonist"]
    assert saved["world"] == expected["world"]


@pytest.mark.parametrize(
    "body",
    [
        {"protagonist": {"unknown": "未知"}},
        {"world": {"unknown": "未知"}},
        {"protagonist": {"cared": [{"name": "妹妹", "unknown": "未知"}]}},
        {"world": {"maps": [{"name": "小镇", "unknown": "未知"}]}},
        {"world": {"far_maps": [{"name": "北境", "unknown": "未知"}]}},
    ],
)
async def test_cards_reject_unknown_keys_including_nested_elements(client, story, body):
    response = await client.patch(f"/api/books/{story['book']}", json=body)
    assert response.status_code == 422
    assert "不认识的字段：unknown" in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"protagonist": []},
        {"protagonist": None},
        {"protagonist": {"name": 7}},
        {"protagonist": {"pursuit": None}},
        {"protagonist": {"cared": "妹妹"}},
        {"protagonist": {"cared": [{"name": False}]}},
        {"world": None},
        {"world": {"power": {"text": "力量规则"}}},
        {"world": {"maps": {"name": "小镇"}}},
        {"world": {"maps": [{"powers": 1}]}},
        {"world": {"far_maps": ["北境"]}},
        {"world": {"far_maps": [{"line": None}]}},
    ],
)
async def test_cards_reject_wrong_types_without_writing(client, story, body):
    path = f"/api/books/{story['book']}"
    response = await client.patch(path, json={"title": "不该保存", **body})
    assert response.status_code == 422
    saved = (await client.get(path)).json()
    assert saved["title"] == "旧书的数据底座"
    assert saved["protagonist"] == saved["world"] == {}


async def test_unplanned_node_cannot_be_planned_by_patch(client, story):
    nodes = (await client.get(f"/api/books/{story['book']}/nodes")).json()
    assert nodes[0]["segment"] is None
    response = await client.patch(f"/api/nodes/{story['node']}", json={"segment": {"goal": "赢过镇守"}})
    assert response.status_code == 422
    assert response.json()["detail"] == "这一段还没规划，写到这里时主编会来定"


async def planned_segment(sessionmaker, node_id):
    segment = {
        "number": 1,
        "status": "confirmed",
        "planned_at": 0,
        "finale": False,
        "map": "青石镇",
        "goal": "拿回信物",
        "wait": "兄妹重逢",
        "opening": {"scene": "雨夜", "pressure": "债主逼门", "first_win": "反将一军", "hook": "故乡来信"},
    }
    async with sessionmaker() as session:
        node = await session.get(StoryNode, node_id)
        node.segment = segment
        await session.commit()
    return segment


async def test_planned_segment_merges_opening_by_subkey(client, story, sessionmaker):
    original = await planned_segment(sessionmaker, story["node"])
    path = f"/api/nodes/{story['node']}"
    response = await client.patch(path, json={"segment": {"goal": "救出妹妹", "opening": {"scene": "街头追逐"}}})
    assert response.status_code == 200
    expected = {**original, "goal": "救出妹妹", "opening": {**original["opening"], "scene": "街头追逐"}}
    assert response.json()["segment"] == expected
    response = await client.patch(path, json={"event": "作者改过节点", "segment": {"opening": {}}})
    assert response.status_code == 200
    assert response.json()["segment"] == expected
    nodes = (await client.get(f"/api/books/{story['book']}/nodes")).json()
    assert nodes[0]["segment"] == expected


async def test_segment_opening_can_be_cleared_and_rebuilt_without_changing_other_keys(client, story, sessionmaker):
    original = await planned_segment(sessionmaker, story["node"])
    path = f"/api/nodes/{story['node']}"
    cleared = await client.patch(path, json={"segment": {"opening": None}})
    assert cleared.status_code == 200
    assert cleared.json()["segment"] == {**original, "opening": None}
    rebuilt = await client.patch(path, json={"segment": {"opening": {"hook": "新的第三章钩子"}}})
    assert rebuilt.status_code == 200
    assert rebuilt.json()["segment"] == {**original, "opening": {"hook": "新的第三章钩子"}}


@pytest.mark.parametrize(
    "patch",
    [
        {"number": 2},
        {"status": "auto"},
        {"planned_at": 8},
        {"finale": True},
        {"unknown": "未知"},
        {"opening": {"unknown": "未知"}},
        {"goal": 8},
        {"opening": {"scene": False}},
        {"opening": "不能传字符串"},
        {"opening": []},
        "不能传字符串",
        [],
        None,
    ],
)
async def test_segment_rejects_program_fields_unknown_keys_and_wrong_types(client, story, sessionmaker, patch):
    original = await planned_segment(sessionmaker, story["node"])
    response = await client.patch(f"/api/nodes/{story['node']}", json={"segment": patch})
    assert response.status_code == 422
    nodes = (await client.get(f"/api/books/{story['book']}/nodes")).json()
    assert nodes[0]["segment"] == original


async def test_want_pressure_loop_roundtrip_and_omission(client, story):
    bible = (await client.get(f"/api/books/{story['book']}/bible")).json()
    assert bible["characters"][0]["want"] == ""
    outline = (await client.get(f"/api/books/{story['book']}/outline")).json()
    assert outline["volumes"][0]["want"] == outline["volumes"][0]["pressure"] == ""
    assert outline["volumes"][0]["units"][0]["loop"] == ""
    for path, values in [
        (f"/api/characters/{story['character']}", {"want": "今夜救出妹妹"}),
        (f"/api/volumes/{story['volume']}", {"want": "拿到通行证", "pressure": "全城封锁"}),
        (f"/api/units/{story['unit']}", {"loop": "受压、找漏洞、反击"}),
    ]:
        response = await client.patch(path, json=values)
        assert response.status_code == 200
        assert all(response.json()[key] == value for key, value in values.items())
        assert (await client.patch(path, json={})).status_code == 200
        for key in values:
            assert (await client.patch(path, json={key: None})).status_code == 422
    created = await client.post(f"/api/books/{story['book']}/characters", json={"name": "妹妹", "want": "找到哥哥"})
    assert created.status_code == 201 and created.json()["want"] == "找到哥哥"
    bible = (await client.get(f"/api/books/{story['book']}/bible")).json()
    assert next(row for row in bible["characters"] if row["name"] == "林岚")["want"] == "今夜救出妹妹"
    volume = (await client.get(f"/api/books/{story['book']}/outline")).json()["volumes"][0]
    assert (volume["want"], volume["pressure"], volume["units"][0]["loop"]) == (
        "拿到通行证",
        "全城封锁",
        "受压、找漏洞、反击",
    )


async def test_new_data_edits_still_require_idle_department(client, story, sessionmaker):
    await planned_segment(sessionmaker, story["node"])
    async with sessionmaker() as session:
        session.add(Job(book_id=story["book"], kind="write_book", status="running", thread_id=str(uuid.uuid4())))
        await session.commit()
    for path, values in [
        (f"/api/books/{story['book']}", {"protagonist": {"name": "改名"}}),
        (f"/api/books/{story['book']}", {"world": {"power": "新规则"}}),
        (f"/api/nodes/{story['node']}", {"segment": {"goal": "新目标"}}),
        (f"/api/characters/{story['character']}", {"want": "新欲望"}),
        (f"/api/volumes/{story['volume']}", {"want": "新目标", "pressure": "新压力"}),
        (f"/api/units/{story['unit']}", {"loop": "新循环"}),
    ]:
        assert (await client.patch(path, json=values)).status_code == 409


async def test_setup_flow_http_and_sse_keep_legacy_and_future_versions(client, story, sessionmaker):
    async with sessionmaker() as session:
        for kind, params, expected in [("book_setup", {}, 1), ("book_setup", {"flow": 2}, 2), ("write_book", {}, None)]:
            job = Job(book_id=story["book"], kind=kind, status="succeeded", thread_id=str(uuid.uuid4()), params=params)
            session.add(job)
            await session.commit()
            response = await client.get(f"/api/jobs/{job.id}")
            assert response.status_code == 200 and response.json()["setup_flow"] == expected
            assert job_dict(job)["setup_flow"] == expected
            assert JobOut.model_validate(job_dict(job)).setup_flow == expected
    created = await client.post("/api/books", json={"idea": "一个少年寻找故乡的故事"})
    assert created.status_code == 201
    assert created.json()["job"]["setup_flow"] == created.json()["book"]["active_job"]["setup_flow"] == 3


async def test_segment_approval_defaults_copy_update_and_no_prompt_rules(client, story):
    path = f"/api/books/{story['book']}/settings"
    original = (await client.get(path)).json()
    defaults = (await client.get("/api/settings/new-book-defaults")).json()
    assert original["settings"]["segment_approval"] is defaults["settings"]["segment_approval"] is True
    response = await client.patch(path, json={"segment_approval": False})
    assert response.status_code == 200 and response.json()["settings"]["segment_approval"] is False
    assert response.json()["rules_text"] == original["rules_text"]
    response = await client.patch(path, json={"effort_preset": "premium"})
    assert response.json()["settings"]["segment_approval"] is False
    response = await client.put("/api/settings/new-book-defaults", json={"segment_approval": False})
    assert response.status_code == 200 and response.json()["settings"]["segment_approval"] is False
    assert response.json()["rules_text"] == defaults["rules_text"]
    created = (await client.post("/api/books", json={"idea": "一个少年寻找故乡的故事"})).json()
    new_path = f"/api/books/{created['book']['id']}/settings"
    assert (await client.get(new_path)).json()["settings"]["segment_approval"] is False
    await client.put("/api/settings/new-book-defaults", json={"segment_approval": True})
    assert (await client.get(new_path)).json()["settings"]["segment_approval"] is False
    assert (await client.patch(path, json={"segment_approval": None})).status_code == 422


async def test_live_setting_change_uses_chinese_label(client, story, sessionmaker):
    async with sessionmaker() as session:
        session.add(Job(book_id=story["book"], kind="write_book", status="running", thread_id=str(uuid.uuid4())))
        await session.commit()
    response = await client.patch(f"/api/books/{story['book']}/settings", json={"segment_approval": False})
    assert response.status_code == 200
    async with sessionmaker() as session:
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.book_id == story["book"]))
        assert message.content == "作者修改了本书设置：每一段开写前先给我确认：关闭"
