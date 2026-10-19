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


async def test_chat_adds_the_next_segment_and_writes_it(client):
    from tests.test_outline_write import outline_book

    book, *_ = await outline_book(client)
    outcome = (await say(client, book, "第二篇也写一下"))["payload"]["outcome"]
    assert outcome["kind"] == "outline" and outcome["target_type"] == "segment" and outcome["created_id"]
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert [arc["title"] for arc in tree["arcs"]][0] == "青阳城篇" and len(tree["arcs"]) == 2
    assert tree["arcs"][1]["node_id"] == outcome["created_id"] and tree["arcs"][1]["text"]
    meeting = (await client.get(f"/api/books/{book}/meeting")).json()
    assert "我在最后加上了" in meeting[-1]["content"]

    # 撤销：新加的那一篇整篇删掉
    assert (await client.delete(f"/api/arcs/{outcome['created_id']}")).status_code == 204
    # 跳着说的不乱建
    outcome = (await say(client, book, "第五篇也写一下"))["payload"]["outcome"]
    assert outcome["kind"] == "not_found"
    assert len((await client.get(f"/api/books/{book}/outline-tree")).json()["arcs"]) == 1


async def test_one_message_with_several_things_does_each_in_turn(client):
    book = await new_book(client)
    message = await say(client, book, "帮我想一个书本的开局和结尾，写进大纲")
    assert "steps" in message["payload"], message["payload"]
    steps = message["payload"]["steps"]
    # 开局是第一篇（还没有就新加），结尾是全书结局
    assert [step["kind"] for step in steps] == ["outline", "outline"]
    assert steps[0]["target_type"] == "segment" and steps[0]["created_id"]
    assert steps[1]["target_type"] == "book"
    tree = (await client.get(f"/api/books/{book}/outline-tree")).json()
    assert len(tree["arcs"]) == 1 and tree["arcs"][0]["text"]

    # 后一件没做成，不影响前一件
    message = await say(client, book, "新建一个角色王二，然后测试分流出错")
    steps = message["payload"]["steps"]
    assert [step["kind"] for step in steps] == ["created", "failed"]
