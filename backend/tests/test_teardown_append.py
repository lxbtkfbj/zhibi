"""补章节：重算接缝、收尾边界、存档与假模型接着拆；不接触作者书库。"""

import asyncio
import copy

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import event, select

from app.agents import schemas as s
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, BookSave, Chapter, Character, Job, PlotUnit, TeardownSource, Volume
from app.prompts import default_content
from app.services import book_saves, jobs, teardown_split
from app.services.teardown_runner import Runner
from tests.test_teardown_runner import DemoRouter


@pytest.fixture
async def client(monkeypatch):
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(jobs, "enqueue_teardown", lambda _: None)
    monkeypatch.setattr("app.prompts._load", default_content)
    monkeypatch.setattr(demo, "DELAY_S", 0)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def seed(sm, *, original=True, stage="done", summary="旧卷那段话", grouped=True, opened=False):
    async with sm() as session:
        book = Book(
            title="作者改过的书名",
            source="teardown",
            status="writing",
            teardown={
                "stage": stage,
                "upto": None,
                "original_volumes": original,
                "settings": {"upto": 3, "kept": "整理设定的记录"},
                "merits": {"upto": 3, "points": [{"title": "作者保留的好在哪", "text": "不改"}]},
                "names": {"name": "人名映射"},
                "split": {"chapters": 3, "chars": 9, "volumes": 1, "number_issue_total": 2},
                "number_issues": [{"index": 2, "kind": "跳了"}],
                "excluded": [{"title": "以前排掉的"}],
            },
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="末卷", chapter_count=3, summary=summary, status="done")
        session.add(volume)
        await session.flush()
        if opened:
            book.teardown = {**book.teardown, "open_volume_id": str(volume.id)}
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="旧单元", chapter_count=3, status="done")
        session.add(unit)
        await session.flush()
        for index in range(1, 4):
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    unit_id=unit.id if grouped else None,
                    index=index,
                    title=f"章名{index}",
                    content=f"旧文{index}",
                    word_count=3,
                    source="imported",
                    status="final",
                    outline={"goal": f"作者章纲{index}"},
                    summary=f"旧摘要{index}",
                    teardown={
                        "number": index,
                        "raw_title": f"第{index}章 章名{index}",
                        "flags": [],
                        "read_version": 1,
                        "read": {"feel": "爽", "people": [], "things": [], "moments": [], "waits": [], "tropes": []},
                    },
                )
            )
        session.add(Character(book_id=book.id, name="作者角色", source="author", notes="不许改"))
        await session.commit()
        return book.id, volume.id, unit.id


async def upload(client, bid, text="第四章 后来\n新正文4。\n第五章 接着\n新正文5。", name="后续.txt"):
    return await client.post(f"/api/teardown/{bid}/append", files={"file": (name, text.encode())})


def test_split_append_preserves_missing_initial_volume_and_normal_import():
    raw = "第三章 开头\n旧卷结尾。\n第二卷 新卷\n第一章 新的\n新卷正文。".encode()
    append = teardown_split.split(raw, append=True)
    normal = teardown_split.split(raw)
    assert append["volumes"] == ["新卷"]
    assert [ch.volume for ch in append["chapters"]] == [None, 1]
    assert normal["volumes"] == ["第一卷", "新卷"]
    assert [ch.volume for ch in normal["chapters"]] == [1, 2]


async def test_duplicates_leading_content_and_middle_heading_not_duplicate(client, sessionmaker):
    bid, _, _ = await seed(sessionmaker)
    response = await upload(
        client,
        bid,
        "第二章 章名2\n不同的正文。\n第三章 章名3\n不同。\n第四章 新章\n新正文。\n"
        "第一章 章名1\n旧文1\n第二章 章名2\n不是原文。",
    )
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["chapter_count"] == 2
    assert preview["duplicates"] == {
        "leading": [{"number": 2, "title": "章名2"}, {"number": 3, "title": "章名3"}],
        "content": 1,
    }
    assert preview["first"] == {"index": 4, "title": "新章", "order": 2}
    assert preview["last"] == {"index": 5, "title": "章名2", "order": 4}
    result = await client.post(f"/api/teardown/{bid}/append/import", json={})
    assert result.status_code == 200, result.text
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert [entry["reason"] for entry in book.teardown["excluded"][1:]] == [
            "章号章名一样",
            "章号章名一样",
            "正文一样",
        ]


