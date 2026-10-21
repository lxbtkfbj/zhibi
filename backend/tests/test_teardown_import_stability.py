"""导入更稳：转换选择、主编分卷与排除理由经过真实接口/数据库验证。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.main import create_app
from app.models import Book, Chapter, TeardownSource, Volume


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def upload(client, text):
    response = await client.post("/api/teardown", files={"file": ("測試書.txt", text.encode(), "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("convert", [True, False])
async def test_t2s_preview_switch_import_and_append_follow_book(client, sessionmaker, convert):
    preview = await upload(client, "書名：繁體書\n第一卷 龍門\n第一章 初見\n這裡的頭髮與發展不同，主角推開門。")
    bid = preview["book_id"]
    assert preview["traditional"] and preview["t2s"]
    assert preview["title"] == "繁体书" and preview["opening"].startswith("这里的头发与发展")
    response = await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "auto", "t2s": convert})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["traditional"] and preview["t2s"] is convert
    assert preview["title"] == ("繁体书" if convert else "繁體書")
    assert preview["volumes"][0]["title"] == ("龙门" if convert else "龍門")
    preserved = await client.post(f"/api/teardown/{bid}/encoding", json={"encoding": "utf-8"})
    assert preserved.json()["t2s"] is convert
    imported = await client.post(f"/api/teardown/{bid}/import", json={"volume_mode": "editor"})
    assert imported.status_code == 200, imported.text
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(bid))
        assert book.teardown["t2s"] is convert
        first = await session.scalar(select(Chapter).where(Chapter.book_id == book.id))
        assert first.title == ("初见" if convert else "初見")
        assert first.content.startswith("这里" if convert else "這裡")
    appended = await client.post(
        f"/api/teardown/{bid}/append",
        files={"file": ("後續.txt", "第二卷 不用這個卷名\n第二章 後來\n頭髮與發展仍然不同，主角繼續向前。".encode())},
    )
    assert appended.status_code == 201, appended.text
    assert appended.json()["t2s"] is convert
    assert appended.json()["ignored_volumes"] == 1 and appended.json()["volumes"] == []
    # 补章节不允许调用者借共用的编码接口改变书级选择。
    encoded = await client.post(f"/api/teardown/{bid}/append/encoding", json={"encoding": "auto", "t2s": not convert})
    assert encoded.status_code == 200 and encoded.json()["t2s"] is convert
    done = await client.post(f"/api/teardown/{bid}/append/import", json={})
    assert done.status_code == 200, done.text
    async with sessionmaker() as session:
        chapters = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(bid)).order_by(Chapter.index))
        )
        assert len(chapters) == 2 and chapters[0].volume_id == chapters[1].volume_id
        assert chapters[1].title == ("后来" if convert else "後來")
        assert chapters[1].content.startswith("头发与发展" if convert else "頭髮與發展")


@pytest.mark.parametrize("mode", [None, "editor", "original"])
async def test_every_import_matches_no_volume_exactly_even_legacy_mode(client, sessionmaker, mode):
    body = "第一章 开始\n山林中的人向前走。\n第二章 继续\n山林中的人停下来。"
    normal = await upload(client, body)
    assert (await client.post(f"/api/teardown/{normal['book_id']}/import", json={})).status_code == 200
    with_volumes = await upload(client, "第一卷 山林\n" + body.replace("第二章", "第二卷 远方\n第二章"))
    assert "volume_mode" not in with_volumes and "largest_volume" not in with_volumes
    bid = with_volumes["book_id"]
    payload = {} if mode is None else {"volume_mode": mode}
    assert (await client.post(f"/api/teardown/{bid}/import", json=payload)).status_code == 200
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(bid))
        base = await session.get(Book, uuid.UUID(normal["book_id"]))
        volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index)))
        chapters = list(
            await session.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index))
        )
        base_volume = await session.scalar(select(Volume).where(Volume.book_id == base.id))
        fields = ("title", "status", "chapter_count", "summary", "index")
        assert len(volumes) == 1 and volumes[0].title == "还没分卷"
        assert [getattr(volumes[0], key) for key in fields] == [getattr(base_volume, key) for key in fields]
        assert book.teardown["original_volumes"] is base.teardown["original_volumes"] is False
        assert book.teardown["open_volume_id"] == str(volumes[0].id)
        assert base.teardown["open_volume_id"] == str(base_volume.id)
        assert all(ch.volume_id == volumes[0].id for ch in chapters)
    tree = (await client.get(f"/api/books/{bid}/outline-tree")).json()
    assert tree["arcs"][0]["volumes"][0]["open"] is True


async def test_large_volume_import_also_uses_editor_without_preview_choice(client, sessionmaker):
    preview = await upload(
        client, "第一卷 大卷\n" + "\n".join(f"第{i}章 章名{i}\n山林中的人向前走到第{i}处。" for i in range(1, 402))
    )
    assert "volume_mode" not in preview and "largest_volume" not in preview
    assert preview["volumes"][0]["chapters"] == 401
    bid = preview["book_id"]
    assert (await client.post(f"/api/teardown/{bid}/import", json={})).status_code == 200
    async with sessionmaker() as session:
        book = await session.get(Book, uuid.UUID(bid))
        assert book.teardown["original_volumes"] is False and book.teardown["open_volume_id"]
        assert await session.get(TeardownSource, book.id) is None


async def test_new_exclusions_can_all_be_checked_back_in(client, sessionmaker):
    content = "山林中少年推开门，往前走，看见熟悉的人。" * 10
    text = (
        "第51章 主线\n"
        + content
        + "\n第一章 外书\n不同世界的人走进门。\n第二章 外书续\n另一个世界的少年离开了。"
        + "\n第52章 报错\nHTTP/1.1 200 OK 余额不足\n第53章 重复\n"
        + content
        + "\n第53章 重复\n"
        + content[:-1]
        + "！\n第54章 回归\n主线少年回到山林。"
    )
    preview = await upload(client, text)
    reasons = {item["reason"] for item in preview["excluded"]}
    assert reasons == {"像是混进来的别的书", "乱码", "和前面一章重复"}
    bid = preview["book_id"]
    bad = await client.post(f"/api/teardown/{bid}/import", json={"include": [999]})
    assert bad.status_code == 422
    good = await client.post(
        f"/api/teardown/{bid}/import", json={"include": [item["order"] for item in preview["excluded"]]}
    )
    assert good.status_code == 200, good.text
    async with sessionmaker() as session:
        chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == uuid.UUID(bid))))
        assert len(chapters) == preview["chapter_count"] + len(preview["excluded"])


async def test_switch_encoding_first_detects_traditional_and_defaults_conversion(client):
    response = await client.post(
        "/api/teardown", files={"file": ("big5.txt", "第一章 風雲\n這是小說。".encode("big5"))}
    )
    assert response.status_code == 201
    initial = response.json()
    assert initial["traditional"] is False and initial["t2s"] is False
    changed = await client.post(f"/api/teardown/{initial['book_id']}/encoding", json={"encoding": "big5"})
    assert changed.status_code == 200
    assert changed.json()["traditional"] is True and changed.json()["t2s"] is True
    assert changed.json()["first"]["title"] == "风云"


async def test_append_mainline_skips_foreign_anchor_and_junction(client):
    initial = await upload(client, "第51章 主线\n主线少年走进山林。\n第一章 外书\n另一本书里的少年离开了。")
    bid = initial["book_id"]
    include = [item["order"] for item in initial["excluded"]]
    assert len(include) == 1
    imported = await client.post(f"/api/teardown/{bid}/import", json={"include": include})
    assert imported.status_code == 200
    response = await client.post(
        f"/api/teardown/{bid}/append", files={"file": ("后续.txt", "第52章 主线继续\n主线少年继续向前。".encode())}
    )
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["number_issues"] == [] and preview["junction"]["kind"] is None


async def test_append_ignored_heading_and_contiguous_typo_indexes_are_book_relative(client):
    initial = await upload(client, "第一章 起点\n主线少年走进山林。")
    bid = initial["book_id"]
    assert (await client.post(f"/api/teardown/{bid}/import", json={})).status_code == 200
    response = await client.post(
        f"/api/teardown/{bid}/append",
        files={
            "file": (
                "后续.txt",
                "第12章 后续\n正文里的一行。\n第999章\n还在同一章。\n第13章 又来\n正文向前。\n第四章 归位\n正文归位。".encode(),
            )
        },
    )
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["ignored_headings"][0]["index"] == 2
    assert preview["number_issues"][0]["count"] == 2
    assert preview["number_issues"][0]["index"] == 2 and preview["number_issues"][0]["end_index"] == 3
