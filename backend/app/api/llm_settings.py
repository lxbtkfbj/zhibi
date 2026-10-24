import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.crypto import SecretError, decrypt, encrypt
from app.db import get_sessionmaker
from app.llm import web_search
from app.llm.discovery import ModelDiscoveryError, fetch_models, normalize_base_url
from app.llm.router import LOCAL_HOSTS, LLMError, LLMRouter, ResolvedProfile, ping, tool_support
from app.models import ROLES, AppSetting, LlmProfile, RoleAssignment
from app.schemas import (
    ModelListIn,
    ModelListOut,
    ProfileIn,
    ProfileOut,
    ProfilePatch,
    TestResult,
    WebSearchIn,
    WebSearchOut,
)

router = APIRouter(prefix="/llm", tags=["llm"])


def to_out(p: LlmProfile) -> ProfileOut:
    out = ProfileOut.model_validate(p)
    out.has_key = bool(p.api_key_encrypted)
    return out


async def _get(session: AsyncSession, profile_id: uuid.UUID, *, for_update: bool = False) -> LlmProfile:
    profile = await session.get(
        LlmProfile,
        profile_id,
        with_for_update=True if for_update else None,
        populate_existing=for_update,
    )
    if profile is None:
        raise HTTPException(404, "模型配置不存在")
    return profile


def _validate(provider: str, base_url: str, model: str) -> None:
    if provider == "openai_compatible" and (not base_url.strip() or not model.strip()):
        raise HTTPException(422, "请填写接口地址和模型名")


@router.post("/models", response_model=ModelListOut)
async def list_models(body: ModelListIn, session: AsyncSession = SessionDep) -> ModelListOut:
    try:
        base_url = normalize_base_url(body.base_url)
        api_key = body.api_key.strip()
        if body.profile_id is not None and not api_key:
            profile = await _get(session, body.profile_id)
            if profile.api_key_encrypted:
                # 改地址后必须显式输入 Key，不能将旧配置的凭据发往新的地址。
                if base_url != profile.base_url.strip().rstrip("/"):
                    raise HTTPException(422, "接口地址已更改，请重新填写 API Key 后再获取模型列表")
                api_key = decrypt(profile.api_key_encrypted)
        return ModelListOut(models=await fetch_models(base_url, api_key))
    except SecretError as exc:
        raise HTTPException(422, "已保存的 API Key 无法读取，请重新填写 API Key") from exc
    except ModelDiscoveryError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.get("/profiles", response_model=list[ProfileOut])
async def list_profiles(session: AsyncSession = SessionDep) -> list[ProfileOut]:
    rows = (await session.execute(select(LlmProfile).order_by(LlmProfile.created_at))).scalars().all()
    return [to_out(p) for p in rows]


