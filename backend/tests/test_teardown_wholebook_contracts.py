"""拆书第五批：只整理入口、旧书树不变、篇右栏、期待台账和补章接缝。"""

import uuid
from types import SimpleNamespace

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import event, select

from app.config import get_settings
from app.main import create_app
from app.models import Book, Foreshadowing, Job, StoryNode, Volume
from app.services import chat_tools, jobs, teardown_chat
from app.services.teardown_info import needs_closing
from tests.test_desk_v2_backend import fixture_book
from tests.test_teardown_append import seed as append_seed
from tests.test_teardown_append import upload
from tests.test_teardown_jobs import seed as job_seed


@pytest.fixture
async def client(monkeypatch):
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(jobs, "enqueue_teardown", lambda _: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


@pytest.mark.parametrize(
    "meta,last,total,expected",
    [
        ({}, 0, 5, False),
        ({"arcs": {"failed": True}}, 0, 5, False),
        ({}, 2, 5, True),
        ({"settings": {"upto": 2}}, 2, 5, True),
        ({"settings": {"upto": 2}, "waits": {"upto": 2}, "stage": "stopped"}, 2, 2, True),
        ({"settings": {"upto": 2}, "waits": {"upto": 2}, "stage": "done"}, 2, 2, True),
        (
            {"settings": {"upto": 2}, "waits": {"upto": 2}, "stage": "done", "ending": {"upto": 2}},
            2,
            2,
            False,
        ),
        ({"settings": {"upto": 2}, "waits": {"upto": 2}, "stage": "stopped"}, 2, 5, False),
        (
            {
                "settings": {"upto": 2},
                "waits": {"upto": 2},
                "stage": "done",
                "ending": {"upto": 2},
                "arcs": {"failed": True},
            },
            2,
            2,
            True,
        ),
        (
            {"settings": {"upto": 2}, "waits": {"upto": 2}, "stage": "stopped", "arcs": {"failed": True}},
            2,
            5,
            True,
        ),
    ],
)
def test_needs_closing_all_rules(meta, last, total, expected):
    assert needs_closing(meta, last, total) is expected


@pytest.mark.parametrize("only_arc_failed", [False, True])
async def test_done_can_only_close_missing_steps_and_then_no_longer_start(client, sessionmaker, only_arc_failed):
    bid = await job_seed(sessionmaker, stage="done", read=5)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {
            **book.teardown,
            "split": {"chapters": 5},
            "settings": {"upto": 5},
            "waits": {"upto": 5},
            **({"ending": {"upto": 5, "ended": False}, "arcs": {"failed": True}} if only_arc_failed else {}),
        }
        await session.commit()
    summary = (await client.get(f"/api/books/{bid}")).json()["teardown"]
    assert summary["needs_closing"] is True and summary["arcs"] == 0
    response = await client.post(f"/api/teardown/{bid}/start", json={})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(response.json()["id"]))
        assert job.params["settings_only"] is True
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stage": "done", "ending": {"upto": 5, "ended": False}}
        if only_arc_failed:
            book.teardown["arcs"] = {}
        job.status = "succeeded"
        await session.commit()
    assert (await client.post(f"/api/teardown/{bid}/start", json={})).status_code == 409


async def test_only_wants_waits_still_uses_settings_only_job_flag(client, sessionmaker):
    bid = await job_seed(sessionmaker, stage="stopped", read=3)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "settings": {"upto": 3}, "waits": {"upto": 2}}
        await session.commit()
    response = await client.post(f"/api/teardown/{bid}/start", json={"upto": 3})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        job = await session.get(Job, uuid.UUID(response.json()["id"]))
        assert job.params["settings_only"] is True


async def test_summary_read_and_last_are_same_grouped_query_and_internal_state_hidden(client, sessionmaker):
    bid = await job_seed(sessionmaker, stage="done", read=5, failed=(2,))
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {
            **book.teardown,
            "split": {"chapters": 5},
            "arcs": {"rows": [{"node": "a", "hash": "private"}], "inputs": "private"},
            "ending": {"upto": 5, "ended": False, "hint": "private"},
            "waits": {"upto": 5, "total": 7, "open": 2, "at": "private"},
            "settings": {"upto": 5},
        }
        await session.commit()
        engine = session.bind.sync_engine
    statements = []

    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        listed = (await client.get("/api/books")).json()[0]["teardown"]
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    detail = (await client.get(f"/api/books/{bid}")).json()["teardown"]
    assert listed == detail
    assert (listed["read"], listed["last_read"], listed["arcs"], listed["needs_closing"]) == (4, 5, 1, False)
    assert listed["ending"] == {"upto": 5, "ended": False}
    assert listed["waits"] == {"upto": 5, "total": 7, "open": 2}
    assert "private" not in str(listed)
    reads = [statement for statement in statements if "FROM chapters" in statement]
    assert len(reads) == 1 and "count(" in reads[0] and "max(chapters.index)" in reads[0]


