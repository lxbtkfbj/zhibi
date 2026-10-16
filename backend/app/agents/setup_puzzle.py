"""开书拼图的确定性规则：快照合并、引用清洗与程序提醒，不触发模型或保存。"""

import re
from copy import deepcopy
from typing import Any

from app.agents.glossary import clean_techniques

ORDER = ["concept", "protagonist", "world", "segment", "volumes", "first_volume"]
PIECES = {
    "concept": ["concept"],
    "protagonist": ["protagonist"],
    "world": ["world"],
    "segment": ["segment", "volumes"],
    "first_volume": ["first_volume"],
}
PIECE_ORDER = ["concept", "protagonist", "world", "segment", "first_volume"]
PIECE_NAMES = {
    "concept": "定调",
    "protagonist": "主角",
    "world": "世界与人",
    "segment": "第一段",
    "first_volume": "第一卷",
}
TARGET_NAMES = {
    "concept": "定调",
    "protagonist": "主角卡",
    "world": "世界与人",
    "segment": "第一段的走向",
    "volumes": "第一段的分卷与线索",
    "first_volume": "第一卷卷纲",
}
SYNC_INSTRUCTIONS = {
    "protagonist": "根据修改后的定调同步检查主角卡；作者定下的和不受影响的部分保持原样。",
    "world": "根据修改后的定调和主角卡同步检查世界、第一张地图和这里的人；主角卡里的姓名和在乎的人要对得上；不受影响的部分保持原样。",
    "segment": "根据修改后的上游内容同步检查第一段的走向：开篇、目标、读者等什么、揭开什么、终点和全书方向，铁钉保持原样；不受影响的部分保持原样。",
    "volumes": "根据修改后的第一段走向同步检查分卷、线索和人物出场；不受影响的部分保持原样。",
    "first_volume": "根据修改后的上游内容同步检查第一卷卷纲：这一卷想做成什么、卷首处境、剧情单元和开篇落地；不受影响的部分保持原样。",
}

QUESTIONS: dict[str, list[tuple[str, str]]] = {
    "concept": [
        ("positioning", "写给谁看？"),
        ("logline", "一句话讲什么？"),
        ("selling_points", "读者会为哪种场面叫好？"),
        ("core_loop", "主角每个单元反复做什么？"),
        ("tone", "读起来什么味道？"),
        ("length_title", "写多长、叫什么？"),
    ],
    "protagonist": [
        ("start", "他从哪里起步？"),
        ("drive", "他为什么要往前走？"),
        ("person", "他是个什么样的人？"),
        ("finger", "他凭什么走得动？"),
        ("flaw_arc", "他的软肋是什么，最后变成谁？"),
        ("cared", "他在乎谁？"),
        ("interlock", "三件套咬得上吗？"),
    ],
    "world": [
        ("surface", "超凡的力量是明是暗？"),
        ("power", "升级靠什么？"),
        ("first_map", "第一张地图上谁说了算？"),
        ("opponents", "主角和谁打？"),
        ("people", "他身边有谁？"),
        ("shadows", "远处还有什么？"),
    ],
    "segment": [
        ("opening", "开篇怎么开？"),
        ("goal", "这一段主角想做成什么？"),
        ("wait", "这一段让读者等什么？"),
        ("reveal", "这一段揭开什么？"),
        ("end", "这一段走到哪里结束？"),
        ("cast", "人物什么时候登场？"),
        ("volumes", "这一段分几卷？"),
        ("direction", "结局大概往哪去？"),
    ],
    "first_volume": [
        ("want", "这一卷想做成什么？"),
        ("pressure", "卷首主角被什么压着？"),
        ("climax", "卷末最大的场面是什么、结果如何？"),
        ("rival", "这一卷和谁斗？"),
        ("units", "这一卷拆成哪些剧情单元？"),
        ("growth", "主角这一卷长了什么？"),
        ("newcomers", "谁第一次登场？"),
        ("landing", "开篇落在哪里？"),
    ],
}

