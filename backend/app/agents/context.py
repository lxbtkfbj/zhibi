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
            *[
                f"{label}：{c[key]}"
                for label, key in (
                    ("目标读者", "target_reader"),
                    ("对标", "benchmark"),
                    ("核心循环", "core_loop"),
                    ("主角钩子", "protagonist_hook"),
                )
                if c.get(key)
            ],
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
    for label, key in (
        ("性格", "personality"),
        ("背景", "background"),
        ("能力", "abilities"),
        ("目标", "goal"),
        ("此刻想要", "want"),
    ):
        if ch.get(key):
            parts.append(f"{label}：{ch[key]}")
    state = "，".join(x for x in (ch.get("location"), ch.get("condition")) if x)
    if state:
        parts.append(f"当前：{state}")
    return "\n".join(parts)


def format_character_state(ch: dict[str, Any]) -> str:
    """人物当前状态的简表：规划时用，比完整人物卡短。"""
    parts = [f"【{ch.get('name', '')}】{ch.get('role_type', '')}"]
    if ch.get("is_alive") is False:
        parts.append("已死亡")
    for label, key in (
        ("位置", "location"),
        ("状态", "condition"),
        ("实力", "abilities"),
        ("目标", "goal"),
        ("此刻想要", "want"),
    ):
        if ch.get(key):
            parts.append(f"{label}：{ch[key]}")
    return "；".join(parts)


def format_protagonist(card: dict, character: dict | None = None, hook: str = "") -> str:
    """主角卡；旧书沿用设定库人物和概念里的主角钩子。"""
    if not card:
        lines = ["（这本书开书时还没有主角卡）"]
        if character:
            lines.append(format_character(character))
        if hook:
            lines.append(f"主角钩子：{hook}")
        return "\n".join(lines)

    lines = [f"{label}：{card[key]}" for label, key in (("姓名", "name"), ("起点", "start")) if card.get(key)]
    lines.append("驱动力")
    for label, key in (("开局动机", "trigger"), ("长线追求", "pursuit"), ("情感根源", "root")):
        if card.get(key):
            lines.append(f"- {label}：{card[key]}")
    lines.append(f"- 怎么升级：{card.get('escalation') or '写到再定'}")
    for label, key in (
        ("性格", "personality"),
        ("做事风格", "style"),
        ("底线", "bottom_line"),
        ("说话方式", "voice"),
        ("金手指·现在", "finger"),
    ):
        if card.get(key):
            lines.append(f"{label}：{card[key]}")
    lines.append(f"金手指·以后：{card.get('finger_later') or '写到再定'}")
    for label, key in (("软肋", "flaw"), ("成长的终点", "arc_end")):
        if card.get(key):
            lines.append(f"{label}：{card[key]}")
    if card.get("cared"):
        lines.append(
            "在乎的人："
            + "；".join(
                f"{person.get('name', '')}（{person.get('relation', '')}：{person.get('why', '')}）"
                for person in card["cared"]
            )
        )
    if card.get("interlock"):
        lines.append(f"三件套怎么咬合：{card['interlock']}")
    if character and character.get("want"):
        lines.append(f"此刻想要：{character['want']}")
    return "\n".join(lines)


def format_world_entry(item: dict) -> str:
    """保留原条目行，只在其后追加阶梯各级或卡片字段。"""
    lines = [f"- [{item.get('category', '')}] {item.get('name', '')}：{item.get('content', '')}"]
    if item.get("style") == "ladder":
        for level in item.get("levels") or []:
            lines.append(f"{level.get('name', '')}：{level['text']}" if level.get("text") else level.get("name", ""))
    elif item.get("style") == "card":
        lines.extend(
            f"{field.get('name', '')}：{field['value']}" for field in item.get("fields") or [] if field.get("value")
        )
    return "\n".join(lines)


