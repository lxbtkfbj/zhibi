"""定调经候选、退回和建议改变时也要查下游，不自动改下游。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import Book, SettingCandidate, SettingSuggestion, SettingVersion, WorldEntry


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app.state.redis.aclose()


@pytest.mark.parametrize("operation", ["candidate", "revert", "suggestion", "all_suggestions"])
async def test_concept_edit_paths_review_after_commit(client, sessionmaker, monkeypatch, operation):
    old, new = "少年在青阳城修炼。", "少年离开青阳城查案。"
    async with sessionmaker() as session:
        book = Book(title="测试书", concept={"title": "测试书", "story": old})
        session.add(book)
        await session.flush()
        entry = WorldEntry(book_id=book.id, name="青阳城", category="世界与地图", content="此处不自动改")
        candidate = SettingCandidate(
            book_id=book.id, target_type="concept", target_id=book.id, path="story", base=old, options=[{"text": new}]
        )
        version = SettingVersion(
            book_id=book.id,
            target_type="concept",
            target_id=book.id,
            version=1,
            source="author",
            snapshot={"title": "测试书", "story": new},
        )
        suggestion = SettingSuggestion(
            book_id=book.id,
            kind="review",
            target_type="concept",
            target_id=book.id,
            title="改定调",
            payload={
                "op": "set_field",
                "target_type": "concept",
                "target_id": str(book.id),
                "path": "story",
                "value": new,
            },
        )
        session.add_all([entry, candidate, version, suggestion])
        await session.commit()
        book_id, entry_id = book.id, entry.id
        ids = {"candidate": candidate.id, "revert": version.id, "suggestion": suggestion.id}
    calls = []

    async def review(session, redis, book, check=None, *, scope=None, kind="review"):
        # 另一个事务能读到已提交的新定调；模型阶段回滚不会丢失作者改动。
        async with sessionmaker() as separate:
            assert (await separate.get(Book, book_id)).concept["story"] == new
        calls.append((scope, kind))
        session.add(SettingSuggestion(book_id=book_id, kind=kind, title="待作者看", payload={"op": "note"}))
        await session.commit()
        return {"suggestions": [], "note": "只挂建议"}

    monkeypatch.setattr("app.api.library_ai.review_library", review)
    if operation == "candidate":
        response = await client.post(f"/api/candidates/{ids[operation]}/choose", json={"index": 0})
    elif operation == "revert":
        response = await client.post(f"/api/versions/{ids[operation]}/revert")
    elif operation == "suggestion":
        response = await client.post(f"/api/suggestions/{ids[operation]}/accept")
    else:
        response = await client.post(f"/api/books/{book_id}/suggestions/accept-all")
    assert response.status_code == 200, response.text
    assert calls == [(f"定调改了。\n改之前：{old}\n改之后：{new}\n查设定库和大纲里哪些地方要跟着改。", "concept")]
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, entry_id)).content == "此处不自动改"
        review_suggestions = list(
            await session.scalars(select(SettingSuggestion).where(SettingSuggestion.kind == "concept"))
        )
        assert len(review_suggestions) == 1 and review_suggestions[0].status == "pending"


@pytest.mark.parametrize("operation", ["patch", "rewrite"])
async def test_direct_concept_changes_review_exact_scope_and_outline_targets(
    client, sessionmaker, monkeypatch, operation
):
    from app.agents.schemas import LibraryIssue, LibraryReview, RewriteOne
    from app.api import library_ai
    from app.models import StoryNode

    old, new = "少年在青阳城修炼。", "少年离开青阳城查案。"
    async with sessionmaker() as session:
        book = Book(title="定调连带", concept={"story": old}, status="setting_up")
        session.add(book)
        await session.flush()
        entry = WorldEntry(book_id=book.id, name="青阳城", category="世界与地图", content="不要自动改")
        node = StoryNode(
            book_id=book.id,
            position=2,
            kind="milestone",
            title="青阳城篇",
            segment={"title": "青阳城篇", "text": "在青阳城修炼。"},
        )
        session.add_all([entry, node])
        await session.commit()
        bid, nid = book.id, node.id
    calls = []

    async def model(book_id, role, schema, prompt, **values):
        if schema is RewriteOne:
            return RewriteOne(text=new, note="改好了")
        assert schema is LibraryReview
        calls.append(values)
        return LibraryReview(
            issues=[
                LibraryIssue(
                    kind="矛盾",
                    title="篇目标需要核对",
                    target_name="青阳城篇",
                    quote="修炼",
                    fix="查案",
                    why="定调已经改了",
                )
            ],
            note="只挂建议，不改原文。",
        )

    monkeypatch.setattr(library_ai, "call_model", model)
    if operation == "patch":
        response = await client.patch(f"/api/books/{bid}", json={"concept": {"story": new}})
    else:
        response = await client.post(
            f"/api/books/{bid}/library/rewrite",
            json={
                "target_type": "concept",
                "target_id": str(bid),
                "path": "story",
                "mode": "instruction",
                "instruction": "改成查案",
            },
        )
    assert response.status_code == 200, response.text
    assert calls[0]["scope"] == f"定调改了。\n改之前：{old}\n改之后：{new}\n查设定库和大纲里哪些地方要跟着改。"
    async with sessionmaker() as session:
        suggestions = list(await session.scalars(select(SettingSuggestion).where(SettingSuggestion.book_id == bid)))
        assert len(suggestions) == 1 and suggestions[0].kind == "concept"
        assert suggestions[0].target_type == "segment" and suggestions[0].target_id == nid
        assert suggestions[0].payload["op"] == "splice"
        assert (await session.get(StoryNode, nid)).segment["text"] == "在青阳城修炼。"


async def test_concept_edit_before_library_build_does_not_call_model(client, sessionmaker, monkeypatch):
    from unittest.mock import AsyncMock

    from app.api import library_ai

    async with sessionmaker() as session:
        book = Book(title="还没建库", concept={"story": "旧定调"})
        session.add(book)
        await session.commit()
        bid = book.id
    call = AsyncMock(side_effect=AssertionError("未建库不应查一遍"))
    monkeypatch.setattr(library_ai, "call_model", call)
    response = await client.patch(f"/api/books/{bid}", json={"concept": {"story": "新的定调"}})
    assert response.status_code == 200, response.text
    call.assert_not_called()
