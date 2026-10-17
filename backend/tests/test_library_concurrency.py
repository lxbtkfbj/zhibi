"""等待书锁的编辑请求必须在拿到锁后重新检查编辑部是否开工。"""

import asyncio
import contextlib
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.config import get_settings
from app.main import create_app
from app.models import Book, Character, Job, PlotUnit, SettingVersion, StoryNode, Volume, WorldEntry
from app.services.versions import snapshot_of


async def wait_for_database_lock(sessionmaker, blocker_pid, request):
    """等 PostgreSQL 确认请求实际被阻塞，而不是用固定延时猜调度顺序。"""
    async with asyncio.timeout(10):
        async with sessionmaker() as observer:
            while True:
                if request.done():
                    response = request.result()
                    pytest.fail(f"编辑请求没有等待书锁：{response.status_code} {response.text}")
                waiting = await observer.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND :blocker = ANY(pg_blocking_pids(pid)))"
                    ),
                    {"blocker": blocker_pid},
                )
                # pg_stat_activity 在事务里可缓存快照；每轮新事务读取实时阻塞状态。
                await observer.rollback()
                if waiting:
                    return


@pytest.mark.parametrize(
    "operation",
    ["create_entry", "update_entry", "create_character", "update_character", "book", "volume", "unit", "node"],
)
async def test_waiting_edit_rechecks_busy_state_after_acquiring_book_lock(sessionmaker, operation):
    async with sessionmaker() as session:
        book = Book(title="并发保护", status="ready", concept={"story": "原定调"})
        session.add(book)
        await session.flush()
        entry = WorldEntry(book_id=book.id, name="旧设定", category="特殊规则", content="原设定")
        character = Character(book_id=book.id, name="旧角色", personality="原性格")
        node = StoryNode(
            book_id=book.id, position=1, kind="milestone", title="终点", segment={"title": "原篇名", "text": "原篇文"}
        )
        volume = Volume(book_id=book.id, index=1, title="原卷", summary="原卷纲")
        session.add_all([entry, character, node, volume])
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="原单元", summary="原单元纲")
        session.add(unit)
        await session.commit()
        tracked = [(type(row), row.id, snapshot_of(row)) for row in (book, entry, character, node, volume, unit)]
        book_id = book.id
        requests = {
            "create_entry": ("POST", f"/api/books/{book_id}/world-entries", {"name": "不该新建"}),
            "update_entry": ("PATCH", f"/api/world-entries/{entry.id}", {"content": "不该写入"}),
            "create_character": ("POST", f"/api/books/{book_id}/characters", {"name": "不该新建"}),
            "update_character": ("PATCH", f"/api/characters/{character.id}", {"personality": "不该写入"}),
            "book": ("PATCH", f"/api/books/{book_id}", {"concept": {"story": "不该写入"}}),
            "volume": ("PATCH", f"/api/volumes/{volume.id}", {"summary": "不该写入"}),
            "unit": ("PATCH", f"/api/units/{unit.id}", {"summary": "不该写入"}),
            "node": ("PATCH", f"/api/nodes/{node.id}", {"segment": {"text": "不该写入"}}),
        }

    method, url, payload = requests[operation]
    request = None
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            async with sessionmaker() as blocker:
                await blocker.execute(select(Book.id).where(Book.id == book_id).with_for_update())
                blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
                request = asyncio.create_task(client.request(method, url, json=payload))
                await wait_for_database_lock(sessionmaker, blocker_pid, request)
                # 模拟开写接口：持有书锁、提交 queued 任务，再让排队的作者编辑拿锁。
                blocker.add(Job(book_id=book_id, kind="write_book", thread_id=f"race-{uuid.uuid4()}", status="queued"))
                await blocker.commit()
            response = await asyncio.wait_for(request, timeout=10)
        finally:
            await app.state.redis.aclose()
            if request is not None and not request.done():
                request.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await request
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "编辑部正在工作，请等这一轮结束再修改"
    async with sessionmaker() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(SettingVersion).where(SettingVersion.book_id == book_id)
            )
            == 0
        )
        assert (
            await session.scalar(select(func.count()).select_from(WorldEntry).where(WorldEntry.book_id == book_id)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(Character).where(Character.book_id == book_id)) == 1
        )
        for model, row_id, original in tracked:
            assert snapshot_of(await session.get(model, row_id)) == original