async def test_arc_digest_scope_virtual_arc_and_ending_not_a_part(client, sessionmaker):
    bid, uid, vid, _, _, _ = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        arc = StoryNode(
            book_id=bid, kind="milestone", position=1, title="一篇", segment={"title": "一篇", "text": "篇文"}
        )
        ending = StoryNode(book_id=bid, kind="ending", position=2, title="结局", event="完结")
        other = StoryNode(book_id=uuid.uuid4(), kind="milestone", position=1, title="外篇")
        session.add_all([arc, ending])
        await session.flush()
        volume = await session.get(Volume, vid)
        volume.target_node_id = arc.id
        await session.commit()
    tree = (await client.get(f"/api/books/{bid}/outline-tree")).json()
    assert tree["segmented"] is True
    assert [row["title"] for row in tree["arcs"]] == ["一篇", "还没归篇"]
    virtual = tree["arcs"][-1]
    assert {key: value for key, value in virtual.items() if key != "volumes"} == {
        "node_id": None,
        "virtual": True,
        "title": "还没归篇",
        "text": "",
        "status": "done",
        "locked": True,
        "planned": True,
        "end": None,
    }
    assert virtual["volumes"][0]["index"] == 2
    assert tree["ending"] == {"node_id": str(ending.id), "title": "结局", "event": "完结"}
    digest = await client.get(f"/api/books/{bid}/teardown/digest", params={"arc": str(arc.id)})
    assert digest.status_code == 200
    assert digest.json() == (await client.get(f"/api/books/{bid}/teardown/digest", params={"unit": str(uid)})).json()
    for params in ({"arc": str(arc.id), "volume": str(vid)}, {"arc": str(arc.id), "unit": str(uid)}):
        assert (await client.get(f"/api/books/{bid}/teardown/digest", params=params)).status_code == 422
    for aid in (ending.id, other.book_id):
        response = await client.get(f"/api/books/{bid}/teardown/digest", params={"arc": str(aid)})
        assert response.status_code == 404 and response.json()["detail"] == "篇不存在"


@pytest.mark.parametrize("segmented", [True, False])
async def test_author_tree_complete_original_projection_unchanged(client, sessionmaker, segmented):
    async with sessionmaker() as session:
        book = Book(title="自己写的书", source="new")
        session.add(book)
        await session.flush()
        node = StoryNode(
            book_id=book.id,
            kind="milestone",
            position=1,
            title="节点",
            event="节点事件",
            segment={"title": "篇", "text": "篇文"} if segmented else None,
        )
        ending = StoryNode(book_id=book.id, kind="ending", position=2, title="结局", event="结局文字")
        session.add_all([node, ending])
        await session.flush()
        volume = Volume(
            book_id=book.id,
            index=1,
            title="卷",
            summary="卷文",
            chapter_count=2,
            target_node_id=node.id,
            status="planned",
        )
        loose = Volume(book_id=book.id, index=2, title="未挂篇卷", chapter_count=0)
        session.add_all([volume, loose])
        await session.commit()
    volume_out = {
        "id": str(volume.id),
        "index": 1,
        "title": "卷",
        "summary": "卷文",
        "chapter_count": 2,
        "status": "planned",
        "locked": False,
        "units": [],
    }
    loose_out = {
        "id": str(loose.id),
        "index": 2,
        "title": "未挂篇卷",
        "summary": "",
        "chapter_count": 0,
        "status": "planned",
        "locked": False,
        "units": [],
    }
    arcs = (
        [
            {
                "node_id": str(node.id),
                "title": "篇",
                "text": "篇文",
                "status": "planned",
                "locked": False,
                "planned": True,
                "end": {"title": "节点", "event": "节点事件", "kind": "milestone"},
                "volumes": [volume_out],
            },
            {
                "node_id": str(ending.id),
                "title": "结局",
                "text": "结局文字",
                "status": "later",
                "locked": False,
                "planned": False,
                "end": {"title": "结局", "event": "结局文字", "kind": "ending"},
                "volumes": [],
            },
        ]
        if segmented
        else [
            {
                "node_id": None,
                "title": "全书",
                "text": "",
                "status": "planned",
                "locked": False,
                "planned": True,
                "end": None,
                "volumes": [volume_out, loose_out],
            }
        ]
    )
    assert (await client.get(f"/api/books/{book.id}/outline-tree")).json() == {
        "arcs": arcs,
        "ending": {"node_id": str(ending.id), "title": "结局", "event": "结局文字"},
        "segmented": segmented,
    }


