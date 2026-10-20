"""提示词页的公开白名单、中文名称与变量说明。"""

import re

from app.prompts import VARIABLE, canonical_name, default_content

# 名称、中文名、分组、实际调用角色、使用时机。顺序就是界面顺序。
CATALOG = [
    (
        "book_draft",
        "新建页起草",
        "开书",
        "chief",
        "作者在首页写点子点开新书时，先填好书名、简介、类别、标签和篇幅；不满意时按意见改",
    ),
    ("setup_pitches", "三个故事方向", "开书", "chief", "开书第一步：按点子给三个故事方向"),
    ("setup_story", "定调", "开书", "chief", "把挑中的故事方向展开成定调"),
    ("library_build_focus", "建库：主角和金手指", "开书", "lorekeeper", "开书第二步：先出重点"),
    ("library_build_rest", "建库：其余设定", "开书", "lorekeeper", "开书第二步：补齐设定库"),
    ("setup_outline", "出大纲", "开书", "chief", "开书第三步：大纲"),
    ("split_segment", "这一篇分卷与线索", "规划", "chief", "定下一篇后分卷，开写前补齐第一篇"),
    ("setup_notes", "处理作者插话", "开书", "chief", "开书进行中处理插话与设置修改"),
    ("library_rewrite", "改一处", "设定库", "lorekeeper", "作者让 AI 改设定库或大纲里的一处"),
    ("library_fill_gaps", "补漏", "设定库", "chief", "看设定库还缺什么"),
    ("library_draft", "帮写几条", "设定库", "lorekeeper", "新书页上作者让编辑部在某一类里写几条候选，挑中的才收下"),
    ("library_fill_entry", "补齐一条", "设定库", "lorekeeper", "作者让编辑部把某一条设定空着的栏目补上，写过的不动"),
    (
        "outline_write",
        "帮写大纲的一段",
        "规划",
        "chief",
        "新书页大纲上作者让编辑部把结局、某一篇、某一卷、某个单元或某一章写出来",
    ),
    ("library_review", "查一遍", "设定库", "reviewer", "查设定库的矛盾、同根、好看、题材"),
    ("chat_reply", "聊天回答", "聊天", "chief", "作者在群聊提问或私聊时，角色回答；实际用聊天对象的角色"),
    ("chat_teardown", "拆书群聊回答", "拆书", "teardown", "拆的书里群聊回答用"),
    ("persona_teardown", "拆书人设", "拆书", "teardown", "拆书调用的系统提示"),
    ("teardown_read", "拆书：读原文", "拆书", "teardown", "逐章记下章纲和人物设定的原始记录"),
    ("teardown_units", "拆书：归单元", "拆书", "teardown", "把读好的章归成单元"),
    ("teardown_volumes", "拆书：归卷", "拆书", "teardown", "原书没分卷时把单元归成卷"),
    ("teardown_volume_text", "拆书：写卷", "拆书", "teardown", "原书分了卷时写这一卷的那段话"),
    ("teardown_arcs", "拆书：归篇", "拆书", "teardown", "把收住的卷归成篇"),
    ("teardown_ending", "拆书：全书结局", "拆书", "teardown", "看原书完没完结，完结了再写全书结局"),
    ("teardown_waits", "拆书：读者在等的事", "拆书", "teardown", "把逐章记录里的立下、提起、兑现连成账"),
    ("teardown_card", "拆书：写角色卡", "拆书", "teardown", "只用各章记录写角色卡和名场面"),
    ("teardown_world", "拆书：整理设定", "拆书", "teardown", "只用各章记录逐类整理设定库"),
    ("teardown_merits", "拆书：这本书好在哪", "拆书", "teardown", "照程序算好的数字写这本书好在哪"),
    (
        "chat_agent",
        "聊天：自己查、自己动手",
        "聊天",
        "chief",
        "作者在群聊里说话、模型支持工具调用时：接话的人自己查资料、自己动手改书，再回作者一段话；实际用接话的人的角色",
    ),
    ("chat_summary", "对话摘要", "聊天", "lorekeeper", "对话太长时把更早的部分折成摘要"),
    ("chat_plan", "总结方案", "聊天", "chief", "作者让编辑部把聊过的想法总结成方案卡；实际用聊天对象的角色"),
    ("requirements_tidy", "整理作者要求", "聊天", "chief", "把作者要求清单里像提问、闲聊、重复、过时的标出来"),
    ("library_route", "群聊分流", "聊天", "router", "作者在群聊里说话时，判断是改设定、写作要求还是提问闲聊"),
    ("plan_segment", "定下一篇", "规划", "chief", "每一篇开写前规划下一篇"),
    ("volume_directions", "卷纲方向", "规划", "chief", "卷纲比稿前提出不同方向"),
    ("plan_volume", "拆卷纲", "规划", "chief", "规划每一卷的剧情单元，开写前补齐第 1 卷"),
    ("judge_pitches", "卷纲比稿评审", "规划", "reviewer", "多个卷纲方案比稿时"),
    ("audit_volume", "卷纲专项审稿", "规划", "reviewer", "卷纲专项检查开启时"),
    ("plan_chapters", "出章纲", "规划", "chief", "把剧情单元拆成章纲"),
    ("prepare_chapter", "备本章资料", "写作", "lorekeeper", "写正文前挑选本章资料"),
    ("write_chapter", "写正文", "写作", "writer", "生成章节正文或重写时"),
    ("extend_chapter", "字数不够接着写", "写作", "writer", "正文没有达到目标字数时"),
    ("rewrite_ending", "改写结尾", "写作", "writer", "结尾需要补钩子时"),
    ("review_chapter", "审稿", "审稿与入库", "reviewer", "正文完成后进行质量审稿"),
    ("check_consistency", "查矛盾", "审稿与入库", "lorekeeper", "正文完成后核对设定一致性"),
    ("digest_chapter", "记入设定库", "审稿与入库", "lorekeeper", "章节定稿后更新设定库"),
    ("recap_unit", "单元回顾", "审稿与入库", "lorekeeper", "剧情单元完成后"),
    ("recap_volume", "卷回顾", "审稿与入库", "lorekeeper", "整卷完成后"),
    ("persona_chief", "主编人设", "角色与规矩", "chief", "主编每次调用的系统提示"),
    ("persona_lorekeeper", "设定师人设", "角色与规矩", "lorekeeper", "设定师每次调用的系统提示"),
    ("persona_writer", "写手人设", "角色与规矩", "writer", "写手每次调用的系统提示"),
    ("persona_reviewer", "审稿人设", "角色与规矩", "reviewer", "审稿每次调用的系统提示"),
    ("rules", "通用规则", "角色与规矩", "all", "所有角色的系统提示"),
    ("glossary", "术语表", "角色与规矩", "all", "编辑批注里的技巧名称与白话解释"),
    ("playbooks.harem_xuanhuan", "后宫玄幻爽文", "题材打法", "chief,reviewer", "匹配或指定后宫玄幻爽文时的规划与审稿"),
    ("playbooks.general", "通用", "题材打法", "chief,reviewer", "匹配或指定通用打法时的规划与审稿"),
]
BY_NAME = {row[0]: row for row in CATALOG}

