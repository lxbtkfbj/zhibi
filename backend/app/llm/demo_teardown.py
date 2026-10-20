"""拆书整理演示：只搬传入的记录，不补小说事实；章号限于已读范围。"""

import re

from app.agents import schemas as s

SCHEMAS = {
    s.TeardownCardMoment,
    s.TeardownTie,
    s.TeardownNow,
    s.TeardownCard,
    s.TeardownLevel,
    s.TeardownLadder,
    s.TeardownLadders,
    s.TeardownGoldfinger,
    s.TeardownGoldfingers,
    s.TeardownPlace,
    s.TeardownPlaces,
    s.TeardownFaction,
    s.TeardownFactions,
    s.TeardownItem,
    s.TeardownItems,
    s.TeardownSecret,
    s.TeardownSecrets,
    s.TeardownRule,
    s.TeardownRules,
    s.TeardownPoint,
    s.TeardownMerits,
}


def _last(user):
    match = re.search(r"已经读到第 (\d+) 章", user)
    return max(1, int(match[1])) if match else 1


def _card(user):
    last = _last(user)
    person = re.search(r"【这个人】(.+?)（也叫：(.*?)）；", user)
    name, aliases = (person[1], person[2]) if person else ("演示人物", "无")
    protagonist = re.search(r"【主角】([^\n]+)", user)
    shown = re.findall(r"^第 (\d+) 章：(.*)$", user, re.M)
    notes = [note for chapter, note in shown if 1 <= int(chapter) <= last]
    moments = [
        s.TeardownCardMoment(chapter=int(chapter), what=what, shows=shows)
        for chapter, what, shows in re.findall(r"^第 (\d+) 章名场面：(.*?)——立住了(.*)$", user, re.M)
        if 1 <= int(chapter) <= last
    ]
    return s.TeardownCard(
        name=name,
        aliases=[] if aliases == "无" else aliases.split("、"),
        one_line=(notes[0] if notes else "记录里未写清身份")[:30],
        role_type="主角" if protagonist and protagonist[1].strip() == name else "配角",
        background="；".join(notes[:2]),
        moments=moments[:4],
        missing=["所属", "性别", "年龄", "外貌", "性格与说话方式", "想要什么", "软肋", "能力", "此刻"],
    )


def _things(user):
    last = _last(user)
    result = []
    for match in re.finditer(r"^- (.+?)（原文里出现过 \d+ 章，第一次在第 (\d+) 章）：(.*)$", user, re.M):
        name, first, note = match[1], int(match[2]), match[3]
        belongs = re.search(r"（属于 ([^）]+)）", note)
        result.append(
            dict(
                name=name, first=first if 1 <= first <= last else None, note=note, parent=belongs[1] if belongs else ""
            )
        )
    return result


def _world(schema, user):
    rows = _things(user)
    items = []
    for row in rows:
        common = dict(name=row["name"], first_chapter=row["first"])
        note = row["note"]
        if schema in {s.TeardownLadders, s.TeardownLadder, s.TeardownLevel}:
            items.append(s.TeardownLadder(name=row["name"], levels=[s.TeardownLevel(name=row["name"], note=note)]))
        elif schema in {s.TeardownGoldfingers, s.TeardownGoldfinger}:
            items.append(s.TeardownGoldfinger(**common, what=note))
        elif schema in {s.TeardownPlaces, s.TeardownPlace}:
            items.append(s.TeardownPlace(**common, parent=row["parent"], note=note))
        elif schema in {s.TeardownFactions, s.TeardownFaction}:
            members = [
                name for name, belongs in re.findall(r"^- ([^：\n]+)：([^\n]+)$", user, re.M) if row["name"] in belongs
            ]
            items.append(s.TeardownFaction(**common, note=note, members=members))
        elif schema in {s.TeardownItems, s.TeardownItem}:
            items.append(s.TeardownItem(**common, note=note))
        elif schema in {s.TeardownSecrets, s.TeardownSecret}:
            chapters = [
                (int(chapter), secret)
                for chapter, secret in re.findall(r"第 (\d+) 章：[^；]*?（(埋下|揭开)）", note)
                if 1 <= int(chapter) <= _last(user)
            ]
            planted = next((chapter for chapter, action in chapters if action == "埋下"), None)
            revealed = next(
                (
                    chapter
                    for chapter, action in chapters
                    if action == "揭开" and (planted is None or chapter >= planted)
                ),
                None,
            )
            items.append(
                s.TeardownSecret(name=row["name"], truth=note, planted_chapter=planted, revealed_chapter=revealed)
            )
        else:
            items.append(s.TeardownRule(**common, note=note))
    if schema is s.TeardownLadders:
        return s.TeardownLadders(ladders=items)
    if schema is s.TeardownLadder:
        return items[0] if items else s.TeardownLadder(name="演示等级", levels=[])
    if schema is s.TeardownLevel:
        return items[0].levels[0] if items else s.TeardownLevel(name="演示等级", note="记录里没有等级")
    wrappers = {
        s.TeardownGoldfingers,
        s.TeardownPlaces,
        s.TeardownFactions,
        s.TeardownItems,
        s.TeardownSecrets,
        s.TeardownRules,
    }
    if schema in wrappers:
        return schema(items=items)
    if items:
        return items[0]
    required = {s.TeardownGoldfinger: {"what": ""}, s.TeardownSecret: {"truth": ""}}
    return schema(name="演示条目", **required.get(schema, {"note": ""}))


def _merits(user):
    sections = (
        ("开头", "第 1 章摘要：", "先交代主角处境，再留下继续读的理由"),
        ("节奏", "单元：", "可以先定一个小故事的收束点，再安排章数"),
        ("变强", "- 第 ", "可以把变化安排在读者能看见的事件里"),
        ("在等什么", "读者在等的事", "可以先立一个期待，再安排提起和兑现"),
        ("桥段", "用过的桥段", "可以在熟悉的桥段里改变人物的应对"),
        ("立得住的人", "名场面最多的人", "可以用人物自己的选择来立住性格"),
    )
    points, missing = [], []
    lines = user.splitlines()
    for topic, prefix, lesson in sections:
        position = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
        if position is None:
            missing.append(f"{topic}：记录不够")
            continue
        evidence = lines[position]
        if prefix in {"读者在等的事", "名场面最多的人"} and position + 1 < len(lines):
            evidence += lines[position + 1]
        points.append(
            s.TeardownPoint(topic=topic, text=f"整理到第 {_last(user)} 章：{evidence[:85]}。想学的作者{lesson}。"[:150])
        )
    return s.TeardownMerits(points=points, missing=missing)


def respond(schema, user):
    if schema is s.TeardownCard:
        return _card(user)
    if schema is s.TeardownCardMoment:
        return (_card(user).moments or [s.TeardownCardMoment(chapter=1, what="记录里未写名场面", shows="")])[0]
    if schema is s.TeardownTie:
        return s.TeardownTie(who="", relation="")
    if schema is s.TeardownNow:
        return s.TeardownNow()
    if schema is s.TeardownMerits:
        return _merits(user)
    if schema is s.TeardownPoint:
        return (_merits(user).points or [s.TeardownPoint(topic="开头", text="第 1 章记录不足，不作判断。")])[0]
    return _world(schema, user)
