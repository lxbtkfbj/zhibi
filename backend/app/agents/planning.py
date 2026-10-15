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
            or (f.get("status") == "planted" and (f.get("payoff_volume") or volume) >= volume)
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

    done: dict[int, set[str]] = {}
    for u in units:
        for a in u.get("foreshadow_actions") or []:
            seq = ref_seq(a.get("ref", ""))
            if seq:
                done.setdefault(seq, set()).add(a.get("action", ""))
    for f in ledger:
        status, code = f.get("status", "planned"), foreshadow_code(f)
        if status in ("abandoned", "resolved"):
            continue
        actions = done.get(f.get("seq"), set())
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