VARIABLE_LABELS = {
    "title": "书名",
    "name": "名单上的名字",
    "aliases": "别称",
    "dossier": "各章记下的人物记录",
    "kind": "这次整理的类别",
    "context": "主角变化或角色所属",
    "things": "各章记下的设定记录",
    "kind_rule": "这一类的整理要求",
    "facts": "程序算好的数字和摘出的记录",
    "first": "起始章号",
    "last": "结束章号",
    "index": "卷序号",
    "done_units": "前面已经归好的单元",
    "done_volumes": "前面已经归好的卷",
    "tail_rule": "最后几章怎么收尾",
    "max_arcs": "最多归成几篇",
    "hint": "文件末尾的完结字样提示",
    "open": "还吊着的事",
    "book_info": "原书信息与拆书进度",
    "lookup": "怎么查资料",
    "progress": "写到哪了",
    "extras": "角色自己的资料",
    "pending": "等你确认的内容",
    "summary": "之前聊过",
    "quote": "作者选中的原文",
    "where": "在哪里聊",
    "how_to_apply": "结论怎么生效",
    "material_note": "资料是全文还是目录",
    "working": "编辑部在不在干活",
    "retry": "上次做到一半",
    "act_rule": "能不能动手",
    "role_focus": "这个角色管什么",
    "who": "和谁聊",
    "messages": "要折进摘要的对话",
    "mode_line": "要做什么",
    "mode_rule": "怎么写",
    "no_secret": "这本书还没有底牌时的提示",
    "fixed": "已经定了的分卷或单元",
    "existing": "设定库里已经有的",
    "pitch": "挑中的故事方向",
    "category_hints": "每一类该写清什么",
    "library": "设定库目录",
    "library_full": "设定库全文",
    "target_full": "这一条的全文",
    "related": "相关的条目",
    "target_label": "要改的地方",
    "current": "原文",
    "category_hint": "这一类该写清什么",
    "category": "这一类",
    "same_kind": "这一类已经有的",
    "fields": "这一类的栏目",
    "request": "作者想要什么",
    "count": "写几条",
    "target_name": "要补的那一条",
    "node_name": "要写的那一段",
    "viewing": "作者正在看的那一页",
    "write_rule": "这一层写什么",
    "mode": "怎么改",
    "genre_defaults": "题材和常建的条目",
    "scope": "这次查什么",
    "note": "作者的话",
    "last_segment": "上一篇",
    "length": "篇幅与收束",
    "protagonist": "主角、金手指和底牌",
    "segment": "这一篇",
    "volumes": "分卷与线索",
    "focus": "这次审什么",
    "opening": "开篇落地",
    "volume_hint": "分卷提示",
    "chosen_direction": "作者选定的方向",
    "previous": "上一轮的方向",
    "slot": "要补的位置",
    "locked": "已确认的部分",
    "target_node": "本卷走向的节点",
    "secrets": "信息差表",
    "rhythm": "节奏底线",
    "idea": "作者的点子",
    "catalog": "可选的类别和常见标签",
    "requirements": "作者的要求",
    "style": "文风参考",
    "revision": "修改要求",
    "playbook": "题材打法",
    "chapter_hint": "章数提示",
    "concept": "书的概念",
    "lore": "世界观与人物",
    "spine": "大纲",
    "threads": "故事线索",
    "outline": "章纲或总纲",
    "first_volume": "第一卷卷纲",
    "feedback": "作者意见",
    "done": "已完成的方案",
    "todo": "待完成的步骤",
    "notes": "作者插话",
    "rules": "通用规则",
    "strictness": "审稿尺度",
    "volume_index": "卷号",
    "volume_title": "卷名",
    "volume": "本卷规划",
    "unit_index": "单元序号",
    "unit_title": "单元标题",
    "unit": "本单元规划",
    "units": "各单元回顾",
    "chapter_index": "章号",
    "chapter_title": "章节标题",
    "chapter_words": "目标字数",
    "chapter_count": "章节数量",
    "chapter_line": "这个单元几章、从第几章起",
    "chapter_rule": "章数要求",
    "chapter_catalog": "章节目录",
    "chapters": "各章内容",
    "first_chapter": "起始章号",
    "last_chapter": "结束章号",
    "characters": "人物资料",
    "world": "设定库",
    "world_catalog": "世界设定目录",
    "roster": "人物名册",
    "ledger": "伏笔台账",
    "neighbors": "相邻卷与单元",
    "story_so_far": "故事前情",
    "trope_usage": "套路使用台账",
    "used_climaxes": "已用高潮",
    "unit_hint": "单元数量提示",
    "direction": "本次卷纲方向",
    "pitch_count": "比稿方案数",
    "pitches": "待评卷纲方案",
    "plan": "卷纲方案",
    "found": "程序发现的问题",
    "content": "正文",
    "recent": "最近几章",
    "words": "已写字数",
    "missing": "还缺字数",
    "body": "结尾前正文",
    "ending": "原结尾",
    "ending_words": "结尾目标字数",
    "reason": "改写原因",
    "hook": "结尾钩子",
    "foreshadow_tasks": "本章伏笔与期待任务",
    "previous_tail": "上章结尾",
    "recall": "相关前文",
    "glossary": "术语表",
}


