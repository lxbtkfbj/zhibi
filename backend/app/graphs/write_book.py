"""写书主循环：分层滚动规划，从第一卷一直写到完本。

每一轮先看「下一步该做什么」（数据库为准，断点续跑、换任务都能接上）：
- 当前这一卷还只有总纲卡片 → 主编拆卷纲（剧情单元、线索节拍、伏笔排期）→ 作者拍板
- 下一个剧情单元还没有章纲 → 主编出这个单元的章纲
- 有章纲、还没定稿的章节 → 写手写正文 → 审稿与设定师并行检查 → 不合格退回重写（最多两次，
  仍不合格交给作者）→ 设定师把本章带来的变化写进设定库和伏笔台账 → 定稿
- 新书写完前 3 章，请作者试读一次；一卷写完进入下一卷；写够这一轮的章数或全书写完就停。
作者随时可以插话：每写完一步都会读到，之后的规划和正文都按作者的话来。
"""

import re
import uuid
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import editorial
from app.agents.context import format_revision
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts
from app.graphs.deps import GraphDeps
from app.llm.router import LLMError
from app.models import Book, Chapter, MeetingMessage, PlotUnit, Volume
from app.services import setup_store, writing_store
from app.services.writing_context import chapter_blocks, chapter_plan_blocks, volume_blocks

# 审稿不合格时最多自动重写几次；之后交给作者
MAX_REWRITES = 2
# 新书写完前几章请作者试读
TRIAL_READ_AFTER = 3
UNTIL = ("count", "volume", "book")


class WriteState(TypedDict, total=False):
    # count：写够 target 章；volume：写完当前这一卷；book：一直写到完本
    until: str
    target: int
    # 这一轮已经定稿的章数
    written: int
    start_volume: int
    notes_seen: int
    # 下一步：plan_volume / volume_gate / plan_chapters / write / trial_gate / finalize / chapter_gate / done
    step: str
    volume_id: str
    volume_index: int
    volume_title: str
    unit_id: str
    chapter_id: str
    chapter_index: int
    chapter_title: str
    # 本章已经重写了几次，以及给写手的修改要求
    attempt: int
    revision: str
    review: dict
    consistency: dict
    blocking: list[str]
    # 作者对卷纲的修改意见
    feedback: str


def initial_state(params: dict) -> WriteState:
    until = params.get("until") if params.get("until") in UNTIL else "count"
    return {
        "until": until,
        "target": max(1, int(params.get("count") or 1)),
        "written": 0,
        "notes_seen": 0,
        "attempt": 0,
        "revision": "",
        "feedback": "",
    }


async def _requirement(session: AsyncSession, book_id: uuid.UUID, line: str) -> None:
    book = await session.get(Book, book_id)
    if book is not None and line.strip():
        book.requirements = list(dict.fromkeys([*(book.requirements or []), line.strip()]))


async def decide(session: AsyncSession, book_id: uuid.UUID, state: WriteState) -> dict:
    """根据数据库里的进度决定下一步。顺手把写完的单元、卷标记为完成。"""
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    finals = await session.scalar(
        select(func.count()).select_from(Chapter).where(Chapter.book_id == book_id, Chapter.status == "final")
    )
    if book.source == "new" and not book.trial_read_done and finals >= TRIAL_READ_AFTER:
        return {"step": "trial_gate"}
    until, written, target = state.get("until", "count"), state.get("written", 0), state.get("target", 1)
    if until == "count" and written >= target:
        return {"step": "done", "reason": f"这一轮计划的 {target} 章都定稿了。"}

    volumes = list(
        (await session.execute(select(Volume).where(Volume.book_id == book_id).order_by(Volume.index))).scalars().all()
    )
    for volume in volumes:
        if volume.status == "done":
            continue
        start = state.get("start_volume") or volume.index
        out = {
            "start_volume": start,
            "volume_id": str(volume.id),
            "volume_index": volume.index,
            "volume_title": volume.title,
        }
        if until == "volume" and volume.index > start:
            return {**out, "step": "done", "reason": f"第{start}卷写完了。"}
        units = list(
            (await session.execute(select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index)))
            .scalars()
            .all()
        )
        if volume.status == "planned" or not units:
            return {**out, "step": "plan_volume"}
        if volume.status == "detailed":
            return {**out, "step": "volume_gate"}
        chapter = (
            await session.execute(
                select(Chapter)
                .where(Chapter.volume_id == volume.id, Chapter.status != "final")
                .order_by(Chapter.index)
                .limit(1)
            )
        ).scalar()
        if chapter is not None:
            return {
                **out,
                "step": "write",
                "unit_id": str(chapter.unit_id),
                "chapter_id": str(chapter.id),
                "chapter_index": chapter.index,
                "chapter_title": chapter.title,
            }
        for unit in units:
            if unit.status == "done":
                continue
            has_chapters = await session.scalar(
                select(func.count()).select_from(Chapter).where(Chapter.unit_id == unit.id)
            )
            if not has_chapters:
                return {**out, "step": "plan_chapters", "unit_id": str(unit.id)}
            unit.status = "done"
        volume.status = "done"
    book.status = "completed"
    return {"step": "done", "reason": "全书写完了！"}


