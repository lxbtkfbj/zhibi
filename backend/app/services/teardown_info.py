"""书房和书详情共用的拆书摘要，不暴露原文件或长列表。"""

from app.schemas import TeardownSummary


def needs_closing(meta, last, total) -> bool:
    if not last:
        return False
    if ((meta.get("settings") or {}).get("upto") or 0) < last:
        return True
    if ((meta.get("waits") or {}).get("upto") or 0) < last:
        return True
    if last == total and meta.get("stage") != "done":
        return True
    if meta.get("stage") == "done" and (meta.get("ending") or {}).get("upto") != total:
        return True
    if (meta.get("arcs") or {}).get("failed"):
        return True
    essence = meta.get("essence") or {}
    return not essence or (essence.get("upto") or 0) < last or bool(essence.get("failed"))


def essence_counts(essence):
    sections = [
        section
        for section in (essence.get("sections") or {}).values()
        if section.get("points") or section.get("figures")
    ]
    return len(sections), sum(
        len(section.get("points") or []) + len(section.get("figures") or []) for section in sections
    )


def teardown_summary(book, preview: dict | None = None, *, read: int = 0, last_read: int = 0) -> TeardownSummary | None:
    if book.source != "teardown":
        return None
    data = book.teardown or {}
    confirming = data.get("stage") == "confirming"
    split = data.get("split") or {}
    preview = preview or {}
    settings = data.get("settings") or {}
    essence = data.get("essence") or {}
    ending = data.get("ending") or {}
    waits = data.get("waits") or {}
    return TeardownSummary.model_validate(
        {
            "stage": data.get("stage", "imported"),
            "author": data.get("author", ""),
            "intro": data.get("intro", ""),
            "chars": preview.get("chars", 0) if confirming else split.get("chars", 0),
            "chapters": preview.get("chapter_count", 0) if confirming else split.get("chapters", 0),
            "read": read,
            "last_read": last_read,
            "needs_closing": needs_closing(data, last_read, split.get("chapters", 0)),
            "arcs": len((data.get("arcs") or {}).get("rows") or []),
            "ending": {"upto": ending.get("upto"), "ended": ending.get("ended", False)} if ending else None,
            "waits": {"upto": waits.get("upto"), "total": waits.get("total", 0), "open": waits.get("open", 0)}
            if waits
            else None,
            "volumes": len(preview.get("volumes", [])) if confirming else split.get("volumes", 0),
            "number_issue_total": preview.get("number_issue_total", 0)
            if confirming
            else split.get("number_issue_total", 0),
            "excluded_count": len(preview.get("excluded", [])) if confirming else len(data.get("excluded", [])),
            "open_volume_id": data.get("open_volume_id"),
            "imported_at": data.get("imported_at"),
            "original_volumes": data.get("original_volumes", False),
            "upto": data.get("upto"),
            "stop_reason": data.get("stop_reason"),
            "stop_note": data.get("stop_note"),
            "names": data.get("names") or {},
            "settings": {"upto": settings.get("upto")} if settings else None,
            "essence": {"upto": essence.get("upto"), "points": essence_counts(essence)[1]} if essence else None,
            "added": data.get("added") or [],
            "adding": {"file": preview["file"]["name"], "chapters": preview.get("chapter_count", 0)}
            if not confirming and preview.get("mode") == "append"
            else None,
        }
    )
