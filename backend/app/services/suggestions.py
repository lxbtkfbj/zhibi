"""新书页「待处理」（第四步第二批）：编辑部「我建议这样改，你同不同意」的一条条。

- 同意：照建议改，改前改后记在这一条的 payload.result 上（和聊天里改完一样：前后对照、「换回原来的」）。
- 换回原来的：这一处后来没被动过才能换（作者手改、写章、聊天里又改、回到过存档都算动过）。
- 让编辑部改：只说了毛病的、群聊里说了当时没改的，当成作者在聊天里说的一句话发出去，编辑部自己查、自己改。
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Book, SettingSuggestion
from app.services import book_saves

# 建议这一行自己改了状态不算改书：换回原来的不把它变回「待处理」
SELF = "setting_suggestions"


def result_label(suggestion: SettingSuggestion, diff: list[dict]) -> str:
    return (diff[0].get("label") if diff else "") or suggestion.title[:40]


async def applied(session, suggestion: SettingSuggestion, apply) -> None:
    """照建议改，并把这一处改之前、改之后记在建议上。apply 是真正去改的那一步（不提交）。"""
    book_id = suggestion.book_id
    await session.flush()
    before = await book_saves.read_state(session, book_id)
    await apply()
    await session.flush()
    after = await book_saves.read_state(session, book_id)
    rows = [row for row in book_saves.row_changes(before, after) if row["table"] != SELF]
    if not rows:
        return
    await book_saves.keep_change(session, book_id, before, after, rows)
    diff = book_saves.readable_diff(before, after, rows)
    suggestion.payload = {
        **(suggestion.payload or {}),
        "result": {"change": rows, "diff": diff, "target_label": result_label(suggestion, diff)},
    }


async def revert(session, redis, suggestion_id) -> SettingSuggestion:
    """同意以后的「换回原来的」：只换这一处，换完存一档「你换回了：……」。"""
    from app.services.group_notes import take_back
    from app.services.meeting import publish

    suggestion = await session.get(SettingSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(404, "记录不存在")
    result = dict((suggestion.payload or {}).get("result") or {})
    book_id = suggestion.book_id
    await take_back(session, book_id, result)
    suggestion = await session.get(SettingSuggestion, suggestion_id)
    suggestion.payload = {**(suggestion.payload or {}), "result": {**result, "undone": True}}
    await session.commit()
    await book_saves.safe_checkpoint(session, book_id, "author", f"你换回了：{result.get('target_label') or '这一处'}")
    for event in ("library", "saves"):
        await publish(redis, book_id, event, {"id": str(book_id)})
    return await session.get(SettingSuggestion, suggestion_id)


async def changes(session, book_id) -> dict[str, bool]:
    """同意过的那几条现在还能不能「换回原来的」：{建议的 id: 能不能}"""
    rows = list(
        await session.scalars(
            select(SettingSuggestion)
            .where(SettingSuggestion.book_id == book_id, SettingSuggestion.status == "accepted")
            .order_by(SettingSuggestion.resolved_at.desc())
            .limit(100)
        )
    )
    wanted = [(str(s.id), s.payload["result"]) for s in rows if ((s.payload or {}).get("result") or {}).get("change")]
    if not wanted:
        return {}
    now = await book_saves.read_state(session, book_id)
    return {
        key: not r.get("undone") and all(now.rows.get(c["table"], {}).get(c["id"]) == c["after"] for c in r["change"])
        for key, r in wanted
    }


def chat_text(suggestion: SettingSuggestion) -> str:
    """让编辑部改：群聊里说过的照原话再说一遍；只说了毛病的，当成「照这条意见改」"""
    payload = suggestion.payload or {}
    if suggestion.kind == "chat":
        return str(payload.get("content") or suggestion.title)
    why = str(payload.get("why") or payload.get("content") or "")
    title = suggestion.title.replace("（已锁）", "")
    return f"照这条意见改：{title}" + (f"（{why}）" if why and why not in title else "")


def can_hand_over(suggestion: SettingSuggestion) -> bool:
    return suggestion.kind == "chat" or (suggestion.payload or {}).get("op") == "note"


async def hand_over(session, redis, suggestion_id, conv, background_tasks):
    """让编辑部改：发一句话到聊天里（作者正在看的那一段），这一条记成交给编辑部了。编辑部在写书时不行。"""
    from app.api.deps import ensure_idle
    from app.schemas import NoteIn
    from app.services.group_notes import receive_note

    suggestion = await session.get(SettingSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(404, "记录不存在")
    if suggestion.status != "pending":
        raise HTTPException(409, "这条建议已经处理过")
    if not can_hand_over(suggestion):
        raise HTTPException(422, "这一条有具体改法，点「同意」就行")
    try:
        await ensure_idle(session, suggestion.book_id)
    except HTTPException as exc:
        raise HTTPException(409, "编辑部正在干活，等这一轮做完再让它改") from exc
    book = await session.get(Book, suggestion.book_id)
    text = chat_text(suggestion)[:5000]
    await session.commit()
    note = await receive_note(NoteIn(content=text, conv=conv), background_tasks, book, session, redis)
    suggestion = await session.get(SettingSuggestion, suggestion_id)
    suggestion.status, suggestion.resolved_at = "accepted", datetime.now(UTC)
    suggestion.payload = {**(suggestion.payload or {}), "result": {"to_chat": note.id}}
    await session.commit()
    return note
