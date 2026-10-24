"""联网搜索只用内存传输和独立测试数据库，绝不连接真实 DeepSeek。"""

import json
import logging
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.crypto import encrypt
from app.llm import web_search as web
from app.models import AppSetting, LlmProfile


@pytest.fixture
async def fake_search(monkeypatch):
    clients = []
    monkeypatch.setattr(web.asyncio, "sleep", AsyncMock())

    def create(responses):
        requests = []
        pending = iter(responses)

        def handle(request):
            requests.append(request)
            response = next(pending)
            if isinstance(response, Exception):
                raise response
            status, body = response
            return httpx.Response(status, json=body)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        clients.append(client)
        turn = web.WebSearchTurn(
            web.SearchKey("fake-key"),
            base_url="http://127.0.0.1:9999/",
            today=date(2026, 10, 24),
            client=client,
        )
        return turn, requests

    yield create
    for client in clients:
        await client.aclose()


def test_key_comes_only_from_the_web_search_setting(caplog, monkeypatch):
    monkeypatch.setattr(web.log, "disabled", False)
    caplog.set_level(logging.WARNING, logger=web.__name__)
    assert web.key_of({"api_key_encrypted": encrypt("fake-key")}) == web.SearchKey("fake-key")
    for value in (None, {}, {"api_key_encrypted": ""}, {"api_key_encrypted": None}, {"api_key_encrypted": encrypt("")}):
        assert web.key_of(value) is None
    assert web.key_of({"api_key_encrypted": "not-an-encrypted-secret"}) is None
    assert "无法解密" in caplog.text
    assert "not-an-encrypted-secret" not in caplog.text


async def test_load_key_is_a_snapshot_and_never_borrows_a_model_profile(sessionmaker):
    async with sessionmaker() as session:
        session.add(
            LlmProfile(
                name="官方DeepSeek",
                provider="openai_compatible",
                base_url="https://api.deepseek.com/v1",
                api_key_encrypted=encrypt("profile-key"),
                model="deepseek-flash",
            )
        )
        await session.commit()
        assert await web.load_key(session) is None
        row = AppSetting(key=web.SETTING, value={"api_key_encrypted": encrypt("fake-key")})
        session.add(row)
        await session.commit()
        selected = await web.load_key(session)
        assert selected == web.SearchKey("fake-key")
    async with sessionmaker() as other:
        (await other.get(AppSetting, web.SETTING)).value = {"api_key_encrypted": encrypt("changed-key")}
        await other.commit()
    async with sessionmaker() as session:
        assert selected.api_key == "fake-key"
        assert (await web.load_key(session)).api_key == "changed-key"


def test_config_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("ZHIBI_WEB_SEARCH_BASE_URL", raising=False)
    assert Settings(_env_file=None).web_search_base_url == "https://api.deepseek.com"
    monkeypatch.setenv("ZHIBI_WEB_SEARCH_BASE_URL", "http://127.0.0.1:9911")
    assert Settings(_env_file=None).web_search_base_url == "http://127.0.0.1:9911"


def test_tool_definitions_are_exactly_task_json_and_date_is_frozen(monkeypatch):
    task = Path(__file__).resolve().parents[2] / "docs/codex任务/主编联网搜索/1-主编上网搜.md"
    section = task.read_text(encoding="utf-8").split("### 2.2 定义", 1)[1].split("### 2.3", 1)[0]
    expected = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
    assert web.tool_specs(date(2026, 10, 24)) == expected
    expected[0]["function"]["description"] = expected[0]["function"]["description"].replace(
        "今天是 2026 年 10 月 24 日。", "今天是 2027 年 1 月 2 日。"
    )
    assert web.tool_specs(date(2027, 1, 2)) == expected

    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 24)

    monkeypatch.setattr(web, "date", Clock)
    turn = web.WebSearchTurn(web.SearchKey("fake"))
    monkeypatch.setattr(Clock, "today", classmethod(lambda cls: cls(2027, 1, 2)))
    assert turn.specs()[0]["function"]["description"].endswith("今天是 2026 年 10 月 24 日。")
    assert web.tool_specs()[0]["function"]["description"].endswith("今天是 2027 年 1 月 2 日。")


