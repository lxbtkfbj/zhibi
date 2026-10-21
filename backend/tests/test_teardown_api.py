"""拆书导入、只读投影、搜索、事务与存档的接口验收。"""

import asyncio
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import event, func, select

from app.config import get_settings
from app.main import create_app
from app.models import Book, BookSave, Chapter, TeardownSource, Volume
from app.services import book_saves

TEXT = "书名：《原书》\n作者：原作者\n简介：原简介\n序章\n风吹过山林。\n第一卷 山林\n第一章 初见\n茉莉拿起天毒珠。\n第二章 上架感言\n感谢读者，求票。\n第三章 再见\n天毒珠又亮了，天毒珠藏着秘密。\n第四章 空章\n第二卷 远方\n第五章 出发\n茉莉出发。"


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def upload(client, text=TEXT, name="原书.txt", encoding="utf-8"):
    response = await client.post("/api/teardown", files={"file": (name, text.encode(encoding), "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


async def test_upload_preview_encoding_import_and_archive(client, sessionmaker):
    preview = await upload(client)
    bid = preview["book_id"]
    assert preview["title"] == "原书" and preview["author"] == "原作者"
    assert preview["chapter_count"] == 4
    assert len(preview["excluded"]) == 2
    assert preview["first"] == {"index": 1, "title": "序章"}
    assert preview["volumes"][0]["chapters"] == 3
    assert (await client.get(f"/api/teardown/{bid}/preview")).json() == preview
    async with sessionmaker() as session:
        source = await session.get(TeardownSource, uuid.UUID(bid))
        assert source.data == TEXT.encode() and source.encoding == ""
        book = await session.get(Book, uuid.UUID(bid))
        assert set(book.teardown) == {"stage", "author", "intro", "file"}
        assert book.status == "writing"
        assert not await session.scalar(select(func.count()).select_from(Chapter))
    listing = (await client.get("/api/books")).json()[0]
    assert listing["source"] == "teardown" and listing["teardown"]["chapters"] == 4
    assert listing["teardown"]["read"] == 0
    assert listing["teardown"]["chars"] == preview["chars"]
    assert listing["teardown"]["imported_at"] is None
    changed = await client.patch(
        f"/api/books/{bid}", json={"title": "我改的书名", "author": "我填的作者", "intro": "我填的简介"}
    )
    assert changed.status_code == 200
    changed = await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "utf-8"})
    assert changed.status_code == 200
    assert changed.json()["title"] == "我改的书名"
    assert changed.json()["author"] == "我填的作者" and changed.json()["intro"] == "我填的简介"
    assert not changed.json()["encoding_auto"]
    include = [preview["excluded"][0]["order"]]
    imported = await client.post(
        f"/api/teardown/{bid}/import", json={"include": include, "author": "导入作者", "title": "最终书名"}
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["teardown"]["chapters"] == 5
    assert imported.json()["teardown"]["author"] == "导入作者"
    imported_at = imported.json()["teardown"]["imported_at"]
    assert imported_at
    assert (await client.get(f"/api/books/{bid}")).json()["teardown"]["imported_at"] == imported_at
    assert (
        next(book for book in (await client.get("/api/books")).json() if book["id"] == bid)["teardown"]["imported_at"]
        == imported_at
    )
    changed = await client.patch(f"/api/books/{bid}", json={"concept": {"genre": "玄幻"}, "review_changes": False})
    assert changed.json()["title"] == "最终书名"
    async with sessionmaker() as session:
        assert await session.get(TeardownSource, uuid.UUID(bid)) is None
        chapters = list(await session.scalars(select(Chapter).order_by(Chapter.index)))
        assert len(chapters) == 5 and all(
            c.unit_id is None and c.outline == {} and c.status == "final" and c.source == "imported" for c in chapters
        )
        assert chapters[1].teardown["raw_title"] == "第一章 初见" and chapters[1].teardown["number"] == 1
        assert chapters[2].title == "上架感言" and "不像正文" in chapters[2].teardown["flags"]
        assert chapters[0].teardown["number"] is None
        assert all(c.word_count == len("".join(c.content.split())) for c in chapters)
        volumes = list(await session.scalars(select(Volume).order_by(Volume.index)))
        assert [v.chapter_count for v in volumes] == [5]
        assert volumes[0].title == "还没分卷"
        assert all(c.volume_id == volumes[0].id for c in chapters)
        assert all(v.status == "done" for v in volumes)
        book = await session.get(Book, uuid.UUID(bid))
        assert book.teardown["imported_at"] == imported_at
        assert book.teardown["original_volumes"] is False
        assert book.teardown["open_volume_id"] == str(volumes[0].id)
        assert book.teardown["split"]["number_issue_total"] == 1
        save = await session.scalar(select(BookSave))
        assert save.title == "导入原文" and "teardown_sources" not in save.tree
    for method, path, kwargs in [
        ("get", "preview", {}),
        ("post", "encoding", {"json": {"encoding": "auto"}}),
        ("post", "import", {"json": {}}),
    ]:
        response = await getattr(client, method)(f"/api/teardown/{bid}/{path}", **kwargs)
        assert response.status_code == 409 and response.json()["detail"] == "这本书已经导入了"


async def test_encoding_errors_and_auto_and_cancel(client, sessionmaker):
    preview = await upload(client, "第一章 出发\n中文原文。", "《测试》（全本）.TXT", "gb18030")
    bid = preview["book_id"]
    assert preview["title"] == "测试"
    bad = await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "utf-8"})
    assert bad.status_code == 422 and bad.json()["detail"] == "用 UTF-8 读不出来，换一种试试"
    assert (await client.get(f"/api/teardown/{bid}/preview")).json() == preview
    good = await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "gb18030"})
    assert good.status_code == 200 and not good.json()["encoding_auto"]
    assert (await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "auto"})).json()["encoding_auto"]
    assert (await client.delete(f"/api/books/{bid}")).status_code == 204
    async with sessionmaker() as session:
        assert await session.get(TeardownSource, uuid.UUID(bid)) is None


