"""把结构化的方案整理成适合放进提示词的中文文本（上下文工程）。"""

from typing import Any

from app.book_settings import compile_rules


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
            f"篇幅：{format_length(c)}",
        ]
    )


def planned_chapters(c: dict[str, Any]) -> int:
    """按总字数和每章字数估算全书章数；概念里没有篇幅时返回 0。"""
    length, words = c.get("target_length"), c.get("chapter_words")
    if not length or not words:
        return 0
    return max(1, round(length * 10000 / words))


def format_length(c: dict[str, Any]) -> str:
    parts = []
    if c.get("target_length"):
        parts.append(f"全书约 {c['target_length']} 万字")
    parts.append(f"计划 {c.get('target_volumes', '')} 卷")
    parts.append(f"每章约 {c.get('chapter_words', '')} 字")
    if planned_chapters(c):
        parts.append(f"合计约 {planned_chapters(c)} 章")
    return "，".join(parts)


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


def format_character_state(ch: dict[str, Any]) -> str:
    """人物当前状态的简表：规划时用，比完整人物卡短。"""
    parts = [f"【{ch.get('name', '')}】{ch.get('role_type', '')}"]
    if ch.get("is_alive") is False:
        parts.append("已死亡")
    for label, key in (("位置", "location"), ("状态", "condition"), ("实力", "abilities"), ("目标", "goal")):
        if ch.get(key):
            parts.append(f"{label}：{ch[key]}")
    return "；".join(parts)


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


def format_spine(spine: dict[str, Any]) -> str:
    if not spine:
        return "（暂无）"
    milestones = "\n".join(
        f"{m.get('index')}. 【{m.get('title', '')}】（约第{m.get('volume', '?')}卷）{m.get('event', '')}"
        f"——之后：{m.get('change', '')}"
        for m in spine.get("milestones", [])
    )
    return "\n".join(
        [
            f"核心矛盾：{spine.get('core_conflict', '')}",
            f"主题：{spine.get('theme', '')}",
            f"主角成长弧：{spine.get('protagonist_arc', '')}",
            f"开篇：{spine.get('opening', '')}",
            f"结局：{spine.get('ending', '')}",
            f"关键转折：\n{milestones or '（暂无）'}",
        ]
    )


def format_threads(threads: dict[str, Any] | list[dict[str, Any]], volume: int | None = None) -> str:
    """线索列表；给了 volume 时只列出这一卷前后的节拍，控制篇幅。"""
    items = threads.get("threads", []) if isinstance(threads, dict) else threads
    if not items:
        return "（暂无）"
    blocks = []
    for t in items:
        beats = t.get("beats", [])
        if volume is not None:
            beats = [b for b in beats if abs((b.get("volume") or 0) - volume) <= 1]
        lines = [f"【{t.get('name', '')}】{t.get('kind', '')}：{t.get('summary', '')}"]
        if t.get("characters"):
            lines.append(f"人物：{'、'.join(t['characters'])}")
        lines += [f"  第{b.get('volume')}卷：{b.get('beat', '')}" for b in beats]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def format_steps(steps: list[dict[str, Any]]) -> str:
    return "；".join(f"{s.get('thread', '')}——{s.get('beat', '')}" for s in steps if s.get("thread"))


def format_volume_card(v: dict[str, Any]) -> str:
    lines = [
        f"第{v.get('index')}卷《{v.get('title', '')}》"
        + (f"约 {v['chapter_count']} 章" if v.get("chapter_count") else "")
    ]
    for label, key in (
        ("舞台", "stage"),
        ("概要", "summary"),
        ("卷末目标", "goal"),
        ("高潮", "climax"),
        ("主要对手", "antagonist"),
        ("主角实力", "power_range"),
    ):
        if v.get(key):
            lines.append(f"{label}：{v[key]}")
    if v.get("thread_beats"):
        lines.append(f"推进线索：{format_steps(v['thread_beats'])}")
    if v.get("new_characters"):
        lines.append(f"新登场：{'、'.join(v['new_characters'])}")
    return "\n".join(lines)


def foreshadow_code(f: dict[str, Any]) -> str:
    return f"F{f.get('seq')}" if f.get("seq") else "F?"


FORESHADOW_STATUS = {"planned": "未埋", "planted": "已埋", "resolved": "已收", "abandoned": "放弃"}


def format_foreshadowing(f: dict[str, Any]) -> str:
    where = []
    if f.get("plant_volume"):
        where.append(f"第{f['plant_volume']}卷埋")
    if f.get("payoff_volume"):
        where.append(f"第{f['payoff_volume']}卷收")
    status = FORESHADOW_STATUS.get(f.get("status", "planned"), "")
    head = f"- {foreshadow_code(f)}［{f.get('span', '中')}·{status}{'·' + '、'.join(where) if where else ''}］"
    return f"{head}{f.get('description', '')}（埋：{f.get('plant_plan', '')}；收：{f.get('payoff_plan', '')}）"


