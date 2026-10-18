"""第三包任务 1：设定库聚合、编辑验证、版本、候选和建议。"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app import library_config as config
from app.config import get_settings
from app.main import create_app
from app.models import (
    Book,
    Character,
    Secret,
    SettingCandidate,
    SettingCategory,
    SettingSuggestion,
    SettingVersion,
    WorldEntry,
)


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app.state.redis.aclose()


async def make_book(sessionmaker, **kwargs):
    async with sessionmaker() as session:
        book = Book(title="测试书", **kwargs)
        session.add(book)
        await session.commit()
        return book.id


async def create_entry(client, book_id, **kwargs):
    response = await client.post(
        f"/api/books/{book_id}/world-entries", json={"name": "青阳城", "category": "世界与地图", **kwargs}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def make_suggestion(sessionmaker, book_id, payload, **kwargs):
    async with sessionmaker() as session:
        suggestion = SettingSuggestion(book_id=book_id, kind="review", title="修改建议", payload=payload, **kwargs)
        session.add(suggestion)
        await session.commit()
        return suggestion.id


async def test_library_config_matches_single_backend_source(client):
    response = await client.get("/api/library-config")
    assert response.status_code == 200
    body = response.json()
    for key in ("statuses", "styles", "sources", "focus_tags", "common_tags", "role_types", "legacy_role_types"):
        assert body[key] == getattr(config, key.upper())
    assert body["builtin_categories"] == config.BUILTIN_CATEGORIES
    for key in ("fields", "state_fields"):
        assert body["character_category"][key] == [
            {"name": name, "column": column} for name, column in config.CHARACTER_CATEGORY[key]
        ]
    assert body["genre_defaults"] == {
        genre: [{"category": category, "name": name, "status": status} for category, name, status in rows]
        for genre, rows in config.GENRE_DEFAULTS.items()
    }


async def test_library_categories_counts_focus_and_sorting(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            [
                Character(book_id=book_id, name="主角", role_type="主角", status="later", position=0),
                Character(book_id=book_id, name="对手", tags=["底牌"], status="one", position=9),
                Character(book_id=book_id, name="普通人", status="must", position=8),
                WorldEntry(
                    book_id=book_id, category="等级体系", name="阶梯", style="ladder", status="must", position=3
                ),
                WorldEntry(
                    book_id=book_id, category="特殊规则", name="系统", tags=["金手指"], status="one", position=0
                ),
                WorldEntry(book_id=book_id, category="custom:a", name="厉鬼", status="later", position=1),
                SettingCategory(book_id=book_id, key="b", name="剧本", style="paragraph", position=9),
                SettingCategory(book_id=book_id, key="a", name="厉鬼", style="card", position=1),
                SettingSuggestion(book_id=book_id, kind="review", title="查一遍", payload={"op": "note"}),
            ]
        )
        await session.commit()
    response = await client.get(f"/api/books/{book_id}/library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["key"] for row in body["categories"]] == [
        "角色卡片",
        *[row["key"] for row in config.BUILTIN_CATEGORIES],
        "custom:a",
        "custom:b",
    ]
    assert body["categories"][0]["count"] == 3 and body["categories"][0]["must_count"] == 1
    assert body["categories"][1]["count"] == body["categories"][1]["must_count"] == 1
    assert body["categories"][-2]["count"] == 1 and body["categories"][-2]["must_count"] == 0
    assert [row["name"] for row in body["characters"]] == ["普通人", "对手", "主角"]
    assert [row["name"] for row in body["entries"]] == ["阶梯", "系统", "厉鬼"]
    assert set(body["focus"]["characters"]) == {row["id"] for row in body["characters"] if row["name"] != "普通人"}
    assert body["focus"]["entries"] == [body["entries"][1]["id"]]
    assert body["suggestions_pending"] == 1
    assert (await client.get(f"/api/books/{uuid.uuid4()}/library")).status_code == 404


async def test_custom_category_crud_preserves_removed_fields(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    response = await client.post(
        f"/api/books/{book_id}/setting-categories",
        json={"name": "厉鬼", "style": "card", "fields": ["外形", "杀人规律"], "hint": "说明规则"},
    )
    assert response.status_code == 201, response.text
    category = response.json()
    entry = await create_entry(
        client, book_id, category=f"custom:{category['key']}", fields=[{"name": "外形", "value": "没有脸"}]
    )
    assert entry["style"] == "card"
    response = await client.patch(
        f"/api/setting-categories/{category['id']}", json={"name": "鬼", "fields": ["杀人规律"], "position": 4}
    )
    assert response.status_code == 200 and response.json()["key"] == category["key"]
    for style in ("paragraph", "card", None):
        response = await client.patch(f"/api/setting-categories/{category['id']}", json={"style": style})
        assert response.status_code == 422 and "类别的样式建好后不能改" in response.text
    assert (await client.delete(f"/api/setting-categories/{category['id']}")).status_code == 409
    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert bible["world_entries"][0]["fields"] == [{"name": "外形", "value": "没有脸"}]
    categories = (await client.get(f"/api/books/{book_id}/setting-categories")).json()
    assert categories[0]["name"] == "鬼" and categories[0]["position"] == 4
    assert (await client.patch(f"/api/world-entries/{entry['id']}", json={"category": "规则"})).status_code == 200
    assert (await client.delete(f"/api/setting-categories/{category['id']}")).status_code == 204
    assert (await client.get(f"/api/books/{book_id}/setting-categories")).json() == []
    assert (
        await client.post(f"/api/books/{book_id}/setting-categories", json={"name": "非法", "style": "表格"})
    ).status_code == 422


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "不存在"},
        {"category": "角色卡片"},
        {"category": "custom:missing"},
        {"style": "ladder"},
        {"status": "done"},
        {"status": None},
        {"parent_id": str(uuid.uuid4())},
        {"secret_id": str(uuid.uuid4())},
    ],
)
async def test_entry_rejects_invalid_values(client, sessionmaker, patch):
    book_id = await make_book(sessionmaker)
    response = await client.post(
        f"/api/books/{book_id}/world-entries", json={"name": "地方", "category": "地理", **patch}
    )
    assert response.status_code == 422, response.text


async def test_entry_reference_ownership_cycles_styles_and_sources(client, sessionmaker):
    book_id, other_id = await make_book(sessionmaker), await make_book(sessionmaker)
    async with sessionmaker() as session:
        secret, local_secret = Secret(book_id=other_id, seq=1), Secret(book_id=book_id, seq=1)
        session.add_all(
            [secret, local_secret, SettingCategory(book_id=other_id, key="other", name="别书", style="card")]
        )
        await session.commit()
        secret_id, local_secret_id = secret.id, local_secret.id
    other = await create_entry(client, other_id)
    parent = await create_entry(client, book_id, category="地理", source="ai")
    assert parent["category"] == "世界与地图" and parent["style"] == "paragraph" and parent["source"] == "author"
    child = await create_entry(client, book_id, name="子城", parent_id=parent["id"], secret_id=str(local_secret_id))
    grandchild = await create_entry(client, book_id, name="小院", parent_id=child["id"])
    for patch in (
        {"parent_id": parent["id"]},
        {"parent_id": child["id"]},
        {"parent_id": grandchild["id"]},
        {"parent_id": other["id"]},
        {"secret_id": str(secret_id)},
        {"category": "力量体系"},
        {"category": "custom:other"},
    ):
        assert (await client.patch(f"/api/world-entries/{parent['id']}", json=patch)).status_code == 422
    updated = (await client.patch(f"/api/world-entries/{child['id']}", json={"one_line": "作者说明"})).json()
    assert updated["source"] == "author"
    async with sessionmaker() as session:
        row = await session.get(WorldEntry, uuid.UUID(grandchild["id"]))
        row.source, row.locked = "ai", True
        await session.commit()
    updated = (
        await client.patch(f"/api/world-entries/{grandchild['id']}", json={"content": "作者可以改锁定条目"})
    ).json()
    assert updated["source"] == "ai_edited" and updated["locked"]
    ladder = await create_entry(client, book_id, category="力量体系", name="境界")
    assert ladder["category"] == "等级体系" and ladder["style"] == "ladder"
    response = await client.post(
        f"/api/books/{book_id}/world-entries", json={"category": "等级体系", "name": "错样式", "style": "paragraph"}
    )
    assert response.status_code == 422 and response.json()["detail"] == "这个类别用的是阶梯"


async def test_versions_initial_edit_revert_and_creation(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    async with sessionmaker() as session:
        legacy = WorldEntry(book_id=book_id, name="旧条目", category="特殊规则", content="原文", source="migration")
        session.add(legacy)
        await session.commit()
        entry_id = legacy.id
    assert (await client.patch(f"/api/world-entries/{entry_id}", json={"content": "新版"})).status_code == 200
    path = f"/api/books/{book_id}/versions?target_type=entry&target_id={entry_id}"
    versions = (await client.get(path)).json()
    assert [row["version"] for row in versions] == [2, 1]
    assert (
        versions[1]["snapshot"]["content"] == "原文"
        and versions[1]["source"] == "migration"
        and versions[1]["note"] == "初版"
    )
    assert versions[0]["source"] == "ai_edited"
    assert (await client.patch(f"/api/world-entries/{entry_id}", json={"one_line": "一句话"})).status_code == 200
    response = await client.post(f"/api/versions/{versions[1]['id']}/revert")
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "原文" and response.json()["one_line"] == ""
    versions = (await client.get(path)).json()
    assert [row["version"] for row in versions] == [4, 3, 2, 1]
    assert versions[0]["source"] == "revert" and versions[0]["note"] == "退回到第 1 版"
    assert versions[0]["snapshot"] == versions[-1]["snapshot"]
    entry = await create_entry(client, book_id)
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={entry['id']}")).json()
    assert len(versions) == 1 and versions[0]["version"] == 1
    other_book = await make_book(sessionmaker)
    assert (
        await client.get(f"/api/books/{other_book}/versions?target_type=entry&target_id={entry_id}")
    ).status_code == 404


@pytest.mark.parametrize(
    ("content", "path", "base", "expected1", "expected2"),
    [
        ("原文", "content", "原文", "稳妥版本", "大胆"),
        ("前原文后", "content@1:3", "原文", "前稳妥版本后", "前大胆后"),
        ("移位前原文后", "content@1:3", "原文", "移位前稳妥版本后", "移位前大胆后"),
    ],
)
async def test_candidates_switch_repeatedly_and_reject_stale(
    client, sessionmaker, content, path, base, expected1, expected2
):
    book_id = await make_book(sessionmaker)
    entry = await create_entry(client, book_id, content=content, one_line="不动这里")
    async with sessionmaker() as session:
        candidate = SettingCandidate(
            book_id=book_id,
            target_type="entry",
            target_id=uuid.UUID(entry["id"]),
            path=path,
            base=base,
            options=[{"label": "稳妥", "text": "稳妥版本"}, {"label": "大胆", "text": "大胆"}],
        )
        session.add(candidate)
        await session.commit()
        candidate_id = candidate.id
    endpoint = f"/api/candidates/{candidate_id}/choose"
    assert (await client.post(endpoint, json={"index": 5})).status_code == 422
    for index, expected in ((0, expected1), (1, expected2), (0, expected1)):
        response = await client.post(endpoint, json={"index": index})
        assert response.status_code == 200, response.text
        assert response.json()["target"]["content"] == expected and response.json()["target"]["one_line"] == "不动这里"
        assert response.json()["target"]["source"] == "candidate" and response.json()["candidate"]["chosen"] == index
    candidates = (await client.get(f"/api/books/{book_id}/candidates?target_type=entry&target_id={entry['id']}")).json()
    assert candidates[0]["base"] == "稳妥版本"
    await client.patch(f"/api/world-entries/{entry['id']}", json={"content": "作者全新写法"})
    response = await client.post(endpoint, json={"index": 1})
    assert response.status_code == 409 and response.json()["detail"] == "原文已经改过，没法只换这一段"
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={entry['id']}")).json()
    assert len(versions) == 5


async def test_suggestions_all_six_operations(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    entry = await create_entry(client, book_id, content="灵海和灵海。", one_line="原来的说明")
    ops = [
        {
            "op": "replace_text",
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "content",
            "old": "灵海",
            "new": "灵渊",
        },
        {
            "op": "splice",
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "content@3:5",
            "base": "灵渊",
            "new": "深渊",
        },
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "tags", "value": ["底牌"]},
        {
            "op": "create_entry",
            "entry": {"category": "力量体系", "name": "新境界", "levels": [{"name": "初境", "text": "起步"}]},
        },
        {"op": "create_character", "character": {"name": "楚雄", "role_type": "对手", "relation": "旧识"}},
        {"op": "note"},
    ]
    for payload in ops:
        suggestion_id = await make_suggestion(sessionmaker, book_id, payload)
        response = await client.post(f"/api/suggestions/{suggestion_id}/accept")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "accepted" and response.json()["resolved_at"]
        assert (await client.post(f"/api/suggestions/{suggestion_id}/accept")).status_code == 409
    library = (await client.get(f"/api/books/{book_id}/library")).json()
    original = next(row for row in library["entries"] if row["id"] == entry["id"])
    assert original["content"] == "灵渊和深渊。" and original["tags"] == ["底牌"]
    assert original["one_line"] == "原来的说明" and original["source"] == "suggestion"
    created = next(row for row in library["entries"] if row["name"] == "新境界")
    assert created["category"] == "等级体系" and created["style"] == "ladder" and created["source"] == "suggestion"
    assert library["characters"][0]["source"] == "suggestion" and library["suggestions_pending"] == 0
    assert len((await client.get(f"/api/books/{book_id}/suggestions?status=accepted")).json()) == 6
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={entry['id']}")).json()
    assert len(versions) == 4 and versions[0]["note"] == "修改建议"


async def test_accept_all_skips_failed_transactions_but_keeps_following_successes(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    locked = await create_entry(client, book_id, locked=True, content="灵海")
    ordinary = await create_entry(client, book_id, name="另一城", content="作者已改")
    async with sessionmaker() as session:
        session.add(Character(book_id=book_id, name="同名人物"))
        await session.commit()
    payloads = [
        {
            "op": "splice",
            "target_type": "entry",
            "target_id": locked["id"],
            "path": "content",
            "base": "灵海",
            "new": "灵渊",
        },
        {
            "op": "splice",
            "target_type": "entry",
            "target_id": ordinary["id"],
            "path": "content",
            "base": "旧稿",
            "new": "新稿",
        },
        {"op": "create_character", "character": {"name": "同名人物"}},
        {
            "op": "set_field",
            "target_type": "entry",
            "target_id": ordinary["id"],
            "path": "one_line",
            "value": "成功的修改",
        },
        {"op": "note"},
    ]
    ids = [
        await make_suggestion(sessionmaker, book_id, payload, created_at=datetime.now(UTC) + timedelta(seconds=index))
        for index, payload in enumerate(payloads)
    ]
    response = await client.post(f"/api/suggestions/{ids[0]}/accept")
    assert response.status_code == 409 and response.json()["detail"] == "这一条已锁，先解锁再改"
    response = await client.post(f"/api/books/{book_id}/suggestions/accept-all")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted"] == [str(value) for value in ids[3:]]
    assert [row["id"] for row in result["skipped"]] == [str(value) for value in ids[:3]]
    assert all(row["reason"] for row in result["skipped"])
    pending = (await client.get(f"/api/books/{book_id}/suggestions")).json()
    assert len(pending) == 3 and all(row["resolved_at"] is None for row in pending)
    library = (await client.get(f"/api/books/{book_id}/library")).json()
    row = next(row for row in library["entries"] if row["id"] == ordinary["id"])
    assert row["one_line"] == "成功的修改" and row["content"] == "作者已改" and len(library["characters"]) == 1
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={ordinary['id']}")).json()
    assert len(versions) == 2
    response = await client.post(f"/api/suggestions/{ids[0]}/ignore")
    assert response.status_code == 200 and response.json()["status"] == "ignored"


async def test_candidate_and_suggestion_reject_other_book_and_private_fields(client, sessionmaker):
    book_id, other_id = await make_book(sessionmaker), await make_book(sessionmaker)
    entry = await create_entry(client, other_id, content="秘密")
    async with sessionmaker() as session:
        candidate = SettingCandidate(
            book_id=book_id,
            target_type="entry",
            target_id=uuid.UUID(entry["id"]),
            path="content",
            base="秘密",
            options=[{"label": "选项", "text": "不准改"}],
        )
        session.add(candidate)
        await session.commit()
        candidate_id = candidate.id
    assert (await client.post(f"/api/candidates/{candidate_id}/choose", json={"index": 0})).status_code == 404
    suggestion = await make_suggestion(
        sessionmaker,
        book_id,
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "content", "value": "不准改"},
    )
    assert (await client.post(f"/api/suggestions/{suggestion}/accept")).status_code == 404
    for path in ("book_id", "source", "created_at"):
        suggestion = await make_suggestion(
            sessionmaker,
            other_id,
            {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": path, "value": str(book_id)},
        )
        assert (await client.post(f"/api/suggestions/{suggestion}/accept")).status_code == 422
    library = (await client.get(f"/api/books/{other_id}/library")).json()
    assert library["entries"][0]["content"] == "秘密"
    async with sessionmaker() as session:
        versions = list(await session.scalars(select(SettingVersion).where(SettingVersion.book_id == other_id)))
        assert len(versions) == 1


@pytest.mark.parametrize("fields", [["外形", "外形"], [""], ["  "]])
async def test_category_fields_are_unambiguous(client, sessionmaker, fields):
    book_id = await make_book(sessionmaker)
    response = await client.post(
        f"/api/books/{book_id}/setting-categories", json={"name": "厉鬼", "style": "card", "fields": fields}
    )
    assert response.status_code == 422


async def test_candidate_empty_option_can_be_switched_back(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    entry = await create_entry(client, book_id, content="前原文后")
    async with sessionmaker() as session:
        candidate = SettingCandidate(
            book_id=book_id,
            target_type="entry",
            target_id=uuid.UUID(entry["id"]),
            path="content@1:3",
            base="原文",
            options=[{"label": "省略", "text": ""}, {"label": "展开", "text": "新的文字"}],
        )
        session.add(candidate)
        await session.commit()
        candidate_id = candidate.id
    for index, expected in ((0, "前后"), (1, "前新的文字后"), (0, "前后"), (1, "前新的文字后")):
        response = await client.post(f"/api/candidates/{candidate_id}/choose", json={"index": index})
        assert response.status_code == 200, response.text
        assert response.json()["target"]["content"] == expected


async def test_invalid_reference_suggestion_rolls_back_without_affecting_next(client, sessionmaker):
    book_id, other_id = await make_book(sessionmaker), await make_book(sessionmaker)
    entry = await create_entry(client, book_id)
    other = await create_entry(client, other_id)
    payloads = [
        {
            "op": "set_field",
            "target_type": "entry",
            "target_id": entry["id"],
            "path": "parent_id",
            "value": other["id"],
        },
        {"op": "set_field", "target_type": "entry", "target_id": entry["id"], "path": "one_line", "value": "合法"},
    ]
    ids = [
        await make_suggestion(sessionmaker, book_id, payload, created_at=datetime.now(UTC) + timedelta(seconds=index))
        for index, payload in enumerate(payloads)
    ]
    response = await client.post(f"/api/books/{book_id}/suggestions/accept-all")
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == [str(ids[1])]
    assert response.json()["skipped"][0]["id"] == str(ids[0])
    library = (await client.get(f"/api/books/{book_id}/library")).json()
    assert library["entries"][0]["parent_id"] is None and library["entries"][0]["one_line"] == "合法"
    versions = (await client.get(f"/api/books/{book_id}/versions?target_type=entry&target_id={entry['id']}")).json()
    assert len(versions) == 2


async def test_suggestion_outline_ranges_locks_and_concept_reference(client, sessionmaker):
    from app.models import PlotUnit, StoryNode, Volume

    book_id, other_id = await make_book(sessionmaker), await make_book(sessionmaker)
    other_entry = await create_entry(client, other_id)
    async with sessionmaker() as session:
        volume = Volume(book_id=book_id, index=1, title="第一卷")
        session.add(volume)
        await session.flush()
        unit = PlotUnit(book_id=book_id, volume_id=volume.id, index=1, title="第一单元")
        node = StoryNode(
            book_id=book_id,
            position=1,
            kind="milestone",
            title="节点",
            status="pinned",
            segment={"title": "篇", "text": "原文"},
        )
        session.add_all([unit, node])
        await session.commit()
        volume_id, unit_id, node_id = volume.id, unit.id, node.id
    for kind, target, path, value, expected in (
        ("unit", unit_id, "chapter_count", 0, 422),
        ("unit", unit_id, "chapter_count", 51, 422),
        ("volume", volume_id, "chapter_count", 1001, 422),
        ("concept", book_id, "secret_entry_id", other_entry["id"], 422),
        ("segment", node_id, "text", "改文", 409),
    ):
        suggestion_id = await make_suggestion(
            sessionmaker,
            book_id,
            {"op": "set_field", "target_type": kind, "target_id": str(target), "path": path, "value": value},
        )
        response = await client.post(f"/api/suggestions/{suggestion_id}/accept")
        assert response.status_code == expected, response.text
    async with sessionmaker() as session:
        versions = list(await session.scalars(select(SettingVersion).where(SettingVersion.book_id == book_id)))
        assert versions == []
        assert (await session.get(PlotUnit, unit_id)).chapter_count == 8
        assert (await session.get(Volume, volume_id)).chapter_count == 0
        assert (await session.get(Book, book_id)).concept == {}


async def test_character_versions_preserve_runtime_state_and_sync_secret_names(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    async with sessionmaker() as session:
        character = Character(
            book_id=book_id, name="原名", want="眼下目标", location="城内", tags=["金手指"], source="ai"
        )
        secret = Secret(book_id=book_id, seq=1, knowers=[{"name": "原名", "knows": "真相"}])
        session.add_all([character, secret])
        await session.commit()
        character_id, secret_id = character.id, secret.id
    response = await client.patch(
        f"/api/characters/{character_id}", json={"name": "新名", "relation": "朋友", "locked": True}
    )
    assert response.status_code == 200 and response.json()["source"] == "ai_edited"
    versions = (
        await client.get(f"/api/books/{book_id}/versions?target_type=character&target_id={character_id}")
    ).json()
    assert len(versions) == 2 and "want" not in versions[0]["snapshot"]
    async with sessionmaker() as session:
        character = await session.get(Character, character_id)
        character.want = "后来目标"
        await session.commit()
    response = await client.post(f"/api/versions/{versions[-1]['id']}/revert")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "原名" and response.json()["want"] == "后来目标"
    async with sessionmaker() as session:
        assert (await session.get(Secret, secret_id)).knowers[0]["name"] == "原名"


async def test_revert_rejects_deleted_parent_reference(client, sessionmaker):
    book_id = await make_book(sessionmaker)
    parent = await create_entry(client, book_id)
    child = await create_entry(client, book_id, name="子城", parent_id=parent["id"])
    versions_path = f"/api/books/{book_id}/versions?target_type=entry&target_id={child['id']}"
    versions = (await client.get(versions_path)).json()
    assert (await client.delete(f"/api/world-entries/{parent['id']}")).status_code == 204
    response = await client.post(f"/api/versions/{versions[0]['id']}/revert")
    assert response.status_code == 422, response.text
    assert len((await client.get(versions_path)).json()) == 1
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, uuid.UUID(child["id"]))).parent_id is None