async def _new_notes(d: GraphDeps, seen: int) -> list[tuple[int, str]]:
    async with d.sessionmaker() as session:
        rows = await session.execute(
            select(MeetingMessage.id, MeetingMessage.content)
            .where(MeetingMessage.job_id == d.job_id, MeetingMessage.kind == "note", MeetingMessage.id > seen)
            .order_by(MeetingMessage.id)
        )
        return [(row.id, row.content) for row in rows]


async def dispatch_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    update: dict = {}
    rows = await _new_notes(d, state.get("notes_seen", 0))
    if rows:
        # 作者的插话记进这本书的要求里，之后的卷纲、章纲和正文都要落实
        async with d.sessionmaker() as session:
            for _, content in rows:
                await _requirement(session, d.book_id, content)
            await session.commit()
        update["notes_seen"] = rows[-1][0]
        await d.emit.say("chief", "收到，从接下来的规划和章节开始照你说的写。")
    async with d.sessionmaker() as session:
        decision = await decide(session, d.book_id, state)
        await session.commit()
    reason = decision.pop("reason", "")
    if decision["step"] == "done":
        await d.emit.say("system", f"{reason}本轮共定稿 {state.get('written', 0)} 章。", kind="decision")
    return {**update, **decision}


def route_step(state: WriteState) -> str:
    return state.get("step") or "done"


async def plan_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    feedback = state.get("feedback", "")
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        volume = await session.get(Volume, uuid.UUID(state["volume_id"]))
        blocks = await volume_blocks(session, book, volume)
        ledger = await setup_store.load_ledger(session, d.book_id)
        current: dict = {}
        if feedback:
            units = (
                (
                    await session.execute(
                        select(PlotUnit).where(PlotUnit.volume_id == volume.id).order_by(PlotUnit.index)
                    )
                )
                .scalars()
                .all()
            )
            current = {
                "units": [setup_store.unit_dict(u) for u in units],
                "new_foreshadowings": [f for f in ledger if f["plant_volume"] == volume.index and f["span"] != "长"],
            }
        index, target = volume.index, volume.chapter_count
    await d.emit.status(
        "chief",
        f"主编正在按你的意见修改第{index}卷卷纲…" if feedback else f"主编正在拆第{index}卷：剧情单元、线索交织与伏笔…",
    )
    result = await editorial.plan_volume(d.llm, blocks, current, feedback, purpose=f"写作·第{index}卷卷纲")
    plan = result.model_dump(exclude={"remark"})
    units = fit_chapter_counts(plan["units"], target)
    fresh = setup_store.assign_seqs(plan["new_foreshadowings"], ledger)
    units, fresh = attach_new_foreshadowings(units, fresh, index)
    async with d.sessionmaker() as session:
        volume = await session.get(Volume, uuid.UUID(state["volume_id"]))
        await writing_store.save_volume_plan(session, d.book_id, volume, units, fresh, replace_new=bool(feedback))
        await session.commit()
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"第{index}卷拆成 {len(units)} 个剧情单元，新埋伏笔 {len(fresh)} 条",
        {"type": "volume_plan", "data": {"volume": index, "units": units, "new_foreshadowings": fresh}},
    )
    return {"feedback": ""}


