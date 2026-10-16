"""第二包任务 1：逐字固定的分段规划上下文与旧书兼容快照。"""

from copy import deepcopy

import pytest

from app.agents.context import (
    format_character,
    format_character_state,
    format_opening,
    format_protagonist,
    format_segment_info,
    format_spine,
    format_unit,
    format_volume_card,
    format_world,
)

PROTAGONIST = {
    "name": "林岚",
    "start": "青石镇最底层的杂役",
    "trigger": "妹妹被带走",
    "pursuit": "找回被偷走的十年记忆",
    "root": "不想再忘记家人",
    "escalation": "从找妹妹到找回全镇的记忆",
    "personality": "谨慎，却见不得人受欺负",
    "style": "先试探，再出手",
    "bottom_line": "不拿无辜的人换线索",
    "voice": "话少，答应就做到",
    "finger": "读出旧物残留的记忆",
    "finger_later": "读出一座城的记忆",
    "flaw": "不肯向别人求助",
    "arc_end": "学会把后背交给同伴",
    "cared": [
        {"name": "林小雨", "relation": "相依为命的妹妹", "why": "她替自己记着过去"},
        {"name": "老周", "relation": "师父", "why": "收留过兄妹"},
    ],
    "interlock": "接委托读旧物，破案带回自己的记忆碎片",
}

WORLD = {
    "surface": "凡人不知道记忆可以买卖",
    "power": "每读一次记忆就失去一段自己的记忆",
    "maps": [
        {
            "name": "青石镇",
            "powers": "商会与镇守府争夺旧物",
            "ceiling": "二阶读忆师",
            "rules": "日落后不得买卖",
            "start": "杂役",
            "gains": "第一块记忆碎片",
        },
        {"name": "旧城", "powers": "守城人", "ceiling": "三阶读忆师"},
    ],
    "trouble": "交不上欠租",
    "opponent": "掌握买卖账本的商会会长",
    "far_maps": [{"name": "外门", "line": "门票是一段记忆"}, {"name": "北境寒原", "line": ""}],
    "shadow": "有人收走每座城的记忆",
    "mystery": "谁偷走了那十年",
    "mystery_answer": "是未来的自己",
}


def test_protagonist_complete_snapshot():
    assert format_protagonist(PROTAGONIST, {"want": "先拿回妹妹的木牌"}) == (
        "姓名：林岚\n起点：青石镇最底层的杂役\n驱动力\n"
        "- 开局动机：妹妹被带走\n- 长线追求：找回被偷走的十年记忆\n"
        "- 情感根源：不想再忘记家人\n- 怎么升级：从找妹妹到找回全镇的记忆\n"
        "性格：谨慎，却见不得人受欺负\n做事风格：先试探，再出手\n底线：不拿无辜的人换线索\n"
        "说话方式：话少，答应就做到\n金手指·现在：读出旧物残留的记忆\n"
        "金手指·以后：读出一座城的记忆\n软肋：不肯向别人求助\n成长的终点：学会把后背交给同伴\n"
        "在乎的人：林小雨（相依为命的妹妹：她替自己记着过去）；老周（师父：收留过兄妹）\n"
        "三件套怎么咬合：接委托读旧物，破案带回自己的记忆碎片\n此刻想要：先拿回妹妹的木牌"
    )


def test_protagonist_unplanned_and_empty_values_snapshot():
    assert format_protagonist({"name": "林岚", "escalation": "", "finger_later": "", "cared": []}) == (
        "姓名：林岚\n驱动力\n- 怎么升级：写到再定\n金手指·以后：写到再定"
    )
    assert format_protagonist({"name": "林岚"}, {"want": ""}) == (
        "姓名：林岚\n驱动力\n- 怎么升级：写到再定\n金手指·以后：写到再定"
    )


def test_protagonist_legacy_snapshots():
    assert format_protagonist({}, {"name": "林岚", "role_type": "主角", "goal": "找人"}, "能读旧物") == (
        "（这本书开书时还没有主角卡）\n【林岚】主角\n目标：找人\n主角钩子：能读旧物"
    )
    assert format_protagonist({}) == "（这本书开书时还没有主角卡）"
    assert format_protagonist({}, hook="旧书的钩子") == "（这本书开书时还没有主角卡）\n主角钩子：旧书的钩子"


