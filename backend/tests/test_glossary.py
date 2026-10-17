"""术语表解析、默认与覆盖加载、提示词页校验及开书方式默认值。"""

import httpx
import pytest

from app.agents import glossary
from app.book_settings import BookSettings, compile_rules, default_settings, merge_settings
from app.main import app
from app.prompts import default_content, load
from app.prompts.catalog import validate_content


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def test_parse_ignores_preface_and_preserves_explanations():
    text = "# 术语表\n不用的前言\n\n## 欲扬先抑\n先压后扬。\n第二行。\n\n## 打脸三拍\n质疑、展示、反应。"
    assert glossary.parse(text) == [("欲扬先抑", "先压后扬。\n第二行。"), ("打脸三拍", "质疑、展示、反应。")]
    assert glossary.parse("没有二级标题") == []


def test_clean_techniques_uses_current_table_and_limits_three(monkeypatch):
    monkeypatch.setattr(glossary, "terms", lambda: [(f"术语{i}", f"解释{i}") for i in range(1, 6)])
    assert glossary.clean_techniques(["表外", "术语2", "术语1", "术语2", "术语3", "术语4"]) == [
        "术语2",
        "术语1",
        "术语3",
    ]
    assert glossary.clean_techniques(None) == []
    assert glossary.glossary_block() == "【术语表】可用的技巧名称：术语1、术语2、术语3、术语4、术语5"


@pytest.mark.parametrize(
    "content",
    [
        "\n".join(f"## 术语{i}\n解释" for i in range(3)),
        "\n".join(f"## 术语{i}\n解释" for i in range(5)) + "\n## 空解释\n",
        "\n".join("## 重复术语\n解释" for _ in range(5)),
    ],
)
def test_glossary_requires_five_distinct_explained_terms(content):
    with pytest.raises(ValueError):
        validate_content("glossary", content)


async def test_glossary_api_and_prompt_override_are_live(client):
    original = default_content("glossary")
    default_terms = glossary.parse(original)
    response = await client.get("/api/glossary")
    assert response.status_code == 200
    assert response.json()["terms"] == [
        {"term": name, "explanation": explanation} for name, explanation in default_terms
    ]
    assert len(default_terms) >= 5
    catalog = (await client.get("/api/prompts")).json()
    entry = next(row for row in catalog if row["name"] == "glossary")
    assert (entry["title"], entry["group"], entry["role"], entry["variables"]) == ("术语表", "角色与规矩", "all", [])
    assert (await client.get("/api/prompts/glossary")).json()["content"] == original
    custom = "# 自定义术语\n" + "\n\n".join(f"## 自定义{i}\n解释{i}" for i in range(5))
    response = await client.put("/api/prompts/glossary", json={"content": custom})
    assert response.status_code == 200 and response.json()["customized"]
    assert load("glossary") == custom
    assert glossary.terms()[0] == ("自定义0", "解释0")
    assert glossary.clean_techniques([default_terms[0][0], "自定义0"]) == ["自定义0"]
    assert (await client.get("/api/glossary")).json()["terms"][0] == {"term": "自定义0", "explanation": "解释0"}
    too_short = "\n\n".join(f"## 自定义{i}\n解释{i}" for i in range(3))
    response = await client.put("/api/prompts/glossary", json={"content": too_short})
    assert response.status_code == 422 and "至少需要 5 个术语" in response.json()["detail"]
    assert load("glossary") == custom
    assert (await client.delete("/api/prompts/glossary")).status_code == 200
    assert load("glossary") == original


async def test_setup_mode_defaults_and_rules(client):
    assert BookSettings().setup_mode == "puzzle"
    assert default_settings()["setup_mode"] == "puzzle"
    assert merge_settings({}, {"setup_mode": "puzzle"})["setup_mode"] == "puzzle"
    assert compile_rules({"setup_mode": "puzzle"}) == ""
    defaults = (await client.get("/api/settings/new-book-defaults")).json()
    assert defaults["settings"]["setup_mode"] == "puzzle"
    response = await client.put("/api/settings/new-book-defaults", json={"setup_mode": "puzzle"})
    assert response.status_code == 200 and response.json()["settings"]["setup_mode"] == "puzzle"
    assert (await client.get("/api/settings/new-book-defaults")).json()["settings"]["setup_mode"] == "puzzle"
    assert (await client.put("/api/settings/new-book-defaults", json={"setup_mode": "wrong"})).status_code == 422


async def test_new_default_does_not_reinterpret_legacy_books(client, sessionmaker):
    from app.book_settings import settings_of
    from app.models import Book

    legacy = Book(title="旧书", settings={"title_style": "chief"})
    explicit = Book(title="旧拼图书", settings={"setup_mode": "puzzle"})
    assert settings_of(legacy)["setup_mode"] == "oneshot"
    assert settings_of(explicit)["setup_mode"] == "puzzle"
    async with sessionmaker() as session:
        session.add(legacy)
        await session.commit()
        book_id = legacy.id
    await client.put("/api/settings/new-book-defaults", json={"setup_mode": "oneshot"})
    assert (await client.get("/api/settings/new-book-defaults")).json()["settings"]["setup_mode"] == "oneshot"
    response = await client.get(f"/api/books/{book_id}/settings")
    assert response.json()["settings"]["setup_mode"] == "oneshot"
    assert response.json()["settings"]["title_style"] == "chief"
