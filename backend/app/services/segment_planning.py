"""写作中定下一段的确定性整理和提醒；确认前不修改数据库。"""

import re
from copy import deepcopy

from app.agents.context import foreshadow_code
from app.agents.setup_puzzle import normalize_secrets

END_CONTENT = ("title", "event", "prerequisite", "consequence")


def normalize_next_segment(
    part: dict, nodes: list[dict], characters: list[dict], *, lengths: dict | None = None
) -> tuple[dict, list[dict]]:
    plan, view, notes = deepcopy(part), deepcopy(nodes), []
    lengths = lengths or {}
    last = max((i for i, node in enumerate(nodes) if node.get("segment") is not None), default=-1)
    following = last + 2
    ending = next((i for i, node in enumerate(nodes, 1) if node.get("kind") == "ending"), 0)
    end = deepcopy(plan.get("end") or {})
    ref = end.get("ref") or 0
    adopted = ref in {following, ending} and isinstance(ref, int) and 1 <= ref <= len(nodes)
    if adopted:
        current = nodes[ref - 1]
        plan["adopt"] = {
            "node_id": current.get("id"),
            "snapshot": {key: current.get(key, "") for key in END_CONTENT},
        }
        if current.get("status") == "pinned":
            end = {**end, **{key: current.get(key) for key in (*END_CONTENT, "volume")}}
        view[ref - 1] = {**current, **{key: end.get(key, "") for key in END_CONTENT}}
        if current.get("status") != "pinned":
            view[ref - 1]["volume"] = end.get("volume")
        end_index = ref
    else:
        if ref:
            notes.append({"question": "end", "text": "终点引用的节点不是紧接着的远景节点，已改为新起一个。"})
        plan["adopt"] = None
        end["ref"] = 0
        view.insert(
            last + 1,
            {**end, "id": None, "kind": "milestone", "status": "pencil", "origin": "ai", "segment": None},
        )
        end_index = last + 2
    plan["end"] = end
    plan["nodes_view"] = [{**node, "index": i} for i, node in enumerate(view, 1)]
    plan["end_index"] = end_index
    at_ending = adopted and ref == ending
    plan["finale"] = bool(lengths.get("finale") or lengths.get("last_one") or at_ending)
    if lengths.get("last_one") and not at_ending:
        notes.append({"question": "end", "text": "篇幅只够一段了，这一段的终点应该是结局。"})
    names = {str(person.get("name", "")).strip() for person in characters}
    new_characters = []
    for character in plan.get("new_characters") or []:
        name = str(character.get("name", "")).strip()
        if not name:
            continue
        if name in names:
            notes.append({"question": "people", "text": f"「{name}」已经在人物表里，没有重复添加。"})
            continue
        new_characters.append({**character, "name": name})
        names.add(name)
    plan["new_characters"] = new_characters
    plan["relationships"] = [
        relation
        for relation in plan.get("relationships") or []
        if relation.get("source") in names and relation.get("target") in names
    ]
    secrets, dropped = normalize_secrets(plan.get("secrets") or [], [*characters, *new_characters], view)
    plan["secrets"] = [{**secret, "node": end_index} for secret in secrets]
    if dropped:
        notes.append({"question": "reveal", "text": f"已丢弃 {dropped} 个不在人物表里的知情人。"})
    if plan.get("wait"):
        plan["wait"] = {**plan["wait"], "kind": "期待", "span": "长", "node": end_index}
    return plan, notes


def segment_checks(
    plan: dict,
    split: dict,
    world: dict,
    ledger: list[dict],
    nodes: list[dict],
    notes: list[dict] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    flags: dict[str, list[str]] = {}

    def add(question: str, text: str) -> None:
        if text not in flags.setdefault(question, []):
            flags[question].append(text)

    def missing(key: str, question: str, text: str) -> None:
        if not str(plan.get(key) or "").strip():
            add(question, text)

    for note in notes or []:
        add(note["question"], note["text"])
    missing("carried", "carried", "还没写上一段留下的线头怎么处理。")
    mentioned = set(re.findall(r"(?<![A-Za-z0-9])E\d+(?!\d)", str(plan.get("carried") or ""), re.I))
    mentioned = {ref.upper() for ref in mentioned}
    for item in ledger:
        if item.get("kind") == "期待" and item.get("status") == "planted" and foreshadow_code(item) not in mentioned:
            add("carried", f"{foreshadow_code(item)}「{item.get('description', '')}」还开着，这一段没说怎么处理。")
    missing("pursuit", "pursuit", "还没写主角的追求这一段怎么变。")
    missing("finger_next", "finger_next", "还没写金手指下一阶段。")
    if plan.get("finale") and not world.get("mystery_answer") and not plan.get("answers"):
        add("answers", "快写完了，核心谜团还没定谜底。")
    missing("map", "map", "还没写这一段在哪张地图。")
    if plan.get("map") and plan["map"] not in {item.get("name") for item in world.get("maps") or []}:
        new_map = plan.get("new_map") or {}
        if new_map.get("name") != plan["map"]:
            add("map", f"换到了新地图「{plan['map']}」，但还没写这张地图的详情。")
    missing("trouble", "opponents", "还没写开头压着主角的小麻烦。")
    missing("opponent", "opponents", "还没写这一段的大对手。")
    missing("goal", "goal", "还没写这一段的目标。")
    missing("goal_link", "goal", "还没写做成这一段的目标为什么离长线追求更近。")
    if not (plan.get("wait") or {}).get("description"):
        add("wait", "还没写这一段让读者等什么。")
    missing("reveal", "reveal", "还没写这一段揭开什么。")
    for field, label in (("prerequisite", "之前得先有"), ("consequence", "之后变成")):
        if not (plan.get("end") or {}).get(field):
            add("end", f"这一段的终点还没写「{label}」。")
    ending = next((node for node in nodes if node.get("kind") == "ending"), {})
    if ending.get("status") == "pinned" and plan.get("ending"):
        add("direction", "结局是铁钉，新的结局方向没有采用。")
    cards = split.get("volumes") or []
    if not cards:
        add("volumes", "这一段还没有分卷。")
    elif len(cards) > 3:
        add("volumes", f"这一段分了 {len(cards)} 卷，通常一到三卷；远处的卷写到再定。")
    for card in cards:
        if not card.get("chapter_count"):
            add("volumes", f"第 {card.get('index')} 卷还没写预计章数。")
        if not str(card.get("want") or "").strip():
            add("volumes", f"第 {card.get('index')} 卷还没写这一卷想做成什么。")
    return [text for texts in flags.values() for text in texts], flags
