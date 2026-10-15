"""接口的请求与响应模型。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator


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
    structured_method_auto: bool = False
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
    mode: Literal["puzzle", "oneshot"] | None = None


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
    setup_progress: dict = {}
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
    tropes: list[str] = []
    resolution: str = ""
    status: str = "planned"
    recap: str = ""
    reveals: list[dict] = []
    editor_note: str = ""
    techniques: list[str] = []
    plan_issues: list[str] = []


class UnitPatch(BaseModel):
    title: str | None = None
    chapter_count: int | None = Field(None, ge=1, le=50)
    goal: str | None = None
    conflict: str | None = None
    climax: str | None = None
    outcome: str | None = None
    key_events: list[str] | None = None
    reveals: list[dict] | None = None
    editor_note: str | None = None
    techniques: list[str] | None = None

    @field_validator("reveals", "editor_note", "techniques")
    @classmethod
    def annotations_not_null(cls, value):
        if value is None:
            raise ValueError("揭晓、编辑批注和技巧不能为空值")
        return value


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
    recap: str = ""
    units: list[UnitOut]
    target_node_id: uuid.UUID | None = None
    reaches_node: bool = False
    editor_note: str = ""
    techniques: list[str] = []


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
    target_node_id: uuid.UUID | None = None
    reaches_node: bool | None = None
    editor_note: str | None = None
    techniques: list[str] | None = None

    @field_validator("reaches_node", "editor_note", "techniques")
    @classmethod
    def annotations_not_null(cls, value):
        if value is None:
            raise ValueError("节点进度、编辑批注和技巧不能为空值")
        return value


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
    materials: dict = {}
    updated_at: datetime


class ChapterPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    content: str | None = None


class RewriteRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=4000)
    # 后面还有已定稿的章节时，作者要确认知道「后面的章节不会跟着改」
    confirm: bool = False


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
    kind: Literal["伏笔", "期待"] = "伏笔"
    node_id: uuid.UUID | None = None
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

    @computed_field
    @property
    def code(self) -> str:
        return f"{'E' if self.kind == '期待' else 'F'}{self.seq}"


class ForeshadowingPatch(BaseModel):
    kind: Literal["伏笔", "期待"] | None = None
    node_id: uuid.UUID | None = None
    description: str | None = Field(None, min_length=1)
    span: Literal["短", "中", "长"] | None = None
    plant_plan: str | None = None
    payoff_plan: str | None = None
    plant_volume: int | None = Field(None, ge=1)
    payoff_volume: int | None = Field(None, ge=1)
    status: Literal["planned", "planted", "resolved", "abandoned"] | None = None

    @field_validator("kind")
    @classmethod
    def kind_not_null(cls, value):
        if value is None:
            raise ValueError("台账类型不能为空")
        return value


# ---------- 关键节点、人物锚点与信息差 ----------


NodeStatus = Literal["pinned", "pencil", "empty"]
AnchorKind = Literal["登场", "确认关系", "翻脸", "高光", "退场", "其他"]
ReaderKnowledge = Literal["知道", "不知道", "部分"]


class NodeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    event: str = ""
    prerequisite: str = ""
    consequence: str = ""
    volume: int | None = Field(None, ge=1)
    status: NodeStatus = "pinned"
    after_node_id: uuid.UUID | None = None


class NodePatch(BaseModel):
    title: str | None = Field(None, max_length=100)
    event: str | None = None
    prerequisite: str | None = None
    consequence: str | None = None
    volume: int | None = Field(None, ge=1)
    status: NodeStatus | None = None
    editor_note: str | None = None

    @field_validator("title", "event", "prerequisite", "consequence", "status", "editor_note")
    @classmethod
    def text_not_null(cls, value):
        if value is None:
            raise ValueError("节点文字和状态不能为空值")
        return value


class NodeOrder(BaseModel):
    ids: list[uuid.UUID]


class AnchorCreate(BaseModel):
    node_id: uuid.UUID
    character_id: uuid.UUID
    kind: AnchorKind
    note: str = ""


class AnchorPatch(BaseModel):
    node_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    kind: AnchorKind | None = None
    note: str | None = None

    @field_validator("node_id", "character_id", "kind", "note")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("锚点字段不能为空值")
        return value


class AnchorOut(AnchorCreate, ORM):
    id: uuid.UUID
    character_name: str = ""


class NodeOut(ORM):
    id: uuid.UUID
    index: int = Field(validation_alias=AliasChoices("index", "position"))
    kind: Literal["opening", "milestone", "ending"]
    title: str
    event: str
    prerequisite: str
    consequence: str
    volume: int | None
    status: NodeStatus
    origin: Literal["ai", "author"]
    editor_note: str
    techniques: list[str]
    anchors: list[AnchorOut] = []


class Knower(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    since_chapter: int | None = Field(None, ge=1)
    how: str = ""


class SecretCreate(BaseModel):
    title: str = Field("", max_length=100)
    truth: str = ""
    knowers: list[Knower] = []
    reader_knows: ReaderKnowledge | None = None
    reveal_plan: str = ""
    node_id: uuid.UUID | None = None
    status: Literal["hidden", "public"] = "hidden"


class SecretPatch(BaseModel):
    title: str | None = Field(None, max_length=100)
    truth: str | None = None
    knowers: list[Knower] | None = None
    reader_knows: ReaderKnowledge | None = None
    reveal_plan: str | None = None
    node_id: uuid.UUID | None = None
    status: Literal["hidden", "public"] | None = None

    @field_validator("title", "truth", "knowers", "reveal_plan", "status")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("信息差文字、知情人和状态不能为空值")
        return value


class SecretOut(SecretCreate, ORM):
    id: uuid.UUID
    seq: int
    created_chapter: int | None = None

    @computed_field
    @property
    def code(self) -> str:
        return f"S{self.seq}"


class BibleOut(BaseModel):
    characters: list[CharacterOut]
    relationships: list[RelationshipOut]
    world_entries: list[WorldEntryOut]
    foreshadowings: list[ForeshadowingOut]
    secrets: list[SecretOut] = []


# ---------- 任务与会议室 ----------


class Decision(BaseModel):
    action: Literal["approve", "revise"]
    feedback: str = Field("", max_length=5000)


SetupPiece = Literal["concept", "nodes", "cast", "fill", "first_volume"]


class DirectionDecision(BaseModel):
    action: Literal["choose", "redo"]
    choice: int | None = Field(None, ge=0)
    mix: str = Field("", max_length=20000)
    length: str = Field("", max_length=1000)
    feedback: str = Field("", max_length=20000)


class ChoiceFlip(BaseModel):
    topic: str = Field(min_length=1, max_length=100)
    choice: str = Field(min_length=1, max_length=1000)

    @field_validator("topic", "choice")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("决定和选项不能为空")
        return value.strip()


class PieceDecision(BaseModel):
    action: Literal["confirm", "delegate", "revise", "candidates", "fill", "reopen", "unlock"]
    piece: SetupPiece
    feedback: str = Field("", max_length=20000)
    node_id: uuid.UUID | None = None
    flips: list[ChoiceFlip] = Field(default_factory=list, max_length=3)


class Answer(BaseModel):
    # 对应提问的序号；answer 为空表示交给编辑部决定
    index: int = Field(ge=0)
    answer: str = Field("", max_length=500)


class Answers(BaseModel):
    answers: list[Answer] = Field(default_factory=list, max_length=20)
    extra: str = Field("", max_length=5000)


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    to: Literal["chief", "lorekeeper", "writer", "reviewer"] | None = None


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
    prompt_tokens: int | None
    completion_tokens: int | None
    by_role: dict[str, dict[str, int | None]]
