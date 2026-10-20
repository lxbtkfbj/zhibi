"""精髓试验：先逐单元拆剧情，再按节写知识点，最后合成核心要点。数字都由程序先数好。

    python analyze.py <目录名> [只跑这几节，逗号分开]
结果写在 data/拆书试验/精髓/<目录名>/essence.json，每节给模型的材料写在 materials/ 下面方便核对。
"""

import asyncio
import re
import sys
from collections import Counter, defaultdict
from typing import Literal

from common import OUT, Caller, db, load, render, save, template  # noqa: I001

from pydantic import BaseModel, Field

# ---------- 模型要交回的格式 ----------


class Point(BaseModel):
    title: str = Field(description="「招式名：一句话说清这一招」，30 字以内，不写人名事件")
    steps: list[str] = Field(description="怎么用，2-5 步，每步 25 字以内，能照着做的动作")
    evidence: str = Field(description="这本书里的证据：用了几次＋两三个例子，80 字以内")
    note: str = Field("", description="什么时候用、要注意什么，40 字以内，没有空着")
    chapters: list[int] = Field(description="证据章号，从小到大，3-8 个")


class Section(BaseModel):
    points: list[Point]
    missing: list[str] = Field(default_factory=list, description="想写却缺记录、看不出来的")


class Figure(BaseModel):
    name: str
    archetype: str = Field(description="人设模板，网文读者常说的叫法，2-8 个字")
    build: str = Field(description="作者用哪几招把这个人设立起来，80 字以内")
    role: str = Field(description="在剧情里起什么作用，60 字以内")
    arc: str = Field("", description="自己或者和主角的关系怎么变，没变写空")
    chapters: list[int]


class CastSection(BaseModel):
    figures: list[Figure]
    points: list[Point]
    missing: list[str] = Field(default_factory=list)


class CheckedSection(Section):
    fixes: list[str] = Field(default_factory=list, description="改了什么，一句一条；没改空着")


class CheckedCast(CastSection):
    fixes: list[str] = Field(default_factory=list, description="改了什么，一句一条；没改空着")


class Overview(BaseModel):
    genre: str = Field(description="一句话：这是一本什么书、读者追它主要图什么，40 字以内")
    engine: str = Field(description="一句话：这本书靠什么让人一直追下去，60 字以内")
    points: list[Point]


class ShuangTag(BaseModel):
    index: int
    tags: list[str] = Field(description="1-3 个爽点类别，最主要的在前")
    crowd: str = Field("", description="被谁的反应放大，没有空着")


class ShuangTags(BaseModel):
    chapters: list[ShuangTag]


class MergeGroup(BaseModel):
    names: list[str]
    keep: str
    why: str = Field(description="第几章怎么看出来是同一个人，40 字以内")


class Merges(BaseModel):
    groups: list[MergeGroup] = Field(default_factory=list)


class UnitPlot(BaseModel):
    n: int
    trigger_type: Literal["前事的后果", "早先埋下的事发作", "换了新地方新局面", "有人找上门", "主角自己要做", "意外撞上"]
    trigger: str = Field(description="具体是哪件事引出来的，40 字以内")
    shape: list[str] = Field(description="起承转合 4-6 步，每步 20 字以内")
    payoff: str = Field(description="「哪一种：哪一下」，40 字以内")
    new: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    stakes: Literal["更大", "差不多", "更小"]
    stakes_note: str = ""
    hook_out: str = ""
    seeds: str = ""


class UnitPlots(BaseModel):
    units: list[UnitPlot]


SECTIONS = {
    # 键：（标题，提示词，格式）
    "source": ("情节怎么想", "essence_source", Section),
    "skeleton": ("剧情骨架", "essence_skeleton", Section),
    "link": ("剧情衔接", "essence_link", Section),
    "fresh": ("保持新鲜", "essence_fresh", Section),
    "longline": ("长线布局", "essence_longline", Section),
    "setting": ("设定设计", "essence_setting", Section),
    "shuang": ("爽点类型", "essence_shuang", Section),
    "scene": ("爽点戏怎么写", "essence_scene", Section),
    "hero": ("主角", "essence_hero", Section),
    "cast": ("配角与对手", "essence_cast", CastSection),
    "rhythm": ("节奏与钩子", "essence_rhythm", Section),
    "opening": ("开篇", "essence_opening", Section),
}

# ---------- 读数据、数数 ----------


def ctype(text: str) -> str:
    head = re.split(r"[：:]", text or "", maxsplit=1)[0].strip()
    return head if 0 < len(head) <= 6 else "其他"


def spans(numbers) -> str:
    out, start, prev = [], None, None
    for n in sorted(set(numbers)):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}–{prev}" if prev > start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}–{prev}" if prev > start else str(start))
    return "、".join(out)


