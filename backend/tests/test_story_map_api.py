"""第一包数据底座接口：节点约束、跨书引用、信息差与台账共用编号。"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.models import Book, Character, Foreshadowing, Job, NodeAnchor, Secret, StoryNode, Volume


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def story(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="测试全书地图", status="ready", setup_progress={"mode": "oneshot"})
        other = Book(title="另一部书", status="ready")
        session.add_all([book, other])
        await session.flush()
        nodes = [
            StoryNode(book_id=book.id, position=i, kind=kind, title=title)
            for i, (kind, title) in enumerate(
                [("opening", "开篇"), ("milestone", "转折一"), ("milestone", "转折二"), ("ending", "结局")], 1
            )
        ]
        foreign_node = StoryNode(book_id=other.id, position=1, kind="milestone", title="别的故事")
        character = Character(book_id=book.id, name="林岚")
        foreign_character = Character(book_id=other.id, name="外书人物")
        session.add_all([*nodes, foreign_node, character, foreign_character])
        await session.flush()
        anchor = NodeAnchor(book_id=book.id, node_id=nodes[1].id, character_id=character.id, kind="登场", note="初见")
        secret = Secret(
            book_id=book.id,
            seq=1,
            title="身份",
            truth="真实身份",
            node_id=nodes[1].id,
            knowers=[{"name": "林岚", "since_chapter": None, "how": "开书设定"}],
        )
        ledger = Foreshadowing(book_id=book.id, seq=1, description="信物", node_id=nodes[1].id)
        volume = Volume(book_id=book.id, index=1, title="第一卷", target_node_id=nodes[1].id)
        session.add_all([anchor, secret, ledger, volume])
        await session.commit()
        return {
            "book": str(book.id),
            "other": str(other.id),
            "nodes": [str(node.id) for node in nodes],
            "foreign_node": str(foreign_node.id),
            "character": str(character.id),
            "foreign_character": str(foreign_character.id),
            "anchor": str(anchor.id),
            "secret": str(secret.id),
            "ledger": str(ledger.id),
            "volume": str(volume.id),
        }


async def test_nodes_crud_order_and_metadata(client, story):
    path = f"/api/books/{story['book']}/nodes"
    nodes = (await client.get(path)).json()
    assert [node["index"] for node in nodes] == [1, 2, 3, 4]
    assert nodes[1]["anchors"][0]["character_name"] == "林岚"
    assert (await client.get(f"/api/books/{story['book']}")).json()["setup_progress"] == {"mode": "oneshot"}
    response = await client.post(path, json={"title": "作者插入", "event": "一句话"})
    assert response.status_code == 201
    added = response.json()
    assert (added["kind"], added["origin"], added["status"], added["index"]) == ("milestone", "author", "pinned", 4)
    assert (await client.get(path)).json()[-1]["kind"] == "ending"
    response = await client.patch(f"/api/nodes/{story['nodes'][1]}", json={"event": "作者改过", "volume": 2})
    assert response.json()["event"] == "作者改过"
    assert response.json()["status"] == "pencil"
    ids = [story["nodes"][0], added["id"], story["nodes"][2], story["nodes"][1], story["nodes"][3]]
    response = await client.post(path + "/order", json={"ids": ids})
    assert response.status_code == 200
    assert [node["id"] for node in response.json()] == ids
    assert [node["index"] for node in response.json()] == [1, 2, 3, 4, 5]
    assert (await client.delete(f"/api/nodes/{added['id']}")).status_code == 204
    assert [node["index"] for node in (await client.get(path)).json()] == [1, 2, 3, 4]
    # 关键节点只能走新接口，不能在 spine JSON 里建立第二份事实来源。
    assert (await client.patch(f"/api/books/{story['book']}", json={"spine": {"ending": "旧结局"}})).status_code == 422


async def test_node_constraints_and_explicit_insert(client, story, sessionmaker):
    path = f"/api/books/{story['book']}/nodes"
    for endpoint in [story["nodes"][0], story["nodes"][-1]]:
        response = await client.delete(f"/api/nodes/{endpoint}")
        assert response.status_code == 409 and response.json()["detail"] == "开篇和结局不能删"
    for ids in [
        story["nodes"][:-1],
        story["nodes"][::-1],
        [story["nodes"][0]] * 4,
        [*story["nodes"][:-1], story["foreign_node"]],
    ]:
        assert (await client.post(path + "/order", json={"ids": ids})).status_code == 422
    for after in [story["nodes"][-1], story["foreign_node"], str(uuid.uuid4())]:
        assert (await client.post(path, json={"title": "位置不对", "after_node_id": after})).status_code == 422
    response = await client.post(path, json={"title": "紧跟开篇", "after_node_id": story["nodes"][0]})
    assert response.status_code == 201 and response.json()["index"] == 2
    assert (await client.post(path, json={"title": "空位", "status": "empty"})).status_code == 422
    assert (await client.patch(f"/api/nodes/{story['nodes'][1]}", json={"status": "empty"})).status_code == 422
    assert (await client.patch(f"/api/nodes/{story['nodes'][1]}", json={"status": None})).status_code == 422
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(story["book"]))
        book.status = "setting_up"
        await session.commit()
    assert (await client.post(path, json={"title": "空位", "status": "empty"})).status_code == 201
    assert (await client.patch(f"/api/nodes/{story['nodes'][1]}", json={"status": "empty"})).status_code == 200


async def test_delete_node_cascades_and_nulls_references(client, story, sessionmaker):
    assert (await client.delete(f"/api/nodes/{story['nodes'][1]}")).status_code == 204
    async with sessionmaker() as session:
        assert await session.get(NodeAnchor, uuid.UUID(story["anchor"])) is None
        for model, key, field in [
            (Volume, "volume", "target_node_id"),
            (Secret, "secret", "node_id"),
            (Foreshadowing, "ledger", "node_id"),
        ]:
            assert getattr(await session.get(model, uuid.UUID(story[key])), field) is None
    assert [node["index"] for node in (await client.get(f"/api/books/{story['book']}/nodes")).json()] == [1, 2, 3]


async def test_anchor_crud_and_character_cascade(client, story, sessionmaker):
    body = {"node_id": story["nodes"][2], "character_id": story["character"], "kind": "高光", "note": "救人"}
    response = await client.post(f"/api/books/{story['book']}/anchors", json=body)
    assert response.status_code == 201
    anchor = response.json()
    assert anchor["character_name"] == "林岚"
    response = await client.patch(f"/api/anchors/{anchor['id']}", json={"kind": "确认关系", "note": "相认"})
    assert response.status_code == 200 and response.json()["note"] == "相认"
    assert (await client.delete(f"/api/anchors/{anchor['id']}")).status_code == 204
    assert (await client.delete(f"/api/characters/{story['character']}")).status_code == 204
    async with sessionmaker() as session:
        assert not (
            await session.scalars(select(NodeAnchor).where(NodeAnchor.book_id == uuid.UUID(story["book"])))
        ).all()


async def test_cross_book_references_are_rejected(client, story):
    book = story["book"]
    anchor = {"node_id": story["nodes"][0], "character_id": story["character"], "kind": "登场"}
    for field, foreign in [("node_id", story["foreign_node"]), ("character_id", story["foreign_character"])]:
        assert (await client.post(f"/api/books/{book}/anchors", json={**anchor, field: foreign})).status_code == 422
        assert (await client.patch(f"/api/anchors/{story['anchor']}", json={field: foreign})).status_code == 422
    for suffix, values in [("secrets", {"title": "秘密"}), ("foreshadowings", {"description": "期待"})]:
        assert (
            await client.post(f"/api/books/{book}/{suffix}", json={**values, "node_id": story["foreign_node"]})
        ).status_code == 422
    for suffix, key in [("secrets", "secret"), ("foreshadowings", "ledger")]:
        assert (
            await client.patch(f"/api/{suffix}/{story[key]}", json={"node_id": story["foreign_node"]})
        ).status_code == 422
    assert (
        await client.patch(f"/api/volumes/{story['volume']}", json={"target_node_id": story["foreign_node"]})
    ).status_code == 422
    assert (
        await client.post(f"/api/books/{book}/secrets", json={"knowers": [{"name": "外书人物"}]})
    ).status_code == 422


async def test_secret_crud_and_character_rename(client, story, sessionmaker):
    path = f"/api/books/{story['book']}/secrets"
    response = await client.post(
        path,
        json={
            "title": "修为",
            "truth": "隐藏实力",
            "reader_knows": "知道",
            "knowers": [{"name": "林岚", "since_chapter": 3, "how": "亲眼看见"}],
        },
    )
    assert response.status_code == 201
    secret = response.json()
    assert secret["code"] == "S2" and secret["seq"] == 2
    response = await client.patch(
        f"/api/secrets/{secret['id']}", json={"status": "public", "reader_knows": None, "node_id": story["nodes"][2]}
    )
    assert response.status_code == 200 and response.json()["status"] == "public"
    assert response.json()["reader_knows"] is None
    async with sessionmaker() as session:
        session.add(Secret(book_id=uuid.UUID(story["other"]), seq=1, title="同名不同人", knowers=[{"name": "林岚"}]))
        await session.commit()
    response = await client.patch(f"/api/characters/{story['character']}", json={"name": "林清岚"})
    assert response.status_code == 200 and "secrets" not in response.json()
    secrets = (await client.get(path)).json()
    assert all(row["knowers"][0]["name"] == "林清岚" for row in secrets)
    assert secrets[1]["knowers"][0] == {"name": "林清岚", "since_chapter": 3, "how": "亲眼看见"}
    assert (await client.get(f"/api/books/{story['other']}/secrets")).json()[0]["knowers"][0]["name"] == "林岚"
    bible = (await client.get(f"/api/books/{story['book']}/bible")).json()
    assert [row["code"] for row in bible["secrets"]] == ["S1", "S2"]
    assert (await client.delete(f"/api/secrets/{secret['id']}")).status_code == 204
    assert len((await client.get(path)).json()) == 1


async def test_ledger_kind_and_code_share_number_space(client, story):
    path = f"/api/books/{story['book']}/foreshadowings"
    response = await client.post(path, json={"description": "三年之约", "kind": "期待", "node_id": story["nodes"][2]})
    assert response.status_code == 201
    expectation = response.json()
    assert (expectation["kind"], expectation["seq"], expectation["code"]) == ("期待", 2, "E2")
    response = await client.post(path, json={"description": "戒指"})
    assert response.json()["code"] == "F3"
    response = await client.patch(f"/api/foreshadowings/{expectation['id']}", json={"kind": "伏笔", "node_id": None})
    assert response.json()["code"] == "F2" and response.json()["node_id"] is None


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_all_story_writes_refuse_busy_book(client, story, sessionmaker, status):
    async with sessionmaker() as session:
        session.add(
            Job(book_id=uuid.UUID(story["book"]), kind="book_setup", status=status, thread_id=str(uuid.uuid4()))
        )
        await session.commit()
    book = story["book"]
    calls = [
        ("post", f"/books/{book}/nodes", {"title": "新节点"}),
        ("patch", f"/nodes/{story['nodes'][1]}", {"event": "变更"}),
        ("delete", f"/nodes/{story['nodes'][1]}", None),
        ("post", f"/books/{book}/nodes/order", {"ids": story["nodes"]}),
        (
            "post",
            f"/books/{book}/anchors",
            {"node_id": story["nodes"][1], "character_id": story["character"], "kind": "登场"},
        ),
        ("patch", f"/anchors/{story['anchor']}", {"note": "变更"}),
        ("delete", f"/anchors/{story['anchor']}", None),
        ("post", f"/books/{book}/secrets", {"title": "秘密"}),
        ("patch", f"/secrets/{story['secret']}", {"truth": "变更"}),
        ("delete", f"/secrets/{story['secret']}", None),
        ("post", f"/books/{book}/foreshadowings", {"description": "期待", "kind": "期待"}),
        ("patch", f"/foreshadowings/{story['ledger']}", {"kind": "期待"}),
        ("delete", f"/foreshadowings/{story['ledger']}", None),
        ("patch", f"/characters/{story['character']}", {"name": "改名"}),
    ]
    for method, path, body in calls:
        response = await client.request(method, "/api" + path, **({"json": body} if body is not None else {}))
        assert response.status_code == 409, (method, path, response.text)


@pytest.mark.parametrize("resource", ["nodes", "anchors", "secrets"])
async def test_missing_resources_return_404(client, resource):
    assert (await client.delete(f"/api/{resource}/{uuid.uuid4()}")).status_code == 404
