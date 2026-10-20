"""书房和书详情共用的拆书摘要，不暴露原文件或长列表。"""


def teardown_summary(book, preview: dict | None = None) -> dict | None:
    if book.source != "teardown":
        return None
    data = book.teardown or {}
    confirming = data.get("stage") == "confirming"
    split = data.get("split") or {}
    preview = preview or {}
    settings = data.get("settings") or {}
    merits = data.get("merits") or {}
    return {
        "stage": data.get("stage", "imported"),
        "author": data.get("author", ""),
        "intro": data.get("intro", ""),
        "chars": preview.get("chars", 0) if confirming else split.get("chars", 0),
        "chapters": preview.get("chapter_count", 0) if confirming else split.get("chapters", 0),
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
        "merits": {
            "upto": merits.get("upto"),
            "points": merits.get("points") or [],
            "missing": merits.get("missing") or [],
        }
        if merits
        else None,
    }
