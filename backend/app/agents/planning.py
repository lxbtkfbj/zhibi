"""规划产出的程序化整理：章数对齐、伏笔编号与动作、挑出与某一卷相关的伏笔。"""

import math
import re
from typing import Any


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
        ref = f"F{f['seq']}"
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


REF = re.compile(r"F(\d+)", re.I)


def ref_seq(ref: str) -> int | None:
    match = REF.search(ref or "")
    return int(match.group(1)) if match else None
