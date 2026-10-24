"""模型调用层：按编辑部角色选择模型配置，统一处理结构化输出、重试与用量记录。"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from urllib.parse import urlparse

import httpx
import openai
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crypto import decrypt
from app.llm import demo
from app.models import Book, LlmCall, LlmProfile, RoleAssignment
from app.prompts import prompt_names_for

log = logging.getLogger(__name__)

MAX_PARSE_ATTEMPTS = 3
FULL_CONTENT_LIMIT = 2000


class LLMError(RuntimeError):
    pass


class ToolsUnsupported(LLMError):
    """接口不认工具调用：记在模型配置上，以后走老路。"""


class _TeardownCallError(LLMError):
    """拆书的逐次失败已经记过，不再重复记一条。"""


@dataclass
class TeardownPolicy:
    """一次拆书共享的临时策略；不写模型配置，也不影响写书调用。"""

    parallel: int = 4
    ignore_reasoning: bool = False
    rate_limits: list[float] = field(default_factory=list)

    def rate_limited(self) -> None:
        now = time.monotonic()
        self.rate_limits[:] = [at for at in self.rate_limits if now - at < 60]
        self.rate_limits.append(now)
        if len(self.rate_limits) >= 2:
            self.parallel = max(1, self.parallel - 1)


def _unsupported_reasoning(exc: openai.APIStatusError) -> bool:
    message = f"{exc} {json.dumps(exc.body, ensure_ascii=False, default=str)}".lower()
    return (
        exc.status_code in (400, 422)
        and any(term in message for term in ("reasoning_effort", "reasoning effort", "reasoning", "推理强度"))
        and any(
            term in message
            for term in (
                "unsupported",
                "not support",
                "doesn't support",
                "unrecognized",
                "unknown",
                "not allowed",
                "不支持",
                "不认",
            )
        )
    )


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


# 多来回调工具：每个来回 429／5xx／断线最多重来几次（这一来回已经吐过字就不重来）
TOOL_ROUND_ATTEMPTS = 3


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
    chat_tools: bool | None = None
    timeout_s: int = 300
    reasoning_effort: str | None = None
    profile_id: uuid.UUID | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: LlmProfile) -> "ResolvedProfile":
        return cls(
            profile_id=row.id,
            updated_at=row.updated_at,
            name=row.name,
            provider=row.provider,
            base_url=row.base_url,
            api_key=decrypt(row.api_key_encrypted) if row.api_key_encrypted else "",
            model=row.model,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            structured_method=row.structured_method,
            chat_tools=row.chat_tools,
            timeout_s=row.timeout_s,
            reasoning_effort=row.reasoning_effort or None,
        )


DEMO_PROFILE = ResolvedProfile(name="演示模式", provider="demo", model="demo")


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def build_chat_model(
    p: ResolvedProfile,
    *,
    http_client: httpx.Client,
    http_async_client: httpx.AsyncClient,
    streaming: bool = False,
) -> ChatOpenAI:
    """客户端必须由调用方拥有，不能落入 LangChain 的跨任务全局缓存。"""
    kwargs: dict = {}
    if p.reasoning_effort:
        kwargs["reasoning_effort"] = p.reasoning_effort
    return ChatOpenAI(
        model=p.model,
        base_url=p.base_url or None,
        api_key=p.api_key or "EMPTY",
        temperature=p.temperature,
        max_tokens=p.max_tokens,
        timeout=p.timeout_s,
        # 重试必须在路由层进行，否则 SDK 内的失败请求不会留下逐次记录。
        max_retries=0,
        streaming=streaming,
        stream_usage=True,
        http_client=http_client,
        http_async_client=http_async_client,
        # 代理与传输由显式客户端负责，禁用库默认 socket transport 及其误报警告。
        http_socket_options=(),
        **kwargs,
    )


class _HttpClients:
    """仅在本任务中复用连接；本地/远程代理策略和不同超时不能混用。"""

    def __init__(self) -> None:
        self._pairs: dict[tuple[bool, int], tuple[httpx.Client, httpx.AsyncClient]] = {}
        self._closed = False

    def for_profile(self, profile: ResolvedProfile) -> tuple[httpx.Client, httpx.AsyncClient]:
        if self._closed:
            raise RuntimeError("模型 HTTP 客户端已经关闭")
        trust_env = urlparse(profile.base_url).hostname not in LOCAL_HOSTS
        key = (trust_env, profile.timeout_s)
        if key not in self._pairs:
            # 远程保留系统代理，本机模型（如 Ollama）仍然直连。
            client = httpx.Client(trust_env=trust_env, timeout=profile.timeout_s)
            try:
                async_client = httpx.AsyncClient(trust_env=trust_env, timeout=profile.timeout_s)
            except BaseException:
                client.close()
                raise
            self._pairs[key] = (client, async_client)
        return self._pairs[key]

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        pairs, self._pairs = self._pairs, {}
        errors: list[BaseException] = []
        for client, async_client in pairs.values():
            try:
                await async_client.aclose()
            except BaseException as exc:
                errors.append(exc)
            try:
                client.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "\n\n请只输出一个 JSON 对象，不要输出任何其他文字或代码块标记。"
        f"JSON 必须符合以下 JSON Schema：\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
    )


def _unsupported_structured_method(exc: openai.BadRequestError, method: str) -> bool:
    """Only remember capability errors, never malformed schemas or unrelated 400s."""
    message = f"{exc} {json.dumps(exc.body, ensure_ascii=False, default=str)}".lower()
    if any(
        term in message
        for term in (
            "invalid schema",
            "invalid_json_schema",
            "invalid_function_parameters",
            "schema validation",
            "schema is invalid",
            "unsupported schema keyword",
        )
    ):
        return False
    feature_terms = (
        (
            "tools",
            "tool_choice",
            "function_call",
            "functions",
            "function calling",
            "function-calling",
            "tool calling",
            "tool use",
            "工具调用",
        )
        if method == "function_calling"
        else ("response_format", "json_schema", "json schema", "structured output")
    )
    unsupported_terms = (
        "unsupported",
        "not support",
        "doesn't support",
        "unrecognized",
        "unknown parameter",
        "not available",
        "不支持",
        "未支持",
    )
    return any(term in message for term in feature_terms) and any(term in message for term in unsupported_terms)


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
        self._http_clients = _HttpClients()

    def _chat_model(self, profile: ResolvedProfile, *, streaming: bool = False) -> ChatOpenAI:
        client, async_client = self._http_clients.for_profile(profile)
        return build_chat_model(
            profile,
            http_client=client,
            http_async_client=async_client,
            streaming=streaming,
        )

    async def aclose(self) -> None:
        """在任务的事件循环结束之前释放所有模型连接。"""
        await self._http_clients.aclose()

    async def __aenter__(self) -> "LLMRouter":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

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

    def _unchanged_profile(self, profile: ResolvedProfile):
        statement = update(LlmProfile).where(
            LlmProfile.id == profile.profile_id,
            LlmProfile.structured_method == profile.structured_method,
            LlmProfile.base_url == profile.base_url,
            LlmProfile.model == profile.model,
            LlmProfile.provider == profile.provider,
        )
        if profile.updated_at is not None:
            # Never overwrite a configuration the author edited while this call ran.
            statement = statement.where(LlmProfile.updated_at == profile.updated_at)
        return statement

    async def _remember_chat_tools(self, profile: ResolvedProfile, supported: bool) -> None:
        if profile.profile_id is None:
            return
        async with self.sessionmaker() as session:
            await session.execute(self._unchanged_profile(profile).values(chat_tools=supported))
            await session.commit()

    async def _remember_structured_method(self, profile: ResolvedProfile, method: str) -> None:
        if profile.profile_id is None:
            return
        async with self.sessionmaker() as session:
            statement = self._unchanged_profile(profile)
            result = await session.execute(statement.values(structured_method=method, structured_method_auto=True))
            await session.commit()
            if result.rowcount:
                log.info("模型配置 %s (%s) 已自动改用 %s，已保存", profile.name, profile.profile_id, method)

    async def structured[T: BaseModel](
        self,
        role: str,
        schema: type[T],
        system: str,
        user: str,
        *,
        purpose: str,
        max_attempts: int = MAX_PARSE_ATTEMPTS,
        teardown_policy: TeardownPolicy | None = None,
    ) -> T:
        profile = await self.resolve(role)
        if profile.provider == "demo":
            started = time.monotonic()
            request = _request(system, user, schema, "demo")
            try:
                result = await demo.respond(schema, system, user)
            except Exception as exc:
                await self._record(role, profile, purpose, started, 0, 0, ok=False, error=str(exc), request=request)
                raise
            await self._record(
                role, profile, purpose, started, 0, 0, ok=True, request=request, response=result.model_dump_json()
            )
            return result
        return await self._structured_remote(
            role,
            profile,
            schema,
            system,
            user,
            purpose,
            max_attempts=max_attempts,
            teardown_policy=teardown_policy,
        )

    async def _invoke_teardown[T: BaseModel](
        self,
        role: str,
        profile: ResolvedProfile,
        method: str,
        schema: type[T],
        system: str,
        user: str,
        purpose: str,
        policy: TeardownPolicy,
    ) -> "tuple[Outcome[T], float]":
        limited = 0
        while True:
            temporary = replace(profile, reasoning_effort=None if policy.ignore_reasoning else "low")
            started = time.monotonic()
            try:
                return await self._invoke_structured(temporary, method, schema, system, user), started
            except openai.APIStatusError as exc:
                # 别的一批可能已在本请求飞行中更新共享策略；按这次实际发出的参数判断。
                reasoning = temporary.reasoning_effort is not None and _unsupported_reasoning(exc)
                if not reasoning and exc.status_code != 429:
                    raise
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    None,
                    None,
                    ok=False,
                    error=str(exc),
                    request=_request(system, user, schema, method),
                    response=_error_response(exc),
                )
                if reasoning:
                    policy.ignore_reasoning = True
                    continue
                limited += 1
                policy.rate_limited()
                if limited >= 6:
                    raise _TeardownCallError(f"调用模型失败（{profile.name}）：{exc}") from exc
                await asyncio.sleep(min(5 * 2 ** (limited - 1), 40))

    async def _structured_remote[T: BaseModel](
        self,
        role: str,
        profile: ResolvedProfile,
        schema: type[T],
        system: str,
        user: str,
        purpose: str,
        *,
        max_attempts: int = MAX_PARSE_ATTEMPTS,
        teardown_policy: TeardownPolicy | None = None,
    ) -> T:
        method = profile.structured_method
        last_error = ""
        unsupported_method = False
        for attempt in range(1, max_attempts + 1):
            prompt_user = (
                user
                if not last_error
                else f"{user}\n\n【上次输出无法解析】{last_error}\n请严格按要求的结构重新输出完整结果。"
            )
            started = time.monotonic()
            request = _request(system, prompt_user, schema, method)
            try:
                if teardown_policy is not None:
                    outcome, started = await self._invoke_teardown(
                        role, profile, method, schema, system, prompt_user, purpose, teardown_policy
                    )
                else:
                    outcome = await self._invoke_structured(profile, method, schema, system, prompt_user)
            except openai.BadRequestError as exc:
                # 部分接口不支持工具调用或 JSON Schema，自动降级为 JSON 模式
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    None,
                    None,
                    ok=False,
                    error=str(exc),
                    request=request,
                    response=_error_response(exc),
                )
                if method != "json_mode" and attempt < max_attempts and _unsupported_structured_method(exc, method):
                    log.warning("模型配置 %s 的结构化输出方式 %s 不受支持，尝试 json_mode", profile.name, method)
                    unsupported_method = True
                    method = "json_mode"
                    continue
                raise LLMError(f"模型接口拒绝了请求：{exc}") from exc
            except (openai.APIError, TimeoutError) as exc:
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    None,
                    None,
                    ok=False,
                    error=str(exc),
                    request=request,
                    response=_error_response(exc),
                )
                retryable = isinstance(exc, (TimeoutError, openai.APIConnectionError)) or (
                    isinstance(exc, openai.APIStatusError) and (exc.status_code == 429 or exc.status_code >= 500)
                )
                if retryable and attempt < max_attempts:
                    continue
                raise LLMError(f"调用模型失败（{profile.name}）：{exc}") from exc
            except _TeardownCallError:
                raise
            except Exception as exc:
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    None,
                    None,
                    ok=False,
                    error=str(exc),
                    request=request,
                    response=_error_response(exc),
                )
                raise
            prompt_tokens, completion_tokens = outcome.usage
            if outcome.parsed is not None and not outcome.truncated:
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    prompt_tokens,
                    completion_tokens,
                    ok=True,
                    request=request,
                    response=outcome.response,
                )
                if unsupported_method and method != profile.structured_method:
                    await self._remember_structured_method(profile, method)
                return outcome.parsed
            last_error = (outcome.error or ("模型输出被截断" if outcome.truncated else "未返回结构化结果"))[:500]
            await self._record(
                role,
                profile,
                purpose,
                started,
                prompt_tokens,
                completion_tokens,
                ok=False,
                error=last_error,
                request=request,
                response=outcome.response,
            )
            if outcome.truncated:
                # 被截断时重试同样的请求没有意义
                raise LLMError(
                    f"模型输出被截断（本次输入 {prompt_tokens if prompt_tokens is not None else '未知'} token，"
                    f"输出 {completion_tokens if completion_tokens is not None else '未知'} token）："
                    "上下文窗口或最大输出长度不够。请换用上下文更长的模型，或调大最大输出 token；"
                    "本地 Ollama 需要调大 num_ctx。"
                )
            if method != "json_mode":
                # 工具调用格式失败后改用 JSON 模式，小模型往往更稳定
                method = "json_mode"
        raise LLMError(f"模型连续 {MAX_PARSE_ATTEMPTS} 次没有按要求的格式输出：{last_error}")

    async def _invoke_structured[T: BaseModel](
        self, profile: ResolvedProfile, method: str, schema: type[T], system: str, user: str
    ) -> "Outcome[T]":
        llm = self._chat_model(profile)
        if method == "json_mode":
            raw = await llm.bind(response_format={"type": "json_object"}).ainvoke(
                [SystemMessage(system + schema_instruction(schema)), HumanMessage(user)]
            )
            outcome: Outcome[T] = Outcome(usage=_usage(raw), truncated=_truncated(raw), response=_raw_response(raw))
            try:
                outcome.parsed = parse_json_output(schema, str(raw.content))
            except ValueError as exc:
                outcome.error = str(exc)
            return outcome

        runnable = llm.with_structured_output(schema, method=method, include_raw=True)
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(user)])
        raw = out["raw"]
        outcome = Outcome(usage=_usage(raw), truncated=_truncated(raw), response=_raw_response(raw))
        if out["parsed"] is not None:
            outcome.parsed = out["parsed"]
            return outcome
        if out["parsing_error"] is not None:
            outcome.error = str(out["parsing_error"])
            return outcome
        # 没有拿到工具调用：参数 JSON 不完整，或者模型直接用文字回复了 JSON
        candidates = [str(c.get("args") or "") for c in getattr(raw, "invalid_tool_calls", None) or []]
        candidates.append(str(raw.content or ""))
        for text in candidates:
            try:
                outcome.parsed = parse_json_output(schema, text)
                return outcome
            except ValueError:
                continue
        snippet = str(raw.content or "").strip()[:200]
        outcome.error = f"模型没有按结构化格式输出{('，而是回复了：' + snippet) if snippet else ''}"
        return outcome

    async def stream_text(self, role: str, system: str, user: str, *, purpose: str) -> AsyncIterator[str]:
        """流式生成正文（写手用）。"""
        profile = await self.resolve(role)
        started = time.monotonic()
        request = _request(system, user, None, "demo_stream" if profile.provider == "demo" else "stream_text")
        prompt_tokens = completion_tokens = 0 if profile.provider == "demo" else None
        parts: list[str] = []
        ok, error = False, ""
        truncated = False
        try:
            if profile.provider == "demo":
                async for chunk in demo.stream_text(system, user):
                    parts.append(chunk)
                    yield chunk
            else:
                llm = self._chat_model(profile, streaming=True)
                async for chunk in llm.astream([SystemMessage(system), HumanMessage(user)]):
                    truncated = truncated or _truncated(chunk)
                    if chunk.usage_metadata:
                        prompt_tokens = chunk.usage_metadata.get("input_tokens", prompt_tokens)
                        completion_tokens = chunk.usage_metadata.get("output_tokens", completion_tokens)
                    if chunk.content:
                        parts.append(str(chunk.content))
                        yield str(chunk.content)
            if truncated:
                raise LLMError(
                    "模型输出被截断：正文尚未完成。原样回复已保存在调用记录，请调大最大输出 token 或换用上下文更长的模型。"
                )
            ok = True
        except (openai.APIError, TimeoutError) as exc:
            error = str(exc)
            raise LLMError(f"调用模型失败（{profile.name}）：{exc}") from exc
        except BaseException as exc:
            error = str(exc) or type(exc).__name__
            raise
        finally:
            await self._record(
                role,
                profile,
                purpose,
                started,
                prompt_tokens,
                completion_tokens,
                ok=ok,
                error=error,
                request=request,
                response="".join(parts),
            )

    async def tool_rounds(
        self,
        role: str,
        system: str,
        user: str,
        tools: list[dict],
        run_tool: Callable[[ToolCall], Awaitable[str]],
        *,
        purpose: str,
        max_rounds: int = 6,
    ) -> AsyncIterator[tuple[str, str]]:
        """多来回调工具（聊天里接话的人自己查、自己动手）：模型调了工具就执行，把结果交回去再问；
        哪一来回不调工具了，那一来回的字就是回答，边写边吐 ("text", 字)。调工具的那一来回要是先说了几句，
        吐 ("reset", "") 让调用方清掉。模型在写工具参数（不出字）时也吐 ("tick", "")：调用方据此知道它还在动。
        最后一来回不许再调工具，逼它把话说完。
        只看有没有调工具，不看结束原因（中转拼出来的结束原因不可靠）。每个来回记一条调用记录。"""
        profile = await self.resolve(role)
        names = [tool["function"]["name"] for tool in tools]
        history: list = [SystemMessage(system), HumanMessage(user)]
        transcript = user
        done: list[tuple[ToolCall, str]] = []
        for round_no in range(1, max_rounds + 1):
            last = round_no == max_rounds
            request = {
                "system": system,
                "user": transcript,
                "schema_name": "工具：" + "、".join(names) + ("（这一来回不许再调工具）" if last else ""),
                "schema": tools,
                "method": "tools",
                "round": round_no,
                "prompt_names": prompt_names_for(system, user),
            }
            text, calls = "", []
            async for kind, value in self._tool_round(role, profile, history, tools, done, last, request, purpose):
                if kind in ("text", "tick"):
                    yield kind, value
                else:
                    text, calls = value
            if not calls:
                return
            if text.strip():
                yield "reset", ""
            history.append(
                AIMessage(
                    content=text,
                    tool_calls=[{"name": c.name, "args": c.args or {}, "id": c.id, "type": "tool_call"} for c in calls],
                )
            )
            lines = []
            for call in calls:
                result = (
                    await run_tool(call)
                    if call.args is not None
                    else "参数没法解析（不是合法的 JSON），照工具说明重新调一次。"
                )
                done.append((call, result))
                history.append(ToolMessage(content=result, tool_call_id=call.id))
                lines.append(f"调了 {call.name}：{json.dumps(call.args, ensure_ascii=False)}\n工具回：{result}")
            transcript += f"\n\n—— 第 {round_no} 来回调的工具 ——\n" + "\n\n".join(lines)

    async def _tool_round(self, role, profile, history, tools, done, last, request, purpose):
        """一个来回：边写边吐字，最后吐 ("done", (这一来回的字, 调的工具))。"""
        if profile.provider == "demo":
            started = time.monotonic()
            names = [] if last else [tool["function"]["name"] for tool in tools]
            planned, text = demo.tool_turn(history[0].content, history[1].content, names, done)
            calls = [ToolCall(f"demo_{len(done)}_{i}", name, args) for i, (name, args) in enumerate(planned)]
            await self._record(
                role, profile, purpose, started, 0, 0, ok=True, request=request, response=_round_response(text, calls)
            )
            if not calls:
                for i in range(0, len(text), 8):
                    await asyncio.sleep(demo.DELAY_S / 40)
                    yield "text", text[i : i + 8]
            yield "done", (text, calls)
            return
        llm = self._chat_model(profile, streaming=True)
        bound = llm.bind_tools(tools, tool_choice="none") if last else llm.bind_tools(tools)
        for attempt in range(1, TOOL_ROUND_ATTEMPTS + 1):
            started = time.monotonic()
            message = None
            usage = (None, None)
            parts: list[str] = []
            calls: list[ToolCall] = []
            ok, error, failure = False, "", None
            try:
                async for chunk in bound.astream(history):
                    # 消息相加会把累计用量也相加；记账只留最后一个带用量的小块。
                    if chunk.usage_metadata:
                        usage = _usage(chunk)
                    message = chunk if message is None else message + chunk
                    piece = _content_text(chunk.content)
                    if piece:
                        parts.append(piece)
                        yield "text", piece
                    else:
                        # 在写工具参数、在想：不出字，但还在动
                        yield "tick", ""
                calls = _tool_calls(message, len(done))
                if _truncated(message):
                    error = "模型输出被截断"
                else:
                    ok = True
            except BaseException as exc:
                error, failure = str(exc) or type(exc).__name__, exc
            finally:
                await self._record(
                    role,
                    profile,
                    purpose,
                    started,
                    *usage,
                    ok=ok,
                    error=error,
                    request=request,
                    response=_round_response("".join(parts), calls)
                    or (_error_response(failure) if isinstance(failure, Exception) else None),
                )
            if failure is None and not ok:
                raise LLMError(
                    "模型输出被截断：上下文窗口或最大输出长度不够，请调大最大输出 token 或换用上下文更长的模型。"
                )
            if failure is None:
                yield "done", ("".join(parts), calls)
                return
            if isinstance(failure, openai.BadRequestError):
                if not parts and _unsupported_structured_method(failure, "function_calling"):
                    log.warning("模型配置 %s 不支持工具调用，以后聊天走老路", profile.name)
                    await self._remember_chat_tools(profile, False)
                    raise ToolsUnsupported(f"这个模型不支持工具调用：{failure}") from failure
                raise LLMError(f"模型接口拒绝了请求：{failure}") from failure
            if isinstance(failure, (openai.APIError, TimeoutError)):
                retryable = isinstance(failure, (TimeoutError, openai.APIConnectionError)) or (
                    isinstance(failure, openai.APIStatusError)
                    and (failure.status_code == 429 or failure.status_code >= 500)
                )
                if retryable and attempt < TOOL_ROUND_ATTEMPTS and not parts:
                    continue
                raise LLMError(f"调用模型失败（{profile.name}）：{failure}") from failure
            raise failure

    async def _record(
        self,
        role: str,
        profile: ResolvedProfile,
        purpose: str,
        started: float,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        *,
        ok: bool,
        error: str = "",
        request: dict | None = None,
        response: str | None = None,
    ) -> None:
        async with self.sessionmaker() as session:
            # 同一本书并行审稿时串行化入库与清理，保证第 2001 条之后仍严格保留 2000 条正文。
            if self.book_id is not None:
                await session.execute(select(Book.id).where(Book.id == self.book_id).with_for_update())
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
                    request=request,
                    response=response,
                )
            )
            await session.flush()
            scope = LlmCall.book_id == self.book_id if self.book_id is not None else LlmCall.book_id.is_(None)
            cutoff = await session.scalar(
                select(LlmCall.id).where(scope).order_by(LlmCall.id.desc()).offset(FULL_CONTENT_LIMIT).limit(1)
            )
            if cutoff is not None:
                await session.execute(
                    update(LlmCall)
                    .where(
                        scope, LlmCall.id <= cutoff, or_(LlmCall.request.is_not(None), LlmCall.response.is_not(None))
                    )
                    .values(request=None, response=None)
                )
            await session.commit()


@dataclass
class Outcome[T: BaseModel]:
    usage: tuple[int | None, int | None]
    truncated: bool = False
    parsed: T | None = None
    error: str = ""
    response: str = ""


def _request(system: str, user: str, schema: type[BaseModel] | None, method: str) -> dict:
    return {
        "system": system + schema_instruction(schema) if schema is not None and method == "json_mode" else system,
        "user": user,
        "schema_name": schema.__name__ if schema is not None else None,
        "schema": schema.model_json_schema() if schema is not None else None,
        "method": method,
        "prompt_names": prompt_names_for(system, user),
    }


def _raw_response(message) -> str:
    """优先保留供应商的工具参数原文（包括无效 JSON），而不是重新序列化验证后的模型。"""
    calls = (getattr(message, "additional_kwargs", None) or {}).get("tool_calls") or []
    if calls:
        return "\n".join(str((call.get("function") or {}).get("arguments") or "") for call in calls)
    calls = getattr(message, "invalid_tool_calls", None) or getattr(message, "tool_calls", None) or []
    if calls:
        return "\n".join(
            args if isinstance(args := call.get("args"), str) else json.dumps(args, ensure_ascii=False)
            for call in calls
        )
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def _error_response(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if body is None:
        return None
    return body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, default=str)


def _truncated(message) -> bool:
    # 中转会把好几段结束原因拼在一起（「tool_callstool_calls」「lengthlength」），看有没有 length
    meta = getattr(message, "response_metadata", None) or {}
    return "length" in str(meta.get("finish_reason") or "")


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part)
        for part in content or []
        if not isinstance(part, dict) or part.get("type", "text") == "text"
    )


def _tool_calls(message, offset: int) -> list[ToolCall]:
    """这一来回调了哪些工具：参数不是合法 JSON 的 args 记成 None，回给模型让它重调。没有 id 的补一个。"""
    if message is None:
        return []
    calls = [(c.get("id"), c.get("name") or "", c.get("args") or {}) for c in message.tool_calls or []]
    calls += [(c.get("id"), c.get("name") or "", None) for c in getattr(message, "invalid_tool_calls", None) or []]
    return [ToolCall(id or f"call_{offset}_{i}", name, args) for i, (id, name, args) in enumerate(calls)]


def _round_response(text: str, calls: list[ToolCall]) -> str:
    if not calls:
        return text
    lines = "\n".join(f"{c.name}：{json.dumps(c.args, ensure_ascii=False)}" for c in calls)
    return (text + "\n\n" if text else "") + "【调了工具】\n" + lines


def _usage(message) -> tuple[int | None, int | None]:
    meta = getattr(message, "usage_metadata", None) or {}
    return (
        int(meta["input_tokens"]) if meta.get("input_tokens") is not None else None,
        int(meta["output_tokens"]) if meta.get("output_tokens") is not None else None,
    )


async def ping(profile: ResolvedProfile) -> str:
    """测试连接：发一条极短的请求。"""
    if profile.provider == "demo":
        return "演示模式无需联网"
    clients = _HttpClients()
    try:
        client, async_client = clients.for_profile(profile)
        llm = build_chat_model(profile, http_client=client, http_async_client=async_client).bind(max_tokens=64)
        reply = await llm.ainvoke([HumanMessage("请只回复：连接成功")])
    except openai.APIError as exc:
        raise LLMError(str(exc)) from exc
    finally:
        await clients.aclose()
    text = str(reply.content).strip()
    return text[:200] if text else "连接成功（模型在思考，没有直接回复；可在高级参数里把推理强度设为 none）"


PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "look_up",
        "description": "查一条设定",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
}


async def tool_support(profile: ResolvedProfile) -> tuple[bool | None, str]:
    """测试时顺带看：群聊里编辑部用这个模型能不能自己查资料、自己动手。
    演示模式、本机模型不测；其余不管结构化输出方式，真叫它调一次普通工具。"""
    if profile.provider == "demo":
        return None, "演示模式不真调工具"
    url = urlparse(profile.base_url or "")
    if url.hostname in LOCAL_HOSTS or url.port == 11434:
        return False, "本机模型不让编辑部自己查资料、翻手册、动手（太慢）：群聊里先判断要做什么，再一件件做"
    clients = _HttpClients()
    try:
        client, async_client = clients.for_profile(profile)
        llm = build_chat_model(profile, http_client=client, http_async_client=async_client).bind_tools([PROBE_TOOL])
        reply = await llm.ainvoke([HumanMessage("请调用 look_up 工具，name 填「测试」。")])
    except Exception as exc:  # 测试按钮不该报 500：不认工具的接口什么错都可能回
        return False, f"调工具出错了：{str(exc)[:200]}"
    finally:
        await clients.aclose()
    if getattr(reply, "tool_calls", None):
        return True, "能调工具：群聊里编辑部会自己查资料、翻手册、动手"
    return False, "叫它调工具它没调：群聊里编辑部用它时会退回老办法，先判断要做什么，再一件件做"
