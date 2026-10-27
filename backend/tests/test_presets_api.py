"""预设的全局选择、作者保存、导入导出、版本追溯和只读资料预览。"""

import asyncio
import json
import shutil
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select

from alembic import command
from app.main import create_app
from app.models import AppSetting, Book, ChatConversation, ChatThread, MeetingMessage, Preset, PresetSave
from app.services import preset_store, presets
from app.services.chat_agent import agent_values
from app.services.chat_context import dialogue


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
        yield client


async def clone(client, **kwargs):
    response = await client.post("/api/presets/mine", json=kwargs)
    assert response.status_code == 201, response.text
    return response.json()


async def save(client, preset, *, name=None, blocks=None):
    response = await client.put(
        f"/api/presets/mine/{preset['id']}",
        json={"name": name or preset["name"], "blocks": blocks if blocks is not None else preset["blocks"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_system_catalog_versions_conditions_and_default_names(client):
    listing = (await client.get("/api/presets?kind=chief_group")).json()
    assert listing["kinds"] == [{"kind": "chief_group", "label": "主编群聊"}]
    assert listing["active"] == {"source": "system"}
    assert listing["mine"] == []
    assert [row["version"] for row in listing["versions"]] == [1]
    system = (await client.get("/api/presets/system/chief_group")).json()
    assert len(system["blocks"]) == 19 and system["version"] == 1
    assert all({"content", "without", "origin", "history"} <= block.keys() for block in system["blocks"])
    for block in system["blocks"]:
        assert block["history"] == [{"version": 1, "date": system["date"], "change": block["origin"]}]
    assert (await client.get("/api/presets/system/chief_group?version=99")).status_code == 404
    assert (await client.get("/api/presets?kind=other")).status_code == 422
    assert (await client.get("/api/presets/system/other")).status_code == 422
    assert (await client.get("/api/presets/conditions")).json() == list(presets.CONDITIONS)
    assert (await client.get("/api/presets/placeholders")).json() == list(presets.PLACEHOLDERS)
    one = await clone(client)
    two = await clone(client)
    assert (one["name"], two["name"]) == ("我的主编群聊 1", "我的主编群聊 2")
    assert one["blocks"] == presets.copy_blocks(system["blocks"])
    assert one["based_on"] == {"source": "system", "version": 1}
    assert one["saved"] == 1 and one["issues"] == []
    assert (await client.delete(f"/api/presets/mine/{one['id']}")).status_code == 200
    assert (await clone(client))["name"] == "我的主编群聊 1"
    listing = (await client.get("/api/presets")).json()
    assert len(listing["mine"]) == 2
    assert all(row["block_count"] == 19 and row["enabled_count"] == 17 for row in listing["mine"])


async def test_copy_save_history_restore_and_cascade_delete(client, sessionmaker):
    original = await clone(client, name="原件")
    blocks = deepcopy(original["blocks"])
    blocks[0]["content"] = "作者改过的角色"
    updated = await save(client, original, name="改过", blocks=blocks)
    assert updated["saved"] == 2 and updated["blocks"] == blocks
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] >= original["updated_at"]
    copied = await clone(client, source="mine", id=updated["id"], name="复制作者的")
    assert copied["blocks"] == blocks and copied["saved"] == 1
    assert {key: copied["based_on"][key] for key in ("source", "id", "saved")} == {
        "source": "mine",
        "id": updated["id"],
        "saved": 2,
    }
    history = (await client.get(f"/api/presets/mine/{original['id']}/saves")).json()
    assert [row["saved"] for row in history] == [2, 1]
    assert all("blocks" not in row for row in history)
    first = (await client.get(f"/api/presets/mine/{original['id']}/saves/1")).json()
    assert first["name"] == "原件" and first["blocks"] == original["blocks"]
    restored = (await client.post(f"/api/presets/mine/{original['id']}/saves/1/restore")).json()
    assert restored["saved"] == 3 and restored["blocks"] == original["blocks"] and restored["name"] == "原件"
    second = (await client.get(f"/api/presets/mine/{original['id']}/saves/2")).json()
    assert second["blocks"] == blocks  # 退回不会改写旧的保存
    assert (await client.get(f"/api/presets/mine/{original['id']}/saves/999")).status_code == 404
    assert (await client.delete(f"/api/presets/mine/{original['id']}")).status_code == 200
    assert (await client.get(f"/api/presets/mine/{original['id']}")).status_code == 404
    async with sessionmaker() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(PresetSave).where(PresetSave.preset_id == uuid.UUID(original["id"]))
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(PresetSave)) == 1


async def test_concurrent_unnamed_creates_pick_first_unused_names_without_restricting_manual_names(client):
    responses = await asyncio.gather(*(client.post("/api/presets/mine", json={}) for _ in range(4)))
    assert all(response.status_code == 201 for response in responses)
    assert {response.json()["name"] for response in responses} == {f"我的主编群聊 {n}" for n in range(1, 5)}
    one, two = await asyncio.gather(
        client.post("/api/presets/mine", json={"name": "手动重名"}),
        client.post("/api/presets/mine", json={"name": "手动重名"}),
    )
    assert one.status_code == two.status_code == 201
    assert one.json()["name"] == two.json()["name"] == "手动重名"


async def test_save_incomplete_checks_and_active_global_selection(client, sessionmaker):
    mine = await clone(client)
    blocks = [block for block in mine["blocks"] if "{{作者这次说的}}" not in block["content"]]
    incomplete = await save(client, mine, blocks=blocks)
    errors = [issue for issue in incomplete["issues"] if issue["severity"] == "error"]
    assert len(errors) == 1 and errors[0]["message"] == "没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。"
    response = await client.put("/api/presets/active", json={"kind": "chief_group", "source": "mine", "id": mine["id"]})
    assert response.status_code == 422 and response.json()["detail"]["issues"] == incomplete["issues"]
    assert (await client.get("/api/presets")).json()["active"] == {"source": "system"}
    warning_blocks = deepcopy(mine["blocks"])
    warning_blocks[0]["enabled"] = False
    warning = await save(client, incomplete, blocks=warning_blocks)
    response = await client.put("/api/presets/active", json={"kind": "chief_group", "source": "mine", "id": mine["id"]})
    assert response.status_code == 200 and response.json()["issues"] == warning["issues"]
    async with sessionmaker() as session:
        session.add_all([Book(title="甲"), Book(title="乙")])
        await session.commit()
        # 不接收 book_id：所有书、所有请求只读同一条全局设置。
        selected = await preset_store.get_active_preset(session)
        assert selected["id"] == mine["id"] and selected["version"] == warning["saved"]
        row = await session.get(AppSetting, "active_preset.chief_group")
        assert row.value == {"source": "mine", "id": mine["id"]}
    response = await client.delete(f"/api/presets/mine/{mine['id']}")
    assert response.status_code == 409 and response.json()["detail"] == "这份正在用，先换一份再删"
    assert (
        await client.put("/api/presets/active", json={"kind": "chief_group", "source": "system"})
    ).status_code == 200
    assert (await client.delete(f"/api/presets/mine/{mine['id']}")).status_code == 200


async def test_program_owns_new_block_ids_and_required_is_not_editable(client):
    mine = await clone(client)
    blocks = deepcopy(mine["blocks"])
    old_required = blocks[0]["required"]
    blocks[0]["required"] = not old_required
    blocks.extend(
        [
            {"title": "我新加的", "id": "made_up", "role": "assistant", "required": True, "content": "我的字"},
            {"title": "没给记号", "content": "另一块"},
        ]
    )
    updated = await save(client, mine, blocks=blocks)
    assert updated["blocks"][0]["required"] == old_required
    new = updated["blocks"][-2:]
    assert all(row["id"].startswith("custom_") and row["required"] is False for row in new)
    assert len({row["id"] for row in updated["blocks"]}) == len(updated["blocks"])
    again = await save(client, updated)
    assert again["blocks"] == updated["blocks"]
    invalid = deepcopy(again["blocks"])
    invalid[-1]["id"] = {"bad": "type"}
    response = await client.put(f"/api/presets/mine/{mine['id']}", json={"name": mine["name"], "blocks": invalid})
    assert response.status_code == 422 and "id" in response.text


async def test_export_import_preserves_all_block_bytes_and_supports_uploaded_file(client):
    mine = await clone(client, name="我的 / 预设：中文")
    blocks = deepcopy(mine["blocks"])
    blocks[0]["content"] = "  空白和换行也保留\n\n{{陌生占位符}}\n"
    mine = await save(client, mine, blocks=blocks)
    response = await client.get(f"/api/presets/mine/{mine['id']}/export")
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/json")
    assert (
        "filename*=UTF-8''" in response.headers["content-disposition"]
        and "%E6%88%91" in response.headers["content-disposition"]
    )
    exported = response.json()
    assert set(exported) == {"format", "format_version", "kind", "name", "blocks"}
    imported = await client.post(
        "/api/presets/import", files={"file": ("我的预设.json", response.content, "application/json")}
    )
    assert imported.status_code == 201, imported.text
    imported = imported.json()
    assert (
        imported["blocks"] == blocks
        and imported["name"] == mine["name"]
        and imported["based_on"] == {"source": "import"}
    )
    assert imported["saved"] == 1
    assert (await client.get(f"/api/presets/mine/{imported['id']}/export")).json() == exported
    system_export = (await client.get("/api/presets/system/chief_group/export?version=1")).json()
    direct = await client.post("/api/presets/import", json=system_export)
    assert direct.status_code == 201 and direct.json()["blocks"] == system_export["blocks"]


@pytest.mark.parametrize(
    "bad",
    [
        "format",
        "version",
        "kind",
        "role",
        "when",
        "missing_role",
        "missing_when",
        "missing_id",
        "duplicate_id",
        "id_type",
        "blocks",
        "name",
    ],
)
async def test_bad_import_is_422_and_never_creates_rows(client, sessionmaker, bad):
    data = preset_store.exported(presets.system_preset())
    if bad == "format":
        data["format"] = "other"
    elif bad == "version":
        data["format_version"] = True
    elif bad == "kind":
        data["kind"] = "other"
    elif bad in {"role", "when"}:
        data["blocks"][0][bad] = "other"
    elif bad.startswith("missing_"):
        del data["blocks"][0][bad.removeprefix("missing_")]
    elif bad == "duplicate_id":
        data["blocks"][1]["id"] = data["blocks"][0]["id"]
    elif bad == "id_type":
        data["blocks"][0]["id"] = []
    elif bad == "blocks":
        data["blocks"] = "not a list"
    elif bad == "name":
        data["name"] = " "
    response = await client.post("/api/presets/import", json=data)
    assert response.status_code == 422 and response.json()["detail"], response.text
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(Preset)) == 0
        assert await session.scalar(select(func.count()).select_from(PresetSave)) == 0