@pytest.mark.parametrize("start,expected", [("6000", 6000), (-1, 0), ("n/a", 0), (None, 0), ({}, 0)])
def test_lenient_args(start, expected):
    assert web.ReadWebpage.model_validate({"url": " https://example.com/x ", "start": start}) == web.ReadWebpage(
        url="https://example.com/x", start=expected
    )
    assert web.SearchWeb.model_validate({"query": "  异火  "}).question == ""
    assert web.SearchWeb.model_validate({"query": "  异火  ", "question": None}).question == ""


async def test_search_request_and_exact_empty_result(fake_search):
    turn, requests = fake_search([(200, {"results": []}), (200, {"results": []})])
    args = web.SearchWeb(query="  " + "词" * 140 + "  ", question="  " + "问" * 140 + "  ")
    label, text = await turn.execute(args)
    request = requests[0]
    assert str(request.url) == "http://127.0.0.1:9999/v1/tools/search"
    assert request.headers["Authorization"] == "Bearer fake-key"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"query": "词" * 128, "count": 10, "ori_question": "问" * 128}
    assert label == "网上搜「" + "词" * 30 + "」"
    assert web.doing_of(args) == "在上网搜「" + "词" * 30 + "」"
    assert text == "网上没搜到「" + "词" * 128 + "」。换几个短一点的词再搜。"
    await turn.execute(web.SearchWeb(query=" 异火 ", question="  "))
    assert json.loads(requests[1].content) == {"query": "异火", "count": 10}


@pytest.mark.parametrize("body", [{}, {"results": None}, {"results": []}])
async def test_missing_or_null_search_results_are_empty(fake_search, body):
    turn, requests = fake_search([(200, body)])
    assert await turn.execute(web.SearchWeb(query="异火")) == (
        "网上搜「异火」",
        "网上没搜到「异火」。换几个短一点的词再搜。",
    )
    assert turn.searches == len(requests) == 1


@pytest.mark.parametrize("results", [1, 0, True, False, "", "unexpected", {}, {"title": "not a list"}])
async def test_non_list_search_results_use_existing_error_without_breaking_turn(fake_search, results):
    turn, requests = fake_search([(200, {"results": results})])
    assert await turn.execute(web.SearchWeb(query="异火")) == ("网上搜「异火」", web.NO_RESPONSE)
    assert turn.searches == len(requests) == 1
    web.asyncio.sleep.assert_not_awaited()


async def test_search_selection_cleanup_dedup_fallback_and_exact_format(fake_search):
    rows = [
        {"url": "https://empty.example", "summary": "  ", "snippet": "\n"},
        {
            "url": "https://baike.baidu.com/item/fire",
            "site_name": "百度百科",
            "title": "异火榜",
            "date": "2026-07-27T00:00:00Z",
            "summary": r"\# 异火榜  \[1\-2\]  " + "\n\t" + r"火\, 火",
            "snippet": "不应该用这段",
        },
        {"url": "https://baike.baidu.com/item/fire", "title": "重复链接", "summary": "重复"},
        {"url": "https://baike.baidu.com/item/other", "site_name": "百度百科", "title": "异火榜", "summary": "重复"},
        {"url": "https://fallback.example/a", "site_name": "", "title": "", "snippet": "只给了摘要"},
        {"url": "https://long.example/a", "site_name": "长" * 21, "title": "长摘要", "summary": "字" * 801},
        {"url": "https://four.example", "site_name": "四", "title": "第四条", "summary": "四"},
        {"url": "https://five.example", "site_name": "五", "title": "第五条", "summary": "五"},
        {"url": "https://six.example", "site_name": "六", "title": "第六条", "summary": "不该出现"},
    ]
    turn, _ = fake_search([(200, {"results": rows})])
    label, text = await turn.execute(web.SearchWeb(query="斗破苍穹 萧炎 异火"))
    assert label == "网上搜「斗破苍穹 萧炎 异火」"
    assert text == (
        "网上搜「斗破苍穹 萧炎 异火」，前 5 条：\n\n"
        "1. 百度百科《异火榜》（2026-07-27）\nhttps://baike.baidu.com/item/fire\n# 异火榜 [1-2] 火, 火\n\n"
        "2. fallback.example《（没有标题）》\nhttps://fallback.example/a\n只给了摘要\n\n"
        "3. long.example《长摘要》\nhttps://long.example/a\n" + "字" * 800 + "……\n\n"
        "4. 四《第四条》\nhttps://four.example\n四\n\n"
        "5. 五《第五条》\nhttps://five.example\n五\n\n" + web.SOURCE_NOTE
    )
    assert web.search_text("词", rows[1:2]).startswith("网上搜「词」，前 1 条：")


