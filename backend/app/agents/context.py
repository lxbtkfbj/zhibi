"""把结构化的方案整理成适合放进提示词的中文文本（上下文工程）。"""

from typing import Any


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def format_concept(c: dict[str, Any]) -> str:
    if not c:
        return "（暂无）"
    return "\n".join(
        [
            f"书名：{c.get('title', '')}（备选：{'、'.join(c.get('alt_titles', []))}）",
            f"类型：{c.get('genre', '')}；标签：{'、'.join(c.get('tags', []))}",
            f"一句话简介：{c.get('logline', '')}",
            f"核心卖点：\n{_lines(c.get('selling_points', []))}",
            f"主角钩子：{c.get('protagonist_hook', '')}",
            f"基调：{c.get('tone', '')}",
            f"计划 {c.get('target_volumes', '')} 卷，每章约 {c.get('chapter_words', '')} 字",
        ]
    )


def format_character(ch: dict[str, Any]) -> str:
    parts = [f"【{ch.get('name', '')}】{ch.get('role_type', '')}"]
    basics = "，".join(x for x in (ch.get("gender"), ch.get("age"), ch.get("appearance")) if x)
    if basics:
        parts.append(basics)
    for label, key in (("性格", "personality"), ("背景", "background"), ("能力", "abilities"), ("目标", "goal")):
        if ch.get(key):
            parts.append(f"{label}：{ch[key]}")
    state = "，".join(x for x in (ch.get("location"), ch.get("condition")) if x)
    if state:
        parts.append(f"当前：{state}")
    if ch.get("secrets"):
        parts.append(f"秘密：{'；'.join(ch['secrets'])}")
    return "\n".join(parts)


def format_lore(lore: dict[str, Any]) -> str:
    if not lore:
        return "（暂无）"
    world = "\n".join(
        f"- [{w.get('category', '')}] {w.get('name', '')}：{w.get('content', '')}"
        for w in lore.get("world_entries", [])
    )
    characters = "\n\n".join(format_character(ch) for ch in lore.get("characters", []))
    relations = "\n".join(
        f"- {r.get('source')} 与 {r.get('target')}：{r.get('kind')}。{r.get('description', '')}"
        for r in lore.get("relationships", [])
    )
    return f"世界观：\n{world}\n\n人物：\n{characters}\n\n人物关系：\n{relations or '（暂无）'}"


def format_outline(outline: dict[str, Any]) -> str:
    if not outline:
        return "（暂无）"
    volumes = "\n".join(
        f"第{v.get('index')}卷《{v.get('title')}》：{v.get('summary', '')}（卷末目标：{v.get('goal', '')}）"
        for v in outline.get("volumes", [])
    )
    units = "\n\n".join(
        "\n".join(
            [
                f"单元{u.get('index')}「{u.get('title')}」约 {u.get('chapter_count')} 章",
                f"目标：{u.get('goal', '')}",
                f"冲突：{u.get('conflict', '')}",
                f"高潮：{u.get('climax', '')}",
                f"结果：{u.get('outcome', '')}",
                f"关键事件：{' → '.join(u.get('key_events', []))}",
            ]
        )
        for u in outline.get("first_volume_units", [])
    )
    foreshadowings = "\n".join(
        f"- {f.get('description')}（埋：{f.get('plant_plan', '')}；收：{f.get('payoff_plan', '')}）"
        for f in outline.get("foreshadowings", [])
    )
    return f"分卷：\n{volumes}\n\n第一卷剧情单元：\n{units}\n\n伏笔：\n{foreshadowings or '（暂无）'}"


def format_style(style_reference: str) -> str:
    if not style_reference.strip():
        return ""
    return f"【作者提供的文风参考】\n{style_reference.strip()[:3000]}"


def format_revision(current_label: str, current: str, instructions: str) -> str:
    if not instructions.strip():
        return ""
    return f"【{current_label}】\n{current}\n\n【修改要求】\n{instructions.strip()}\n\n请在当前版本的基础上修改，保留不需要改动的部分，输出修改后的完整结果。"