@pytest.mark.parametrize(
    "text,kind",
    [
        ("第四章 后来\n新文。", None),
        ("第六章 后来\n新文。", "跳了"),
        ("第二章 不同的章名\n新文。", "倒回去了"),
        ("第二卷 新卷\n第一章 后来\n新文。", None),
    ],
)
async def test_junction_uses_original_number_and_volume(client, sessionmaker, text, kind):
    bid, _, _ = await seed(sessionmaker)
    response = await upload(client, bid, text)
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["junction"]["kind"] == kind
    assert all(issue["index"] == 4 for issue in preview["number_issues"])
    assert preview["junction"]["a"] == 3


@pytest.mark.parametrize(
    "text,expected_titles,expected_counts,reopen_unit",
    [
        ("第四章 继续\n新文。", ["末卷"], [4], True),
        ("第一卷 末卷\n第四章 继续\n新文。", ["末卷"], [4], True),
        ("第四章 继续\n新文。\n第二卷 新卷\n第一章 另起\n新卷正文。", ["末卷", "新卷"], [4, 1], True),
        ("第二卷 新卷\n第一章 另起\n新卷正文。", ["末卷", "新卷"], [3, 1], False),
    ],
)
async def test_original_volume_destinations_and_exact_tail_reopening(
    client, sessionmaker, text, expected_titles, expected_counts, reopen_unit
):
    bid, vid, uid = await seed(sessionmaker)
    response = await upload(client, bid, text)
    assert response.status_code == 201, response.text
    assert [entry["kind"] for entry in response.json()["reopen"]] == (
        ["unit", "summary"] if reopen_unit else ["summary"]
    )
    assert (await client.post(f"/api/teardown/{bid}/append/import", json={})).status_code == 200
    async with sessionmaker() as session:
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == bid).order_by(Volume.index)))
        assert [volume.title for volume in volumes] == expected_titles
        assert [volume.chapter_count for volume in volumes] == expected_counts
        assert all(volume.summary == "" for volume in volumes)
        assert (await session.get(PlotUnit, uid) is None) == reopen_unit
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid).order_by(Chapter.index)))
        assert chapters[0].outline == {"goal": "作者章纲1"} and chapters[0].teardown["read_version"] == 1
        assert chapters[0].unit_id == (None if reopen_unit else uid)
        assert all(
            ch.unit_id is None and ch.outline == {} and ch.status == "final" and ch.source == "imported"
            for ch in chapters[3:]
        )
        assert volumes[0].id == vid


@pytest.mark.parametrize(
    "original,summary,grouped,opened,expected",
    [
        (True, "", False, False, []),
        (False, "旧段落", True, False, ["unit", "volume"]),
        (False, "旧段落", False, True, []),
    ],
)
async def test_three_reopening_conditions_and_negative_cases(
    client, sessionmaker, original, summary, grouped, opened, expected
):
    bid, vid, _ = await seed(sessionmaker, original=original, summary=summary, grouped=grouped, opened=opened)
    response = await upload(client, bid, "第二卷 不采用\n第四章 后来\n新正文。")
    assert response.status_code == 201, response.text
    assert [entry["kind"] for entry in response.json()["reopen"]] == expected
    assert response.json()["ignored_volumes"] == (0 if original else 1)
    assert (await client.post(f"/api/teardown/{bid}/append/import", json={})).status_code == 200
    async with sessionmaker() as session:
        volume = await session.get(Volume, vid)
        book = await session.get(Book, bid)
        if not original:
            assert volume.chapter_count == 4
            assert book.teardown["open_volume_id"] == str(vid)
            if not opened:
                assert volume.title == "还没收尾" and volume.status == "planned" and volume.summary == ""
            else:
                assert volume.title == "末卷" and volume.summary == "旧段落" and volume.status == "done"


