"""主角卡、世界与地图、段规划的手动编辑模型；不参与模型生成。"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


class CardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def known_fields(cls, value):
        if isinstance(value, dict):
            for key in value:
                if key not in cls.model_fields:
                    raise PydanticCustomError("extra_forbidden", "不认识的字段：{field}", {"field": key})
        return value


class CaredPerson(CardPatch):
    name: str = ""  # 姓名
    relation: str = ""  # 和主角的关系
    why: str = ""  # 主角为什么在乎他


class ProtagonistPatch(CardPatch):
    name: str = ""  # 主角姓名
    start: str = ""  # 身份、开局处境、读者为什么会代入
    trigger: str = ""  # 开局动机
    pursuit: str = ""  # 长线追求
    root: str = ""  # 情感根源
    escalation: str = ""  # 驱动力怎么升级
    personality: str = ""  # 核心性格加一个反差
    style: str = ""  # 做事风格
    bottom_line: str = ""  # 绝不做的事
    voice: str = ""  # 说话方式
    finger: str = ""  # 金手指现在的能力，或最大的优势
    finger_later: str = ""  # 金手指以后的成长
    flaw: str = ""  # 软肋
    arc_end: str = ""  # 成长的终点
    cared: list[CaredPerson] = Field(default_factory=list)  # 在乎的人
    interlock: str = ""  # 驱动力、金手指、核心循环怎么咬合


class DetailedMap(CardPatch):
    name: str = ""  # 地图名
    powers: str = ""  # 谁说了算、谁和谁有仇
    ceiling: str = ""  # 天花板有多高
    rules: str = ""  # 这里特有的规矩
    start: str = ""  # 主角从哪一层起步
    gains: str = ""  # 这里能拿到什么


class FarMap(CardPatch):
    name: str = ""  # 地图名
    line: str = ""  # 一句话，可以空


class WorldPatch(CardPatch):
    surface: str = ""  # 世界的表里
    power: str = ""  # 力量规则
    maps: list[DetailedMap] = Field(default_factory=list)  # 已经写细的地图
    trouble: str = ""  # 第一段开篇压着主角的小麻烦
    opponent: str = ""  # 第一段的大对手
    far_maps: list[FarMap] = Field(default_factory=list)  # 还没写细的远处地图
    shadow: str = ""  # 终极敌人的影子
    mystery: str = ""  # 核心谜团的谜面
    mystery_answer: str = ""  # 核心谜团的谜底


class OpeningPatch(CardPatch):
    scene: str = ""  # 第一章的切入场面
    pressure: str = ""  # 前 3 章主角被什么压着
    first_win: str = ""  # 第一个小爽点
    finger: str = ""  # 金手指露头
    hook: str = ""  # 第 3 章结尾的钩子


class SegmentPatch(CardPatch):
    # 段号、确认状态、规划章数和收尾标记由程序维护，不允许手动传入。
    map: str = ""  # 这一段在哪张地图
    trouble: str = ""  # 开篇压着主角的小麻烦
    opponent: str = ""  # 这一段的大对手
    goal: str = ""  # 这一段的目标
    goal_link: str = ""  # 为什么离长线追求更近
    wait: str = ""  # 这一段让读者等什么
    reveal: str = ""  # 这一段揭开什么
    opening: OpeningPatch | None = None  # 只有第一段有开篇落地
    carried: str = ""  # 上一段留下的线头
    pursuit: str = ""  # 主角的追求
    finger_next: str = ""  # 金手指下一阶段
    answers: str = ""  # 定下的谜底