def test_world_complete_snapshot():
    assert format_world(WORLD) == (
        "世界的表里：凡人不知道记忆可以买卖\n力量规则：每读一次记忆就失去一段自己的记忆\n"
        "地图「青石镇」：谁说了算：商会与镇守府争夺旧物；天花板：二阶读忆师；特有的规矩：日落后不得买卖；"
        "主角从这里起步：杂役；能拿到：第一块记忆碎片\n"
        "地图「旧城」：谁说了算：守城人；天花板：三阶读忆师\n"
        "第一段·开篇的小麻烦：交不上欠租\n第一段·大对手：掌握买卖账本的商会会长\n"
        "后面的地图：外门（门票是一段记忆） → 北境寒原\n终极敌人的影子：有人收走每座城的记忆\n"
        "核心谜团：谜面：谁偷走了那十年；谜底：是未来的自己"
    )


def test_world_with_lore_lists_snapshot():
    world = {
        "surface": "超凡隐藏在旧物里",
        "world_entries": [{"category": "规则", "name": "读忆", "content": "碰到旧物才能读"}],
        "characters": [
            {"name": "林岚", "role_type": "主角", "goal": "找到妹妹", "want": "拿到木牌"},
            {"name": "林小雨", "role_type": "妹妹", "personality": "机灵"},
        ],
        "relationships": [{"source": "林岚", "target": "林小雨", "kind": "兄妹", "description": "相依为命"}],
    }
    assert format_world(world) == (
        "世界的表里：超凡隐藏在旧物里\n后面的地图：写到再定\n核心谜团：谜底：写到再定\n\n"
        "设定条目：\n- [规则] 读忆：碰到旧物才能读\n\n"
        "人物：\n【林岚】主角\n目标：找到妹妹\n此刻想要：拿到木牌\n\n【林小雨】妹妹\n性格：机灵\n\n"
        "人物关系：\n- 林岚 与 林小雨：兄妹。相依为命"
    )


def test_world_unplanned_maps_answer_and_legacy_snapshots():
    assert format_world({"far_maps": [], "mystery": "妹妹去了哪里", "mystery_answer": ""}) == (
        "后面的地图：写到再定\n核心谜团：谜面：妹妹去了哪里；谜底：写到再定"
    )
    assert format_world({"far_maps": [{"name": "北境", "line": ""}], "mystery_answer": "在北境"}) == (
        "后面的地图：北境\n核心谜团：谜底：在北境"
    )
    assert format_world({}) == "（这本书开书时还没有「世界与地图」）"


def test_first_segment_world_fallback_snapshot():
    segment = {
        "number": 1,
        "status": "confirmed",
        "planned_at": 0,
        "map": "",
        "trouble": "",
        "opponent": "",
        "goal": "找到妹妹的去向",
        "goal_link": "她记着丢失的那十年",
        "wait": "拿回妹妹的木牌",
        "reveal": "木牌来自北境",
        "finale": False,
    }
    before = deepcopy(segment)
    assert format_segment_info(segment, WORLD) == (
        "第 1 段（开书时规划）\n地图：青石镇\n开篇的小麻烦：交不上欠租\n"
        "大对手：掌握买卖账本的商会会长\n这一段的目标：找到妹妹的去向\n"
        "为什么离长线追求更近：她记着丢失的那十年\n读者在等：拿回妹妹的木牌\n这一段揭开什么：木牌来自北境"
    )
    assert segment == before
    assert format_segment_info({"number": 1, "planned_at": 0}, {"maps": []}) == "第 1 段（开书时规划）"
    assert (
        format_segment_info(
            {"number": 1, "planned_at": 0, "map": "旧城", "trouble": "追兵", "opponent": "守城人"}, WORLD
        )
        == "第 1 段（开书时规划）\n地图：旧城\n开篇的小麻烦：追兵\n大对手：守城人"
    )


def test_second_segment_confirmed_snapshot():
    assert format_segment_info(
        {
            "number": 2,
            "status": "confirmed",
            "planned_at": 35,
            "map": "旧城",
            "opponent": "守城人",
            "goal": "换到北境的路引",
            "carried": "会长临死前的提醒",
            "pursuit": "查清谁在收集记忆",
            "finger_next": "同时读两件旧物",
            "answers": "路引里藏着失踪者的名字",
        },
        WORLD,
    ) == (
        "第 2 段（写到第 35 章时规划，作者确认）\n地图：旧城\n大对手：守城人\n"
        "这一段的目标：换到北境的路引\n上一段留下的线头：会长临死前的提醒\n"
        "主角的追求：查清谁在收集记忆\n金手指下一阶段：同时读两件旧物\n定下的谜底：路引里藏着失踪者的名字"
    )


def test_third_segment_auto_finale_snapshot():
    assert format_segment_info(
        {"number": 3, "status": "auto", "planned_at": 88, "map": "北境", "goal": "把记忆还给所有人", "finale": True}
    ) == (
        "第 3 段（写到第 88 章时规划，按设置自动通过）\n地图：北境\n这一段的目标：把记忆还给所有人\n"
        "这是收尾段：开始收线，揭开核心谜团，往结局方向走。"
    )


