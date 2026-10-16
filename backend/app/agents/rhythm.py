"""章纲节奏底线与期待超期检查：只检查实际提供了情绪的章纲，保留旧书的空白。"""

from typing import Any

from app.agents.context import foreshadow_code

RHYTHM = {
    "harem_xuanhuan": {"max_low_streak": 3, "low_share": 1 / 3},
    "general": {"max_low_streak": 5, "low_share": 1 / 2},
}
MOOD_REPEAT = 4
CLIMAX_TAIL = 2
REMIND_AFTER = {"短": 20, "中": 20, "长": 50}


def rhythm_text(playbook_key: str) -> str:
    rules = RHYTHM.get(playbook_key, RHYTHM["general"])
    share = "三分之一" if rules["low_share"] == 1 / 3 else "二分之一"
    return (
        "【这本书的节奏底线】\n"
        f"- 连续压抑（情绪 ≤ -1）最多 {rules['max_low_streak']} 章。\n"
        f"- 一个单元里压抑的章不超过{share}。\n"
        f"- 同一种主情绪不要连续 {MOOD_REPEAT} 章。\n"
        f"- 单元里情绪最高的一章放在最后 {CLIMAX_TAIL} 章内。"
    )


def check_chapter_plan(chapters: list[dict], playbook_key: str, prior: list[dict]) -> list[str]:
    """index 是全书章号；没有时按列表顺序补号。旧章纲不计入分母，也不把两侧拼成连续段。"""
    rules = RHYTHM.get(playbook_key, RHYTHM["general"])
    first = int(chapters[0].get("index") or len(prior) + 1) if chapters else 1
    history = [dict(c, index=c.get("index") or first - len(prior) + i) for i, c in enumerate(prior)][-5:]
    current = [dict(c, index=c.get("index") or first + i) for i, c in enumerate(chapters)]
    valid = [c for c in current if isinstance(c.get("emotion"), int | float)]
    if not valid:
        return []
    issues: list[str] = []
    lows: list[dict] = []
    moods: list[dict] = []

    def flush_low() -> None:
        if len(lows) > rules["max_low_streak"] and any(c["index"] >= first for c in lows):
            issues.append(
                f"第 {lows[0]['index']}-{lows[-1]['index']} 章连续 {len(lows)} 章压抑"
                f"（底线 {rules['max_low_streak']} 章），中间安排一次小的扬或爆发"
            )

    def flush_mood() -> None:
        if len(moods) >= MOOD_REPEAT and any(c["index"] >= first for c in moods):
            issues.append(f"第 {moods[0]['index']}-{moods[-1]['index']} 章主情绪都是「{moods[0]['mood']}」，换一换")

    for chapter in [*history, *current, {}]:
        emotion = chapter.get("emotion")
        known = isinstance(emotion, int | float)
        if known and emotion <= -1:
            lows.append(chapter)
        else:
            flush_low()
            lows = []
        mood = chapter.get("mood") if known else None
        if not mood or (moods and moods[-1]["mood"] != mood):
            flush_mood()
            moods = []
        if mood:
            moods.append(chapter)
    low_count = sum(c["emotion"] <= -1 for c in valid)
    if low_count > len(valid) * rules["low_share"]:
        share = "三分之一" if rules["low_share"] == 1 / 3 else "二分之一"
        issues.append(f"本单元 {len(valid)} 章里有 {low_count} 章压抑，超过{share}")
    peak = max(c["emotion"] for c in valid)
    peaks = [c["index"] for c in valid if c["emotion"] == peak]
    # 并列最高时，最后两章中有一章达到最高即可；旧章纲仍占原来的章节位置。
    if not any(index >= current[-1]["index"] - CLIMAX_TAIL + 1 for index in peaks):
        issues.append(f"单元情绪最高的一章在第 {peaks[-1]} 章，不在最后 {CLIMAX_TAIL} 章内，把高潮往后挪")
    return issues


def overdue_expectations(
    ledger: list[dict[str, Any]], unit_first: int, unit_last: int, actions: list[dict]
) -> list[str]:
    """只认正确的期待编号；本单元已安排提醒或兑现的无需重复提醒。"""
    arranged = {a.get("ref", "").strip().upper() for a in actions if a.get("action") in ("提醒", "回收")}
    issues = []
    for item in ledger:
        if item.get("kind") != "期待" or item.get("status") != "planted":
            continue
        ref = foreshadow_code(item)
        chapters = [int(c) for c in [item.get("planted_chapter"), *(item.get("hint_chapters") or [])] if c]
        if not chapters:
            continue
        silence = unit_last - max(chapters)
        if silence > REMIND_AFTER.get(item.get("span"), 20) and ref not in arranged:
            issues.append(f"{ref}「{item.get('description', '')}」已经 {silence} 章没提了，本单元安排一次提醒或兑现")
    return issues
