"""拆书任务入口、单队列恢复、迁移兼容和作者修改边界。"""

import asyncio
import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, text

from app.config import get_settings
from app.graphs.deps import cancel_key
from app.llm.router import LLMRouter
from app.main import create_app
from app.models import Book, BookSave, Chapter, Job, LlmProfile, MeetingMessage, RoleAssignment, Volume
from app.services import job_runner, jobs
from app.worker import tasks


@pytest.fixture
async def client(monkeypatch):
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(jobs, "enqueue_teardown", lambda _: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def seed(sessionmaker, *, stage="imported", read=0, failed=(), source="teardown"):
    async with sessionmaker() as session:
        book = Book(title="原书", source=source, status="writing", teardown={"stage": stage, "original_volumes": False})
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="还没分卷", chapter_count=5, status="done")
        session.add(volume)
        await session.flush()
        book.teardown = {**book.teardown, "open_volume_id": str(volume.id)}
        for index in range(1, 6):
            meta = {"read_version": 1} if index <= read and index not in failed else {}
            if index in failed:
                meta["read_failed"] = {"at": "2026-10-20", "error": "格式不对"}
            session.add(
                Chapter(
                    book_id=book.id, volume_id=volume.id, index=index, title=f"章{index}", content="原文", teardown=meta
                )
            )
        await session.commit()
        return book.id


async def test_start_queue_imported_archive_message_and_duplicate(client, sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    queued = []
    monkeypatch.setattr(jobs, "enqueue_teardown", queued.append)
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": 3})
    assert response.status_code == 200, response.text
    data = response.json()
    jid = uuid.UUID(data["id"])
    assert queued == [jid]
    assert data["kind"] == "teardown" and data["status"] == "queued"
    assert data["pending"]["teardown"]["target"] == 3
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.teardown["stage"] == "queued" and book.teardown["upto"] == 3
        save = await session.scalar(select(BookSave).where(BookSave.book_id == bid))
        assert save.title == "开始拆书前"
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.book_id == bid))
        assert message.speaker == "lorekeeper"
        assert message.content == "开始拆了：读到第 3 章。读好的章纲随时出现在大纲和正文里。"
    assert (await client.post(f"/api/teardown/{bid}/start", json={})).status_code == 409
    assert (await client.get(f"/api/books/{bid}")).json()["teardown"]["stage"] == "queued"


@pytest.mark.parametrize("upto", [None, 5, 99])
async def test_target_at_or_beyond_total_is_full(client, sessionmaker, upto):
    bid = await seed(sessionmaker)
    result = await client.post(f"/api/teardown/{bid}/start", json={"upto": upto})
    assert result.status_code == 200
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).teardown["upto"] is None


@pytest.mark.parametrize(
    "stage,read,failed,upto,expected",
    [
        ("stopped", 3, (), 3, 422),
        ("stopped", 3, (), 2, 422),
        ("stopped", 3, (), 4, 200),
        ("done", 5, (), None, 409),
        ("done", 5, (2,), None, 200),
        ("confirming", 0, (), None, 409),
    ],
)
async def test_start_states_and_upto(client, sessionmaker, stage, read, failed, upto, expected):
    bid = await seed(sessionmaker, stage=stage, read=read, failed=failed)
    result = await client.post(f"/api/teardown/{bid}/start", json={"upto": upto})
    assert result.status_code == expected, result.text
    if expected == 422:
        assert result.json()["detail"] == "已经拆到第 3 章了，要拆得更多才能接着拆"


async def test_import_can_start_and_force_boundary_save(client, sessionmaker):
    uploaded = await client.post("/api/teardown", files={"file": ("原书.txt", "第一章 初见\n一段正文。".encode())})
    bid = uploaded.json()["book_id"]
    result = await client.post(f"/api/teardown/{bid}/import", json={"start": {"upto": None}})
    assert result.status_code == 200, result.text
    assert result.json()["active_job"]["kind"] == "teardown"
    assert result.json()["teardown"]["stage"] == "queued"
    async with sessionmaker() as session:
        saves = (
            await session.scalars(select(BookSave).where(BookSave.book_id == uuid.UUID(bid)).order_by(BookSave.id))
        ).all()
        assert [save.title for save in saves] == ["导入原文", "开始拆书前"]