class Book:
    def __init__(self, slug: str):
        self.slug = slug
        self.folder = OUT / slug
        self.meta = load(self.folder / "meta.json")
        self.chapters = load(self.folder / "chapters.json")
        self.units = load(self.folder / "units.json")
        path = self.folder / "waits.json"
        self.waits = load(path)["items"] if path.exists() else []
        path = self.folder / "cards.json"
        self.cards = {c["name"]: c for c in load(path)} if path.exists() else {}
        path = self.folder / "texts.json"
        self.texts = {int(k): v for k, v in load(path).items()} if path.exists() else {}
        self.by_index = {c["index"]: c for c in self.chapters}
        self.last = max(self.by_index)
        self.plots: dict[int, dict] = {}
        self.tags: dict[int, dict] = {}
        self._people()

    # 人：was 和「合并同一个人」把旧名字并到留下的名字上，出场按章数
    def _people(self, merges=()):
        parent: dict[str, str] = {}

        def find(x):
            while parent.get(x, x) != x:
                x = parent[x]
            return x

        for group in merges:
            for name in group["names"]:
                a, b = find(name), find(group["keep"])
                if a != b:
                    parent[a] = b
        for c in self.chapters:
            for p in c.get("people", []):
                if p.get("was") and p["was"] != p["name"]:
                    a, b = find(p["was"]), find(p["name"])
                    if a != b:
                        parent[a] = b
        self.find = find
        appear, shown, change, moments = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
        for c in self.chapters:
            for p in c.get("people", []):
                name = find(p["name"])
                if c["index"] not in appear[name]:
                    appear[name].append(c["index"])
                if p.get("shown"):
                    shown[name].append((c["index"], p["shown"]))
                if p.get("change"):
                    change[name].append((c["index"], p["change"]))
            for m in c.get("moments", []):
                moments[find(m["who"])].append((c["index"], m["what"], m["shows"]))
        self.appear, self.shown, self.change, self.moments = appear, shown, change, moments
        self.hero = max(appear, key=lambda n: len(appear[n]))
        aliases = defaultdict(set)
        for name in list(parent):
            aliases[find(name)].add(name)
        self.aliases = aliases

    def unit_of(self, index):
        for u in self.units:
            if u["first"] <= index <= u["last"]:
                return u
        return None

    def first_seen(self):
        return {name: chs[0] for name, chs in self.appear.items()}

    def open_at(self, index):
        return [w for w in self.waits if w["planted"] <= index and (w["resolved"] is None or w["resolved"] > index)]

    # 共用的数字
    def feel_facts(self) -> list[str]:
        feel = Counter(c["feel"] for c in self.chapters)
        big = [c["index"] for c in self.chapters if c["feel"] == "大爽"]
        lines = [
            f"- 读者感觉（模型判的）：憋屈 {feel['憋屈']} 章，平 {feel['平']} 章，爽 {feel['爽']} 章，大爽 {feel['大爽']} 章。",
            f"- 大爽在第 {spans(big) or '（没有）'} 章。",
        ]
        best, run, start = (0, 0, 0), 0, 0
        for c in self.chapters:
            if c["feel"] == "憋屈":
                run, start = run + 1, start if run else c["index"]
                if run > best[0]:
                    best = (run, start, c["index"])
            else:
                run = 0
        lines.append(
            f"- 最长连着憋屈：第 {best[1]}–{best[2]} 章，{best[0]} 章。" if best[0] else "- 没有连着憋屈的章。"
        )
        good = [c["index"] for c in self.chapters if c["feel"] in ("爽", "大爽")]
        if len(good) > 1:
            gaps = [(b - a, a, b) for a, b in zip(good, good[1:], strict=False)]
            g = max(gaps)
            lines.append(
                f"- 两次过瘾（爽或大爽）之间平均隔 {sum(x[0] for x in gaps) / len(gaps):.1f} 章，"
                f"最长一次从第 {g[1]} 章到第 {g[2]} 章（隔 {g[0]} 章）。"
            )
        types = defaultdict(list)
        for c in self.chapters:
            if c["feel"] in ("爽", "大爽"):
                types[ctype(c["cool_point"])].append(c["index"])
        lines.append(
            "- 过瘾那几章的看点种类（看点冒号前的词）："
            + "；".join(f"{k} {len(v)} 章（第 {spans(v)} 章）" for k, v in sorted(types.items(), key=lambda x: -len(x[1])))
        )
        return lines

    def unit_facts(self) -> str:
        sizes = [u["last"] - u["first"] + 1 for u in self.units]
        if not sizes:
            return "- 还没有归好的单元。"
        return f"- 单元 {len(sizes)} 个，平均 {sum(sizes) / len(sizes):.1f} 章，最短 {min(sizes)} 章，最长 {max(sizes)} 章。"

    def wait_facts(self) -> list[str]:
        if not self.waits:
            return ["- 还没有读者在等的事的账。"]
        counts = [(len(self.open_at(c["index"])), c["index"]) for c in self.chapters]
        lo, hi = min(counts), max(counts)
        empty = [i for n, i in counts if n == 0]
        resolved = [w for w in self.waits if w["resolved"]]
        relay = sum(
            1 for w in resolved
            if any(o is not w and o["planted"] < w["resolved"] and (o["resolved"] is None or o["resolved"] > w["resolved"])
                   for o in self.waits)
        )
        return [
            f"- 读者在等的事一共 {len(self.waits)} 件，兑现 {len(resolved)} 件，还吊着 {len(self.waits) - len(resolved)} 件。",
            f"- 同一时间读者在等的事：最少 {lo[0]} 件（第 {lo[1]} 章），平均 {sum(n for n, _ in counts) / len(counts):.1f} 件，最多 {hi[0]} 件（第 {hi[1]} 章）。",
            f"- 一件都没吊着的章：{('第 ' + spans(empty) + ' 章') if empty else '没有'}。",
            f"- 兑现的 {len(resolved)} 件里，有 {relay} 件在兑现之前，已经有别的事立下、并且兑现之后还吊着（接力）。",
        ]

    def returns(self, gap=15):
        out = []
        for name, chs in self.appear.items():
            for a, b in zip(chs, chs[1:], strict=False):
                if b - a > gap:
                    out.append((name, a, b))
        return sorted(out, key=lambda x: x[2])

    def text_of(self, indices):
        missing = [i for i in indices if i not in self.texts]
        if missing:
            with db() as conn:
                rows = conn.execute(
                    "select c.index, c.content from chapters c join books b on b.id = c.book_id"
                    " where b.title = %s and c.index = any(%s)",
                    (self.meta["title"], missing),
                ).fetchall()
            self.texts.update({i: t for i, t in rows})
        return {i: self.texts.get(i, "") for i in indices}


