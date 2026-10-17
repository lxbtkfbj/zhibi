"""开书三步的程序检查，以及写作继续使用的引用清洗。"""

import re
from copy import deepcopy
from typing import Any

from app.agents.glossary import clean_techniques

ORDER = ["concept", "settings_focus", "settings_rest", "outline", "outline_chapters"]
PIECES = {
    "concept": ["concept"],
    "settings": ["settings_focus", "settings_rest"],
    "outline": ["outline", "outline_chapters"],
}
PIECE_ORDER = ["concept", "settings", "outline"]
PIECE_NAMES = {"concept": "定调", "settings": "设定库", "outline": "大纲"}
TARGET_NAMES = {
    "concept": "定调",
    "settings_focus": "主角和金手指",
    "settings_rest": "其余设定",
    "outline": "大纲",
    "outline_chapters": "第一个单元的章纲",
}

SECRET_REF = re.compile(r"S([1-9]\d*)", re.I)


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


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
    checks = []

    def add(question: str, text: str) -> None:
        checks.append({"question": question, "text": text})

    def empty(value) -> bool:
        return not str(value or "").strip()

    if piece == "concept":
        concept = setup.get("concept") or {}
        count = len(str(concept.get("story") or "").strip())
        if not 150 <= count <= 500:
            add("story", f"定调要写成一段话，200-400 字，现在是 {count} 字。")
        if empty(concept.get("secret")):
            add("secret", "底牌还没写；这本书没有大秘密就写「没有」。")
    elif piece == "settings":
        rest = setup.get("settings_rest") or setup.get("settings") or {}
        entries = rest.get("entries") or []
        characters = rest.get("characters") or []
        if not any(entry.get("category") == "世界与地图" and entry.get("name") == "世界概况" for entry in entries):
            add("world", "世界与地图的第一条要叫「世界概况」。")
        for entry in entries:
            if entry.get("status") in {"现在要定", "must"} and empty(entry.get("content")):
                add("content", f"「{entry.get('name', '')}」是现在要定的，还没写一段话。")
            if entry.get("category") == "等级体系" and not entry.get("levels"):
                add("levels", f"「{entry.get('name', '')}」还没写各级；没有正式等级就写一级「没有」。")
        focus = setup.get("settings_focus") or {}
        hero = focus.get("protagonist") or focus.get("character")
        for person in [*characters, *([hero] if hero else [])]:
            if person.get("status", "现在要定") in {"现在要定", "must"} and any(
                empty(person.get(field)) for field in ("personality", "background", "goal")
            ):
                add("content", f"「{person.get('name', '')}」是现在要定的，还没写一段话。")
        if not any(
            person.get("role_type") != "主角" and person.get("status", "现在要定") in {"现在要定", "must"}
            for person in characters
        ):
            add("characters", "还没写第一卷登场的人物。")
    elif piece == "outline":
        outline = setup.get("outline") or {}
        arcs, volumes, units = (outline.get(key) or [] for key in ("arcs", "volumes", "units"))
        if not arcs or empty(arcs[0].get("text")):
            add("arcs", "第一篇要写一段话。")
        if any(arc.get("planned") for arc in arcs[1:]):
            add("arcs", "只有第一篇写细，后面的篇写到再定。")
        if not volumes or empty(volumes[0].get("summary")):
            add("volumes", "第 1 卷要写一段话。")
        if not units or any(empty(unit.get("summary")) for unit in units):
            add("units", "第 1 卷要拆成剧情单元，每个单元一段话。")
        chapters = (setup.get("outline_chapters") or {}).get("chapters") or outline.get("chapters")
        if not chapters:
            add("chapters", "第一个单元的章纲还没出来。")
    return checks
