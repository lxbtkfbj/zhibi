"""编辑部各角色的结构化产出。字段描述会随 schema 发给模型，因此用中文写清楚。"""

import contextlib
import json
import re
from typing import Any, Literal, get_origin

from pydantic import BaseModel, Field, field_validator, model_validator


class Lenient(BaseModel):
    """模型有时会把列表或对象写成 JSON 字符串（"[...]"），这里先还原再校验。"""

    @model_validator(mode="before")
    @classmethod
    def _decode_json_strings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fixed = dict(data)
        for name, field in cls.model_fields.items():
            value = fixed.get(name)
            if not (isinstance(value, str) and value.strip()[:1] in ("[", "{")):
                continue
            annotation = field.annotation
            wants_container = get_origin(annotation) in (list, dict) or (
                isinstance(annotation, type) and issubclass(annotation, BaseModel)
            )
            if wants_container:
                with contextlib.suppress(ValueError):
                    fixed[name] = json.loads(value)
        return fixed


def remark_field(focus: str = "") -> Any:
    extra = f"重点说清{focus}。" if focus else ""
    return Field(
        description=f"你在编辑部会议上的发言：用第一人称、口语化地说明你做了什么、为什么这样做。{extra}1-4 句话"
    )


class BookConcept(Lenient):
    title: str = Field(description="书名本身（不带书名号、不带备选），网文风格，好记、有画面感")
    alt_titles: list[str] = Field(default_factory=list, description="2-3 个备选书名")
    genre: str = Field(description="类型，如「玄幻·修仙」「都市·重生」")
    tags: list[str] = Field(default_factory=list, description="3-6 个标签")
    logline: str = Field(description="一句话简介，50 字以内，点出主角、核心冲突与看点")
    selling_points: list[str] = Field(description="3-5 个核心卖点 / 爽点，要具体，不要空话")
    protagonist_hook: str = Field(description="主角最独特、最吸引读者的地方")
    tone: str = Field(description="基调与文风，如「轻松幽默，节奏快」")
    target_length: int = Field(
        default=100,
        ge=5,
        le=1000,
        description="全书计划总字数，单位：万字（200 万字就填 200）。以作者要求为准；作者没说时按类型的主流长度",
    )
    target_volumes: int = Field(ge=1, le=20, description="计划分几卷：按篇幅定，每卷通常 25-60 万字")
    chapter_words: int = Field(ge=1000, le=8000, description="每章目标字数，通常 2000-4000")
    remark: str = remark_field("书名、核心卖点和篇幅为什么这样定")

    @field_validator("target_length", mode="before")
    @classmethod
    def _to_wan(cls, value: Any) -> Any:
        """模型偶尔写成「200万」或按字数写成 2000000，统一换算成万字。"""
        if isinstance(value, str):
            match = re.search(r"\d+(\.\d+)?", value.replace(",", ""))
            if not match:
                return value
            value = float(match.group())
        if isinstance(value, int | float) and value > 1000:
            value = value / 10000
        return round(value) if isinstance(value, float) else value


class WorldEntryDraft(Lenient):
    category: Literal["地理", "势力", "力量体系", "历史", "物品", "规则", "其他"] = Field(description="条目类别")
    name: str = Field(description="条目名称")
    content: str = Field(description="具体设定，写清规则、限制与代价，100-300 字")


class CharacterDraft(Lenient):
    name: str = Field(description="姓名")
    role_type: Literal["主角", "女主", "男主", "配角", "反派", "龙套"] = Field(description="角色定位")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄或年龄段")
    appearance: str = Field(default="", description="外貌，突出 1-2 个记忆点")
    personality: str = Field(description="性格，写出矛盾面和说话方式")
    background: str = Field(description="出身与过往经历")
    abilities: str = Field(default="", description="能力、修为、技能或资源")
    goal: str = Field(description="此人最想要什么")
    location: str = Field(default="", description="故事开始时所在的位置")
    condition: str = Field(default="", description="故事开始时的状态，如伤势、处境")
    secrets: list[str] = Field(default_factory=list, description="此人隐藏的秘密或掌握的关键信息")


class RelationshipDraft(Lenient):
    source: str = Field(description="人物 A 的姓名（必须是人物列表里的人）")
    target: str = Field(description="人物 B 的姓名（必须是人物列表里的人）")
    kind: str = Field(description="关系类型，如 师徒、宿敌、青梅竹马")
    description: str = Field(default="", description="关系的具体情况与张力")


class LoreDraft(Lenient):
    world_entries: list[WorldEntryDraft] = Field(description="世界观条目，6-12 条，必须包含力量体系或核心规则")
    characters: list[CharacterDraft] = Field(description="主要人物，5-10 人，至少包含主角和一个主要反派")
    relationships: list[RelationshipDraft] = Field(default_factory=list, description="人物之间的重要关系")
    remark: str = remark_field("主角叫什么、金手指或核心能力是什么、主要反派是谁，方便作者随时插话调整")


class Milestone(Lenient):
    index: int = Field(ge=1, description="节点序号，从 1 开始，按时间顺序")
    title: str = Field(description="节点名称，4-10 字")
    volume: int = Field(ge=1, description="大约发生在第几卷")
    event: str = Field(description="这个节点发生了什么，50-120 字")
    change: str = Field(description="这之后主角或局势发生了什么不可逆的变化")


