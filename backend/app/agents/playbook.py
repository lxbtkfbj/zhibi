"""题材打法库：按书的类型和标签挑一套打法（套路与节奏、防重复规则），注入各层规划的提示词。

打法写在 app/prompts/playbooks/*.md，用「## 」分节，各规划环节只取用得上的几节。
「套路库」里每个套路写成「### 名称（全书最多 N 次）」，「破局手法」里每类写成「- 名称（……）：说明」，
程序据此统计全书已经用了几次，并在卷纲出来后检查有没有超限、有没有连着用。
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.prompts import _load, track_rendered

GENERAL = "general"
# 按顺序匹配：类型和标签里每一组词都至少出现一个，就用这套打法；都不匹配时用通用版
RULES: list[tuple[str, tuple[tuple[str, ...], ...]]] = [
    (
        "harem_xuanhuan",
        (
            ("玄幻", "修仙", "仙侠", "修真", "高武", "异世"),
            ("后宫", "多女主", "修罗场", "种马", "爽文", "无敌", "打脸"),
        ),
    ),
]

# 各规划环节取哪几节
STAGES: dict[str, tuple[str, ...]] = {
    "threads": ("总则", "线索", "防重复"),
    "outline": ("总则", "分卷", "套路库", "防重复"),
    "volume": ("总则", "单元", "套路库", "破局手法", "防重复"),
    "chapters": ("章节", "套路库", "防重复"),
    "review": ("单元", "套路上限", "破局手法", "防重复"),
}

CHINESE_NUMBERS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5}


@dataclass(frozen=True)
class Limit:
    book: int | None = None  # 全书最多几次
    volume: int | None = None  # 每卷最多几次
    streak: int = 1  # 最多连着用几个单元

    def label(self) -> str:
        parts = []
        if self.book is not None:
            parts.append(f"全书最多 {self.book} 次")
        if self.volume is not None:
            parts.append(f"每卷最多 {self.volume} 次")
        parts.append("不能连续两个单元" if self.streak == 1 else f"最多连续 {self.streak} 个单元")
        return "，".join(parts)


@dataclass(frozen=True)
class Playbook:
    key: str
    name: str
    sections: dict[str, str]
    tropes: dict[str, Limit]
    trope_texts: dict[str, str]
    resolutions: dict[str, Limit]

    def text(self, stage: str, tropes: list[str] | None = None) -> str:
        """某个规划环节要看的打法。tropes 给了时，套路库只带这几个套路（章纲只需要本单元用到的）。"""
        parts = []
        for section in STAGES[stage]:
            if section == "套路库" and tropes is not None:
                picked = dict.fromkeys(name for t in tropes if (name := self.canonical_trope(t)))
                body = "\n\n".join(self.trope_texts[name] for name in picked)
            elif section == "套路上限":
                body = "、".join(f"{name}（{limit.label()}）" for name, limit in self.tropes.items())
            else:
                body = self.sections.get(section, "")
            if body.strip():
                parts.append(f"◆ {section}\n{body.strip()}")
        if not parts:
            return ""
        head = f"【题材打法：{self.name}（编辑部的经验，照着用；与作者的要求冲突时以作者为准）】"
        return track_rendered(f"playbooks.{self.key}", head + "\n" + "\n\n".join(parts))

    def canonical_trope(self, text: str) -> str | None:
        return _canonical(text, self.tropes)

    def canonical_resolution(self, text: str) -> str | None:
        return _canonical(text, self.resolutions)


def _canonical(text: str, names: dict[str, Limit]) -> str | None:
    """模型写的名称对到打法库里的名称：完全相同，或者一方包含另一方（如「拍卖会风波」→「拍卖会」）。"""
    text = (text or "").strip()
    if not text:
        return None
    if text in names:
        return text
    return next((name for name in names if name in text or (len(text) >= 2 and text in name)), None)


def _limit(spec: str) -> Limit:
    book = re.search(r"全书最多\s*(\d+)\s*次", spec)
    volume = re.search(r"每卷最多\s*(\d+)\s*次", spec)
    streak = re.search(r"不能连续([一两二三四五])个单元", spec)
    return Limit(
        book=int(book.group(1)) if book else None,
        volume=int(volume.group(1)) if volume else None,
        streak=CHINESE_NUMBERS[streak.group(1)] - 1 if streak else 1,
    )


def parse(key: str, text: str) -> Playbook:
    title = re.search(r"^#\s+(.+)$", text, re.M)
    sections: dict[str, str] = {}
    for block in re.split(r"^##\s+", text, flags=re.M)[1:]:
        name, _, body = block.partition("\n")
        sections[name.strip()] = body.strip()
    if not title:
        raise ValueError("题材打法缺少一级标题（# 名称）")
    required = {section for stage in STAGES.values() for section in stage} - {"套路上限"}
    missing = sorted(section for section in required if not sections.get(section))
    if missing:
        raise ValueError("题材打法缺少有效分节：" + "、".join(missing))
    tropes: dict[str, Limit] = {}
    trope_texts: dict[str, str] = {}
    for block in re.split(r"^###\s+", sections.get("套路库", ""), flags=re.M)[1:]:
        head, _, body = block.partition("\n")
        match = re.match(r"(.+?)（(.*)）\s*$", head.strip())
        name, spec = (match.group(1).strip(), match.group(2)) if match else (head.strip(), "")
        tropes[name] = _limit(spec)
        trope_texts[name] = f"{head.strip()}\n{body.strip()}"
    resolutions = {
        m.group(1).strip(): _limit(m.group(2))
        for m in re.finditer(r"^-\s*(.+?)（(.*?)）", sections.get("破局手法", ""), re.M)
    }
    if not tropes:
        raise ValueError("套路库至少需要一个 ### 套路名称")
    if not resolutions:
        raise ValueError("破局手法至少需要一条「- 名称（限制）：说明」")
    return Playbook(
        key=key,
        name=title.group(1).strip() if title else key,
        sections=sections,
        tropes=tropes,
        trope_texts=trope_texts,
        resolutions=resolutions,
    )


def load(key: str) -> Playbook:
    if key not in {GENERAL, *(rule[0] for rule in RULES)}:
        raise ValueError(f"未知题材打法：{key}")
    return parse(key, _load(f"playbooks.{key}"))


def pick(concept: dict[str, Any] | None, selection: str = "auto") -> Playbook:
    """作者指定时直接用该打法，否则按概念里的类型和标签挑选。"""
    if selection and selection != "auto":
        return load(selection)
    concept = concept or {}
    words = " ".join([str(concept.get("genre") or ""), *map(str, concept.get("tags") or [])])
    for key, groups in RULES:
        if all(any(w in words for w in group) for group in groups):
            return load(key)
    return load(GENERAL)


def playbook_text(
    concept: dict[str, Any] | None, stage: str, tropes: list[str] | None = None, *, selection: str = "auto"
) -> str:
    return pick(concept, selection).text(stage, tropes)


# ---------- 套路使用台账 ----------


def _core(playbook: Playbook, unit: dict[str, Any]) -> str:
    """单元的核心套路：第一个套路，能对上打法库就用打法库里的名称。"""
    tropes = [t for t in unit.get("tropes") or [] if str(t).strip()]
    if not tropes:
        return ""
    return playbook.canonical_trope(tropes[0]) or str(tropes[0]).strip()


def _resolution(playbook: Playbook, unit: dict[str, Any]) -> str:
    text = str(unit.get("resolution") or "").strip()
    return playbook.canonical_resolution(text) or text


def _trope_counts(playbook: Playbook, units: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for u in units:
        names = {playbook.canonical_trope(t) or str(t).strip() for t in u.get("tropes") or [] if str(t).strip()}
        counts.update(names)
    return counts


def usage_text(playbook: Playbook, prior: list[dict[str, Any]]) -> str:
    """前面各卷用过哪些套路和破局手法、还剩几次，给规划和审稿看。prior 按卷、单元顺序排列。"""
    if not prior:
        return "（还没用过任何套路，这是第一卷）"
    tropes = _trope_counts(playbook, prior)
    resolutions = Counter(r for u in prior if (r := _resolution(playbook, u)))
    lines = []
    if tropes:
        items = []
        for name, n in tropes.most_common():
            cap = playbook.tropes[name].book if name in playbook.tropes else None
            if cap is None:
                items.append(f"{name} {n} 次")
            else:
                items.append(f"{name} {n}/{cap} 次" + ("（已用完，不能再用）" if n >= cap else ""))
        lines.append("套路：" + "、".join(items))
    if resolutions:
        items = []
        for name, n in resolutions.most_common():
            cap = playbook.resolutions[name].book if name in playbook.resolutions else None
            if cap is None:
                items.append(f"{name} {n} 次")
            else:
                items.append(f"{name} {n}/{cap} 次" + ("（已用完，不能再用）" if n >= cap else ""))
        lines.append("破局手法：" + "、".join(items))
    recent = [
        f"第{u.get('volume')}卷单元{u.get('index')}「{u.get('title', '')}」"
        f"套路「{_core(playbook, u) or '未标'}」、破局「{_resolution(playbook, u) or '未标'}」"
        for u in prior[-2:]
    ]
    lines.append("最近两个单元：" + "；".join(recent) + "（新一卷开头不要接着用同样的）")
    return "\n".join(lines)


def _issue(unit: int, problem: str, suggestion: str, severity: str) -> dict[str, Any]:
    return {"aspect": "repetition", "unit": unit, "problem": problem, "suggestion": suggestion, "severity": severity}


def repetition_issues(
    playbook: Playbook, prior: list[dict[str, Any]], units: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """卷纲的套路检查（程序算的，不靠模型）：全书上限、每卷上限、连续使用。

    prior：前面各卷的单元（按顺序）；units：这一卷的新卷纲。
    """
    issues: list[dict[str, Any]] = []
    used = _trope_counts(playbook, prior)
    used_resolutions = Counter(r for u in prior if (r := _resolution(playbook, u)))
    in_volume: Counter[str] = Counter()
    reported: set[tuple[str, str]] = set()
    for u in units:
        index = int(u.get("index") or 0)
        for name in _trope_counts(playbook, [u]):
            used[name] += 1
            cap = playbook.tropes[name].book if name in playbook.tropes else None
            if cap is not None and used[name] > cap and ("trope", name) not in reported:
                reported.add(("trope", name))
                issues.append(
                    _issue(
                        index,
                        f"套路「{name}」全书最多用 {cap} 次，算上这一卷已经用到 {used[name]} 次",
                        f"把第{index}单元的「{name}」换成别的套路",
                        "high",
                    )
                )
        resolution = _resolution(playbook, u)
        if not resolution:
            continue
        used_resolutions[resolution] += 1
        in_volume[resolution] += 1
        limit = playbook.resolutions.get(resolution)
        if limit is None:
            continue
        if (
            limit.book is not None
            and used_resolutions[resolution] > limit.book
            and ("book", resolution) not in reported
        ):
            reported.add(("book", resolution))
            issues.append(
                _issue(
                    index,
                    f"破局手法「{resolution}」全书最多用 {limit.book} 次，算上这一卷已经用到 {used_resolutions[resolution]} 次",
                    f"第{index}单元换一种破局方式",
                    "high",
                )
            )
        if limit.volume is not None and in_volume[resolution] > limit.volume and ("volume", resolution) not in reported:
            reported.add(("volume", resolution))
            issues.append(
                _issue(
                    index,
                    f"破局手法「{resolution}」每卷最多用 {limit.volume} 次，这一卷用了 {in_volume[resolution]} 次",
                    f"第{index}单元换一种破局方式",
                    "medium",
                )
            )

    # 连续使用：带上前一卷最后几个单元，新一卷的开头也不能接着用
    tail = prior[-3:]
    sequence = [*tail, *units]
    for i in range(len(tail), len(sequence)):
        u, index = sequence[i], int(sequence[i].get("index") or 0)
        core, before = _core(playbook, u), _core(playbook, sequence[i - 1]) if i else ""
        if core and core == before:
            issues.append(
                _issue(
                    index, f"第{index}单元和上一个单元的核心套路都是「{core}」", "连续两个单元换不同的套路", "medium"
                )
            )
        resolution = _resolution(playbook, u)
        limit = playbook.resolutions.get(resolution, Limit())
        streak = 1
        while i - streak >= 0 and _resolution(playbook, sequence[i - streak]) == resolution:
            streak += 1
        if resolution and streak == limit.streak + 1:
            issues.append(
                _issue(
                    index,
                    f"破局手法「{resolution}」连着用了 {streak} 个单元",
                    f"第{index}单元换一种破局方式",
                    "medium",
                )
            )
    return issues
