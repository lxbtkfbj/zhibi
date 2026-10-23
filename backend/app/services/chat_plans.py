"""会话里的方案卡：先看方案，再显式逐条落实，所有结果可追溯。"""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.schemas import ChatPlan
from app.api.deps import ensure_idle
from app.db import get_sessionmaker
from app.models import Book, Character, MeetingMessage, SettingSuggestion, WorldEntry
from app.services import book_saves, jobs
from app.services.chat import conversation_lock, model
from app.services.chat_context import conversation_state, dialogue, dialogue_text, reply_values
from app.services.group_notes import active_note_job, update_message
from app.services.library import load_target, lock_book
from app.services.meeting import SPEAKER_NAMES, post_message, publish
from app.services.requirements import SCOPE_INPUTS, add_requirement
from app.services.versions import snapshot_of


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
                note = await session.get(MeetingMessage, note_id)
                # 群聊只总结这句话所在的那一段对话
                conv = (note.payload or {}).get("conv") if thread == "group" else None
                state = await conversation_state(session, book_id, thread, conv)
                rows = await dialogue(
                    session,
                    book_id,
                    thread,
                    getattr(state, "reset_after", 0),
                    conv=state.id if thread == "group" else None,
                )
                book = await session.get(Book, book_id)
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
    from app.services.memories import remembered_outcome

    return remembered_outcome(row, working=await jobs.is_busy(session, book_id))


async def apply_item(session, redis, book_id, message_id, title, item):
    """方案卡上的一条：和聊天里动手是同一套（改一栏、补齐、新建、写大纲、记要求、改简介、删除），
    每条都有前后对照、能换回原来的、能再改一版。编辑部正在写的时候，除了写作要求都先放进待处理。"""
    from app.services.chat_tools import plan_change, run_change

    await lock_book(session, book_id)
    session.expire_all()
    book = await session.get(Book, book_id)
    if item["where"] != "写作要求" and await jobs.is_busy(session, book_id):
        return await suggestion(session, book_id, title, item)
    if item["where"] == "写作要求":
        result = await save_requirement(session, book_id, message_id, item)
        await session.commit()
        return result
    change = await plan_change(session, book, item)
    await session.commit()
    message = await session.get(MeetingMessage, message_id)
    try:
        outcome, _ = await run_change(session, redis, message, change)
    except HTTPException as exc:
        # 锁住的、已经开写的、编辑部刚好开工的：照旧放进待处理的建议，不硬改
        if exc.status_code != 409 or not any(w in str(exc.detail) for w in ("已锁", "已经开写", "正在工作")):
            raise
        await session.rollback()
        outcome = await suggestion(session, book_id, title, item)
    # 结果放在方案卡的 results 里，卡上不留 outcome
    message = await session.get(MeetingMessage, message_id)
    await session.refresh(message)
    message.payload = {k: v for k, v in (message.payload or {}).items() if k != "outcome"}
    await session.commit()
    return outcome


def results_line(results) -> str:
    """方案卡照办完说一句：改了几处、新建几条、记了几条要求、删了几处、几条没做成。"""

    def count(*kinds, options=None):
        return sum(r["kind"] in kinds and (options is None or (r.get("mode") == "options") == options) for r in results)

    created = sum(len(r.get("items") or [None]) for r in results if r["kind"] == "created")
    parts = [
        (count("edit", "fill", "outline", options=False), "改了 {} 处"),
        (count("edit", options=True), "{} 处出了三种写法等你挑"),
        (created, "新建 {} 条"),
        (count("requirement", "to_job"), "记了 {} 条要求"),
        (count("deleted"), "删了 {} 处"),
        (count("suggestion", "later"), "{} 条放进了待处理的建议"),
        (count("failed", "not_found", "too_late"), "{} 条没做成"),
    ]
    return "，".join(text.format(n) for n, text in parts if n)


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
        # 编辑部动书之前：作者自己改过还没存的，先存一档
        if any(item["where"] != "写作要求" for item in plan["items"]):
            await book_saves.before_ai(session, book_id)
        await lock_book(session, book_id)
        job = await active_note_job(session, book_id)
        opened = jobs.open_wait(job)
        key = (job.pending or {}).get("kind") if job and job.status == "waiting_author" and not opened else ""
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
        setup_applied = False
        for item in items:
            try:
                result = await apply_item(session, redis, book_id, message_id, plan["title"], item)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                result = {"kind": "failed", "reason": str(getattr(exc, "detail", exc))}
            if item["where"] in {"定调", "设定库"} and result["kind"] in {"edit", "fill", "created"}:
                setup_applied = True
            await append_result(session, redis, message_id, result)
        row = await session.get(MeetingMessage, message_id)
        results = row.payload["results"]
        await update_message(session, redis, row, status="applied")
        feedback = next((r for r in results if r["kind"] == "feedback"), None)
        if feedback:
            content = f"方案「{plan['title']}」交给编辑部了：{feedback['label']}。"
        else:
            content = f"方案「{plan['title']}」照办了：" + (results_line(results) or "没有改动") + "。"
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
        # 方案卡照办完：一档
        if any(result.get("change") for result in results):
            await book_saves.safe_checkpoint(
                session, book_id, role, lead=f"{SPEAKER_NAMES.get(role, '主编')}照方案「{plan['title']}」办了："
            )
        if opened and setup_applied and jobs.open_wait(await active_note_job(session, book_id)):
            await post_message(
                session,
                redis,
                book_id=book_id,
                job_id=None,
                speaker="chief",
                kind="speech",
                content="照方案办好了。要我按现在的定调和设定把开书稿补齐吗？点底部的「补齐开书稿」就行；想先看看三个故事方向也可以，挑一个，我按那个方向写。",
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
    if "snapshot" not in result:
        raise HTTPException(422, "这一条在下面点「换回原来的」")
    await ensure_idle(session, book_id)
    if not result.get("undone"):
        target = await load_target(session, book_id, result["target_type"], result["target_id"], for_update=True)
        if snapshot_of(target) != result["snapshot"]:
            raise HTTPException(409, "已经改过，去设定库处理")
        from app.api.bible import _delete

        await _delete(session, Character if result["target_type"] == "character" else WorldEntry, target.id)
        result["undone"] = True
    return await update_message(session, redis, row, results=results)
