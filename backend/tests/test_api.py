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
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, Job, MeetingMessage
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
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年"})
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
    assert book["status"] == "awaiting_approval"
    assert book["active_job"]["status"] == "waiting_author"
    assert book["title"] == "青灯问道"

    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    assert len(outline["volumes"]) == 8
    unit = outline["volumes"][0]["units"][0]
    res = await client.patch(f"/api/units/{unit['id']}", json={"title": "作者改的标题"})
    assert res.json()["title"] == "作者改的标题"

    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert len(bible["characters"]) == 6
    hero = next(c for c in bible["characters"] if c["role_type"] == "主角")
    res = await client.patch(f"/api/characters/{hero['id']}", json={"condition": "伤好了"})
    assert res.json()["condition"] == "伤好了"
    villain = next(c for c in bible["characters"] if c["name"] == "赵乾")
    res = await client.post(
        f"/api/books/{book_id}/relationships",
        json={"source_id": hero["id"], "target_id": villain["id"], "kind": "同门"},
    )
    assert res.status_code == 201
    res = await client.post(
        f"/api/books/{book_id}/world-entries", json={"category": "物品", "name": "破扫帚", "content": "老瞎子的"}
    )
    assert res.status_code == 201

    assert (await client.post(f"/api/jobs/{job_id}/decision", json={"action": "revise"})).status_code == 422
    res = await client.post(f"/api/jobs/{job_id}/decision", json={"action": "revise", "feedback": "第三单元再紧凑一些"})
    assert res.json()["status"] == "queued"
    await run_queued(queued)

    # 作者改过的内容在 AI 修改后依然保留（演示模型的大纲修改不改第一单元标题之外的东西）
    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert next(c for c in bible["characters"] if c["role_type"] == "主角")["condition"] == "伤好了"
    assert any(w["name"] == "破扫帚" for w in bible["world_entries"])

    res = await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})
    await run_queued(queued)
    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "ready"
    assert (await client.get(f"/api/jobs/{job_id}")).json()["status"] == "succeeded"
    assert (await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})).status_code == 409

    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    assert messages[0]["speaker"] == "author"
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "critique" for m in messages)
    assert messages[-1]["kind"] == "decision"
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
    res = await client.post("/api/books", json={"idea": "穿越成反派的狗"})
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


async def test_questions_then_note_then_review(client, queued):
    """动笔前提问 → 作者回答（含补充）→ 作者插话 → 方案出来后插话改走「提修改意见」。"""
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年", "ask": True})
    book_id, job_id = res.json()["book"]["id"], res.json()["job"]["id"]
    await run_queued(queued)

    job = (await client.get(f"/api/jobs/{job_id}")).json()
    assert job["status"] == "waiting_author"
    assert job["pending"]["kind"] == "setup_questions"
    questions = job["pending"]["questions"]
    assert (await client.get(f"/api/books/{book_id}")).json()["status"] == "setting_up"
    # 还没出方案，不能拍板
    assert (await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})).status_code == 409

    # 回答问题时也可以先插一句
    res = await client.post(f"/api/books/{book_id}/notes", json={"content": "开局节奏一定要快"})
    assert res.status_code == 201
    assert res.json()["kind"] == "note"

    res = await client.post(
        f"/api/jobs/{job_id}/answers",
        json={
            "answers": [{"index": 0, "answer": questions[0]["options"][2]}, {"index": 1, "answer": ""}],
            "extra": "主角叫云澈",
        },
    )
    assert res.json()["status"] == "queued"
    assert queued[-1][1]["brief"] == [f"{questions[0]['question']}——{questions[0]['options'][2]}", "补充：主角叫云澈"]
    assert (await client.post(f"/api/jobs/{job_id}/answers", json={})).status_code == 409  # 已经答过了

    await run_queued(queued)
    job = (await client.get(f"/api/jobs/{job_id}")).json()
    assert job["pending"]["kind"] == "setup_review"
    book = (await client.get(f"/api/books/{book_id}")).json()
    assert book["status"] == "awaiting_approval"
    nodes = (await client.get(f"/api/books/{book_id}/nodes")).json()
    assert any(node["kind"] == "milestone" for node in nodes)
    assert "milestones" not in book["spine"]
    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    # 选择 200 万字后，演示总纲按新八卷合同分摊篇幅，不再固定沿用旧四卷的 90 章。
    assert outline["volumes"][1]["chapter_count"] == 83
    assert sum(v["chapter_count"] for v in outline["volumes"]) == 667

    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    note = next(m for m in messages if m["kind"] == "note")
    # 插话被主编读到并回应
    assert any(m["speaker"] == "chief" and m["kind"] == "speech" and m["id"] > note["id"] for m in messages)
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "questions" for m in messages)
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "spine" for m in messages)

    # 方案出来以后，插话要走「提修改意见」
    assert (await client.post(f"/api/books/{book_id}/notes", json={"content": "再改改"})).status_code == 409

    ending = next(node for node in nodes if node["kind"] == "ending")
    res = await client.patch(f"/api/nodes/{ending['id']}", json={"event": "作者改的结局"})
    assert res.json()["event"] == "作者改的结局"
    assert res.json()["status"] == "pencil"
    assert len((await client.get(f"/api/books/{book_id}/nodes")).json()) == len(nodes)