async def test_upload_validation(client, monkeypatch):
    for name, data, code, detail in [
        ("bad.epub", b"content", 422, "只能导入 TXT 文件"),
        ("empty.txt", b" \r\n\t", 422, "文件里没有文字"),
    ]:
        response = await client.post("/api/teardown", files={"file": (name, data)})
        assert response.status_code == code and response.json()["detail"] == detail
    monkeypatch.setattr("app.api.teardown.MAX_BYTES", 20)
    response = await client.post("/api/teardown", files={"file": ("big.txt", b"a" * 21)})
    assert response.status_code == 413 and response.json()["detail"] == "文件超过 50MB"


async def test_no_volumes_virtual_unit_and_readonly_selects(client, sessionmaker):
    preview = await upload(client, "第一章\n天毒珠。\n第二章 后来\n接着出发。")
    bid = preview["book_id"]
    result = await client.post(f"/api/teardown/{bid}/import", json={})
    assert result.status_code == 200
    vid = result.json()["teardown"]["open_volume_id"]
    statements = []
    async with sessionmaker() as session:
        engine = session.bind.sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "chapters" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        tree = (await client.get(f"/api/books/{bid}/outline-tree")).json()
        for query in ("", "?with_outline=true", "?volume=1"):
            response = await client.get(f"/api/books/{bid}/chapters{query}")
            assert response.status_code == 200 and "content" not in response.json()[0]
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert statements and all("chapters.content" not in sql.split("FROM")[0] for sql in statements)
    volume = tree["arcs"][0]["volumes"][0]
    assert volume["title"] == "还没分卷" and volume["open"] is True and volume["status"] == "done"
    virtual = volume["units"][0]
    assert virtual["id"] == f"unassigned-{vid}" and virtual["virtual"] and virtual["index"] is None
    assert virtual["chapter_count"] == 2 and virtual["chapters"][0]["word_count"] == 4
    chapter = (await client.get(f"/api/books/{bid}/chapters/1")).json()
    assert chapter["title"] == "" and chapter["content"] == "天毒珠。"
    changed = await client.patch(
        f"/api/books/{bid}/chapters/1", json={"title": "手改章名", "outline": {"goal": "手改章纲"}}
    )
    assert changed.status_code == 200 and changed.json()["outline"]["goal"] == "手改章纲"


async def test_summary_and_detail_count_read_versions_with_one_grouped_list_query(client, sessionmaker):
    async with sessionmaker() as session:
        books = [
            Book(title="已读和未读", source="teardown", teardown={"stage": "stopped", "split": {"chapters": 5}}),
            Book(title="另一本拆的书", source="teardown", teardown={"stage": "running", "split": {"chapters": 2}}),
            Book(title="还没读", source="teardown", teardown={"stage": "imported", "split": {"chapters": 1}}),
            Book(title="作者自己的书", source="new"),
        ]
        session.add_all(books)
        await session.flush()
        ids = [book.id for book in books]
        records = [
            [
                {"read_version": 1},
                {"read_version": 2, "read_failed": {"error": "重读失败"}},
                {"read_failed": {"error": "没读成"}},
                {},
                {"read_version": None},
            ],
            [{"read_version": 1}, {}],
            [{}],
            [{"read_version": 1}],
        ]
        for book, teardown_rows in zip(books, records, strict=True):
            session.add_all(
                Chapter(book_id=book.id, index=index, content="原文不进书架查询", status="final", teardown=teardown)
                for index, teardown in enumerate(teardown_rows, 1)
            )
        await session.commit()
        engine = session.bind.sync_engine
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "chapters" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await client.get("/api/books")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    by_id = {book["id"]: book for book in response.json()}
    assert [by_id[str(bid)]["teardown"]["read"] for bid in ids[:3]] == [2, 1, 0]
    assert by_id[str(ids[3])]["teardown"] is None
    assert len(statements) == 1 and "GROUP BY chapters.book_id" in statements[0]
    assert "chapters.content" not in statements[0]
    for bid, expected in zip(ids[:3], [2, 1, 0], strict=True):
        response = await client.get(f"/api/books/{bid}")
        assert response.status_code == 200, response.text
        assert response.json()["teardown"]["read"] == expected
    chapter_flags = (await client.get(f"/api/books/{ids[0]}/chapters")).json()
    assert [chapter["teardown"]["read"] for chapter in chapter_flags] == [True, True, False, False, False]