def entry(name: str) -> tuple:
    name = canonical_name(name)
    if name not in BY_NAME:
        raise ValueError("提示词不存在")
    return BY_NAME[name]


def variables(name: str) -> list[dict[str, str]]:
    text = default_content(name)
    labels = dict(VARIABLE_LABELS)
    # 变量单独成行、紧接【标题】时，以那份模板的标题为准。
    for match in re.finditer(r"^【([^\n]+)】\s*\n\s*\{\{(\w+)\}\}\s*$", text, re.M):
        labels[match.group(2)] = match.group(1)
    return [{"name": key, "label": labels[key]} for key in dict.fromkeys(VARIABLE.findall(text))]


def validate_content(name: str, content: str) -> None:
    name = entry(name)[0]
    expected, provided = set(VARIABLE.findall(default_content(name))), set(VARIABLE.findall(content))
    errors = []
    if expected - provided:
        errors.append("缺少变量：" + "、".join("{{" + key + "}}" for key in sorted(expected - provided)))
    if provided - expected:
        errors.append("不支持的变量：" + "、".join("{{" + key + "}}" for key in sorted(provided - expected)))
    malformed = re.sub(VARIABLE, "", content)
    if "{{" in malformed or "}}" in malformed:
        errors.append("变量格式不完整，请使用 {{变量名}}")
    if not content.strip():
        errors.append("提示词不能为空")
    if errors:
        raise ValueError("；".join(errors))
    if name.startswith("playbooks."):
        from app.agents.playbook import parse

        parse(name.split(".", 1)[1], content)
    if name == "glossary":
        from app.agents.glossary import parse

        terms = parse(content)
        if len({term for term, _ in terms if term}) < 5:
            raise ValueError("术语表至少需要 5 个术语")
        if any(not term or not explanation for term, explanation in terms):
            raise ValueError("每个术语都需要名称和解释")
