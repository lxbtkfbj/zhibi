"""规划产出的程序化整理：章数对齐、伏笔编号与动作、挑出与某一卷相关的伏笔。"""

import math
import re
from typing import Any

from app.agents.context import foreshadow_code


def unit_hint(chapter_count: int) -> str:
    """一卷大约拆几个剧情单元（每单元 5-15 章，平均七八章）。"""
    if chapter_count <= 0:
        return "4-8"
    low = max(2, math.ceil(chapter_count / 15))
    high = max(low + 1, min(30, round(chapter_count / 7)))
    return f"{low}-{high}"


def fit_chapter_counts(units: list[dict[str, Any]], target: int, minimum: int = 3) -> list[dict[str, Any]]:
    """让各单元章数之和等于本卷预计章数：模型算错时从后往前逐章增减。"""
    if not units or target <= 0:
        return units
    out = [{**u, "chapter_count": max(minimum, int(u.get("chapter_count") or minimum))} for u in units]
    diff = target - sum(u["chapter_count"] for u in out)
    i = len(out) - 1
    guard = 0
    while diff != 0 and guard < 10_000:
        step = 1 if diff > 0 else -1
        if step > 0 or out[i]["chapter_count"] > minimum:
            out[i]["chapter_count"] += step
            diff -= step
        i = (i - 1) % len(out)
        guard += 1
    return out