@pytest.mark.parametrize("stage", ["done", "imported", "stopped"])
async def test_append_state_metadata_archive_restore_and_author_protections(client, sessionmaker, stage):
    bid, vid, uid = await seed(sessionmaker, original=False, stage=stage)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.teardown = {**book.teardown, "stop_reason": "author", "stop_note": "原来停下的说明"}
        await session.commit()
        before = copy.deepcopy(book.teardown)
    response = await upload(client, bid)
    assert response.status_code == 201
    assert (await client.get(f"/api/books/{bid}")).json()["teardown"]["adding"] == {"file": "后续.txt", "chapters": 2}
    response = await client.post(f"/api/teardown/{bid}/append/import", json={})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        assert book.title == "作者改过的书名" and book.teardown["upto"] == 3
        assert book.teardown["stage"] == ("stopped" if stage == "done" else stage)
        assert book.teardown["stop_reason"] == ("added" if stage == "done" else "author")
        assert book.teardown["stop_note"] == ("补了第 4–5 章，还没拆。" if stage == "done" else "原来停下的说明")
        for key in ("settings", "merits", "names"):
            assert book.teardown[key] == before[key]
        assert book.teardown["split"] == {**before["split"], "chapters": 5, "chars": 19}
        assert book.teardown["added"][0]["first"] == 4 and book.teardown["added"][0]["last"] == 5
        assert await session.get(TeardownSource, bid) is None
        character = await session.scalar(select(Character).where(Character.book_id == bid))
        assert character.source == "author" and character.notes == "不许改"
        saves = list(await session.scalars(select(BookSave).where(BookSave.book_id == bid).order_by(BookSave.id)))
        assert [save.title for save in saves] == ["补章节前", "补了第 4–5 章"]
        await book_saves.restore(session, bid, saves[0].id)
        book = await session.get(Book, bid)
        assert book.teardown == before
        volume = await session.get(Volume, vid)
        assert volume.summary == "旧卷那段话" and volume.title == "末卷" and volume.status == "done"
        assert await session.get(PlotUnit, uid) is not None
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid)))
        assert len(chapters) == 3 and all(ch.unit_id == uid for ch in chapters)


async def test_restore_removes_new_volumes_and_added_chapters(client, sessionmaker):
    bid, _, uid = await seed(sessionmaker)
    assert (await upload(client, bid, "第二卷 新卷\n第一章 后来\n新文。")).status_code == 201
    assert (await client.post(f"/api/teardown/{bid}/append/import", json={})).status_code == 200
    async with sessionmaker() as session:
        before = await session.scalar(select(BookSave).where(BookSave.title == "补章节前"))
        await book_saves.restore(session, bid, before.id)
        assert len(list(await session.scalars(select(Volume).where(Volume.book_id == bid)))) == 1
        assert len(list(await session.scalars(select(Chapter).where(Chapter.book_id == bid)))) == 3
        assert await session.get(PlotUnit, uid) is not None


@pytest.mark.parametrize(
    "block,status,message",
    [
        ("confirming", 409, "这本书还没导入，先在确认页导入"),
        ("new", 404, "这本书不是拆的书"),
        ("queued", 409, "这本书正在拆，先停下再补"),
        ("running", 409, "这本书正在拆，先停下再补"),
        ("editorial", 409, "这本书正在拆，先停下再补"),
    ],
)
async def test_every_append_endpoint_checks_state_under_book_lock(client, sessionmaker, block, status, message):
    bid, _, _ = await seed(sessionmaker)
    assert (await upload(client, bid)).status_code == 201
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        if block == "new":
            book.source = "new"
        elif block == "confirming":
            book.teardown = {**book.teardown, "stage": block}
        else:
            session.add(
                Job(
                    book_id=bid,
                    kind="chat" if block == "editorial" else "teardown",
                    thread_id="busy",
                    status="running" if block == "editorial" else block,
                )
            )
        await session.commit()
    for method, path, kwargs in [
        ("get", "", {}),
        ("delete", "", {}),
        ("post", "", {"files": {"file": ("more.txt", b"text")}}),
        ("post", "/encoding", {"json": {"encoding": "auto"}}),
        ("post", "/import", {"json": {}}),
    ]:
        response = await getattr(client, method)(f"/api/teardown/{bid}/append{path}", **kwargs)
        assert response.status_code == status and response.json()["detail"] == message


