"""Capability fallback memory must not overwrite edits or mislabel manual settings."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from pydantic import BaseModel

from app.api.llm_settings import _get, to_out, update_profile
from app.llm.router import LLMError, LLMRouter, Outcome, _unsupported_structured_method
from app.models import LlmProfile, RoleAssignment
from app.schemas import ProfilePatch


class Answer(BaseModel):
    answer: str


def bad_request(message):
    return openai.BadRequestError(
        message,
        response=httpx.Response(400, request=httpx.Request("POST", "https://model.example/v1/chat/completions")),
        body={"error": {"message": message}},
    )


@pytest.mark.parametrize(
    "method,message,expected",
    [
        ("function_calling", "unsupported_tools", True),
        ("function_calling", "tools are not supported by this model", True),
        ("function_calling", "This model does not support function calling", True),
        ("function_calling", "Tool calling is not supported", True),
        ("function_calling", "Tool use is not supported", True),
        ("function_calling", "不支持工具调用", True),
        ("json_schema", "response_format type json_schema is not supported", True),
        ("json_schema", "Unknown parameter: response_format", True),
        ("json_schema", "Invalid schema for response_format: 'oneOf' is not supported", False),
        ("function_calling", "invalid_function_parameters: tools schema keyword is unsupported", False),
        ("function_calling", "max_tokens is not supported", False),
        ("json_schema", "context_length_exceeded", False),
    ],
)
def test_only_capability_errors_are_remembered(method, message, expected):
    assert _unsupported_structured_method(bad_request(message), method) is expected


async def seed(sessionmaker, method="function_calling"):
    async with sessionmaker() as session:
        profile = LlmProfile(name="memory", base_url="https://model.example/v1", model="chat", structured_method=method)
        session.add(profile)
        await session.flush()
        session.add(RoleAssignment(role="default", profile_id=profile.id))
        await session.commit()
        return profile.id


async def test_json_schema_capability_fallback_is_persisted(sessionmaker, monkeypatch):
    profile_id = await seed(sessionmaker, "json_schema")
    async with LLMRouter(sessionmaker) as router:
        invoke = AsyncMock(
            side_effect=[
                bad_request("response_format json_schema is not supported"),
                Outcome(usage=(1, 1), parsed=Answer(answer="ok"), response='{"answer":"ok"}'),
            ]
        )
        monkeypatch.setattr(router, "_invoke_structured", invoke)
        await router.structured("chief", Answer, "system", "user", purpose="schema fallback")
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.structured_method == "json_mode" and profile.structured_method_auto


async def test_parse_fallback_is_not_persisted(sessionmaker, monkeypatch):
    profile_id = await seed(sessionmaker)
    async with LLMRouter(sessionmaker) as router:
        monkeypatch.setattr(
            router,
            "_invoke_structured",
            AsyncMock(
                side_effect=[
                    Outcome(usage=(1, 1), error="bad JSON", response="broken"),
                    Outcome(usage=(1, 1), parsed=Answer(answer="ok"), response='{"answer":"ok"}'),
                ]
            ),
        )
        await router.structured("chief", Answer, "system", "user", purpose="parse failure")
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.structured_method == "function_calling" and not profile.structured_method_auto


async def test_concurrent_author_edit_is_not_overwritten(sessionmaker):
    profile_id = await seed(sessionmaker)
    async with LLMRouter(sessionmaker) as router:
        original = await router.resolve("chief")
        async with sessionmaker() as session:
            # Even changing only the key, which isn't present in the UPDATE predicates,
            # changes updated_at and must win over the in-flight model invocation.
            await update_profile(profile_id, ProfilePatch(api_key="new-fake-key"), session)
        await router._remember_structured_method(original, "json_mode")
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.structured_method == "function_calling" and not profile.structured_method_auto


async def test_auto_hint_survives_unrelated_edits_and_clears_on_manual_method_change(sessionmaker):
    profile_id = await seed(sessionmaker)
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        profile.structured_method = "json_mode"
        profile.structured_method_auto = True
        await session.commit()
        assert to_out(profile).structured_method_auto
        same = await update_profile(profile_id, ProfilePatch(name="renamed", structured_method="json_mode"), session)
        assert same.structured_method_auto
        manual = await update_profile(profile_id, ProfilePatch(structured_method="json_schema"), session)
        assert not manual.structured_method_auto and manual.structured_method == "json_schema"


async def test_author_update_lock_serializes_in_flight_fallback(sessionmaker):
    profile_id = await seed(sessionmaker)
    async with LLMRouter(sessionmaker) as router:
        original = await router.resolve("chief")
        async with sessionmaker() as author:
            locked = await _get(author, profile_id, for_update=True)
            assert not locked.structured_method_auto
            pending = asyncio.create_task(router._remember_structured_method(original, "json_mode"))
            try:
                await asyncio.sleep(0.05)
                assert not pending.done(), "Fallback must wait for the author's row lock"
                await update_profile(profile_id, ProfilePatch(model="new-model"), author)
                await asyncio.wait_for(pending, timeout=5)
            finally:
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.model == "new-model"
        assert profile.structured_method == "function_calling" and not profile.structured_method_auto


async def test_invalid_schema_400_does_not_retry_or_persist(sessionmaker, monkeypatch):
    profile_id = await seed(sessionmaker, "json_schema")
    async with LLMRouter(sessionmaker) as router:
        invoke = AsyncMock(side_effect=bad_request("Invalid schema for response_format: 'oneOf' is not supported"))
        monkeypatch.setattr(router, "_invoke_structured", invoke)
        with pytest.raises(LLMError):
            await router.structured("chief", Answer, "system", "user", purpose="invalid schema")
        assert invoke.await_count == 1
    async with sessionmaker() as session:
        profile = await session.get(LlmProfile, profile_id)
        assert profile.structured_method == "json_schema" and not profile.structured_method_auto
