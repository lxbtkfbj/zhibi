"""书房和书详情共用的拆书摘要，不暴露原文件或长列表。"""


def teardown_summary(book, preview: dict | None = None) -> dict | None:
    if book.source != "teardown":
        return None
    data = book.teardown or {}
    confirming = data.get("stage") == "confirming"
    split = data.get("split") or {}
    preview = preview or {}
    return {
        "stage": "confirming" if confirming else "imported",
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
    }
