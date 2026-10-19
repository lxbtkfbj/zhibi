"""把 run_read.py、run_units.py 的结果整理成一份给作者看的 md。

用 `python -I make_report.py <结果文件夹> <输出 md>` 运行（结果文件夹里有 chapters.json、read/、units.json）。
钱按 DeepSeek V4-Flash 官方价算（2026-08-17 起峰谷定价，每百万 token：输入 高峰 3 元／空闲 1.5 元，输出 高峰 9 元／空闲 4.5 元）。
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PRICE = {"高峰": (3.0, 9.0), "空闲": (1.5, 4.5)}
FEEL_MARK = {"憋屈": "▁", "平": "▃", "爽": "▆", "大爽": "█"}


def main() -> None:
    folder, out = Path(sys.argv[1]), Path(sys.argv[2])
    source = json.loads((folder / "chapters.json").read_text(encoding="utf-8"))
    titles = {c["index"]: c["title"] for c in source["chapters"]}
    read = sorted((c for f in (folder / "read").glob("batch_*.json") for c in json.loads(f.read_text(encoding="utf-8"))["chapters"]), key=lambda c: c["index"])
    by_index = {c["index"]: c for c in read}
    summary = json.loads((folder / "read" / "read_summary.json").read_text(encoding="utf-8"))
    units = json.loads((folder / "units.json").read_text(encoding="utf-8"))
    vol_path = folder / "volumes.json"
    volumes = json.loads(vol_path.read_text(encoding="utf-8")) if vol_path.exists() else {"volumes": [], "open_from": None, "calls": []}
    roster = summary["roster"]

    def who(name: str, known: str = "") -> str:
        for key in (known, name):
            for p in roster:
                if key and (key == p["name"] or key in p["aliases"]):
                    return p["name"]
        return name

    calls = summary["calls"] + units["calls"] + volumes["calls"]
    ins = sum(c.get("usage", {}).get("input_tokens", 0) for c in calls)
    outs = sum(c.get("usage", {}).get("output_tokens", 0) for c in calls)
    fails = [c for c in summary["calls"] if c.get("error")]
    unit_seconds = sum(c["seconds"] for c in units["calls"] + volumes["calls"])
    money = {k: ins / 1e6 * a + outs / 1e6 * b for k, (a, b) in PRICE.items()}
    chars = sum(len(c["text"]) for c in source["chapters"])

    L: list[str] = []
    w = L.append
    w(f"# 《{source['book']}》前 {len(source['chapters'])} 章试拆")
    w("")
    w("> 这是在执笔外面用脚本跑的试验，执笔里还没有「拆一本书」。用的是你的「A 3.8f」（A 中转站的 deepseek-v4.1-flash），思考调低；没用你的官方 DeepSeek 配置。")
    w("> 章号和原书一样（原书第 52、53 章之间的「上架感言」不算正文，跳过了）。")
    w("")
    body_start = len(L)
    w("## 跑了多久、花了多少")
    w("")
    w(f"- 原文 {chars:,} 字，{len(source['chapters'])} 章，分 {summary['batches']} 批读，四批同时跑。")
    w(f"- 逐章记 {summary['seconds'] / 60:.1f} 分钟；归单元、归卷 {len(units['calls']) + len(volumes['calls'])} 次，{unit_seconds / 60:.1f} 分钟。")
    w(f"- 调用模型 {len(calls)} 次，失败 {len(fails) + sum(1 for c in units['calls'] + volumes['calls'] if c.get('error'))} 次" + (f"（{'；'.join(sorted({c['error'][:40] for c in fails}))}）" if fails else "") + f"；没读成跳过的章：{summary['skipped'] or '没有'}。")
    w(f"- 输入 {ins:,} token，输出 {outs:,} token。实际走的是 A 中转站，按中转的价算；拿 DeepSeek V4-Flash 官方价估个数：白天高峰时段约 {money['高峰']:.2f} 元，空闲时段约 {money['空闲']:.2f} 元。")
    per_char = (money["高峰"] / chars) if chars else 0
    w(f"- 照这个比例，整本 223 万字只拆大纲约 {per_char * 2229054:.0f} 元（高峰）、{summary['seconds'] / chars * 2229054 / 60:.0f} 分钟上下；以后拆设定、写「这本书好在哪」再多三成左右。")
    w("")
    w("## 读者感觉（模型判的，每章一格）")
    w("")
    w("▁ 憋屈　▃ 平　▆ 爽　█ 大爽")
    w("")
    for start in range(1, len(source["chapters"]) + 1, 20):
        row = "".join(FEEL_MARK.get(by_index[i]["feel"], "？") if i in by_index else "×" for i in range(start, min(start + 20, len(source["chapters"]) + 1)))
        w(f"`第 {start:>3}–{min(start + 19, len(source['chapters'])):>3} 章` {row}  ")
    feels = Counter(c["feel"] for c in read)
    w("")
    w("　".join(f"{k} {feels.get(k, 0)} 章" for k in FEEL_MARK))
    w("")

    stats = L[body_start:]
    del L[body_start:]

    def chapter_block(i: int) -> None:
        c = by_index.get(i)
        if not c:
            w(f"- **第 {i} 章 {titles[i]}**：没读成")
            return
        w(f"- **第 {i} 章 {titles[i]}**（{c['feel']}）")
        w(f"  - 发生什么：{c['goal']}　场景：{' → '.join(c['scenes'])}")
        w(f"  - 看点：{c['cool_point']}")
        w(f"  - 钩子：{c['hook']}")

    def unit_block(n: int, u: dict) -> None:
        w(f"### 单元 {n}　{u['title']}（第 {u['first']}–{u['last']} 章，{u['last'] - u['first'] + 1} 章）")
        w("")
        w(u["text"])
        w("")
        for i in range(u["first"], u["last"] + 1):
            chapter_block(i)
        w("")

    w("## 大纲：卷、单元和每章章纲")
    w("")
    w("卷那段话按「想做成什么；被什么挡着；卷末高潮；卷末变成什么」写，单元那段话按「什么事找上门；怎么应对；叫好的那一下；拿到什么」写。")
    w("")
    numbered = list(enumerate(units["units"], start=1))
    for k, v in enumerate(volumes["volumes"], start=1):
        w(f"## 第 {k} 卷　{v['title']}（第 {v['first']}–{v['last']} 章）")
        w("")
        w(f"> {v['text']}")
        w("")
        for n, u in numbered:
            if v["first"] <= u["first"] <= v["last"]:
                unit_block(n, u)
    rest_from = volumes["open_from"] or (volumes["volumes"][-1]["last"] + 1 if volumes["volumes"] else 1)
    rest_units = [(n, u) for n, u in numbered if u["first"] >= rest_from]
    if rest_units or units.get("open_from"):
        w(f"## 还没归卷（第 {rest_from} 章起，这一卷还没收在大高潮上，等后面的章读了再归）")
        w("")
        for n, u in rest_units:
            unit_block(n, u)
    if units.get("open_from"):
        w(f"### 还没归单元（第 {units['open_from']} 章起，故事还没收尾，等后面的章读了再归）")
        w("")
        for i in range(units["open_from"], len(source["chapters"]) + 1):
            chapter_block(i)
        w("")

    # 人物：按出场章数排
    appear: dict[str, list[int]] = {}
    shown: dict[str, list[tuple[int, str]]] = {}
    for c in read:
        for p in c["people"]:
            key = who(p["name"], p.get("was", ""))
            if c["index"] not in appear.setdefault(key, []):
                appear[key].append(c["index"])
            shown.setdefault(key, []).append((c["index"], p["shown"]))
    moments: dict[str, list[tuple[int, dict]]] = {}
    for c in read:
        for m in c["moments"]:
            moments.setdefault(who(m["who"]), []).append((c["index"], m))
    alias_count = Counter(a for p in roster for a in set(p["aliases"]))
    names = {p["name"] for p in roster}
    shared = {a for a, n in alias_count.items() if n > 1 or a in names}
    aliases = {p["name"]: [a for a in p["aliases"] if a not in shared] for p in roster}
    ranked = sorted(appear.items(), key=lambda kv: (-len(kv[1]), kv[1][0]))
    w("## 主要人物（出场章数最多的 15 个，程序按各章记录合的）")
    w("")
    for name, chs in ranked[:15]:
        also = f"，也叫 {'、'.join(aliases.get(name, []))}" if aliases.get(name) else ""
        w(f"### {name}（出场 {len(chs)} 章，第 {chs[0]} 章起{also}）")
        w("")
        w(f"- 第一次出场：{shown[name][0][1]}")
        if len(shown[name]) > 1:
            w(f"- 最近一次（第 {shown[name][-1][0]} 章）：{shown[name][-1][1]}")
        for i, m in moments.get(name, [])[:4]:
            w(f"- 名场面 第 {i} 章：{m['what']}——立住{m['shows']}")
        w("")
    rest = [f"{n}（{len(c)}）" for n, c in ranked[15:]]
    w(f"其余 {len(rest)} 人（括号里是出场章数）：{'、'.join(rest)}")
    w("")

    w("## 别称（模型认成同一个人的叫法，请帮忙看认得对不对）")
    w("")
    for p in roster:
        if aliases[p["name"]]:
            w(f"- {p['name']}：{'、'.join(aliases[p['name']])}")
    if shared:
        w(f"- 几个人共用、不算谁的别称：{'、'.join(sorted(shared))}")
    for c in read:
        for p in c["people"]:
            if p.get("was"):
                w(f"- 第 {c['index']} 章认出「{p['was']}」就是「{p['name']}」")
    w("")
    lone = [p for p in roster if len(appear.get(p["name"], [])) == 1]
    w(f"只出场一章的 {len(lone)} 人里，可能有和别人是同一个的：{'、'.join(p['name'] for p in lone[:60])}")
    w("")

    w("## 名场面（全部）")
    w("")
    for c in read:
        for m in c["moments"]:
            w(f"- 第 {c['index']} 章 {m['who']}：{m['what']}——立住{m['shows']}")
    w("")

    w("## 读者在等的事")
    w("")
    for c in read:
        for x in c["waits"]:
            w(f"- 第 {c['index']} 章 {x['action']}：{x['what']}")
    w("")

    w("## 金手指、秘密、规矩")
    w("")
    for c in read:
        for t in c["things"]:
            if t["kind"] in ("金手指", "秘密", "规矩", "等级"):
                w(f"- 第 {c['index']} 章 〔{t['kind']}{('·' + t['secret']) if t['secret'] else ''}〕{t['name']}：{t['note']}")
    w("")
    places = [f"{t['name']}（{c['index']}）" for c in read for t in c["things"] if t["kind"] in ("地方", "势力", "物品功法")]
    w(f"地方、势力、物品（括号里是第几章）：{'、'.join(places)}")
    w("")

    w("## 熟悉的桥段")
    w("")
    tropes = Counter(t for c in read for t in c["tropes"])
    w("、".join(f"{t}（{n}）" for t, n in tropes.most_common()))
    w("")
    L.extend(stats)
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"写好了：{out}，{len(L)} 行；高峰 {money['高峰']:.2f} 元，输入 {ins}，输出 {outs}")


if __name__ == "__main__":
    main()