# ---------- 每节的材料 ----------


def merge_material(book: Book) -> str:
    called = defaultdict(set)
    for c in book.chapters:
        for p in c.get("people", []):
            called[book.find(p["name"])].update(p.get("also_called") or [])
    lines = []
    for name, chs in sorted(book.appear.items(), key=lambda x: x[1][0]):
        shown = book.shown[name]
        notes = [f"第 {i} 章：{s[:60]}" for i, s in ([shown[0]] + ([shown[-1]] if len(shown) > 1 else []))] if shown else []
        others = (called[name] | book.aliases[name]) - {name}
        lines.append(
            f"【{name}】出场 {len(chs)} 章（第 {chs[0]}–{chs[-1]} 章）；别的叫法：{'、'.join(sorted(others)) or '没有'}；"
            + "；".join(notes)
        )
    return "\n".join(lines)


def tag_facts(book: Book) -> list[str]:
    good = [c for c in book.chapters if c["feel"] in ("爽", "大爽")]
    by_tag, primary, pairs, crowd = defaultdict(list), Counter(), Counter(), 0
    for c in good:
        tags = book.tags.get(c["index"], {}).get("tags") or [ctype(c["cool_point"])]
        primary[tags[0]] += 1
        for tag in dict.fromkeys(tags):
            by_tag[tag].append(c["index"])
        for a in range(len(tags)):
            for b in range(a + 1, len(tags)):
                pairs[tuple(sorted((tags[a], tags[b])))] += 1
        crowd += bool(book.tags.get(c["index"], {}).get("crowd"))
    lines = [
        f"- 过瘾的章一共 {len(good)} 章（爽 {sum(c['feel'] == '爽' for c in good)}、大爽 {sum(c['feel'] == '大爽' for c in good)}），每章标了 1–3 类。",
        f"- 有人在旁边看着、靠旁观者反应放大的：{crowd} 章。",
        "各类爽点（按出现章数）：",
    ]
    for tag, chs in sorted(by_tag.items(), key=lambda x: -len(x[1])):
        big = [i for i in chs if book.by_index[i]["feel"] == "大爽"]
        gap = f"，平均隔 {(chs[-1] - chs[0]) / (len(chs) - 1):.1f} 章来一次" if len(chs) > 1 else ""
        lines.append(f"- {tag}：{len(chs)} 章（其中排第一位的 {primary[tag]} 章），大爽 {len(big)} 章{gap}；第 {spans(chs)} 章")
    lines.append("经常一起出现的类：" + "；".join(f"{a}+{b} {n} 章" for (a, b), n in pairs.most_common(6)))
    return lines