@pytest.mark.parametrize("generic", [False, True])
async def test_queued_stop_restores_previous_state(client, sessionmaker, generic):
    bid = await seed(sessionmaker, stage="stopped", read=2)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stop_reason": "upto", "stop_note": "拆到第 2 章了（你定的）。", "upto": 2}
        before = dict(book.teardown)
        await session.commit()
    started = (await client.post(f"/api/teardown/{bid}/start", json={"upto": 4})).json()
    path = f"/api/jobs/{started['id']}/cancel" if generic else f"/api/teardown/{bid}/stop"
    stopped = await client.post(path)
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
    assert stopped.json()["pending"] is None
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).teardown == before


async def test_running_stop_only_marks_cancellation_and_blocks_manual_changes(client, sessionmaker):
    bid = await seed(sessionmaker)
    started = (await client.post(f"/api/teardown/{bid}/start", json={})).json()
    jid = uuid.UUID(started["id"])
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.status = "running"
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stage": "running"}
        await session.commit()
    for payload in ({"title": "新标题"}, {"style_reference": "文风"}):
        result = await client.patch(f"/api/books/{bid}", json=payload)
        assert result.status_code == 409
        assert result.json()["detail"] == "正在拆，点「停下」才能改"
    stopped = await client.post(f"/api/teardown/{bid}/stop")
    assert stopped.json()["status"] == "running"
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        assert await redis.get(cancel_key(jid)) == "1"
    finally:
        await redis.aclose()
    async with sessionmaker() as session:
        assert (await session.get(Book, bid)).teardown["stage"] == "running"
        save = await session.scalar(select(BookSave).where(BookSave.book_id == bid))
        restore = await client.post(f"/api/books/{bid}/saves/{save.id}/restore")
        assert restore.status_code == 409


async def test_delete_running_teardown_cancels_first(client, sessionmaker):
    bid = await seed(sessionmaker)
    started = (await client.post(f"/api/teardown/{bid}/start", json={})).json()
    jid = uuid.UUID(started["id"])
    async with sessionmaker() as session:
        (await session.get(Job, jid)).status = "running"
        await session.commit()
    assert (await client.delete(f"/api/books/{bid}")).status_code == 204
    async with sessionmaker() as session:
        assert await session.get(Book, bid) is None
        assert await session.get(Job, jid) is None
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        assert await redis.get(cancel_key(jid)) == "1"
    finally:
        await redis.aclose()


async def test_own_book_keeps_previous_busy_behavior(client, sessionmaker):
    bid = await seed(sessionmaker, source="new")
    async with sessionmaker() as session:
        session.add(Job(book_id=bid, kind="write_book", thread_id="write", status="running"))
        await session.commit()
    assert (await client.post(f"/api/teardown/{bid}/start", json={})).status_code == 404
    edit = await client.patch(f"/api/books/{bid}", json={"title": "新标题"})
    assert edit.json()["detail"] == "编辑部正在工作，请等这一轮结束再修改"
    assert (await client.patch(f"/api/books/{bid}", json={"style_reference": "仍可改文风"})).status_code == 200
    assert (await client.delete(f"/api/books/{bid}")).status_code == 409


@pytest.mark.parametrize("source,expected", [("teardown", 409), ("new", 200)])
async def test_version_revert_blocks_teardown_only_while_busy(client, sessionmaker, source, expected):
    bid = await seed(sessionmaker, source=source)
    created = await client.post(f"/api/books/{bid}/characters", json={"name": "原名"})
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert (await client.patch(f"/api/characters/{cid}", json={"name": "新名"})).status_code == 200
    versions = (
        await client.get(f"/api/books/{bid}/versions", params={"target_type": "character", "target_id": cid})
    ).json()
    vid = versions[-1]["id"]
    async with sessionmaker() as session:
        session.add(
            Job(
                book_id=bid,
                kind="teardown" if source == "teardown" else "write_book",
                thread_id="busy",
                status="running",
            )
        )
        await session.commit()
    result = await client.post(f"/api/versions/{vid}/revert")
    assert result.status_code == expected, result.text
    if source == "teardown":
        assert result.json()["detail"] == "正在拆，点「停下」才能改"