async def test_invalid_json_checks_and_missing_targets_are_explained(client):
    response = await client.post("/api/presets/import", files={"file": ("bad.json", b"not json", "application/json")})
    assert response.status_code == 422 and "JSON" in response.json()["detail"]
    assert (await client.post("/api/presets/import", data={"file": "not upload"})).status_code == 422
    assert (await client.post("/api/presets/check", content="not json")).status_code == 422
    assert (await client.post("/api/presets/check", json={"blocks": []})).json()["issues"][0]["code"] == "missing_note"
    response = await client.post("/api/presets/check", json=presets.copy_blocks(presets.system_preset()["blocks"]))
    assert response.json() == {"issues": []}
    key = uuid.uuid4()
    assert (await client.get(f"/api/presets/mine/{key}")).status_code == 404
    assert (await client.post("/api/presets/mine", json={"source": "mine", "id": str(key)})).status_code == 404
    assert (await client.post("/api/presets/mine", json={"source": "mine"})).status_code == 422
    assert (await client.post("/api/presets/mine", json={"source": "other"})).status_code == 422
    assert (await client.put("/api/presets/active", json={"source": "mine"})).status_code == 422
    assert (await client.put("/api/presets/active", json={"source": "other"})).status_code == 422


async def test_system_latest_advances_mine_is_frozen_and_lineage_survives_parent_deletion(
    client, sessionmaker, monkeypatch, tmp_path
):
    original_root = presets._root("chief_group")
    local = tmp_path / "chief_group"
    shutil.copytree(str(original_root), local)
    monkeypatch.setattr(presets, "_root", lambda kind: local)
    original = await clone(client)
    copied = await clone(client, source="mine", id=original["id"])
    async with sessionmaker() as session:
        assert (await preset_store.get_active_preset(session))["version"] == 1
    shutil.copytree(local / "v1", local / "v2")
    metadata = json.loads((local / "v2" / "preset.json").read_text(encoding="utf-8"))
    metadata.update(version=2, date="2099-01-02", note="测试新版")
    metadata["blocks"][0]["required"] = not metadata["blocks"][0]["required"]
    metadata["blocks"][0]["change"] = "测试修改角色"
    (local / "v2" / "preset.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    path = local / "v2" / f"{metadata['blocks'][0]['id']}.md"
    path.write_text("测试新版角色\n", encoding="utf-8")
    async with sessionmaker() as session:
        active = await preset_store.get_active_preset(session)
        assert active["version"] == 2 and active["blocks"][0]["content"] == "测试新版角色"
    fresh = (await client.get("/api/presets/system/chief_group")).json()
    assert [row["version"] for row in fresh["blocks"][0]["history"]] == [1, 2]
    assert fresh["blocks"][0]["history"][-1]["change"] == "测试修改角色"
    assert (await client.get(f"/api/presets/mine/{original['id']}")).json()["system_newer"] == {
        "version": 2,
        "date": "2099-01-02",
        "note": "测试新版",
    }
    unchanged = await save(client, original)
    assert unchanged["blocks"] == original["blocks"]  # 连 required 也不偷偷跟系统新版走
    assert (await client.put("/api/presets/active", json={"source": "mine", "id": copied["id"]})).status_code == 200
    async with sessionmaker() as session:
        assert (await preset_store.get_active_preset(session))["blocks"] == copied["blocks"]
    assert (await client.delete(f"/api/presets/mine/{original['id']}")).status_code == 200
    assert (await client.get(f"/api/presets/mine/{copied['id']}")).json()["system_newer"]["version"] == 2
    imported = await client.post("/api/presets/import", json=preset_store.exported(fresh))
    assert "system_newer" not in imported.json()


async def test_placeholder_preview_matches_live_algorithm_latest_conversation_and_is_readonly(client, sessionmaker):
    day = datetime(2026, 10, 27, tzinfo=UTC)
    async with sessionmaker() as session:
        book = Book(title="预览", idea="测试", concept={"logline": "长简介" * 200})
        session.add(book)
        await session.flush()
        first = ChatConversation(book_id=book.id, summary="旧段摘要", last_at=day)
        latest = ChatConversation(book_id=book.id, summary="最新摘要", last_at=day + timedelta(minutes=1))
        archived = ChatConversation(
            book_id=book.id,
            summary="归档的摘要",
            last_at=day + timedelta(minutes=2),
            archived_at=day + timedelta(minutes=3),
        )
        session.add_all([first, latest, archived])
        await session.flush()
        session.add_all(
            [
                MeetingMessage(
                    book_id=book.id, speaker="author", kind="note", content="旧段原话", payload={"conv": str(first.id)}
                ),
                MeetingMessage(
                    book_id=book.id, speaker="author", kind="note", content="最新原话", payload={"conv": str(latest.id)}
                ),
                MeetingMessage(
                    book_id=book.id,
                    speaker="author",
                    kind="note",
                    content="归档原话",
                    payload={"conv": str(archived.id)},
                ),
            ]
        )
        await session.commit()
        expected = presets.placeholder_values(
            await agent_values(
                session,
                book,
                "chief",
                SimpleNamespace(content="", payload={}),
                await dialogue(session, book.id, "group", conv=latest.id),
                latest.summary,
                False,
                False,
            )
        )
        counts = [
            await session.scalar(select(func.count()).select_from(model)) for model in (ChatConversation, ChatThread)
        ]
    response = await client.get(f"/api/presets/placeholders?book_id={book.id}")
    assert response.status_code == 200, response.text
    items = {row["name"]: row for row in response.json()}
    assert items["聊天记录"]["preview"] == "作者：最新原话" and items["之前聊过"]["preview"] == "最新摘要"
    for name in ("简介", "设定库", "大纲", "写到哪了", "记忆", "之前聊过", "聊天记录"):
        assert items[name]["preview"] == expected[name][:300] + ("……" if len(expected[name]) > 300 else "")
    for name in ("资料说明", "等你确认的", "编辑部正在干活"):
        assert items[name]["preview"] == (expected[name] or "（现在是空的）")
    for name in ("正在看的那一页", "选中的原文", "上次做到一半", "作者这次说的"):
        assert items[name]["preview"] == "发的时候才有"
    async with sessionmaker() as session:
        assert [
            await session.scalar(select(func.count()).select_from(model)) for model in (ChatConversation, ChatThread)
        ] == counts


async def test_placeholder_preview_legacy_group_state_empty_book_and_teardown_error(client, sessionmaker):
    async with sessionmaker() as session:
        book, empty, teardown = Book(title="旧书"), Book(title="新书"), Book(title="拆的书", source="teardown")
        session.add_all([book, empty, teardown])
        await session.flush()
        session.add(
            ChatThread(book_id=book.id, thread="group", summary="旧群聊摘要", summarized_until=0, reset_after=0)
        )
        session.add(MeetingMessage(book_id=book.id, speaker="author", kind="note", content="旧群聊原话"))
        await session.commit()
    items = {
        row["name"]: row["preview"] for row in (await client.get(f"/api/presets/placeholders?book_id={book.id}")).json()
    }
    assert items["之前聊过"] == "旧群聊摘要" and items["聊天记录"] == "作者：旧群聊原话"
    assert (await client.get(f"/api/presets/placeholders?book_id={empty.id}")).status_code == 200
    response = await client.get(f"/api/presets/placeholders?book_id={teardown.id}")
    assert response.status_code == 422 and "作者自己的书" in response.text
    assert (await client.get(f"/api/presets/placeholders?book_id={uuid.uuid4()}")).status_code == 404
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(ChatConversation)) == 0
        assert await session.scalar(select(func.count()).select_from(ChatThread)) == 1


