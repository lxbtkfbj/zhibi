"""提示词页的公开白名单、中文名称与变量说明。"""

import re

from app.prompts import VARIABLE, canonical_name, default_content

# 名称、中文名、分组、实际调用角色、使用时机。顺序就是界面顺序。
CATALOG = [
    ("setup_interview", "动笔前提问", "开书", "chief", "开书前了解作者的点子"),
    ("setup_concept", "定书的概念", "开书", "chief", "起书名、确定概念与篇幅"),
    ("setup_lore", "建世界观与人物", "开书", "lorekeeper", "创建或修改世界观与人物"),
    ("setup_spine", "定主线骨架", "开书", "chief", "规划故事主线"),
    ("setup_threads", "线索规划", "开书", "chief", "规划各条线索"),
    ("setup_outline", "全书总纲", "开书", "chief", "规划全书分卷"),
    ("setup_critique", "审开书方案", "开书", "reviewer", "审阅完整开书方案"),
    ("setup_triage", "处理作者意见", "开书", "chief", "收到开书方案修改意见时"),
    ("setup_notes", "处理作者插话", "开书", "chief", "开书进行中处理插话与设置修改"),
    ("volume_directions", "卷纲方向", "规划", "chief", "卷纲比稿前提出不同方向"),
    ("plan_volume", "拆卷纲", "规划", "chief", "规划每一卷的剧情单元"),
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
    ("playbooks.harem_xuanhuan", "后宫玄幻爽文", "题材打法", "chief,reviewer", "匹配或指定后宫玄幻爽文时的规划与审稿"),
    ("playbooks.general", "通用", "题材打法", "chief,reviewer", "匹配或指定通用打法时的规划与审稿"),
]
BY_NAME = {row[0]: row for row in CATALOG}

VARIABLE_LABELS = {
    "idea": "作者的点子", "requirements": "作者的要求", "style": "文风参考", "revision": "修改要求",
    "playbook": "题材打法", "chapter_hint": "章数提示", "concept": "书的概念", "lore": "世界观与人物",
    "spine": "主线骨架", "threads": "故事线索", "outline": "章纲或总纲", "first_volume": "第一卷卷纲",
    "feedback": "作者意见", "done": "已完成的方案", "todo": "待完成的步骤", "notes": "作者插话",
    "rules": "通用规则", "strictness": "审稿尺度", "volume_index": "卷号", "volume_title": "卷名",
    "volume": "本卷规划", "unit_index": "单元序号", "unit_title": "单元标题", "unit": "本单元规划",
    "units": "各单元回顾", "chapter_index": "章号", "chapter_title": "章节标题", "chapter_words": "目标字数",
    "chapter_count": "章节数量", "chapter_catalog": "章节目录", "chapters": "各章内容", "first_chapter": "起始章号",
    "last_chapter": "结束章号", "characters": "人物资料", "world": "世界设定", "world_catalog": "世界设定目录",
    "roster": "人物名册", "ledger": "伏笔台账", "neighbors": "相邻卷与单元", "story_so_far": "故事前情",
    "trope_usage": "套路使用台账", "used_climaxes": "已用高潮", "unit_hint": "单元数量提示",
    "direction": "本次卷纲方向", "pitch_count": "比稿方案数", "pitches": "待评卷纲方案", "plan": "卷纲方案",
    "found": "程序发现的问题", "content": "正文", "recent": "最近几章", "words": "已写字数",
    "missing": "还缺字数", "body": "结尾前正文", "ending": "原结尾", "ending_words": "结尾目标字数",
    "reason": "改写原因", "hook": "结尾钩子", "foreshadow_tasks": "本章伏笔任务", "previous_tail": "上章结尾",
    "recall": "相关前文",
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
