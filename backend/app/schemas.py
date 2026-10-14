"""接口的请求与响应模型。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 模型配置 ----------

StructuredMethod = Literal["function_calling", "json_mode", "json_schema"]
ReasoningEffort = Literal["", "none", "minimal", "low", "medium", "high"]


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: Literal["openai_compatible", "demo"] = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = Field(0.8, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
    structured_method: StructuredMethod = "function_calling"
    timeout_s: int = Field(300, ge=10, le=3600)
    reasoning_effort: ReasoningEffort = ""


class ProfilePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    provider: Literal["openai_compatible", "demo"] | None = None
    base_url: str | None = None
    # 留空表示不修改已保存的 Key
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
    structured_method: StructuredMethod | None = None
    timeout_s: int | None = Field(None, ge=10, le=3600)
    reasoning_effort: ReasoningEffort | None = None


class ProfileOut(ORM):
    id: uuid.UUID
    name: str
    provider: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int | None
    structured_method: str
    timeout_s: int
    reasoning_effort: str | None
    has_key: bool = False


class TestResult(BaseModel):
    ok: bool
    message: str


# ---------- 书 ----------


class BookCreate(BaseModel):
    idea: str = Field(min_length=4, max_length=5000)
    style_reference: str = Field("", max_length=20000)


class BookPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    style_reference: str | None = Field(None, max_length=20000)
    concept: dict | None = None


class JobOut(ORM):
    id: uuid.UUID
    book_id: uuid.UUID
    kind: str
    status: str
    pending: dict | None
    error: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class BookSummary(ORM):
    id: uuid.UUID
    title: str
    source: str
    genre: str
    status: str
    idea: str
    logline: str = ""
    created_at: datetime
    updated_at: datetime


class BookDetail(BookSummary):
    style_reference: str
    concept: dict
    active_job: JobOut | None = None


class BookCreated(BaseModel):
    book: BookDetail
    job: JobOut


# ---------- 大纲 ----------


class UnitOut(ORM):
    id: uuid.UUID
    index: int
    title: str
    chapter_count: int
    goal: str
    conflict: str
    climax: str
    outcome: str
    key_events: list[str]


class UnitPatch(BaseModel):
    title: str | None = None
    chapter_count: int | None = Field(None, ge=1, le=50)
    goal: str | None = None
    conflict: str | None = None
    climax: str | None = None
    outcome: str | None = None
    key_events: list[str] | None = None


class VolumeOut(ORM):
    id: uuid.UUID
    index: int
    title: str
    summary: str
    goal: str
    status: str
    units: list[UnitOut]


class VolumePatch(BaseModel):
    title: str | None = None
    summary: str | None = None
    goal: str | None = None


class OutlineOut(BaseModel):
    concept: dict
    volumes: list[VolumeOut]


# ---------- 设定库 ----------


class CharacterBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = []
    role_type: str = "配角"
    gender: str = ""
    age: str = ""
    appearance: str = ""
    personality: str = ""
    background: str = ""
    abilities: str = ""
    goal: str = ""
    location: str = ""
    condition: str = ""
    secrets: list[str] = []
    notes: str = ""
    is_alive: bool = True


class CharacterOut(CharacterBase, ORM):
    id: uuid.UUID
    first_appearance_chapter: int | None


class CharacterPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    aliases: list[str] | None = None
    role_type: str | None = None
    gender: str | None = None
    age: str | None = None
    appearance: str | None = None
    personality: str | None = None
    background: str | None = None
    abilities: str | None = None
    goal: str | None = None
    location: str | None = None
    condition: str | None = None
    secrets: list[str] | None = None
    notes: str | None = None
    is_alive: bool | None = None


class WorldEntryBase(BaseModel):
    category: str = "其他"
    name: str = Field(min_length=1, max_length=100)
    content: str = ""


class WorldEntryOut(WorldEntryBase, ORM):
    id: uuid.UUID


class WorldEntryPatch(BaseModel):
    category: str | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    content: str | None = None


class RelationshipIn(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: str = Field(min_length=1, max_length=50)
    description: str = ""


class RelationshipOut(ORM):
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: str
    description: str


class RelationshipPatch(BaseModel):
    kind: str | None = Field(None, min_length=1, max_length=50)
    description: str | None = None


class ForeshadowingBase(BaseModel):
    description: str = Field(min_length=1)
    plant_plan: str = ""
    payoff_plan: str = ""
    status: Literal["planned", "planted", "resolved", "abandoned"] = "planned"


class ForeshadowingOut(ForeshadowingBase, ORM):
    id: uuid.UUID
    planted_chapter: int | None
    resolved_chapter: int | None


class ForeshadowingPatch(BaseModel):
    description: str | None = Field(None, min_length=1)
    plant_plan: str | None = None
    payoff_plan: str | None = None
    status: Literal["planned", "planted", "resolved", "abandoned"] | None = None


class BibleOut(BaseModel):
    characters: list[CharacterOut]
    relationships: list[RelationshipOut]
    world_entries: list[WorldEntryOut]
    foreshadowings: list[ForeshadowingOut]


# ---------- 任务与会议室 ----------


class Decision(BaseModel):
    action: Literal["approve", "revise"]
    feedback: str = Field("", max_length=5000)


class MeetingMessageOut(BaseModel):
    id: int
    book_id: str
    job_id: str | None
    speaker: str
    speaker_name: str
    kind: str
    content: str
    payload: dict | None
    created_at: str | None


class UsageOut(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    by_role: dict[str, dict[str, int]]