async def test_placeholder_preview_all_archived_starts_empty_without_writing_conversations(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="只剩归档对话")
        session.add(book)
        await session.flush()
        archived = ChatConversation(book_id=book.id, summary="不该再带上", archived_at=datetime.now(UTC))
        session.add(archived)
        await session.flush()
        session.add(ChatThread(book_id=book.id, thread="group", summary="旧状态也不再带上"))
        session.add(
            MeetingMessage(
                book_id=book.id, speaker="author", kind="note", content="归档原话", payload={"conv": str(archived.id)}
            )
        )
        await session.commit()
    response = await client.get(f"/api/presets/placeholders?book_id={book.id}")
    assert response.status_code == 200
    values = {row["name"]: row["preview"] for row in response.json()}
    assert values["聊天记录"] == "（没有）" and values["之前聊过"] == "（没有）"
    async with sessionmaker() as session:
        assert await session.scalar(select(func.count()).select_from(ChatConversation)) == 1


@contextmanager
def database_at_0030(migration_database_urls):
    name = f"zhibi_presets_test_{uuid.uuid4().hex}"
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0030")
        yield config, engine
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def test_0031_upgrade_and_downgrade_preserve_unrelated_settings_and_cascade(migration_database_urls):
    with database_at_0030(migration_database_urls) as (config, engine):
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO app_settings (key, value) VALUES ('unrelated', '{\"safe\": true}')"))
        command.upgrade(config, "0031")
        assert {"presets", "preset_saves"} <= set(sa.inspect(engine).get_table_names())
        pid, sid = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO presets (id,kind,name,based_on,blocks) VALUES (:id,'chief_group','测试','{}','[]')"
                ),
                {"id": pid},
            )
            conn.execute(
                sa.text("INSERT INTO preset_saves (id,preset_id,saved,name,blocks) VALUES (:id,:pid,1,'测试','[]')"),
                {"id": sid, "pid": pid},
            )
            conn.execute(sa.text("DELETE FROM presets WHERE id=:id"), {"id": pid})
            assert conn.execute(sa.text("SELECT count(*) FROM preset_saves")).scalar() == 0
            conn.execute(
                sa.text(
                    "INSERT INTO app_settings (key,value) VALUES ('active_preset.chief_group','{\"source\": \"system\"}')"
                )
            )
        command.downgrade(config, "0030")
        assert not {"presets", "preset_saves"} & set(sa.inspect(engine).get_table_names())
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT value FROM app_settings WHERE key='unrelated'")).scalar() == {
                "safe": True
            }
            assert (
                conn.execute(sa.text("SELECT value FROM app_settings WHERE key='active_preset.chief_group'")).scalar()
                is None
            )
