"""接口测试：模型配置、开新书 → 拍板、设定库编辑与锁定、会议室历史与 SSE。"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, Job, MeetingMessage, StoryThread
from app.services import jobs
from app.services.job_runner import execute_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
def queued(monkeypatch) -> list[tuple[uuid.UUID, dict | None]]:
    calls: list[tuple[uuid.UUID, dict | None]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: calls.append((job_id, resume)))
    return calls


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


@pytest.fixture(scope="module")
def live_server():
    """SSE 需要真实的 HTTP 服务（httpx 的进程内传输会缓冲整个响应）。"""
    # 独跑本测试时也先建检查点索引，避免 SSE 读快照与 worker 首次建索引互等。
    with PostgresSaver.from_conn_string(get_settings().checkpoint_dsn) as saver:
        saver.setup()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"]
    if sys.platform == "win32":
        cmd += ["--loop", "asyncio:SelectorEventLoop"]
    proc = subprocess.Popen(cmd, env=os.environ.copy())
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/api/health", timeout=10).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("测试服务器没有启动")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def run_queued(queued) -> None:
    while queued:
        job_id, resume = queued.pop(0)
        await execute_job(job_id, resume)


async def test_health(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["components"]["postgres"]["ok"]
    assert body["components"]["redis"]["ok"]


async def test_profiles_and_roles(client):
    res = await client.post("/api/llm/profiles", json={"name": "缺字段", "provider": "openai_compatible"})
    assert res.status_code == 422

    res = await client.post(
        "/api/llm/profiles",
        json={
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test-123456",
        },
    )
    assert res.status_code == 201, res.text
    profile = res.json()
    assert profile["has_key"] is True
    assert "api_key" not in profile

    roles = (await client.get("/api/llm/roles")).json()
    assert roles["default"] == profile["id"]  # 第一个配置自动成为默认

    demo_profile = (await client.post("/api/llm/profiles", json={"name": "演示", "provider": "demo"})).json()
    roles = (await client.put("/api/llm/roles", json={"reviewer": demo_profile["id"]})).json()
    assert roles["reviewer"] == demo_profile["id"]

    res = await client.post(f"/api/llm/profiles/{demo_profile['id']}/test")
    assert res.json()["ok"] is True

    res = await client.patch(f"/api/llm/profiles/{profile['id']}", json={"model": "deepseek-reasoner", "api_key": ""})
    assert res.json()["model"] == "deepseek-reasoner"
    assert res.json()["has_key"] is True  # 留空不清除已保存的 Key

    assert (await client.post("/api/llm/profiles", json={"name": "演示", "provider": "demo"})).status_code == 409


async def test_new_book_flow(client, queued):
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年", "mode": "oneshot"})
    assert res.status_code == 201, res.text
    book_id, job_id = res.json()["book"]["id"], res.json()["job"]["id"]
    assert len(queued) == 1

    # 编辑部工作时不能手动改
    res = await client.post(f"/api/books/{book_id}/characters", json={"name": "路人甲"})
    assert res.status_code == 409

    await run_queued(queued)
    listed = (await client.get("/api/books")).json()
    assert listed[0]["job_status"] == "waiting_author"
    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "setting_up"
    assert book["active_job"]["status"] == "waiting_author"
    assert book["title"] == "逆世帝尊"
    assert book["active_job"]["setup_flow"] == 3
    assert book["active_job"]["pending"]["piece"] == "outline"

    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    assert len(outline["volumes"]) == 2
    unit = outline["volumes"][0]["units"][0]
    res = await client.patch(f"/api/units/{unit['id']}", json={"title": "作者改的标题"})
    assert res.json()["title"] == "作者改的标题"

    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert len(bible["characters"]) == 6
    hero = next(c for c in bible["characters"] if c["role_type"] == "主角")
    res = await client.patch(f"/api/characters/{hero['id']}", json={"condition": "伤好了"})
    assert res.json()["condition"] == "伤好了"
    villain = next(c for c in bible["characters"] if c["name"] == "秦昊")
    res = await client.post(
        f"/api/books/{book_id}/relationships",
        json={"source_id": hero["id"], "target_id": villain["id"], "kind": "同门"},
    )
    assert res.status_code == 201
    res = await client.post(
        f"/api/books/{book_id}/world-entries", json={"category": "物品", "name": "破扫帚", "content": "老瞎子的"}
    )
    assert res.status_code == 201

    assert (await client.post(f"/api/jobs/{job_id}/piece", json={"action": "revise"})).status_code == 422
    res = await client.post(f"/api/jobs/{job_id}/piece", json={"action": "revise", "feedback": "第三单元再紧凑一些"})
    assert res.json()["status"] == "queued"
    await run_queued(queued)

    # 大纲重写不整库重建，作者改过的角色状态和自建条目原样保留。
    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert next(c for c in bible["characters"] if c["role_type"] == "主角")["condition"] == "伤好了"
    assert any(w["name"] == "破扫帚" for w in bible["world_entries"])

    res = await client.post(f"/api/jobs/{job_id}/piece", json={"action": "confirm"})
    await run_queued(queued)
    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "ready"
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "succeeded"
    assert (await client.post(f"/api/jobs/{job_id}/piece", json={"action": "confirm"})).status_code == 409

    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    assert messages[0]["speaker"] == "author"
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "outline" for m in messages)
    assert any(m["speaker"] == "reviewer" for m in messages)
    assert messages[-1]["speaker"] == "chief"
    assert messages[-1]["content"] == "开书方案定好了，可以开写了。"
    after = messages[-3]["id"]
    tail = (await client.get(f"/api/books/{book_id}/meeting", params={"after": after})).json()
    assert [m["id"] for m in tail] == [m["id"] for m in messages[-2:]]

    usage = (await client.get(f"/api/books/{book_id}/usage")).json()
    assert usage["calls"] >= 7
    assert set(usage["by_role"]) == {"chief", "lorekeeper", "reviewer"}

    assert (await client.delete(f"/api/books/{book_id}")).status_code == 204
    assert (await client.get(f"/api/books/{book_id}")).status_code == 404


async def test_cancel_and_resume(client, queued):
    res = await client.post("/api/books", json={"idea": "末世里开奶茶店"})
    job_id = res.json()["job"]["id"]
    res = await client.post(f"/api/jobs/{job_id}/cancel")
    assert res.json()["status"] == "cancelled"
    queued.clear()
    await execute_job(uuid.UUID(job_id))  # 已取消的任务即使被投递也不会执行
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "cancelled"

    res = await client.post(f"/api/jobs/{job_id}/resume")
    assert res.json()["status"] == "queued"
    await run_queued(queued)
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "waiting_author"


async def test_sse_replays_history_then_streams(client, queued, live_server):
    """SSE：先补发历史消息，再实时推送 worker 产生的新消息。"""
    res = await client.post("/api/books", json={"idea": "穿越成反派的狗", "mode": "oneshot"})
    book_id = res.json()["book"]["id"]

    received: list[dict] = []

    async def listen():
        async with (
            httpx.AsyncClient(base_url=live_server, timeout=30) as live,
            live.stream("GET", f"/api/books/{book_id}/events") as response,
        ):
            event = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event:
                    received.append({"event": event, "data": json.loads(line.split(":", 1)[1])})
                    if event == "job" and received[-1]["data"]["status"] == "waiting_author":
                        return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.5)
    await run_queued(queued)
    await asyncio.wait_for(listener, timeout=20)

    messages = [r["data"] for r in received if r["event"] == "message"]
    assert messages[0]["speaker"] == "author"  # 历史消息
    assert any(m["speaker"] == "reviewer" for m in messages)  # 实时消息
    ids = [m["id"] for m in messages]
    assert ids == sorted(ids) and len(ids) == len(set(ids))


async def test_ask_is_ignored_and_queued_note_is_read_before_outline(client, queued):
    """旧 ask 参数忽略；工作中插话仍被消费，三步完成后停在大纲等待。"""
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年", "mode": "oneshot", "ask": True})
    book_id, job_id = res.json()["book"]["id"], res.json()["job"]["id"]
    assert res.json()["job"]["setup_flow"] == 3
    assert (await client.get(f"/api/books/{book_id}")).json()["status"] == "setting_up"
    # 尚未生成方案，不能确认，也不能走已退役的开书提问／整套拍板。
    assert (await client.post(f"/api/jobs/{job_id}/piece", json={"action": "confirm"})).status_code == 409
    assert (await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})).status_code == 409
    assert (await client.post(f"/api/jobs/{job_id}/answers", json={})).status_code == 409

    res = await client.post(f"/api/books/{book_id}/notes", json={"content": "开局节奏一定要快"})
    assert res.status_code == 201
    assert res.json()["kind"] == "note" and res.json()["job_id"] == job_id
    await run_queued(queued)

    job = (await client.get(f"/api/jobs/{job_id}")).json()
    assert job["status"] == "waiting_author"
    assert job["pending"]["kind"] == "setup_piece" and job["pending"]["piece"] == "outline"
    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "setting_up"
    assert book["setup_progress"]["pieces"] == {"concept": "confirmed", "settings": "confirmed", "outline": "waiting"}
    nodes = (await client.get(f"/api/books/{book_id}/nodes")).json()
    assert any(node["kind"] == "milestone" for node in nodes)
    assert "milestones" not in book["spine"]
    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    # 仅第一篇分卷，第 1 卷章数对齐单元，不再沿用第二包的 31+30 章。
    assert len(outline["volumes"]) == 2
    assert outline["volumes"][0]["chapter_count"] == sum(
        unit["chapter_count"] for unit in outline["volumes"][0]["units"]
    )
    assert len(outline["volumes"][0]["units"]) == 4
    assert not outline["volumes"][1]["units"]
    assert sum(bool(node["segment"]) for node in nodes) == 1

    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    note = next(m for m in messages if m["kind"] == "note")
    assert any(m["speaker"] == "chief" and m["kind"] == "speech" and m["id"] > note["id"] for m in messages)
    types = {m["payload"]["type"] for m in messages if m["kind"] == "artifact"}
    assert {"pitches", "concept", "settings_focus", "settings_rest", "outline", "chapter_plan"} <= types
    assert not {"questions", "critique", "segment"}.intersection(types)
    assert "开局节奏一定要快" in book["requirements"]
    # 大纲等待时继续走本步意见，不接受普通插话和旧 answers 接口。
    assert (await client.post(f"/api/books/{book_id}/notes", json={"content": "再改改"})).status_code == 409
    assert (await client.post(f"/api/jobs/{job_id}/answers", json={})).status_code == 409

    ending = next(node for node in nodes if node["kind"] == "ending")
    res = await client.patch(f"/api/nodes/{ending['id']}", json={"event": "作者改的结局"})
    assert res.json()["event"] == "作者改的结局"
    assert res.json()["status"] == "pencil"
    assert len((await client.get(f"/api/books/{book_id}/nodes")).json()) == len(nodes)


@pytest.fixture
async def legacy_thread_book(sessionmaker):
    """已开完旧书的线索显式布置，测试编辑 API，不要求新三步提前生成任务 5 的线索。"""
    async with sessionmaker() as session:
        book = Book(title="旧书线索编辑", idea="已有旧书", status="ready", concept={"title": "旧书线索编辑"})
        session.add(book)
        await session.flush()
        session.add_all(
            [
                StoryThread(
                    book_id=book.id,
                    index=1,
                    name="寻找妹妹",
                    kind="主线",
                    summary="追寻妹妹的下落",
                    beats=[{"volume": 1, "beat": "找到第一条线索"}],
                ),
                StoryThread(
                    book_id=book.id,
                    index=2,
                    name="同行之人",
                    kind="感情线",
                    summary="从试探到信任",
                    beats=[{"volume": 1, "beat": "初次结伴"}],
                ),
            ]
        )
        await session.commit()
        return book.id


async def test_write_chapters_and_read_them(client, queued, legacy_thread_book):
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年", "mode": "oneshot"})
    book_id, job_id = res.json()["book"]["id"], res.json()["job"]["id"]
    # 方案还没定稿不能开写
    assert (await client.post(f"/api/books/{book_id}/write", json={"count": 1})).status_code == 409
    await run_queued(queued)
    await client.post(f"/api/jobs/{job_id}/piece", json={"action": "confirm"})
    await run_queued(queued)

    assert (await client.get(f"/api/books/{book_id}/threads")).json() == []
    threads = (await client.get(f"/api/books/{legacy_thread_book}/threads")).json()
    assert threads[0]["kind"] == "主线" and threads[0]["beats"][0]["volume"] == 1
    res = await client.patch(f"/api/threads/{threads[1]['id']}", json={"summary": "作者改的感情线"})
    assert res.json()["summary"] == "作者改的感情线"
    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    first = outline["volumes"][0]
    assert first["status"] == "approved" and first["summary"] and first["units"][0]["summary"]
    planned = (await client.get(f"/api/books/{book_id}/chapters")).json()
    assert len(planned) == first["units"][0]["chapter_count"]
    assert all(chapter["status"] == "planned" for chapter in planned)

    res = await client.post(f"/api/books/{book_id}/write", json={"until": "count", "count": 2})
    assert res.status_code == 201, res.text
    write_id = res.json()["id"]
    # 编辑部手上有活时不能再开一轮
    assert (await client.post(f"/api/books/{book_id}/write", json={"count": 1})).status_code == 409
    await run_queued(queued)
    assert (await client.get(f"/api/jobs/{write_id}")).json()["status"] == "succeeded"

    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "writing"
    assert book["chapters_final"] == 2 and book["words_final"] > 0
    listing = (await client.get(f"/api/books/{book_id}/chapters")).json()
    assert [c["status"] for c in listing] == ["final", "final", *(["planned"] * (len(planned) - 2))]
    assert [c["id"] for c in listing] == [c["id"] for c in planned]  # 开写复用开书已出的章纲。
    assert listing[0]["outline"] is None  # 目录不带章纲
    by_volume = (await client.get(f"/api/books/{book_id}/chapters", params={"volume": 1})).json()
    assert by_volume[0]["outline"]["hook"]
    chapter = (await client.get(f"/api/books/{book_id}/chapters/2")).json()
    assert chapter["content"] and chapter["review"]["review"]["verdict"] == "pass"
    res = await client.patch(f"/api/books/{book_id}/chapters/2", json={"content": "作者 改过 的正文"})
    assert res.json()["word_count"] == 7
    assert (await client.get(f"/api/books/{book_id}/chapters/99")).status_code == 404
    assert chapter["materials"]["notes"]  # 设定师写之前备的资料

    # 一键导出 TXT：按卷、按章，带标题
    res = await client.get(f"/api/books/{book_id}/export.txt")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/plain")
    assert "filename*=UTF-8''" in res.headers["content-disposition"]
    text = res.content.decode("utf-8-sig")
    assert text.startswith(book["title"])
    assert f"第1卷 {first['title']}" in text
    assert f"第1章 {listing[0]['title']}\n\n　　" in text and "　　作者 改过 的正文" in text
    assert text.index("第1章 ") < text.index("第2章 ") and "第3章" not in text  # 只导出定稿的

    # 按作者的意见重写：只有定稿的章节可以；后面还有定稿章节时要确认
    rewrite = f"/api/books/{book_id}/chapters/{{}}/rewrite"
    assert (await client.post(rewrite.format(3), json={"feedback": "再改改"})).status_code == 409
    res = await client.post(rewrite.format(1), json={"feedback": "开头再紧一点"})
    assert res.status_code == 409 and "后面已经定稿了 1 章" in res.json()["detail"]
    res = await client.post(rewrite.format(1), json={"feedback": "开头再紧一点", "confirm": True})
    assert res.status_code == 201 and res.json()["kind"] == "rewrite_chapter"
    # 重写进行中不能再开一轮
    assert (await client.post(rewrite.format(2), json={"feedback": "x"})).status_code == 409
    await run_queued(queued)
    assert (await client.get(f"/api/jobs/{res.json()['id']}")).json()["status"] == "succeeded"
    chapter = (await client.get(f"/api/books/{book_id}/chapters/1")).json()
    assert chapter["status"] == "final" and "（按作者的意见改：开头再紧一点）" in chapter["content"]


async def test_export_needs_final_chapters(client, queued):
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年", "mode": "oneshot"})
    assert (await client.get(f"/api/books/{res.json()['book']['id']}/export.txt")).status_code == 409


async def note_book(sessionmaker, kind=None, status="queued", pending=None, *, flow=3):
    """只布置任务状态，不运行模型，隔离插话接口的分流规则。"""
    async with sessionmaker() as session:
        book = Book(idea="一个能看见别人寿命的少年", requirements=["已有的作者要求"])
        session.add(book)
        await session.flush()
        job = None
        if kind:
            job = Job(
                book_id=book.id,
                kind=kind,
                status=status,
                pending=pending,
                thread_id=f"note-{uuid.uuid4()}",
                params={"flow": flow} if kind == "book_setup" else {},
            )
            session.add(job)
        await session.commit()
        return book.id, job.id if job else None


@pytest.mark.parametrize(
    ("kind", "status", "pending"),
    [
        ("book_setup", "queued", None),
        ("book_setup", "running", None),
        ("write_book", "queued", None),
        ("write_book", "running", None),
    ],
)
async def test_targeted_notes_wait_for_active_reader(client, sessionmaker, kind, status, pending):
    book_id, job_id = await note_book(sessionmaker, kind, status, pending)
    response = await client.post(
        f"/api/books/{book_id}/notes", json={"content": "  苏灵素改成 19 岁  ", "to": "lorekeeper"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["job_id"] is None
    assert response.json()["payload"]["outcome"] == {"kind": "chat"}
    assert response.json()["payload"]["thread"] == "lorekeeper"
    assert response.json()["content"] == "苏灵素改成 19 岁"
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == ["已有的作者要求"]
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.book_id == book_id).order_by(MeetingMessage.id)
            )
        )
    assert [(m.speaker, m.kind) for m in messages] == [("author", "note"), ("lorekeeper", "speech")]
    assert all(m.job_id is None for m in messages)
    assert messages[-1].payload["reply_to"] == [response.json()["id"]]


async def test_legacy_setup_questions_private_note_is_remembered_without_resuming_old_graph(client, sessionmaker):
    """旧流程的私聊也只讨论，不冒充修改意见或唤醒旧图。"""
    book_id, _ = await note_book(sessionmaker, "book_setup", "waiting_author", {"kind": "setup_questions"}, flow=2)
    response = await client.post(
        f"/api/books/{book_id}/notes", json={"content": "保留作者补充的姓名", "to": "lorekeeper"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["job_id"] is None
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert book.requirements == ["已有的作者要求"]
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.book_id == book_id).order_by(MeetingMessage.id)
            )
        )
    assert [(message.speaker, message.kind) for message in messages] == [("author", "note"), ("lorekeeper", "speech")]
    assert all(message.job_id is None for message in messages)


@pytest.mark.parametrize("recipient", [None, "chief", "lorekeeper", "writer", "reviewer"])
@pytest.mark.parametrize(
    ("kind", "status"), [(None, "queued"), ("rewrite_chapter", "running"), ("book_setup", "failed")]
)
async def test_idle_and_non_reader_notes_are_remembered_immediately(client, sessionmaker, recipient, kind, status):
    book_id, _ = await note_book(sessionmaker, kind, status)
    body = {"content": "  节奏再快一点  ", "to": recipient}
    for _ in range(2):
        response = await client.post(f"/api/books/{book_id}/notes", json=body)
        assert response.status_code == 201, response.text
        assert (response.json()["job_id"] is not None) == (recipient is None and kind == "rewrite_chapter")
        assert response.json()["kind"] == "note"
        assert response.json()["payload"]["requirement_saved"]
        assert response.json()["payload"]["outcome"]["kind"] == (
            "chat" if recipient else "to_job" if kind == "rewrite_chapter" else "requirement"
        )
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == (
            ["已有的作者要求"] if recipient else ["已有的作者要求", "节奏再快一点"]
        )
        messages = list(
            await session.scalars(
                select(MeetingMessage).where(MeetingMessage.book_id == book_id).order_by(MeetingMessage.id)
            )
        )
    assert len(messages) == 4
    for note, reply in (messages[:2], messages[2:]):
        assert note.speaker == "author" and note.content == "节奏再快一点"
        assert reply.speaker == (recipient or "chief") and reply.kind == "speech"
        if recipient:
            assert reply.payload["reply_to"] == [note.id]
        else:
            assert reply.content == "记下了。"


@pytest.mark.parametrize("pending_kind", jobs.DECISION_KINDS)
@pytest.mark.parametrize("recipient", [None, "lorekeeper"])
async def test_notes_rejected_at_every_decision_gate(client, sessionmaker, pending_kind, recipient):
    book_id, _ = await note_book(sessionmaker, "write_book", "waiting_author", {"kind": pending_kind})
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "改一下", "to": recipient})
    assert response.status_code == (201 if recipient else 409)
    if not recipient:
        assert response.json()["detail"] == {"code": "use_feedback", "message": "等你拍板时请直接提意见"}
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == ["已有的作者要求"]
        messages = list(await session.scalars(select(MeetingMessage).where(MeetingMessage.book_id == book_id)))
        assert len(messages) == (2 if recipient else 0)
        assert all(m.job_id is None for m in messages)


@pytest.mark.parametrize("body", [{"content": "改一下", "to": "author"}, {"content": "  \n  ", "to": "writer"}])
async def test_notes_reject_invalid_recipient_and_blank_content(client, sessionmaker, body):
    book_id, _ = await note_book(sessionmaker)
    assert (await client.post(f"/api/books/{book_id}/notes", json=body)).status_code == 422


@pytest.mark.parametrize("duplicate", [False, True])
async def test_concurrent_idle_notes_preserve_every_requirement(client, sessionmaker, monkeypatch, duplicate):
    book_id, _ = await note_book(sessionmaker)
    first = {"content": "开篇更紧凑"}
    second = first if duplicate else {"content": "补上人物年龄"}
    responses = await asyncio.wait_for(
        asyncio.gather(*[client.post(f"/api/books/{book_id}/notes", json=body) for body in (first, second)]),
        timeout=10,
    )
    assert [response.status_code for response in responses] == [201, 201]
    async with sessionmaker() as session:
        requirements = (await session.get(Book, book_id)).requirements
        messages = (
            (await session.execute(select(MeetingMessage).where(MeetingMessage.book_id == book_id))).scalars().all()
        )
    expected = {"已有的作者要求", "开篇更紧凑"}
    if not duplicate:
        expected.add("补上人物年龄")
    assert set(requirements) == expected
    assert len(requirements) == len(expected)
    assert sum(message.kind == "note" for message in messages) == 2
    assert sum(message.kind == "speech" for message in messages) == 2