def format_world(world: dict) -> str:
    """世界与地图；开书阶段可附带尚未存入设定库的列表。"""
    if not world:
        return "（这本书开书时还没有「世界与地图」）"
    lines = [
        f"{label}：{world[key]}" for label, key in (("世界的表里", "surface"), ("力量规则", "power")) if world.get(key)
    ]
    for item in world.get("maps") or []:
        details = "；".join(
            f"{label}：{item[key]}"
            for label, key in (
                ("谁说了算", "powers"),
                ("天花板", "ceiling"),
                ("特有的规矩", "rules"),
                ("主角从这里起步", "start"),
                ("能拿到", "gains"),
            )
            if item.get(key)
        )
        if item.get("name") or details:
            lines.append(f"地图「{item.get('name', '')}」：{details}")
    for label, key in (("第一段·开篇的小麻烦", "trouble"), ("第一段·大对手", "opponent")):
        if world.get(key):
            lines.append(f"{label}：{world[key]}")
    far_maps = " → ".join(
        item.get("name", "") + (f"（{item['line']}）" if item.get("line") else "")
        for item in world.get("far_maps") or []
        if item.get("name") or item.get("line")
    )
    lines.append(f"后面的地图：{far_maps or '写到再定'}")
    if world.get("shadow"):
        lines.append(f"终极敌人的影子：{world['shadow']}")
    mystery = [f"谜面：{world['mystery']}"] if world.get("mystery") else []
    mystery.append(f"谜底：{world.get('mystery_answer') or '写到再定'}")
    lines.append("核心谜团：" + "；".join(mystery))
    blocks = ["\n".join(lines)]
    if world.get("world_entries"):
        blocks.append("设定条目：\n" + "\n".join(format_world_entry(item) for item in world["world_entries"]))
    if world.get("characters"):
        blocks.append("人物：\n" + "\n\n".join(format_character(ch) for ch in world["characters"]))
    if world.get("relationships"):
        blocks.append(
            "人物关系：\n"
            + "\n".join(
                f"- {item.get('source', '')} 与 {item.get('target', '')}："
                f"{item.get('kind', '')}。{item.get('description', '')}"
                for item in world["relationships"]
            )
        )
    return "\n\n".join(blocks)


def _segment_value(segment: dict, key: str, world: dict | None) -> str:
    """第一段的地图和对手优先用段内值，留空时回读世界卡。"""
    value = segment.get(key)
    if not value and segment.get("number") == 1 and world:
        if key == "map":
            maps = world.get("maps") or []
            value = maps[0].get("name") if maps else None
        elif key in {"trouble", "opponent"}:
            value = world.get(key)
    return value or ""


def format_segment_info(segment: dict, world: dict | None = None) -> str:
    """段的规划：保留作者确认方式及规划时的写作进度。"""
    number, planned_at = segment.get("number"), segment.get("planned_at")
    if number == 1 and planned_at == 0:
        lines = ["第 1 段（开书时规划）"]
    else:
        approval = "按设置自动通过" if segment.get("status") == "auto" else "作者确认"
        lines = [f"第 {number} 段（写到第 {planned_at} 章时规划，{approval}）"]
    for label, key in (
        ("地图", "map"),
        ("开篇的小麻烦", "trouble"),
        ("大对手", "opponent"),
        ("这一段的目标", "goal"),
        ("为什么离长线追求更近", "goal_link"),
        ("读者在等", "wait"),
        ("这一段揭开什么", "reveal"),
        ("上一段留下的线头", "carried"),
        ("主角的追求", "pursuit"),
        ("金手指下一阶段", "finger_next"),
        ("定下的谜底", "answers"),
    ):
        value = _segment_value(segment, key, world)
        if value:
            lines.append(f"{label}：{value}")
    if segment.get("finale"):
        lines.append("这是收尾段：开始收线，揭开核心谜团，往结局方向走。")
    return "\n".join(lines)


