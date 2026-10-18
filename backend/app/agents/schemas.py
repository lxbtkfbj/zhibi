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


TECHNIQUES_DESC = "用到的技巧名称，只能从【术语表】里选，最多 3 个；没有合适的就留空"
EDITOR_NOTE_DESC = "编辑批注：这里用了什么技巧、想让读者有什么感受，写给不懂写作技巧的作者看，一两句白话，30-80 字"
STAGE_LADDER_DESC = (
    "舞台阶梯：主角活动的大地图一层层扩大，每一层能撑一两卷，有自己的势力格局和强者上限，"
    "如「青石镇 → 天剑宗 → 中州 → 上界」或「老城区 → 整座城市 → 省城 → 全国」；不是一个个副本或案发地点"
)


class AuthorChoice(Lenient):
    topic: str = Field(description="决定了什么，4-10 字，如「感情线」「开局方式」")
    chosen: str = Field(description="编辑部现在的选择，20 字以内")
    alternatives: list[str] = Field(description="作者可以换成的其他选择，1-3 个，每个 20 字以内，彼此有实质差别")
    why: str = Field(description="为什么这样选，一句白话")


def decisions_field() -> Any:
    return Field(
        default_factory=list,
        description="这一步里编辑部替作者做的、作者可能想换的关键决定，最多 3 个；作者已经明确说过的事不要列，没有就留空",
    )


AnchorKind = Literal["登场", "确认关系", "翻脸", "高光", "退场", "其他"]
ReaderKnows = Literal["知道", "不知道", "部分"]


class NodeAnchorDraft(Lenient):
    character: str = Field(description="人物姓名（必须是人物列表里的人）")
    node: int = Field(ge=1, description="挂在第几个节点（关键节点的序号）")
    kind: AnchorKind = Field(description="在这个节点前后：登场 / 确认关系 / 翻脸 / 高光 / 退场 / 其他")
    note: str = Field(default="", description="具体发生什么，20-50 字")


class SecretDraft(Lenient):
    title: str = Field(description="秘密的短名，4-12 字，如「主角的真实修为」")
    truth: str = Field(description="真相是什么，30-80 字")
    knowers: list[str] = Field(
        default_factory=list, description="开书时就知道这件事的人（人物列表里的姓名）；没人知道就留空"
    )
    reader_knows: ReaderKnows = Field(
        description="读者一开始知不知道：知道＝读者看得到、角色看不到，是扮猪吃虎和打脸的燃料；不知道＝悬念，揭开时读者也意外；部分＝读者只知道一角"
    )
    reveal_plan: str = Field(description="计划在什么时候、对谁揭开，揭开后局面怎么变，30-80 字")
    node: int = Field(default=0, ge=0, description="在第几个节点前后揭开；不确定填 0")


NodeKind = Literal["开篇", "节点", "结局"]


class StoryNodeDraft(Lenient):
    ref: int = Field(default=0, ge=0, description="改写已有节点时填它现在的序号；新增的节点填 0")
    kind: NodeKind = Field(description="开篇 / 节点 / 结局：第一个必须是开篇，最后一个必须是结局，其余都是节点")
    title: str = Field(description="节点名称，4-10 字，如「飞升神界」")
    volume: int = Field(ge=1, description="大约发生在第几卷")
    event: str = Field(
        description="发生什么：这件大事本身，具体到人和场面，50-120 字；远景节点和结局只写方向，一两句即可"
    )
    prerequisite: str = Field(
        default="",
        description="之前得先有：要让这件事发生、并让读者觉得合理，前面必须已经具备的实力、关系、仇怨、秘密或局势，30-100 字；开篇可以留空",
    )
    consequence: str = Field(
        description="之后变成：主角和局势发生了哪些回不去的变化（实力、地图、关系、敌人、目标），30-100 字"
    )
    editor_note: str = Field(default="", description=EDITOR_NOTE_DESC)
    techniques: list[str] = Field(default_factory=list, description=TECHNIQUES_DESC)


ThreadKind = Literal["主线", "感情线", "反派线", "谜团线", "成长线", "其他"]


class ThreadBeat(Lenient):
    volume: int = Field(ge=1, description="这一步落在第几卷")
    beat: str = Field(description="这条线在这一卷走到哪一步：发生什么、关系或局势变成什么样，30-80 字")


class ThreadDraft(Lenient):
    name: str = Field(description="线索名称，如「主线：太荒遗孤」「感情线：云霓裳」「反派线：天阳神宗」")
    kind: ThreadKind = Field(description="线索类型")
    characters: list[str] = Field(default_factory=list, description="这条线的核心人物姓名")
    summary: str = Field(description="这条线讲什么、大概往哪收；远处写到再定，50-120 字")
    beats: list[ThreadBeat] = Field(description="这条线的节拍，按卷的顺序排列；不是每卷都要有，但不能长时间断线")


class ThreadStep(Lenient):
    thread: str = Field(description="线索名称（必须是线索列表里的名称）")
    beat: str = Field(description="这个单元让这条线走到哪一步，20-60 字")


class VolumeDraft(Lenient):
    index: int = Field(ge=1, description="卷序号，从 1 开始")
    title: str = Field(description="卷名本身，不要带「第几卷」")
    stage: str = Field(default="", description="本卷的舞台：地图、地点，如「青州 → 万劫谷」")
    summary: str = Field(
        description="这一卷的一段话：这一卷想做成什么（是这一篇目标的哪一步）、卷首处境、卷末的高潮和结果、这一卷的对手和他的谋划、新登场的人；作者在大纲里看到的就是这一段"
    )
    want: str = Field(
        default="", description="这一卷想做成什么：主角这一卷的目标，要具体；说清它是这一篇目标的哪一步，30-60 字"
    )
    goal: str = Field(description="卷末结果：卷末主角得到什么、失去什么、处境怎么变")
    climax: str = Field(default="", description="本卷最大的高潮场面，50-100 字")
    antagonist: str = Field(
        default="", description="这一卷的对手：谁、在谋划什么、先赢主角哪一次；对手要有自己的谋划，不能降智"
    )
    power_range: str = Field(
        default="", description="主角这一卷的成长：实力怎么变（如「炼气三层 → 筑基初期」）、拿到什么、金手指解锁什么"
    )
    new_characters: list[str] = Field(default_factory=list, description="本卷新登场的重要人物，写成「姓名：身份」")
    chapter_count: int = Field(default=0, ge=0, le=1000, description="本卷预计章数（每卷通常 25-60 万字）")
    target_node: int = Field(ge=1, description="本卷走向第几个节点（关键节点的序号）：一般就是这一篇的终点")
    reaches_node: bool = Field(default=False, description="这个节点是不是就发生在本卷（作为本卷高潮或卷末）")
    editor_note: str = Field(default="", description=EDITOR_NOTE_DESC)
    techniques: list[str] = Field(default_factory=list, description=TECHNIQUES_DESC)