async def test_search_shared_counts_literal_wildcards_and_limits(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="自己的书", status="writing")
        session.add(book)
        await session.flush()
        bid = book.id
        session.add_all(
            [
                Chapter(
                    book_id=bid, index=i, title=str(i), content="%_天毒珠\n" + "后" * 100 + "天毒珠", status="final"
                )
                for i in range(1, 206)
            ]
        )
        await session.commit()
    assert (await client.get(f"/api/books/{bid}")).json()["teardown"] is None
    result = (await client.get(f"/api/books/{bid}/search", params={"q": " 天毒珠 "})).json()
    assert result["chapters"] == 205 and len(result["results"]) == 200
    assert result["results"][0]["times"] == 2 and "\n" not in result["results"][0]["near"]
    assert len(result["results"][0]["near"]) == 2 + 3 + 60
    assert (await client.get(f"/api/books/{bid}/search", params={"q": "%_"})).json()["chapters"] == 205
    for q in ("", "   ", "字" * 31):
        response = await client.get(f"/api/books/{bid}/search", params={"q": q})
        assert response.status_code == 422 and response.json()["detail"] == "要搜的词 1 到 30 个字"
    assert (await client.get(f"/api/teardown/{bid}/preview")).status_code == 404


async def test_import_atomic_on_failure_and_double_submit(client, sessionmaker, monkeypatch):
    preview = await upload(client)
    bid = preview["book_id"]
    bad = await client.post(f"/api/teardown/{bid}/import", json={"include": [999]})
    assert bad.status_code == 422
    from app.services import teardown_split

    original = teardown_split.number_issues

    def fail(chapters):
        raise RuntimeError("事务中止测试")

    monkeypatch.setattr(teardown_split, "number_issues", fail)
    with pytest.raises(RuntimeError, match="事务中止测试"):
        await client.post(f"/api/teardown/{bid}/import", json={})
    async with sessionmaker() as session:
        assert (await session.get(Book, uuid.UUID(bid))).teardown["stage"] == "confirming"
        assert await session.get(TeardownSource, uuid.UUID(bid)) is not None
        assert not await session.scalar(select(func.count()).select_from(Chapter))
        assert not await session.scalar(select(func.count()).select_from(Volume))
    monkeypatch.setattr(teardown_split, "number_issues", original)
    results = await asyncio.gather(*(client.post(f"/api/teardown/{bid}/import", json={}) for _ in range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_save_restore_keeps_imported_metadata_and_source_absent(client, sessionmaker):
    preview = await upload(client)
    bid = preview["book_id"]
    assert (await client.post(f"/api/teardown/{bid}/import", json={})).status_code == 200
    async with sessionmaker() as session:
        save = await session.scalar(select(BookSave))
        chapter = await session.scalar(select(Chapter).where(Chapter.index == 1))
        raw = dict(chapter.teardown)
        chapter.title = "后改"
        await session.commit()
        await book_saves.restore(session, uuid.UUID(bid), save.id)
        book = await session.get(Book, uuid.UUID(bid))
        chapter = await session.scalar(select(Chapter).where(Chapter.index == 1))
        assert chapter.title == "序章" and chapter.teardown == raw
        assert book.teardown["stage"] == "imported" and book.source == "teardown"
        assert await session.get(TeardownSource, uuid.UUID(bid)) is None


async def test_restore_before_import_never_deletes_only_remaining_original(client, sessionmaker):
    preview = await upload(client)
    bid = preview["book_id"]
    saved = (await client.post(f"/api/books/{bid}/saves", json={"label": "确认之前"})).json()["save"]
    assert (await client.post(f"/api/teardown/{bid}/import", json={})).status_code == 200
    response = await client.post(f"/api/books/{bid}/saves/{saved['id']}/restore")
    assert response.status_code == 409 and "导入前的存档没有原文件" in response.json()["detail"]
    async with sessionmaker() as session:
        assert (await session.get(Book, uuid.UUID(bid))).teardown["stage"] == "imported"
        assert (
            await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.book_id == uuid.UUID(bid)))
            == 4
        )


def test_empty_teardown_does_not_invalidate_legacy_saved_rows():
    for model in (Book, Chapter):
        before = {"title": "作者原来的文字", "source": "new" if model is Book else "generated"}
        assert book_saves.row_data(model, before) == book_saves.row_data(model, {**before, "teardown": {}})
        assert book_saves.row_data(model, {**before, "teardown": {"stage": "imported"}})["teardown"] == {
            "stage": "imported"
        }
