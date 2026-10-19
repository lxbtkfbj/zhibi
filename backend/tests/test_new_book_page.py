"""新建页：作者先填书名、简介、类别、标签、篇幅，建好书编辑部不开工；编辑部只在作者叫了才起草或改。"""

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.book_meta import CHANNELS, DEFAULT_CHAPTER_WORDS
from app.config import get_settings
from app.llm import demo
from app.main import create_app
from app.models import Book, Job, LlmCall, MeetingMessage
from app.prompts import render
from app.services import jobs


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
def queued(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(jobs, "enqueue", lambda job_id, resume=None: calls.append(job_id))
    return calls


@pytest.fixture
async def client():
    application = create_app()
    application.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await application.state.redis.aclose()


async def count(sessionmaker, model) -> int:
    async with sessionmaker() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_blank_book_saves_what_author_filled_and_starts_nothing(client, queued, sessionmaker):
    res = await client.post(
        "/api/books",
        json={
            "start_setup": False,
            "title": "  寿命簿 ",
            "blurb": "一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营。",
            "genre": "玄幻",
            "tags": ["苟道", " 宗门", "苟道", ""],
            "target_length": 240,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["job"] is None
    book = body["book"]
    assert book["title"] == "寿命簿"
    assert book["genre"] == "玄幻"
    assert book["idea"].startswith("一个能看见")
    assert book["concept"] == {
        "title": "寿命簿",
        "story": "一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营。",
        "channel": "男频",
        "genre": "玄幻",
        "tags": ["苟道", "宗门"],
        "target_length": 240,
        "chapter_words": DEFAULT_CHAPTER_WORDS,
    }
    assert book["active_job"] is None
    assert queued == []
    assert await count(sessionmaker, Job) == 0
    assert await count(sessionmaker, MeetingMessage) == 0


async def test_blank_book_can_be_completely_empty(client, queued):
    res = await client.post("/api/books", json={"start_setup": False})
    assert res.status_code == 201, res.text
    book = res.json()["book"]
    assert book["title"] == "未命名"
    assert book["concept"] == {"chapter_words": DEFAULT_CHAPTER_WORDS}
    assert queued == []


async def test_blank_book_uses_chapter_words_from_settings(client, queued):
    assert (await client.put("/api/settings/new-book-defaults", json={"chapter_words": 3200})).status_code == 200
    assert (await client.get("/api/book-meta")).json()["chapter_words"] == 3200
    res = await client.post("/api/books", json={"start_setup": False, "target_length": 100})
    assert res.json()["book"]["concept"]["chapter_words"] == 3200


async def test_blank_book_moves_default_rules_into_writing_requirements(client, queued):
    # 2026-10-19：「其他规矩」并进写作要求，新书默认里带着的，建书时挪成这本书一直有效的写作要求
    defaults = await client.put("/api/settings/new-book-defaults", json={"other_rules": "别写套话\n\n 主角说话要贫 "})
    assert defaults.status_code == 200
    book = (await client.post("/api/books", json={"start_setup": False})).json()["book"]
    rows = (await client.get(f"/api/books/{book['id']}/requirements")).json()
    assert [(row["text"], row["label"]) for row in rows] == [("别写套话", "一直有效"), ("主角说话要贫", "一直有效")]
    settings = (await client.get(f"/api/books/{book['id']}/settings")).json()
    assert settings["settings"]["other_rules"] == "" and "别写套话" not in settings["rules_text"]


async def test_book_detail_tells_actual_chapter_words(client, queued):
    # 本书设置没填每章字数：按新建时记进定调的写；填了以后按设置写，书的详情跟着变（简介页「约 N 章」用它算）
    book = (await client.post("/api/books", json={"start_setup": False})).json()["book"]
    assert book["chapter_words"] == DEFAULT_CHAPTER_WORDS
    assert (await client.patch(f"/api/books/{book['id']}/settings", json={"chapter_words": 3000})).status_code == 200
    assert (await client.get(f"/api/books/{book['id']}")).json()["chapter_words"] == 3000


@pytest.mark.parametrize(
    "extra",
    [
        {"target_length": 0},
        {"target_length": 6000},
        {"tags": ["一" * 21]},
        {"tags": ["标签"] * 21},
        {"channel": "全频"},
    ],
)
async def test_blank_book_rejects_bad_fields(client, queued, extra):
    res = await client.post("/api/books", json={"start_setup": False, **extra})
    assert res.status_code == 422


async def test_old_entry_still_needs_an_idea_and_starts_the_setup(client, queued):
    res = await client.post("/api/books", json={"idea": "末世"})
    assert res.status_code == 422
    res = await client.post("/api/books", json={"idea": "末世里开奶茶店"})
    assert res.status_code == 201, res.text
    assert res.json()["job"] is not None
    assert len(queued) == 1


async def test_book_meta_lists_channels_categories_and_tags(client):
    meta = (await client.get("/api/book-meta")).json()
    assert [c["key"] for c in meta["channels"]] == ["男频", "女频"]
    assert "玄幻" in meta["channels"][0]["categories"]
    assert all(group["tags"] for c in meta["channels"] for group in c["tag_groups"])
    assert meta["chapter_words"] == DEFAULT_CHAPTER_WORDS


async def test_draft_fills_the_page_without_making_a_book(client, queued, sessionmaker):
    res = await client.post("/api/book-drafts", json={"idea": "一个能看见别人剩余寿命的杂役弟子"})
    assert res.status_code == 200, res.text
    draft = res.json()
    assert draft["title"] == "寿命簿"
    assert draft["blurb"].startswith("一个能看见别人剩余寿命的杂役弟子")
    assert draft["channel"] == "男频" and draft["genre"] == "玄幻"
    assert draft["tags"] and draft["target_length"] == 200
    assert draft["reply"]
    assert await count(sessionmaker, Book) == 0
    assert queued == []
    async with sessionmaker() as session:
        call = (await session.execute(select(LlmCall))).scalar_one()
    assert call.book_id is None and call.purpose == "新建页·起草"


async def test_revise_keeps_what_author_did_not_mention(client, queued):
    current = {
        "title": "我自己起的名",
        "blurb": "原来的简介",
        "channel": "男频",
        "genre": "仙侠",
        "tags": ["凡人"],
        "target_length": None,
    }
    res = await client.post("/api/book-drafts", json={"idea": "点子", "current": current, "feedback": "简介再抓人一点"})
    assert res.status_code == 200, res.text
    draft = res.json()
    assert draft["title"] == "我自己起的名"
    assert draft["genre"] == "仙侠" and draft["tags"] == ["凡人"]
    assert draft["blurb"] != "原来的简介"
    # 篇幅作者没填也没提，就别替作者填上
    assert draft["target_length"] is None


async def test_blank_page_can_ask_without_an_idea(client, queued):
    current = {"title": "", "blurb": "", "channel": "女频", "genre": "古代言情", "tags": [], "target_length": None}
    res = await client.post("/api/book-drafts", json={"idea": "", "current": current, "feedback": "帮我把简介写完整"})
    assert res.status_code == 200, res.text
    assert res.json()["genre"] == "古代言情"


@pytest.mark.parametrize(
    "body",
    [{"idea": ""}, {"idea": "x"}, {"idea": "点子", "feedback": "改改"}],
)
async def test_draft_needs_an_idea_or_current_page(client, body):
    assert (await client.post("/api/book-drafts", json=body)).status_code == 422


def test_draft_prompt_lists_catalog_and_revision_rule():
    text = render(
        "book_draft",
        idea="点子",
        catalog="男频类别：玄幻",
        requirements="",
        revision="【作者的意见】\n改简介",
        mode_rule="8. 只改作者说到的地方",
    )
    assert "【可选的类别和常见标签】\n男频类别：玄幻" in text
    assert "改简介" in text and "只改作者说到的地方" in text
    assert len(CHANNELS) == 2
