STATUSES = {"must": "现在要定", "one": "一句话就好", "later": "以后再说"}
STYLES = {"card": "卡片", "ladder": "阶梯", "paragraph": "段落"}
SOURCES = {
    "author": "作者写的",
    "ai": "AI 写的",
    "ai_edited": "AI 写、作者改过",
    "candidate": "从选择里挑的",
    "suggestion": "按建议改的",
    "writing": "写作中记下的",
    "teardown": "拆书拆出来的",
    "migration": "从旧设定迁移的",
    "revert": "退回过",
}
FOCUS_TAGS = ["金手指", "底牌"]  # 「重点」= 定位是主角的角色卡片 + 带这两个标签的条目和角色卡片
COMMON_TAGS = ["金手指", "底牌", "第一卷"]
ROLE_TYPES = ["主角", "女主", "男主", "班底", "对手", "导师", "配角"]
LEGACY_ROLE_TYPES = {"反派": "对手", "龙套": "配角"}  # 旧值保留，显示时按右边

CHARACTER_CATEGORY = {
    "key": "角色卡片",
    "name": "角色卡片",
    "style": "card",
    "hint": "有名有姓、会再出场的人；会说话的器灵、系统人格也算。",
    # (字段名, characters 的列)；顺序就是卡片上的顺序
    "fields": [
        ("姓名", "name"),
        ("别名", "aliases"),
        ("定位", "role_type"),
        ("性别", "gender"),
        ("年龄", "age"),
        ("外貌", "appearance"),
        ("性格与说话方式", "personality"),
        ("身世", "background"),
        ("想要什么", "goal"),
        ("能力", "abilities"),
        ("和主角的关系", "relation"),
        ("备注", "notes"),
    ],
    # 每章更新的状态，设定师写
    "state_fields": [
        ("此刻想要", "want"),
        ("在哪", "location"),
        ("处境", "condition"),
        ("是否活着", "is_alive"),
    ],
}

GOLDFINGER = "金手指"

BUILTIN_CATEGORIES = [
    {
        "key": GOLDFINGER,
        "name": "金手指",
        "style": "paragraph",
        "hint": "主角最大的倚仗：系统、物品、体质、重生记忆……写清是什么、谁知道、能做什么、规矩和限制、代价、怎么变强、来历。一般只有一两条；主角天生的特质也可以单拎出来写在这里。",
    },
    {
        "key": "等级体系",
        "name": "等级体系",
        "style": "ladder",
        "hint": "任何分高低的一串等级：修炼境界、玩家等级、专精、官阶、位份、物品品阶。可以有几套，也可以写「没有」。总说明写清怎么往上升、越级多难、有什么代价；各级写名称和一段介绍，按高低排。",
    },
    {
        "key": "世界与地图",
        "name": "世界与地图",
        "style": "paragraph",
        "hint": "第一条是「世界概况」：什么时代、科技到什么程度；超凡的力量是公开的还是藏着的，普通人知道多少；钱用什么；社会风气。之后是一个个地方：这是什么地方，给人什么感觉；属于哪里；谁说了算；有什么规矩或危险；主角在这里处境如何；这里能得到什么。用得上的写，用不上的不写。",
    },
    {
        "key": "势力划分",
        "name": "势力划分",
        "style": "paragraph",
        "hint": "宗门、家族、国家、公司、公会、队伍、种族：什么组织；想要什么；谁领头、实力多大；和主角是敌是友；内部有什么矛盾。用得上的写，用不上的不写。",
    },
    {
        "key": "物品与功法",
        "name": "物品与功法",
        "style": "paragraph",
        "hint": "能拿到、能学、能传下去的东西：法宝、丹药、道具、装备、功法、技能、血脉传承。写清是什么东西或什么本事；有什么用、有什么限制；从哪来、谁想要它；现在在谁手里。用得上的写，用不上的不写。",
    },
    {
        "key": "往事与秘密",
        "name": "往事与秘密",
        "style": "paragraph",
        "hint": "过去的事和藏着的真相：过去发生了什么，或者藏着什么真相；谁知道、谁不知道；打算什么时候、怎么揭开；和主角有什么关系。用得上的写，用不上的不写。",
    },
    {
        "key": "特殊规则",
        "name": "特殊规则",
        "style": "paragraph",
        "hint": "这个世界特有的机制，如夺舍的限制、通关奖励、驾驭厉鬼的代价、系统规则：管什么；怎么运作；有什么限制和代价；会给故事制造什么麻烦或机会。用得上的写，用不上的不写。",
    },
]

OLD_CATEGORY_MAP = {
    "地理": "世界与地图",
    "势力": "势力划分",
    "力量体系": "等级体系",
    "历史": "往事与秘密",
    "物品": "物品与功法",
    "规则": "特殊规则",
    "其他": "特殊规则",
}

# 各题材常建的条目：只是起点，任务 3 建库时给主编参考
GENRE_DEFAULTS = {
    "玄幻、仙侠": [
        ("等级体系", "修炼境界", "must"),
        ("世界与地图", "世界概况", "must"),
        ("世界与地图", "第一张地图", "must"),
        ("势力划分", "第一张地图上的宗门、家族", "must"),
        ("物品与功法", "丹药、法宝的品阶", "one"),
        ("特殊规则", "货币", "one"),
        ("往事与秘密", "底牌", "must"),
    ],
    "都市": [
        ("特殊规则", "金手指或异能的规矩、藏着还是公开", "must"),
        ("世界与地图", "世界概况", "one"),
        ("势力划分", "公司、家族、圈子", "one"),
        ("往事与秘密", "底牌", "must"),
    ],
    "无限流、网游": [
        ("特殊规则", "游戏或副本规则", "must"),
        ("等级体系", "玩家等级、技能、专精", "must"),
        ("物品与功法", "道具与奖励", "one"),
        ("世界与地图", "世界概况", "one"),
        ("往事与秘密", "底牌：游戏的来历", "must"),
    ],
    "悬疑、灵异": [
        ("特殊规则", "灵异规则、案子从哪来", "must"),
        ("世界与地图", "世界概况", "one"),
        ("势力划分", "警方或处理这类事的机构", "one"),
        ("往事与秘密", "底牌", "must"),
    ],
    "历史、宫斗、官场": [
        ("等级体系", "官阶或位份", "must"),
        ("特殊规则", "规矩与礼法", "must"),
        ("世界与地图", "宫里、府里或朝堂", "must"),
        ("势力划分", "家族、派系", "must"),
        ("往事与秘密", "身世之谜、旧案", "one"),
    ],
}


def normalize_category(value: str) -> str:
    """兼容旧类别；自建类别是否属于当前书由调用方校验。"""
    if value in OLD_CATEGORY_MAP:
        return OLD_CATEGORY_MAP[value]
    if value == CHARACTER_CATEGORY["key"] or value in {item["key"] for item in BUILTIN_CATEGORIES}:
        return value
    return value if value.startswith("custom:") else "特殊规则"


def category_style(category: str, custom: dict[str, str]) -> str:
    """返回设定条目类别固定的样式。"""
    if category == "角色卡片":
        return "card"
    if category == "等级体系":
        return "ladder"
    if category.startswith("custom:"):
        return custom[category]
    return "paragraph"