def format_opening(opening: dict | None) -> str:
    if not opening:
        return ""
    lines = [
        f"- {label}：{opening[key]}"
        for label, key in (
            ("第 1 章的切入场面", "scene"),
            ("前 3 章主角被什么压着", "pressure"),
            ("第一个小爽点", "first_win"),
            ("金手指露头", "finger"),
            ("第 3 章结尾的钩子", "hook"),
        )
        if opening.get(key)
    ]
    if not lines:
        return ""
    return "\n".join(["【开篇落地】第一个单元要把开篇写进去，第一个单元出章纲时照这个来：", *lines])


def format_lore(lore: dict[str, Any]) -> str:
    if not lore:
        return "（暂无）"
    world = "\n".join(format_world_entry(w) for w in lore.get("world_entries", []))
    characters = "\n\n".join(format_character(ch) for ch in lore.get("characters", []))
    relations = "\n".join(
        f"- {r.get('source')} 与 {r.get('target')}：{r.get('kind')}。{r.get('description', '')}"
        for r in lore.get("relationships", [])
    )
    anchors: dict[int, list[str]] = {}
    titles = {i: n.get("title", "") for i, n in enumerate(lore.get("nodes") or [], start=1)}
    for a in lore.get("anchors") or []:
        node = a.get("node", 0)
        if a.get("node_title"):
            titles[node] = a["node_title"]
        anchors.setdefault(node, []).append(
            f"{a.get('character', '')} {a.get('kind', '')}" + (f"——{a['note']}" if a.get("note") else "")
        )
    anchor_text = "\n".join(
        f"- 节点 {n}" + (f"「{titles[n]}」" if titles.get(n) else "") + f"：{'；'.join(anchors[n])}"
        for n in sorted(anchors)
    )
    secrets = list(lore.get("secrets") or [])
    # 过渡期旧 schema 尚会产出人物秘密，仍放进独立的信息差区，不能在保存前丢掉上下文。
    next_seq = max((s.get("seq") or 0 for s in secrets), default=0) + 1
    known = {(s.get("truth", "").strip(), k.get("name")) for s in secrets for k in s.get("knowers") or []}
    for ch in lore.get("characters") or []:
        for truth in ch.get("secrets") or []:
            key = (truth.strip(), ch.get("name", ""))
            if not key[0] or key in known:
                continue
            secrets.append(
                {
                    "seq": next_seq,
                    "title": truth[:12].rstrip("，。！？；：、,.!?;:"),
                    "truth": truth,
                    "knowers": [{"name": ch.get("name", ""), "since_chapter": None, "how": "开书设定"}],
                }
            )
            known.add(key)
            next_seq += 1
    return (
        f"世界观：\n{world}\n\n人物：\n{characters}\n\n人物关系：\n{relations or '（暂无）'}"
        f"\n\n人物锚点：\n{anchor_text or '（暂无）'}\n\n信息差：\n{format_secrets(secrets)}"
    )