@router.post("/profiles", response_model=ProfileOut, status_code=201)
async def create_profile(body: ProfileIn, session: AsyncSession = SessionDep) -> ProfileOut:
    _validate(body.provider, body.base_url, body.model)
    data = body.model_dump(exclude={"api_key"})
    profile = LlmProfile(**data)
    try:
        profile.api_key_encrypted = encrypt(body.api_key) if body.api_key else None
    except SecretError as exc:
        raise HTTPException(500, str(exc)) from exc
    session.add(profile)
    try:
        await session.flush()
        # 第一个配置自动设为默认
        default = await session.get(RoleAssignment, "default")
        if default is None:
            session.add(RoleAssignment(role="default", profile_id=profile.id))
        elif default.profile_id is None:
            default.profile_id = profile.id
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "已有同名的模型配置") from exc
    await session.refresh(profile)
    return to_out(profile)


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
async def update_profile(profile_id: uuid.UUID, body: ProfilePatch, session: AsyncSession = SessionDep) -> ProfileOut:
    # Serialize author edits with automatic capability updates. A stale ORM value
    # of False would otherwise omit the hint reset from the UPDATE entirely.
    profile = await _get(session, profile_id, for_update=True)
    changes = body.model_dump(exclude_unset=True, exclude={"api_key"})
    # A different endpoint/model/method is a new capability choice. Unrelated edits
    # (or resubmitting the unchanged form) must retain the automatic-fallback hint.
    if body.api_key or any(
        key in changes and changes[key] != getattr(profile, key)
        for key in ("provider", "base_url", "model", "structured_method")
    ):
        profile.structured_method_auto = False
    if body.api_key or any(
        key in changes and changes[key] != getattr(profile, key) for key in ("provider", "base_url", "model")
    ):
        profile.chat_tools = None
    for key, value in changes.items():
        setattr(profile, key, value)
    if body.api_key:
        profile.api_key_encrypted = encrypt(body.api_key)
    _validate(profile.provider, profile.base_url, profile.model)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "已有同名的模型配置") from exc
    await session.refresh(profile)
    return to_out(profile)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(profile_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    profile = await _get(session, profile_id)
    await session.delete(profile)
    await session.commit()


@router.post("/profiles/{profile_id}/test", response_model=TestResult)
async def test_profile(profile_id: uuid.UUID, session: AsyncSession = SessionDep) -> TestResult:
    profile = await _get(session, profile_id)
    try:
        resolved = ResolvedProfile.from_row(profile)
        reply = await ping(resolved)
    except (LLMError, SecretError) as exc:
        return TestResult(ok=False, message=str(exc)[:500])
    tools, tools_message = await tool_support(resolved)
    # 演示、本机模型照旧不测，也不把跳过测试记成能力结论。
    url = urlparse(resolved.base_url or "")
    if resolved.provider != "demo" and url.hostname not in LOCAL_HOSTS and url.port != 11434 and tools is not None:
        async with LLMRouter(get_sessionmaker()) as llm:
            await llm._remember_chat_tools(resolved, tools)
    return TestResult(ok=True, message=reply, tools=tools, tools_message=tools_message)


@router.get("/roles", response_model=dict[str, uuid.UUID | None])
async def get_roles(session: AsyncSession = SessionDep) -> dict[str, uuid.UUID | None]:
    rows = (await session.execute(select(RoleAssignment))).scalars().all()
    assigned = {r.role: r.profile_id for r in rows}
    return {role: assigned.get(role) for role in ROLES}


@router.put("/roles", response_model=dict[str, uuid.UUID | None])
async def set_roles(
    body: dict[str, uuid.UUID | None], session: AsyncSession = SessionDep
) -> dict[str, uuid.UUID | None]:
    for role, profile_id in body.items():
        if role not in ROLES:
            raise HTTPException(422, f"未知角色：{role}")
        if profile_id is not None:
            await _get(session, profile_id)
        row = await session.get(RoleAssignment, role)
        if row is None:
            session.add(RoleAssignment(role=role, profile_id=profile_id))
        else:
            row.profile_id = profile_id
    await session.commit()
    return await get_roles(session)


async def _web_search(session: AsyncSession) -> AppSetting | None:
    return await session.get(AppSetting, web_search.SETTING)


@router.get("/web-search", response_model=WebSearchOut)
async def get_web_search(session: AsyncSession = SessionDep) -> WebSearchOut:
    row = await _web_search(session)
    return WebSearchOut(has_key=bool(row and row.value.get("api_key_encrypted")))


@router.put("/web-search", response_model=WebSearchOut)
async def set_web_search(body: WebSearchIn, session: AsyncSession = SessionDep) -> WebSearchOut:
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(422, "请填写 API Key")
    try:
        value = {"api_key_encrypted": encrypt(api_key)}
    except SecretError as exc:
        raise HTTPException(500, str(exc)) from exc
    row = await _web_search(session)
    if row is None:
        session.add(AppSetting(key=web_search.SETTING, value=value))
    else:
        row.value = value
    await session.commit()
    return WebSearchOut(has_key=True)


@router.delete("/web-search", response_model=WebSearchOut)
async def clear_web_search(session: AsyncSession = SessionDep) -> WebSearchOut:
    row = await _web_search(session)
    if row is not None:
        await session.delete(row)
        await session.commit()
    return WebSearchOut(has_key=False)


@router.post("/web-search/test", response_model=TestResult)
async def test_web_search(body: WebSearchIn, session: AsyncSession = SessionDep) -> TestResult:
    """填了新密钥就试新的（还没保存也行），没填就试已保存的。"""
    api_key = body.api_key.strip()
    if not api_key:
        row = await _web_search(session)
        token = row.value.get("api_key_encrypted") if row else None
        if not token:
            return TestResult(ok=False, message="还没填 API Key")
        try:
            api_key = decrypt(token)
        except SecretError:
            return TestResult(ok=False, message="已保存的 API Key 无法读取，请重新填写")
    ok, message = await web_search.try_key(api_key)
    return TestResult(ok=ok, message=message)