ForeshadowSpan = Literal["短", "中", "长"]


class ForeshadowingDraft(Lenient):
    description: str = Field(description="伏笔内容：真相是什么")
    span: ForeshadowSpan = Field(default="中", description="跨度：短（一个单元内收）/ 中（一卷内收）/ 长（跨卷）")
    plant_plan: str = Field(description="计划在哪里、以什么方式埋下，读者当时会怎么误解")
    payoff_plan: str = Field(description="计划在哪里回收，回收时的效果")
    plant_volume: int = Field(default=1, ge=1, description="在第几卷埋下")
    payoff_volume: int = Field(default=1, ge=1, description="在第几卷回收")
    node: int = Field(default=0, ge=0, description="为第几个节点的「之前得先有」做铺垫；没有就填 0")


class ExpectationDraft(Lenient):
    description: str = Field(description="读者在等什么，一句话，如「三年之约：主角要当众击败退婚的未婚妻」")
    span: Literal["中", "长"] = Field(default="长", description="跨度：中（一卷内兑现）/ 长（跨卷兑现）")
    plant_plan: str = Field(
        description="怎么立起来：谁当着谁、立下什么约定、放出什么狠话或定下什么目标，读者从此在等什么"
    )
    payoff_plan: str = Field(description="怎么兑现，以及怎么超出读者的预期（比读者以为的更大、更快，或者换个角度）")
    plant_volume: int = Field(default=1, ge=1, description="在第几卷立下")
    payoff_volume: int = Field(default=1, ge=1, description="在第几卷兑现")
    node: int = Field(default=0, ge=0, description="和第几个节点有关；没有就填 0")


class ArcSecretDraft(SecretDraft):
    entry: str = Field(default="", description="这个秘密写在设定库「往事与秘密」的哪一条里，填条目名称；没有就留空")


