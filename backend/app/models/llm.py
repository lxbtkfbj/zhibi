import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Identity, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk

ROLES = ("default", "chief", "lorekeeper", "writer", "reviewer", "router", "teardown")


class LlmProfile(UUIDPk, Timestamps, Base):
    """一套模型配置（接口地址 + 模型 + 参数）。"""

    __tablename__ = "llm_profiles"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    # openai_compatible：OpenAI 兼容接口；demo：内置演示模型，不联网
    provider: Mapped[str] = mapped_column(String(30), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200), default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.8)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    # function_calling / json_mode / json_schema
    structured_method: Mapped[str] = mapped_column(String(30), default="function_calling")
    structured_method_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    timeout_s: Mapped[int] = mapped_column(Integer, default=300)
    # 推理强度（none / low / medium / high）；留空不发送。Ollama 上设为 none 可关闭思考，速度快很多
    reasoning_effort: Mapped[str | None] = mapped_column(String(20))


class RoleAssignment(Base):
    """编辑部角色 → 模型配置。没有单独分配的角色使用 default。"""

    __tablename__ = "role_assignments"

    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_profiles.id", ondelete="SET NULL"))


class LlmCall(Base):
    """每次模型调用的耗时与用量，供界面展示。"""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_book_id_id", "book_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="SET NULL"), index=True)
    role: Mapped[str] = mapped_column(String(30))
    profile_name: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    purpose: Mapped[str] = mapped_column(String(100), default="")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    response: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptOverride(Base):
    """全局提示词覆盖；读取时直接查数据库，API 和 worker 无须共享进程内缓存。"""

    __tablename__ = "prompt_overrides"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
