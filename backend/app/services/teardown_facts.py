"""「这本书好在哪」的数字由程序算，模型只拿整理好的事实写白话。"""

from collections import Counter

from app.services.teardown_roster import Roster
from app.services.teardown_world import evenly


def canonical_name(name: str, roster: Roster, names: dict[str, str]) -> str:
    person = roster.find(name.strip())
    original = person["name"] if person else name.strip()
    return names.get(original, original)


def build_facts(
    reads: list[dict],
    units: list[dict],
    volumes: list[dict],
    roster: Roster,
    protagonist: str,
    names: dict[str, str],
    upto: int,
) -> str:
    chapters = sorted((chapter for chapter in reads if 1 <= chapter["index"] <= upto), key=lambda c: c["index"])
    protagonist = canonical_name(protagonist, roster, names)
    lines = [f"读到第 {upto} 章，共 {len(chapters)} 章。", f"主角：{protagonist}。"]
    first = next((chapter for chapter in chapters if chapter["index"] == 1), {})
    lines.append(f"第 1 章摘要：{first.get('summary', '')}")
    lines.append(
        "前三章的结尾钩子："
        + "；".join(
            f"第 {chapter['index']} 章「{chapter.get('hook', '')}」" for chapter in chapters if chapter["index"] <= 3
        )
    )
    goldfinger = next(
        (
            (chapter["index"], thing["name"])
            for chapter in chapters
            for thing in chapter.get("things", [])
            if thing["kind"] == "金手指"
        ),
        None,
    )
    lines.append(
        f"金手指第一次出现：第 {goldfinger[0]} 章「{goldfinger[1]}」。" if goldfinger else "记录里没有金手指。"
    )
    cool = next((chapter for chapter in chapters if chapter.get("feel") in ("爽", "大爽")), None)
    if cool:
        lines.append(f"第一次爽：第 {cool['index']} 章，看点「{cool.get('cool_point', '')}」。")
    feel = Counter(chapter.get("feel") for chapter in chapters)
    lines.append(
        "读者感觉（模型判的）："
        + "，".join(f"{kind} {feel.get(kind, 0)} 章" for kind in ("憋屈", "平", "爽", "大爽"))
        + "。"
    )
    big = [chapter["index"] for chapter in chapters if chapter.get("feel") == "大爽"]
    if big:
        lines.append(f"大爽在第 {'、'.join(map(str, big))} 章。")
    best, run = [], []
    for chapter in chapters:
        if chapter.get("feel") == "憋屈":
            run = [*run, chapter["index"]] if not run or chapter["index"] == run[-1] + 1 else [chapter["index"]]
        else:
            run = []
        if len(run) > len(best):
            best = run
    lines.append(f"最长连着憋屈：第 {best[0]}–{best[-1]} 章，{len(best)} 章。" if best else "没有憋屈的章。")
    units = sorted(
        (unit for unit in units if 1 <= unit["first"] <= unit["last"] <= upto), key=lambda unit: unit["first"]
    )
    if units:
        sizes = [unit["last"] - unit["first"] + 1 for unit in units]
        lines.append(
            f"单元：{len(units)} 个，平均 {sum(sizes) / len(sizes):.1f} 章，最短 {min(sizes)} 章，最长 {max(sizes)} 章。"
        )
        lines.append(
            "各单元：" + "；".join(f"第 {unit['first']}–{unit['last']} 章「{unit['title']}」" for unit in units)
        )
    volumes = sorted(
        (volume for volume in volumes if 1 <= volume["first"] <= min(volume["last"], upto)),
        key=lambda volume: volume["index"],
    )
    if volumes:
        lines.append(
            "卷："
            + "；".join(
                f"第 {volume['index']} 卷「{volume['title']}」第 {volume['first']}–{min(volume['last'], upto)} 章"
                for volume in volumes
            )
        )
    changes = list(
        dict.fromkeys(
            (chapter["index"], person["change"])
            for chapter in chapters
            for person in chapter.get("people", [])
            if canonical_name(person["name"], roster, names) == protagonist and person.get("change")
        )
    )
    lines.append(
        "主角各章的变化：\n"
        + ("\n".join(f"- 第 {index} 章：{change}" for index, change in evenly(changes, 80)) or "（没有）")
    )
    waits = [
        (chapter["index"], wait["action"], wait["what"]) for chapter in chapters for wait in chapter.get("waits", [])
    ]
    lines.append(
        "读者在等的事（各章立下、提起、兑现的）：\n"
        + ("\n".join(f"- 第 {index} 章{action}：{what}" for index, action, what in evenly(waits, 80)) or "（没有）")
    )
    tropes, first_use = Counter(), {}
    for chapter in chapters:
        for trope in dict.fromkeys(chapter.get("tropes", [])):
            tropes[trope] += 1
            first_use.setdefault(trope, chapter["index"])
    lines.append(
        "用过的桥段（用了几章、第一次在第几章）："
        + "；".join(f"{trope} {count} 章（第 {first_use[trope]} 章起）" for trope, count in tropes.most_common(12))
    )
    moments: dict[str, list[tuple[int, dict]]] = {}
    for chapter in chapters:
        for moment in chapter.get("moments", []):
            if roster.find(moment["who"].strip()) is None and moment["who"].strip() not in names.values():
                continue
            name = canonical_name(moment["who"], roster, names)
            moments.setdefault(name, []).append((chapter["index"], moment))
    top = sorted(moments.items(), key=lambda item: -len(item[1]))[:5]
    lines.append(
        "名场面最多的人：\n"
        + "\n".join(
            f"- {name}（{len(scenes)} 场）："
            + "；".join(f"第 {index} 章 {moment['what']}——{moment['shows']}" for index, moment in scenes[:4])
            for name, scenes in top
        )
    )
    return "\n".join(lines)