async def test_empty_search_and_sixth_search_are_blocked_without_requests_or_count(fake_search):
    turn, requests = fake_search([(200, {"results": []})] * 5)
    empty = web.SearchWeb(query=" \n ")
    assert turn.blocked(empty) == "没说要搜什么。"
    assert await turn.execute(empty) == ("", "没说要搜什么。")
    assert turn.searches == 0
    for _ in range(5):
        assert turn.blocked(web.SearchWeb(query="词")) is None
        await turn.execute(web.SearchWeb(query="词"))
    assert turn.searches == 5
    assert turn.blocked(web.SearchWeb(query="词")) == web.SEARCH_LIMIT
    assert await turn.execute(web.SearchWeb(query="词")) == ("", web.SEARCH_LIMIT)
    assert len(requests) == 5


@pytest.mark.parametrize("url", ["", "ftp://example.com", "https:///example", "http://", "https://[invalid"])
async def test_invalid_page_is_blocked_without_fetch_or_count(fake_search, url):
    turn, requests = fake_search([])
    args = web.ReadWebpage(url=f" {url} ")
    expected = f"链接不对：「{url}」。照搜到的链接原样写。"
    assert turn.blocked(args) == expected
    assert await turn.execute(args) == ("", expected)
    assert not requests
    assert not turn._pages


def test_markdown_cleanup_only_removes_allowed_escapes():
    allowed = "\\`*_{}[]()#+-.!|,~<>:"
    escaped = "".join("\\" + char for char in allowed)
    assert web.clean_markdown(" \n" + escaped + r"\a\中" + "\n\n\n\n段落  ") == allowed + r"\a\中" + "\n\n段落"
    assert web.clean_markdown("前文\r\n\r\n\r\n后文") == "前文\n\n后文"


async def test_fetch_exact_format_pagination_and_per_turn_cache(fake_search):
    content = "文" * 6012
    turn, requests = fake_search([(200, {"title": "异火榜", "content": content})])
    args = web.ReadWebpage(url=" https://baike.baidu.com/item/fire ", start="-4")
    assert web.doing_of(args) == "在读网页 baike.baidu.com"
    label, text = await turn.execute(args)
    assert str(requests[0].url) == "http://127.0.0.1:9999/v1/tools/fetch"
    assert json.loads(requests[0].content) == {"url": args.url}
    assert label == "网页《异火榜》"
    assert text == (
        f"网页《异火榜》（全文 6012 字，这是第 1～6000 字）\n{args.url}\n"
        + "文" * 6000
        + "\n……后面还有；要接着读，start 填 6000"
    )
    _, next_page = await turn.execute(web.ReadWebpage(url=args.url, start="6000"))
    assert next_page == f"网页《异火榜》（全文 6012 字，这是第 6001～6012 字）\n{args.url}\n" + "文" * 12
    _, end = await turn.execute(web.ReadWebpage(url=args.url, start=10000))
    assert end == f"网页《异火榜》（全文 6012 字，这是第 6013～6012 字）\n{args.url}\n"
    assert len(requests) == 1


