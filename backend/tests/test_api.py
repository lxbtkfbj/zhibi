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

from app.config import get_settings
from app.llm import demo
from app.main import create_app
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
    assert len(outline["volumes"]) == 4
    unit = outline["volumes"][0]["units"][0]
    res = await client.patch(f"/api/units/{unit['id']}", json={"title": "作者改的标题"})
    assert res.json()["title"] == "作者改的标题"

    bible = (await client.get(f"/api/books/{book_id}/bible")).json()
    assert len(bible["characters"]) == 5
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
    assert book["spine"]["milestones"]
    outline = (await client.get(f"/api/books/{book_id}/outline")).json()
    assert outline["volumes"][1]["chapter_count"] == 90

    messages = (await client.get(f"/api/books/{book_id}/meeting")).json()
    note = next(m for m in messages if m["kind"] == "note")
    # 插话被主编读到并回应
    assert any(m["speaker"] == "chief" and m["kind"] == "speech" and m["id"] > note["id"] for m in messages)
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "questions" for m in messages)
    assert any(m["kind"] == "artifact" and m["payload"]["type"] == "spine" for m in messages)

    # 方案出来以后，插话要走「提修改意见」
    assert (await client.post(f"/api/books/{book_id}/notes", json={"content": "再改改"})).status_code == 409

    res = await client.patch(f"/api/books/{book_id}", json={"spine": {"ending": "作者改的结局"}})
    assert res.json()["spine"]["ending"] == "作者改的结局"
    assert res.json()["spine"]["milestones"]