def format_ledger(foreshadowings: list[dict[str, Any]]) -> str:
    return "\n".join(format_foreshadowing(f) for f in foreshadowings) or "（暂无）"


def format_outline(outline: dict[str, Any]) -> str:
    """全书总纲：分卷卡片 + 伏笔台账。"""
    if not outline:
        return "（暂无）"
    volumes = "\n\n".join(format_volume_card(v) for v in outline.get("volumes", []))
    return f"分卷：\n{volumes}\n\n伏笔台账：\n{format_ledger(outline.get('foreshadowings', []))}"


def format_unit(u: dict[str, Any]) -> str:
    lines = [
        f"单元{u.get('index')}「{u.get('title')}」约 {u.get('chapter_count')} 章",
        f"目标：{u.get('goal', '')}",
        f"冲突：{u.get('conflict', '')}",
        f"高潮：{u.get('climax', '')}",
        f"结果：{u.get('outcome', '')}",
        f"关键事件：{' → '.join(u.get('key_events', []))}",
    ]
    if u.get("thread_beats"):
        lines.append(f"推进线索：{format_steps(u['thread_beats'])}")
    if u.get("tropes") or u.get("resolution"):
        tropes = "、".join(t for t in u.get("tropes") or [] if t) or "未标"
        lines.append(f"套路：{tropes}；破局：{u.get('resolution') or '未标'}")
    if u.get("foreshadow_actions"):
        lines.append(
            "伏笔："
            + "；".join(
                f"{a.get('action')}{a.get('ref')} {a.get('detail', '')}".strip() for a in u["foreshadow_actions"]
            )
        )
    return "\n".join(lines)


def format_units(units: list[dict[str, Any]]) -> str:
    return "\n\n".join(format_unit(u) for u in units) or "（暂无）"


def format_volume_plan(plan: dict[str, Any]) -> str:
    """卷纲：剧情单元 + 本卷新埋的伏笔。"""
    if not plan:
        return "（暂无）"
    text = format_units(plan.get("units", []))
    fresh = plan.get("new_foreshadowings") or []
    if fresh:
        text += "\n\n本卷新埋的伏笔：\n" + "\n".join(
            f"- {f.get('description')}（第{f.get('plant_unit')}单元埋；"
            + (f"第{f['payoff_unit']}单元收" if f.get("payoff_unit") else f"第{f.get('payoff_volume')}卷收")
            + "）"
            for f in fresh
        )
    return text


def format_direction(d: dict[str, Any]) -> str:
    """比稿时某一份方案的方向，告诉主编这一稿要往哪拆。"""
    if not d:
        return ""
    lines = [f"【这一稿的方向：{d.get('name', '')}】", f"思路：{d.get('idea', '')}"]
    if d.get("difference"):
        lines.append(f"和其他方向的区别：{d['difference']}")
    lines.append("请沿着这个方向拆这一卷，和其他方向拉开差距；本卷卡片的卷末目标、线索节拍和作者的要求仍要落实。")
    return "\n".join(lines)


def format_pitches(pitches: list[dict[str, Any]]) -> str:
    """比稿：每份方案的方向和完整卷纲。"""
    return "\n\n".join(
        f"【方案{p.get('pitch')}：{(p.get('direction') or {}).get('name', '')}】\n"
        f"思路：{(p.get('direction') or {}).get('idea', '')}\n{format_volume_plan(p.get('plan') or {})}"
        for p in pitches
    )


def format_requirements(brief: list[str], notes: list[str], settings: dict | None = None) -> str:
    """Every active requirement is included; deleting a ledger row removes it next step."""
    lines = list(dict.fromkeys(x for x in [*brief, *notes] if x.strip()))
    blocks = [compile_rules(settings)]
    if lines:
        body = "\n".join(f"- {line}" for line in lines)
        blocks.append(f"【作者的要求（必须落实；后面的要求与前面冲突时以后面的为准）】\n{body}")
    return "\n\n".join(block for block in blocks if block)


def format_style(style_reference: str) -> str:
    if not style_reference.strip():
        return ""
    return f"【作者提供的文风参考】\n{style_reference.strip()[:3000]}"


def format_revision(current_label: str, current: str, instructions: str) -> str:
    if not instructions.strip():
        return ""
    return f"【{current_label}】\n{current}\n\n【修改要求】\n{instructions.strip()}\n\n请在当前版本的基础上修改，保留不需要改动的部分，输出修改后的完整结果。"