def test_spine_segment_and_future_nodes_snapshot():
    spine = {
        "core_conflict": "被偷的记忆",
        "theme": "找回",
        "protagonist_arc": "从独行到信任",
        "nodes": [
            {"kind": "opening", "title": "失踪", "event": "妹妹被带走", "volume": 1},
            {
                "kind": "milestone",
                "title": "夺回木牌",
                "event": "击败会长",
                "volume": 2,
                "consequence": "得到北境线索",
                "segment": {"number": 1, "goal": "找到妹妹", "wait": "拿回木牌", "reveal": "木牌的来历", "map": ""},
            },
            {"kind": "milestone", "title": "北境", "event": "走出风雪", "volume": 4},
            {"kind": "ending", "title": "归来", "event": "还回记忆"},
        ],
    }
    before = deepcopy(spine)
    assert format_spine(spine, WORLD) == (
        "核心矛盾：被偷的记忆\n主题：找回\n主角成长弧：从独行到信任\n关键节点：\n"
        "节点 1「失踪」· 开篇［暂定｜约第 1 卷］发生：妹妹被带走\n"
        "节点 2「夺回木牌」［暂定｜约第 2 卷］发生：击败会长\n  之后变成：得到北境线索\n"
        "  这是第 1 段的终点：目标：找到妹妹；读者在等：拿回木牌；揭开：木牌的来历；地图：青石镇\n"
        "节点 3「北境」［暂定｜约第 4 卷｜这一段写到再定］发生：走出风雪\n"
        "节点 4「归来」· 结局［暂定｜这一段写到再定］发生：还回记忆"
    )
    assert spine == before


def test_spine_marks_only_nodes_after_last_planned_segment():
    nodes = [
        {"title": "第一段", "segment": {"number": 1, "map": "小镇"}},
        {"title": "中途的节点"},
        {"title": "第二段", "segment": {"number": 2, "goal": "出城"}},
        {"title": "远处"},
    ]
    assert format_spine({"nodes": nodes}, WORLD) == (
        "核心矛盾：\n主题：\n主角成长弧：\n关键节点：\n"
        "节点 1「第一段」［暂定］发生：\n  这是第 1 段的终点：地图：小镇\n"
        "节点 2「中途的节点」［暂定］发生：\n"
        "节点 3「第二段」［暂定］发生：\n  这是第 2 段的终点：目标：出城\n"
        "节点 4「远处」［暂定｜这一段写到再定］发生："
    )


@pytest.mark.parametrize("extra", [{}, {"segment": None}])
def test_spine_old_book_byte_exact_snapshot(extra):
    assert format_spine(
        {
            "core_conflict": "旧矛盾",
            "theme": "旧主题",
            "protagonist_arc": "旧成长",
            "nodes": [
                {"kind": "opening", "title": "开篇", "event": "出门", "volume": 1, **extra},
                {
                    "kind": "milestone",
                    "title": "归来",
                    "status": "pinned",
                    "event": "回家",
                    "prerequisite": "找到路",
                    "consequence": "团圆",
                    **extra,
                },
                {"kind": "ending", "title": "", "status": "empty", **extra},
            ],
        },
        WORLD,
    ) == (
        "核心矛盾：旧矛盾\n主题：旧主题\n主角成长弧：旧成长\n关键节点：\n"
        "节点 1「开篇」· 开篇［暂定｜约第 1 卷］发生：出门\n"
        "节点 2「归来」［铁钉］发生：回家\n  之前得先有：找到路\n  之后变成：团圆\n"
        "节点 3「（留空）」· 结局［留空］这里还没定"
    )


def test_opening_snapshot():
    assert format_opening(
        {
            "scene": "当铺失火",
            "pressure": "被逼还债",
            "first_win": "找回木牌",
            "finger": "读出木牌记忆",
            "hook": "妹妹还活着",
        }
    ) == (
        "【开篇落地】第一个单元要把开篇写进去，第一个单元出章纲时照这个来：\n"
        "- 第 1 章的切入场面：当铺失火\n- 前 3 章主角被什么压着：被逼还债\n"
        "- 第一个小爽点：找回木牌\n- 金手指露头：读出木牌记忆\n- 第 3 章结尾的钩子：妹妹还活着"
    )
    assert format_opening({"scene": "当铺失火", "hook": ""}) == (
        "【开篇落地】第一个单元要把开篇写进去，第一个单元出章纲时照这个来：\n- 第 1 章的切入场面：当铺失火"
    )