async def test_write_chapters_and_read_them(client, queued):
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年"})
    book_id, job_id = res.json()["book"]["id"], res.json()["job"]["id"]
    # 方案还没定稿不能开写
    assert (await client.post(f"/api/books/{book_id}/write", json={"count": 1})).status_code == 409
    await run_queued(queued)
    await client.post(f"/api/jobs/{job_id}/decision", json={"action": "approve"})
    await run_queued(queued)

    threads = (await client.get(f"/api/books/{book_id}/threads")).json()
    assert threads[0]["kind"] == "主线" and threads[0]["beats"][0]["volume"] == 1
    res = await client.patch(f"/api/threads/{threads[1]['id']}", json={"summary": "作者改的感情线"})
    assert res.json()["summary"] == "作者改的感情线"
    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    first = outline["volumes"][0]
    assert first["status"] == "approved" and first["stage"] and first["units"][0]["thread_beats"]

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
    assert [c["status"] for c in listing] == ["final", "final", "planned", "planned", "planned", "planned"]
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
    res = await client.post("/api/books", json={"idea": "一个能看见别人寿命的少年"})
    assert (await client.get(f"/api/books/{res.json()['book']['id']}/export.txt")).status_code == 409


async def note_book(sessionmaker, kind=None, status="queued", pending=None):
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
                params={},
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
        ("book_setup", "waiting_author", {"kind": "setup_questions"}),
    ],
)
async def test_targeted_notes_wait_for_active_reader(client, sessionmaker, kind, status, pending):
    book_id, job_id = await note_book(sessionmaker, kind, status, pending)
    response = await client.post(
        f"/api/books/{book_id}/notes", json={"content": "  苏灵素改成 19 岁  ", "to": "lorekeeper"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["job_id"] == str(job_id)
    assert response.json()["payload"] == {"thread": "lorekeeper", "requirement_saved": True}
    assert response.json()["content"] == "苏灵素改成 19 岁"
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == ["已有的作者要求", "苏灵素改成 19 岁"]
        messages = (
            (await session.execute(select(MeetingMessage).where(MeetingMessage.book_id == book_id))).scalars().all()
        )
    assert [(m.speaker, m.kind, m.payload) for m in messages] == [
        ("author", "note", {"thread": "lorekeeper", "requirement_saved": True})
    ]


@pytest.mark.parametrize("recipient", [None, "chief", "lorekeeper", "writer", "reviewer"])
@pytest.mark.parametrize(
    ("kind", "status"), [(None, "queued"), ("rewrite_chapter", "running"), ("book_setup", "failed")]
)
async def test_idle_and_non_reader_notes_are_remembered_immediately(client, sessionmaker, recipient, kind, status):
    book_id, _ = await note_book(sessionmaker, kind, status)
    body = {"content": "  节奏再快一点  ", "to": recipient}
    expected_payload = {"requirement_saved": True, **({"thread": recipient} if recipient else {})}
    requirement = "节奏再快一点"
    for _ in range(2):
        response = await client.post(f"/api/books/{book_id}/notes", json=body)
        assert response.status_code == 201, response.text
        assert response.json()["job_id"] is None
        assert response.json()["kind"] == "note"
        assert response.json()["payload"] == expected_payload
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == ["已有的作者要求", requirement]
        messages = (
            (
                await session.execute(
                    select(MeetingMessage).where(MeetingMessage.book_id == book_id).order_by(MeetingMessage.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(messages) == 4
    for note, reply in (messages[:2], messages[2:]):
        assert note.speaker == "author" and note.content == "节奏再快一点"
        assert reply.speaker == (recipient or "chief") and reply.kind == "speech"
        assert reply.content == "记下了，下次开工就照办。"
        assert note.payload == reply.payload == expected_payload


@pytest.mark.parametrize("pending_kind", jobs.DECISION_KINDS)
@pytest.mark.parametrize("recipient", [None, "lorekeeper"])
async def test_notes_rejected_at_every_decision_gate(client, sessionmaker, pending_kind, recipient):
    book_id, _ = await note_book(sessionmaker, "write_book", "waiting_author", {"kind": pending_kind})
    response = await client.post(f"/api/books/{book_id}/notes", json={"content": "改一下", "to": recipient})
    assert response.status_code == 409
    assert response.json()["detail"] == "等你拍板时请直接提意见"
    async with sessionmaker() as session:
        assert (await session.get(Book, book_id)).requirements == ["已有的作者要求"]
        assert (await session.execute(select(MeetingMessage).where(MeetingMessage.book_id == book_id))).first() is None


@pytest.mark.parametrize("body", [{"content": "改一下", "to": "author"}, {"content": "  \n  ", "to": "writer"}])
async def test_notes_reject_invalid_recipient_and_blank_content(client, sessionmaker, body):
    book_id, _ = await note_book(sessionmaker)
    assert (await client.post(f"/api/books/{book_id}/notes", json=body)).status_code == 422


@pytest.mark.parametrize("duplicate", [False, True])
async def test_concurrent_idle_notes_preserve_every_requirement(client, sessionmaker, monkeypatch, duplicate):
    book_id, _ = await note_book(sessionmaker)
    barrier = asyncio.Barrier(2)
    original = jobs.active_job

    async def concurrent_read(session, requested_book_id):
        result = await original(session, requested_book_id)
        if requested_book_id == book_id:
            # 两个独立请求先读到相同的旧 requirements，再一起进入追加操作。
            await barrier.wait()
        return result

    monkeypatch.setattr(jobs, "active_job", concurrent_read)
    first = {"content": "开篇更紧凑", "to": "writer"}
    second = first if duplicate else {"content": "补上人物年龄", "to": "lorekeeper"}
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
