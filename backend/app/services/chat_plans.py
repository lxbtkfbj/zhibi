"""会话里的方案卡：先看方案，再显式逐条落实，所有结果可追溯。"""

import re
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.schemas import ChatPlan
from app.api.deps import ensure_idle
from app.api.library_ai import RewriteIn, rewrite_target
from app.db import get_sessionmaker
from app.models import Book, Character, MeetingMessage, SettingSuggestion, WorldEntry
from app.services import jobs
from app.services.chat import conversation_lock, model
from app.services.chat_context import dialogue, dialogue_text, references, reply_values, thread_of
from app.services.group_notes import active_note_job, revert_id, update_message
from app.services.library import load_target, lock_book
from app.services.library_context import load_context
from app.services.meeting import SPEAKER_NAMES, post_message, publish
from app.services.requirements import SCOPE_INPUTS, add_requirement
from app.services.versions import record_version, snapshot_of, target_type_of


def item_line(item):
    where, target, part, category, change = (item.get(k, "") for k in ("where", "target", "part", "category", "change"))
    if where == "写作要求":
        return f"写作要求（{item.get('scope', '一直有效')}）：{change}"
    if where == "定调":
        return f"定调：{change}"
    place = f"{where} · {target}"
    if where == "设定库":
        if category:
            place += f"（新建 · {category}）"
        if part:
            place += f" · {part}"
    return f"{place}：{change}"


def plan_text(plan, *, feedback=False):
    lines = [f"【和作者商量定的方案：{plan['title']}】" if feedback else f"方案：{plan['title']}", plan["summary"]]
    if feedback:
        lines.append("要落实的：")
    lines.extend(("- " if feedback else "· ") + item_line(i) for i in plan.get("items", []))
    if plan.get("open_questions"):
        lines.append(("还没定的（先不用管）：" if feedback else "还没定的：") + "；".join(plan["open_questions"]))
    return "\n".join(lines)