async def test_duplicate_and_empty_errors_encoding_replace_cancel_and_validation(client, sessionmaker, monkeypatch):
    bid, _, _ = await seed(sessionmaker)
    assert (await client.get(f"/api/teardown/{bid}/append")).json()["detail"] == "没有待确认的补章节"
    response = await upload(client, bid, "第一章 章名1\n不同正文。\n第二章 章名2\n不同正文。")
    assert response.status_code == 422 and response.json()["detail"] == "这个文件里的章书里都有了"
    response = await upload(client, bid, "第四章 上架感言\n感谢读者，求票。")
    assert response.status_code == 422 and response.json()["detail"] == "没有要补的章节，请勾选后再补"
    assert (await upload(client, bid, name="bad.epub")).json()["detail"] == "只能导入 TXT 文件"
    monkeypatch.setattr("app.api.teardown.MAX_BYTES", 10)
    response = await upload(client, bid)
    assert response.status_code == 413 and response.json()["detail"] == "文件超过 50MB"
    monkeypatch.setattr("app.api.teardown.MAX_BYTES", 52428800)
    response = await client.post(
        f"/api/teardown/{bid}/append", files={"file": ("编码.txt", "第四章 中文\n后面的正文。".encode("gb18030"))}
    )
    assert response.status_code == 201
    response = await client.post(f"/api/teardown/{bid}/append/encoding", json={"encoding": "utf-8"})
    assert response.status_code == 422 and response.json()["detail"] == "用 UTF-8 读不出来，换一种试试"
    assert (await client.post(f"/api/teardown/{bid}/append/encoding", json={"encoding": "gb18030"})).json()[
        "encoding_auto"
    ] is False
    assert (await client.post(f"/api/teardown/{bid}/append/encoding", json={"encoding": "auto"})).json()[
        "encoding_auto"
    ] is True
    assert (await upload(client, bid)).status_code == 201
    assert (await client.get(f"/api/teardown/{bid}/append")).json()["file"]["name"] == "后续.txt"
    assert (await client.delete(f"/api/teardown/{bid}/append")).status_code == 204
    assert (await client.get(f"/api/teardown/{bid}/append")).status_code == 404


async def test_import_recomputes_against_current_book_and_include_order(client, sessionmaker):
    bid, _, uid = await seed(sessionmaker)
    response = await upload(client, bid, "第四章 后来\n新正文。\n第五章 上架感言\n谢谢读者。\n第六章 再来\n正文。")
    assert response.status_code == 201
    order = response.json()["excluded"][0]["order"]
    async with sessionmaker() as session:
        last = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 3))
        last.unit_id = None
        volume = await session.get(Volume, last.volume_id)
        volume.summary = ""
        await session.commit()
    assert (await client.post(f"/api/teardown/{bid}/append/import", json={"include": [999]})).status_code == 422
    response = await client.post(f"/api/teardown/{bid}/append/import", json={"include": [order]})
    assert response.status_code == 200, response.text
    assert response.json()["teardown"]["chapters"] == 6
    async with sessionmaker() as session:
        assert await session.get(PlotUnit, uid) is not None
        last = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 5))
        assert "不像正文" in last.teardown["flags"]


async def test_import_recomputes_duplicates_added_after_upload_and_double_submit(client, sessionmaker):
    bid, vid, _ = await seed(sessionmaker)
    assert (await upload(client, bid)).status_code == 201
    async with sessionmaker() as session:
        session.add(
            Chapter(
                book_id=bid,
                volume_id=vid,
                index=4,
                title="后来",
                content="已被别处接进来",
                teardown={"number": 4, "flags": []},
            )
        )
        volume = await session.get(Volume, vid)
        volume.chapter_count += 1
        await session.commit()
    results = await asyncio.gather(*(client.post(f"/api/teardown/{bid}/append/import", json={}) for _ in range(2)))
    assert sorted(response.status_code for response in results) == [200, 404]
    saved = next(response.json() for response in results if response.status_code == 200)
    assert saved["teardown"]["added"][0]["chapters"] == 1
    assert saved["teardown"]["added"][0]["first"] == 5


