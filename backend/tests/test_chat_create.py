"""新书页群聊里让编辑部新建设定：「写一张封不觉的角色卡」照这一类的栏目写好，直接放进设定库，能撤销。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Character
from tests.test_chat_task6 import final_message


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


async def new_book(client) -> str:
    res = await client.post("/api/books", json={"start_setup": False, "title": "惊悚乐园外传", "genre": "悬疑"})
    return res.json()["book"]["id"]


async def say(client, book, text) -> dict:
    res = await client.post(f"/api/books/{book}/notes", json={"content": text})
    assert res.status_code == 201, res.text
    return await final_message(client, book, res.json()["id"])


async def test_group_chat_writes_a_new_character_card(client, monkeypatch, sessionmaker):
    book = await new_book(client)
    seen = {}

    async def fake_call(book_id, role, schema, template, **values):
        seen.update(values, template=template)
        return s.DraftSet(
            entries=[
                s.DraftEntry(
                    name="封不觉",
                    values=[
                        s.FieldValue(name="定位", value="配角"),
                        s.FieldValue(name="身世", value="推理小说作家，常年熬夜写稿"),
                        s.FieldValue(name="性格与说话方式", value="嘴毒，冷幽默"),
                        s.FieldValue(name="软肋", value="怕麻烦"),
                    ],
                )
            ],
            note="照原作的样子写，只是不当主角",
        )

    monkeypatch.setattr("app.api.workspace.call_model", fake_call)
    message = await say(client, book, "这是惊悚乐园的同人，请你写一张封不觉的角色卡")
    outcome = message["payload"]["outcome"]
    assert outcome["kind"] == "created", outcome
    assert outcome["target_type"] == "character" and outcome["target_label"] == "角色列表 · 封不觉"
    # 照角色列表的栏目写，作者点的名字交代给设定师
    assert seen["template"] == "library_draft" and seen["count"] == "1 条"
    assert "名字就用：封不觉" in seen["request"] and "身世" in seen["fields"]

    async with sessionmaker() as session:
        character = await session.get(Character, uuid.UUID(outcome["target_id"]))
        assert character.name == "封不觉" and character.source == "ai"
        assert character.role_type == "配角" and character.background.startswith("推理小说作家")
        assert character.extra["软肋"] == "怕麻烦"
    meeting = (await client.get(f"/api/books/{book}/meeting")).json()
    assert any(m["speaker"] == "chief" and "放进了角色列表" in m["content"] for m in meeting)

    # 已经有了的再说新建：不重复建，告诉作者补齐或改
    again = (await say(client, book, "新建一个封不觉角色"))["payload"]["outcome"]
    assert again["kind"] == "not_found"
    meeting = (await client.get(f"/api/books/{book}/meeting")).json()
    assert "已经有「封不觉」了" in meeting[-1]["content"]

    # 消息下面点撤销：前端删掉建的那几条
    res = await client.delete(f"/api/characters/{outcome['target_id']}")
    assert res.status_code == 204


async def test_editing_a_missing_entry_says_how_to_create_it(client, monkeypatch):
    book = await new_book(client)

    async def fake_intent(book_id, role, schema, template, **values):
        return s.LibraryIntent(kind="改设定", target_name="封不觉", part="身世", mode="照作者的意思改")

    monkeypatch.setattr("app.services.group_notes.call_model", fake_intent)
    outcome = (await say(client, book, "封不觉的身世改成孤儿"))["payload"]["outcome"]
    assert outcome["kind"] == "not_found"
    meeting = (await client.get(f"/api/books/{book}/meeting")).json()
    assert "设定库里还没有「封不觉」" in meeting[-1]["content"]
