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


class BookDirection(Lenient):
    name: str = Field(
        description="方向名：给这个方向贴的标签，4-8 字，说清主打什么，如「废柴逆袭流」「旧案追凶流」；不是书名"
    )
    titles: list[str] = Field(
        default_factory=list,
        description="2 个书名候选，按【这本书的写作规矩】的书名要求起，不带书名号；两个候选换不同角度，一个突出金手指或核心意象，一个突出主角或反差",
    )
    logline: str = Field(description="一句话故事，50 字以内：主角是谁、想要什么、最大的阻碍是什么")
    protagonist: str = Field(description="主角：身份、性格、最抓人的一点，30-60 字")
    drive: str = Field(
        default="",
        description="驱动力：主角为什么非往前走不可——开局被什么逼着、长线想要什么，一句话，40 字以内；不能只是「变强」",
    )
    golden_finger: str = Field(
        description="金手指：先用一句话说清核心规则，再写怎么成长（越用越强、解锁或扩张什么）和一个能逼主角冒险或做选择的限制，40-80 字"
    )
    core_loop: str = Field(
        default="",
        description="核心循环：主角在一个个剧情单元里反复做的那件事、读者每个单元爽在哪里，一句话，40 字以内",
    )
    opening: str = Field(description="开局怎么切入：前 3 章发生什么、核心钩子是什么，40-80 字")
    selling_points: list[str] = Field(description="2-3 个卖点，具体到读者爽在哪里")
    stage_ladder: str = Field(description=STAGE_LADDER_DESC)
    tone: str = Field(description="基调，如「热血爽快，偶尔幽默」")
    reader: str = Field(description="目标读者：男频还是女频、爱看什么、最讨厌什么，一句话")
    difference: str = Field(description="和其他方向最大的不同，一句话")
    editor_note: str = Field(default="", description=EDITOR_NOTE_DESC)
    techniques: list[str] = Field(default_factory=list, description=TECHNIQUES_DESC)


class BookDirections(Lenient):
    """开书前主编先给出几个方向，作者挑一个（也可以混搭）。"""

    reference: str = Field(
        default="",
        description="对标作品：作者点名借鉴或对标某本书时，写出你对那本书的理解——核心设定和金手指、读者爽在哪里、主角是什么样的人、舞台怎么扩大、整体气质，拿不准的地方写「不确定」，80-200 字；作者没有提到任何作品就留空",
    )
    directions: list[BookDirection] = Field(description="3 个方向：作者已经定下的东西都保留，差别只做在作者没定的地方")
    recommended: int = Field(default=0, ge=0, description="你推荐的方向序号（从 0 开始）")
    remark: str = remark_field("推荐哪个方向、为什么；有对标作品时请作者看看你的理解对不对")


class BookConcept(Lenient):
    title: str = Field(description="书名本身（不带书名号、不带备选），按作者写作规矩里的书名要求来起")
    alt_titles: list[str] = Field(default_factory=list, description="2-3 个备选书名，风格与书名一致")
    genre: str = Field(description="类型，如「玄幻·修仙」「都市·重生」")
    tags: list[str] = Field(default_factory=list, description="3-6 个标签")
    target_reader: str = Field(default="", description="目标读者：男频还是女频、这类读者爱看什么、最讨厌什么，一句话")
    benchmark: str = Field(
        default="", description="对标：作者提到对标作品时，写清借鉴它什么、哪里要不一样，一两句；作者没提就留空"
    )
    logline: str = Field(description="一句话故事，50 字以内：谁、想要什么、最大的阻碍、和别的书哪里不一样")
    selling_points: list[str] = Field(
        description="核心卖点 2-3 个，具体到读者会为哪种场面叫好，不要「热血」「很爽」这类空话"
    )
    core_loop: str = Field(
        default="",
        description="核心循环：主角在一个个剧情单元里反复做的那件事，以及读者每个单元能拿到的爽感；以感情为主的书，写感情怎么一步步推进；40-80 字",
    )
    tone: str = Field(description="基调与文风：轻松还是压抑、幽默还是冷峻、节奏快还是慢，一两句")
    target_length: int = Field(
        default=100,
        ge=5,
        le=1000,
        description="全书计划总字数，单位：万字（200 万字就填 200）。以作者要求为准；作者没说时按类型的主流长度",
    )
    target_volumes: int = Field(
        ge=1, le=20, description="大概分几卷：按篇幅粗估，每卷通常 25-60 万字；后面每一段写到之前再细分"
    )
    chapter_words: int = Field(ge=1000, le=8000, description="每章目标字数，通常 2000-4000")
    stage_ladder: str = Field(default="", description=STAGE_LADDER_DESC)
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("一句话故事、核心卖点和核心循环为什么这样定")

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
    want: str = Field(default="", description="此刻想要什么：故事开始时此人最想马上做成的事，一句话")
    location: str = Field(default="", description="故事开始时所在的位置")
    condition: str = Field(default="", description="故事开始时的状态，如伤势、处境")


