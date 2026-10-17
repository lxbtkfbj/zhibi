"""新开书作者改节点拓扑时，段规划仍只属于第二个节点。"""

import uuid
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import select

from app.main import app
from app.models import Book, Character, Foreshadowing, NodeAnchor, Secret, StoryNode, Volume
from app.services.setup_store import load_setup


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def story(sessionmaker):
    async with sessionmaker() as session:
        book = Book(
            title="第一段拓扑", status="setting_up", setup_progress={"flow": 2, "mode": "puzzle", "current": "segment"}
        )
        session.add(book)
        await session.flush()
        segment = {
            "number": 1,
            "status": "confirmed",
            "planned_at": 0,
            "map": "青城",
            "goal": "考核夺名额",
            "goal_link": "进入藏书楼",
            "wait": "考核胜过赵乾",
            "opening": {"scene": "从药碗异常切入", "hook": "门外有人敲门"},
            "reveal": "药碗来自库房",
            "finale": False,
        }
        nodes = [
            StoryNode(
                book_id=book.id,
                position=i,
                kind=kind,
                title=title,
                event=f"{title}事件",
                prerequisite="此前",
                consequence="此后",
                volume=volume,
                status=status,
                origin="author",
                segment=deepcopy(segment) if i == 2 else None,
            )
            for i, (kind, title, volume, status) in enumerate(
                [
                    ("opening", "开篇", 1, "pencil"),
                    ("milestone", "原终点", 2, "pinned"),
                    ("milestone", "作者远景", 5, "pencil"),
                    ("ending", "结局", 8, "pencil"),
                ],
                1,
            )
        ]
        hero = Character(book_id=book.id, name="陆远", role_type="主角")
        session.add_all([*nodes, hero])
        await session.flush()
        volumes = [
            Volume(book_id=book.id, index=i, title=f"第{i}卷", target_node_id=nodes[1].id, reaches_node=i == 2)
            for i in (1, 2)
        ]
        wait = Foreshadowing(
            book_id=book.id, seq=1, kind="期待", span="长", description=segment["wait"], node_id=nodes[1].id
        )
        other_wait = Foreshadowing(
            book_id=book.id, seq=2, kind="期待", span="长", description="别的期待不跟着搬", node_id=nodes[1].id
        )
        secret = Secret(book_id=book.id, seq=1, title="旧秘密", truth="真相", node_id=nodes[1].id)
        anchor = NodeAnchor(
            book_id=book.id, character_id=hero.id, node_id=nodes[1].id, kind="高光", note="旧节点上的高光"
        )
        session.add_all([*volumes, wait, other_wait, secret, anchor])
        await session.commit()
        return {
            "book": str(book.id),
            "nodes": [str(node.id) for node in nodes],
            "segment": segment,
            "wait": wait.id,
            "other_wait": other_wait.id,
            "secret": secret.id,
            "anchor": anchor.id,
        }


async def check_binding(sessionmaker, story, endpoint_id, *, original_deleted=False):
    async with sessionmaker() as session:
        setup = await load_setup(session, uuid.UUID(story["book"]))
        nodes = setup["segment"]["nodes"]
        assert nodes[1]["id"] == endpoint_id
        assert nodes[1]["segment"] == story["segment"]
        assert all(node["segment"] is None for i, node in enumerate(nodes) if i != 1)
        assert all(volume["target_node"] == 2 for volume in setup["volumes"]["volumes"])
        assert str((await session.get(Foreshadowing, story["wait"])).node_id) == endpoint_id
        expected_old = None if original_deleted else uuid.UUID(story["nodes"][1])
        assert (await session.get(Foreshadowing, story["other_wait"])).node_id == expected_old
        assert (await session.get(Secret, story["secret"])).node_id == expected_old
        anchor = await session.get(NodeAnchor, story["anchor"])
        assert (anchor.node_id if anchor else None) == expected_old
        return nodes


async def test_insert_before_endpoint_transfers_segment_and_only_segment_references(client, sessionmaker, story):
    response = await client.post(
        f"/api/books/{story['book']}/nodes",
        json={"title": "作者新终点", "event": "救回师父", "status": "pencil", "after_node_id": story["nodes"][0]},
    )
    assert response.status_code == 201, response.text
    new_id = response.json()["id"]
    nodes = await check_binding(sessionmaker, story, new_id)
    assert nodes[1]["event"] == "救回师父" and nodes[1]["origin"] == "author" and nodes[1]["volume"] == 2
    old = next(node for node in nodes if node["id"] == story["nodes"][1])
    assert old["event"] == "原终点事件" and old["status"] == "pinned" and old["volume"] == 2


async def test_reorder_keeps_author_words_and_pinned_volume(client, sessionmaker, story):
    await client.patch(f"/api/nodes/{story['nodes'][2]}", json={"status": "pinned", "volume": 5})
    ids = [story["nodes"][0], story["nodes"][2], story["nodes"][1], story["nodes"][3]]
    response = await client.post(f"/api/books/{story['book']}/nodes/order", json={"ids": ids})
    assert response.status_code == 200, response.text
    nodes = await check_binding(sessionmaker, story, story["nodes"][2])
    assert [node["id"] for node in nodes] == ids
    assert nodes[1]["event"] == "作者远景事件" and nodes[1]["status"] == "pinned" and nodes[1]["volume"] == 5
    assert nodes[2]["event"] == "原终点事件" and nodes[2]["status"] == "pinned"


async def test_delete_endpoint_moves_plan_but_does_not_reinterpret_secrets_or_anchors(client, sessionmaker, story):
    response = await client.delete(f"/api/nodes/{story['nodes'][1]}")
    assert response.status_code == 204, response.text
    nodes = await check_binding(sessionmaker, story, story["nodes"][2], original_deleted=True)
    assert nodes[1]["volume"] == 2 and nodes[1]["event"] == "作者远景事件"


async def test_cannot_delete_only_segment_endpoint(client, sessionmaker, story):
    assert (await client.delete(f"/api/nodes/{story['nodes'][2]}")).status_code == 204
    response = await client.delete(f"/api/nodes/{story['nodes'][1]}")
    assert response.status_code == 409 and "至少要保留一个终点" in response.json()["detail"]
    await check_binding(sessionmaker, story, story["nodes"][1])


@pytest.mark.parametrize("status,flow", [("ready", 2), ("writing", 2), ("setting_up", 1)])
async def test_ready_and_legacy_books_keep_original_node_semantics(client, sessionmaker, story, status, flow):
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(story["book"]))
        book.status, book.setup_progress = status, {"flow": flow}
        await session.commit()
    response = await client.post(
        f"/api/books/{story['book']}/nodes", json={"title": "普通插入", "after_node_id": story["nodes"][0]}
    )
    assert response.status_code == 201, response.text
    assert response.json()["segment"] is None
    async with sessionmaker() as session:
        old = await session.get(StoryNode, uuid.UUID(story["nodes"][1]))
        assert old.segment == story["segment"]
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == old.book_id)))
        assert all(volume.target_node_id == old.id for volume in volumes)