def tag_examples(book: Book, limit=6) -> list[str]:
    by_tag = defaultdict(list)
    for c in book.chapters:
        if c["feel"] in ("爽", "大爽"):
            for tag in (book.tags.get(c["index"], {}).get("tags") or [ctype(c["cool_point"])])[:2]:
                by_tag[tag].append(c)
    out = []
    for tag, chs in sorted(by_tag.items(), key=lambda x: -len(x[1])):
        big = [c for c in chs if c["feel"] == "大爽"][:3]
        rest = [c for c in chs if c["feel"] != "大爽"]
        step = max(1, len(rest) // max(1, limit - len(big)))
        pick = sorted(big + rest[::step][: limit - len(big)], key=lambda c: c["index"])
        out.append(f"【{tag}】")
        for c in pick:
            crowd = book.tags.get(c["index"], {}).get("crowd")
            out.append(f"第 {c['index']} 章（{c['feel']}）{c['cool_point']}" + (f"｜旁观：{crowd}" if crowd else ""))
    return out


def unit_block(book: Book, u: dict) -> str:
    chs = [book.by_index[i] for i in range(u["first"], u["last"] + 1) if i in book.by_index]
    seen = book.first_seen()
    newcomers = [n for n, i in seen.items() if u["first"] <= i <= u["last"]]
    things = [f"{t['kind']}「{t['name']}」" for c in chs for t in c.get("things", [])]
    planted = [f"「{w['what']}」（第 {w['planted']} 章）" for w in book.waits if u["first"] <= w["planted"] <= u["last"]]
    done = [f"「{w['what']}」（第 {w['resolved']} 章）" for w in book.waits if w["resolved"] and u["first"] <= w["resolved"] <= u["last"]]
    lines = [f"【单元 {u['n']}】第 {u['first']}–{u['last']} 章「{u['title']}」", f"那段话：{u['text']}"]
    lines += [f"第 {c['index']} 章：{c['goal']}｜{c['cool_point']}｜{c['hook']}" for c in chs]
    lines.append(f"第一次出场：{'、'.join(newcomers) or '（没有）'}")
    lines.append(f"新冒出来的：{'、'.join(things[:20]) or '（没有）'}")
    lines.append(f"读者在等的事：立下 {'；'.join(planted) or '（没有）'}；兑现 {'；'.join(done) or '（没有）'}")
    return "\n".join(lines)


def plot_line(book: Book, u: dict) -> str:
    p = book.plots.get(u["n"], {})
    return (
        f"单元 {u['n']} 第 {u['first']}–{u['last']} 章「{u['title']}」：起因（{p.get('trigger_type', '')}）{p.get('trigger', '')}；"
        f"起承转合：{' → '.join(p.get('shape', []))}"
    )


def materials(book: Book, key: str) -> str:
    ch, units, plots = book.chapters, book.units, book.plots
    out: list[str] = []
    if key == "shuang":
        out += ["数字：", *tag_facts(book), "", "每一类挑几章的看点（大爽优先，其余隔开挑）：", *tag_examples(book)]
        out += ["", "各单元最过瘾的一下（逐单元拆的结果）："]
        out += [f"单元 {u['n']}（第 {u['first']}–{u['last']} 章「{u['title']}」）：{plots.get(u['n'], {}).get('payoff', '')}" for u in units]
    elif key == "rhythm":
        hooks = Counter(ctype(c["hook"]) for c in ch)
        bad = [f"第 {c['index']} 章：{c['goal']}｜{c['summary'][:80]}" for c in ch if c["feel"] == "憋屈"]
        out += ["数字：", book.unit_facts(), *book.feel_facts(),
                "- 章末钩子的种类：" + "，".join(f"{k} {v} 章" for k, v in hooks.most_common()), *book.wait_facts(), "",
                "逐章的感觉和结尾钩子："]
        out += [f"第 {c['index']} 章［{c['feel']}］{c['hook']}" for c in ch]
        out += ["", "憋屈的章：", *(bad or ["（没有）"]), "", "各单元："]
        for u in units:
            f = Counter(book.by_index[i]["feel"] for i in range(u["first"], u["last"] + 1) if i in book.by_index)
            out.append(f"单元 {u['n']} 第 {u['first']}–{u['last']} 章（{u['last'] - u['first'] + 1} 章）：大爽 {f['大爽']}、爽 {f['爽']}、平 {f['平']}、憋屈 {f['憋屈']}")
    elif key == "hero":
        h = book.hero
        out.append(f"主角：{h}（出场 {len(book.appear[h])} 章；别的名字：{'、'.join(sorted(book.aliases[h] - {h})) or '没有'}）")
        card = book.cards.get(h)
        if card:
            out.append("角色卡：" + "；".join(f"{k}：{card[k]}" for k in ("one_line", "personality", "background", "want", "goal", "abilities") if card.get(k)))
        out += ["", "主角每章写出来的样子（shown）和变化（change）："]
        changes = dict(book.change[h])
        for i, text in book.shown[h]:
            out.append(f"第 {i} 章：{text}" + (f"｜变化：{changes[i]}" if i in changes else ""))
        out += ["", "主角的名场面："] + [f"第 {i} 章：{w} —— {s}" for i, w, s in book.moments[h]]
    elif key == "cast":
        others = sorted((n for n in book.appear if n != book.hero), key=lambda n: -len(book.appear[n]))[:12]
        back = defaultdict(list)
        for name, a, b in book.returns():
            back[name].append(f"第 {b} 章（隔了 {b - a} 章）")
        for n in others:
            chs = book.appear[n]
            out.append(f"【{n}】出场 {len(chs)} 章（第 {chs[0]} 章到第 {chs[-1]} 章）" + (f"；隔了很久又回来：{'、'.join(back[n])}" if back[n] else ""))
            if card := book.cards.get(n):
                out.append(f"  卡片：{card.get('one_line') or ''}")
            shown = book.shown[n]
            pick = [shown[0]] + shown[1:][:: max(1, len(shown[1:]) // 4 or 1)][:4] if shown else []
            out += [f"  第 {i} 章写出来的：{t}" for i, t in pick]
            out += [f"  第 {i} 章变化：{t}" for i, t in book.change[n]]
            out += [f"  第 {i} 章名场面：{w} —— {s}" for i, w, s in book.moments[n]]
    elif key == "skeleton":
        out += ["各单元（按先后）："]
        for u in units:
            out += [f"单元 {u['n']} 第 {u['first']}–{u['last']} 章「{u['title']}」：{u['text']}", "  " + plot_line(book, u).split("：", 1)[1]]
        if book.units and book.units[-1]["last"] < book.last:
            out.append(f"（第 {book.units[-1]['last'] + 1}–{book.last} 章还没收尾，没归单元）")
        out += ["", f"主角（{book.hero}）的变化："] + [f"第 {i} 章：{t}" for i, t in book.change[book.hero]]
        long = sorted(book.waits, key=lambda w: -((w["resolved"] or book.last) - w["planted"]))[:8]
        out += ["", "读者在等的事里吊得最久的几件："] + [
            f"第 {w['planted']} 章立下「{w['what']}」→ " + (f"第 {w['resolved']} 章兑现" if w["resolved"] else "还吊着") for w in long
        ]
    elif key == "source":
        kinds = Counter(p["trigger_type"] for p in plots.values())
        out += ["数字：各单元的起因 —— " + "，".join(f"{k} {v} 个单元" for k, v in kinds.most_common()), "", "各单元（按先后）："]
        prev = None
        for u in units:
            p = plots.get(u["n"], {})
            out.append(f"单元 {u['n']} 第 {u['first']}–{u['last']} 章「{u['title']}」：起因（{p.get('trigger_type', '')}）{p.get('trigger', '')}")
            out.append(f"  那段话：{u['text']}")
            if prev:
                out.append(f"  上一单元留下的线：{prev.get('hook_out') or '（没有）'}")
            out.append(f"  新加进来的：{'、'.join(p.get('new', [])) or '（没有）'}")
            out.append(f"  这一单元埋下、后面才用上的：{p.get('seeds') or '（没有）'}")
            prev = p
    elif key == "link":
        out += ["数字：", *book.wait_facts(), "", "单元之间的交接（按先后）："]
        for a, b in zip(units, units[1:], strict=False):
            pa, pb = plots.get(a["n"], {}), plots.get(b["n"], {})
            end = book.by_index.get(a["last"], {})
            still = book.open_at(a["last"])
            out += [
                f"单元 {a['n']}「{a['title']}」→ 单元 {b['n']}「{b['title']}」（第 {a['last']} 章 → 第 {b['first']} 章）",
                f"  上一单元留下的线：{pa.get('hook_out') or '（没有）'}",
                f"  第 {a['last']} 章结尾钩子：{end.get('hook', '')}",
                f"  下一单元的起因：（{pb.get('trigger_type', '')}）{pb.get('trigger', '')}",
                f"  交界处读者还在等的事 {len(still)} 件：{'；'.join(w['what'] for w in still) or '（没有）'}",
            ]
    elif key == "fresh":
        stakes = Counter(p["stakes"] for p in plots.values())
        out += ["数字：赌注比上一单元 —— " + "，".join(f"{k} {v} 次" for k, v in stakes.most_common()), "", "各单元（按先后）："]
        seen = book.first_seen()
        for u in units:
            p = plots.get(u["n"], {})
            rng = range(u["first"], u["last"] + 1)
            types = Counter(ctype(book.by_index[i]["cool_point"]) for i in rng if i in book.by_index and book.by_index[i]["feel"] in ("爽", "大爽"))
            tropes = Counter(t for i in rng if i in book.by_index for t in book.by_index[i].get("tropes", []))
            newcomers = sum(1 for i in seen.values() if u["first"] <= i <= u["last"])
            things = Counter(t["kind"] for i in rng if i in book.by_index for t in book.by_index[i].get("things", []))
            out += [
                f"单元 {u['n']} 第 {u['first']}–{u['last']} 章「{u['title']}」",
                f"  最过瘾的：{p.get('payoff', '')}；过瘾的种类：{'、'.join(f'{k}×{v}' for k, v in types.most_common()) or '（没有）'}",
                f"  比上一单元换了：{'、'.join(p.get('changed', [])) or '（第一个单元）'}；赌注：{p.get('stakes', '')}（{p.get('stakes_note', '')}）",
                f"  新加进来：{'、'.join(p.get('new', [])) or '（没有）'}；新出场的人 {newcomers} 个；新冒出来的东西：{'、'.join(f'{k}{v}' for k, v in things.items()) or '（没有）'}",
                f"  桥段：{'、'.join(f'{k}×{v}' for k, v in tropes.most_common(6)) or '（没有）'}",
            ]
    elif key == "longline":
        out += ["读者在等的事（整本账，按立下先后）："]
        for w in sorted(book.waits, key=lambda w: w["planted"]):
            end = f"第 {w['resolved']} 章兑现（吊了 {w['resolved'] - w['planted']} 章）：{w['how']}" if w["resolved"] else f"还吊着（已经 {book.last - w['planted']} 章）"
            out.append(f"{w['code']}｜{w['kind']}｜第 {w['planted']} 章立下「{w['what']}」｜提起：{spans(w['hints']) or '没有'}｜{end}")
        out += ["", "秘密（逐章记录里的埋下、揭开）："]
        out += [f"第 {c['index']} 章 {t['secret']}「{t['name']}」：{t['note']}" for c in ch for t in c.get("things", []) if t.get("secret")] or ["（没有）"]
        out += ["", "隔了很久又出现的人（中间隔 15 章以上）："]
        for name, a, b in book.returns():
            text = next((t for i, t in book.shown[name] if i == b), "")
            out.append(f"{name}：第 {a} 章之后，第 {b} 章又出现（隔了 {b - a} 章）：{text}")
        if not book.returns():
            out.append("（没有）")
        out += ["", "各单元埋下、后面才用上的："] + [f"单元 {u['n']}（第 {u['first']}–{u['last']} 章）：{plots.get(u['n'], {}).get('seeds') or '（没有）'}" for u in units]
    elif key == "opening":
        for c in ch[:10]:
            out.append(f"第 {c['index']} 章「{c['title']}」［{c['feel']}］{c['goal']}｜场景：{' / '.join(c['scenes'])}｜看点：{c['cool_point']}｜钩子：{c['hook']}")
        if units:
            out.append(f"\n第一个单元：第 {units[0]['first']}–{units[0]['last']} 章「{units[0]['title']}」：{units[0]['text']}")
        firsts = {}
        for c in ch:
            for t in c.get("things", []):
                firsts.setdefault(t["kind"], (c["index"], t["name"]))
        out.append("各类东西第一次出现：" + "；".join(f"{k} 第 {i} 章「{n}」" for k, (i, n) in firsts.items()))
        good = next((c["index"] for c in ch if c["feel"] in ("爽", "大爽")), None)
        out.append(f"第一次过瘾：第 {good} 章。" if good else "前面还没有过瘾的章。")
        out.append(f"主角：{book.hero}，第 {book.appear[book.hero][0]} 章出场。")
    elif key == "setting":
        groups, first = defaultdict(list), {}
        for c in ch:
            for t in c.get("things", []):
                first.setdefault((t["kind"], t["name"]), c["index"])
                groups[t["kind"]].append(
                    f"第 {c['index']} 章「{t['name']}」{('（' + t['secret'] + '）') if t.get('secret') else ''}"
                    f"{('［属于' + t['belongs'] + '］') if t.get('belongs') else ''}：{t['note'][:70]}"
                )
        good = [c for c in ch if c["feel"] in ("爽", "大爽")]
        link = []
        for (kind, name), at in first.items():
            if kind not in ("金手指", "等级", "规矩", "物品功法") or len(name) < 2:
                continue
            hit = [c for c in good if name in c["cool_point"] or name in c["summary"]]
            if len(hit) >= 2:
                tags = Counter(t for c in hit for t in (book.tags.get(c["index"], {}).get("tags") or [])[:2])
                link.append((len(hit), f"{kind}「{name}」（第 {at} 章出现）：出现在 {len(hit)} 个过瘾的章里（第 {spans([c['index'] for c in hit])} 章），这些章的爽点：{'、'.join(f'{k}{v}' for k, v in tags.most_common(4))}"))
        out += ["设定和爽点的对应（程序按设定名字在过瘾章的看点和摘要里数的）："]
        out += [line for _, line in sorted(link, key=lambda x: -x[0])[:15]] or ["（没有数到）"]
        out += ["", f"主角（{book.hero}）开局的处境（前三章）："] + [f"第 {c['index']} 章：{c['summary'][:150]}" for c in ch[:3]]
        card = book.cards.get(book.hero)
        if card:
            out.append("主角卡上的身世：" + (card.get("background") or "（没有）"))
        out += ["", f"主角的变化（实力、地位、在哪）："] + [f"第 {i} 章：{t}" for i, t in book.change[book.hero]]
        out.append("")
        for kind in ("金手指", "等级", "规矩", "物品功法", "势力", "地方", "秘密"):
            if groups[kind]:
                out.append(f"【{kind}】一共 {len(groups[kind])} 条" + ("，下面列前 25 条" if len(groups[kind]) > 25 else ""))
                out += groups[kind][:25]
    return "\n".join(out)


def top_tags(book: Book, n=3):
    count = Counter(t for c in book.chapters if c["feel"] in ("爽", "大爽")
                    for t in dict.fromkeys(book.tags.get(c["index"], {}).get("tags") or []))
    return [t for t, _ in count.most_common(n)]


def scene_material(book: Book, tag: str) -> str:
    """这一类排在第一位的爽章里挑三章：大爽优先、名场面多的优先、彼此隔开。"""
    pool = [c for c in book.chapters if c["feel"] in ("爽", "大爽")
            and (book.tags.get(c["index"], {}).get("tags") or [""])[0] == tag]
    pool += [c for c in book.chapters if c["feel"] in ("爽", "大爽") and c not in pool
             and tag in (book.tags.get(c["index"], {}).get("tags") or [])]
    score = sorted(pool, key=lambda c: (-(c["feel"] == "大爽"), -len(c.get("moments", [])), c["index"]))
    picked = []
    for c in score:
        if all(abs(c["index"] - p) > 3 for p in picked):
            picked.append(c["index"])
        if len(picked) == 3:
            break
    texts = book.text_of(picked)
    out = []
    for i in sorted(picked):
        c = book.by_index[i]
        crowd = book.tags.get(i, {}).get("crowd")
        out += [
            f"===== 第 {i} 章「{c['title']}」（{c['feel']}）=====",
            f"看点：{c['cool_point']}" + (f"；旁观：{crowd}" if crowd else ""),
            "前面两章：" + "；".join(f"第 {j} 章 {book.by_index[j]['summary'][:90]}" for j in range(max(1, i - 2), i) if j in book.by_index),
            "【原文】\n" + texts[i],
            "",
        ]
    return "\n".join(out)


def section_text(sec: dict) -> str:
    lines = []
    for f in sec.get("figures", []):
        lines.append(f"【人物】{f['name']}（{f['archetype']}）｜怎么立：{f['build']}｜作用：{f['role']}｜变化：{f.get('arc') or '（空）'}｜章：{f['chapters']}")
    for i, p in enumerate(sec["points"], 1):
        lines.append(f"【第 {i} 条】{p['title']}")
        lines += [f"  steps {n}：{s}" for n, s in enumerate(p["steps"], 1)]
        lines.append(f"  evidence：{p['evidence']}")
        if p.get("note"):
            lines.append(f"  note：{p['note']}")
        lines.append(f"  chapters：{p['chapters']}")
    return "\n".join(lines)


def cited_records(book: Book, sec: dict, cap=40) -> str:
    import re as _re

    want = []
    for item in [*sec.get("figures", []), *sec["points"]]:
        want += item.get("chapters", [])
        text = " ".join([item.get("evidence", ""), *item.get("steps", []), item.get("build", ""), item.get("arc", "")])
        for m in _re.finditer(r"(\d+)(?:\s?[–\-]\s?(\d+))?\s?章", text):
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            want += list(range(a, min(b, a + 3) + 1))
    seen = [i for i in dict.fromkeys(want) if i in book.by_index][:cap]
    return "\n".join(f"第 {i} 章：{book.by_index[i]['summary']}｜看点：{book.by_index[i]['cool_point']}" for i in sorted(seen))


def check_points(book: Book):
    def check(parsed):
        points = parsed.points
        if not points:
            return "至少写一个知识点"
        for p in points:
            bad = [i for i in p.chapters if i not in book.by_index]
            if bad:
                return f"「{p.title}」里的章号 {bad} 不在已经拆过的章里（第 1–{book.last} 章）"
        return None

    return check


async def run(slug: str, only: set[str] | None) -> None:
    book = Book(slug)
    caller = Caller(book.folder)
    title, upto, total = book.meta["title"], book.last, book.meta["total"]
    system = render("essence_persona", title=title, upto=upto, total=total, rules=template("rules").strip())
    result_path = book.folder / "essence.json"
    result = load(result_path) if result_path.exists() else {"sections": {}}
    try:
        if "merges" not in result or (only and "merges" in only):
            parsed = await caller.call(
                Merges, render("essence_merge", title=title, people=merge_material(book)), "合并同一个人", system=system
            )
            result["merges"] = [g.model_dump() for g in parsed.groups]
            save(result_path, result)
        book._people(result["merges"])
        print("  合并：", "；".join(f"{'、'.join(g['names'])}→{g['keep']}（{g['why']}）" for g in result["merges"]) or "没有")
        if "tags" not in result or (only and "tags" in only):
            good = [c for c in book.chapters if c["feel"] in ("爽", "大爽")]
            tags = {}
            for start in range(0, len(good), 80):
                group = good[start : start + 80]
                want = {c["index"] for c in group}

                def check_tags(parsed, want=want):
                    got = {c.index for c in parsed.chapters}
                    return None if want <= got else f"漏了第 {sorted(want - got)} 章，每章都要写一条"

                lines = "\n".join(
                    f"第 {c['index']} 章（{c['feel']}）看点：{c['cool_point']}｜{c['summary'][:110]}" for c in group
                )
                parsed = await caller.call(
                    ShuangTags, render("essence_shuang_tags", title=title, chapters=lines),
                    f"爽点分类 {group[0]['index']}-{group[-1]['index']}", system=system, check=check_tags,
                )
                for item in parsed.chapters:
                    if item.index in want:
                        tags[item.index] = item.model_dump()
            result["tags"] = tags
            save(result_path, result)
        book.tags = {int(k): v for k, v in result["tags"].items()}
        if "plots" in result and not (only and "plots" in only):
            book.plots = {int(k): v for k, v in result["plots"].items()}
        else:
            for start in range(0, len(book.units), 8):
                group = book.units[start : start + 8]
                want = {u["n"] for u in group}

                def check(parsed, want=want):
                    got = {u.n for u in parsed.units}
                    return None if want <= got else f"漏了单元 {sorted(want - got)}，每个单元都要写一条"

                parsed = await caller.call(
                    UnitPlots,
                    render("essence_units", title=title, units="\n\n".join(unit_block(book, u) for u in group)),
                    f"逐单元拆剧情 {group[0]['n']}-{group[-1]['n']}",
                    system=system,
                    check=check,
                )
                for u in parsed.units:
                    if u.n in want:
                        book.plots[u.n] = u.model_dump()
            result["plots"] = book.plots
            save(result_path, result)

        async def section(key):
            name, prompt, schema = SECTIONS[key]
            (book.folder / "materials").mkdir(exist_ok=True)
            if key == "scene":
                parts = []

                async def one(tag):
                    text = scene_material(book, tag)
                    (book.folder / "materials" / f"scene-{tag}.txt").write_text(text, encoding="utf-8")
                    return await caller.call(schema, render(prompt, tag=tag, materials=text), f"{name}·{tag}", system=system, check=check_points(book))

                parts = await asyncio.gather(*(one(tag) for tag in top_tags(book)))
                result["sections"][key] = {"name": name, "points": [p.model_dump() for s in parts for p in s.points],
                                           "missing": [m for s in parts for m in s.missing]}
                save(result_path, result)
                return
            text = materials(book, key)
            (book.folder / "materials" / f"{key}.txt").write_text(text, encoding="utf-8")
            parsed = await caller.call(schema, render(prompt, materials=text), name, system=system, check=check_points(book))
            result["sections"][key] = {"name": name, **parsed.model_dump()}
            save(result_path, result)

        keys = [k for k in SECTIONS if not only or k in only]
        result["sections"] = {k: v for k, v in result["sections"].items() if k in SECTIONS}
        await asyncio.gather(*(section(k) for k in keys))
        if not only or "overview" in only:
            lines = []
            for key, sec in result["sections"].items():
                for p in sec["points"]:
                    lines.append(f"【{sec['name']}】{p['title']}｜怎么用：{'；'.join(p['steps'])}｜证据：{p['evidence'][:80]}（第 {spans(p['chapters'])} 章）")
            parsed = await caller.call(Overview, render("essence_overview", materials="\n".join(lines)), "核心要点", system=system, check=check_points(book))
            result["overview"] = parsed.model_dump()
            save(result_path, result)
    finally:
        await caller.close()
    print(f"完成 → {result_path}")


async def check_run(slug: str, keys: list[str]) -> None:
    """核对：拿各节写好的内容和它引到的章的记录比，改掉记录里找不到的事。结果放 result["checked"]，原稿不动，方便对比。"""
    book = Book(slug)
    caller = Caller(book.folder)
    title, upto, total = book.meta["title"], book.last, book.meta["total"]
    system = render("essence_persona", title=title, upto=upto, total=total, rules=template("rules").strip())
    result_path = book.folder / "essence.json"
    result = load(result_path)
    book._people(result.get("merges", []))
    result.setdefault("checked", {})
    try:
        async def one(key):
            sec = result["sections"][key]
            schema = CheckedCast if sec.get("figures") else CheckedSection
            user = render("essence_check", title=title, section_name=sec["name"], section=section_text(sec), records=cited_records(book, sec))
            parsed = await caller.call(schema, user, f"核对·{sec['name']}", system=system, check=check_points(book))
            result["checked"][key] = {"name": sec["name"], **parsed.model_dump()}
            save(result_path, result)
            print(f"  {sec['name']} 改了 {len(parsed.fixes)} 处：" + "；".join(parsed.fixes))

        await asyncio.gather(*(one(k) for k in keys))
    finally:
        await caller.close()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[2].startswith("check:"):
        asyncio.run(check_run(sys.argv[1], sys.argv[2][6:].split(",")))
    else:
        only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
        asyncio.run(run(sys.argv[1], only))