class RelationshipDraft(Lenient):
    source: str = Field(description="人物 A 的姓名（必须是人物列表里的人）")
    target: str = Field(description="人物 B 的姓名（必须是人物列表里的人）")
    kind: str = Field(description="关系类型，如 师徒、宿敌、青梅竹马")
    description: str = Field(default="", description="关系的具体情况与张力")


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


class NodeCandidates(Lenient):
    """作者要换一个节点或补一个空位时，主编给出的节点。"""

    nodes: list[StoryNodeDraft] = Field(description="按要求的数量给出：候选 3 个，补空位 1 个")
    remark: str = remark_field("这几个节点分别押在什么上")


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
    beat: str = Field(description="这一段让这条线走到哪一步，20-60 字")


class VolumeDraft(Lenient):
    index: int = Field(ge=1, description="卷序号，从 1 开始")
    title: str = Field(description="卷名本身，不要带「第几卷」")
    stage: str = Field(default="", description="本卷的舞台：地图、地点，如「青州 → 万劫谷」")
    summary: str = Field(description="本卷剧情概要，150-300 字")
    want: str = Field(
        default="", description="这一卷想做成什么：主角这一卷的目标，要具体；说清它是这一段目标的哪一步，30-60 字"
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
    target_node: int = Field(ge=1, description="本卷走向第几个节点（关键节点的序号）：一般就是这一段的终点")
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


class CaredPerson(Lenient):
    name: str = Field(description="姓名；作者定过的照用")
    relation: str = Field(description="和主角是什么关系，如「相依为命的妹妹」「欠他一条命的老兵」")
    why: str = Field(description="主角为什么在乎他，一句话")


class ProtagonistDraft(Lenient):
    """主角卡：他是谁、想要什么、为什么、凭什么。远处的事写到再定。"""

    name: str = Field(description="主角姓名；作者定过的照用")
    start: str = Field(
        description="起点：身份；开局处境有多低多难；读者为什么会代入他。用通俗说法，如「最底层的杂役」，不写具体的境界名称，40-80 字"
    )
    trigger: str = Field(description="驱动力·开局动机：开局发生了什么，逼得他不得不行动，30-60 字")
    pursuit: str = Field(
        description="驱动力·长线追求：贯穿全书或大半本的追求，如找人、复仇、守护、找回、证明、求生、登顶；要具体，不能只是「变强」；它是个谜的话先写谜面，谜底可以先不定，30-80 字"
    )
    root: str = Field(description="驱动力·情感根源：他为什么在乎——爱谁、欠谁、怕什么、缺什么，30-60 字")
    personality: str = Field(description="性格：2-3 个核心性格，加一个反差，20-50 字")
    style: str = Field(description="做事风格：遇事怎么想、怎么出手，20-40 字")
    bottom_line: str = Field(description="底线：他绝不会做的事，一两条")
    voice: str = Field(description="说话方式：口头习惯和语气，再写一两句他会说的话做示范")
    finger: str = Field(
        description="金手指·现在：一句话说清核心规则；第一阶段能做什么；限制是什么；谁知道。没有金手指的书，写主角最大的优势（才华、身份、记忆、性格），40-100 字"
    )
    flaw: str = Field(description="软肋：最大的缺点或心结，20-40 字")
    arc_end: str = Field(description="成长的终点：最后变成什么样的人，一句方向即可")
    cared: list[CaredPerson] = Field(
        default_factory=list, description="开局就在他身边、他在乎的人，1-3 个；后面才登场的人到时候再加"
    )
    interlock: str = Field(
        description="咬合检查：一两句说清驱动力、金手指、核心循环怎么咬在一起——金手指怎么帮他追求，每个单元转一圈怎么让追求往前走"
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("主角为什么非往前走不可、三件套怎么咬合")


class MapDraft(Lenient):
    name: str = Field(description="地图名，如「青石镇」「老城区」「林府」")
    powers: str = Field(description="谁说了算、谁和谁有仇：三四个势力，各一句话")
    ceiling: str = Field(description="天花板有多高：这张地图上最强的是谁、强到什么程度")
    rules: str = Field(description="这里特有的规矩：能生出剧情的规矩，一两条")
    start: str = Field(description="主角在这张地图上从哪一层起步、处境如何")
    gains: str = Field(description="这里能拿到什么：机缘、地位、名声、资源，让主角有理由在这里拼")


class FarMap(Lenient):
    name: str = Field(description="地图名")
    line: str = Field(default="", description="一句话：那里大概是什么样；还没想好就留空")


class WorldDraft(Lenient):
    """世界、第一张地图和这里的人：近处写细，远处只留影子。"""

    surface: str = Field(
        description="世界的表里：超自然的力量是公开的还是藏着的，普通人知道多少；这决定主角能不能公开出手，30-80 字"
    )
    power: str = Field(
        description="力量规则：升级靠什么；限制和代价；低阶几层叫什么、差距多大（越一级有多难）；往上的层级写到再定，80-200 字"
    )
    first_map: MapDraft = Field(description="第一张地图：要小而具体")
    trouble: str = Field(description="开篇压着主角的小麻烦：是谁（人物表里的姓名）、怎么压着他，一两句")
    opponent: str = Field(
        description="这一段的大对手：是谁（人物表里的姓名）、想要什么、为什么和主角撞上、手里有什么牌、会怎么谋划；他比主角强，会先赢一次，60-120 字"
    )
    far_maps: list[FarMap] = Field(
        default_factory=list, description="后面几张地图：沿着舞台阶梯写名字和一句话，可以只有名字，也可以空着"
    )
    shadow: str = Field(
        description="终极敌人的影子：前期以什么方式露一面——传说、阴影或代理人，一两句；具体是谁写到再定"
    )
    mystery: str = Field(
        description="核心谜团的谜面：读者从开局就好奇的那个问题，常常就是主角长线追求里的谜；谜底现在不用定"
    )
    world_entries: list[WorldEntryDraft] = Field(
        description="设定条目，4-8 条，写手写正文时查：力量体系、第一张地图上的势力和地点、核心规则；远处的东西写到再定"
    )
    characters: list[CharacterDraft] = Field(
        description="这里的人：主角、主角卡里在乎的人、开篇的小麻烦、这一段的大对手，以及第一段会登场的女主、伙伴、导师；要紧的人物七八个以内"
    )
    relationships: list[RelationshipDraft] = Field(
        default_factory=list, description="人物之间的重要关系；每个人和主角之间的张力都要写进来"
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("第一张地图谁说了算、这一段的对手是谁、主角身边有谁")


class OpeningPlan(Lenient):
    scene: str = Field(description="第一章从哪个场面切入：从冲突或异常切入，不从背景介绍开始，40-80 字")
    pressure: str = Field(description="前 3 章主角被什么压着，30-60 字")
    first_win: str = Field(description="第一个小爽点：落在第几章、是什么，30-60 字")
    finger: str = Field(description="金手指第几章露头、怎么露，30-60 字")
    hook: str = Field(description="第 3 章结尾的钩子：停在什么悬念上，30-60 字")


class SegmentDraft(Lenient):
    """第一段怎么走与全书方向：开篇、这一段的目标、读者等什么、揭开什么、终点，以及结局大概往哪去。"""

    opening: OpeningPlan = Field(description="开篇：前 3 章怎么写")
    goal: str = Field(
        description="这一段的目标：主角这一段想做成的那件事，要具体，有期限或有对手，如「三个月后的外门大比拿到名额」，不能是「变强」，30-60 字"
    )
    goal_link: str = Field(description="做成它为什么能离长线追求更近，一句话")
    wait: ExpectationDraft = Field(
        description="这一段让读者等什么：一件读者明确在等的事（约定、比试、倒计时、要揭穿的身份），在终点前后兑现；它就是这一段的长线期待"
    )
    reveal: str = Field(description="这一段揭开什么：核心谜团露出哪一角，同时冒出什么新问题，40-80 字")
    secrets: list[SecretDraft] = Field(default_factory=list, description="这一段用得到的信息差（谁知道什么），2-6 条")
    nodes: list[StoryNodeDraft] = Field(
        description="节点，按顺序：第一个是开篇；第二个是这一段的终点，也是这一段的最高潮；作者已经想到的远景节点跟在后面（没有就不写）；最后一个是结局"
    )
    core_conflict: str = Field(description="贯穿全书的核心矛盾：长线追求和最大的阻碍")
    theme: str = Field(description="这本书最终想表达什么，一句话")
    protagonist_arc: str = Field(description="主角的成长弧线：从什么样的人变成什么样的人，和主角卡的成长终点一致")
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这一段的目标和终点是什么、第一段怎么兑现核心卖点、结局大概往哪去")


class SegmentVolumesDraft(Lenient):
    """这一段分几卷、几条线在这一段走到哪一步、人物什么时候登场。"""

    volumes: list[VolumeDraft] = Field(
        description="这一段的分卷卡片，通常 1-3 卷，卷号接着分卷提示往下编；每卷都走向这一段的终点，最后一卷写到终点"
    )
    threads: list[ThreadDraft] = Field(
        description="线索，3-8 条：一条主线，再配感情线、反派线、谜团线、成长线；已有的线沿用原名，节拍只排这一段的几卷"
    )
    anchors: list[NodeAnchorDraft] = Field(
        default_factory=list, description="人物出场：要紧人物各自在哪个节点前后登场、确认关系、翻脸、高光或退场"
    )
    decisions: list[AuthorChoice] = decisions_field()
    remark: str = remark_field("这一段分几卷、每卷写到哪、感情线什么时候进场")


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
    chapter_count: int = Field(ge=3, le=40, description="预计章数，通常 5-15")
    goal: str = Field(description="这一段主角要做成什么")
    conflict: str = Field(description="阻碍与冲突来自哪里；对手怎么谋划")
    climax: str = Field(description="高潮场面与爽点：主角怎么破局，读者爽在哪里")
    outcome: str = Field(description="结果，以及给下一段留下的钩子")
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
        default="", description="这一卷想做成什么：主角这一卷的目标，要具体；说清它是这一段目标的哪一步，30-60 字"
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
    remark: str = remark_field("这一段的节奏怎么安排、哪一章最燃")


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
    abilities: str = Field(default="", description="能力或修为的最新情况；没变就留空")
    is_alive: bool = Field(default=True, description="本章结束时是否还活着")


class NewCharacter(Lenient):
    name: str = Field(description="姓名")
    role_type: Literal["主角", "女主", "男主", "配角", "反派", "龙套"] = Field(default="配角", description="角色定位")
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
SetupTarget = Literal["concept", "protagonist", "world", "segment", "volumes", "first_volume"]
SETUP_TARGET_DESC = (
    "concept 定调 / protagonist 主角卡 / world 世界与人 / segment 第一段的走向（开篇、目标、期待、揭晓、节点与全书方向）"
    " / volumes 第一段的分卷、线索与人物出场 / first_volume 第一卷卷纲"
)


class ReviewIssue(Lenient):
    target: SetupTarget = Field(description="问题出在哪部分：" + SETUP_TARGET_DESC)
    question: str = Field(
        default="", description="对应哪道必答题：填【这次审什么】里给的题目键，如 drive；对不上就留空"
    )
    problem: str = Field(description="具体问题，指出原文位置")
    suggestion: str = Field(description="怎么改")
    severity: Literal["high", "medium", "low"] = Field(description="严重程度")


class SetupCritique(Lenient):
    verdict: Literal["pass", "revise"] = Field(description="pass：可以交给作者；revise：有必须修改的问题")
    highlights: list[str] = Field(default_factory=list, description="写得好的地方，1-3 条")
    issues: list[ReviewIssue] = Field(default_factory=list, description="问题清单，按严重程度排序")
    remark: str = remark_field()


class UnlockRequest(Lenient):
    target: SetupTarget = Field(description="要解锁的部分：" + SETUP_TARGET_DESC)
    reason: str = Field(description="为什么要解锁、准备怎么改，一两句")


class RevisionTriage(Lenient):
    """主编读完意见后，决定改哪些部分、怎么改。"""

    concept_instructions: str = Field(
        default="", description="对定调（定位、一句话故事、卖点、核心循环、基调、篇幅与书名）的修改要求；不需要改则留空"
    )
    protagonist_instructions: str = Field(
        default="",
        description="对主角卡（起点、驱动力、性格与底线、金手指、软肋与成长终点、在乎的人）的修改要求；不需要改则留空",
    )
    world_instructions: str = Field(
        default="",
        description="对世界与人（世界的表里、力量规则、第一张地图、对手、这里的人、远处的影子）的修改要求，交给设定师；不需要改则留空",
    )
    segment_instructions: str = Field(
        default="",
        description="对第一段的走向（开篇、这一段的目标、读者等什么、揭开什么、信息差、节点与全书方向）的修改要求：改节点要写明第几个节点、怎么改，铁钉节点只有作者点名时才能改；不需要改则留空",
    )
    volumes_instructions: str = Field(
        default="", description="对第一段的分卷、线索和人物出场的修改要求；不需要改则留空"
    )
    first_volume_instructions: str = Field(
        default="", description="对第一卷卷纲（这一卷想做成什么、卷首处境、剧情单元）的修改要求；不需要改则留空"
    )
    unlock_requests: list[UnlockRequest] = Field(
        default_factory=list, description="作者的话需要改动作者已确认（锁定）的部分时，在这里提出解锁请求；不需要就留空"
    )
    pinned_overrides: list[int] = Field(
        default_factory=list,
        description="作者这次的话明确点名要改的铁钉节点序号（按提示词里的节点序号）；作者没有点名就留空",
    )
    remark: str = remark_field("你打算怎么落实作者的话")

    def instructions(self) -> dict[str, str]:
        found = {t: getattr(self, f"{t}_instructions", "") for t in SETUP_PARTS}
        return {t: text for t, text in found.items() if text.strip()}


class InterviewQuestion(Lenient):
    question: str = Field(description="问作者的问题，口语化，一句话，不用专业术语")
    options: list[str] = Field(description="2-4 个具体可选的答案，每个 20 字以内，作者点一下就能选")
    recommended: int = Field(default=0, ge=0, description="你推荐的选项序号（从 0 开始）")


class InterviewDraft(Lenient):
    """动笔前主编先问作者几个关键问题。"""

    questions: list[InterviewQuestion] = Field(description="3-5 个问题，只问作者点子里没交代、又会大幅影响整本书的事")
    remark: str = remark_field("为什么要先问这几件事")