class SegmentVolumesDraft(Lenient):
    """这一篇分几卷、几条线在这一篇走到哪一步、人物什么时候登场、读者在等什么、用到哪些信息差。"""

    volumes: list[VolumeDraft] = Field(
        description="这一篇的分卷卡片，通常 1-3 卷，卷号接着分卷提示往下编；每卷都走向这一篇的终点，最后一卷写到终点"
    )
    threads: list[ThreadDraft] = Field(
        description="线索，3-8 条：一条主线，再配感情线、反派线、谜团线、成长线；已有的线沿用原名，节拍只排这一篇的几卷"
    )
    anchors: list[NodeAnchorDraft] = Field(
        default_factory=list, description="人物出场：要紧人物各自在哪个节点前后登场、确认关系、翻脸、高光或退场"
    )
    wait: ExpectationDraft | None = Field(
        default=None,
        description="这一篇让读者等的那件事，记成一条长线期待：在这一篇的卷里立下，在终点前后兑现",
    )
    secrets: list[ArcSecretDraft] = Field(
        default_factory=list, description="这一篇用得到的信息差，2-6 条；信息差表里已有的不用重写"
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这一篇分几卷、每卷写到哪、感情线什么时候进场")


ForeshadowAction = Literal["埋下", "提醒", "回收"]


class RevealStep(Lenient):
    ref: str = Field(description="秘密编号，如 S2（必须是信息差表里已有的编号）")
    to: str = Field(description="揭给谁：人物姓名，或者「读者」「众人」")
    how: str = Field(description="怎么揭开、揭开后局面怎么变，20-60 字")


class ForeshadowStep(Lenient):
    ref: str = Field(description="台账编号：伏笔如 F3，期待如 E2（必须是台账里已有的编号）")
    action: ForeshadowAction = Field(
        description="埋下 / 提醒（让读者再想起来）/ 回收；对期待来说，埋下就是立下，回收就是兑现"
    )
    detail: str = Field(default="", description="具体怎么做，20-60 字")


class PlotUnitDraft(Lenient):
    index: int = Field(ge=1, description="剧情单元序号，从 1 开始")
    title: str = Field(description="单元标题")
    summary: str = Field(
        default="",
        description="一段话：什么事找上门；主角怎么应对、用了什么本事；读者叫好的那一下；做完拿到什么、主线往前走了哪一步",
    )
    chapter_count: int = Field(ge=3, le=40, description="预计章数，通常 5-15")
    goal: str = Field(description="这个单元主角要做成什么")
    conflict: str = Field(description="阻碍与冲突来自哪里；对手怎么谋划")
    climax: str = Field(description="高潮场面与爽点：主角怎么破局，读者爽在哪里")
    outcome: str = Field(description="结果，以及给下一个单元留下的钩子")
    loop: str = Field(
        default="",
        description="核心循环在这个单元怎么转一圈：主角做了什么、得到什么、读者爽在哪；以感情为主的书写感情推进了哪一步，20-60 字",
    )
    key_events: list[str] = Field(description="按顺序列出 4-8 个关键事件")
    thread_beats: list[ThreadStep] = Field(default_factory=list, description="本单元推进哪些线索，至少一条")
    foreshadow_actions: list[ForeshadowStep] = Field(
        default_factory=list, description="本单元对台账里已有伏笔和期待的动作（埋下、提醒或回收）"
    )
    reveals: list[RevealStep] = Field(default_factory=list, description="本单元揭开的秘密；没有就留空")
    editor_note: str = Field(default="", description=EDITOR_NOTE_DESC)
    techniques: list[str] = Field(default_factory=list, description=TECHNIQUES_DESC)
    tropes: list[str] = Field(
        default_factory=list,
        description="本单元用到的套路：核心套路写在第一个，最多再加一个；用题材打法「套路库」里的名称，如「拍卖会」",
    )
    resolution: str = Field(
        default="", description="主角在高潮靠什么破局：从题材打法「破局手法」里选一类，只写类名，如「算计设局」"
    )


class NewForeshadowing(ForeshadowingDraft):
    plant_unit: int = Field(default=1, ge=1, description="在本卷第几个单元埋下")
    payoff_unit: int = Field(
        default=0, ge=0, description="在本卷第几个单元回收；跨卷回收填 0，并在 payoff_volume 写明第几卷"
    )


class NewExpectation(ExpectationDraft):
    span: Literal["中", "长"] = Field(default="中", description="跨度：中（本卷内兑现）/ 长（跨卷兑现）")
    plant_unit: int = Field(default=1, ge=1, description="在本卷第几个单元立下")
    payoff_unit: int = Field(
        default=0, ge=0, description="在本卷第几个单元兑现；跨卷兑现填 0，并在 payoff_volume 写明第几卷"
    )


class NodeUpdate(Lenient):
    title: str = Field(description="调整后的节点名称，4-10 字")
    event: str = Field(description="调整后发生什么，50-120 字")
    prerequisite: str = Field(description="调整后之前得先有，30-100 字")
    consequence: str = Field(description="调整后之后变成，30-100 字")
    reason: str = Field(description="为什么要调整：前文写成了什么样，原来的节点哪里不自然，一两句")


class VolumePlanDraft(Lenient):
    """卷纲：把一卷拆成剧情单元，并安排本卷的线索节拍与伏笔。"""

    want: str = Field(
        default="", description="这一卷想做成什么：主角这一卷的目标，要具体；说清它是这一篇目标的哪一步，30-60 字"
    )
    pressure: str = Field(
        default="", description="卷首处境：这一卷开头主角被什么压着（先抑）；和上一卷开头的压法不要一样，30-60 字"
    )
    units: list[PlotUnitDraft] = Field(description="本卷的剧情单元，章数之和等于本卷预计章数")
    new_foreshadowings: list[NewForeshadowing] = Field(
        default_factory=list, description="本卷新埋的短线、中线伏笔，2-6 条"
    )
    new_expectations: list[NewExpectation] = Field(default_factory=list, description="本卷新立的中线期待，1-3 条")
    node_update: NodeUpdate | None = Field(
        default=None, description="本卷走向的节点是暂定、按前文已经写不自然时，提议的调整；不需要调整或节点是铁钉时留空"
    )
    node_conflict: str = Field(
        default="", description="本卷走向的节点是铁钉、但和前文有冲突时，说明冲突在哪；没有冲突就留空"
    )
    remark: str = remark_field("这一卷怎么拆、节奏怎么起伏、最大的爽点在哪")


class VolumeDirection(Lenient):
    name: str = Field(description="方向名，4-8 字，如「借刀杀人」「感情线唱主角」")
    idea: str = Field(description="这一稿怎么拆：主打什么套路、对手怎么谋划、高潮怎么打、感情线占多重，80-150 字")
    difference: str = Field(default="", description="和其他方向最大的不同，一句话")


class VolumeDirections(Lenient):
    """拆卷纲之前，主编先想几个不同方向，每个方向各拆一份，交给审稿比稿。"""

    directions: list[VolumeDirection] = Field(description="按编辑部力度设置给出 2-4 个方向，彼此要有实质差别")
    remark: str = remark_field("这几个方向分别押在什么上")


def _score(value: Any) -> Any:
    """分数限制在 1-10：模型偶尔写成 0 分、11 分或「8分」。"""
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        value = int(match.group()) if match else 5
    if isinstance(value, int | float):
        return max(1, min(10, round(value)))
    return value


class PitchScore(Lenient):
    pitch: int = Field(ge=1, description="方案序号，从 1 开始")
    cool: int = Field(description="爽点，1-10 分：爽点够不够密、够不够足，卷末是不是全卷最大的高潮")
    weaving: int = Field(description="线索交织，1-10 分：线索节拍是否都落到单元里，几条线是否互相牵动")
    villain: int = Field(description="反派智商，1-10 分：对手的谋划是否合理，主角是不是赢在对手犯蠢")
    novelty: int = Field(description="新意，1-10 分：和前面用过的套路、破局方式比有没有新东西")
    comment: str = Field(description="一句话点评：最大的长处和短板")

    @field_validator("cool", "weaving", "villain", "novelty", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> Any:
        return _score(value)

    @property
    def total(self) -> int:
        return self.cool + self.weaving + self.villain + self.novelty


class PitchJudgement(Lenient):
    """审稿比稿：给每份卷纲方案打分，选出最好的一份，必要时建议融合。"""

    scores: list[PitchScore] = Field(description="每份方案一条")
    winner: int = Field(ge=1, description="选中的方案序号")
    merge: str = Field(
        default="",
        description="要从其他方案借来的内容：写清借哪个方案的哪个单元或哪个设计、放到选中方案的什么位置；不需要融合就留空",
    )
    remark: str = remark_field("为什么选这一份、它赢在哪里")


AuditAspect = Literal["villain", "rhythm", "foreshadow", "repetition", "expectation"]
AUDIT_ASPECT_DESC = (
    "villain 反派是否降智 / rhythm 爽点节奏 / foreshadow 伏笔排期 / repetition 套路重复 / expectation 期待感"
)


class AuditCheck(Lenient):
    aspect: AuditAspect = Field(description=AUDIT_ASPECT_DESC)
    ok: bool = Field(description="这一项是否过关")
    comment: str = Field(description="一句话结论")


class AuditIssue(Lenient):
    aspect: AuditAspect = Field(description=AUDIT_ASPECT_DESC)
    unit: int = Field(default=0, ge=0, description="问题出在第几个单元；整卷的问题填 0")
    problem: str = Field(description="具体问题")
    suggestion: str = Field(description="怎么改")
    severity: Literal["high", "medium", "low"] = Field(description="high：必须改；medium：应该改；low：小建议")


class VolumeAudit(Lenient):
    """卷纲专项审稿：反派智商、爽点节奏、伏笔排期、套路重复、期待感。"""

    verdict: Literal["pass", "revise"] = Field(description="pass：可以交给作者；revise：有必须修改的问题")
    checks: list[AuditCheck] = Field(description="五项各一条")
    issues: list[AuditIssue] = Field(default_factory=list, description="问题清单，最多 6 条，按严重程度排序")
    remark: str = remark_field()


EmotionMood = Literal["爽", "燃", "甜", "虐", "悬", "笑", "暖", "惊"]


class ChapterOutlineDraft(Lenient):
    title: str = Field(description="章节标题，不带「第几章」，网文风格，4-12 字")
    goal: str = Field(description="本章要完成的剧情任务")
    scenes: list[str] = Field(description="按顺序列出 2-4 个场景：在哪、谁、发生什么")
    conflict: str = Field(description="本章的冲突或阻碍")
    cool_point: str = Field(description="本章的爽点或情绪高点：打脸、反转、突破、心动、揭秘……")
    hook: str = Field(description="结尾钩子：本章停在什么悬念上，让读者想看下一章")
    characters: list[str] = Field(default_factory=list, description="出场的主要人物姓名")
    foreshadow_actions: list[ForeshadowStep] = Field(
        default_factory=list, description="本章对伏笔和期待的动作（伏笔如 F3，期待如 E2）"
    )
    emotion: int = Field(
        default=0, description="本章读者的情绪落点：-2 憋屈压抑，-1 偏压，0 平稳或悬着，1 偏扬，2 爆发爽快"
    )
    mood: EmotionMood = Field(default="悬", description="本章的主情绪：爽 / 燃 / 甜 / 虐 / 悬 / 笑 / 暖 / 惊")
    reveals: list[RevealStep] = Field(default_factory=list, description="本章揭开的秘密；没有就留空")

    @field_validator("emotion", mode="before")
    @classmethod
    def _emotion(cls, value: Any) -> int:
        if isinstance(value, str):
            match = re.search(r"[+-]?\d+(?:\.\d+)?", value)
            value = float(match.group()) if match else 0
        if not isinstance(value, int | float) or value != value:
            return 0
        return int(max(-2, min(2, value)))


class ChapterPlanDraft(Lenient):
    """章纲：一个剧情单元里每一章写什么。"""

    chapters: list[ChapterOutlineDraft] = Field(description="本单元的每一章，数量等于本单元章数")
    remark: str = remark_field("这个单元的节奏怎么安排、哪一章最燃")


Severity = Literal["high", "medium", "low"]


class ChapterIssue(Lenient):
    problem: str = Field(description="具体问题，引用原文位置")
    suggestion: str = Field(description="怎么改")
    severity: Severity = Field(description="high：必须重写；medium：影响阅读，应该改；low：小建议")


class ChapterReview(Lenient):
    verdict: Literal["pass", "revise"] = Field(description="pass：可以定稿；revise：必须重写")
    highlights: list[str] = Field(default_factory=list, description="写得好的地方，1-3 条")
    issues: list[ChapterIssue] = Field(default_factory=list, description="问题清单，最多 5 条，按严重程度排序")
    remark: str = remark_field()


class ConsistencyReport(Lenient):
    issues: list[ChapterIssue] = Field(default_factory=list, description="与设定库、前文矛盾的地方；没有矛盾就留空")
    remark: str = remark_field()


class CharacterUpdate(Lenient):
    name: str = Field(description="人物姓名（必须是设定库里已有的人物）")
    location: str = Field(default="", description="本章结束时所在位置；没变就留空")
    condition: str = Field(default="", description="本章结束时的状态，如伤势、处境、心境；没变就留空")
    want: str = Field(default="", description="本章结束时此人此刻最想马上做成的事；变了才写，没变就留空")
    power: str = Field(
        default="",
        description="本章结束时的实力与地位：修炼的写境界，言情、职场写身份、家世、职位，用等级体系里的叫法；变了才写，没变就留空",
    )
    abilities: str = Field(
        default="", description="会的本事变了（学会新本事、失去旧本事）才写，写变化后完整的能力说明；境界写在实力与地位；没变就留空"
    )
    is_alive: bool = Field(default=True, description="本章结束时是否还活着")


class NewCharacter(Lenient):
    name: str = Field(description="姓名")
    role_type: Literal["主角", "女主", "男主", "班底", "对手", "导师", "配角"] = Field(
        default="配角", description="角色定位"
    )
    background: str = Field(default="", description="身份与来历")
    personality: str = Field(default="", description="性格与说话方式")


class ForeshadowUpdate(Lenient):
    ref: str = Field(description="伏笔编号，如 F3")
    action: ForeshadowAction = Field(description="本章实际对这条伏笔做了什么")


class SecretUpdate(Lenient):
    ref: str = Field(description="秘密编号，如 S2（必须是信息差表里已有的编号）")
    learned_by: list[str] = Field(default_factory=list, description="本章新知道这件事的人（设定库里已有的姓名）")
    public: bool = Field(default=False, description="本章之后这件事是否已经人尽皆知")
    how: str = Field(default="", description="怎么知道的，一句话")


class NewSecret(Lenient):
    title: str = Field(description="秘密的短名，4-12 字")
    truth: str = Field(description="真相是什么，30-80 字")
    knowers: list[str] = Field(default_factory=list, description="本章结束时知道这件事的人（设定库里已有的姓名）")
    reader_knows: ReaderKnows = Field(description="读者知不知道：知道 / 不知道 / 部分")


class ChapterEntry(Lenient):
    category: str = Field(
        description="放进哪一类：等级体系、世界与地图、势力划分、物品与功法、往事与秘密、特殊规则，或已有的自建类别的名字"
    )
    name: str = Field(description="名称，照正文里的叫法")
    one_line: str = Field(description="一句话：是什么")
    content: str = Field(default="", description="正文里交代了的细节，一两句；没交代就留空")


class ChapterDigest(Lenient):
    """定稿后设定师提取本章带来的变化，程序校验后写进设定库。"""

    summary: str = Field(description="本章摘要，100-200 字，写清发生了什么、结果如何，供后文回顾")
    character_updates: list[CharacterUpdate] = Field(default_factory=list, description="状态有变化的已有人物")
    new_characters: list[NewCharacter] = Field(default_factory=list, description="本章新登场、之后还会出现的人物")
    foreshadow_updates: list[ForeshadowUpdate] = Field(
        default_factory=list, description="本章实际埋下、提醒或回收的伏笔与期待（期待：埋下＝立下，回收＝兑现）"
    )
    secret_updates: list[SecretUpdate] = Field(
        default_factory=list, description="本章正文里真的发生的信息差变化：谁新知道了哪个秘密、哪个秘密公开了"
    )
    new_secrets: list[NewSecret] = Field(
        default_factory=list, description="本章出现的、之后会影响剧情的新秘密；没有就留空"
    )
    new_entries: list[ChapterEntry] = Field(
        default_factory=list,
        description="本章新出现、之后还会用到的设定（地点、物品、功法、组织、规矩、货币的叫法）；设定库里已有的不要重复；路人、一次性的东西不记",
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description="本章正文和设定库对不上的地方，一句话一条（比如设定库写货币用灵石，正文写了金币）；没有就留空",
    )
    remark: str = remark_field()


class StoryRecap(Lenient):
    """一个剧情单元或一卷写完后设定师写的回顾，供后面的规划和写作回顾前情。"""

    recap: str = Field(
        description="回顾正文：按时间顺序写清发生了什么、结果如何、人物关系和实力有什么变化、留下了哪些悬念和没收的伏笔"
    )
    remark: str = remark_field()


class ChapterMaterials(Lenient):
    """写一章之前，设定师读章纲，从设定库和前文里挑出这一章用得上的资料。"""

    characters: list[str] = Field(
        default_factory=list, description="这一章会出场或被提到、写手需要看完整资料的人物（用设定库里的姓名）"
    )
    world: list[str] = Field(default_factory=list, description="这一章用得上的设定条目名称（用设定库里的名称）")
    chapters: list[int] = Field(
        default_factory=list, description="写这一章需要回顾的前文章节号，最多 5 个，只选真正有关联的"
    )
    notes: list[str] = Field(
        default_factory=list,
        description="提醒写手的注意事项，最多 5 条：人物此刻的伤势和处境、谁知道什么秘密、力量体系的限制、容易写错的细节",
    )
    remark: str = remark_field()


SETUP_PARTS = ("concept", "protagonist", "world", "segment", "volumes", "first_volume")


class Renamed(Lenient):
    old: str = Field(description="原来的叫法（人名、地名、境界名、物品名等专有名词），照原文抄")
    new: str = Field(description="改成的新叫法")


class RewriteOption(Lenient):
    label: Literal["稳妥", "大胆", "出格"] = Field(description="这种写法的大胆程度")
    text: str = Field(
        description="换上去的新文字：只写要改的那一处，不写别的部分；格式和原文一致（原文是一句就写一句，原文是一段就写一段）"
    )
    renamed: list[Renamed] = Field(default_factory=list, description="这种写法里改了叫法的专有名词；没改就留空")
    one_line: str = Field(
        default="", description="只在改的是一段话、而且这一条的一句话也该跟着变时，写新的一句话；否则留空"
    )


class RewriteOptions(Lenient):
    options: list[RewriteOption] = Field(description="三种写法，依次是稳妥、大胆、出格；稳妥的最贴近原来的意思")
    note: str = Field(default="", description="给作者的一句话：三种写法各自好在哪，推荐哪一种")


class RewriteOne(Lenient):
    text: str = Field(description="换上去的新文字：只写要改的那一处，不写别的部分；格式和原文一致")
    renamed: list[Renamed] = Field(default_factory=list, description="改了叫法的专有名词；没改就留空")
    one_line: str = Field(
        default="", description="只在改的是一段话、而且这一条的一句话也该跟着变时，写新的一句话；否则留空"
    )
    note: str = Field(default="", description="给作者的一句话：改了什么")


class FieldValue(Lenient):
    name: str = Field(description="字段名")
    value: str = Field(description="字段的内容")


class NewEntry(Lenient):
    category: str = Field(
        description="放进哪一类：角色卡片、金手指、等级体系、世界与地图、势力划分、物品与功法、往事与秘密、特殊规则，或已有的自建类别的名字"
    )
    name: str = Field(description="条目名称；角色卡片写人名")
    status: Literal["现在要定", "一句话就好", "以后再说"] = Field(description="现在要定、一句话就好、以后再说")
    one_line: str = Field(description="一句话")
    content: str = Field(
        default="", description="一段话；状态是一句话就好、以后再说的留空；角色卡片和卡片样式的类别留空，写在 fields 里"
    )
    fields: list[FieldValue] = Field(
        default_factory=list,
        description="角色卡片写定位、性别、年龄、外貌、性格与说话方式、身世、想要什么、能力、和主角的关系；卡片样式的自建类别写它的字段；其他留空",
    )
    why: str = Field(description="为什么要补这一条，一句话")


class NewCategory(Lenient):
    name: str = Field(description="自建类别的名字，如「厉鬼」「剧本」「灵宠」")
    style: Literal["卡片", "段落"] = Field(description="卡片还是段落")
    fields: list[str] = Field(default_factory=list, description="卡片样式的字段名，按顺序；段落样式留空")
    hint: str = Field(description="这一类一段话里该说清什么，一句话")
    why: str = Field(description="为什么这本书需要这一类，一句话")


class GapReport(Lenient):
    entries: list[NewEntry] = Field(default_factory=list, description="建议新增的条目，最多 8 条；已有的不要重复")
    categories: list[NewCategory] = Field(
        default_factory=list, description="建议新建的自建类别，最多 2 个；八个默认类别放得下的不要建"
    )
    note: str = Field(default="", description="给作者的一句话总结")


class LibraryIssue(Lenient):
    kind: Literal["矛盾", "同根", "好看", "题材", "该定没定", "其他"] = Field(description="问题属于哪一类")
    title: str = Field(description="给作者看的一句话：哪里有问题")
    target_name: str = Field(default="", description="问题在哪一条（条目或角色卡片的名称）；涉及好几条写最主要的一条")
    quote: str = Field(default="", description="要改的原文，从那一条里照抄一句；不需要改原文的留空")
    fix: str = Field(default="", description="建议换成的文字，只写换掉 quote 的那一句；没有具体改法的留空")
    why: str = Field(description="为什么，一句话")


class LibraryReview(Lenient):
    issues: list[LibraryIssue] = Field(
        default_factory=list, description="查出的问题，按严重程度排，最多 10 条；没有问题就留空"
    )
    note: str = Field(default="", description="给作者的一句话总结")


class LibraryIntent(Lenient):
    kind: Literal["改设定", "写大纲", "写作要求", "提问闲聊"] = Field(
        description="这句话是哪一种：要改设定库里的某一处选「改设定」；要编辑部现在就把大纲上的某一段（结局、某一篇、某一卷、某个单元、某一章）写出来或重写选「写大纲」；要编辑部以后规划、写作时照着做的选「写作要求」；提问、商量、出主意、闲聊选「提问闲聊」；拿不准时选「提问闲聊」"
    )
    target_name: str = Field(
        default="", description="改设定时才写：要改哪一条，条目或角色卡片的名称，照设定库目录里的写法"
    )
    part: str = Field(
        default="", description="改设定时才写：改这一条的哪一处：卡片的字段名、等级的级名、「名称」「一句话」「一段话」"
    )
    quote: str = Field(default="", description="改设定、只改其中一句时，把那一句从原文里照抄出来；否则留空")
    outline_target: str = Field(
        default="",
        description="写大纲时才写：写大纲上的哪一段。作者说「这一篇」「这一章」「这段」「这里」这种指着正在看的那一页的，写「正在看的」；说了哪一段的照作者的说法写，比如「第三卷」「结局」「青阳城篇」「第 12 章」",
    )
    mode: Literal["给几个写法", "照作者的意思改", "补齐空着的"] = Field(
        default="给几个写法",
        description="改设定时才写：作者只说了不满意、没说怎么改的，选给几个写法；说清了怎么改的，选照作者的意思改；要把这一条补齐、写全、补完整的，选补齐空着的",
    )
    instruction: str = Field(default="", description="改设定、写大纲时才写：作者想怎么改、想写成什么样，用作者的话概括一句")
    requirement: str = Field(
        default="",
        description="写作要求时才写：写成一句清楚的要求，说清做什么、不写理由，「这样」「那个」换成具体内容，60 字以内",
    )
    scope: Literal["一直有效", "只管下一章", "只管这一卷", "只管下一卷"] = Field(
        default="一直有效",
        description="写作要求时才写：作者说了「下一章」「这一卷」「下一卷」的照选，没说的选一直有效",
    )
    who: Literal["主编", "设定师", "写手", "审稿"] = Field(
        default="主编",
        description="提问闲聊时才写：谁来回答最合适：问设定、前后对不对、谁知道什么找设定师；问怎么写、文风找写手；要挑毛病找审稿；其余找主编",
    )
    reply: str = Field(default="", description="改设定、写大纲、写作要求时，主编在群聊里回作者的一句话；提问闲聊留空")


class BookDraft(Lenient):
    title: str = Field(description="书名本身（不带书名号、不带备选）")
    blurb: str = Field(description="简介：写给读者看的那段话，100-250 字；开头一句就抓人，不剧透结局")
    channel: Literal["男频", "女频"] = Field(description="男频还是女频")
    genre: str = Field(description="类别：从给出的类别里挑一个，原样照写")
    tags: list[str] = Field(default_factory=list, description="3-5 个标签，优先用给出的常见标签，没有合适的才自己写，每个不超过 6 个字")
    target_length: int = Field(ge=1, le=5000, description="篇幅，单位万字，一般 100-300")
    reply: str = Field(default="", description="一句话告诉作者你这版的思路，或者这次改了哪里")


class Pitch(Lenient):
    name: str = Field(description="方向名：给这个版本贴的标签，4-8 字，说清主打什么，如「废柴逆袭流」；不是书名")
    text: str = Field(description="故事方向：一百字左右，一段话说清主角是谁、凭什么、想要什么、读者爽在哪")
    titles: list[str] = Field(description="2 个书名候选：一个突出金手指或核心意象，一个突出主角或反差")


class PitchSet(Lenient):
    benchmark: str = Field(
        default="",
        description="作者点名对标某本书时，写出你理解的读者爱那本书什么：核心设定、爽点、主角气质；拿不准的写「不确定」；没有对标就留空",
    )
    pitches: list[Pitch] = Field(description="三个故事方向，彼此在读者享受的东西上有实质差别；作者定下的东西三个都保留")
    recommended: int = Field(ge=1, le=3, description="推荐第几个")
    reply: str = Field(
        description="主编在群聊里说的话：一两句白话说清推荐哪个、为什么；有对标时顺带请作者看看理解对不对"
    )


class StoryConcept(Lenient):
    story: str = Field(description="定调：一段话，200-400 字，说清这本小说主要讲什么故事")
    secret: str = Field(
        description="底牌：全书最大的秘密，一两句，只有作者和编辑部知道；金手指的来历、幕后的人最好都落在它上面；这本书没有大秘密就写「没有」"
    )
    title: str = Field(description="书名本身（不带书名号、不带备选）")
    alt_titles: list[str] = Field(default_factory=list, description="2-3 个备选书名，风格与书名一致")
    genre: str = Field(description="类型，如「玄幻·修仙」「都市·重生」")
    tags: list[str] = Field(default_factory=list, description="3-6 个标签")
    target_reader: str = Field(default="", description="目标读者：男频还是女频、这类读者爱看什么、最讨厌什么，一句话")
    tone: str = Field(description="基调与文风：轻松还是压抑、幽默还是冷峻、节奏快还是慢，一两句")
    target_length: int = Field(
        default=100,
        ge=5,
        le=1000,
        description="全书计划总字数，单位：万字（200 万字就填 200）。以作者要求为准；作者没说时按类型的主流长度",
    )
    chapter_words: int = Field(ge=1000, le=8000, description="每章目标字数，通常 2000-4000")
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这一段为什么这样写、底牌怎么和金手指连上")

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


class CharacterCardDraft(Lenient):
    name: str = Field(description="姓名；作者定过的照用")
    aliases: list[str] = Field(default_factory=list, description="别名、外号、化名；没有就留空")
    role_type: Literal["主角", "女主", "男主", "班底", "对手", "导师", "配角"] = Field(description="定位")
    status: Literal["现在要定", "一句话就好", "以后再说"] = Field(
        default="现在要定", description="现在要定的写全；一句话就好、以后再说的只写名字和一句话"
    )
    one_line: str = Field(description="一句话：这个人是谁、在故事里干什么")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄或年龄段")
    appearance: str = Field(default="", description="外貌，一两个记得住的特点")
    personality: str = Field(default="", description="性格与说话方式：2-3 个核心性格加一个反差，再写一两句他会说的话")
    background: str = Field(default="", description="身世：公开的来历；藏着的秘密不要写在这里")
    goal: str = Field(default="", description="想要什么：长远的和眼下的，各一句")
    abilities: str = Field(default="", description="能力：本事、修为、技能，用等级体系里的叫法")
    relation: str = Field(default="", description="和主角的关系，一句话；主角本人留空")
    want: str = Field(default="", description="此刻想要什么：故事开始时最想马上做成的事，一句话")


class FingerDraft(Lenient):
    place: Literal["金手指", "物品与功法", "特殊规则", "角色卡片"] = Field(
        description="金手指放在哪：一般放「金手指」这一类；没有金手指、只写主角最大优势的，写在主角的角色卡片里"
    )
    name: str = Field(description="金手指的名称，如「轮回镜」；写在角色卡片里的，填主角的名字")
    one_line: str = Field(description="一句话")
    content: str = Field(
        description="一段话：写成主角在故事里遇到的样子——能做什么、第一阶段有多大本事、限制和代价、谁知道、以后往哪长；来历落在底牌上，但不要直接把底牌写出来"
    )


class LibraryFocus(Lenient):
    protagonist: CharacterCardDraft = Field(description="主角的角色卡片，写全")
    finger: FingerDraft = Field(description="金手指；没有金手指的书，写主角最大的优势，放在角色卡片里")
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("主角为什么非往前走不可、金手指怎么和底牌连上")


class LevelDraft(Lenient):
    name: str = Field(description="这一级的名称")
    text: str = Field(default="", description="这一级的介绍，一两句；高阶的可以留空，以后再补")


class EntryDraft(Lenient):
    category: str = Field(
        description="放进哪一类：等级体系、世界与地图、势力划分、物品与功法、往事与秘密、特殊规则；这几类放不下、属于建议的自建类别的，写那个自建类别的名字"
    )
    name: str = Field(description="条目名称；世界与地图的第一条叫「世界概况」")
    status: Literal["现在要定", "一句话就好", "以后再说"] = Field(description="现在要定、一句话就好、以后再说")
    one_line: str = Field(description="一句话")
    content: str = Field(
        default="",
        description="一段话（等级体系写总说明：怎么往上升、越级多难、有什么代价）；一句话就好、以后再说的留空",
    )
    levels: list[LevelDraft] = Field(
        default_factory=list,
        description="只有等级体系才写：各级从低到高；没有正式等级的，写一级「没有」，并在总说明里说清怎么看强弱",
    )
    fields: list[FieldValue] = Field(default_factory=list, description="只有卡片样式的自建类别才写：它的字段")
    parent: str = Field(default="", description="只有世界与地图里的地方才写：属于哪里，写上级地方的名称；没有就留空")


class LibraryRest(Lenient):
    characters: list[CharacterCardDraft] = Field(
        default_factory=list,
        description="主角以外的角色卡片：第一卷就登场的写全（班底、女主或男主、导师、开篇的小麻烦、第一个大对手），后面才登场的写「以后再说」；要紧的人物八个以内",
    )
    entries: list[EntryDraft] = Field(description="设定条目：按题材常建的条目起步，用得上的才建，用不上的不建")
    categories: list[NewCategory] = Field(
        default_factory=list,
        description="八个默认类别放不下、又是这本书的核心东西时，建议新建的自建类别，最多 2 个；作者同意才建",
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这本书的设定以什么为主、哪几条最要紧")


class ArcDraft(Lenient):
    title: str = Field(description="篇名，如「青阳城篇」「宗门篇」")
    text: str = Field(
        description="第一篇写一段话（在哪个舞台、主角这一篇想做成什么、谁挡路、怎么收尾、读者在等什么和揭开什么、主角从哪儿走到哪儿）；后面的篇只写一句方向"
    )
    planned: bool = Field(description="第一篇填 true；后面的篇填 false（写到再定）")


class VolumeBrief(Lenient):
    title: str = Field(description="卷名本身，不要带「第几卷」")
    summary: str = Field(
        description="第 1 卷写一段话（这一卷想做成什么、卷首处境、卷末的高潮和结果、这一卷的对手、新登场的人）；其余卷写一句话"
    )
    chapter_count: int = Field(ge=1, le=1000, description="这一卷大约多少章")


class UnitBrief(Lenient):
    title: str = Field(description="单元名，2-8 字，如「退婚」「识宝」")
    summary: str = Field(
        description="一段话：什么事找上门；主角怎么应对、用了什么本事；读者叫好的那一下；做完拿到什么、主线往前走了哪一步"
    )
    chapter_count: int = Field(ge=1, le=50, description="这个单元几章")


class NewName(Lenient):
    category: str = Field(description="角色卡片，或设定库的类别名")
    name: str = Field(description="名称")
    one_line: str = Field(description="一句话")


class OutlineDraft(Lenient):
    arcs: list[ArcDraft] = Field(
        description="全书的篇，按顺序：第一篇写细；中间的篇只写定调里提到的或作者自己想到的，没有就不写；不要硬排"
    )
    ending: str = Field(description="结局：一句话，往哪里结束")
    volumes: list[VolumeBrief] = Field(description="第一篇分成的卷，按顺序")
    units: list[UnitBrief] = Field(description="第 1 卷拆成的剧情单元，按顺序；章数加起来等于第 1 卷的章数")
    new_names: list[NewName] = Field(
        default_factory=list, description="大纲里冒出来、设定库里还没有的人物和地方；没有就留空"
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("第一篇怎么兑现卖点、第 1 卷的节奏怎么排")


class SetupNotePlan(Lenient):
    concept_instructions: str = Field(default="", description="定调需要怎样修改；不需要改则留空")
    settings_instructions: str = Field(default="", description="设定库里哪一处需要怎样修改；不需要改则留空")
    outline_instructions: str = Field(default="", description="大纲需要怎样修改；不需要改则留空")
    remark: str = remark_field("你打算怎么落实作者的话")

    def instructions(self) -> dict[str, str]:
        return {
            name: text
            for name in ("concept", "settings", "outline")
            if (text := getattr(self, f"{name}_instructions")).strip()
        }


class EndNodeDraft(Lenient):
    ref: int = Field(
        default=0,
        ge=0,
        description="终点用已有节点时填它的序号（大纲里紧接着的远景节点，或结局）；新起一个节点填 0",
    )
    title: str = Field(description="终点的名称，4-10 字")
    event: str = Field(description="终点发生什么：这一篇的最高潮，具体到人和场面，50-120 字")


class FillEntry(Lenient):
    name: str = Field(description="设定库里状态是「以后再说」、这一篇要用到的条目名称，照目录写")
    content: str = Field(description="现在把它写全：一段话")


class NextArcDraft(Lenient):
    title: str = Field(description="篇名，如「宗门篇」「北境篇」")
    text: str = Field(
        description="这一篇的一段话，200-400 字：舞台沿用还是往上走一层；主角这一篇想做成什么；谁挡路、对手想要什么；怎么收尾；读者在等什么；底牌这一篇露出哪一角；主角从哪儿走到哪儿"
    )
    end: EndNodeDraft = Field(description="这一篇的终点，也是这一篇的最高潮")
    fill_entries: list[FillEntry] = Field(
        default_factory=list, description="这一篇要用到、现在还是「以后再说」的条目，写全；用不到的不写"
    )
    new_entries: list[EntryDraft] = Field(
        default_factory=list,
        description="这一篇新出现、设定库里还没有的设定：新舞台、新势力、新规矩、新物品；更高的等级写进已有的等级体系（用原来的条目名称，只写新的几级）",
    )
    new_characters: list[CharacterCardDraft] = Field(
        default_factory=list, description="这一篇新登场的要紧人物；已经在设定库里的不用重写"
    )
    secret: str = Field(
        default="", description="只有提示里说这本书还没有底牌时才写：从已经写出来的金手指、谜团里推一两句底牌；否则留空"
    )
    ending_change: str = Field(default="", description="结局方向要调的，写新的一句；结局锁住时不能改；不调就留空")
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这一篇为什么这样走、终点为什么选在这里")


class ChatReply(Lenient):
    reply: str = Field(
        description="回作者的话：先直接回答，再说理由；用这本书里的人物、设定、章节说话；出主意时给两三个有实质差别的方向并说推荐哪个；一般三到八句，作者要细节才写长"
    )


class ChatSummary(Lenient):
    summary: str = Field(
        description="之前聊过什么，300 字以内：聊过的话题；作者的想法和倾向；已经定下、记成要求或改了设定的结论；还没定的问题"
    )


class PlanItem(Lenient):
    where: Literal["定调", "设定库", "大纲", "写作要求"] = Field(
        description="这一条落在哪：定调的一段话；设定库里的一条；大纲里的篇、卷、单元或结局；以后规划和写作都要照做的写作要求"
    )
    target: str = Field(
        default="",
        description="设定库写条目或角色卡片的名称（照设定库目录，新建的写新名字）；大纲写「第 N 篇」「第 N 卷」「单元「名称」」或「结局」；定调、写作要求留空",
    )
    part: str = Field(
        default="",
        description="设定库才写：改这一条的哪一处，卡片的字段名、等级的级名、「一句话」「一段话」；新建的和整条都要改的留空",
    )
    category: str = Field(
        default="",
        description="设定库里新建的才写：放进哪一类，八个默认类别之一（角色卡片、金手指、等级体系、世界与地图、势力划分、物品与功法、往事与秘密、特殊规则）或已有的自建类别",
    )
    change: str = Field(
        description="要落实成什么，写清楚具体内容，不看前面的对话也能照做；不要写「方向一」「刚才说的那个」，要把内容写出来"
    )
    scope: Literal["一直有效", "只管下一章", "只管这一卷", "只管下一卷"] = Field(
        default="一直有效", description="写作要求才看：作者说了只管下一章、这一卷、下一卷的照选，没说的选一直有效"
    )


class ChatPlan(Lenient):
    title: str = Field(description="方案名，4-12 字，如「开篇和老怪」")
    summary: str = Field(description="一段话说清和作者商量定了什么，100-300 字，给作者看")
    items: list[PlanItem] = Field(
        default_factory=list,
        description="要落实的条目，按定调、设定库、大纲、写作要求的顺序排；只放作者提出或明确同意的，最多 12 条；什么都没定就留空",
    )
    open_questions: list[str] = Field(
        default_factory=list, description="聊到了、但作者还没拍板的问题，每条一句；没有就留空"
    )


class TidyItem(Lenient):
    index: int = Field(ge=1, description="要求的序号，照清单")
    action: Literal["保留", "删掉", "改写"] = Field(description="这一条怎么处理")
    reason: str = Field(description="为什么，一句白话，给作者看")
    rewrite: str = Field(default="", description="只有改写才写：改好的一句要求")


class RequirementsTidy(Lenient):
    items: list[TidyItem] = Field(description="清单里每一条都给一个判断，按序号排")


class DraftEntry(Lenient):
    name: str = Field(description="名称；角色写人名")
    values: list[FieldValue] = Field(
        default_factory=list, description="按【这一类的栏目】一栏一栏写，栏目名照抄；拿不准的栏目不写"
    )
    levels: list[LevelDraft] = Field(
        default_factory=list, description="只有一级一级往上排的类别才写：各级从低到高；其余类别留空"
    )


class DraftSet(Lenient):
    entries: list[DraftEntry] = Field(description="写出来的几条，条数照【写几条】，彼此要有实质差别")
    note: str = Field(default="", description="给作者的一两句话：这几条各自是什么思路")


class EntryFill(Lenient):
    values: list[FieldValue] = Field(default_factory=list, description="只写【要补的栏目】里的那几栏，栏目名照抄")
    note: str = Field(default="", description="给作者的一句话：这次补了什么思路")


class OutlineNodeWrite(Lenient):
    """大纲上的一段：全书结局、篇、卷、单元，只有名字和一段话。"""

    title: str = Field(default="", description="名字，不带「第几篇」「第几卷」；全书结局不用写")
    text: str = Field(description="这一段")
    note: str = Field(default="", description="给作者的一句话：这次的思路")


class ChapterOutlineWrite(Lenient):
    """大纲上的一章：章名和章纲。"""

    title: str = Field(default="", description="章名，不带「第几章」，网文风格，4-12 字")
    goal: str = Field(description="这一章要完成的剧情任务，一句话")
    scenes: list[str] = Field(default_factory=list, description="按顺序 2-4 个场景，每个一句：在哪、谁、发生什么")
    cool_point: str = Field(default="", description="这一章的爽点或情绪高点")
    hook: str = Field(default="", description="结尾停在什么悬念上")
    note: str = Field(default="", description="给作者的一句话：这次的思路")
