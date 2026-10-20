"""给装修样张取数据：样张上的字全从这里来，不手打。

来源只有两处，都原样取，不改字：
1. 作者书库里拆到第 100 章的《逆天邪神》（只读调本机 8000 的接口）：卷、单元、章纲、各章记下的人和事；
2. 第二批验证时用前 50 章试整理设定的结果（data/拆书试验/逆天邪神前五十章/整理设定/）：角色卡、各类设定、「这本书好在哪」。
   这些第三批做完以后由拆书自己出，现在先用验证的结果。

在仓库根目录运行：python docs/界面原型/取样张数据.py
写出 docs/界面原型/装修样张-数据.js（window.DATA = {...}）。原书正文不取（只取模型写的章纲和记录）。
"""

import collections
import glob
import io
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOK = "ff4aff0b-d1f1-46c4-b120-f7da9ac1ec2a"
API = f"http://127.0.0.1:8000/api/books/{BOOK}"
TRIAL = ROOT / "data/拆书试验/逆天邪神前五十章"


def get(path: str):
    with urllib.request.urlopen(API + path, timeout=20) as r:
        return json.load(r)


def load(path: Path):
    return json.load(io.open(path, encoding="utf-8"))


def main() -> None:
    book = get("")
    tree = get("/outline-tree")
    chapters = get("/chapters?with_outline=true")
    volumes = [v for arc in tree["arcs"] for v in arc["volumes"]]
    units = []
    for v in volumes:
        for u in v["units"]:
            ch = u["chapters"]
            if ch:
                units.append({"volume": v["index"], "title": u["title"], "virtual": bool(u.get("virtual")), "first": ch[0]["index"], "last": ch[-1]["index"], "text": u.get("summary") or ""})
    outline = {c["index"]: {"title": c["title"], "words": c.get("word_count"), **{k: (c.get("outline") or {}).get(k) for k in ("goal", "scenes", "cool_point", "hook")}} for c in chapters}
    # 各章记下的人和事（第 1–101 章，拆到第 100 章、第 101 章是同一批读的）
    records = {}
    for i in range(1, 102):
        records[i] = (get(f"/chapters/{i}").get("teardown") or {}).get("read") or {}

    def people_count(a: int, b: int):
        cnt, first = collections.Counter(), {}
        for i in range(a, b + 1):
            for p in records.get(i, {}).get("people", []):
                n = p["name"].strip()
                cnt[n] += 1
                first.setdefault(n, i)
        return [[n, c, first[n]] for n, c in cnt.most_common()]

    def things(a: int, b: int):
        seen, out = set(), []
        for i in range(a, b + 1):
            for t in records.get(i, {}).get("things", []):
                key = (t["kind"], t["name"].strip())
                if key not in seen:
                    seen.add(key)
                    out.append([i, t["kind"], t["name"].strip(), t.get("note", ""), t.get("belongs", ""), t.get("secret", "")])
        return out

    def waits(a: int, b: int):
        return [[i, w["action"], w["what"]] for i in range(a, b + 1) for w in records.get(i, {}).get("waits", [])]

    hero_names = {"萧澈", "云澈"}
    changes = [[i, p["change"]] for i in range(1, 102) for p in records[i].get("people", []) if p["name"].strip() in hero_names and p.get("change")]

    # 试整理设定的结果
    cards = load(TRIAL / "整理设定/cards.json")
    world = load(TRIAL / "整理设定/world.json")
    world = world.get("world", world)
    merits = load(TRIAL / "整理设定/merits.json")
    merits = merits.get("merits", merits)
    trial_read = {}
    for f in sorted(glob.glob(str(TRIAL / "read/batch_*.json"))):
        for c in load(Path(f))["chapters"]:
            trial_read[c["index"]] = c
    appear = {}
    for card in cards:
        names = {card["name"], card["card"]["name"], *card["card"].get("aliases", [])}
        appear[card["card"]["name"]] = sorted(i for i, c in trial_read.items() if any(p["name"].strip() in names or p.get("was", "").strip() in names for p in c.get("people", [])))

    data = {
        "book": {"title": book["title"], "teardown": book.get("teardown"), "volumes": [{"index": v["index"], "title": v["title"], "chapters": v["chapter_count"]} for v in volumes]},
        "units": units,
        "outline": {i: outline[i] for i in list(range(1, 23)) + [101, 102] if i in outline},
        "records": {i: records[i] for i in (2, 4)},
        "unit1": {"people": people_count(1, 10), "things": things(1, 10), "waits": waits(1, 10)},
        "vol1": {"people": people_count(1, 101)[:10], "changes": changes},
        "trial": {"cards": [c["card"] | {"chapters": c["chapters"]} for c in cards], "world": world, "merits": merits, "appear": appear, "upto": max(trial_read)},
    }
    out = ROOT / "docs/界面原型/装修样张-数据.js"
    out.write_text("// 由 取样张数据.py 生成，不要手改\nwindow.DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"写好 {out}：{len(units)} 个单元，{len(changes)} 条主角变化，{len(cards)} 张试整理的角色卡")


if __name__ == "__main__":
    main()