KINDS = {"开篇": "opening", "节点": "milestone", "结局": "ending"}
NODE_CONTENT = ("title", "event", "prerequisite", "consequence", "volume", "editor_note", "techniques")
SECRET_REF = re.compile(r"S([1-9]\d*)", re.I)
EXPECTATION_REF = re.compile(r"E([1-9]\d*)", re.I)


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def merge_nodes(
    ai_nodes: list[dict], current_nodes: list[dict], pinned_overrides: set[str] | None = None
) -> list[dict]:
    """ref 对应提示词快照；所有铁钉保留原位，本轮点名只授权改内容，其他铁钉原样恢复。"""
    current = deepcopy(current_nodes)
    allowed = pinned_overrides or set()
    entries: list[tuple[dict, int | None]] = []
    used = set()
    for draft in ai_nodes:
        ref = _number(draft.get("ref"))
        source = ref - 1 if 1 <= ref <= len(current) else None
        if source is not None and source in used:
            continue
        previous = current[source] if source is not None else {}
        if source is not None:
            used.add(source)
        if previous.get("status") == "pinned":
            node = deepcopy(previous)
            if previous.get("id") in allowed:
                node.update({key: deepcopy(draft[key]) for key in NODE_CONTENT if key in draft})
                node["techniques"] = clean_techniques(node.get("techniques") or [])
        else:
            node = {
                "id": previous.get("id"),
                "kind": KINDS.get(draft.get("kind"), draft.get("kind", "milestone")),
                "title": "",
                "event": "",
                "prerequisite": "",
                "consequence": "",
                "volume": None,
                "editor_note": "",
                "techniques": [],
                **{key: deepcopy(draft[key]) for key in NODE_CONTENT if key in draft},
                "status": "pencil",
                "origin": previous.get("origin", "ai"),
            }
            if node["kind"] not in {"opening", "milestone", "ending"}:
                node["kind"] = "milestone"
            node["techniques"] = clean_techniques(node["techniques"])
        node.pop("ref", None)
        entries.append((node, source))
    for source, node in enumerate(current):
        if node.get("status") != "pinned" or source in used:
            continue
        position = 0
        for predecessor in range(source - 1, -1, -1):
            found = next((i for i, (_, original) in enumerate(entries) if original == predecessor), None)
            if found is not None:
                position = found + 1
                break
        entries.insert(position, (deepcopy(node), source))
        used.add(source)
    if not entries:
        return []
    # 铁钉边界优先于模型新增的边界；否则新开篇/结局会把不可改的旧铁钉挤到中间。
    opening = next(
        (entry for entry in entries if entry[0].get("kind") == "opening" and entry[0].get("status") == "pinned"),
        next((entry for entry in entries if entry[0].get("kind") == "opening"), None),
    )
    ending = next(
        (
            entry
            for entry in reversed(entries)
            if entry[0].get("kind") == "ending" and entry[0].get("status") == "pinned"
        ),
        next((entry for entry in reversed(entries) if entry[0].get("kind") == "ending"), None),
    )
    for kind, chosen in (("opening", opening), ("ending", ending)):
        if chosen is None:
            # 若省略边界而留下的都是铁钉，恢复旧边界优于把铁钉改成另一种类型。
            candidates = entries if kind == "opening" else list(reversed(entries))
            chosen = next(
                (
                    entry
                    for entry in candidates
                    if entry[0].get("status") != "pinned" and entry is not opening and entry is not ending
                ),
                None,
            )
            if chosen is None:
                prior = next((node for node in current if node.get("kind") == kind), None)
                if prior is not None:
                    chosen = (deepcopy(prior), current.index(prior))
                    entries.append(chosen)
            if chosen is not None:
                chosen[0]["kind"] = kind
            if kind == "opening":
                opening = chosen
            else:
                ending = chosen
    middle = [entry for entry in entries if entry is not opening and entry is not ending]
    for node, _ in middle:
        if node.get("kind") in {"opening", "ending"} and node.get("status") != "pinned":
            node["kind"] = "milestone"
    ordered = ([opening] if opening else []) + middle + ([ending] if ending else [])
    # 内容授权不是重排授权；所有铁钉都固定在本次提示词快照的位置。
    # 快照已包含作者手工插入、删除和重排，不能让模型把未点名铁钉挪回旧位置。
    fixed = [entry for entry in ordered if entry[0].get("status") == "pinned"]
    for entry in fixed:
        ordered.remove(entry)
    for entry in sorted(fixed, key=lambda entry: entry[1]):
        if entry is opening:
            index = 0
        elif entry is ending:
            index = len(ordered)
        else:
            index = max(1 if opening else 0, min(entry[1], len(ordered) - (ending in ordered)))
        ordered.insert(index, entry)
    if any(index != source for index, (node, source) in enumerate(ordered) if node.get("status") == "pinned"):
        # 前置节点被漏删或结局前新增过多时，原位与两端规则可能无法同时成立。
        # 退回原拓扑，只采纳按 ref 对齐的内容，不能为 AI 的顺带结构调整移动作者铁钉。
        by_source = {source: node for node, source in ordered if source is not None}
        ordered = [
            ({**deepcopy(by_source.get(source, node)), "kind": node["kind"]}, source)
            for source, node in enumerate(current)
        ]
    return [{**node, "_snapshot_ref": source + 1 if source is not None else 0} for node, source in ordered]