async def test_import_reloads_identity_map_after_before_checkpoint_commit(client, sessionmaker, monkeypatch):
    bid, vid, uid = await seed(sessionmaker)
    assert (await upload(client, bid)).status_code == 201
    checkpoint = book_saves.checkpoint

    async def checkpoint_with_other_editor(session, book_id, *args, **kwargs):
        saved = await checkpoint(session, book_id, *args, **kwargs)
        if kwargs.get("title") == "补章节前":
            # 同一 HTTP 请求第一遍 plan 已把这些行装进 identity map。
            async with sessionmaker() as another:
                last = await another.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 3))
                last.unit_id = None
                volume = await another.get(Volume, vid)
                volume.summary = "刚被作者改过的段落"
                await another.commit()
        return saved

    monkeypatch.setattr(book_saves, "checkpoint", checkpoint_with_other_editor)
    response = await client.post(f"/api/teardown/{bid}/append/import", json={})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        assert await session.get(PlotUnit, uid) is not None
        volume = await session.get(Volume, vid)
        assert volume.summary == ""
        first = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 1))
        assert first.unit_id == uid


@pytest.mark.parametrize("changed", ["data", "encoding", "filename", "size"])
async def test_import_rejects_replaced_source_in_checkpoint_gap_even_with_same_include_orders(
    client, sessionmaker, monkeypatch, changed
):
    bid, vid, uid = await seed(sessionmaker)
    response = await upload(client, bid, "第四章 上架感言\n感谢读者。\n第五章 保留\n新正文。")
    assert response.status_code == 201, response.text
    include_order = response.json()["excluded"][0]["order"]
    checkpoint = book_saves.checkpoint
    replacement = "第四章 上架感言\n另一次感谢读者。\n第五章 换文件\n不同正文。".encode()

    async def checkpoint_with_replacement(session, book_id, *args, **kwargs):
        saved = await checkpoint(session, book_id, *args, **kwargs)
        if kwargs.get("title") == "补章节前":
            async with sessionmaker() as another:
                source = await another.get(TeardownSource, bid)
                if changed == "data":
                    source.data = replacement
                elif changed == "encoding":
                    source.encoding = "utf-8"
                elif changed == "filename":
                    source.filename = "另外上传的.txt"
                else:
                    source.size += 1
                await another.commit()
        return saved

    monkeypatch.setattr(book_saves, "checkpoint", checkpoint_with_replacement)
    response = await client.post(f"/api/teardown/{bid}/append/import", json={"include": [include_order]})
    assert response.status_code == 409 and response.json()["detail"] == "待确认的文件已经换了，请刷新确认页"
    async with sessionmaker() as session:
        source = await session.get(TeardownSource, bid)
        assert source is not None
        if changed == "data":
            assert source.data == replacement
        elif changed == "encoding":
            assert source.encoding == "utf-8"
        elif changed == "filename":
            assert source.filename == "另外上传的.txt"
        assert len(list(await session.scalars(select(Chapter).where(Chapter.book_id == bid)))) == 3
        assert await session.get(PlotUnit, uid) is not None
        volume = await session.get(Volume, vid)
        assert volume.summary == "旧卷那段话" and volume.chapter_count == 3


async def test_junction_uses_last_numbered_non_extra_and_offsets_after_special(client, sessionmaker):
    bid, vid, _ = await seed(sessionmaker)
    async with sessionmaker() as session:
        last = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 3))
        last.teardown = {**last.teardown, "number": 7}
        session.add(
            Chapter(
                book_id=bid,
                volume_id=vid,
                index=4,
                title="番外",
                content="番外正文",
                teardown={"number": 99, "flags": ["番外"]},
            )
        )
        volume = await session.get(Volume, vid)
        volume.chapter_count = 4
        await session.commit()
    response = await upload(client, bid, "序章 开头\n接下来的开头。\n第九章 后来\n新正文。")
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["junction"] == {"kind": "跳了", "a": 7, "b": 9, "missing": 1}
    assert preview["number_issues"][0]["index"] == 6


