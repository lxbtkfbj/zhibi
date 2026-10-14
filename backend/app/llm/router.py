"""模型调用层：按编辑部角色选择模型配置，统一处理结构化输出、重试与用量记录。"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import openai
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crypto import decrypt
from app.llm import demo
from app.models import LlmCall, LlmProfile, RoleAssignment

log = logging.getLogger(__name__)

MAX_PARSE_ATTEMPTS = 3


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedProfile:
    name: str
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.8
    max_tokens: int | None = None
    structured_method: str = "function_calling"
    timeout_s: int = 300

    @classmethod
    def from_row(cls, row: LlmProfile) -> "ResolvedProfile":
        return cls(
            name=row.name,
            provider=row.provider,
            base_url=row.base_url,
            api_key=decrypt(row.api_key_encrypted) if row.api_key_encrypted else "",
            model=row.model,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            structured_method=row.structured_method,
            timeout_s=row.timeout_s,
        )


DEMO_PROFILE = ResolvedProfile(name="演示模式", provider="demo", model="demo")


def build_chat_model(p: ResolvedProfile, *, streaming: bool = False) -> ChatOpenAI:
    return ChatOpenAI(
        model=p.model,
        base_url=p.base_url or None,
        api_key=p.api_key or "EMPTY",
        temperature=p.temperature,
        max_tokens=p.max_tokens,
        timeout=p.timeout_s,
        max_retries=2,
        streaming=streaming,
        stream_usage=True,
    )


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\n请只输出一个 JSON 对象，不要输出任何其他文字或代码块标记。"
        f"JSON 必须符合以下 JSON Schema：\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


def parse_json_output[T: BaseModel](schema: type[T], text: str) -> T:
    """宽松解析：去掉代码块标记，截取第一个 { 到最后一个 }。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("输出中没有 JSON 对象")
    return schema.model_validate_json(cleaned[start : end + 1])


