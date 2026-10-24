"""群聊一句话内的联网搜索：密钥快照、次数限制、网页缓存和交回的原文。"""

import asyncio
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

import httpx
from pydantic import field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import Lenient
from app.config import get_settings
from app.crypto import SecretError, decrypt
from app.llm.router import LOCAL_HOSTS
from app.models import LlmProfile

log = logging.getLogger(__name__)

SEARCH_LIMIT = "这句话已经搜了 5 次，不能再搜了。用搜到的回答，还缺什么跟作者说清。"
PAGE_LIMIT = "这句话已经读了 3 个网页，不能再读了。用读到的回答。"
NO_RESPONSE = "网上搜索这会儿没响应。先用手头的资料回答，跟作者说一声没搜成。"
SOURCE_NOTE = "这些是网上的说法，不一定准：跟作者说的时候讲明是网上搜到的、出自哪个网站；几处说法对不上的，照实说。"
ESCAPED_MARKDOWN = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|,~<>:])")


@dataclass(frozen=True)
class SearchKey:
    profile_id: uuid.UUID
    name: str
    api_key: str


def hostname(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def select_key(rows: Iterable[LlmProfile]) -> SearchKey | None:
    """先按配置创建顺序挑一套，再解密；损坏的首选密钥不悄悄换成另一套。"""
    candidates = [
        row
        for row in rows
        if row.provider == "openai_compatible"
        and hostname(row.base_url) == "api.deepseek.com"
        and row.api_key_encrypted
    ]
    if not candidates:
        return None
    row = min(candidates, key=lambda p: (p.created_at, p.id))
    try:
        key = decrypt(row.api_key_encrypted)
    except SecretError:
        log.warning("联网搜索的 API Key 无法解密：模型配置 %s (%s)", row.name, row.id)
        return None
    return SearchKey(row.id, row.name, key) if key else None


async def load_key(session: AsyncSession) -> SearchKey | None:
    rows = await session.scalars(select(LlmProfile).where(LlmProfile.provider == "openai_compatible"))
    return select_key(rows)


class SearchWeb(Lenient):
    query: str
    question: str = ""

    @field_validator("query", "question", mode="before")
    @classmethod
    def clean_text(cls, value):
        return (value if isinstance(value, str) else str(value or "")).strip()[:128]


class ReadWebpage(Lenient):
    url: str
    start: int = 0

    @field_validator("url", mode="before")
    @classmethod
    def clean_url(cls, value):
        return (value if isinstance(value, str) else str(value or "")).strip()

    @field_validator("start", mode="before")
    @classmethod
    def clean_start(cls, value):
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0


def tool_specs(today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "上网搜。拆过的书先用 look_up_teardown 查，那里有章号，比网上准。没拆过的书（情节、人物、设定、原话）、书以外的事（现实里的历史地理和各行各业的知识、最近流行什么题材、书名人名有没有被用过），你拿不准就搜；凭常识就能说清的，或者跟作者问的事关系不大的，不用搜。一次搜一件事。交回前 5 条：网站、标题、日期、链接和一段摘要。"
                f"今天是 {today.year} 年 {today.month} 月 {today.day} 日。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜什么：几个关键词，用空格隔开，比如「斗破苍穹 萧炎 异火」，越短越准。只想看某个网站，加上 site:网址，比如「萧炎 site:baike.baidu.com」。",
                        },
                        "question": {
                            "type": "string",
                            "description": "想弄清的是什么，一句话，比如「斗破苍穹里萧炎收了哪几种异火」。",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_webpage",
                "description": "打开一个网页读正文：搜到的摘要不够用时，或者作者给了链接让你看。一次给 6000 字，长的可以往后翻。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "网页链接，照搜到的或者作者给的原样写。"},
                        "start": {
                            "type": "integer",
                            "description": "从第几个字开始读，往后翻时用；第一次读不用写。",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
    ]


def doing_of(args: SearchWeb | ReadWebpage) -> str:
    if isinstance(args, SearchWeb):
        return f"在上网搜「{args.query[:30]}」"
    return f"在读网页 {hostname(args.url)}"


def clean_markdown(text: str) -> str:
    return re.sub(r"(?:\r?\n){3,}", "\n\n", ESCAPED_MARKDOWN.sub(r"\1", text)).strip()


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def search_text(query: str, rows: list[dict]) -> str:
    picked: list[str] = []
    urls, titles = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        summary = _text(row.get("summary")) or _text(row.get("snippet"))
        if not summary:
            continue
        url = _text(row.get("url"))
        site = _text(row.get("site_name"))
        if not site or len(site) > 20:
            site = hostname(url)
        title = _text(row.get("title")) or "（没有标题）"
        if url in urls or (site, title) in titles:
            continue
        urls.add(url)
        titles.add((site, title))
        summary = re.sub(r"\s+", " ", clean_markdown(summary))
        if len(summary) > 800:
            summary = summary[:800] + "……"
        dated = _text(row.get("date"))[:10]
        heading = f"{len(picked) + 1}. {site}《{title}》" + (f"（{dated}）" if dated else "")
        picked.append(f"{heading}\n{url}\n{summary}")
        if len(picked) == 5:
            break
    if not picked:
        return f"网上没搜到「{query}」。换几个短一点的词再搜。"
    return f"网上搜「{query}」，前 {len(picked)} 条：\n\n" + "\n\n".join([*picked, SOURCE_NOTE])


def cannot_read(url: str) -> str:
    return f"这个网页打不开（网站拦着，或者没有能读的正文）：{url}。换一条搜到的链接试试。"


@dataclass(frozen=True)
class _Page:
    title: str = ""
    content: str = ""
    error: str = ""

    def result(self, args: ReadWebpage) -> tuple[str, str]:
        if self.error:
            return f"网页 {hostname(args.url)}", self.error
        label = f"网页《{self.title}》" if self.title else "网页（没有标题）"
        start = min(args.start, len(self.content))
        piece = self.content[start : start + 6000]
        end = start + len(piece)
        text = f"{label}（全文 {len(self.content)} 字，这是第 {start + 1}～{end} 字）\n{args.url}\n{piece}"
        if end < len(self.content):
            text += f"\n……后面还有；要接着读，start 填 {end}"
        return label, text


class WebSearchTurn:
    """只活在一句话里；不把结果存到下一句话，也不跨事件循环复用连接。"""

    def __init__(
        self,
        key: SearchKey,
        *,
        today: date | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.key = key
        self.today = today or date.today()
        self.base_url = (base_url if base_url is not None else get_settings().web_search_base_url).rstrip("/")
        self.searches = 0
        self._pages: dict[str, _Page] = {}
        self._client = client
        self._owns_client = client is None

    def specs(self) -> list[dict]:
        return tool_specs(self.today)

    def blocked(self, args: SearchWeb | ReadWebpage) -> str | None:
        """调用方在改回答框、记「查了」之前检查；无效参数和超额都不发请求。"""
        if isinstance(args, SearchWeb):
            if not args.query:
                return "没说要搜什么。"
            return SEARCH_LIMIT if self.searches >= 5 else None
        if not re.match(r"^https?://", args.url, re.IGNORECASE) or not hostname(args.url):
            return f"链接不对：「{args.url}」。照搜到的链接原样写。"
        return PAGE_LIMIT if args.url not in self._pages and len(self._pages) >= 3 else None

    async def execute(self, args: SearchWeb | ReadWebpage) -> tuple[str, str]:
        """通过 blocked 检查后执行；失败照样占次数并返回可记进「查了」的结果。"""
        if blocked := self.blocked(args):
            return "", blocked
        if isinstance(args, SearchWeb):
            self.searches += 1
            body = {"query": args.query, "count": 10}
            if args.question:
                body["ori_question"] = args.question
            result = await self._post("search", body)
            if isinstance(result, str):
                text = result
            else:
                rows = result.get("results")
                rows = [] if rows is None else rows
                text = search_text(args.query, rows) if isinstance(rows, list) else NO_RESPONSE
            return f"网上搜「{args.query[:30]}」", text
        if args.url not in self._pages:
            result = await self._post("fetch", {"url": args.url})
            if isinstance(result, str):
                page = _Page(error=result)
            else:
                content = clean_markdown(_text(result.get("content")))
                page = (
                    _Page(title=_text(result.get("title")), content=content)
                    if content
                    else _Page(error=cannot_read(args.url))
                )
            self._pages[args.url] = page
        return self._pages[args.url].result(args)

    async def _post(self, action: str, body: dict) -> dict | str:
        if self._client is None:
            self._client = httpx.AsyncClient(trust_env=hostname(self.base_url) not in LOCAL_HOSTS, timeout=30)
        for attempt in range(2):
            try:
                response = await self._client.post(
                    f"{self.base_url}/v1/tools/{action}",
                    headers={"Authorization": f"Bearer {self.key.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
            except httpx.RequestError:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return NO_RESPONSE
            status = response.status_code
            if status in (408, 429) or status >= 500:
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                return NO_RESPONSE
            if status == 401 or (action == "search" and status == 403):
                return f"联网搜索用不了：DeepSeek 不认这把密钥。请作者在系统设置里检查「{self.key.name}」的 API Key。"
            if status == 402:
                return "联网搜索用不了：DeepSeek 账户余额不足，请作者去 DeepSeek 开放平台充值。"
            if action == "fetch" and status in (403, 404):
                return cannot_read(body["url"])
            if not response.is_success:
                return f"网上搜索没成：DeepSeek 回了 {status}。"
            try:
                result = response.json()
            except ValueError:
                return NO_RESPONSE
            return result if isinstance(result, dict) else NO_RESPONSE
        return NO_RESPONSE

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
