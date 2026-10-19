"""接口的请求与响应模型。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.api.segment_models import ProtagonistPatch, SegmentPatch, WorldPatch


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
    # 群聊里编辑部能不能用它自己查资料、动手：True 能、False 不能、None 不适用（演示模式、连不上）
    tools: bool | None = None
    tools_message: str = ""


class ModelListIn(BaseModel):
    base_url: str
    api_key: str = ""
    profile_id: uuid.UUID | None = None


class ModelListOut(BaseModel):
    models: list[str]


# ---------- 书 ----------


def clean_tag_list(value: list[str]) -> list[str]:
    tags = [tag.strip() for tag in value if tag.strip()]
    if any(len(tag) > 20 for tag in tags):
        raise ValueError("每个标签不超过 20 个字")
    return list(dict.fromkeys(tags))


class BookCreate(BaseModel):
    prefill: bool = False
    idea: str = Field("", max_length=5000)
    style_reference: str = Field("", max_length=20000)
    # 动笔前让主编先问几个关键问题（篇幅、主角、金手指、结局……）
    ask: bool = False
    mode: Literal["puzzle", "oneshot"] | None = None
    # 新建页：false 时只建书、存作者填的内容，编辑部不开工
    start_setup: bool = True
    title: str = Field("", max_length=200)
    blurb: str = Field("", max_length=5000)
    channel: Literal["男频", "女频", ""] = ""
    genre: str = Field("", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # 单位万字
    target_length: int | None = Field(None, ge=1, le=5000)

    @field_validator("title", "blurb", "genre")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return clean_tag_list(value)

    @model_validator(mode="after")
    def idea_needed_to_start(self) -> "BookCreate":
        if self.start_setup and len(self.idea.strip()) < 4:
            raise ValueError("点子至少写 4 个字")
        return self


class BookDraftFields(BaseModel):
    """新建页上的几项：编辑部起草或按意见改，都只在页面上，作者点下一步才建书。"""

    title: str = Field("", max_length=200)
    blurb: str = Field("", max_length=5000)
    channel: Literal["男频", "女频", ""] = ""
    genre: str = Field("", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    target_length: int | None = Field(None, ge=1, le=5000)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        return clean_tag_list(value)


class BookDraftOut(BookDraftFields):
    # 编辑部说的一句话：这版的思路，或这次改了哪里
    reply: str = ""


class BookDraftIn(BaseModel):
    idea: str = Field("", max_length=5000)
    # 按意见改时带上页面上现在的样子
    current: BookDraftFields | None = None
    feedback: str = Field("", max_length=2000)

    @model_validator(mode="after")
    def has_something(self) -> "BookDraftIn":
        if self.feedback.strip() and self.current is None:
            raise ValueError("按意见改要带上现在的内容")
        if not self.feedback.strip() and len(self.idea.strip()) < 2:
            raise ValueError("先写一句点子")
        return self


class BookPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    style_reference: str | None = Field(None, max_length=20000)
    concept: dict | None = None
    spine: dict | None = None
    protagonist: ProtagonistPatch | None = None
    world: WorldPatch | None = None
    # 改了简介要不要让编辑部顺带查设定库；新工作台不叫编辑部就不查
    review_changes: bool = True

    @field_validator("protagonist", "world")
    @classmethod
    def cards_not_null(cls, value):
        if value is None:
            raise ValueError("主角卡和世界与地图不能为空值")
        return value


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
    setup_flow: int | None = None

    @model_validator(mode="before")
    @classmethod
    def read_setup_flow(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            values = dict(value)
            params = values.get("params") or {}
            flow = values.get("setup_flow", params.get("flow", 1))
        else:
            values = {name: getattr(value, name) for name in cls.model_fields if name != "setup_flow"}
            flow = (getattr(value, "params", None) or {}).get("flow", 1)
        values["setup_flow"] = flow if values.get("kind") == "book_setup" else None
        return values


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
    protagonist: dict = {}
    world: dict = {}
    setup_progress: dict = {}
    requirements: list[str] = []
    trial_read_done: bool = False
    card_layouts: dict = {}
    active_job: JobOut | None = None
    # 写作进度：已定稿章数、总字数
    chapters_final: int = 0
    words_final: int = 0
    # 实际按每章多少字写：本书设置填了用它，没填用新建时记进定调的，都没有按 3000
    chapter_words: int = 0


class BookCreated(BaseModel):
    book: BookDetail
    # 新建页建的书编辑部不开工，没有任务
    job: JobOut | None = None


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
    summary: str = ""
    locked: bool = False
    chapter_count: int
    goal: str
    conflict: str
    climax: str
    outcome: str
    loop: str = ""
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
    summary: str | None = None
    locked: bool | None = None
    # 0 表示还没定：有几章算几章，写到这里编辑部再按剧情定
    chapter_count: int | None = Field(None, ge=0, le=50)
    goal: str | None = None
    conflict: str | None = None
    climax: str | None = None
    outcome: str | None = None
    loop: str | None = None
    key_events: list[str] | None = None
    reveals: list[dict] | None = None
    editor_note: str | None = None
    techniques: list[str] | None = None

    @field_validator("loop", "summary", "locked")
    @classmethod
    def loop_not_null(cls, value):
        if value is None:
            raise ValueError("核心循环不能为空值")
        return value

    @field_validator("reveals", "editor_note", "techniques")
    @classmethod
    def annotations_not_null(cls, value):
        if value is None:
            raise ValueError("揭晓、编辑批注和技巧不能为空值")
        return value


class UnitCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    summary: str = ""
    # 新建的单元章数先不定（0）：有几章算几章，写到这里编辑部再按剧情定
    chapter_count: int = Field(0, ge=0, le=50)
    after_unit_id: uuid.UUID | None = None


class UnitOrder(BaseModel):
    ids: list[uuid.UUID]


class VolumeCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    summary: str = ""
    # 新建的卷章数先不定（0）：拆单元时编辑部按剧情定
    chapter_count: int = Field(0, ge=0, le=1000)
    target_node_id: uuid.UUID | None = None
    after_volume_id: uuid.UUID | None = None


class VolumeOut(ORM):
    id: uuid.UUID
    index: int
    title: str
    want: str = ""
    pressure: str = ""
    stage: str = ""
    summary: str
    locked: bool = False
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
    want: str | None = None
    pressure: str | None = None
    stage: str | None = None
    summary: str | None = None
    locked: bool | None = None
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

    @field_validator("want", "pressure", "locked")
    @classmethod
    def segment_fields_not_null(cls, value):
        if value is None:
            raise ValueError("这一卷想做成什么和卷首处境不能为空值")
        return value

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
    # 设定师记下的变化：原样不给前端，给的是下面整理好的一行行
    bible_changes: dict | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def changes(self) -> list[str]:
        """这一章写完设定师记下的变化（新书页正文末尾那一块）。"""
        from app.services.writing_store import changes_text

        return changes_text(self.bible_changes)


class ChapterOutlineIn(BaseModel):
    """作者在新书页改的章纲：发生什么（第一行是目标，下面每行一个场景）、看点、结尾钩子。"""

    goal: str | None = Field(None, max_length=2000)
    scenes: list[str] | None = Field(None, max_length=20)
    cool_point: str | None = Field(None, max_length=2000)
    hook: str | None = Field(None, max_length=2000)


class ChapterPatch(BaseModel):
    # 空的就是还没起名（新书页上撤销编辑部起的章名时会存回空的）
    title: str | None = Field(None, max_length=200)
    content: str | None = None
    # 只改给出的几项；已经开写的章不能改
    outline: ChapterOutlineIn | None = None


class ChapterCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    outline: ChapterOutlineIn = Field(default_factory=ChapterOutlineIn)
    # 插在哪：这一章之前或之后（同一个单元里的章号）；都不给就接在单元最后
    before_index: int | None = None
    after_index: int | None = None


class OutlineWriteIn(BaseModel):
    """让编辑部把大纲上的这一段写出来：全书结局、篇、卷、单元、章。"""

    target_type: Literal["book", "segment", "volume", "unit", "chapter"]
    target_id: str = Field(max_length=64)
    request: str = Field(default="", max_length=1000)


class OutlineRestoreIn(BaseModel):
    """撤销编辑部帮写的那一段：把改之前的样子存回去。"""

    target_type: Literal["book", "segment", "volume", "unit", "chapter"]
    target_id: str = Field(max_length=64)
    before: dict


class SplitIn(BaseModel):
    """编辑部帮拆：单元出章纲、卷拆成单元。只出一版给作者看，不存。current 是上一版（再出一版时带上）。"""

    target_type: Literal["unit", "volume"]
    target_id: str = Field(max_length=64)
    request: str = Field(default="", max_length=1000)
    current: list[dict] | None = Field(default=None, max_length=60)


class SplitAcceptIn(BaseModel):
    """收下帮拆的这一版：drafts 是作者改过、删过以后留下的那几条（带着模型原来给的全部字段）；拆卷时 plan 是整份卷纲。"""

    target_type: Literal["unit", "volume"]
    target_id: str = Field(max_length=64)
    drafts: list[dict] = Field(min_length=1, max_length=60)
    plan: dict | None = None


class SplitUndoIn(BaseModel):
    """撤销刚收下的那一版：undo 是收下时带回来的。"""

    target_type: Literal["unit", "volume"]
    target_id: str = Field(max_length=64)
    undo: dict


class FillRequest(BaseModel):
    """让编辑部把一条设定空着的栏目补上。"""

    target_type: Literal["character", "entry"]
    target_id: uuid.UUID
    request: str = Field(default="", max_length=1000)


class ArcCreate(BaseModel):
    title: str = Field(default="", max_length=100)
    text: str = Field(default="", max_length=4000)
    # 插在哪一篇前面或后面（节点编号）；都不给就接在已定的篇后面
    before_node_id: uuid.UUID | None = None
    after_node_id: uuid.UUID | None = None


class OutlineMove(BaseModel):
    """大纲里一个篇、卷、单元或章往前或往后挪一格。"""

    kind: Literal["arc", "volume", "unit", "chapter"]
    # 篇是节点编号，卷和单元是它们的编号，章是章号
    id: str = Field(min_length=1, max_length=60)
    direction: Literal["up", "down"]


class RewriteRequest(BaseModel):
    feedback: str = Field(min_length=1, max_length=4000)
    # 后面还有已定稿的章节时，作者要确认知道「后面的章节不会跟着改」
    confirm: bool = False


class WriteRequest(BaseModel):
    # count：写够 count 章；unit：写完眼下这个单元；volume：写完当前这一卷；book：一直写到完本（中间遇到卷纲拍板会停下等你）
    until: Literal["count", "unit", "volume", "book"] = "count"
    count: int = Field(3, ge=1, le=500)


# ---------- 设定库 ----------


SettingStatus = Literal["must", "one", "later"]
SettingStyle = Literal["card", "ladder", "paragraph"]


class SettingField(BaseModel):
    name: str = Field(min_length=1)
    value: str = ""


class SettingLevel(BaseModel):
    name: str = ""
    text: str = ""


def clean_extra(value: dict[str, str] | None, keep_empty: bool = False) -> dict[str, str] | None:
    """栏目名去空白、不超过 20 字；内容去首尾空白。"""
    if value is None:
        return None
    out: dict[str, str] = {}
    for key, text in value.items():
        name = key.strip()
        if not name or len(name) > 20:
            raise ValueError("栏目名要 1 到 20 个字")
        text = text.strip()
        if text or keep_empty:
            out[name] = text
    return out


class LayoutField(BaseModel):
    key: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=20)


class CardLayoutIn(BaseModel):
    facts: list[LayoutField] = Field(default_factory=list, max_length=30)
    sections: list[LayoutField] = Field(default_factory=list, max_length=30)
    # 删掉的栏目：这一类每一条里写的内容一起清掉
    dropped: list[str] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def unique_labels(self):
        labels = [f.label.strip() for f in [*self.facts, *self.sections]]
        if len(labels) != len(set(labels)):
            raise ValueError("栏目名不能重复")
        return self


class DraftRequest(BaseModel):
    """编辑部帮写：在某一类里写几条候选。栏目照新书页上这一类现在的样子。"""

    category: str = Field(min_length=1, max_length=60)
    request: str = Field(default="", max_length=1000)
    count: int = Field(default=3, ge=1, le=6)
    facts: list[LayoutField] = Field(default_factory=list, max_length=30)
    sections: list[LayoutField] = Field(default_factory=list, max_length=30)


class CharacterBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # 只认「candidate」（从编辑部帮写的候选里收下的），别的一律当作者自己写的
    source: str = "author"
    aliases: list[str] = []
    role_type: str = "配角"
    gender: str = ""
    age: str = ""
    appearance: str = ""
    personality: str = ""
    background: str = ""
    abilities: str = ""
    goal: str = ""
    want: str = ""
    location: str = ""
    condition: str = ""
    notes: str = ""
    is_alive: bool = True
    one_line: str = ""
    relation: str = ""
    status: SettingStatus = "must"
    tags: list[str] = []
    locked: bool = False
    position: int = 0
    # 没有专门一列的栏目，键是栏目名
    extra: dict[str, str] = {}

    @field_validator("extra")
    @classmethod
    def extra_keys(cls, value):
        return clean_extra(value)


class CharacterOut(CharacterBase, ORM):
    id: uuid.UUID
    first_appearance_chapter: int | None
    source: str = "ai"
    # 置顶的时间：有就是置顶了，后置顶的排在上面
    pinned_at: datetime | None = None


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
    want: str | None = None
    location: str | None = None
    condition: str | None = None
    notes: str | None = None
    is_alive: bool | None = None
    one_line: str | None = None
    relation: str | None = None
    status: SettingStatus | None = None
    tags: list[str] | None = None
    locked: bool | None = None
    position: int | None = None
    # 只改给出的几栏，空字符串表示清掉这一栏
    extra: dict[str, str] | None = None

    @field_validator("extra")
    @classmethod
    def extra_keys(cls, value):
        return clean_extra(value, keep_empty=True)

    @field_validator("*")
    @classmethod
    def want_not_null(cls, value):
        if value is None:
            raise ValueError("角色字段不能为空值")
        return value


class WorldEntryBase(BaseModel):
    category: str = "其他"
    name: str = Field(min_length=1, max_length=100)
    source: str = "author"
    content: str = ""
    style: SettingStyle | None = None
    status: SettingStatus = "must"
    tags: list[str] = []
    one_line: str = ""
    aliases: list[str] = []
    fields: list[SettingField] = []
    levels: list[SettingLevel] = []
    parent_id: uuid.UUID | None = None
    secret_id: uuid.UUID | None = None
    locked: bool = False
    position: int = 0

    @field_validator("style")
    @classmethod
    def style_not_null(cls, value):
        if value is None:
            raise ValueError("样式不能为空值")
        return value

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value):
        names = [field.name for field in value]
        if len(names) != len(set(names)):
            raise ValueError("卡片字段名不能重复")
        return value


class WorldEntryOut(WorldEntryBase, ORM):
    id: uuid.UUID
    style: SettingStyle = "paragraph"
    source: str = "ai"
    created_chapter: int | None = None


class WorldEntryPatch(BaseModel):
    category: str | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    content: str | None = None
    style: SettingStyle | None = None
    status: SettingStatus | None = None
    tags: list[str] | None = None
    one_line: str | None = None
    aliases: list[str] | None = None
    fields: list[SettingField] | None = None
    levels: list[SettingLevel] | None = None
    parent_id: uuid.UUID | None = None
    secret_id: uuid.UUID | None = None
    locked: bool | None = None
    position: int | None = None
    # 只改给出的几栏（按栏目名合进 fields），空字符串表示清掉这一栏
    field_values: dict[str, str] | None = None

    @field_validator("field_values")
    @classmethod
    def field_value_keys(cls, value):
        return clean_extra(value, keep_empty=True)

    @field_validator("*")
    @classmethod
    def not_null(cls, value, info):
        if value is None and info.field_name not in {"parent_id", "secret_id"}:
            raise ValueError("设定字段不能为空值")
        return value

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value):
        names = [field.name for field in value]
        if len(names) != len(set(names)):
            raise ValueError("卡片字段名不能重复")
        return value


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
    segment: SegmentPatch | None = None

    @field_validator("segment")
    @classmethod
    def segment_not_null(cls, value):
        if value is None:
            raise ValueError("段规划不能为空值")
        return value

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
    updated_by_volume: int | None = None
    editor_note: str
    techniques: list[str]
    anchors: list[AnchorOut] = []
    segment: dict | None = None


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


SetupPiece = Literal["concept", "settings", "outline"]


class PitchDecision(BaseModel):
    action: Literal["pick", "redo", "start", "fill"]
    index: int | None = Field(None, ge=1, le=3)
    length: Literal[50, 100, 200, 300, 500] | None = None
    title: str | None = Field(None, min_length=1, max_length=200)
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
    action: Literal["confirm", "delegate", "revise"]
    piece: SetupPiece | None = None
    feedback: str = Field("", max_length=20000)
    flips: list[ChoiceFlip] = Field(default_factory=list, max_length=3)


class SegmentDecision(BaseModel):
    action: Literal["confirm", "delegate", "revise", "redo"]
    feedback: str | None = Field("", max_length=20000)
    flips: list[ChoiceFlip] = Field(default_factory=list, max_length=6)
    pin_end: bool = False


class Answer(BaseModel):
    # 对应提问的序号；answer 为空表示交给编辑部决定
    index: int = Field(ge=0)
    answer: str = Field("", max_length=500)


class Answers(BaseModel):
    answers: list[Answer] = Field(default_factory=list, max_length=20)
    extra: str = Field("", max_length=5000)


class ChatQuote(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    where: str = Field(min_length=1, max_length=300)


class ChatViewing(BaseModel):
    """作者发话时正在看的那一页（新书页上带）：群聊里说「帮我写这一篇」就按它来。"""

    target_type: Literal["book", "segment", "volume", "unit", "chapter", "character", "entry", "concept"]
    target_id: str = Field(max_length=64)
    label: str = Field(default="", max_length=200)


class NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    to: Literal["chief", "lorekeeper", "writer", "reviewer"] | None = None
    # 新书页群聊里打 @ 点的名：这一句由他来答（to 是旧版的私聊）
    ask: Literal["chief", "lorekeeper", "writer", "reviewer"] | None = None
    quote: ChatQuote | None = None
    viewing: ChatViewing | None = None
    # 新书页群聊：发在哪一段对话（不给就是最近聊的那一段）
    conv: str | None = None
    # 从这里重来：这句话（作者的某一句）和后面的聊天收起来，再发这一句
    rewind_from: int | None = None


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
