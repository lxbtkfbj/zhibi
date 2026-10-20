"""把作者库里已经拆过的书（只读）导成试验用的几个 json：meta / chapters / units / cards。

    python export_book.py <书名> <目录名> [读者在等的事 json]
"""

import sys
from pathlib import Path

from common import OUT, db, load, save


def main() -> None:
    title, slug = sys.argv[1], sys.argv[2]
    folder = OUT / slug
    with db() as conn:
        book_id, author, meta = conn.execute(
            "select b.id, coalesce(b.teardown->>'author', s.preview->>'author', ''), b.teardown from books b left join teardown_sources s on s.book_id = b.id where b.title = %s and b.source = 'teardown'",
            (title,),
        ).fetchone()
        rows = conn.execute(
            "select c.index, c.title, c.outline, c.summary, c.teardown, u.index, v.index from chapters c"
            " left join plot_units u on u.id = c.unit_id left join volumes v on v.id = c.volume_id"
            " where c.book_id = %s order by c.index",
            (book_id,),
        ).fetchall()
        units = conn.execute(
            "select u.index, u.title, coalesce(u.summary, ''), v.index from plot_units u join volumes v on v.id = u.volume_id"
            " where u.book_id = %s order by v.index, u.index",
            (book_id,),
        ).fetchall()
        cards = conn.execute(
            "select name, aliases, role_type, one_line, appearance, personality, background, abilities, goal, want,"
            " relation, tags, first_appearance_chapter, extra from characters where book_id = %s",
            (book_id,),
        ).fetchall()
        intro = conn.execute("select preview->>'intro' from teardown_sources where book_id = %s", (book_id,)).fetchone()
    chapters, ranges = [], {}
    for index, ch_title, outline, summary, teardown, unit_n, volume_n in rows:
        read = (teardown or {}).get("read")
        if not read:
            continue
        outline = outline or {}
        key = (volume_n, unit_n) if unit_n is not None else None
        if key:
            a, b = ranges.get(key, (index, index))
            ranges[key] = (min(a, index), max(b, index))
        chapters.append({
            "index": index, "title": ch_title, "goal": outline.get("goal", ""), "scenes": outline.get("scenes", []),
            "cool_point": outline.get("cool_point", ""), "hook": outline.get("hook", ""), "summary": summary or "",
            **read, "unit": key,
        })
    unit_list = []
    for n, (unit_n, u_title, u_text, volume_n) in enumerate(units, 1):
        if (volume_n, unit_n) in ranges:
            a, b = ranges[(volume_n, unit_n)]
            unit_list.append({"n": n, "first": a, "last": b, "title": u_title, "text": u_text})
    by_key = {(c["unit"]): None for c in chapters}
    order = {(v, u): i for i, (u, _t, _x, v) in enumerate(units, 1)}
    for c in chapters:
        c["unit"] = order.get(c["unit"]) if c["unit"] else None
    del by_key
    save(folder / "meta.json", {
        "title": title, "author": author, "total": len(rows), "upto": max(c["index"] for c in chapters),
        "intro": (intro or [""])[0] or "", "protagonist": "",
    })
    save(folder / "chapters.json", chapters)
    save(folder / "units.json", unit_list)
    save(folder / "cards.json", [
        dict(zip(["name", "aliases", "role_type", "one_line", "appearance", "personality", "background", "abilities",
                  "goal", "want", "relation", "tags", "first", "extra"], row, strict=True))
        for row in cards
    ])
    if len(sys.argv) > 3:
        save(folder / "waits.json", load(Path(sys.argv[3])))
    print(f"{title}：{len(chapters)} 章有记录，{len(unit_list)} 个单元，{len(cards)} 张角色卡 → {folder}")


if __name__ == "__main__":
    main()
