"""照拆书的做法（一批最多 4 章、1.2 万字，第一批单独读，以后 4 批同时读，名单照已读的算）
用改过的通用版逐章记读一本书的前 N 章，再归单元、连读者在等的事。原文从作者库的待确认文件里取（只读）。

    python read_book.py <书名> <目录名> <读到第几章>
"""

import asyncio
import sys

from common import OUT, Caller, db, render, save  # noqa: I001  先导 common，它把 backend 加进 sys.path

from app.agents import schemas as s
from app.services.teardown_settings import people_of
from app.services.teardown_split import selected_chapters, split

MAX_CHARS, PER_BATCH = 12000, 4


def batches_of(chapters):
    out, cur, chars = [], [], 0
    for c in chapters:
        if cur and (len(cur) >= PER_BATCH or chars + len(c["text"]) > MAX_CHARS):
            out.append(cur)
            cur, chars = [], 0
        cur.append(c)
        chars += len(c["text"])
    if cur:
        out.append(cur)
    return out


async def read_all(caller, title, chapters, records):
    async def one(batch):
        reads = [{"index": i, **{k: r[k] for k in ("people",)}} for i, r in sorted(records.items())]
        roster, _, _ = people_of(reads)
        text = "\n".join(c["text"] for c in batch)
        user = render(
            "teardown_read", title=title, first=batch[0]["index"], last=batch[-1]["index"],
            roster=roster.text(text),
            chapters="\n\n".join(f"「第 {c['index']} 章{' ' + c['title'] if c['title'] else ''}」\n{c['text']}" for c in batch),
        )
        want = {c["index"] for c in batch}

        def check(parsed):
            got = {c.index for c in parsed.chapters}
            return None if want <= got else f"漏了第 {sorted(want - got)} 章，每章都要写一条"

        parsed = await caller.call(s.TeardownRead, user, f"读 {batch[0]['index']}-{batch[-1]['index']}", check=check)
        for item in parsed.chapters:
            if item.index in want:
                records[item.index] = item.model_dump()

    batches = batches_of(chapters)
    await one(batches[0])
    pending = list(batches[1:])
    running = set()
    while pending or running:
        while pending and len(running) < 4:
            running.add(asyncio.create_task(one(pending.pop(0))))
        done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()


async def group_units(caller, title, chapters, records, total):
    units, start = [], chapters[0]["index"]
    last = chapters[-1]["index"]
    while start <= last:
        ready = [c for c in chapters if c["index"] >= start][:60]
        lines = [
            f"第 {c['index']} 章：{records[c['index']]['summary']}｜{records[c['index']]['cool_point']}｜{records[c['index']]['hook']}"
            for c in ready
        ]
        done = "\n".join(f"第 {u['first']}–{u['last']} 章「{u['title']}」：{u['text']}" for u in units[-5:]) or "（还没有）"
        b = ready[-1]["index"]
        tail = "这是全书最后几章：全部归完，不留 open_from。" if b == total else "后面还有没读到的章：最后一件事要是还没了结，就留着不归。"

        def check(parsed, a=start, b=b):
            expect = a
            for g in parsed.units:
                if g.first != expect or g.last < g.first or g.last > b:
                    return f"单元要从第 {expect} 章接着划，一个挨一个，不重叠不跳章"
                expect = g.last + 1
            end = parsed.open_from if parsed.open_from else b + 1
            return None if expect == end else "单元划完要正好接到 open_from（或者最后一章）"

        parsed = await caller.call(
            s.TeardownUnits,
            render("teardown_units", title=title, first=start, done_units=done, chapters="\n".join(lines), tail_rule=tail),
            f"归单元 {start}-{b}", check=check,
        )
        for g in parsed.units:
            units.append({"n": len(units) + 1, "first": g.first, "last": g.last, "title": g.title, "text": g.text})
        if parsed.open_from or not parsed.units:
            break
        start = units[-1]["last"] + 1
    return units


async def ledger(caller, title, chapters, records):
    lines = []
    for c in chapters:
        lines.append(f"第 {c['index']} 章：{records[c['index']]['summary']}")
        for w in records[c["index"]]["waits"]:
            lines.append(f"  {w['action']}：{w['what']}")
    parsed = await caller.call(
        s.TeardownWaitLedger,
        render("teardown_waits", title=title, first=chapters[0]["index"], last=chapters[-1]["index"], open="（还没有）",
               chapters="\n".join(lines)),
        "读者在等的事",
    )
    items, by_ref = [], {}
    for n, item in enumerate(parsed.new, 1):
        row = {"code": f"{'E' if item.kind == '期待' else 'F'}{n}", "kind": item.kind, "what": item.what,
               "planted": item.chapter, "hints": [], "resolved": None, "how": ""}
        items.append(row)
        by_ref[item.ref.upper()] = row
    for h in parsed.hinted:
        if row := by_ref.get(h.code.upper()):
            row["hints"] = sorted({*row["hints"], h.chapter})
    for d in parsed.resolved:
        if row := by_ref.get(d.code.upper()):
            row["resolved"], row["how"] = d.chapter, d.how
    return {"upto": chapters[-1]["index"], "last": chapters[-1]["index"], "items": items}


async def main() -> None:
    title, slug, upto = sys.argv[1], sys.argv[2], int(sys.argv[3])
    folder = OUT / slug
    with db() as conn:
        data, encoding, preview = conn.execute(
            "select s.data, s.encoding, s.preview from teardown_sources s join books b on b.id = s.book_id where b.title = %s",
            (title,),
        ).fetchone()
    result = split(bytes(data), encoding=encoding)
    pieces = selected_chapters(result)
    total = len(pieces)
    chapters = [{"index": i, "title": p.title, "text": p.text} for i, p in enumerate(pieces[:upto], 1)]
    print(f"{title}：分出 {total} 章，读前 {len(chapters)} 章，{sum(len(c['text']) for c in chapters)} 字")
    caller = Caller(folder)
    records: dict[int, dict] = {}
    try:
        await read_all(caller, title, chapters, records)
        units = await group_units(caller, title, chapters, records, total)
        waits = await ledger(caller, title, chapters, records)
    finally:
        await caller.close()
    unit_of = {i: u["n"] for u in units for i in range(u["first"], u["last"] + 1)}
    save(folder / "chapters.json", [
        {"index": c["index"], "title": c["title"], **{k: v for k, v in records[c["index"]].items() if k != "index"},
         "unit": unit_of.get(c["index"])}
        for c in chapters
    ])
    save(folder / "units.json", units)
    save(folder / "waits.json", waits)
    save(folder / "meta.json", {
        "title": title, "author": (preview or {}).get("author", ""), "total": total, "upto": len(chapters),
        "intro": (preview or {}).get("intro", ""), "protagonist": "",
    })
    save(folder / "texts.json", {c["index"]: c["text"] for c in chapters})
    print(f"读完：{len(records)} 章，{len(units)} 个单元，{len(waits['items'])} 件读者在等的事 → {folder}")


if __name__ == "__main__":
    asyncio.run(main())