async def test_concurrent_start_only_creates_one_job(client, sessionmaker):
    bid = await seed(sessionmaker)
    results = await asyncio.gather(*(client.post(f"/api/teardown/{bid}/start", json={}) for _ in range(2)))
    assert sorted(result.status_code for result in results) == [200, 409]
    async with sessionmaker() as session:
        assert len((await session.scalars(select(Job).where(Job.book_id == bid))).all()) == 1


async def test_teardown_role_assignment_and_default_fallback(client, sessionmaker):
    async with sessionmaker() as session:
        profile = LlmProfile(name="演示默认", provider="demo", model="demo")
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()
        pid = profile.id
    assert (await client.get("/api/llm/roles")).json()["teardown"] is None
    async with LLMRouter(sessionmaker) as router:
        assert (await router.resolve("teardown")).profile_id == pid
    assigned = await client.put("/api/llm/roles", json={"teardown": str(pid)})
    assert assigned.status_code == 200 and assigned.json()["teardown"] == str(pid)


async def test_orphan_recovery_filters_by_supported_kind_and_lock(sessionmaker):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        records = [
            Job(book_id=bid, kind=kind, thread_id=kind, status="running")
            for kind in ("write_book", "outline_expand", "teardown")
        ]
        session.add_all(records)
        await session.commit()
        write, _, teardown = records
    assert await tasks._orphaned_jobs() == [str(write.id)]
    assert await tasks._orphaned_jobs(("teardown",)) == [str(teardown.id)]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.set(job_runner.lock_key(teardown.id), "locked", ex=60)
        assert await tasks._orphaned_jobs(("teardown",)) == []
    finally:
        await redis.aclose()


async def test_recovery_worker_only_enqueues_its_queue(monkeypatch):
    seen = []
    queued = []

    async def orphaned(kinds=None):
        seen.append(kinds)
        return ["id"]

    monkeypatch.setattr(tasks, "_orphaned_jobs", orphaned)
    monkeypatch.setattr(tasks.run_teardown, "apply_async", lambda **kwargs: queued.append(kwargs))
    monkeypatch.setattr(tasks.run_job, "delay", lambda *_: pytest.fail("拆书 worker 不能捡写作任务"))
    monkeypatch.setattr(tasks, "_worker_loop", None)
    monkeypatch.setattr(tasks, "_worker_loop_pid", None)

    def recover():
        try:
            tasks.recover_orphaned_jobs(
                sender=SimpleNamespace(task_consumer=SimpleNamespace(queues=[SimpleNamespace(name="teardown")]))
            )
        finally:
            tasks.close_worker_loop()

    await asyncio.to_thread(recover)
    assert seen == [("teardown",)]
    assert queued == [{"args": ["id"], "queue": "teardown"}]


async def test_teardown_runner_bypasses_graphs_inside_job_runner(sessionmaker, monkeypatch):
    bid = await seed(sessionmaker)
    async with sessionmaker() as session:
        job = Job(book_id=bid, kind="teardown", thread_id="no-graph")
        session.add(job)
        await session.commit()
        jid = job.id
    from app.services import teardown_runner

    run = AsyncMock()
    monkeypatch.setattr(teardown_runner, "run_teardown", run)
    router = SimpleNamespace()
    redis = object()
    await job_runner._run(jid, None, sessionmaker, redis, "unused", router)
    run.assert_awaited_once_with(jid, sessionmaker, redis, router)
    assert router.book_id == bid


async def test_migration_backfills_only_imported_teardown_books(sessionmaker, monkeypatch):
    path = Path("alembic/versions/0024_teardown_outline.py")
    spec = importlib.util.spec_from_file_location("teardown_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    sql = []
    monkeypatch.setattr(migration.op, "execute", sql.append)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)
    migration.upgrade()
    async with sessionmaker() as session:
        rows = [
            Book(source="new", teardown={"stage": "imported"}),
            Book(source="teardown", teardown={"stage": "confirming"}),
            Book(source="teardown", teardown={"stage": "imported", "open_volume_id": None}),
            Book(source="teardown", teardown={"stage": "imported", "open_volume_id": str(uuid.uuid4())}),
        ]
        session.add_all(rows)
        await session.flush()
        await session.execute(text(sql[0]))
        await session.commit()
        for row in rows:
            await session.refresh(row)
        assert "original_volumes" not in rows[0].teardown
        assert "original_volumes" not in rows[1].teardown
        assert rows[2].teardown["original_volumes"] is True
        assert rows[3].teardown["original_volumes"] is False
