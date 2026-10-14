import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep
from app.crypto import SecretError, encrypt
from app.llm.router import LLMError, ResolvedProfile, ping
from app.models import ROLES, LlmProfile, RoleAssignment
from app.schemas import ProfileIn, ProfileOut, ProfilePatch, TestResult

router = APIRouter(prefix="/llm", tags=["llm"])


def to_out(p: LlmProfile) -> ProfileOut:
    out = ProfileOut.model_validate(p)
    out.has_key = bool(p.api_key_encrypted)
    return out


async def _get(session: AsyncSession, profile_id: uuid.UUID) -> LlmProfile:
    profile = await session.get(LlmProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "模型配置不存在")
    return profile


def _validate(provider: str, base_url: str, model: str) -> None:
    if provider == "openai_compatible" and (not base_url.strip() or not model.strip()):
        raise HTTPException(422, "请填写接口地址和模型名")


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
    profile = await _get(session, profile_id)
    changes = body.model_dump(exclude_unset=True, exclude={"api_key"})
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
        reply = await ping(ResolvedProfile.from_row(profile))
    except (LLMError, SecretError) as exc:
        return TestResult(ok=False, message=str(exc)[:500])
    return TestResult(ok=True, message=reply)


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