async def test_fetch_cleaned_body_and_missing_title(fake_search):
    turn, _ = fake_search([(200, {"title": "", "content": " \n" + r"\# 正文 \[1\-2\]\, " + "\n\n\n\n结尾 "})])
    label, text = await turn.execute(web.ReadWebpage(url="https://example.com"))
    cleaned = "# 正文 [1-2], \n\n结尾"
    assert label == "网页（没有标题）"
    assert (
        text
        == f"网页（没有标题）（全文 {len(cleaned)} 字，这是第 1～{len(cleaned)} 字）\nhttps://example.com\n{cleaned}"
    )


@pytest.mark.parametrize("status,body", [(403, {}), (404, {}), (200, {"content": " \n "})])
async def test_cannot_read_exact_message_counts_and_caches_failure(fake_search, status, body):
    turn, requests = fake_search([(status, body)])
    args = web.ReadWebpage(url="https://blocked.example")
    expected = ("网页 blocked.example", web.cannot_read(args.url))
    assert await turn.execute(args) == expected
    assert await turn.execute(args) == expected
    assert len(turn._pages) == len(requests) == 1


async def test_fourth_distinct_webpage_blocked_but_pagination_still_allowed(fake_search):
    turn, requests = fake_search([(200, {"title": "页", "content": "文" * 6001})] * 3)
    for i in range(3):
        await turn.execute(web.ReadWebpage(url=f"https://example.com/{i}"))
    fourth = web.ReadWebpage(url="https://example.com/4")
    assert turn.blocked(fourth) == web.PAGE_LIMIT
    assert await turn.execute(fourth) == ("", web.PAGE_LIMIT)
    next_page = web.ReadWebpage(url="https://example.com/1", start=6000)
    assert turn.blocked(next_page) is None
    assert (await turn.execute(next_page))[1].endswith("\n文")
    assert len(requests) == 3


@pytest.mark.parametrize("action", ["search", "fetch"])
@pytest.mark.parametrize("status", [401, 402, 400, 422, 408, 429, 500, 503])
async def test_errors_exact_words_count_attempts_and_retry_once(fake_search, action, status):
    retryable = status in (408, 429, 500, 503)
    turn, requests = fake_search([(status, {})] * (2 if retryable else 1))
    args = web.SearchWeb(query="异火") if action == "search" else web.ReadWebpage(url="https://example.com")
    label, text = await turn.execute(args)
    if status == 401:
        expected = "联网搜索用不了：DeepSeek 不认这把密钥。请作者在系统设置「联网搜索」里检查 API Key。"
    elif status == 402:
        expected = "联网搜索用不了：DeepSeek 账户余额不足，请作者去 DeepSeek 开放平台充值。"
    elif retryable:
        expected = web.NO_RESPONSE
    else:
        expected = f"网上搜索没成：DeepSeek 回了 {status}。"
    assert text == expected
    assert label == ("网上搜「异火」" if action == "search" else "网页 example.com")
    assert len(requests) == (2 if retryable else 1)
    assert turn.searches == (1 if action == "search" else 0)
    assert len(turn._pages) == (1 if action == "fetch" else 0)
    assert web.asyncio.sleep.await_count == (1 if retryable else 0)
    if retryable:
        web.asyncio.sleep.assert_awaited_once_with(1)


async def test_search_403_is_key_error_not_blocked_page(fake_search):
    turn, requests = fake_search([(403, {})])
    _, text = await turn.execute(web.SearchWeb(query="异火"))
    assert text == "联网搜索用不了：DeepSeek 不认这把密钥。请作者在系统设置「联网搜索」里检查 API Key。"
    assert len(requests) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("fake timeout"), httpx.ConnectError("fake connection failure")])