def format_secrets(secrets: list[dict[str, Any]]) -> str:
    blocks = []
    for s in secrets:
        status = "公开" if s.get("status") == "public" else "隐藏"
        lines = [
            f"- S{s.get('seq') or '?'}「{s.get('title', '')}」［{status}｜读者：{s.get('reader_knows') or '未标注'}］真相：{s.get('truth', '')}"
        ]
        knowers = []
        for k in s.get("knowers") or []:
            when = "开书时" if k.get("since_chapter") is None else f"第 {k['since_chapter']} 章"
            if k.get("since_chapter") is not None and k.get("how"):
                when += f"，{k['how']}"
            knowers.append(f"{k.get('name', '')}（{when}）")
        detail = "知道的人：" + ("、".join(knowers) or "（暂无）")
        if s.get("reveal_plan"):
            detail += f"；计划：{s['reveal_plan']}"
        lines.append(f"  {detail}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks) or "（暂无）"


def format_spine(spine: dict[str, Any], world: dict | None = None) -> str:
    if not spine:
        return "（暂无）"
    from app.services.setup_store import spine_from_legacy

    spine = spine_from_legacy(spine)
    story_nodes = spine.get("nodes") or []
    last_planned = max((i for i, node in enumerate(story_nodes, 1) if node.get("segment") is not None), default=0)
    nodes = []
    for i, n in enumerate(story_nodes, start=1):
        status = {"pinned": "铁钉", "pencil": "暂定", "empty": "留空"}.get(n.get("status", "pencil"), "暂定")
        label = {"opening": "· 开篇", "ending": "· 结局"}.get(n.get("kind"), "")
        volume = f"｜约第 {n['volume']} 卷" if n.get("volume") else ""
        pending = "｜这一段写到再定" if last_planned and i > last_planned and n.get("kind") != "opening" else ""
        title = n.get("title") or ("（留空）" if n.get("status") == "empty" else "")
        event = "这里还没定" if n.get("status") == "empty" else f"发生：{n.get('event', '')}"
        nodes.append(f"节点 {i}「{title}」{label}［{status}{volume}{pending}］{event}")
        for key, name in (("prerequisite", "之前得先有"), ("consequence", "之后变成")):
            if n.get(key):
                nodes.append(f"  {name}：{n[key]}")
        if n.get("segment") is not None:
            segment = n["segment"]
            details = "；".join(
                f"{label}：{value}"
                for label, key in (("目标", "goal"), ("读者在等", "wait"), ("揭开", "reveal"), ("地图", "map"))
                if (value := _segment_value(segment, key, world))
            )
            nodes.append(f"  这是第 {segment.get('number')} 段的终点" + (f"：{details}" if details else ""))
    return "\n".join(
        [
            f"核心矛盾：{spine.get('core_conflict', '')}",
            f"主题：{spine.get('theme', '')}",
            f"主角成长弧：{spine.get('protagonist_arc', '')}",
            "关键节点：\n" + ("\n".join(nodes) or "（暂无）"),
        ]
    )


def format_segment_part(segment: dict, world: dict | None = None) -> str:
    """第一段的完整当前版本，修改时也要带上开篇五项。"""
    if not segment:
        return "（暂无）"
    blocks = [format_spine(segment, world)]
    nodes = segment.get("nodes") or []
    info = (nodes[1].get("segment") or {}) if len(nodes) > 1 else {}
    if info:
        blocks.append("这一段的规划：\n" + format_segment_info(info, world))
    opening = format_opening(info.get("opening"))
    if opening:
        blocks.append("开篇：\n" + opening.split("\n", 1)[1])
    blocks.append("信息差：\n" + format_secrets(segment.get("secrets") or []))
    blocks.append("这一段的长线期待：\n" + format_ledger(segment.get("expectations") or []))
    return "\n\n".join(blocks)


def format_volumes_part(volumes: dict) -> str:
    """这一段的分卷、线索和按节点分组的人物出场。"""
    if not volumes:
        return "（暂无）"
    anchors: dict[int, list[str]] = {}
    titles: dict[int, str] = {}
    for anchor in volumes.get("anchors") or []:
        if anchor.get("node_title"):
            titles[anchor.get("node", 0)] = anchor["node_title"]
        anchors.setdefault(anchor.get("node", 0), []).append(
            f"{anchor.get('character', '')} {anchor.get('kind', '')}"
            + (f"——{anchor['note']}" if anchor.get("note") else "")
        )
    return "\n\n".join(
        [
            "分卷：\n" + ("\n\n".join(format_volume_card(v) for v in volumes.get("volumes") or []) or "（暂无）"),
            "线索：\n" + format_threads(volumes),
            "人物出场：\n"
            + (
                "\n".join(
                    f"- 节点 {node}" + (f"「{titles[node]}」" if titles.get(node) else "") + "：" + "；".join(items)
                    for node, items in sorted(anchors.items())
                )
                or "（暂无）"
            ),
        ]
    )


def format_next_segment(plan: dict) -> str:
    """修改下一段时带回作者正在确认的整份走向，不带旧轮意见。"""
    if not plan:
        return "（暂无）"
    lines = []
    for label, key in (
        ("上一段留下的线头", "carried"),
        ("主角的追求", "pursuit"),
        ("金手指下一阶段", "finger_next"),
        ("定下的谜底", "answers"),
        ("地图", "map"),
    ):
        if plan.get(key):
            lines.append(f"{label}：{plan[key]}")
    item = plan.get("new_map") or {}
    if item:
        details = "；".join(
            f"{label}：{item[key]}"
            for label, key in (
                ("谁说了算", "powers"),
                ("天花板", "ceiling"),
                ("特有的规矩", "rules"),
                ("主角从这里起步", "start"),
                ("能拿到", "gains"),
            )
            if item.get(key)
        )
        lines.append(f"新地图「{item.get('name', '')}」：{details}")
    for label, key in (("力量规则往上", "power"), ("开头的小麻烦", "trouble"), ("大对手", "opponent")):
        if plan.get(key):
            lines.append(f"{label}：{plan[key]}")
    if plan.get("new_characters"):
        lines.append(
            "新登场的人物："
            + "；".join(
                f"{person.get('name', '')}（{person.get('role_type', '')}）：想要{person.get('goal', '')}"
                + (f"；此刻想要{person['want']}" if person.get("want") else "")
                for person in plan["new_characters"]
            )
        )
    if plan.get("goal") or plan.get("goal_link"):
        lines.append(f"这一段的目标：{plan.get('goal', '')}（为什么离长线追求更近：{plan.get('goal_link', '')}）")
    wait = plan.get("wait") or {}
    if wait:
        lines.append(
            f"读者在等：{wait.get('description', '')}（立下：{wait.get('plant_plan', '')}；兑现：{wait.get('payoff_plan', '')}）"
        )
    if plan.get("reveal"):
        lines.append(f"这一段揭开什么：{plan['reveal']}")
    if plan.get("secrets"):
        lines.append(
            "新的信息差："
            + "；".join(
                f"{secret.get('title', '')}：{secret.get('truth', '')}（知道的人："
                + "、".join(
                    item if isinstance(item, str) else item.get("name", "") for item in secret.get("knowers") or []
                )
                + "）"
                for secret in plan["secrets"]
            )
        )
    end = plan.get("end") or {}
    if end:
        adopted = "沿用" if plan.get("adopt") else "新起"
        lines.append(
            f"终点：节点 {plan.get('end_index', '')}「{end.get('title', '')}」（{adopted}）"
            f"发生：{end.get('event', '')}；之前得先有：{end.get('prerequisite', '')}；之后变成：{end.get('consequence', '')}"
        )
    if plan.get("ending"):
        lines.append(f"结局方向：{plan['ending']}")
    return "\n".join(lines)


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
        ("这一卷想做成", "want"),
        ("卷首处境", "pressure"),
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
    if v.get("target_node"):
        title = v.get("target_node_title") or ""
        lines.append(f"走向：节点 {v['target_node']}「{title}」" + ("（本卷发生）" if v.get("reaches_node") else ""))
    return "\n".join(lines)


def foreshadow_code(f: dict[str, Any]) -> str:
    return f"{'E' if f.get('kind') == '期待' else 'F'}{f.get('seq') or '?'}"


FORESHADOW_STATUS = {"planned": "未埋", "planted": "已埋", "resolved": "已收", "abandoned": "放弃"}
EXPECTATION_STATUS = {"planned": "未立", "planted": "已立", "resolved": "已兑现", "abandoned": "放弃"}


def format_foreshadowing(f: dict[str, Any]) -> str:
    kind = f.get("kind") or "伏笔"
    expectation = kind == "期待"
    plant, payoff = ("立", "兑现") if expectation else ("埋", "收")
    where = []
    if f.get("plant_volume"):
        where.append(f"第{f['plant_volume']}卷{plant}")
    if f.get("payoff_volume"):
        where.append(f"第{f['payoff_volume']}卷{payoff}")
    status = (EXPECTATION_STATUS if expectation else FORESHADOW_STATUS).get(f.get("status", "planned"), "")
    head = f"- {foreshadow_code(f)}［{kind}·{f.get('span', '中')}·{status}{'·' + '、'.join(where) if where else ''}］"
    prefix = "读者在等：" if expectation else ""
    return f"{head}{prefix}{f.get('description', '')}（{plant}：{f.get('plant_plan', '')}；{payoff}：{f.get('payoff_plan', '')}）"


def format_ledger(foreshadowings: list[dict[str, Any]]) -> str:
    return "\n".join(format_foreshadowing(f) for f in foreshadowings) or "（暂无）"


def format_outline(outline: dict[str, Any]) -> str:
    """全书总纲：分卷卡片 + 伏笔台账。"""
    if not outline:
        return "（暂无）"
    volumes = "\n\n".join(format_volume_card(v) for v in outline.get("volumes", []))
    ledger = [
        *(outline.get("foreshadowings") or []),
        *({**f, "kind": "期待"} for f in outline.get("expectations") or []),
    ]
    return f"分卷：\n{volumes}\n\n伏笔与期待台账：\n{format_ledger(ledger)}"


def format_unit(u: dict[str, Any]) -> str:
    lines = [
        f"单元{u.get('index')}「{u.get('title')}」约 {u.get('chapter_count')} 章",
        f"目标：{u.get('goal', '')}",
        f"冲突：{u.get('conflict', '')}",
        f"高潮：{u.get('climax', '')}",
        f"结果：{u.get('outcome', '')}",
    ]
    if u.get("loop"):
        lines.append(f"核心循环：{u['loop']}")
    lines.append(f"关键事件：{' → '.join(u.get('key_events', []))}")
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
    lines.extend(format_reveals(u.get("reveals") or []))
    return "\n".join(lines)


def format_reveals(reveals: list[dict[str, Any]]) -> list[str]:
    return [f"揭晓：{r.get('ref', '')} 揭给 {r.get('to', '')}——{r.get('how', '')}" for r in reveals]


def format_units(units: list[dict[str, Any]]) -> str:
    return "\n\n".join(format_unit(u) for u in units) or "（暂无）"


def format_volume_plan(plan: dict[str, Any]) -> str:
    """卷纲：剧情单元 + 本卷新埋的伏笔。"""
    if not plan:
        return "（暂无）"
    heading = [
        f"{label}：{plan[key]}" for label, key in (("这一卷想做成", "want"), ("卷首处境", "pressure")) if plan.get(key)
    ]
    text = ("\n".join(heading) + "\n\n" if heading else "") + format_units(plan.get("units", []))
    fresh = plan.get("new_foreshadowings") or []
    if fresh:
        text += "\n\n本卷新埋的伏笔：\n" + "\n".join(
            f"- {f.get('description')}（第{f.get('plant_unit')}单元埋；"
            + (f"第{f['payoff_unit']}单元收" if f.get("payoff_unit") else f"第{f.get('payoff_volume')}卷收")
            + "）"
            for f in fresh
        )
    expectations = [{**f, "kind": "期待"} for f in plan.get("new_expectations") or []]
    if expectations:
        text += "\n\n本卷新立的期待：\n" + format_ledger(expectations)
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


def format_direction_choice(direction: dict[str, Any] | None) -> str:
    if not direction:
        return ""
    lines = [
        "【作者选定的方向】",
        f"方向「{direction.get('name', '')}」：{direction.get('logline', '')}",
        f"主角：{direction.get('protagonist', '')}",
        *([f"驱动力：{direction['drive']}"] if direction.get("drive") else []),
        f"金手指：{direction.get('golden_finger', '')}",
        *([f"核心循环：{direction['core_loop']}"] if direction.get("core_loop") else []),
        f"开局：{direction.get('opening', '')}",
        f"卖点：{'；'.join(direction.get('selling_points') or [])}",
        f"舞台阶梯：{direction.get('stage_ladder', '')}",
        f"基调：{direction.get('tone', '')}",
        f"目标读者：{direction.get('reader', '')}",
    ]
    if direction.get("titles"):
        lines.append("书名候选：" + "".join(f"《{title}》" for title in direction["titles"]))
    if direction.get("title"):
        lines.append(f"作者选定的书名：《{direction['title']}》")
    if direction.get("mix"):
        lines.extend(["", "【作者的混搭要求】", direction["mix"]])
    return "\n".join(lines)


def format_previous_directions(previous: dict[str, Any] | None) -> str:
    """只渲染被作者否决的最近一轮，不把更早的方向嵌套带回模型。"""
    if not previous:
        return ""
    lines = ["【上一轮的方向（作者不满意）】"]
    if previous.get("reference"):
        lines.append(f"你对对标作品的理解：{previous['reference']}")
    for index, direction in enumerate(previous.get("directions") or [], 1):
        line = (
            f"{index}. 方向「{direction.get('name', '')}」：{direction.get('logline', '')}；"
            f"金手指：{direction.get('golden_finger', '')}；舞台阶梯：{direction.get('stage_ladder', '')}"
        )
        if direction.get("titles"):
            line += "；书名候选：" + "".join(f"《{title}》" for title in direction["titles"])
        lines.append(line)
    lines.append(f"作者的意见：{previous.get('feedback', '')}")
    return "\n".join(lines)


def format_target_node(volume: dict[str, Any], nodes: list[dict[str, Any]]) -> str:
    target = volume.get("target_node") or 0
    if not isinstance(target, int) or not 1 <= target <= len(nodes):
        return "（本卷没有标走向的节点，按本卷卡片规划）"
    node = nodes[target - 1]
    status = {"pinned": "铁钉", "pencil": "暂定", "empty": "留空"}.get(node.get("status", "pencil"), "暂定")
    arrival = (
        "本卷就要写到它，作为卷末高潮"
        if volume.get("reaches_node")
        else "本卷还写不到它：卷末要让它的「之前得先有」更进一步"
    )
    lines = [
        f"节点 {target}「{node.get('title', '')}」［{status}］——{arrival}",
        f"发生什么：{node.get('event', '')}",
        f"之前得先有：{node.get('prerequisite', '')}",
        f"之后变成：{node.get('consequence', '')}",
    ]
    if target < len(nodes):
        following = nodes[target]
        lines.append(f"再下一个节点：节点 {target + 1}「{following.get('title', '')}」：{following.get('event', '')}")
    return "\n".join(lines)


def format_locked(state: dict[str, Any]) -> str:
    from app.agents.setup_puzzle import PIECE_NAMES, PIECE_ORDER

    nodes = (state.get("segment") or {}).get("nodes") or []
    pinned = [
        f"节点 {index}「{node.get('title', '')}」"
        for index, node in enumerate(nodes, 1)
        if node.get("status") == "pinned"
    ]
    confirmed = [PIECE_NAMES[piece] for piece in PIECE_ORDER if (state.get("pieces") or {}).get(piece) == "confirmed"]
    if state.get("mode", "oneshot") == "puzzle" and confirmed:
        result = "【作者已确认（锁定）的部分】" + "、".join(confirmed)
        if pinned:
            result += "\n其中铁钉节点：" + "、".join(pinned)
        return result
    return (
        "【作者钉死的节点】" + "、".join(pinned) + "（铁钉，不能擅自改；仅本轮作者明确点名时可按要求改，改完仍是铁钉）"
        if pinned
        else ""
    )


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
