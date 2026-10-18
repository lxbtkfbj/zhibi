"""新建页的类别与标签：只是作者顺手点的选项，作者也能自己写。改内容只改这里。"""

# 篇幅换算章数时用的每章字数；作者在设置里定了每章字数时以设置为准。
DEFAULT_CHAPTER_WORDS = 2500
MAX_TAGS = 10

CHANNELS = [
    {
        "key": "男频",
        "categories": [
            "玄幻", "仙侠", "都市", "历史", "科幻", "悬疑", "游戏",
            "武侠", "奇幻", "诸天无限", "军事", "体育", "轻小说",
        ],
        "tag_groups": [
            {"name": "金手指", "tags": ["系统", "签到", "模拟器", "面板加点", "老爷爷", "重生记忆", "天赋觉醒"]},
            {"name": "主角", "tags": ["苟道", "扮猪吃虎", "无敌", "废柴逆袭", "杀伐果断", "腹黑", "凡人"]},
            {"name": "情节", "tags": ["宗门", "穿越", "重生", "退婚", "争霸", "种田经营", "无限流"]},
            {"name": "风格", "tags": ["爽文", "轻松", "热血", "黑暗", "搞笑", "智斗"]},
        ],
    },
    {
        "key": "女频",
        "categories": [
            "古代言情", "现代言情", "幻想言情", "仙侠奇缘", "悬疑推理",
            "科幻空间", "游戏竞技", "浪漫青春", "衍生同人",
        ],
        "tag_groups": [
            {"name": "人设", "tags": ["大女主", "团宠", "马甲", "白月光", "恶毒女配", "病娇", "霸总"]},
            {"name": "情感", "tags": ["甜宠", "虐恋", "先婚后爱", "追妻火葬场", "破镜重圆", "双强", "救赎"]},
            {"name": "情节", "tags": ["穿书", "快穿", "重生", "宫斗", "宅斗", "种田", "娱乐圈", "豪门"]},
            {"name": "风格", "tags": ["轻松", "爽文", "治愈", "沙雕", "虐心"]},
        ],
    },
]

CHANNEL_KEYS = [channel["key"] for channel in CHANNELS]


def channel_of(genre: str) -> str:
    """按类别找频道；作者自己写的类别找不到就返回空。"""
    for channel in CHANNELS:
        if genre in channel["categories"]:
            return channel["key"]
    return ""


def catalog_text() -> str:
    """给模型看的类别和常见标签。"""
    lines = []
    for channel in CHANNELS:
        lines.append(f"{channel['key']}类别：" + "、".join(channel["categories"]))
        for group in channel["tag_groups"]:
            lines.append(f"{channel['key']}常见标签·{group['name']}：" + "、".join(group["tags"]))
    return "\n".join(lines)
