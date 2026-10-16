"""开书拼图的确定性规则：快照合并、引用清洗与程序提醒，不触发模型或保存。"""

import re
from copy import deepcopy
from typing import Any

from app.agents.glossary import clean_techniques

ORDER = ["concept", "spine", "lore", "outline", "threads", "first_volume"]
PIECES = {
    "concept": ["concept"],
    "nodes": ["spine"],
    "cast": ["lore"],
    "fill": ["outline", "threads"],
    "first_volume": ["first_volume"],
}
PIECE_ORDER = ["concept", "nodes", "cast", "fill", "first_volume"]
PIECE_NAMES = {"concept": "定调", "nodes": "关键节点", "cast": "人物上轴", "fill": "填中间", "first_volume": "第一卷"}
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
    """ref 对应提示词快照；作者本轮点名的铁钉只改内容、保留原位，其他铁钉照旧恢复。"""
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
    # 内容授权不是重排授权；只固定本轮点名的铁钉，未授权节点沿用原合并规则。
    fixed = [entry for entry in ordered if entry[0].get("status") == "pinned" and entry[0].get("id") in allowed]
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
    if any(
        index != source
        for index, (node, source) in enumerate(ordered)
        if node.get("status") == "pinned" and node.get("id") in allowed
    ):
        # 前置节点被漏删或结局前新增过多时，原位与两端规则可能无法同时成立。
        # 退回原拓扑，只采纳按 ref 对齐的内容，不能为 AI 的顺带结构调整移动作者铁钉。
        by_source = {source: node for node, source in ordered if source is not None}
        ordered = [
            ({**deepcopy(by_source.get(source, node)), "kind": node["kind"]}, source)
            for source, node in enumerate(current)
        ]
    return [{**node, "_snapshot_ref": source + 1 if source is not None else 0} for node, source in ordered]


def normalize_lore(
    lore: dict, nodes: list[dict], existing_secrets: list[dict] | None = None
) -> tuple[dict, dict[str, int]]:
    result = deepcopy(lore)
    names = {str(person.get("name", "")).strip() for person in result.get("characters") or []} - {""}
    dropped = {"dropped_anchors": 0, "dropped_knowers": 0}
    anchors, seen = [], set()
    for anchor in result.get("anchors") or []:
        name, index = str(anchor.get("character", "")).strip(), _number(anchor.get("node"))
        if name not in names or not 1 <= index <= len(nodes):
            dropped["dropped_anchors"] += 1
            continue
        key = (name, index, anchor.get("kind", "登场"))
        if key not in seen:
            anchors.append(
                {**anchor, "character": name, "node": index, "node_title": nodes[index - 1].get("title", "")}
            )
            seen.add(key)
    if "anchors" in result:
        result["anchors"] = anchors
    existing = {item["seq"]: item for item in existing_secrets or [] if item.get("seq")}
    reserved = {*existing, *(_number(item.get("seq")) for item in result.get("secrets") or [])}
    next_seq = max(reserved, default=0) + 1
    assigned = set()
    secrets = []
    for item in result.get("secrets") or []:
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
                dropped["dropped_knowers"] += 1
            elif name not in known:
                knowers.append({"since_chapter": None, "how": "开书设定", **knower, "name": name})
                known.add(name)
        normalized["knowers"] = knowers
        index = _number(item.get("node"))
        normalized["node"] = index if 1 <= index <= len(nodes) else 0
        secrets.append(normalized)
    if "secrets" in result:
        result["secrets"] = secrets
    return result, dropped


def normalize_outline(outline: dict, nodes: list[dict]) -> tuple[dict, list[dict], list[str]]:
    result, current = deepcopy(outline), deepcopy(nodes)
    warnings = []
    reached = {}
    for volume in result.get("volumes") or []:
        index, target = _number(volume.get("index")), _number(volume.get("target_node"))
        volume["techniques"] = clean_techniques(volume.get("techniques") or [])
        if not 1 <= target <= len(current):
            volume["target_node"] = 0
            volume["reaches_node"] = False
            warnings.append(f"第 {index} 卷的目标节点 {target} 不存在，已清空，请重新指定。")
            continue
        volume["target_node"] = target
        node = current[target - 1]
        volume["target_node_title"] = node.get("title", "")
        if volume.get("reaches_node"):
            if target in reached and reached[target] != index:
                warnings.append(f"节点 {target} 同时安排在第 {reached[target]}、{index} 卷发生，请确认。")
            reached[target] = index
            if node.get("volume") != index:
                if node.get("status") == "pinned":
                    warnings.append(
                        f"第 {index} 卷与铁钉节点 {target}「{node.get('title', '')}」的约第 {node.get('volume')} 卷冲突，未修改铁钉节点。"
                    )
                else:
                    node["volume"] = index
    for key, kind in (("foreshadowings", "伏笔"), ("expectations", "期待")):
        for item in result.get(key) or []:
            item.update(kind=kind, span="长")
            target = _number(item.get("node"))
            item["node"] = target if 1 <= target <= len(current) else 0
    return result, current, warnings


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