async def volume_gate_node(
    state: WriteState, runtime: Runtime[GraphDeps]
) -> Command[Literal["plan_volume", "dispatch"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    index = state.get("volume_index", 0)
    decision = interrupt({"kind": "volume_review", "volume": index, "title": state.get("volume_title", "")})
    d = runtime.context
    feedback = str(decision.get("feedback", "")).strip()
    async with d.sessionmaker() as session:
        if decision.get("action") == "approve":
            volume = await session.get(Volume, uuid.UUID(state["volume_id"]))
            if volume is not None and volume.status == "detailed":
                volume.status = "approved"
            await session.commit()
            await d.emit.say("system", f"作者批准了第{index}卷卷纲，开写。", kind="decision")
            return Command(goto="dispatch")
        # 卷纲的修改意见也要记住，免得以后的规划又改回去
        await _requirement(session, d.book_id, f"第{index}卷卷纲的修改意见：{feedback}")
        await session.commit()
    return Command(goto="plan_volume", update={"feedback": feedback or "请整体再打磨一遍。"})


async def plan_chapters_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(state["unit_id"]))
        exists = await session.scalar(select(func.count()).select_from(Chapter).where(Chapter.unit_id == unit.id))
        if exists:
            return {}  # 上次已经出过章纲（例如提交后、检查点保存前中断）
        volume = await session.get(Volume, unit.volume_id)
        book = await session.get(Book, d.book_id)
        first = await writing_store.next_chapter_index(session, d.book_id)
        blocks = await chapter_plan_blocks(session, book, volume, unit, first)
        label = f"第{volume.index}卷第{unit.index}单元「{unit.title}」"
    await d.emit.status("chief", f"主编正在给{label}出章纲…")
    result = await editorial.plan_chapters(d.llm, blocks)
    plans = [c.model_dump() for c in result.chapters if c.title.strip() or c.goal.strip()]
    if not plans:
        raise LLMError("主编没有给出章纲")
    async with d.sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(state["unit_id"]))
        rows = await writing_store.create_chapters(session, d.book_id, unit, plans)
        await session.commit()
        listing = [{"index": r.index, "title": r.title, "hook": r.outline.get("hook", "")} for r in rows]
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"{label}章纲：第{listing[0]['index']}-{listing[-1]['index']}章",
        {"type": "chapter_plan", "data": {"unit": label, "chapters": listing}},
    )
    return {}


HEADING = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零〇两]+章[^\n]*|#+[^\n]*)\n+")
ENDING = re.compile(r"\n*[（(]?\s*(本章完|未完待续|本章结束)[^\n]*$")


def clean_text(text: str) -> str:
    """去掉模型偶尔加上的章节标题和「本章完」。"""
    text = HEADING.sub("", text.strip(), count=1)
    return ENDING.sub("", text).strip()


def word_count(text: str) -> int:
    return len(re.sub(r"\s", "", text))


async def write_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    revision = state.get("revision", "")
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        book = await session.get(Book, d.book_id)
        blocks = await chapter_blocks(session, book, chapter)
        rewriting = bool(revision and chapter.content)
        blocks["revision"] = (
            format_revision("上一稿", chapter.content, revision).replace(
                "请在当前版本的基础上修改，保留不需要改动的部分，输出修改后的完整结果。",
                "请按修改要求重写这一章，保留上一稿里写得好的部分，输出重写后的完整正文。",
            )
            if rewriting
            else ""
        )
        chapter.status = "drafting"
        await session.commit()
        index, title = chapter.index, chapter.title
    await d.emit.status("writer", f"写手正在{'重写' if rewriting else '写'}第{index}章《{title}》…")
    parts = [chunk async for chunk in editorial.write_chapter(d.llm, blocks)]
    text = clean_text("".join(parts))
    if not text:
        raise LLMError("写手没有写出正文")
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        chapter.content = text
        chapter.word_count = word_count(text)
        await session.commit()
    await d.emit.artifact(
        "writer",
        f"第{index}章《{title}》{'重写稿' if rewriting else '初稿'}，{word_count(text)} 字",
        {
            "type": "chapter_draft",
            "data": {"index": index, "title": title, "words": word_count(text), "excerpt": text[:160]},
        },
    )
    return {"review": {}, "consistency": {}}


async def review_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        blocks = await chapter_blocks(session, await session.get(Book, d.book_id), chapter)
    await d.emit.status("reviewer", f"审稿正在读第{state.get('chapter_index')}章…")
    result = await editorial.review_chapter(d.llm, blocks)
    return {"review": result.model_dump()}


async def check_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        blocks = await chapter_blocks(session, await session.get(Book, d.book_id), chapter)
    await d.emit.status("lorekeeper", f"设定师正在对照设定库检查第{state.get('chapter_index')}章…")
    result = await editorial.check_consistency(d.llm, blocks)
    return {"consistency": result.model_dump()}


def blocking_issues(review: dict, consistency: dict) -> list[str]:
    """必须重写的问题：审稿判退且有中等以上的问题，或者设定检查发现严重矛盾。"""
    out = []
    if review.get("verdict") == "revise":
        out += [
            f"[审稿] {i['problem']}——{i['suggestion']}"
            for i in review.get("issues", [])
            if i.get("severity") in ("high", "medium")
        ]
    out += [
        f"[设定] {i['problem']}——{i['suggestion']}"
        for i in consistency.get("issues", [])
        if i.get("severity") == "high"
    ]
    return out