def normalize_secrets(
    secrets: list[dict], characters: list[dict], nodes: list[dict], existing: list[dict] | None = None
) -> tuple[list[dict], int]:
    names = {str(person.get("name", "")).strip() for person in characters} - {""}
    dropped = 0
    existing = {item["seq"]: item for item in existing or [] if item.get("seq")}
    reserved = {*existing, *(_number(item.get("seq")) for item in secrets or [])}
    next_seq = max(reserved, default=0) + 1
    assigned = set()
    normalized_secrets = []
    for item in secrets or []:
        seq = _number(item.get("seq"))
        if seq <= 0 or seq in assigned:
            seq = next(
                (seq for seq, row in existing.items() if seq not in assigned and row.get("title") == item.get("title")),
                0,
            )
        if seq <= 0 or seq in assigned:
            while next_seq in reserved or next_seq in assigned:
                next_seq += 1
            seq, next_seq = next_seq, next_seq + 1
        assigned.add(seq)
        normalized = {"status": "hidden", **deepcopy(existing.get(seq, {})), **item, "seq": seq}
        knowers, known = [], set()
        for knower in item.get("knowers") or []:
            knower = (
                {"name": knower, "since_chapter": None, "how": "开书设定"} if isinstance(knower, str) else dict(knower)
            )
            name = str(knower.get("name", "")).strip()
            if name not in names:
                dropped += 1
            elif name not in known:
                knowers.append({"since_chapter": None, "how": "开书设定", **knower, "name": name})
                known.add(name)
        normalized["knowers"] = knowers
        index = _number(item.get("node"))
        normalized["node"] = index if 1 <= index <= len(nodes) else 0
        normalized_secrets.append(normalized)
    return normalized_secrets, dropped


def clean_reveals(units: list[dict], secrets: list[dict]) -> list[dict]:
    known = {_number(item.get("seq")) for item in secrets if _number(item.get("seq")) > 0}
    result = deepcopy(units)
    for unit in result:
        if "techniques" in unit:
            unit["techniques"] = clean_techniques(unit["techniques"])
        if "reveals" not in unit:
            continue
        reveals = []
        for reveal in unit.get("reveals") or []:
            match = SECRET_REF.fullmatch(str(reveal.get("ref", "")).strip())
            if match and int(match[1]) in known:
                reveals.append({**reveal, "ref": f"S{int(match[1])}"})
        unit["reveals"] = reveals
    return result


def normalize_world(world: dict, protagonist: dict) -> tuple[dict, list[dict]]:
    result = deepcopy(world)
    notes = []
    characters = result.setdefault("characters", [])
    name = protagonist.get("name", "").strip()
    hero = next((person for person in characters if person.get("role_type") == "主角"), None)
    if hero is None and name:
        characters.insert(
            0,
            {
                "name": name,
                "role_type": "主角",
                "personality": protagonist.get("personality", ""),
                "background": protagonist.get("start", ""),
                "abilities": protagonist.get("finger", ""),
                "goal": protagonist.get("pursuit", ""),
                "want": protagonist.get("trigger", ""),
            },
        )
        notes.append({"question": "people", "text": f"人物表里没有主角，已按主角卡补上「{name}」。"})
    elif hero is not None and name and hero.get("name") != name:
        previous = hero.get("name")
        hero["name"] = name
        for relationship in result.get("relationships") or []:
            for end in ("source", "target"):
                if relationship.get(end) == previous:
                    relationship[end] = name
        notes.append({"question": "people", "text": f"人物表里的主角已改回主角卡上的名字「{name}」。"})
    names = {person.get("name") for person in characters}
    added = []
    for cared in protagonist.get("cared") or []:
        name = str(cared.get("name", "")).strip()
        if name and name not in names:
            characters.append(
                {
                    "name": name,
                    "role_type": "配角",
                    "background": f"主角的{cared.get('relation', '')}：{cared.get('why', '')}",
                }
            )
            names.add(name)
            added.append(name)
    if added:
        notes.append({"question": "people", "text": f"已按主角卡补上在乎的人：{'、'.join(added)}。"})
    result["relationships"] = [
        r for r in result.get("relationships") or [] if r.get("source") in names and r.get("target") in names
    ]
    if "first_map" in result:
        result["maps"] = [result.pop("first_map")]
    result.setdefault("maps", [])
    result.setdefault("mystery_answer", "")
    result.pop("remark", None)
    result.pop("decisions", None)
    return result, notes


