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


class ModelListIn(BaseModel):
    base_url: str
    api_key: str = ""
    profile_id: uuid.UUID | None = None


class ModelListOut(BaseModel):
    models: list[str]


# ---------- 书 ----------


class BookCreate(BaseModel):
    idea: str = Field(min_length=4, max_length=5000)
    style_reference: str = Field("", max_length=20000)
    # 动笔前让主编先问几个关键问题（篇幅、主角、金手指、结局……）
    ask: bool = False


class BookPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    style_reference: str | None = Field(None, max_length=20000)
    concept: dict | None = None
    spine: dict | None = None


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
    # 最近一个任务的状态，用来区分「工作中」和「出错了」
    job_status: str | None = None
    created_at: datetime
    updated_at: datetime


class BookDetail(BookSummary):
    style_reference: str
    concept: dict
    spine: dict
    requirements: list[str] = []
    trial_read_done: bool = False
    active_job: JobOut | None = None
    # 写作进度：已定稿章数、总字数
    chapters_final: int = 0
    words_final: int = 0


class BookCreated(BaseModel):
    book: BookDetail
    job: JobOut


# ---------- 大纲 ----------


class ThreadStepOut(BaseModel):
    thread: str = ""
    beat: str = ""


class ForeshadowStepOut(BaseModel):
    ref: str = ""
    action: str = ""
    detail: str = ""


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
    thread_beats: list[ThreadStepOut] = []
    foreshadow_actions: list[ForeshadowStepOut] = []
    status: str = "planned"


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
    stage: str = ""
    summary: str
    goal: str
    climax: str = ""
    antagonist: str = ""
    power_range: str = ""
    thread_beats: list[ThreadStepOut] = []
    new_characters: list[str] = []
    chapter_count: int
    status: str
    units: list[UnitOut]


class VolumePatch(BaseModel):
    title: str | None = None
    stage: str | None = None
    summary: str | None = None
    goal: str | None = None
    climax: str | None = None
    antagonist: str | None = None
    power_range: str | None = None
    new_characters: list[str] | None = None
    chapter_count: int | None = Field(None, ge=0, le=1000)


class OutlineOut(BaseModel):
    concept: dict
    volumes: list[VolumeOut]


class ThreadBeatOut(BaseModel):
    volume: int = 1
    beat: str = ""


class ThreadOut(ORM):
    id: uuid.UUID
    index: int
    name: str
    kind: str
    summary: str
    characters: list[str]
    beats: list[ThreadBeatOut]


class ThreadPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    summary: str | None = None
    characters: list[str] | None = None
    beats: list[ThreadBeatOut] | None = None


# ---------- 章节 ----------


class ChapterBrief(ORM):
    id: uuid.UUID
    index: int
    title: str
    volume_id: uuid.UUID | None
    unit_id: uuid.UUID | None
    status: str
    word_count: int
    summary: str
    attempts: int
    outline: dict | None = None


class ChapterOut(ChapterBrief):
    content: str
    review: dict
    updated_at: datetime


class ChapterPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = None


class WriteRequest(BaseModel):
    # count：写够 count 章；volume：写完当前这一卷；book：一直写到完本（中间遇到卷纲拍板会停下等你）
    until: Literal["count", "volume", "book"] = "count"
    count: int = Field(3, ge=1, le=500)


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
    span: Literal["短", "中", "长"] = "中"
    plant_plan: str = ""
    payoff_plan: str = ""
    plant_volume: int | None = Field(None, ge=1)
    payoff_volume: int | None = Field(None, ge=1)
    status: Literal["planned", "planted", "resolved", "abandoned"] = "planned"


class ForeshadowingOut(ForeshadowingBase, ORM):
    id: uuid.UUID
    seq: int
    planted_chapter: int | None
    resolved_chapter: int | None
    hint_chapters: list[int] = []


class ForeshadowingPatch(BaseModel):
    description: str | None = Field(None, min_length=1)
    span: Literal["短", "中", "长"] | None = None
    plant_plan: str | None = None
    payoff_plan: str | None = None
    plant_volume: int | None = Field(None, ge=1)
    payoff_volume: int | None = Field(None, ge=1)
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


class Answer(BaseModel):
    # 对应提问的序号；answer 为空表示交给编辑部决定
    index: int = Field(ge=0)
    answer: str = Field("", max_length=500)


class Answers(BaseModel):
    answers: list[Answer] = Field(default_factory=list, max_length=20)
    extra: str = Field("", max_length=5000)


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


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