class LLMRouter:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        job_id: uuid.UUID | None = None,
        book_id: uuid.UUID | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.job_id = job_id
        self.book_id = book_id

    async def resolve(self, role: str) -> ResolvedProfile:
        async with self.sessionmaker() as session:
            for candidate in (role, "default"):
                assignment = await session.get(RoleAssignment, candidate)
                if assignment and assignment.profile_id:
                    profile = await session.get(LlmProfile, assignment.profile_id)
                    if profile:
                        return ResolvedProfile.from_row(profile)
            first = (await session.execute(select(LlmProfile).order_by(LlmProfile.created_at).limit(1))).scalar()
            return ResolvedProfile.from_row(first) if first else DEMO_PROFILE

    async def structured[T: BaseModel](self, role: str, schema: type[T], system: str, user: str, *, purpose: str) -> T:
        profile = await self.resolve(role)
        if profile.provider == "demo":
            started = time.monotonic()
            result = await demo.respond(schema, system, user)
            await self._record(role, profile, purpose, started, 0, 0, ok=True)
            return result
        return await self._structured_remote(role, profile, schema, system, user, purpose)

    async def _structured_remote[T: BaseModel](
        self, role: str, profile: ResolvedProfile, schema: type[T], system: str, user: str, purpose: str
    ) -> T:
        method = profile.structured_method
        last_error = ""
        for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
            prompt_user = (
                user
                if not last_error
                else f"{user}\n\n【上次输出无法解析】{last_error}\n请严格按要求的结构重新输出完整结果。"
            )
            started = time.monotonic()
            try:
                parsed, usage = await self._invoke_structured(profile, method, schema, system, prompt_user)
            except openai.BadRequestError as exc:
                # 部分接口不支持工具调用或 JSON Schema，自动降级为 JSON 模式
                if method != "json_mode" and attempt < MAX_PARSE_ATTEMPTS:
                    log.warning("结构化输出方式 %s 不受支持，改用 json_mode：%s", method, exc)
                    await self._record(role, profile, purpose, started, 0, 0, ok=False, error=str(exc))
                    method = "json_mode"
                    continue
                await self._record(role, profile, purpose, started, 0, 0, ok=False, error=str(exc))
                raise LLMError(f"模型接口拒绝了请求：{exc}") from exc
            except (openai.APIError, TimeoutError) as exc:
                await self._record(role, profile, purpose, started, 0, 0, ok=False, error=str(exc))
                raise LLMError(f"调用模型失败（{profile.name}）：{exc}") from exc
            prompt_tokens, completion_tokens = usage
            if isinstance(parsed, schema):
                await self._record(role, profile, purpose, started, prompt_tokens, completion_tokens, ok=True)
                return parsed
            last_error = str(parsed)[:500]
            await self._record(
                role, profile, purpose, started, prompt_tokens, completion_tokens, ok=False, error=last_error
            )
        raise LLMError(f"模型连续 {MAX_PARSE_ATTEMPTS} 次没有按要求的格式输出：{last_error}")

    async def _invoke_structured[T: BaseModel](
        self, profile: ResolvedProfile, method: str, schema: type[T], system: str, user: str
    ) -> tuple[T | str, tuple[int, int]]:
        """返回 (解析结果或错误说明, (输入 token, 输出 token))。"""
        llm = build_chat_model(profile)
        if method == "json_mode":
            raw = await llm.bind(response_format={"type": "json_object"}).ainvoke(
                [SystemMessage(system + schema_instruction(schema)), HumanMessage(user)]
            )
            usage = _usage(raw)
            try:
                return parse_json_output(schema, str(raw.content)), usage
            except ValueError as exc:
                return f"{exc}", usage
        runnable = llm.with_structured_output(schema, method=method, include_raw=True)
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(user)])
        usage = _usage(out["raw"])
        if out["parsed"] is not None:
            return out["parsed"], usage
        return f"{out['parsing_error']}", usage

    async def stream_text(self, role: str, system: str, user: str, *, purpose: str) -> AsyncIterator[str]:
        """流式生成正文（写手用）。"""
        profile = await self.resolve(role)
        started = time.monotonic()
        if profile.provider == "demo":
            async for chunk in demo.stream_text(system, user):
                yield chunk
            await self._record(role, profile, purpose, started, 0, 0, ok=True)
            return
        llm = build_chat_model(profile, streaming=True)
        prompt_tokens = completion_tokens = 0
        try:
            async for chunk in llm.astream([SystemMessage(system), HumanMessage(user)]):
                if chunk.usage_metadata:
                    prompt_tokens = chunk.usage_metadata.get("input_tokens", prompt_tokens)
                    completion_tokens = chunk.usage_metadata.get("output_tokens", completion_tokens)
                if chunk.content:
                    yield str(chunk.content)
        except (openai.APIError, TimeoutError) as exc:
            await self._record(
                role, profile, purpose, started, prompt_tokens, completion_tokens, ok=False, error=str(exc)
            )
            raise LLMError(f"调用模型失败（{profile.name}）：{exc}") from exc
        await self._record(role, profile, purpose, started, prompt_tokens, completion_tokens, ok=True)

    async def _record(
        self,
        role: str,
        profile: ResolvedProfile,
        purpose: str,
        started: float,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        ok: bool,
        error: str = "",
    ) -> None:
        async with self.sessionmaker() as session:
            session.add(
                LlmCall(
                    job_id=self.job_id,
                    book_id=self.book_id,
                    role=role,
                    profile_name=profile.name,
                    model=profile.model,
                    purpose=purpose,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    ok=ok,
                    error=error[:2000],
                )
            )
            await session.commit()


def _usage(message) -> tuple[int, int]:
    meta = getattr(message, "usage_metadata", None) or {}
    return int(meta.get("input_tokens", 0)), int(meta.get("output_tokens", 0))


async def ping(profile: ResolvedProfile) -> str:
    """测试连接：发一条极短的请求。"""
    if profile.provider == "demo":
        return "演示模式无需联网"
    llm = build_chat_model(profile).bind(max_tokens=16)
    try:
        reply = await llm.ainvoke([HumanMessage("请只回复：连接成功")])
    except openai.APIError as exc:
        raise LLMError(str(exc)) from exc
    return str(reply.content)[:200]
