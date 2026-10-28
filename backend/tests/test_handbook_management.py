"""手册管理存储、验证、历史、新版与0032迁移；仅独立测试库和演示模型。"""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from alembic import command
from app.models import Handbook, HandbookSave
from app.prompts import default_content, handbooks, load
from app.services import chat_tools, presets
from tests.test_author_requirement_sequence import insert_legacy_row, legacy_database
from tests.test_chat_agent import reply_of, say
from tests.test_chat_task6 import seed
from tests.test_handbooks import client as handbook_client
from tests.test_presets_core import agent_values

client = handbook_client
ROOT = Path(__file__).parents[1]


async def get(client, key="opening"):
    response = await client.get(f"/api/handbooks/{key}")
    assert response.status_code == 200, response.text
    return response.json()


async def save(client, key="opening", **changes):
    current = await get(client, key)
    body = {name: current[name] for name in ("name", "when", "body")} | changes
    response = await client.put(f"/api/handbooks/{key}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def create(client):
    response = await client.post("/api/handbooks")
    assert response.status_code == 200, response.text
    return response.json()


async def enabled(client, key, value):
    return await client.put(f"/api/handbooks/{key}/enabled", json={"enabled": value})


def test_system_bytes_split_rejoin_and_unchanged_description():
    expected = {
        "opening": "cbf9345c40e2e89d63a94dfc77ddde6a7e5e0eb730083c1c558f20a89dfb0032",
        "standards": "4eefacd6accf7904ce45599dd8375c82f102bad730737cf5b26ce3c9019b7e4f",
    }
    originals = []
    for key, digest in expected.items():
        raw = (ROOT / f"app/prompts/skills/{key}.md").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        original = raw.decode("utf-8")
        parsed = handbooks.parse(key, original)
        assert handbooks.compose(parsed.name, parsed.when, parsed.body).encode("utf-8") == raw
        assert handbooks.read(parsed.name).encode("utf-8") == raw
        originals.append(parsed)
    assert handbooks.catalog() == originals
    assert handbooks.tool_spec()["function"]["description"] == (
        "翻编辑部的专业手册，拿到全文再答。手册目录：\n"
        + "\n".join(
            "- "
            + original.content.splitlines()[0][2:]
            + "："
            + next(line[6:] for line in original.content.splitlines() if line.startswith("什么时候翻："))
            for original in originals
        )
    )
    between = handbooks.parse("test", "# 名称\n\n夹在中间的字\n\n什么时候翻：问时\n\n正文\n\n  ")
    assert between.name == "名称" and between.when == "问时"
    assert between.body == "夹在中间的字\n\n\n正文\n\n  "


async def test_modify_use_system_history_and_restore_follow_system(client, sessionmaker):
    initial = await get(client)
    assert initial["source"] == "system" and not initial["modified"] and initial["saved"] == 0
    assert initial["system"]["content"] == initial["content"]
    original = initial["content"]
    custom = await save(client, name="  开书  ", when="  问时  ", body="  正文开头不去空格\n\n尾巴\n\n ")
    assert custom["name"] == "开书" and custom["when"] == "问时" and custom["body"].endswith("\n\n ")
    assert custom["content"] == handbooks.compose(custom["name"], custom["when"], custom["body"])
    assert handbooks.read("开书") == custom["content"] and custom["saved"] == 1
    async with sessionmaker() as session:
        row = await session.get(Handbook, "opening")
        assert row.system_hash == hashlib.sha256(original.encode()).hexdigest()
    response = await client.post("/api/handbooks/opening/use-system")
    assert response.status_code == 200 and response.json()["content"] == original
    assert response.json()["saved"] == 2 and not response.json()["modified"]
    assert (await client.post("/api/handbooks/opening/use-system")).json()["saved"] == 2
    saves = (await client.get("/api/handbooks/opening/saves")).json()
    assert [row["kind"] for row in saves] == ["use_system", "save"]
    assert [row["saved"] for row in saves] == [2, 1]
    assert saves[0]["chars"] == len(original)
    assert (await client.get("/api/handbooks/opening/saves/1")).json()["body"] == custom["body"]
    restored = (await client.post("/api/handbooks/opening/saves/1/restore")).json()
    assert restored["content"] == custom["content"] and restored["saved"] == 3
    following = (await client.post("/api/handbooks/opening/saves/2/restore")).json()
    assert following["content"] == original and not following["modified"] and following["saved"] == 4
    # 退回到一条“退回程序带的”记录仍然跟着程序，而非冻结那次文本。
    again = (await client.post("/api/handbooks/opening/saves/4/restore")).json()
    assert not again["modified"] and again["saved"] == 5
    async with sessionmaker() as session:
        row = await session.get(Handbook, "opening")
        assert row.name is None and row.body is None and row.system_hash is None
        restored_row = await session.get(HandbookSave, ("opening", 5))
        assert restored_row.kind == "restore" and restored_row.restore_saved == 4 and restored_row.follows_system


async def test_enabled_changes_tool_catalog_read_and_conditional_preset_without_saves(client):
    for key in ("opening", "standards"):
        response = await enabled(client, key, False)
        assert response.status_code == 200 and response.json()["saved"] == 0
        assert key not in [book.key for book in handbooks.catalog()]
    assert handbooks.catalog() == [] and handbooks.tool_spec() is None
    assert handbooks.read("开书") == "没有这本手册：开书。目录里有："
    listing = (await client.get("/api/handbooks")).json()
    assert len(listing["items"]) == 2 and listing["catalog"] == ""
    tools = chat_tools.tool_specs(False)
    assert "read_skill" not in [tool["function"]["name"] for tool in tools]
    composed = presets.compose(presets.system_preset(), agent_values(), tools=tools, read_only=False)
    assert "tool_skills" not in [block["id"] for block in composed["preset"]["blocks"]]
    assert (await enabled(client, "opening", True)).status_code == 200
    assert handbooks.tool_spec()["function"]["parameters"]["properties"]["name"]["enum"] == ["开书"]


async def test_create_incomplete_default_names_order_and_delete_cascade(client, sessionmaker):
    one, two = await create(client), await create(client)
    assert one["name"] == "新手册" and two["name"] == "新手册 2"
    assert one["key"].startswith("mine_") and one["saved"] == 1 and not one["enabled"] and not one["complete"]
    response = await enabled(client, one["key"], True)
    assert response.status_code == 422 and response.json()["detail"] == "名称、什么时候翻、正文都写上，才能打开。"
    one = await save(client, one["key"], name="打斗", when="问打斗", body="正文")
    assert one["complete"] and one["saved"] == 2
    assert (await enabled(client, one["key"], True)).status_code == 200
    listing = (await client.get("/api/handbooks")).json()
    assert [item["key"] for item in listing["items"]] == ["opening", "standards", one["key"], two["key"]]
    assert listing["catalog"].endswith("- 打斗：问打斗")
    response = await client.delete("/api/handbooks/opening")
    assert response.status_code == 409 and response.json()["detail"] == "程序带的手册不能删，可以关掉。"
    assert (await client.delete(f"/api/handbooks/{one['key']}")).status_code == 204
    assert (await client.get(f"/api/handbooks/{one['key']}")).status_code == 404
    async with sessionmaker() as session:
        assert await session.get(Handbook, one["key"]) is None
        assert list(await session.scalars(sa.select(HandbookSave).where(HandbookSave.key == one["key"]))) == []
    # 已删除的默认名会被重新使用，而非只递增。
    three = await create(client)
    assert three["name"] == "新手册"


@pytest.mark.parametrize(
    "change,message",
    [
        ({"name": "  "}, "名称不能空着。"),
        ({"name": "字" * 21}, "名称最多 20 个字。"),
        ({"name": "两\n行"}, "名称只写一行。"),
        ({"when": "两\r\n行"}, "什么时候翻只写一行。"),
        ({"when": "字" * 301}, "什么时候翻最多 300 个字。"),
        ({"body": "字" * 50001}, "正文最多五万字。"),
        ({"name": "{{"}, "手册里不能有 {{ 或 }}。"),
        ({"when": "}}"}, "手册里不能有 {{ 或 }}。"),
        ({"body": "{{变量}}"}, "手册里不能有 {{ 或 }}。"),
        ({"when": " "}, "开着的手册，名称、什么时候翻、正文都得写上；还没写完，先关掉再存。"),
        ({"body": "\n "}, "开着的手册，名称、什么时候翻、正文都得写上；还没写完，先关掉再存。"),
    ],
)
async def test_all_validation_messages_and_failed_save_is_atomic(client, change, message):
    current = await get(client)
    body = {name: current[name] for name in ("name", "when", "body")} | change
    response = await client.put("/api/handbooks/opening", json=body)
    assert response.status_code == 422 and response.json()["detail"] == message
    assert await get(client) == current
    assert (await client.get("/api/handbooks/opening/saves")).json() == []


async def test_disabled_incomplete_and_duplicate_names_allowed_but_restore_and_open_check(client):
    current = await get(client)
    mine = await create(client)
    mine = await save(client, mine["key"], name="开书", when="", body="")
    assert mine["saved"] == 2 and not mine["enabled"]
    mine = await save(client, mine["key"], when="问时", body="正文")
    conflict = await enabled(client, mine["key"], True)
    assert (
        conflict.status_code == 422
        and conflict.json()["detail"] == "已经有一本开着的「开书」。先关掉那本，或者给这本改个名。"
    )
    mine = await save(client, mine["key"], name="打斗")
    assert (await enabled(client, mine["key"], True)).status_code == 200
    restore = await client.post(f"/api/handbooks/{mine['key']}/saves/3/restore")
    assert restore.status_code == 422 and "已经有一本开着的「开书」" in restore.json()["detail"]
    incomplete = await client.post(f"/api/handbooks/{mine['key']}/saves/1/restore")
    assert incomplete.status_code == 422 and incomplete.json()["detail"].startswith("开着的手册")
    assert (await enabled(client, "opening", False)).status_code == 200
    assert (await client.post(f"/api/handbooks/{mine['key']}/saves/3/restore")).status_code == 200
    assert handbooks.read("开书") != current["content"]


async def test_concurrent_enable_only_one_same_name_can_commit(client):
    keys = []
    for _ in range(2):
        item = await create(client)
        await save(client, item["key"], name="同名", when="问时", body="正文")
        keys.append(item["key"])
    responses = await asyncio.gather(*(enabled(client, key, True) for key in keys))
    assert sorted(response.status_code for response in responses) == [200, 422]
    assert [book.name for book in handbooks.catalog()].count("同名") == 1


async def test_new_system_seen_use_system_and_removed_files(client, monkeypatch, tmp_path):
    folder = tmp_path / "skills"
    folder.mkdir()
    for key in ("opening", "standards"):
        (folder / f"{key}.md").write_bytes((ROOT / f"app/prompts/skills/{key}.md").read_bytes())
    monkeypatch.setattr(handbooks.resources, "files", lambda _: tmp_path)
    original = await get(client)
    custom = await save(client, body=original["body"] + "\n作者那份")
    path = folder / "opening.md"
    path.write_bytes((original["content"] + "\n程序新版一").encode())
    updated = await get(client)
    assert updated["system_updated"] and updated["content"] == custom["content"]
    assert updated["system"]["body"].endswith("程序新版一")
    seen = (await client.post("/api/handbooks/opening/seen-system")).json()
    assert not seen["system_updated"] and seen["saved"] == 1 and seen["modified"]
    path.write_bytes((original["content"] + "\n程序新版二").encode())
    assert (await get(client))["system_updated"]
    switched = (await client.post("/api/handbooks/opening/use-system")).json()
    assert switched["content"].endswith("程序新版二") and not switched["modified"] and not switched["system_updated"]
    path.write_bytes((original["content"] + "\n程序新版三").encode())
    assert (await get(client))["content"].endswith("程序新版三")
    await save(client, body=custom["body"])
    path.unlink()
    (folder / "standards.md").unlink()
    listing = (await client.get("/api/handbooks")).json()
    assert len(listing["items"]) == 1 and listing["items"][0]["source"] == "mine"
    assert (await get(client))["body"] == custom["body"] and (await get(client))["system"] is None
    assert (await client.delete("/api/handbooks/opening")).status_code == 204


async def test_demo_group_reads_saved_current_full_text(client, sessionmaker):
    original = await get(client)
    custom = await save(client, body=original["body"] + "\n\n手册管理验收专用尾记\n ")
    bid = await seed(sessionmaker)
    note = await say(client, bid, "开书先定什么")
    reply = await reply_of(client, bid, note["id"])
    assert reply["payload"]["tools"][0] == {"kind": "query", "label": "手册《开书》", "text": custom["content"]}


def test_0032_moves_overrides_byte_exact_and_downgrade_twice(migration_database_urls, monkeypatch):
    with legacy_database(migration_database_urls) as (config, engine, metadata):
        command.upgrade(config, "0031")
        dsn = (
            make_url(config.get_main_option("sqlalchemy.url"))
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        monkeypatch.setattr("app.prompts.get_settings", lambda: SimpleNamespace(checkpoint_dsn=dsn))
        monkeypatch.setattr(handbooks, "get_settings", lambda: SimpleNamespace(checkpoint_dsn=dsn))
        original = default_content("skills.opening")
        custom = original + "\n\n作者在提示词页加的字。\n \n"
        unrelated = "其他提示词的作者原文\n  "
        with engine.begin() as connection:
            insert_legacy_row(connection, metadata.tables["prompt_overrides"], name="skills.opening", content=custom)
            insert_legacy_row(connection, metadata.tables["prompt_overrides"], name="rules", content=unrelated)
        for _ in range(2):
            with engine.begin() as connection:
                insert_legacy_row(
                    connection,
                    metadata.tables["prompt_overrides"],
                    name="skills.gone",
                    content="# 失去文件\n\n什么时候翻：问时\n\n留住正文\n\n ",
                )
            before = load("skills.opening")
            assert before.encode() == custom.encode()
            command.upgrade(config, "0032")
            assert handbooks.read("开书").encode() == before.encode()
            with engine.connect() as connection:
                rows = list(connection.execute(sa.text("SELECT * FROM handbooks ORDER BY key")).mappings())
                assert len(rows) == 2
                system = next(row for row in rows if row["key"] == "opening")
                mine = next(row for row in rows if row["key"].startswith("mine_"))
                assert system["enabled"] and system["source"] == "system" and system["saved"] == 1
                assert system["system_hash"] == hashlib.sha256(original.encode()).hexdigest()
                assert mine["source"] == "mine" and not mine["enabled"] and mine["body"] == "留住正文\n\n "
                saves = list(connection.execute(sa.text("SELECT * FROM handbook_saves")).mappings())
                assert len(saves) == 2 and all(row["kind"] == "migrated" and row["saved"] == 1 for row in saves)
                overrides = list(connection.execute(sa.text("SELECT name, content FROM prompt_overrides")).all())
                assert overrides == [("rules", unrelated)]
            command.downgrade(config, "0031")
            assert not {"handbooks", "handbook_saves"} & set(sa.inspect(engine).get_table_names())
            with engine.connect() as connection:
                overrides = dict(connection.execute(sa.text("SELECT name, content FROM prompt_overrides")).all())
                assert overrides == {"skills.opening": custom, "rules": unrelated}
            assert load("skills.opening").encode() == custom.encode()