def normalize_segment(
    draft: dict,
    previous_nodes: list[dict],
    characters: list[dict],
    previous: dict,
    *,
    world: dict | None = None,
    pinned_overrides: set[str] | None = None,
    existing_ledger: list[dict] | None = None,
) -> tuple[dict, list[dict]]:
    from app.services.setup_store import assign_seqs

    nodes = merge_nodes(draft.get("nodes") or [], previous_nodes, pinned_overrides=pinned_overrides)
    notes = []
    for node in nodes:
        node["segment"] = None
    end = nodes[1] if len(nodes) > 1 and nodes[1].get("kind") != "ending" else None
    wait = deepcopy(draft.get("wait") or {})
    if end is None:
        notes.append({"question": "end", "text": "开篇后面还没有这一段的终点。"})
    else:
        maps = (world or {}).get("maps") or []
        end["segment"] = {
            "number": 1,
            "status": "confirmed",
            "planned_at": 0,
            "map": maps[0].get("name", "") if maps else "",
            "trouble": "",
            "opponent": "",
            "goal": draft.get("goal", ""),
            "goal_link": draft.get("goal_link", ""),
            "wait": wait.get("description", ""),
            "reveal": draft.get("reveal", ""),
            "opening": deepcopy(draft.get("opening") or {}),
            "carried": "",
            "pursuit": "",
            "finger_next": "",
            "answers": "",
            "finale": False,
        }
    expectations = assign_seqs(
        [{**wait, "kind": "期待", "span": "长", "node": 2 if end else 0}] if wait else [],
        existing_ledger
        if existing_ledger is not None
        else [*(previous.get("foreshadowings") or []), *(previous.get("expectations") or [])],
    )
    secrets, dropped = normalize_secrets(draft.get("secrets") or [], characters, nodes, previous.get("secrets") or [])
    if dropped:
        notes.append({"question": "reveal", "text": f"已丢弃 {dropped} 个不在人物表里的知情人。"})
    return {
        **{key: draft.get(key, "") for key in ("core_conflict", "theme", "protagonist_arc")},
        "nodes": nodes,
        "secrets": secrets,
        "expectations": expectations,
        "foreshadowings": deepcopy(previous.get("foreshadowings") or []),
    }, notes


