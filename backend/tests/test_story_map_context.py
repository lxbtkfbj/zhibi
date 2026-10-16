"""第一包的数据格式化契约：旧检查点和新数据都输出稳定的中文上下文。"""

from app.agents.context import (
    foreshadow_code,
    format_foreshadowing,
    format_lore,
    format_secrets,
    format_spine,
    format_unit,
    format_volume_card,
)
from app.agents.planning import attach_new_foreshadowings, ref_seq, secret_seq
from app.graphs.book_setup import first_volume_blocks
from app.services.writing_context import format_chapter_outline


def test_spine_snapshot_all_states_and_legacy():
    nodes = [
        {
            "kind": "opening",
            "title": "开篇",
            "event": "捡到青灯",
            "volume": 1,
            "status": "pencil",
            "consequence": "看见寿命",
        },
        {
            "kind": "milestone",
            "title": "回幻妖界",
            "event": "回乡",
            "volume": 2,
            "status": "pinned",
            "prerequisite": "取得钥匙",
            "consequence": "旧敌现身",
        },
        {"kind": "milestone", "title": "", "volume": 4, "status": "empty"},
        {"kind": "ending", "title": "结局", "event": "还灯", "status": "pencil"},
    ]
    assert format_spine({"core_conflict": "借寿", "theme": "代价", "protagonist_arc": "放下", "nodes": nodes}) == (
        "核心矛盾：借寿\n主题：代价\n主角成长弧：放下\n关键节点：\n"
        "节点 1「开篇」· 开篇［暂定｜约第 1 卷］发生：捡到青灯\n  之后变成：看见寿命\n"
        "节点 2「回幻妖界」［铁钉｜约第 2 卷］发生：回乡\n  之前得先有：取得钥匙\n  之后变成：旧敌现身\n"
        "节点 3「（留空）」［留空｜约第 4 卷］这里还没定\n"
        "节点 4「结局」· 结局［暂定］发生：还灯"
    )
    legacy = {
        "opening": "捡灯",
        "milestones": [{"index": 2, "title": "飞升", "event": "上界", "change": "换地图", "volume": 3}],
        "ending": "还灯",
    }
    text = format_spine(legacy)
    assert "节点 1「开篇」" in text and "节点 2「飞升」［暂定｜约第 3 卷］发生：上界" in text
    assert "之后变成：换地图" in text and "节点 3「结局」· 结局" in text
    assert "nodes" not in legacy
    assert format_spine({}) == "（暂无）"


def test_ledger_snapshot_and_shared_reference_parser():
    f = {
        "seq": 8,
        "kind": "期待",
        "span": "中",
        "status": "planted",
        "plant_volume": 2,
        "payoff_volume": 3,
        "description": "三年之约",
        "plant_plan": "立约",
        "payoff_plan": "胜过对手",
    }
    assert foreshadow_code(f) == "E8"
    assert foreshadow_code({"seq": 3}) == "F3"
    assert (
        format_foreshadowing(f)
        == "- E8［期待·中·已立·第2卷立、第3卷兑现］读者在等：三年之约（立：立约；兑现：胜过对手）"
    )
    assert (
        format_foreshadowing({**f, "kind": "伏笔", "seq": 3, "span": "长"})
        == "- F3［伏笔·长·已埋·第2卷埋、第3卷收］三年之约（埋：立约；收：胜过对手）"
    )
    assert [ref_seq(x) for x in ("E8", "F3", "S2")] == [8, 3, None]
    assert [secret_seq(x) for x in ("S2", "F3", "")] == [2, None, None]
    units, _ = attach_new_foreshadowings([{"index": 1}], [{**f, "plant_unit": 1, "payoff_unit": 1}], 2)
    assert units[0]["foreshadow_actions"] == [
        {"ref": "E8", "action": "埋下", "detail": "立约"},
        {"ref": "E8", "action": "回收", "detail": "胜过对手"},
    ]


def test_secret_and_lore_snapshot():
    secrets = [
        {
            "seq": 2,
            "title": "主角的真实修为",
            "truth": "已结丹",
            "reader_knows": "知道",
            "knowers": [
                {"name": "林岚", "since_chapter": None, "how": "开书设定"},
                {"name": "赵青", "since_chapter": 35, "how": "偷听"},
            ],
            "reveal_plan": "大比时揭开",
        }
    ]
    text = "- S2「主角的真实修为」［隐藏｜读者：知道］真相：已结丹\n  知道的人：林岚（开书时）、赵青（第 35 章，偷听）；计划：大比时揭开"
    assert format_secrets(secrets) == text
    assert format_secrets([]) == "（暂无）"
    assert "读者：未标注" in format_secrets([{"seq": 1, "truth": "旧秘密"}])
    lore = {
        "characters": [{"name": "林岚", "role_type": "主角"}],
        "anchors": [{"character": "林岚", "node": 3, "node_title": "回幻妖界", "kind": "登场", "note": "回乡"}],
        "secrets": secrets,
    }
    assert format_lore(lore) == (
        "世界观：\n\n\n人物：\n【林岚】主角\n\n人物关系：\n（暂无）\n\n人物锚点：\n"
        "- 节点 3「回幻妖界」：林岚 登场——回乡\n\n信息差：\n" + text
    )
    old = format_lore({"characters": [{"name": "林岚", "secrets": ["旧秘密"]}]})
    assert "信息差：\n- S1" in old and "秘密：旧秘密" not in old
    mixed = format_lore({**lore, "characters": [{"name": "林岚", "secrets": ["已结丹", "新秘密"]}]})
    assert mixed.count("真相：已结丹") == 1 and "真相：新秘密" in mixed


def test_volume_unit_and_chapter_fields():
    assert (
        format_volume_card(
            {"index": 2, "title": "上界", "target_node": 5, "target_node_title": "飞升神界", "reaches_node": True}
        )
        == "第2卷《上界》\n走向：节点 5「飞升神界」（本卷发生）"
    )
    reveals = [{"ref": "S2", "to": "柳如烟", "how": "当面展示"}]
    assert format_unit({"reveals": reveals}).endswith("揭晓：S2 揭给 柳如烟——当面展示")
    for emotion, label in (
        (-2, "-2 憋屈压抑"),
        (-1, "-1 偏压"),
        (0, "0 平稳或悬着"),
        (1, "+1 偏扬"),
        (2, "+2 爆发爽快"),
    ):
        text = format_chapter_outline({"emotion": emotion, "mood": "爽", "reveals": reveals})
        assert f"情绪：{label}（爽）" in text
        assert text.endswith("揭晓：S2 揭给 柳如烟——当面展示")
    assert "情绪" not in format_chapter_outline({"goal": "旧章纲"})


def test_first_volume_context_reads_new_opening():
    blocks = first_volume_blocks({"segment": {"nodes": [{"kind": "opening", "event": "新的开篇"}]}})
    assert "开篇设计：新的开篇" in blocks["story_so_far"]
