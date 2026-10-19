"""拆书只禁止编辑部动手、原文和结构；手改文字、设定和整书存档照旧。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.api.deps import ensure_not_teardown
from app.config import get_settings
from app.main import create_app
from app.models import (
    AuthorRequirement,
    Book,
    BookSave,
    Chapter,
    Character,
    Job,
    MeetingMessage,
    PlotUnit,
    SettingCandidate,
    SettingSuggestion,
    SettingVersion,
    StoryNode,
    Volume,
)
from app.services.versions import snapshot_of


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as client:
        yield client
    await application.state.redis.aclose()


async def seed(sessionmaker, *, source="teardown", stage="imported", status="writing"):
    async with sessionmaker() as session:
        book = Book(title="原书", genre="玄幻", source=source, status=status, teardown={"stage": stage})
        session.add(book)
        await session.flush()
        node = StoryNode(
            book_id=book.id, position=1, kind="milestone", title="原篇", segment={"title": "原篇", "text": "一段话"}
        )
        volume = Volume(book_id=book.id, index=1, title="原卷", status="done", chapter_count=1)
        character = Character(book_id=book.id, name="原人物")
        message = MeetingMessage(
            book_id=book.id, speaker="chief", kind="speech", content="旧方案", payload={"plan": {"items": []}}
        )
        job = Job(book_id=book.id, kind="write_book", status="failed", thread_id=str(uuid.uuid4()))
        suggestion = SettingSuggestion(book_id=book.id, kind="chat", title="旧建议", payload={"content": "改正文"})
        requirement = AuthorRequirement(book_id=book.id, text="旧要求", source="manual", scope="always")
        session.add_all([node, volume, character, message, job, suggestion, requirement])
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="原单元", status="done", chapter_count=1)
        candidate = SettingCandidate(
            book_id=book.id,
            target_type="character",
            target_id=character.id,
            path="personality",
            base="",
            options=["改写"],
        )
        session.add_all([unit, candidate])
        await session.flush()
        chapter = Chapter(
            book_id=book.id,
            volume_id=volume.id,
            unit_id=unit.id,
            index=1,
            title="原章",
            content="不可改的原文",
            status="final",
            source="imported",
            outline={},
        )
        session.add(chapter)
        await session.commit()
        return {
            name: str(row.id)
            for name, row in {
                "book": book,
                "node": node,
                "volume": volume,
                "unit": unit,
                "character": character,
                "message": message,
                "job": job,
                "suggestion": suggestion,
                "candidate": candidate,
                "requirement": requirement,
            }.items()
        }


def blocked_requests(ids):
    b, v, u, n, c = (ids[name] for name in ("book", "volume", "unit", "node", "character"))
    # 任务文件第 7 节逐项；每个请求体本身合法，不能靠 422 假装拦住。
    cases = [
        ("POST", f"/books/{b}/write", {}, "开写"),
        ("POST", f"/books/{b}/chapters/1/rewrite", {"feedback": "重写这章"}, "重写"),
        ("POST", f"/books/{b}/plan-segment", {}, "定下一篇"),
        ("PATCH", f"/books/{b}/chapters/1", {"content": "改了"}, "改原文"),
        ("PATCH", f"/books/{b}/chapters/1", {"content": ""}, "改原文"),
        ("PATCH", f"/books/{b}/chapters/1", {"content": None}, "改原文"),
        ("DELETE", f"/books/{b}/chapters/1", None, "改大纲结构"),
        ("POST", f"/units/{u}/chapters", {}, "改大纲结构"),
        ("POST", f"/books/{b}/volumes", {}, "改大纲结构"),
        ("DELETE", f"/volumes/{v}", None, "改大纲结构"),
        ("POST", f"/volumes/{v}/units", {}, "改大纲结构"),
        ("POST", f"/volumes/{v}/units/order", {"ids": [u]}, "改大纲结构"),
        ("DELETE", f"/units/{u}", None, "改大纲结构"),
        ("POST", f"/books/{b}/arcs", {}, "改大纲结构"),
        ("DELETE", f"/arcs/{n}", None, "改大纲结构"),
        ("POST", f"/books/{b}/nodes", {"title": "新节点"}, "改大纲结构"),
        ("DELETE", f"/nodes/{n}", None, "改大纲结构"),
        ("POST", f"/books/{b}/nodes/order", {"ids": [n]}, "改大纲结构"),
        ("POST", f"/books/{b}/outline/split", {"target_type": "unit", "target_id": u}, "改大纲结构"),
        ("POST", f"/books/{b}/outline/split/undo", {"target_type": "unit", "target_id": u, "undo": {}}, "改大纲结构"),
        (
            "POST",
            f"/books/{b}/outline/split/accept",
            {"target_type": "unit", "target_id": u, "drafts": [{}]},
            "改大纲结构",
        ),
        ("POST", f"/books/{b}/outline/move", {"kind": "unit", "id": u, "direction": "up"}, "改大纲结构"),
        ("POST", f"/books/{b}/outline/restore", {"target_type": "unit", "target_id": u, "before": {}}, "改大纲结构"),
        ("POST", f"/books/{b}/outline/write", {"target_type": "unit", "target_id": u}, "改大纲结构"),
        ("POST", f"/units/{u}/expand", None, "让编辑部改书"),
        ("POST", f"/volumes/{v}/expand", None, "让编辑部改书"),
        ("POST", f"/books/{b}/drafts", {"category": "角色列表"}, "让编辑部改书"),
        ("POST", f"/books/{b}/fill-entry", {"target_type": "character", "target_id": c}, "让编辑部改书"),
        ("POST", f"/books/{b}/library/check", {"target_type": "character", "target_id": c}, "让编辑部改书"),
        ("POST", f"/books/{b}/library/fill-gaps", None, "让编辑部改书"),
        ("POST", f"/books/{b}/library/review", None, "让编辑部改书"),
        (
            "POST",
            f"/books/{b}/library/rewrite",
            {"target_type": "character", "target_id": c, "path": "personality"},
            "让编辑部改书",
        ),
        ("POST", f"/plans/{ids['message']}/apply", {}, "让编辑部改书"),
        ("POST", f"/suggestions/{ids['suggestion']}/run-chat", None, "让编辑部改书"),
        ("PATCH", f"/books/{b}/settings", {}, "改本书设置"),
        ("POST", f"/books/{b}/requirements", {"text": "新要求"}, "加写作要求"),
        ("POST", f"/books/{b}/requirements/apply", {}, "加写作要求"),
        ("POST", f"/books/{b}/requirements/tidy", None, "加写作要求"),
    ]
    for field, value in {"locked": True, "chapter_count": 2, "target_node_id": n, "reaches_node": True}.items():
        cases.append(("PATCH", f"/volumes/{v}", {field: value}, "改大纲结构"))
    for field, value in {"locked": True, "chapter_count": 2}.items():
        cases.append(("PATCH", f"/units/{u}", {field: value}, "改大纲结构"))
    # 扫路由补上的旧入口：不能借旧任务、旧方案、旧建议把原文和结构改掉。
    cases.extend(
        [
            ("PATCH", f"/nodes/{n}", {"volume": 2}, "改大纲结构"),
            ("PATCH", f"/nodes/{n}", {"status": "pinned"}, "改大纲结构"),
            ("PATCH", f"/requirements/{ids['requirement']}", {"text": "改要求"}, "加写作要求"),
            ("DELETE", f"/requirements/{ids['requirement']}", None, "加写作要求"),
            ("POST", f"/books/{b}/notes/{ids['message']}/revert", {}, "让编辑部改书"),
            ("POST", f"/books/{b}/notes/{ids['message']}/redo", {}, "让编辑部改书"),
            ("POST", f"/plans/{ids['message']}/results/0/undo", None, "让编辑部改书"),
            ("POST", f"/candidates/{ids['candidate']}/choose", {"index": 0}, "让编辑部改书"),
            ("POST", f"/suggestions/{ids['suggestion']}/accept", None, "让编辑部改书"),
            ("POST", f"/suggestions/{ids['suggestion']}/revert", None, "让编辑部改书"),
            ("POST", f"/suggestions/{ids['suggestion']}/to-chat", {}, "让编辑部改书"),
            ("POST", f"/books/{b}/suggestions/accept-all", None, "让编辑部改书"),
        ]
    )
    for action, body in {
        "decision": {"action": "approve"},
        "pitches": {"action": "start"},
        "piece": {"action": "confirm"},
        "segment": {"action": "confirm"},
        "answers": {},
        "directions": None,
        "restart-setup": None,
        "resume": None,
    }.items():
        cases.append(("POST", f"/jobs/{ids['job']}/{action}", body, "让编辑部改书"))
    return cases


@pytest.mark.parametrize("stage,status", [("imported", "writing"), ("confirming", "ready"), ("future-stage", "ready")])
async def test_every_write_route_is_blocked_before_any_side_effect(client, sessionmaker, monkeypatch, stage, status):
    ids = await seed(sessionmaker, stage=stage, status=status)

    def forbidden(*args, **kwargs):
        pytest.fail("拆书请求不应开始模型调用、投递写作任务或触发编辑部自动存档")

    monkeypatch.setattr("app.services.jobs.enqueue", forbidden)
    monkeypatch.setattr("app.llm.router.LLMRouter.__init__", forbidden)
    monkeypatch.setattr("app.services.book_saves.editorial", forbidden)
    for method, path, body, action in blocked_requests(ids):
        response = await client.request(method, "/api" + path, **({"json": body} if body is not None else {}))
        assert response.status_code == 409, (method, path, response.text)
        assert response.json()["detail"] == f"拆的书里不能{action}：原文和大纲结构照原书来，编辑部只回答问题。", path
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter))
        assert chapter.content == "不可改的原文" and chapter.index == 1 and chapter.outline == {}
        assert (await session.get(Book, uuid.UUID(ids["book"]))).title == "原书"
        assert (await session.get(Volume, uuid.UUID(ids["volume"]))).chapter_count == 1
        assert (await session.get(PlotUnit, uuid.UUID(ids["unit"]))).chapter_count == 1
        assert (await session.get(Job, uuid.UUID(ids["job"]))).status == "failed"
        for model, count in [
            (BookSave, 0),
            (SettingVersion, 0),
            (SettingSuggestion, 1),
            (MeetingMessage, 1),
            (AuthorRequirement, 1),
        ]:
            assert await session.scalar(select(func.count()).select_from(model)) == count


@pytest.mark.parametrize("source", ["new", "imported"])
def test_guard_uses_source_not_status_or_teardown_metadata(source):
    ensure_not_teardown(Book(source=source, status="writing", teardown={"stage": "imported"}), "开写")


async def test_teardown_manual_text_settings_saves_and_delete_still_work(client, sessionmaker, monkeypatch):
    ids = await seed(sessionmaker)
    b, v, u, n = (ids[name] for name in ("book", "volume", "unit", "node"))

    def no_model(*args, **kwargs):
        pytest.fail("手改拆书文字和设定不能触发模型调用")

    monkeypatch.setattr("app.llm.router.LLMRouter.__init__", no_model)
    for path, body in [
        (f"/books/{b}", {"title": "手改书名", "concept": {"story": "手改定调"}, "review_changes": True}),
        (f"/books/{b}/chapters/1", {"title": "手改章名", "outline": {"goal": "手改章纲", "scenes": ["一个场景"]}}),
        (f"/volumes/{v}", {"title": "手改卷名", "summary": "手改卷的一段话"}),
        (f"/units/{u}", {"title": "手改单元名", "summary": "手改单元的一段话"}),
        (f"/nodes/{n}", {"title": "手改篇名", "segment": {"text": "手改篇的一段话"}}),
        (f"/characters/{ids['character']}", {"name": "手改人物名", "personality": "冷静"}),
    ]:
        response = await client.patch("/api" + path, json=body)
        assert response.status_code == 200, (path, response.text)

    # 每一类允许的手改仍可增、改、删，不把只读误套到整本书。
    created = []
    for collection, body, changed in [
        ("characters", {"name": "新人物"}, {"name": "新人物二"}),
        ("world-entries", {"category": "世界与地图", "name": "城池"}, {"name": "新城池"}),
        ("foreshadowings", {"description": "门后的影子"}, {"description": "门后的真相"}),
        ("relationships", {"kind": "朋友"}, {"kind": "师徒"}),
        ("secrets", {"truth": "原书的秘密"}, {"truth": "手改的秘密"}),
        ("setting-categories", {"name": "自定类", "style": "card", "fields": []}, {"name": "改名的类"}),
    ]:
        if collection == "relationships":
            body = {**body, "source_id": ids["character"], "target_id": created[0][1]}
        response = await client.post(f"/api/books/{b}/{collection}", json=body)
        assert response.status_code == 201, (collection, response.text)
        row_id = response.json()["id"]
        created.append((collection, row_id))
        response = await client.patch(f"/api/{collection}/{row_id}", json=changed)
        assert response.status_code == 200, (collection, response.text)
    response = await client.put(
        f"/api/books/{b}/card-layouts/角色列表", json={"facts": [{"key": "姓名", "label": "姓名"}]}
    )
    assert response.status_code == 200, response.text
    for collection, row_id in reversed(created):
        response = await client.delete(f"/api/{collection}/{row_id}")
        assert response.status_code == 204, (collection, response.text)
    response = await client.delete(f"/api/books/{b}/card-layouts/角色列表")
    assert response.status_code == 204

    response = await client.post(f"/api/books/{b}/saves", json={"label": "手改之后"})
    assert response.status_code == 200, response.text
    save_id = response.json()["save"]["id"]
    await client.patch(f"/api/books/{b}", json={"title": "暂时改名"})
    response = await client.post(f"/api/books/{b}/saves/{save_id}/restore")
    assert response.status_code == 200, response.text
    assert (await client.get(f"/api/books/{b}")).json()["title"] == "手改书名"
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter))
        assert chapter.content == "不可改的原文" and chapter.outline["goal"] == "手改章纲"
        assert await session.scalar(select(func.count()).select_from(SettingSuggestion)) == 1
    response = await client.delete(f"/api/books/{b}")
    assert response.status_code == 204, response.text


async def test_version_revert_cannot_bypass_original_text_or_structure_but_text_is_allowed(client, sessionmaker):
    ids = await seed(sessionmaker)
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter))
        volume = await session.get(Volume, uuid.UUID(ids["volume"]))
        node = await session.get(StoryNode, uuid.UUID(ids["node"]))
        versions = []
        for target_type, target, changes, action in [
            ("chapter", chapter, {"content": "不能回写的原文"}, "改原文"),
            ("volume", volume, {"chapter_count": 2}, "改大纲结构"),
            ("volume", volume, {"locked": True}, "改大纲结构"),
            ("segment", node, {"segment": {"title": "原篇", "chapter_count": 10}}, "改大纲结构"),
            ("chapter", chapter, {"title": "可退回的章名"}, None),
        ]:
            version = SettingVersion(
                book_id=chapter.book_id,
                target_type=target_type,
                target_id=target.id,
                version=len(versions) + 1,
                snapshot={**snapshot_of(target), **changes},
                source="author",
            )
            session.add(version)
            await session.flush()
            versions.append((version.id, action))
        await session.commit()
    for version_id, action in versions:
        response = await client.post(f"/api/versions/{version_id}/revert")
        assert response.status_code == (409 if action else 200), response.text
        if action:
            assert response.json()["detail"] == f"拆的书里不能{action}：原文和大纲结构照原书来，编辑部只回答问题。"
    async with sessionmaker() as session:
        chapter = await session.scalar(select(Chapter))
        assert chapter.content == "不可改的原文" and chapter.title == "可退回的章名"