@pytest.mark.parametrize("action", ["search", "fetch"])
async def test_network_errors_retry_once_and_never_raise_to_model(fake_search, error, action):
    turn, requests = fake_search([error, error])
    args = web.SearchWeb(query="异火") if action == "search" else web.ReadWebpage(url="https://example.com")
    assert (await turn.execute(args))[1] == web.NO_RESPONSE
    assert len(requests) == 2
    web.asyncio.sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize("failure", [(429, {}), (500, {}), httpx.ConnectError("fake failure")])
async def test_retry_success(fake_search, failure):
    turn, requests = fake_search([failure, (200, {"results": []})])
    assert await turn.execute(web.SearchWeb(query="异火")) == (
        "网上搜「异火」",
        "网上没搜到「异火」。换几个短一点的词再搜。",
    )
    assert len(requests) == 2
    web.asyncio.sleep.assert_awaited_once_with(1)


@pytest.mark.parametrize(
    "base_url,trust_env",
    [
        ("https://api.deepseek.com", True),
        ("http://localhost:1234", False),
        ("http://127.0.0.1:1234", False),
        ("http://[::1]:1234", False),
        ("http://host.docker.internal:1234", False),
    ],
)
async def test_client_proxy_timeout_and_lifecycle_without_any_network(monkeypatch, base_url, trust_env):
    client = AsyncMock()
    client.post.return_value = httpx.Response(200, json={"results": []})
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return client

    monkeypatch.setattr(web.httpx, "AsyncClient", factory)
    turn = web.WebSearchTurn(web.SearchKey("fake"), base_url=base_url)
    assert not seen
    await turn.execute(web.SearchWeb(query="词"))
    await turn.execute(web.SearchWeb(query="词"))
    assert seen == [{"trust_env": trust_env, "timeout": 30}]
    await turn.aclose()
    await turn.aclose()
    client.aclose.assert_awaited_once()


def mock_client(response):
    requests = []

    def handle(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), requests


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            (
                200,
                {"results": [{"title": "网络小说", "url": "https://baike.baidu.com/item/x", "site_name": "百度百科"}]},
            ),
            (True, "能搜：试搜「网络小说」，第一条是百度百科《网络小说》。"),
        ),
        (
            (200, {"results": [{"title": "", "url": "https://example.com/a", "site_name": "名" * 21}]}),
            (True, "能搜：试搜「网络小说」，第一条是example.com《（没有标题）》。"),
        ),
        ((200, {"results": []}), (True, "能搜：试搜「网络小说」，这次没搜到结果。")),
        ((401, {}), (False, "DeepSeek 不认这把密钥，看看有没有填错、是不是已经删了。")),
        ((403, {}), (False, "DeepSeek 不认这把密钥，看看有没有填错、是不是已经删了。")),
        ((402, {}), (False, "DeepSeek 账户余额不足，去 DeepSeek 开放平台充值后再试。")),
        ((429, {}), (False, "DeepSeek 这会儿忙（429），过一会儿再试。")),
        ((503, {}), (False, "DeepSeek 这会儿忙（503），过一会儿再试。")),
        ((422, {}), (False, "没搜成：DeepSeek 回了 422。")),
        (httpx.ConnectError("fake failure"), (False, "连不上 DeepSeek，看看网络，过一会儿再试。")),
    ],
)
async def test_try_key_searches_once_and_explains_to_the_author(response, expected):
    client, requests = mock_client(response)
    async with client:
        assert await web.try_key("typed-key", base_url="http://127.0.0.1:9999/", client=client) == expected
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "http://127.0.0.1:9999/v1/tools/search"
    assert request.headers["Authorization"] == "Bearer typed-key"
    assert json.loads(request.content) == {"query": "网络小说", "count": 1}