async def test_append_changes_are_atomic_and_before_checkpoint_failure_cannot_apply(client, sessionmaker, monkeypatch):
    bid, _, uid = await seed(sessionmaker)
    assert (await upload(client, bid)).status_code == 201
    checkpoint = book_saves.checkpoint

    async def fail_checkpoint(*args, **kwargs):
        raise RuntimeError("存档失败测试")

    monkeypatch.setattr(book_saves, "checkpoint", fail_checkpoint)
    with pytest.raises(RuntimeError, match="存档失败测试"):
        await client.post(f"/api/teardown/{bid}/append/import", json={})
    async with sessionmaker() as session:
        assert len(list(await session.scalars(select(Chapter).where(Chapter.book_id == bid)))) == 3
        assert await session.get(PlotUnit, uid) is not None
        assert await session.get(TeardownSource, bid) is not None
    monkeypatch.setattr(book_saves, "checkpoint", checkpoint)
    # 插入失败时，前面的删单元、清段落等也不能部分提交。
    import app.api.teardown as api

    def fail_insert(*args, **kwargs):
        raise RuntimeError("写章节失败测试")

    monkeypatch.setattr(api, "insert", fail_insert)
    with pytest.raises(RuntimeError, match="写章节失败测试"):
        await client.post(f"/api/teardown/{bid}/append/import", json={})
    async with sessionmaker() as session:
        assert await session.get(PlotUnit, uid) is not None
        assert await session.get(TeardownSource, bid) is not None
        volume = await session.scalar(select(Volume).where(Volume.book_id == bid))
        assert volume.summary == "旧卷那段话" and volume.chapter_count == 3


async def test_list_adding_previews_are_batched_with_confirming(client, sessionmaker):
    bid, _, _ = await seed(sessionmaker)
    assert (await upload(client, bid)).status_code == 201
    response = await client.post("/api/teardown", files={"file": ("新书.txt", "第一章 初见\n原文。".encode())})
    assert response.status_code == 201
    async with sessionmaker() as session:
        engine = session.bind.sync_engine
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "teardown_sources" in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        books = (await client.get("/api/books")).json()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    by_id = {book["id"]: book for book in books}
    assert by_id[str(bid)]["teardown"]["adding"] == {"file": "后续.txt", "chapters": 2}
    assert by_id[response.json()["book_id"]]["teardown"]["adding"] is None


@pytest.mark.parametrize("original", [True, False])
async def test_start_after_append_reads_new_chapters_regroups_reopened_unit_and_rewrites_volume(
    client, sessionmaker, original
):
    bid, vid, uid = await seed(sessionmaker, original=original)
    async with sessionmaker() as session:
        old = await session.scalar(select(Chapter).where(Chapter.book_id == bid, Chapter.index == 2))
        old.teardown = {**old.teardown, "read_failed": {"error": "旧章曾重读失败"}}
        await session.commit()
    assert (await upload(client, bid)).status_code == 201
    response = await client.post(f"/api/teardown/{bid}/append/import", json={"start": {"upto": None}})
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        job = await session.scalar(select(Job).where(Job.book_id == bid))
        assert job.params["retry_failed_only"] is False
        assert job.pending["teardown"]["target"] == 5
        assert job.params["previous_teardown"]["upto"] == 3
        jid = job.id
    router = DemoRouter()
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await Runner(jid, sessionmaker, redis, router).run()
    finally:
        await redis.aclose()
    reads = [call for call in router.calls if call["schema"] == s.TeardownRead]
    assert (
        reads and any("第 4 章" in call["user"] for call in reads) and any("第 5 章" in call["user"] for call in reads)
    )
    assert all("「第 1 章 " not in call["user"] and "「第 3 章 " not in call["user"] for call in reads)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        job = await session.get(Job, jid)
        assert job.status == "succeeded" and book.teardown["stage"] == "done"
        assert await session.get(PlotUnit, uid) is None
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == bid).order_by(Chapter.index)))
        assert all(chapter.unit_id is not None for chapter in chapters)
        assert chapters[0].teardown["read_version"] == 1 and chapters[2].teardown["read_version"] == 1
        assert chapters[0].outline == {"goal": "作者章纲1"}
        assert chapters[3].teardown["read_version"] == 1 and chapters[4].teardown["read_version"] == 1
        volume = await session.get(Volume, vid)
        assert volume.summary and volume.summary != "旧卷那段话"