async def judge_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    review, consistency = state.get("review") or {}, state.get("consistency") or {}
    blocking = blocking_issues(review, consistency)
    attempt = state.get("attempt", 0)
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        chapter.review = {"review": review, "consistency": consistency}
        if blocking and attempt < MAX_REWRITES:
            chapter.attempts = attempt + 1
        await session.commit()
    if review.get("remark"):
        await d.emit.say("reviewer", review["remark"])
    if consistency.get("issues") and consistency.get("remark"):
        await d.emit.say("lorekeeper", consistency["remark"])
    await d.emit.artifact(
        "reviewer",
        f"第{state.get('chapter_index')}章审稿：{'退回重写' if blocking else '通过'}",
        {
            "type": "chapter_review",
            "data": {
                "verdict": "revise" if blocking else "pass",
                "highlights": review.get("highlights", []),
                "issues": [*review.get("issues", []), *consistency.get("issues", [])],
            },
        },
    )
    if not blocking:
        return {"step": "finalize", "blocking": []}
    if attempt < MAX_REWRITES:
        await d.emit.status("chief", f"主编：第{state.get('chapter_index')}章退回重写（第 {attempt + 1} 次）。")
        revision = "\n".join(f"- {line}" for line in blocking)
        return {"step": "write", "attempt": attempt + 1, "revision": revision, "blocking": blocking}
    await d.emit.status("chief", f"第{state.get('chapter_index')}章重写 {MAX_REWRITES} 次仍未通过，请作者定夺。")
    return {"step": "chapter_gate", "blocking": blocking}


def route_judge(state: WriteState) -> str:
    return state.get("step", "finalize")


async def chapter_gate_node(state: WriteState, runtime: Runtime[GraphDeps]) -> Command[Literal["write", "finalize"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    decision = interrupt(
        {
            "kind": "chapter_stuck",
            "chapter": state.get("chapter_index"),
            "title": state.get("chapter_title", ""),
            "issues": state.get("blocking") or [],
        }
    )
    d = runtime.context
    if decision.get("action") == "approve":
        await d.emit.say("system", f"作者决定第{state.get('chapter_index')}章就按现在的版本定稿。", kind="decision")
        return Command(goto="finalize")
    feedback = str(decision.get("feedback", "")).strip() or "按审稿意见再改一次。"
    return Command(goto="write", update={"revision": f"- [作者] {feedback}"})


async def finalize_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    done = {"written": state.get("written", 0) + 1, "attempt": 0, "revision": "", "review": {}, "consistency": {}}
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        if chapter.status == "final":
            return done  # 上次已经定稿（提交后、检查点保存前中断）
        blocks = await chapter_blocks(session, await session.get(Book, d.book_id), chapter)
        index, title, words = chapter.index, chapter.title, chapter.word_count
    await d.emit.status("lorekeeper", f"设定师正在把第{index}章的变化记进设定库…")
    digest = await editorial.digest_chapter(d.llm, blocks)
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        changes = await writing_store.apply_digest(session, d.book_id, chapter, digest)
        await session.commit()
    if digest.remark:
        await d.emit.say("lorekeeper", digest.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"第{index}章《{title}》定稿，{words} 字",
        {
            "type": "chapter_final",
            "data": {"index": index, "title": title, "words": words, "summary": digest.summary, **changes},
        },
    )
    return done


async def trial_gate_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    decision = interrupt({"kind": "trial_read", "chapters": TRIAL_READ_AFTER})
    d = runtime.context
    feedback = str(decision.get("feedback", "")).strip()
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        book.trial_read_done = True
        if feedback:
            await _requirement(session, d.book_id, f"前 {TRIAL_READ_AFTER} 章试读意见：{feedback}")
        await session.commit()
    await d.emit.say(
        "system",
        f"作者试读完前 {TRIAL_READ_AFTER} 章：{feedback}"
        if feedback
        else f"作者试读完前 {TRIAL_READ_AFTER} 章，满意，继续写。",
        kind="decision",
    )
    if feedback:
        await d.emit.say("chief", "意见记下了，后面每一章都按这个来写。")
    return {}


def build_write_graph() -> StateGraph:
    graph = StateGraph(WriteState, context_schema=GraphDeps)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("plan_volume", plan_volume_node)
    graph.add_node("volume_gate", volume_gate_node)
    graph.add_node("plan_chapters", plan_chapters_node)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)
    graph.add_node("check", check_node)
    graph.add_node("judge", judge_node)
    graph.add_node("chapter_gate", chapter_gate_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("trial_gate", trial_gate_node)

    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        route_step,
        {
            "plan_volume": "plan_volume",
            "volume_gate": "volume_gate",
            "plan_chapters": "plan_chapters",
            "write": "write",
            "trial_gate": "trial_gate",
            "done": END,
        },
    )
    for source in ("plan_volume", "plan_chapters", "finalize", "trial_gate"):
        graph.add_edge(source, "dispatch")
    # 审稿与设定检查并行，两边都做完再判定
    graph.add_edge("write", "review")
    graph.add_edge("write", "check")
    graph.add_edge(["review", "check"], "judge")
    graph.add_conditional_edges(
        "judge", route_judge, {"write": "write", "finalize": "finalize", "chapter_gate": "chapter_gate"}
    )
    return graph