def piece_warnings(piece: str, setup: dict, dropped: dict[str, int] | None = None) -> list[str]:
    from app.agents.context import planned_chapters

    warnings = []
    nodes = (setup.get("spine") or {}).get("nodes") or []
    concept, lore, outline = (setup.get(name) or {} for name in ("concept", "lore", "outline"))
    if piece == "nodes":
        for kind, label in (("opening", "开篇"), ("ending", "结局")):
            if sum(node.get("kind") == kind for node in nodes) != 1:
                warnings.append(f"需要且只能有一个{label}节点。")
        count = sum(node.get("kind") == "milestone" for node in nodes)
        if not 6 <= count <= 12:
            warnings.append(f"中间节点现在有 {count} 个，建议 6–12 个。")
        previous, occupied = 0, set()
        total = _number(concept.get("target_volumes"))
        for index, node in enumerate(nodes, 1):
            if node.get("kind") != "opening" and not str(node.get("prerequisite") or "").strip():
                warnings.append(f"节点 {index}「{node.get('title', '')}」还没写「之前得先有」。")
            if not str(node.get("consequence") or "").strip():
                warnings.append(f"节点 {index}「{node.get('title', '')}」还没写「之后变成」。")
            volume = _number(node.get("volume"))
            if volume < 1:
                warnings.append(f"节点 {index} 还没标约第几卷。")
            else:
                occupied.add(volume)
                if volume < previous:
                    warnings.append(f"节点 {index} 的约第 {volume} 卷比前一个节点更早。")
                if total and volume > total:
                    warnings.append(f"节点 {index} 的约第 {volume} 卷超过计划的 {total} 卷。")
                previous = volume
            if node.get("status") == "empty":
                warnings.append(f"节点 {index} 仍然留空，确认时需要补齐。")
        gap = []
        for volume in range(1, (total or max(occupied, default=0)) + 2):
            if volume <= (total or max(occupied, default=0)) and volume not in occupied:
                gap.append(volume)
            else:
                if len(gap) >= 3:
                    warnings.append(f"第 {gap[0]}–{gap[-1]} 卷连续 {len(gap)} 卷没有关键节点。")
                gap = []
    elif piece == "cast":
        anchored = {anchor.get("character") for anchor in lore.get("anchors") or []}
        for person in lore.get("characters") or []:
            if (
                any(kind in str(person.get("role_type", "")) for kind in ("主角", "女主", "反派"))
                and person.get("name") not in anchored
            ):
                warnings.append(f"{person.get('role_type')}「{person.get('name')}」还没有人物锚点。")
        for key, label in (("dropped_anchors", "不合法的人物锚点"), ("dropped_knowers", "不在人物表里的知情人")):
            if (dropped or {}).get(key):
                warnings.append(f"已丢弃 {(dropped or {})[key]} 条{label}。")
        if len(lore.get("secrets") or []) < 4:
            warnings.append("信息差少于 4 条，建议补足关键秘密与知情人的差别。")
    elif piece == "fill":
        volumes = sorted(outline.get("volumes") or [], key=lambda volume: _number(volume.get("index")))
        planned = planned_chapters(concept)
        actual = sum(_number(volume.get("chapter_count")) for volume in volumes)
        if planned and actual != planned:
            warnings.append(f"分卷章数合计 {actual} 章，与计划 {planned} 章不一致。")
        reached = {_number(volume.get("target_node")) for volume in volumes if volume.get("reaches_node")}
        for index, node in enumerate(nodes, 1):
            if node.get("kind") != "opening" and index not in reached:
                warnings.append(f"节点 {index}「{node.get('title', '')}」还没有卷安排本卷发生。")
        previous = 0
        for volume in volumes:
            target = _number(volume.get("target_node"))
            if target and target < previous:
                warnings.append(f"第 {volume.get('index')} 卷的目标节点序号倒退。")
            if target:
                previous = target
        if len(outline.get("expectations") or []) < 2:
            warnings.append("长线期待少于 2 条。")
        for key, kind in (("foreshadowings", "伏笔"), ("expectations", "期待")):
            for item in outline.get(key) or []:
                if _number(item.get("plant_volume")) > _number(item.get("payoff_volume")):
                    warnings.append(f"{kind}「{item.get('description', '')}」的立下／埋下卷晚于兑现／回收卷。")
    elif piece == "first_volume":
        first = setup.get("first_volume") or {}
        seqs = {
            _number(item.get("seq"))
            for item in [*(outline.get("expectations") or []), *(first.get("new_expectations") or [])]
        }
        for unit in first.get("units") or []:
            actions = unit.get("foreshadow_actions") or []
            if not any(
                (match := EXPECTATION_REF.fullmatch(str(action.get("ref", "")).strip())) and int(match[1]) in seqs
                for action in actions
            ):
                warnings.append(f"单元 {unit.get('index')}「{unit.get('title', '')}」没有安排期待动作。")
    return warnings


program_warnings = piece_warnings