async def latest_plan(session, book_id, thread):
    return await session.scalar(
        select(MeetingMessage)
        .where(
            MeetingMessage.book_id == book_id,
            MeetingMessage.kind == "plan",
            MeetingMessage.payload["status"].astext == "open",
            (MeetingMessage.payload["thread"].astext == thread)
            if thread != "group"
            else MeetingMessage.payload["thread"].astext.is_(None),
        )
        .order_by(MeetingMessage.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def make_plan_background(book_id, thread, note_id, redis):
    role = thread if thread != "group" else "chief"
    async with conversation_lock(redis, book_id, thread):
        await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": True, "mode": "plan"})
        async with get_sessionmaker()() as session:
            try:
                state = await thread_of(session, book_id, thread)
                rows = await dialogue(session, book_id, thread, state.reset_after)
                book = await session.get(Book, book_id)
                note = await session.get(MeetingMessage, note_id)
                values = await reply_values(session, book, thread, role, rows, [note], state.summary)
                values = {
                    k: values[k] for k in ("concept", "library", "outline", "progress", "pending", "summary", "note")
                }
                values.update(who=SPEAKER_NAMES.get(thread, "编辑部"), recent=dialogue_text(rows[-30:], limit=12000))
                await session.commit()
                result = await model(book_id, role, ChatPlan, "chat_plan", purpose="总结方案", **values)
                plan = result.model_dump()
                plan["items"] = plan["items"][:12]
                if not plan["items"] and not plan["open_questions"]:
                    await post_message(
                        session,
                        redis,
                        book_id=book_id,
                        job_id=None,
                        speaker=role,
                        kind="speech",
                        content="前面还没聊出要落实的东西。想好了再叫我总结。",
                        payload={"reply_to": [note_id], **({"thread": thread} if thread != "group" else {})},
                    )
                    note = await session.get(MeetingMessage, note_id)
                    await update_message(session, redis, note, outcome={"kind": "chat", "handled": True})
                    return
                previous = await latest_plan(session, book_id, thread)
                while previous:
                    await update_message(session, redis, previous, status="superseded")
                    previous = await latest_plan(session, book_id, thread)
                data = await post_message(
                    session,
                    redis,
                    book_id=book_id,
                    job_id=None,
                    speaker=role,
                    kind="plan",
                    content=plan_text(plan),
                    payload={
                        "plan": plan,
                        "status": "open",
                        "results": [],
                        **({"thread": thread} if thread != "group" else {}),
                    },
                )
                note = await session.get(MeetingMessage, note_id)
                await update_message(session, redis, note, outcome={"kind": "plan_made", "plan_id": data["id"]})
            except Exception as exc:
                await session.rollback()
                await post_message(
                    session,
                    redis,
                    book_id=book_id,
                    job_id=None,
                    speaker="system",
                    kind="error",
                    content=f"{SPEAKER_NAMES[role]}这会儿没整理成方案：{exc}。再试一次。",
                    payload={"thread": thread},
                )
                note = await session.get(MeetingMessage, note_id)
                if note:
                    await update_message(session, redis, note, outcome={"kind": "failed", "reason": str(exc)})
            finally:
                await publish(redis, book_id, "chat_typing", {"thread": thread, "speaker": role, "on": False})


async def request_apply(session, redis, message_id, items, background_tasks):
    message = await session.scalar(
        select(MeetingMessage)
        .where(MeetingMessage.id == message_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if message is None or message.kind != "plan":
        raise HTTPException(404, "方案不存在")
    if message.payload.get("status") != "open":
        raise HTTPException(409, "这个方案已经处理过了")
    plan = deepcopy(message.payload["plan"])
    if items is not None:
        plan["items"] = [i.model_dump() for i in items]
    message.content = plan_text(plan)
    data = await update_message(session, redis, message, plan=plan, status="applying", results=[])
    background_tasks.add_task(apply_background, message_id, redis)
    return data


async def suggestion(session, book_id, title, item):
    row = SettingSuggestion(
        book_id=book_id,
        kind="chat",
        title=f"方案「{title}」里的：{item_line(item)}",
        payload={"op": "note", "content": item["change"]},
    )
    session.add(row)
    await session.flush()
    return {"kind": "suggestion", "suggestion_id": str(row.id)}


async def save_requirement(session, book_id, message_id, item):
    row = await add_requirement(
        session, book_id, item["change"], "plan", SCOPE_INPUTS[item.get("scope", "一直有效")], message_id=message_id
    )
    return {"kind": "requirement", "requirement_id": str(row.id)}


async def apply_item(session, redis, book_id, message_id, title, item):
    await lock_book(session, book_id)
    session.expire_all()
    book = await session.get(Book, book_id)
    if item["where"] == "写作要求":
        return await save_requirement(session, book_id, message_id, item)
    working = await jobs.is_busy(session, book_id)
    if working and item["where"] in {"设定库", "大纲"}:
        return await suggestion(session, book_id, title, item)
    # Concept rewrites also cannot race with an active editor.
    if working:
        return await suggestion(session, book_id, title, item)
    ctx = await load_context(session, book)
    where, name = item["where"], item.get("target", "")
    if where == "设定库":
        target = ctx.find_target(name)
        if target is None:
            if not name.strip():
                raise ValueError("请写出要新建的名称")
            category = next(
                (c for c in ctx.categories if c["name"] == item.get("category")),
                next(c for c in ctx.categories if c["key"] == "特殊规则"),
            )
            values = dict(
                book_id=book_id,
                name=name,
                status="must",
                source="ai",
                one_line=re.split(r"(?<=[。！？!?])|\n", item["change"], maxsplit=1)[0],
            )
            target = (
                Character(**values, background=item["change"])
                if category["key"] == "角色卡片"
                else WorldEntry(**values, category=category["key"], style=category["style"], content=item["change"])
            )
            session.add(target)
            await session.flush()
            kind = target_type_of(target)
            await record_version(session, book_id, kind, target, "ai", f"方案：{title}")
            return {
                "kind": "created",
                "target_type": kind,
                "target_id": str(target.id),
                "target_label": f"{category['name']} · {name}",
                "snapshot": snapshot_of(target),
            }
        path = ctx.route_path(target, item.get("part", ""))
    elif where == "定调":
        target, path = book, "story"
    else:
        target = None
        if nums := references(name, "篇", 1):
            target = next((n for n in ctx._arcs() if ctx.segment_number(n) == nums[0] and n.segment), None)
            path = "text"
        elif nums := references(name, "卷", 1):
            target = next((v for v in ctx.volumes if v.index == nums[0]), None)
            path = "summary"
        elif m := re.fullmatch(r"单元[「『](.+)[」』]", name):
            target = next((u for u in ctx.units if u.title == m[1]), None)
            path = "summary"
        if target is None:
            return await suggestion(session, book_id, title, item)
    if getattr(target, "locked", False) or getattr(target, "status", "") == "pinned":
        return await suggestion(session, book_id, title, item)
    kind, target_id = target_type_of(target), target.id
    label = ctx.target_label(target, path)
    if kind in {"segment", "volume", "unit"}:
        from app.services.library import ensure_unwritten

        try:
            await ensure_unwritten(session, target)
        except HTTPException:
            return await suggestion(session, book_id, title, item)
    try:
        await rewrite_target(
            session,
            redis,
            book,
            RewriteIn(target_type=kind, target_id=target_id, path=path, mode="instruction", instruction=item["change"]),
            require_idle=True,
            allow_waiting=True,
            require_unwritten=True,
            single_attempt=True,
        )
    except HTTPException as exc:
        await session.rollback()
        if exc.status_code == 409 and (
            "正在工作" in str(exc.detail) or "已锁" in str(exc.detail) or "已经开写" in str(exc.detail)
        ):
            return await suggestion(session, book_id, title, item)
        raise
    return {
        "kind": "edit",
        "target_type": kind,
        "target_id": str(target_id),
        "target_label": label,
        "mode": "instruction",
        "revert_version_id": await revert_id(session, kind, target_id),
    }


async def append_result(session, redis, message_id, result):
    row = await session.get(MeetingMessage, message_id)
    await update_message(session, redis, row, results=[*row.payload.get("results", []), result])


async def apply_background(message_id, redis):
    from app.api.jobs import FEEDBACK_LABELS, feedback_to_job

    async with get_sessionmaker()() as session:
        row = await session.get(MeetingMessage, message_id)
        book_id, role, thread, plan = (
            row.book_id,
            row.speaker,
            row.payload.get("thread", "group"),
            deepcopy(row.payload["plan"]),
        )
        await lock_book(session, book_id)
        job = await active_note_job(session, book_id)
        key = (job.pending or {}).get("kind") if job and job.status == "waiting_author" else ""
        if key == "setup_piece":
            key = "outline" if job.pending.get("piece") == "outline" else ""
        if key in FEEDBACK_LABELS:
            try:
                await session.refresh(job, with_for_update=True)
                requirement_results = [
                    await save_requirement(session, book_id, message_id, item)
                    for item in plan["items"]
                    if item["where"] == "写作要求"
                ]
                await feedback_to_job(session, redis, job, plan_text(plan, feedback=True), remember=False)
                await append_result(
                    session, redis, message_id, {"kind": "feedback", "label": f"已交给编辑部：{FEEDBACK_LABELS[key]}"}
                )
                for result in requirement_results:
                    await append_result(session, redis, message_id, result)
            except Exception as exc:
                await session.rollback()
                await append_result(
                    session, redis, message_id, {"kind": "failed", "reason": str(getattr(exc, "detail", exc))}
                )
            items = []
        else:
            items = plan["items"]
        await session.commit()
        for item in items:
            try:
                result = await apply_item(session, redis, book_id, message_id, plan["title"], item)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                result = {"kind": "failed", "reason": str(getattr(exc, "detail", exc))}
            await append_result(session, redis, message_id, result)
        row = await session.get(MeetingMessage, message_id)
        results = row.payload["results"]
        await update_message(session, redis, row, status="applied")
        feedback = next((r for r in results if r["kind"] == "feedback"), None)
        if feedback:
            content = f"方案「{plan['title']}」交给编辑部了：{feedback['label']}。"
        else:
            fragments = [
                f"{label} {sum(r['kind'] == kind for r in results)} {unit}"
                for kind, label, unit in (
                    ("edit", "改了", "处"),
                    ("created", "新建", "条"),
                    ("requirement", "记了", "条要求"),
                    ("suggestion", "", "条放进了待处理的建议"),
                )
                if any(r["kind"] == kind for r in results)
            ]
            content = (
                f"方案「{plan['title']}」照办了：" + ("，".join(s.strip() for s in fragments) or "没有改动") + "。"
            )
        await post_message(
            session,
            redis,
            book_id=book_id,
            job_id=None,
            speaker=role,
            kind="speech",
            content=content,
            payload={"reply_to": [message_id], **({"thread": thread} if thread != "group" else {})},
        )


async def undo_created(session, redis, message_id, index):
    row = await session.get(MeetingMessage, message_id)
    if row is None or row.kind != "plan":
        raise HTTPException(404, "方案不存在")
    book_id = row.book_id
    await lock_book(session, book_id)
    await session.refresh(row, with_for_update=True)
    results = deepcopy(row.payload.get("results", []))
    if index < 0 or index >= len(results) or results[index]["kind"] != "created":
        raise HTTPException(422, "这条结果不能撤销新建")
    result = results[index]
    await ensure_idle(session, book_id)
    if not result.get("undone"):
        target = await load_target(session, book_id, result["target_type"], result["target_id"], for_update=True)
        if snapshot_of(target) != result["snapshot"]:
            raise HTTPException(409, "已经改过，去设定库处理")
        from app.api.bible import _delete

        await _delete(session, Character if result["target_type"] == "character" else WorldEntry, target.id)
        result["undone"] = True
    return await update_message(session, redis, row, results=results)
