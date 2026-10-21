"""补章节的接缝计划：只读原书计算，确认时再算一次，不改拆书流水线。"""

import hashlib
from dataclasses import dataclass

from fastapi import HTTPException

from app.services import teardown_split


def digest(title, text):
    return hashlib.sha1((title + "|" + text).encode()).hexdigest()


@dataclass
class AppendPlan:
    selected: list
    destinations: dict
    volumes: list[dict]
    excluded: list[dict]
    issues: list[dict]
    issue_total: int
    reopen: list[dict]
    preview: dict


def plan(book, chapters, volumes, units, result, filename, size, *, include=(), encoding_auto=True, nodes=()):
    """所有章的位置和卷号均按补上后的书计算；原始 order 专供勾回。"""
    meta = book.teardown or {}
    original = bool(meta.get("original_volumes"))
    total = len(chapters)
    last = chapters[-1]
    last_volume = volumes[-1]
    matching = {((ch.teardown or {}).get("number"), ch.title.strip()) for ch in chapters}
    hashes = {digest(ch.title, ch.content) for ch in chapters}
    duplicate_orders, leading, identical = set(), [], 0
    at_start = True
    excluded = []
    for order, piece in enumerate(result["chapters"]):
        same_heading = piece.number is not None and (piece.number, piece.title.strip()) in matching
        if at_start and same_heading:
            reason = "章号章名一样"
            leading.append({"number": piece.number, "title": piece.title})
        else:
            at_start = False
            reason = "正文一样" if digest(piece.title, piece.text) in hashes else None
            identical += int(reason is not None)
        if reason:
            duplicate_orders.add(order)
            excluded.append({"title": piece.title, "chars": piece.chars, "reason": reason})
    if len(duplicate_orders) == len(result["chapters"]):
        raise HTTPException(422, "这个文件里的章书里都有了")
    selectable = {
        order
        for order, piece in enumerate(result["chapters"])
        if order not in duplicate_orders and set(piece.flags) & set(teardown_split.EXCLUDED_FLAGS)
    }
    included = set(include)
    if included - selectable:
        raise HTTPException(422, "勾回的章节不在排除列表里，请刷新确认页")
    selected = [
        piece
        for order, piece in enumerate(result["chapters"])
        if order not in duplicate_orders and (order in included or order not in selectable)
    ]
    if not selected:
        raise HTTPException(422, "没有要补的章节，请勾选后再补")
    for order in sorted(selectable - included):
        piece = result["chapters"][order]
        excluded.append(
            {
                "title": piece.title,
                "chars": piece.chars,
                "reason": next(flag for flag in teardown_split.EXCLUDED_FLAGS if flag in piece.flags),
            }
        )

    destinations = {None: last_volume.index}
    volume_plans = []
    if original:
        next_index = last_volume.index
        for source_index, title in enumerate(result["volumes"], 1):
            continued = source_index == 1 and title == last_volume.title
            if not continued:
                next_index += 1
                volume_plans.append({"index": next_index, "title": title, "chapters": 0, "continued": False})
            destinations[source_index] = last_volume.index if continued else next_index
    else:
        open_id = meta.get("open_volume_id")
        destination = next((v for v in volumes if str(v.id) == open_id), last_volume)
        destinations.update({index: destination.index for index in range(len(result["volumes"]) + 1)})
        destinations[None] = destination.index
    counts = {}
    for piece in selected:
        destination = destinations[piece.volume]
        counts[destination] = counts.get(destination, 0) + 1
    if original and counts.get(last_volume.index):
        volume_plans.insert(
            0,
            {
                "index": last_volume.index,
                "title": last_volume.title,
                "chapters": counts[last_volume.index],
                "continued": True,
            },
        )
    for volume in volume_plans:
        volume["chapters"] = counts.get(volume["index"], 0)

    # 编号比较用实际落卷的卷号，不能让 None 被误认为新卷。
    numbered = [
        teardown_split.Piece(piece.title, piece.raw, destinations[piece.volume], number=piece.number, flags=piece.flags)
        for piece in selected
    ]
    previous = next(
        (
            ch
            for ch in reversed(chapters)
            if (ch.teardown or {}).get("number") is not None
            and not {"番外", "像是混进来的别的书"}.intersection((ch.teardown or {}).get("flags", []))
        ),
        None,
    )
    junction = {"kind": None, "a": None, "b": None, "missing": 0}
    if previous is not None:
        volume_index = next((v.index for v in volumes if v.id == previous.volume_id), None)
        anchor = teardown_split.Piece(
            previous.title,
            (previous.teardown or {}).get("raw_title", ""),
            volume_index,
            number=previous.teardown["number"],
            flags=previous.teardown.get("flags", []),
        )
        issues, issue_total = teardown_split.number_issues([anchor, *numbered])
        for issue in issues:
            issue["index"] += total - 1
            if "end_index" in issue:
                issue["end_index"] += total - 1
        first_numbered = next(
            (
                piece
                for piece in numbered
                if piece.number is not None and not {"番外", "像是混进来的别的书"}.intersection(piece.flags)
            ),
            None,
        )
        if first_numbered is not None:
            a, b = anchor.number, first_numbered.number
            reset = first_numbered.volume != anchor.volume and b == 1
            kind = None if b == a + 1 or reset else "跳了" if b > a + 1 else "倒回去了"
            junction = {"kind": kind, "a": a, "b": b, "missing": max(0, b - a - 1)}
    else:
        issues, issue_total = teardown_split.number_issues(numbered)
        for issue in issues:
            issue["index"] += total
            if "end_index" in issue:
                issue["end_index"] += total

    reopen = []
    tail_unit = None
    unit = next((u for u in units if u.id == last.unit_id), None) if last.unit_id else None
    if unit is not None:
        grouped = [ch.index for ch in chapters if ch.unit_id == unit.id]
        tail_unit = {"id": str(unit.id), "title": unit.title, "first": min(grouped), "last": max(grouped)}
        if not original or counts.get(last_volume.index):
            reopen.append({"kind": "unit", **tail_unit})
    if original and last_volume.summary:
        reopen.append({"kind": "summary", "id": str(last_volume.id), "title": last_volume.title})
    if not original and not meta.get("open_volume_id"):
        reopen.append({"kind": "volume", "id": str(last_volume.id), "title": last_volume.title})
    if meta.get("ending") or any(node.kind == "ending" for node in nodes):
        reopen.append({"kind": "ending"})

    preview = teardown_split.make_preview(result, filename, size, encoding_auto=encoding_auto)
    ignored_headings = [
        {"index": index, "title": piece.title, "line": line}
        for index, piece in enumerate(selected, total + 1)
        for line in piece.ignored_headings
    ]
    preview.update(
        mode="append",
        title=book.title,
        author=meta.get("author", ""),
        intro=meta.get("intro", ""),
        previous={"chapters": total, "last": {"index": last.index, "title": last.title}, "original_volumes": original},
        chapter_count=len(selected),
        chars=sum(piece.chars for piece in selected),
        first={
            "index": total + 1,
            "title": selected[0].title,
            "order": next(order for order, piece in enumerate(result["chapters"]) if piece is selected[0]),
        },
        last={
            "index": total + len(selected),
            "title": selected[-1].title,
            "order": next(order for order, piece in enumerate(result["chapters"]) if piece is selected[-1]),
        },
        opening=selected[0].text[:300],
        volumes=volume_plans,
        number_issues=issues,
        number_issue_total=issue_total,
        ignored_headings=ignored_headings[:20],
        ignored_heading_total=len(ignored_headings),
        excluded=[
            {
                "order": order,
                "title": piece.title,
                "chars": piece.chars,
                "reason": next(flag for flag in teardown_split.EXCLUDED_FLAGS if flag in piece.flags),
                "head": piece.text[:60],
                "volume": destinations[piece.volume],
            }
            for order, piece in enumerate(result["chapters"])
            if order in selectable
        ],
        junction=junction,
        duplicates={"leading": leading, "content": identical},
        reopen=reopen,
        ignored_volumes=0 if original else len(result["volumes"]),
        selection=[
            {
                "order": order,
                "title": piece.title,
                "raw_title": piece.raw,
                "number": piece.number,
                "volume": destinations[piece.volume],
                "excluded": order in selectable,
                "flags": piece.flags,
            }
            for order, piece in enumerate(result["chapters"])
            if order not in duplicate_orders
        ],
        reopen_context={
            "tail_unit": tail_unit,
            "last_volume": {
                "id": str(last_volume.id),
                "index": last_volume.index,
                "title": last_volume.title,
                "summary": bool(last_volume.summary),
            },
            "open_volume_id": meta.get("open_volume_id"),
            "original_volumes": original,
        },
        last_numbered={"number": previous.teardown["number"], "volume": volume_index} if previous is not None else None,
    )
    return AppendPlan(selected, destinations, volume_plans, excluded, issues, issue_total, reopen, preview)