def attach_new_foreshadowings(
    units: list[dict[str, Any]], fresh: list[dict[str, Any]], volume: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """新埋的伏笔（已编号）：补上卷号，并把「第几单元埋、第几单元收」写进对应单元的伏笔动作。"""
    units = [{**u, "foreshadow_actions": list(u.get("foreshadow_actions") or [])} for u in units]
    by_index = {u.get("index"): u for u in units}
    out = []
    for f in fresh:
        ref = foreshadow_code(f)
        payoff_unit = f.get("payoff_unit") or 0
        item = {
            **f,
            "plant_volume": volume,
            "payoff_volume": volume if payoff_unit else max(volume, f.get("payoff_volume") or volume + 1),
        }
        if not f.get("span"):
            item["span"] = "短" if payoff_unit == f.get("plant_unit") else "中"
        out.append(item)
        for unit_index, action, detail in (
            (f.get("plant_unit"), "埋下", f.get("plant_plan", "")),
            (payoff_unit, "回收", f.get("payoff_plan", "")),
        ):
            unit = by_index.get(unit_index)
            if unit is not None and not any(
                a.get("ref") == ref and a.get("action") == action for a in unit["foreshadow_actions"]
            ):
                unit["foreshadow_actions"].append({"ref": ref, "action": action, "detail": detail})
    return units, out


def relevant_ledger(ledger: list[dict[str, Any]], volume: int) -> list[dict[str, Any]]:
    """与某一卷相关的伏笔：计划在这卷埋或收的，以及已经埋下、还没回收的。"""
    return [
        f
        for f in ledger
        if f.get("status") != "abandoned"
        and (
            f.get("plant_volume") == volume
            or f.get("payoff_volume") == volume
            or (
                f.get("status") == "planted"
                and (f.get("kind") == "期待" or (f.get("payoff_volume") or volume) >= volume)
            )
        )
    ]


REF = re.compile(r"[FE](\d+)", re.I)
SECRET_REF = re.compile(r"S(\d+)", re.I)


def ref_seq(ref: str) -> int | None:
    match = REF.search(ref or "")
    return int(match.group(1)) if match else None


def secret_seq(ref: str) -> int | None:
    match = SECRET_REF.search(ref or "")
    return int(match.group(1)) if match else None


def schedule_issues(
    units: list[dict[str, Any]], fresh: list[dict[str, Any]], ledger: list[dict[str, Any]], volume: int
) -> list[dict[str, Any]]:
    """卷纲的伏笔排期检查（程序算的，不靠模型）。

    台账里计划在本卷埋下、回收的伏笔有没有排进单元；本卷新埋的伏笔，埋和收的单元是否存在、先后是否颠倒。
    """
    issues: list[dict[str, Any]] = []

    def add(problem: str, suggestion: str, unit: int = 0) -> None:
        issues.append(
            {"aspect": "foreshadow", "unit": unit, "problem": problem, "suggestion": suggestion, "severity": "medium"}
        )

    done: dict[str, set[str]] = {}
    for u in units:
        for a in u.get("foreshadow_actions") or []:
            code = a.get("ref", "").strip().upper()
            done.setdefault(code, set()).add(a.get("action", ""))
    for f in ledger:
        status, code = f.get("status", "planned"), foreshadow_code(f)
        if status in ("abandoned", "resolved"):
            continue
        actions = done.get(code, set())
        if f.get("plant_volume") == volume and status == "planned" and "埋下" not in actions:
            add(
                f"{code}「{f.get('description', '')}」计划在本卷埋下，卷纲里没有安排",
                f"把{code}排进某个单元的伏笔动作（埋下）",
            )
        due = status == "planted" or f.get("plant_volume") == volume
        if f.get("payoff_volume") == volume and due and "回收" not in actions:
            add(
                f"{code}「{f.get('description', '')}」计划在本卷回收，卷纲里没有安排",
                f"把{code}排进某个单元的伏笔动作（回收）",
            )
    count = len(units)
    for f in fresh:
        plant, payoff = int(f.get("plant_unit") or 1), int(f.get("payoff_unit") or 0)
        name = f"新伏笔「{f.get('description', '')}」"
        if plant > count:
            add(f"{name}埋在第{plant}单元，本卷只有 {count} 个单元", "改到存在的单元里埋下")
        elif payoff and payoff > count:
            add(f"{name}在第{payoff}单元回收，本卷只有 {count} 个单元", "改到存在的单元回收，或者改成下一卷回收", plant)
        elif payoff and payoff < plant:
            add(f"{name}回收（第{payoff}单元）比埋下（第{plant}单元）还早", "调整埋下或回收的单元", plant)
    return issues


def expectation_issues(
    units: list[dict[str, Any]],
    fresh: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    volume: int,
    first_chapter: int,
) -> list[dict[str, Any]]:
    """卷纲的期待检查：漏排与超期必须修改，单元空档和没有中长线只提示审稿。"""
    from app.agents.rhythm import REMIND_AFTER

    issues: list[dict[str, Any]] = []

    def add(problem: str, suggestion: str, unit: int = 0, *, severity: str = "medium") -> None:
        issues.append(
            {"aspect": "expectation", "unit": unit, "problem": problem, "suggestion": suggestion, "severity": severity}
        )

    expectations = [item for item in ledger if item.get("kind") == "期待"]
    codes = {foreshadow_code(item) for item in expectations}
    done: dict[str, set[str]] = {}
    unit_actions: set[int] = set()
    new_planted = False
    for unit in units:
        for action in unit.get("foreshadow_actions") or []:
            code = action.get("ref", "").strip().upper()
            if code not in codes or action.get("action") not in ("埋下", "提醒", "回收"):
                continue
            done.setdefault(code, set()).add(action["action"])
            unit_actions.add(unit.get("index", 0))
    indices = {unit.get("index") for unit in units}
    for item in fresh:
        plant, payoff = item.get("plant_unit"), item.get("payoff_unit")
        if plant in indices:
            unit_actions.add(plant)
            if item.get("span", "中") in ("中", "长"):
                new_planted = True
        if payoff in indices:
            unit_actions.add(payoff)
        name = f"新期待「{item.get('description', '')}」"
        if plant not in indices:
            add(f"{name}立下的第 {plant or 0} 个单元不存在", "把新期待安排到本卷已有的单元立下")
        elif payoff and payoff not in indices:
            add(f"{name}兑现的第 {payoff} 个单元不存在", "改到本卷已有的单元兑现，或排到后卷", plant)
        elif payoff and payoff < plant:
            add(f"{name}兑现（第 {payoff} 单元）比立下（第 {plant} 单元）还早", "先立下期待，再安排兑现", plant)
    for item in expectations:
        status = item.get("status", "planned")
        if status in ("resolved", "abandoned"):
            continue
        code = foreshadow_code(item)
        name = f"期待 {code}「{item.get('description', '')}」"
        actions = done.get(code, set())
        if item.get("plant_volume") == volume and status == "planned" and "埋下" not in actions:
            add(f"{name}计划在本卷立下，没有排进任何单元", f"把 {code} 排进某个单元的期待动作（立下）")
        if item.get("payoff_volume") == volume and "回收" not in actions:
            add(f"{name}计划在本卷兑现，没有排进任何单元", f"把 {code} 排进某个单元的期待动作（兑现）")
        if status == "planned" and item.get("span") in ("中", "长") and "埋下" in actions:
            new_planted = True
        if status != "planted":
            continue
        mentions = [chapter for chapter in [item.get("planted_chapter"), *(item.get("hint_chapters") or [])] if chapter]
        if not mentions:
            continue
        gap = first_chapter - max(mentions)
        if gap > REMIND_AFTER.get(item.get("span"), 20) and not actions.intersection({"提醒", "回收"}):
            add(f"{name}到本卷开头已经 {gap} 章没提了，本卷没有安排提醒或兑现", f"在某个单元提醒或兑现 {code}")
    for offset, unit in enumerate(units, start=1):
        index = unit.get("index", offset)
        if index not in unit_actions:
            add(f"第 {index} 个单元没有任何期待动作", "考虑安排立下、提醒或兑现一条期待", index, severity="low")
    if not new_planted and not any(
        item.get("status") == "planted" and item.get("span") in ("中", "长") for item in expectations
    ):
        add("本卷开始时没有开着的中长线期待，本卷也没有新立", "考虑在本卷新立一条中长线期待", severity="low")
    return issues