async def test_waits_api_payoff_order_and_chat_lookup(client, sessionmaker):
    bid, *_ = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "waits": {"upto": 4, "total": 3, "open": 1}}
        session.add_all(
            [
                Foreshadowing(
                    book_id=bid,
                    seq=3,
                    kind="期待",
                    description="找到家人",
                    planted_chapter=1,
                    hint_chapters=[2],
                    resolved_chapter=4,
                    status="resolved",
                    payoff_plan="第 4 章：在城中相逢",
                ),
                Foreshadowing(
                    book_id=bid, seq=1, kind="伏笔", description="玉佩来历", planted_chapter=2, status="planted"
                ),
                Foreshadowing(
                    book_id=bid,
                    seq=2,
                    kind="伏笔",
                    description="旧信的主人",
                    planted_chapter=1,
                    resolved_chapter=3,
                    status="resolved",
                    payoff_plan="第 3 章：查明是故人",
                ),
            ]
        )
        await session.commit()
        clues = await chat_tools.clues_text(session, book, ["E3", "F1", "F2"])
    assert all(text in clues for text in ["E3", "F1", "F2", "找到家人", "玉佩来历", "查明是故人"])
    response = (await client.get(f"/api/books/{bid}/teardown/waits")).json()
    assert response == {
        "upto": 4,
        "last": 4,
        "items": [
            {
                "code": "F2",
                "kind": "伏笔",
                "what": "旧信的主人",
                "planted": 1,
                "hints": [],
                "resolved": 3,
                "how": "查明是故人",
            },
            {
                "code": "E3",
                "kind": "期待",
                "what": "找到家人",
                "planted": 1,
                "hints": [2],
                "resolved": 4,
                "how": "在城中相逢",
            },
            {"code": "F1", "kind": "伏笔", "what": "玉佩来历", "planted": 2, "hints": [], "resolved": None, "how": ""},
        ],
    }
    async with sessionmaker() as session:
        (await session.get(Book, bid)).source = "new"
        await session.commit()
    assert (await client.get(f"/api/books/{bid}/teardown/waits")).json() == {"upto": None, "last": 0, "items": []}


@pytest.mark.parametrize("original,ending_node,ending_meta", [(True, True, False), (False, False, True)])
async def test_append_removes_ending_and_detaches_opened_volume_only(
    client, sessionmaker, original, ending_node, ending_meta
):
    bid, vid, _ = await append_seed(sessionmaker, original=original)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        if ending_meta:
            book.teardown = {**book.teardown, "ending": {"upto": 3, "ended": False}}
        arc = StoryNode(
            book_id=bid,
            kind="milestone",
            position=1,
            title="保留篇",
            segment={"title": "保留篇", "text": "作者改过的那段话"},
        )
        session.add(arc)
        if ending_node:
            session.add(StoryNode(book_id=bid, kind="ending", position=2, title="结局", event="旧结局"))
        await session.flush()
        (await session.get(Volume, vid)).target_node_id = arc.id
        await session.commit()
    response = await upload(client, bid, "第四章 后来\n新的正文。")
    assert response.status_code == 201, response.text
    assert response.json()["reopen"][-1] == {"kind": "ending"}
    response = await client.post(f"/api/teardown/{bid}/append/import", json={})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        assert not await session.scalar(select(StoryNode).where(StoryNode.book_id == bid, StoryNode.kind == "ending"))
        assert "ending" not in (await session.get(Book, bid)).teardown
        assert (await session.get(Volume, vid)).target_node_id is None
        assert (await session.get(StoryNode, arc.id)).segment["text"] == "作者改过的那段话"


def test_chat_outline_groups_arcs_unassigned_and_ending_and_info():
    nodes = [
        SimpleNamespace(id="a", kind="milestone", title="篇名", segment={"title": "篇名", "text": "第一句。第二句。"}),
        SimpleNamespace(id="e", kind="ending", event="全书收住。"),
    ]
    volumes = [
        SimpleNamespace(id="v1", index=1, title="卷一", summary="卷一文。", target_node_id="a"),
        SimpleNamespace(id="v2", index=2, title="卷二", summary="卷二文。", target_node_id=None),
    ]
    ctx = SimpleNamespace(nodes=nodes, volumes=volumes, units=[])
    text = teardown_chat.outline_of(ctx, [], full=False, open_volume_id=None)
    assert (
        text
        == "第 1 篇「篇名」（第 1–1 卷）：第一句。\n第 1 卷「卷一」：卷一文。\n还没归篇：\n第 2 卷「卷二」：卷二文。\n全书结局：全书收住。"
    )
    book = SimpleNamespace(
        title="原书",
        teardown={"stage": "done", "ending": {"upto": 2, "ended": True}, "waits": {"upto": 2, "total": 3, "open": 1}},
    )
    chapters = [SimpleNamespace(index=i, teardown={"read_version": 1}, word_count=1) for i in (1, 2)]
    info = teardown_chat.book_info(book, chapters, volumes, nodes=nodes)
    assert (
        "全书归成了 1 篇。原书到第 2 章完结，结局写在大纲的全书那一页。读者在等的事整理到第 2 章：一共 3 件，还吊着 1 件（编号 E 是期待、F 是伏笔，要细节用查伏笔的工具）。"
        in info
    )
    book.teardown["ending"]["ended"] = False
    assert "主编看过最后几章，原书到第 2 章还没完结。" in teardown_chat.book_info(book, chapters, volumes)
