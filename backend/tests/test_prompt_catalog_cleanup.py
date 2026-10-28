"""提示词页整理：目录顺序、份数、逐字名称与说明。"""

from collections import Counter

from app.prompts import catalog

GROUPS = ["角色与规矩", "聊天", "开书", "规划", "设定库", "写作", "审稿与入库", "题材打法", "拆书", "拆书精髓"]


def test_catalog_group_order_counts_and_future_groups(monkeypatch):
    rows = catalog.entries()
    assert list(dict.fromkeys(row[2] for row in rows)) == GROUPS
    assert dict(Counter(row[2] for row in rows)) == dict(zip(GROUPS, [7, 10, 7, 8, 5, 4, 5, 2, 14, 15], strict=True))
    monkeypatch.setattr(catalog, "CATALOG", [*catalog.CATALOG, ("future", "未来", "新组", "chief", "以后")])
    assert catalog.entries()[-1][0] == "future"


def test_chat_order_and_exact_renamed_descriptions():
    assert [row[0] for row in catalog.entries() if row[2] == "聊天"] == [
        "chat_agent",
        "chat_reply",
        "chat_voice",
        "chat_manner",
        "chat_material",
        "chat_summary",
        "feedback_memory",
        "chat_plan",
        "requirements_tidy",
        "library_route",
    ]
    for name, title, description in [
        (
            "chat_agent",
            "群聊：自己查、自己动手",
            "群聊里点名设定师、写手、审稿，模型又能调工具时，这一路的开场和规矩：怎么查、怎么改、怎么记。主编答群聊改用「预设管理」里的预设",
        ),
        (
            "chat_reply",
            "私聊和重新回答",
            "私聊、重新回答，还有模型调不了工具时的群聊，这一路的开场和规矩：只说话，不改书；实际用聊天对象的角色",
        ),
        ("chat_teardown", "群聊回答", "拆的书里的群聊，这一路的开场和规矩：只答不改、怎么查资料"),
    ]:
        row = catalog.entry(name)
        assert (row[1], row[4]) == (title, description)


def test_preset_route_descriptions_match_the_six_approved_sentences():
    descriptions = {
        "voice_chief": "私聊里主编的身份、称呼和口吻；只用在聊天，写书不带。主编在群聊里的口吻，在「预设管理」里改",
        "chat_agent": "群聊里点名设定师、写手、审稿，模型又能调工具时，这一路的开场和规矩：怎么查、怎么改、怎么记。主编答群聊改用「预设管理」里的预设",
        "chat_voice": "私聊、拆的书的群聊、点名别的角色时，接在主编口吻后面：口吻只管怎么说、不改判断，写进书里和记忆里的字不带口吻。主编答群聊不用这份",
        "chat_manner": "自己的书里私聊、点名别的角色时用：回答时想着的四件事和另外几件事；实际用接话的人的角色。主编答群聊不用这份",
        "chat_material": "私聊、拆的书的群聊、点名别的角色时的用户提示：书的资料、之前聊过的、最近的对话和作者这次说的。主编答群聊的资料在「预设管理」里用占位符放",
        "persona_chief": "主编的专业底子：写书的各样活都带；私聊也带。主编答群聊不用这份，用的是「预设管理」里的预设",
    }
    for name, description in descriptions.items():
        assert catalog.entry(name)[4] == description


def test_teardown_and_essence_exact_names_order_and_roles():
    expected = {
        "拆书": [
            ("chat_teardown", "群聊回答"),
            ("persona_teardown", "拆书人设"),
            ("teardown_read", "读原文"),
            ("teardown_units", "归单元"),
            ("teardown_volumes", "归卷"),
            ("teardown_volume_text", "写卷"),
            ("teardown_arcs", "归篇"),
            ("teardown_ending", "全书结局"),
            ("teardown_waits", "读者在等的事"),
            ("teardown_merge", "合并同一个人"),
            ("teardown_tags", "爽点分类"),
            ("teardown_unitplot", "逐单元拆剧情"),
            ("teardown_card", "写角色卡"),
            ("teardown_world", "整理设定"),
        ],
        "拆书精髓": [
            ("persona_essence", "精髓人设"),
            ("essence_source", "情节怎么想"),
            ("essence_skeleton", "剧情骨架"),
            ("essence_link", "剧情衔接"),
            ("essence_fresh", "保持新鲜"),
            ("essence_longline", "长线布局"),
            ("essence_setting", "设定设计"),
            ("essence_shuang", "爽点类型"),
            ("essence_scene", "爽点戏怎么写"),
            ("essence_hero", "主角"),
            ("essence_cast", "配角与对手"),
            ("essence_rhythm", "节奏与钩子"),
            ("essence_opening", "开篇"),
            ("essence_overview", "核心要点"),
            ("essence_check", "核对"),
        ],
    }
    for group, names in expected.items():
        rows = [row for row in catalog.entries() if row[2] == group]
        assert [(row[0], row[1]) for row in rows] == names
        assert all(row[3] == "teardown" for row in rows)