def normalize_volumes(
    part: dict, segment: dict, characters: list[dict], start: int, end_index: int = 2
) -> tuple[dict, dict, list[dict]]:
    part, segment = deepcopy(part), deepcopy(segment)
    notes = []
    nodes = segment.get("nodes") or []
    endpoint = nodes[end_index - 1] if 1 <= end_index <= len(nodes) else None
    volumes = sorted(part.get("volumes") or [], key=lambda row: _number(row.get("index")))
    part["volumes"] = volumes
    last = start + len(volumes) - 1
    for index, volume in enumerate(volumes, start):
        volume["index"] = index
        volume["chapter_count"] = max(0, _number(volume.get("chapter_count")))
        volume["techniques"] = clean_techniques(volume.get("techniques") or [])
        if _number(volume.get("target_node")) != end_index:
            notes.append(
                {"question": "volumes", "text": f"第 {index} 卷没有走向这一段的终点，已改为节点 {end_index}。"}
            )
        volume.update(target_node=end_index, reaches_node=index == last)
        volume["target_node_title"] = endpoint.get("title", "") if endpoint else ""
    if endpoint and volumes:
        if endpoint.get("status") == "pinned" and endpoint.get("volume") != last:
            notes.append(
                {
                    "question": "volumes",
                    "text": f"铁钉节点 {end_index} 约第 {endpoint.get('volume')} 卷，和这一段的最后一卷（第 {last} 卷）对不上，没有改动铁钉。",
                }
            )
        elif endpoint.get("status") != "pinned":
            endpoint["volume"] = last
    if volumes:
        for expectation in segment.get("expectations") or []:
            if _number(expectation.get("node")) != end_index:
                continue
            expectation["plant_volume"] = max(start, min(last, _number(expectation.get("plant_volume"))))
            if not start <= _number(expectation.get("payoff_volume")) <= last:
                expectation["payoff_volume"] = last
    threads, seen = [], set()
    for thread in part.get("threads") or []:
        name = str(thread.get("name", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        thread["name"] = name
        thread["beats"] = sorted(
            [beat for beat in thread.get("beats") or [] if start <= _number(beat.get("volume")) <= last],
            key=lambda beat: _number(beat.get("volume")),
        )
        threads.append(thread)
    part["threads"] = threads
    for volume in volumes:
        volume["thread_beats"] = [
            {"thread": thread["name"], "beat": beat.get("beat", "")}
            for thread in threads
            for beat in thread["beats"]
            if _number(beat.get("volume")) == volume["index"]
        ]
    names = {person.get("name") for person in characters}
    anchors, seen, dropped = [], set(), 0
    for anchor in part.get("anchors") or []:
        name, index = str(anchor.get("character", "")).strip(), _number(anchor.get("node"))
        if name not in names or not 1 <= index <= len(nodes):
            dropped += 1
            continue
        key = (name, index, anchor.get("kind", "登场"))
        if key not in seen:
            anchors.append(
                {**anchor, "character": name, "node": index, "node_title": nodes[index - 1].get("title", "")}
            )
            seen.add(key)
    part["anchors"] = anchors
    if dropped:
        notes.append({"question": "cast", "text": f"已丢弃 {dropped} 条不合法的人物锚点。"})
    return part, segment, notes


def piece_checks(piece: str, setup: dict) -> list[dict]:
    from app.agents.context import planned_chapters

    checks = []

    def add(question: str, text: str) -> None:
        checks.append({"question": question, "text": text})

    def empty(value) -> bool:
        return not str(value or "").strip()

    concept, protagonist, world, segment, volumes, first = (setup.get(key) or {} for key in ORDER)
    nodes = segment.get("nodes") or []
    if piece == "concept":
        if empty(concept.get("target_reader")):
            add("positioning", "还没写写给谁看：男频还是女频、读者爱看什么、最讨厌什么。")
        logline = str(concept.get("logline") or "").strip()
        if not logline:
            add("logline", "还没写一句话故事。")
        elif len(logline) > 60:
            add("logline", f"一句话故事有 {len(logline)} 个字，超过 50 字太多了。")
        count = len(concept.get("selling_points") or [])
        if not 2 <= count <= 3:
            add("selling_points", f"核心卖点现在有 {count} 个，建议 2-3 个，具体到场面。")
        if empty(concept.get("core_loop")):
            add("core_loop", "还没写核心循环：主角每个单元反复做什么。")
    elif piece == "protagonist":
        for field, question, label in (
            ("start", "start", "起点"),
            ("trigger", "drive", "开局动机"),
            ("pursuit", "drive", "长线追求"),
            ("root", "drive", "情感根源"),
            ("personality", "person", "性格"),
            ("bottom_line", "person", "底线"),
            ("voice", "person", "说话方式"),
            ("finger", "finger", "金手指·现在"),
            ("flaw", "flaw_arc", "软肋"),
            ("arc_end", "flaw_arc", "成长的终点"),
            ("interlock", "interlock", "咬合检查"),
        ):
            if empty(protagonist.get(field)):
                add(question, f"还没写「{label}」。")
        if len(str(protagonist.get("pursuit") or "").strip()) < 10:
            add("drive", "长线追求太短，写具体：找谁、向谁复仇、守护什么，不能只是「变强」。")
        if not protagonist.get("cared"):
            add("cared", "还没写开局在乎的人。")
    elif piece == "world":
        if empty(world.get("surface")):
            add("surface", "还没写世界的表里：超凡的力量是公开的还是藏着的。")
        if empty(world.get("power")):
            add("power", "还没写力量规则。")
        maps = world.get("maps") or []
        first_map = maps[0] if maps else {}
        for field, label in (
            ("name", "地图名"),
            ("powers", "谁说了算"),
            ("ceiling", "天花板"),
            ("start", "主角从哪起步"),
            ("gains", "能拿到什么"),
        ):
            if empty(first_map.get(field)):
                add("first_map", f"第一张地图还没写「{label}」。")
        characters = world.get("characters") or []
        names = [person.get("name") for person in characters if person.get("name")]
        for field, label in (("trouble", "开篇的小麻烦"), ("opponent", "这一段的大对手")):
            if empty(world.get(field)):
                add("opponents", f"还没写{label}。")
            elif not any(name in world[field] for name in names):
                add("opponents", f"{label}里没有写是人物表里的谁。")
        if not any(person.get("role_type") == "反派" for person in characters):
            add("opponents", "人物表里还没有反派。")
        count = sum(person.get("role_type") != "龙套" for person in characters)
        if count > 9:
            add("people", f"要紧人物有 {count} 个，第一张地图建议七八个以内，名字多了新读者记不住。")
        if empty(world.get("mystery")):
            add("shadows", "还没写核心谜团的谜面。")
    elif piece == "segment":
        endpoint = nodes[1] if len(nodes) > 1 and nodes[1].get("kind") != "ending" else {}
        info = endpoint.get("segment") or {}
        opening = info.get("opening") or {}
        for field, label in (
            ("scene", "第一章的切入场面"),
            ("pressure", "前 3 章压着主角的事"),
            ("first_win", "第一个小爽点"),
            ("finger", "金手指露头"),
            ("hook", "第 3 章的钩子"),
        ):
            if empty(opening.get(field)):
                add("opening", f"开篇还没写「{label}」。")
        if empty(info.get("goal")):
            add("goal", "还没写这一段的目标。")
        if empty(info.get("goal_link")):
            add("goal", "还没写做成这一段的目标为什么离长线追求更近。")
        if not segment.get("expectations"):
            add("wait", "还没写这一段让读者等什么。")
        if empty(info.get("reveal")):
            add("reveal", "还没写这一段揭开什么。")
        if not segment.get("secrets"):
            add("reveal", "这一段还没有用得到的信息差。")
        if any(sum(node.get("kind") == kind for node in nodes) != 1 for kind in ("opening", "ending")):
            add("end", "需要且只能有一个开篇、一个结局。")
        if not endpoint:
            add("end", "开篇后面还没有这一段的终点。")
        else:
            for field, label in (("prerequisite", "之前得先有"), ("consequence", "之后变成")):
                if empty(endpoint.get(field)):
                    add("end", f"这一段的终点还没写「{label}」。")
        ending = next((node for node in nodes if node.get("kind") == "ending"), {})
        if empty(ending.get("event")):
            add("direction", "还没写结局方向。")
        if empty(segment.get("protagonist_arc")):
            add("direction", "还没写主角最后变成什么样的人。")
        for index, node in enumerate(nodes, 1):
            if node.get("status") == "empty":
                add("direction", f"节点 {index} 仍然留空，确认时需要补齐。")
        cards = volumes.get("volumes") or []
        if not cards:
            add("volumes", "这一段还没有分卷。")
        elif len(cards) > 3:
            add("volumes", f"这一段分了 {len(cards)} 卷，通常一到三卷；远处的卷写到再定。")
        for card in cards:
            if not _number(card.get("chapter_count")):
                add("volumes", f"第 {card.get('index')} 卷还没写预计章数。")
            if empty(card.get("want")):
                add("volumes", f"第 {card.get('index')} 卷还没写这一卷想做成什么。")
        actual = sum(_number(card.get("chapter_count")) for card in cards)
        planned = planned_chapters(concept)
        if planned and actual > planned:
            add("volumes", f"这一段约 {actual} 章，已经超过全书计划的 {planned} 章。")
        if not volumes.get("threads"):
            add("volumes", "这一段还没有线索。")
        arrived = {anchor.get("character") for anchor in volumes.get("anchors") or [] if anchor.get("kind") == "登场"}
        for character in world.get("characters") or []:
            if character.get("role_type") != "龙套" and character.get("name") not in arrived:
                add("cast", f"「{character.get('name')}」还没写什么时候登场。")
    elif piece == "first_volume":
        if empty(first.get("want")):
            add("want", "还没写这一卷想做成什么。")
        if empty(first.get("pressure")):
            add("pressure", "还没写卷首处境。")
        seqs = {
            _number(item.get("seq"))
            for item in [*(segment.get("expectations") or []), *(first.get("new_expectations") or [])]
        }
        for unit in first.get("units") or []:
            if not any(
                (match := EXPECTATION_REF.fullmatch(str(action.get("ref", "")).strip())) and int(match[1]) in seqs
                for action in unit.get("foreshadow_actions") or []
            ):
                add("units", f"单元 {unit.get('index')}「{unit.get('title', '')}」没有安排期待动作。")
            if empty(unit.get("loop")):
                add("units", f"单元 {unit.get('index')}「{unit.get('title', '')}」还没写核心循环怎么转一圈。")
    return checks