class StorySpine(Lenient):
    """主线骨架：先定开头和结局，再定中间的关键转折，分卷大纲在骨架上展开。"""

    core_conflict: str = Field(description="贯穿全书的核心矛盾：主角想要什么、最大的阻碍是什么")
    theme: str = Field(description="这本书最终想表达什么，一句话")
    protagonist_arc: str = Field(description="主角的成长弧线：从什么样的人，经历什么，变成什么样的人")
    opening: str = Field(description="开篇：故事从什么时间、地点、处境切入，前 3 章抛出的核心钩子是什么，100-200 字")
    ending: str = Field(
        description="结局：最终高潮怎么打、主线如何收束、主角最终得到和失去了什么、主要伏笔如何回收，150-300 字"
    )
    milestones: list[Milestone] = Field(
        description="从开篇到结局之间的全书关键转折，6-12 个，按顺序排列，均匀分布到各卷；最后一个是最终高潮"
    )
    remark: str = remark_field("结局是什么、中间最关键的一两个转折是什么")


class VolumeDraft(Lenient):
    index: int = Field(ge=1, description="卷序号，从 1 开始")
    title: str = Field(description="卷名本身，不要带「第几卷」")
    summary: str = Field(description="本卷剧情概要，150-300 字")
    goal: str = Field(description="本卷结束时主角达成或失去了什么")
    chapter_count: int = Field(default=0, ge=0, le=1000, description="本卷预计章数，各卷之和等于全书计划总章数")


class PlotUnitDraft(Lenient):
    index: int = Field(ge=1, description="剧情单元序号，从 1 开始")
    title: str = Field(description="单元标题")
    chapter_count: int = Field(ge=3, le=40, description="预计章数，通常 5-20")
    goal: str = Field(description="这一段主角要做成什么")
    conflict: str = Field(description="阻碍与冲突来自哪里")
    climax: str = Field(description="高潮场面")
    outcome: str = Field(description="结果，以及给下一段留下的钩子")
    key_events: list[str] = Field(description="按顺序列出 3-6 个关键事件")


class ForeshadowingDraft(Lenient):
    description: str = Field(description="伏笔内容")
    plant_plan: str = Field(description="计划在哪里、以什么方式埋下")
    payoff_plan: str = Field(description="计划在哪里回收，回收时的效果")


class OutlineDraft(Lenient):
    volumes: list[VolumeDraft] = Field(description="全书分卷概要，卷数与概念里的计划卷数一致")
    first_volume_units: list[PlotUnitDraft] = Field(
        description="第一卷拆成的剧情单元，4-12 个，章数之和等于第一卷的预计章数"
    )
    foreshadowings: list[ForeshadowingDraft] = Field(default_factory=list, description="全书重要伏笔，3-8 条")
    remark: str = remark_field("全书多少章、第一卷怎么拆、开篇钩子在哪")


SetupTarget = Literal["concept", "lore", "spine", "outline"]


class ReviewIssue(Lenient):
    target: SetupTarget = Field(
        description="问题出在哪部分：concept 概念 / lore 设定与人物 / spine 主线骨架（开篇、结局、关键转折）/ outline 分卷大纲"
    )
    problem: str = Field(description="具体问题，指出原文位置")
    suggestion: str = Field(description="怎么改")
    severity: Literal["high", "medium", "low"] = Field(description="严重程度")


class SetupCritique(Lenient):
    verdict: Literal["pass", "revise"] = Field(description="pass：可以交给作者；revise：有必须修改的问题")
    highlights: list[str] = Field(default_factory=list, description="写得好的地方，1-3 条")
    issues: list[ReviewIssue] = Field(default_factory=list, description="问题清单，按严重程度排序")
    remark: str = remark_field()


class RevisionTriage(Lenient):
    """主编读完意见后，决定改哪些部分、怎么改。"""

    concept_instructions: str = Field(default="", description="对概念的修改要求；不需要改则留空")
    lore_instructions: str = Field(default="", description="对设定与人物的修改要求；不需要改则留空")
    spine_instructions: str = Field(
        default="", description="对主线骨架（开篇、结局、关键转折）的修改要求；不需要改则留空"
    )
    outline_instructions: str = Field(default="", description="对分卷大纲的修改要求；不需要改则留空")
    remark: str = remark_field("你打算怎么落实作者的话")

    def instructions(self) -> dict[str, str]:
        found = {t: getattr(self, f"{t}_instructions", "") for t in ("concept", "lore", "spine", "outline")}
        return {t: text for t, text in found.items() if text.strip()}


class InterviewQuestion(Lenient):
    question: str = Field(description="问作者的问题，口语化，一句话，不用专业术语")
    options: list[str] = Field(description="2-4 个具体可选的答案，每个 20 字以内，作者点一下就能选")
    recommended: int = Field(default=0, ge=0, description="你推荐的选项序号（从 0 开始）")


class InterviewDraft(Lenient):
    """动笔前主编先问作者几个关键问题。"""

    questions: list[InterviewQuestion] = Field(description="3-5 个问题，只问作者点子里没交代、又会大幅影响整本书的事")
    remark: str = remark_field("为什么要先问这几件事")