@pytest.mark.parametrize(
    "opening", [None, {}, {key: "" for key in ("scene", "pressure", "first_win", "finger", "hook")}]
)
def test_empty_opening_snapshot(opening):
    assert format_opening(opening) == ""


CHARACTER = {
    "name": "林岚",
    "role_type": "主角",
    "gender": "男",
    "age": "十八",
    "appearance": "旧衣",
    "personality": "谨慎",
    "background": "杂役",
    "abilities": "读忆",
    "goal": "找到妹妹",
    "location": "当铺",
    "condition": "受伤",
    "is_alive": False,
}
CHARACTER_TEXT = "【林岚】主角\n男，十八，旧衣\n性格：谨慎\n背景：杂役\n能力：读忆\n目标：找到妹妹\n当前：当铺，受伤"
CHARACTER_STATE_TEXT = "【林岚】主角；已死亡；位置：当铺；状态：受伤；实力：读忆；目标：找到妹妹"

VOLUME = {
    "index": 1,
    "title": "青石镇",
    "chapter_count": 30,
    "stage": "小镇",
    "summary": "寻找线索",
    "goal": "拿回木牌",
    "climax": "击败会长",
    "antagonist": "会长",
    "power_range": "一阶",
    "thread_beats": [{"thread": "记忆", "beat": "木牌的来源"}],
    "new_characters": ["老周"],
    "target_node": 2,
    "target_node_title": "夺回木牌",
    "reaches_node": True,
}
VOLUME_TEXT = (
    "第1卷《青石镇》约 30 章\n舞台：小镇\n概要：寻找线索\n卷末目标：拿回木牌\n高潮：击败会长\n"
    "主要对手：会长\n主角实力：一阶\n推进线索：记忆——木牌的来源\n新登场：老周\n走向：节点 2「夺回木牌」（本卷发生）"
)

UNIT = {
    "index": 1,
    "title": "当铺",
    "chapter_count": 3,
    "goal": "还债",
    "conflict": "没有钱",
    "climax": "破解旧案",
    "outcome": "得到酬劳",
    "key_events": ["接委托", "读旧物"],
    "thread_beats": [{"thread": "记忆", "beat": "拿到碎片"}],
    "tropes": ["扮弱"],
    "resolution": "抢先说出真相",
    "foreshadow_actions": [{"ref": "F1", "action": "埋下", "detail": "留下一道刻痕"}],
    "reveals": [{"ref": "S1", "to": "读者", "how": "展示木牌"}],
}
UNIT_TEXT = (
    "单元1「当铺」约 3 章\n目标：还债\n冲突：没有钱\n高潮：破解旧案\n结果：得到酬劳\n"
    "关键事件：接委托 → 读旧物\n推进线索：记忆——拿到碎片\n套路：扮弱；破局：抢先说出真相\n"
    "伏笔：埋下F1 留下一道刻痕\n揭晓：S1 揭给 读者——展示木牌"
)


def test_existing_formatters_new_lines_snapshot():
    assert format_character({**CHARACTER, "want": "拿回木牌"}) == CHARACTER_TEXT.replace(
        "\n当前：", "\n此刻想要：拿回木牌\n当前："
    )
    assert format_character_state({**CHARACTER, "want": "拿回木牌"}) == CHARACTER_STATE_TEXT + "；此刻想要：拿回木牌"
    assert format_volume_card({**VOLUME, "want": "找到妹妹的去向", "pressure": "债主逼门"}) == VOLUME_TEXT.replace(
        "\n舞台：", "\n这一卷想做成：找到妹妹的去向\n卷首处境：债主逼门\n舞台："
    )
    assert format_unit({**UNIT, "loop": "接委托，读旧物，破案"}) == UNIT_TEXT.replace(
        "\n关键事件：", "\n核心循环：接委托，读旧物，破案\n关键事件："
    )


@pytest.mark.parametrize("value", [None, ""])
def test_existing_formatters_empty_new_fields_byte_exact_snapshot(value):
    assert format_character(CHARACTER) == CHARACTER_TEXT
    assert format_character({**CHARACTER, "want": value}) == CHARACTER_TEXT
    assert format_character_state(CHARACTER) == CHARACTER_STATE_TEXT
    assert format_character_state({**CHARACTER, "want": value}) == CHARACTER_STATE_TEXT
    assert format_volume_card(VOLUME) == VOLUME_TEXT
    assert format_volume_card({**VOLUME, "want": value, "pressure": value}) == VOLUME_TEXT
    assert format_unit(UNIT) == UNIT_TEXT
    assert format_unit({**UNIT, "loop": value}) == UNIT_TEXT
