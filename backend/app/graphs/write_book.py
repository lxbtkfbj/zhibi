"""写书主循环：分层滚动规划，从第一卷一直写到完本。

每一轮先看「下一步该做什么」（数据库为准，断点续跑、换任务都能接上）：
- 当前这一卷还只有总纲卡片 → 拆卷纲：主编先想 2-3 个不同方向，每个方向并行各拆一份完整卷纲 →
  审稿按爽点、线索交织、反派智商、新意打分比稿，选出最好的一份（必要时主编把别的方案的长处融进来）→
  审稿做专项审稿（反派是否降智、爽点节奏、伏笔排期、套路重复、期待感，排期与节奏底线由程序检查）→
  有严重问题主编自动改一轮 → 存库 → 作者拍板（提意见则主编按意见改，再拍板）
- 下一个剧情单元还没有章纲 → 主编出这个单元的章纲
- 有章纲、还没定稿的章节 → 设定师读章纲备资料 → 写手写正文（流式，写到哪了实时推给网页）→
  字数明显不够就接着写、结尾写成总结就改写结尾 → 审稿与设定师并行检查 → 不合格退回重写（最多两次，
  仍不合格交给作者）→ 设定师把本章带来的变化写进设定库和伏笔台账 → 定稿
- 一个单元写完，设定师写单元回顾；一卷写完，写卷回顾。后面的规划和写作靠这些回顾记住前情。
- 新书写完前 3 章，请作者试读一次；一卷写完进入下一卷；写够这一轮的章数或全书写完就停。
作者随时可以插话：每写完一步都会读到，之后的规划和正文都按作者的话来。

另有一张小图 build_rewrite_graph：作者对已定稿的某一章提意见，撤销这一章原来记进设定库的变化 →
按意见重写（同样经过续写、改结尾、审稿）→ 重新提取变化定稿 → 重写受影响的单元、卷回顾。
"""

import operator
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Overwrite, Send, interrupt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import editorial
from app.agents.context import foreshadow_code, format_direction, format_pitches, format_revision
from app.agents.planning import attach_new_foreshadowings, expectation_issues, fit_chapter_counts, schedule_issues
from app.agents.playbook import Playbook, pick, repetition_issues
from app.agents.rhythm import check_chapter_plan, overdue_expectations
from app.agents.setup_puzzle import clean_reveals
from app.book_settings import settings_of, strictness_text
from app.graphs.deps import GraphDeps
from app.llm.router import LLMError
from app.models import Book, Chapter, MeetingMessage, PlotUnit, StoryNode, Volume
from app.services import setup_store, writing_store
from app.services.notes import note_thread
from app.services.requirements import active_notes, add_requirement, deleted_texts, ingest_notes
from app.services.writing_context import (
    SENTENCE,
    chapter_blocks,
    chapter_plan_blocks,
    chapter_words,
    format_chapter_outline,
    material_blocks,
    pick_materials,
    prior_units,
    unit_recap_blocks,
    volume_blocks,
    volume_recap_blocks,
)

ASPECT_NAMES = {
    "villain": "反派智商",
    "rhythm": "爽点节奏",
    "foreshadow": "伏笔排期",
    "repetition": "套路重复",
    "expectation": "期待感",
}
NODE_CONTENT = ("title", "event", "prerequisite", "consequence")
# 新书写完前几章请作者试读
TRIAL_READ_AFTER = 3
UNTIL = ("count", "volume", "book")
# 写完后检查：字数不到目标的七成就让写手接着写（最多两次）；结尾写成总结就改写结尾（一次）
SHORT_RATIO = 0.7
MAX_EXTENSIONS = 2
# 改结尾时给写手看结尾之前的多少字
ENDING_CONTEXT = 1500
# 写手写到哪了推给网页：每多写这么多字、或者隔这么久推一次
DRAFT_PUSH_CHARS = 200
DRAFT_PUSH_S = 0.6
RECAP_STEPS = ("recap_unit", "recap_volume")


class WriteState(TypedDict, total=False):
    # count：写够 target 章；volume：写完当前这一卷；book：一直写到完本
    until: str
    target: int
    # 这一轮已经定稿的章数
    written: int
    start_volume: int
    notes_seen: int
    # 下一步：plan_volume / volume_gate / plan_chapters / write / recap_unit / recap_volume / trial_gate /
    # finalize / chapter_gate / done
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
    # 作者对这一章的意见（重写已定稿的章节时）：之后每次重写都要落实
    author_note: str
    # 写完后的检查：续写了几次、结尾改过没有、下一步（extend 接着写 / fix_ending 改结尾 / 空：送审）
    extensions: int
    ending_fixed: bool
    polish: str
    review: dict
    consistency: dict
    blocking: list[str]
    # 作者对卷纲的修改意见
    feedback: str
    # 卷纲比稿：主编想的几个方向、并行拆出的各份方案、审稿选中的方案和融合建议
    directions: list[dict]
    pitches: Annotated[list[dict], operator.add]
    chosen_pitch: int
    merge_note: str
    # 正在打磨、还没存库的卷纲；专项审稿要求的修改；交给作者拍板时还没解决的问题
    volume_draft: dict
    volume_fix: str
    open_issues: list[str]
    node_update: dict | None


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


async def _requirement(session: AsyncSession, book_id: uuid.UUID, line: str, source: str = "note") -> None:
    await add_requirement(session, book_id, line, source)


async def live_settings(d: GraphDeps) -> dict:
    async with d.sessionmaker() as session:
        return settings_of(await session.get(Book, d.book_id))


async def decide(session: AsyncSession, book_id: uuid.UUID, state: WriteState) -> dict:
    """根据数据库里的进度决定下一步。顺手把写完的单元、卷标记为完成。

    这一轮的章数写够了也先把该写的单元回顾、卷回顾写完再停，免得下一轮开头才补。
    """
    book = await session.get(Book, book_id)
    if book is None:
        raise ValueError("书不存在")
    finals = await session.scalar(
        select(func.count()).select_from(Chapter).where(Chapter.book_id == book_id, Chapter.status == "final")
    )
    if (
        settings_of(book)["trial_read"]
        and book.source == "new"
        and not book.trial_read_done
        and finals >= TRIAL_READ_AFTER
    ):
        return {"step": "trial_gate"}
    until, written, target = state.get("until", "count"), state.get("written", 0), state.get("target", 1)
    decision = await _next_step(session, book, state)
    if until == "count" and written >= target and decision["step"] not in RECAP_STEPS:
        return {"step": "done", "reason": f"这一轮计划的 {target} 章都定稿了。"}
    return decision


async def _has_finals(session: AsyncSession, volume_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(Chapter.id).where(Chapter.volume_id == volume_id, Chapter.status == "final").limit(1)
    )
    return found is not None


async def _next_step(session: AsyncSession, book: Book, state: WriteState) -> dict:
    until = state.get("until", "count")
    volumes = list(
        (await session.execute(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index))).scalars().all()
    )
    for volume in volumes:
        here = {"volume_id": str(volume.id), "volume_index": volume.index, "volume_title": volume.title}
        if volume.status == "done":
            if not volume.recap.strip() and await _has_finals(session, volume.id):
                return {**here, "step": "recap_volume"}  # 早先写完、还没有卷回顾的卷，补上
            continue
        start = state.get("start_volume") or volume.index
        out = {**here, "start_volume": start}
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
            if unit.status != "done":
                has_chapters = await session.scalar(
                    select(func.count()).select_from(Chapter).where(Chapter.unit_id == unit.id)
                )
                if not has_chapters:
                    return {**out, "step": "plan_chapters", "unit_id": str(unit.id)}
                unit.status = "done"
            if not unit.recap.strip():
                return {**out, "step": "recap_unit", "unit_id": str(unit.id)}
        if not volume.recap.strip():
            return {**out, "step": "recap_volume"}
        volume.status = "done"
    book.status = "completed"
    return {"step": "done", "reason": "全书写完了！"}


async def _new_notes(d: GraphDeps, seen: int) -> list[tuple[int, str, dict | None]]:
    async with d.sessionmaker() as session:
        rows = await session.execute(
            select(MeetingMessage.id, MeetingMessage.content, MeetingMessage.payload)
            .where(MeetingMessage.job_id == d.job_id, MeetingMessage.kind == "note", MeetingMessage.id > seen)
            .order_by(MeetingMessage.id)
        )
        messages = [(row.id, row.content, row.payload) for row in rows]
        return await active_notes(session, d.book_id, messages) if messages else []


async def dispatch_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    update: dict = {}
    rows = await _new_notes(d, state.get("notes_seen", 0))
    if rows:
        # 作者的插话记进这本书的要求里，之后的卷纲、章纲和正文都要落实
        async with d.sessionmaker() as session:
            await ingest_notes(session, d.book_id, rows)
            await session.commit()
        update["notes_seen"] = rows[-1][0]
        if any(not note_thread(payload) for _, _, payload in rows):
            await d.emit.say("chief", "收到，从接下来的规划和章节开始照你说的写。")
        for _, _, payload in rows:
            if thread := note_thread(payload):
                await d.emit.say(thread, "收到，已经记下，之后的规划和章节都会照办。", payload={"thread": thread})
    async with d.sessionmaker() as session:
        decision = await decide(session, d.book_id, state)
        await session.commit()
    reason = decision.pop("reason", "")
    if decision["step"] == "done":
        await d.emit.say("system", f"{reason}本轮共定稿 {state.get('written', 0)} 章。", kind="decision")
    return {**update, **decision}


def route_step(state: WriteState) -> str:
    return state.get("step") or "done"


async def _volume_context(d: GraphDeps, volume_id: str) -> tuple[Volume, Playbook, dict[str, Any]]:
    """拆卷纲各步共用的上下文：这一卷、这本书的题材打法、拼好的各段提示词。"""
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        volume = await session.get(Volume, uuid.UUID(volume_id))
        # 将提示词这一次引用的目标绑定到稳定 ID，而非在模型返回后重新解释节点序号。
        nodes = await setup_store.load_nodes(session, d.book_id)
        blocks = await volume_blocks(session, book, volume, nodes=nodes)
        blocks["_target_snapshot"] = next(
            (
                {"node_id": node["id"], "index": i, "current": {key: node[key] for key in NODE_CONTENT}}
                for i, node in enumerate(nodes, 1)
                if node["id"] == str(volume.target_node_id)
            ),
            None,
        )
        return volume, pick(book.concept, settings_of(book)["playbook"]), blocks


def _unit_brief(u: dict[str, Any]) -> dict[str, Any]:
    keys = ("index", "title", "chapter_count", "climax", "tropes", "resolution")
    return {k: u.get(k) for k in keys}


def _issue_line(issue: dict[str, Any]) -> str:
    where = f"第{issue['unit']}单元：" if issue.get("unit") else ""
    return f"[{ASPECT_NAMES.get(issue.get('aspect', ''), '其他')}] {where}{issue['problem']}——{issue['suggestion']}"


def _serious(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in issues if i.get("severity") in ("high", "medium")]


async def plan_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """拆卷纲第一步：主编先想 2-3 个不同方向，接下来每个方向并行各拆一份完整卷纲。"""
    if state.get("feedback"):
        return {}  # 旧版检查点：作者意见交给 revise_volume 处理
    d = runtime.context
    await d.check_cancel()
    volume, _, blocks = await _volume_context(d, state["volume_id"])
    index = volume.index
    count = (await live_settings(d))["pitches"]
    if count == 1:
        return {
            "directions": [{"name": "按卷纲卡片拆", "idea": "按本卷卡片拆出一份完整方案。", "difference": ""}],
            "pitches": Overwrite([]),
            "chosen_pitch": 0,
            "merge_note": "",
            "volume_draft": {},
            "volume_fix": "",
            "open_issues": [],
        }
    blocks["requirements"] += f"\n\n本轮按设置给出 {count} 个不同方向，每个方向分别拆一份卷纲。"
    await d.emit.status("chief", f"主编正在为第{index}卷想 {count} 个不同的拆法…")
    result = await editorial.volume_directions(d.llm, blocks, purpose=f"写作·第{index}卷比稿方向")
    directions = [x.model_dump() for x in result.directions if x.name.strip() or x.idea.strip()][:count]
    if not directions:
        directions = [{"name": "贴着卡片拆", "idea": "按本卷卡片稳扎稳打地拆。", "difference": ""}]
    while len(directions) < count:
        directions.append(
            {
                "name": f"补充方向 {len(directions) + 1}",
                "idea": "从不同冲突与节奏切入，提出有区分度的完整方案。",
                "difference": "与已有方案拉开差异。",
            }
        )
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"第{index}卷想了 {len(directions)} 个方向，各拆一份来比稿",
        {"type": "volume_directions", "data": {"volume": index, "directions": directions}},
    )
    return {
        "directions": directions,
        "pitches": Overwrite([]),
        "chosen_pitch": 0,
        "merge_note": "",
        "volume_draft": {},
        "volume_fix": "",
        "open_issues": [],
    }


def route_planned(state: WriteState) -> list[Send] | str:
    if state.get("feedback"):
        return "revise_volume"
    return [
        Send("draft_pitch", {"volume_id": state["volume_id"], "pitch": i, "direction": direction})
        for i, direction in enumerate(state.get("directions") or [], start=1)
    ]


async def draft_pitch_node(task: dict, runtime: Runtime[GraphDeps]) -> dict:
    """按一个方向拆一份完整卷纲。几份方案并行起草，结果汇总到 pitches。"""
    d = runtime.context
    await d.check_cancel()
    pitch, direction = task["pitch"], task["direction"]
    volume, _, blocks = await _volume_context(d, task["volume_id"])
    index, name = volume.index, direction.get("name", "")
    await d.emit.status("chief", f"主编正在按「{name}」拆第{index}卷（方案{pitch}）…")
    result = await editorial.plan_volume(
        d.llm, {**blocks, "direction": format_direction(direction)}, {}, "", purpose=f"写作·第{index}卷方案{pitch}"
    )
    plan = result.model_dump(exclude={"remark"})
    plan["_target_snapshot"] = blocks.get("_target_snapshot")
    plan["units"] = fit_chapter_counts(plan["units"], volume.chapter_count)
    await d.emit.artifact(
        "chief",
        f"方案{pitch}「{name}」：{len(plan['units'])} 个剧情单元",
        {
            "type": "volume_pitch",
            "data": {
                "volume": index,
                "pitch": pitch,
                "name": name,
                "idea": direction.get("idea", ""),
                "remark": result.remark,
                "units": [_unit_brief(u) for u in plan["units"]],
            },
        },
    )
    return {"pitches": [{"pitch": pitch, "direction": direction, "plan": plan}]}


async def judge_pitches_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """审稿比稿：按爽点、线索交织、反派智商、新意打分，选出最好的一份。"""
    d = runtime.context
    await d.check_cancel()
    pitches = sorted(state.get("pitches") or [], key=lambda p: p["pitch"])
    if not pitches:
        raise LLMError("主编没有拆出卷纲方案")
    if len(pitches) == 1:
        return {"volume_draft": pitches[0]["plan"], "chosen_pitch": pitches[0]["pitch"], "merge_note": ""}
    volume, playbook, blocks = await _volume_context(d, state["volume_id"])
    index = volume.index
    await d.emit.status("reviewer", f"审稿正在给第{index}卷的 {len(pitches)} 份方案比稿…")
    result = await editorial.judge_pitches(
        d.llm, {**blocks, "playbook": playbook.text("review")}, pitches, purpose=f"写作·第{index}卷比稿"
    )
    scores = {s.pitch: s for s in result.scores}
    known = [p["pitch"] for p in pitches]
    winner = (
        result.winner if result.winner in known else max(known, key=lambda k: scores[k].total if k in scores else 0)
    )
    chosen = next(p for p in pitches if p["pitch"] == winner)
    merge = result.merge.strip()
    rows = []
    for p in pitches:
        score = scores.get(p["pitch"])
        row = {"pitch": p["pitch"], "name": p["direction"].get("name", "")}
        if score is not None:
            row.update(score.model_dump(exclude={"pitch"}), total=score.total)
        rows.append(row)
    await d.emit.say("reviewer", result.remark)
    await d.emit.artifact(
        "reviewer",
        f"比稿结果：方案{winner}「{chosen['direction'].get('name', '')}」胜出"
        + ("，再融合其他方案的长处" if merge else ""),
        {"type": "pitch_scores", "data": {"volume": index, "winner": winner, "merge": merge, "scores": rows}},
    )
    return {"volume_draft": chosen["plan"], "chosen_pitch": winner, "merge_note": merge}


async def route_judged(state: WriteState, runtime: Runtime[GraphDeps]) -> str:
    if state.get("merge_note"):
        return "merge_pitches"
    return await route_volume_audit(state, runtime)


async def route_volume_audit(state: WriteState, runtime: Runtime[GraphDeps]) -> str:
    return "audit_volume" if (await live_settings(runtime.context))["volume_audit"] else "save_volume"


async def merge_pitches_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """主编按审稿的建议，把其他方案里更好的单元或设计融进选中的方案。"""
    d = runtime.context
    await d.check_cancel()
    chosen = state.get("chosen_pitch", 0)
    others = [p for p in sorted(state.get("pitches") or [], key=lambda p: p["pitch"]) if p["pitch"] != chosen]
    volume, _, blocks = await _volume_context(d, state["volume_id"])
    index = volume.index
    await d.emit.status("chief", f"主编正在把其他方案的长处融进方案{chosen}…")
    instructions = (
        f"审稿比稿后的融合建议：{state.get('merge_note', '')}\n\n可以借鉴的其他方案：\n{format_pitches(others)}"
    )
    result = await editorial.plan_volume(
        d.llm, blocks, state.get("volume_draft") or {}, instructions, purpose=f"写作·第{index}卷融合方案"
    )
    plan = result.model_dump(exclude={"remark"})
    plan["_target_snapshot"] = blocks.get("_target_snapshot")
    plan["units"] = fit_chapter_counts(plan["units"], volume.chapter_count)
    await d.emit.say("chief", result.remark)
    return {"volume_draft": plan, "merge_note": ""}


async def audit_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """五项专项审稿：程序问题必须修改，参考提示交给审稿判断。"""
    d = runtime.context
    await d.check_cancel()
    plan = state.get("volume_draft") or {}
    volume, playbook, blocks = await _volume_context(d, state["volume_id"])
    index = volume.index
    async with d.sessionmaker() as session:
        prior = await prior_units(session, d.book_id, index)
        ledger = await setup_store.load_ledger(session, d.book_id)
        first = await writing_store.next_chapter_index(session, d.book_id)
    units = plan.get("units") or []
    found = [
        *repetition_issues(playbook, prior, units),
        *schedule_issues(
            units, plan.get("new_foreshadowings") or [], [f for f in ledger if f["kind"] == "伏笔"], index
        ),
        *expectation_issues(units, plan.get("new_expectations") or [], ledger, index, first),
    ]
    await d.emit.status("reviewer", f"审稿正在给第{index}卷做专项审稿：反派智商、爽点节奏、伏笔排期、套路重复、期待感…")
    result = await editorial.audit_volume(
        d.llm,
        {**blocks, "playbook": playbook.text("review")},
        plan,
        [("问题：" if i.get("severity") in ("high", "medium") else "提示：") + _issue_line(i) for i in found],
        purpose=f"写作·第{index}卷专项审稿",
    )
    reviewed = [i.model_dump() for i in result.issues]
    serious = _serious(found) + (_serious(reviewed) if result.verdict == "revise" else [])
    checks = [c.model_dump() for c in result.checks]
    for check in checks:
        # 程序查出了问题的那一项不能算过关
        if any(i["aspect"] == check["aspect"] for i in _serious(found)):
            check["ok"] = False
    await d.emit.say("reviewer", result.remark)
    await d.emit.artifact(
        "reviewer",
        f"第{index}卷专项审稿：" + (f"{len(serious)} 个问题要改" if serious else "通过"),
        {
            "type": "volume_audit",
            "data": {
                "volume": index,
                "verdict": "revise" if serious else "pass",
                "checks": checks,
                "issues": [*found, *reviewed],
            },
        },
    )
    if not serious:
        return {"volume_fix": ""}
    await d.emit.status("chief", f"主编采纳专项审稿的意见，先把第{index}卷卷纲改一轮。")
    return {"volume_fix": "\n".join(f"- {_issue_line(i)}" for i in serious)}


def route_audited(state: WriteState) -> str:
    return "revise_volume" if state.get("volume_fix") else "save_volume"


async def revise_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """修改卷纲：按专项审稿的意见自动改一轮，或者按作者拍板时提的意见改。"""
    d = runtime.context
    await d.check_cancel()
    feedback = state.get("feedback", "")
    async with d.sessionmaker() as session:
        removed = await deleted_texts(session, d.book_id)
    removed_feedback = any(text in feedback for text in removed)
    if removed_feedback:
        feedback = ""
    volume, _, blocks = await _volume_context(d, state["volume_id"])
    index = volume.index
    if feedback or removed_feedback:
        # 作者可能在网页上改过卷纲，以数据库里的当前版本为准
        async with d.sessionmaker() as session:
            ledger = await setup_store.load_ledger(session, d.book_id)
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
                "new_foreshadowings": [
                    f for f in ledger if f["kind"] == "伏笔" and f["plant_volume"] == index and f["span"] != "长"
                ],
                "new_expectations": [
                    f for f in ledger if f["kind"] == "期待" and f["plant_volume"] == index and f["span"] != "长"
                ],
            }
        if removed_feedback:
            return {"volume_draft": current, "feedback": "", "volume_fix": "", "node_update": None}
        await d.emit.status("chief", f"主编正在按你的意见修改第{index}卷卷纲…")
        instructions, purpose = feedback, f"写作·第{index}卷按作者意见修改"
    else:
        current = state.get("volume_draft") or {}
        await d.emit.status("chief", f"主编正在按专项审稿的意见修改第{index}卷卷纲…")
        instructions, purpose = state.get("volume_fix", ""), f"写作·第{index}卷按专项审稿修改"
    result = await editorial.plan_volume(d.llm, blocks, current, instructions, purpose=purpose)
    await d.emit.say("chief", result.remark)
    return {
        "volume_draft": {**result.model_dump(exclude={"remark"}), "_target_snapshot": blocks.get("_target_snapshot")},
        "volume_fix": "",
        "node_update": None,
    }


async def _node_proposal(
    session: AsyncSession, book_id: uuid.UUID, volume: Volume, plan: dict
) -> tuple[dict | None, str]:
    conflict = str(plan.get("node_conflict") or "").strip()
    proposed = plan.get("node_update")
    if not proposed:
        return None, conflict
    node = await session.get(StoryNode, volume.target_node_id) if volume.target_node_id else None
    if node is not None and node.status == "pinned":
        return None, conflict + "（主编提议调整铁钉节点，已忽略）"
    snapshot = plan.get("_target_snapshot") or {}
    if (
        node is None
        or node.book_id != book_id
        or node.status != "pencil"
        or snapshot.get("node_id") != str(node.id)
        or snapshot.get("current") != {key: getattr(node, key) for key in NODE_CONTENT}
    ):
        return None, conflict + "（目标节点已变化或缺少原始快照，节点调整已忽略，请重新拆卷纲）"
    return {
        **snapshot,
        "proposed": {key: str(proposed.get(key) or "") for key in NODE_CONTENT},
        "reason": str(proposed.get("reason") or ""),
    }, conflict


async def _apply_node_proposal(session: AsyncSession, book_id: uuid.UUID, volume: Volume, proposal: dict) -> str:
    """批准时再次加锁核对作者当前版本，绝不将等待期间的手改、钉死或换目标覆盖掉。"""
    try:
        node_id = uuid.UUID(proposal.get("node_id", ""))
    except (ValueError, TypeError, AttributeError):
        return "节点调整未应用：原提议的节点已失效，请重新拆卷纲。"
    node = await session.scalar(select(StoryNode).where(StoryNode.id == node_id).with_for_update())
    if (
        node is None
        or node.book_id != book_id
        or volume.target_node_id != node_id
        or node.status != "pencil"
        or proposal.get("current") != {key: getattr(node, key) for key in NODE_CONTENT}
    ):
        return "节点调整未应用：节点或本卷目标已由作者修改，已保留作者当前的版本。"
    proposed = proposal.get("proposed") or {}
    if not all(isinstance(proposed.get(key), str) and proposed[key].strip() for key in NODE_CONTENT):
        return "节点调整未应用：提议内容不完整，已保留原节点。"
    for key in NODE_CONTENT:
        setattr(node, key, proposed[key])
    node.origin = "ai"
    node.updated_by_volume = volume.index
    return f"暂定节点「{node.title}」按这一卷的写法调整了"


async def save_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """卷纲定下来：对齐章数，给新伏笔编号并写进对应单元，存库，然后等作者拍板。"""
    d = runtime.context
    feedback = state.get("feedback", "")
    plan = state.get("volume_draft") or {}
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        volume = await session.get(Volume, uuid.UUID(state["volume_id"]))
        index = volume.index
        ledger = await setup_store.load_ledger(session, d.book_id)
        units = fit_chapter_counts(plan.get("units") or [], volume.chapter_count)
        units = clean_reveals(units, await setup_store.load_secrets(session, d.book_id))
        fresh = setup_store.assign_seqs(
            [
                *({**item, "kind": "伏笔"} for item in plan.get("new_foreshadowings") or []),
                *({"span": "中", **item, "kind": "期待"} for item in plan.get("new_expectations") or []),
            ],
            ledger,
        )
        units, fresh = attach_new_foreshadowings(units, fresh, index)
        await writing_store.save_volume_plan(
            session,
            d.book_id,
            volume,
            units,
            fresh,
            replace_new=bool(feedback),
            replace_expectations="new_expectations" in plan,
        )
        # 改完还剩的问题（程序能查的那部分）交给作者拍板时一并看到
        prior = await prior_units(session, d.book_id, index)
        remaining = [
            *repetition_issues(pick(book.concept, settings_of(book)["playbook"]), prior, units),
            *schedule_issues(
                units, [], [f for f in await setup_store.load_ledger(session, d.book_id) if f["kind"] == "伏笔"], index
            ),
            *expectation_issues(
                units,
                [],
                await setup_store.load_ledger(session, d.book_id),
                index,
                await writing_store.next_chapter_index(session, d.book_id),
            ),
        ]
        proposal, conflict = await _node_proposal(session, d.book_id, volume, plan)
        await session.commit()
    if conflict:
        await d.emit.say("chief", f"节点冲突：{conflict}")
    await d.emit.artifact(
        "chief",
        f"第{index}卷拆成 {len(units)} 个剧情单元，新埋伏笔 {sum(item['kind'] == '伏笔' for item in fresh)} 条、新立期待 {sum(item['kind'] == '期待' for item in fresh)} 条",
        {
            "type": "volume_plan",
            "data": {
                "volume": index,
                "units": units,
                "new_foreshadowings": [item for item in fresh if item["kind"] == "伏笔"],
                "new_expectations": [item for item in fresh if item["kind"] == "期待"],
            },
        },
    )
    return {
        "feedback": "",
        "directions": [],
        "pitches": Overwrite([]),
        "volume_draft": {},
        "node_update": proposal,
        "open_issues": [
            *[_issue_line(i) for i in _serious(remaining)],
            *(
                [f"节点调整：{proposal['current']['title']} → {proposal['proposed']['title']}；{proposal['reason']}"]
                if proposal
                else []
            ),
            *([f"节点冲突：{conflict}"] if conflict else []),
        ],
    }


async def volume_gate_node(
    state: WriteState, runtime: Runtime[GraphDeps]
) -> Command[Literal["revise_volume", "dispatch"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    index = state.get("volume_index", 0)
    pending: dict[str, Any] = {"kind": "volume_review", "volume": index, "title": state.get("volume_title", "")}
    if state.get("open_issues"):
        pending["issues"] = state["open_issues"]
    if state.get("node_update"):
        pending["node_update"] = state["node_update"]
    d = runtime.context
    automatic = not (await live_settings(d))["volume_approval"]
    decision = {"action": "approve"} if automatic else interrupt(pending)
    feedback = str(decision.get("feedback", "")).strip()
    async with d.sessionmaker() as session:
        if decision.get("action") == "approve":
            volume = await session.scalar(
                select(Volume).where(Volume.id == uuid.UUID(state["volume_id"])).with_for_update()
            )
            node_message = ""
            if volume is not None and volume.status == "detailed":
                if state.get("node_update"):
                    node_message = await _apply_node_proposal(session, d.book_id, volume, state["node_update"])
                volume.status = "approved"
            await session.commit()
            if node_message:
                await d.emit.say("system" if automatic else "chief", node_message, kind="decision")
            await d.emit.say(
                "system",
                f"第{index}卷卷纲按设置自动批准，开写。" if automatic else f"作者批准了第{index}卷卷纲，开写。",
                kind="decision",
            )
            return Command(goto="dispatch", update={"open_issues": [], "node_update": None})
        # 卷纲的修改意见也要记住，免得以后的规划又改回去
        if not decision.get("requirement_saved"):
            await _requirement(session, d.book_id, feedback, f"volume:{index}")
        await session.commit()
    return Command(
        goto="revise_volume",
        update={"feedback": feedback or "请整体再打磨一遍。", "node_update": None, "open_issues": []},
    )


def _chapter_plan_issues(
    plans: list[dict], first: int, key: str, prior: list[dict], ledger: list[dict], secrets: list[dict]
) -> list[str]:
    indexed = [{**plan, "index": first + i} for i, plan in enumerate(plans)]
    issues = check_chapter_plan(indexed, key, prior)
    actions = [a for plan in plans for a in plan.get("foreshadow_actions") or []]
    issues.extend(overdue_expectations(ledger, first, first + len(plans) - 1, actions))
    known = {foreshadow_code(item) for item in ledger}
    secret_refs = {f"S{item['seq']}" for item in secrets}
    for i, plan in enumerate(plans, first):
        for field, allowed, label in (("foreshadow_actions", known, "伏笔或期待"), ("reveals", secret_refs, "秘密")):
            clean = []
            for action in plan.get(field) or []:
                ref = str(action.get("ref") or "").strip().upper()
                if ref in allowed:
                    clean.append({**action, "ref": ref})
                else:
                    issues.append(f"第 {i} 章引用了不存在的{label}编号「{ref}」，已丢弃，请使用表内编号重新安排")
            plan[field] = clean
    return issues


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
        blocks["revision"] = ""
        key = pick(book.concept, settings_of(book)["playbook"]).key
        history = list(
            (
                await session.scalars(
                    select(Chapter)
                    .where(Chapter.book_id == d.book_id, Chapter.index < first)
                    .order_by(Chapter.index.desc())
                    .limit(5)
                )
            ).all()
        )
        prior = [{**(chapter.outline or {}), "index": chapter.index} for chapter in reversed(history)]
        ledger = await setup_store.load_ledger(session, d.book_id)
        secrets = await setup_store.load_secrets(session, d.book_id)
        label = f"第{volume.index}卷第{unit.index}单元「{unit.title}」"
    await d.emit.status("chief", f"主编正在给{label}出章纲…")
    for attempt in range(2):
        result = await editorial.plan_chapters(d.llm, blocks)
        plans = [c.model_dump() for c in result.chapters if c.title.strip() or c.goal.strip()]
        if not plans:
            raise LLMError("主编没有给出章纲")
        issues = _chapter_plan_issues(plans, first, key, prior, ledger, secrets)
        if not issues or attempt:
            break
        blocks["revision"] = format_revision(
            "当前章纲",
            "\n\n".join(f"第 {first + i} 章\n{format_chapter_outline(plan)}" for i, plan in enumerate(plans)),
            "\n".join(f"- {issue}" for issue in issues),
        )
        await d.emit.status("chief", f"{label}章纲有 {len(issues)} 处问题，主编按检查结果重出一次…")
        await d.check_cancel()
    async with d.sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(state["unit_id"]))
        unit.plan_issues = issues
        rows = await writing_store.create_chapters(session, d.book_id, unit, plans)
        await session.commit()
        listing = [
            {
                "index": r.index,
                "title": r.title,
                "hook": r.outline.get("hook", ""),
                "emotion": r.outline.get("emotion"),
                "mood": r.outline.get("mood"),
                "reveals": r.outline.get("reveals", []),
            }
            for r in rows
        ]
    if issues:
        await d.emit.status("chief", f"第 {unit.index} 单元章纲还有 {len(issues)} 处节奏问题，已记在卷页")
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"{label}章纲：第{listing[0]['index']}-{listing[-1]['index']}章",
        {"type": "chapter_plan", "data": {"unit": label, "chapters": listing}},
    )
    return {}


HEADING = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零〇两]+章[^\n]*|#+[^\n]*)\n+")
ENDING = re.compile(r"\n*[（(]?\s*(本章完|未完待续|本章结束)[^\n]*$")
# 总结式结尾的常见说法：只在最后一段里找
SUMMARY_ENDING = re.compile(
    r"一切(?:才)?(?:刚刚)?(?:开始|拉开序幕)"
    r"|新的(?:征程|篇章|旅程|开始)"
    r"|(?:拉开|揭开)了?(?:序幕|帷幕)"
    r"|命运的齿轮"
    r"|等待着?(?:他|她|他们|她们|我)?的(?:将是|会是)"
    r"|未来(?:的路)?(?:会|将)(?:怎样|如何)"
    r"|前方的路(?:还很长|漫漫)|路还很长"
    r"|从此以后"
    r"|总而言之|总之，"
    r"|回想(?:起)?(?:今天|这一天|这一切)"
    r"|(?:暗暗|默默|在心里)(?:发誓|下定决心)"
    r"|暴风雨(?:前的宁静|即将来临)"
)
SUMMARY_SCAN = 160
SENTENCE_END = re.compile(r"[。！？!?…」”』）)]$")


def clean_text(text: str) -> str:
    """去掉模型偶尔加上的章节标题和「本章完」。"""
    text = HEADING.sub("", text.strip(), count=1)
    return ENDING.sub("", text).strip()


def word_count(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def split_ending(text: str, size: int = 150) -> tuple[str, str]:
    """把正文分成「结尾之前」和「结尾」：从最后往前取 1-3 段，凑够 size 字左右；只有一段时按句子切。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if len(paragraphs) >= 2:
        tail: list[str] = []
        while len(paragraphs) > 1 and len(tail) < 3 and sum(len(p) for p in tail) < size:
            tail.insert(0, paragraphs.pop())
        return "\n\n".join(paragraphs), "\n\n".join(tail)
    sentences = SENTENCE.findall(text.strip())
    tail_sentences: list[str] = []
    while len(sentences) > 1 and sum(len(x) for x in tail_sentences) < size:
        tail_sentences.insert(0, sentences.pop())
    return "".join(sentences).strip(), "".join(tail_sentences).strip()


def summary_ending(text: str) -> str:
    """结尾是不是总结式的：最后一段里出现「一切才刚刚开始」这类说法时，返回那句说法。"""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return ""
    match = SUMMARY_ENDING.search(paragraphs[-1][-SUMMARY_SCAN:])
    return match.group(0) if match else ""


def polish_step(text: str, target: int, extensions: int, ending_fixed: bool) -> str:
    """写完之后还要做什么：字数明显不够就接着写，结尾写成总结就改结尾，都没问题就送审。"""
    if word_count(text) < target * SHORT_RATIO and extensions < MAX_EXTENSIONS:
        return "extend"
    if not ending_fixed and summary_ending(text):
        return "fix_ending"
    return ""


def join_text(text: str, addition: str) -> str:
    addition = addition.strip()
    if not addition:
        return text
    head = text.rstrip()
    return head + ("\n\n" if SENTENCE_END.search(head) else "") + addition


async def _stream_draft(
    d: GraphDeps, chunks: AsyncIterator[str], *, index: int, title: str, mode: str, prefix: str = ""
) -> str:
    """把写手的流式输出拼起来，同时把写到哪了推给网页（只走 Redis，不进数据库）。"""
    parts: list[str] = []
    size = pushed = 0
    last = time.monotonic()
    async for chunk in chunks:
        parts.append(chunk)
        size += len(chunk)
        now = time.monotonic()
        if size - pushed >= DRAFT_PUSH_CHARS or (now - last >= DRAFT_PUSH_S and size > pushed):
            await d.emit.draft(index, title, mode, prefix + "".join(parts))
            pushed, last = size, now
    text = "".join(parts)
    await d.emit.draft(index, title, mode, prefix + text, done=True)
    return text


def _revision(state: WriteState) -> str:
    """给写手的修改要求：作者对这一章的意见（重写已定稿章节时）始终在最前面。"""
    revision, note = state.get("revision", ""), state.get("author_note", "").strip()
    if note and note not in revision:
        revision = f"- [作者] {note}" + (f"\n{revision}" if revision else "")
    return revision


async def prepare_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """写之前设定师读章纲，从设定库和前文里挑出这一章用得上的资料。备过的（续跑、重写）不再备。"""
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        if chapter.materials:
            return {}
        blocks = await material_blocks(session, await session.get(Book, d.book_id), chapter)
        index, title = chapter.index, chapter.title
    await d.emit.status("lorekeeper", f"设定师正在为第{index}章备资料…")
    result = await editorial.prepare_chapter(d.llm, blocks)
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        materials = await pick_materials(session, d.book_id, chapter.index, result.model_dump())
        chapter.materials = materials
        await session.commit()
    counts = f"人物 {len(materials['characters'])} 位、设定 {len(materials['world'])} 条、前文 {len(materials['chapters'])} 章"
    await d.emit.artifact(
        "lorekeeper",
        f"第{index}章《{title}》的资料备好了：{counts}",
        {"type": "chapter_materials", "data": {"index": index, "title": title, **materials}},
    )
    return {}


async def write_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    revision = _revision(state)
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
        index, title, target = chapter.index, chapter.title, chapter_words(book)
    await d.emit.status("writer", f"写手正在{'重写' if rewriting else '写'}第{index}章《{title}》…")
    raw = await _stream_draft(d, editorial.write_chapter(d.llm, blocks), index=index, title=title, mode="write")
    text = clean_text(raw)
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
    return {
        "review": {},
        "consistency": {},
        "extensions": 0,
        "ending_fixed": False,
        "polish": polish_step(text, target, 0, False),
    }


def route_drafted(state: WriteState) -> str | list[str]:
    """写完（或续写、改结尾之后）：还要补字或改结尾就去做，否则审稿与设定检查并行。"""
    return state.get("polish") or ["review", "check"]


async def _load_draft(d: GraphDeps, chapter_id: str) -> tuple[Chapter, dict[str, str], int]:
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(chapter_id))
        book = await session.get(Book, d.book_id)
        return chapter, await chapter_blocks(session, book, chapter), chapter_words(book)


async def _save_text(d: GraphDeps, chapter_id: str, text: str) -> None:
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(chapter_id))
        chapter.content = text
        chapter.word_count = word_count(text)
        await session.commit()


async def extend_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """字数明显不够：写手从最后一句接着写，把章纲里没写足的场景补上。"""
    d = runtime.context
    await d.check_cancel()
    chapter, blocks, target = await _load_draft(d, state["chapter_id"])
    text, index, title = chapter.content, chapter.index, chapter.title
    words = word_count(text)
    await d.emit.status("writer", f"第{index}章只写了 {words} 字（目标约 {target} 字），写手接着往下写…")
    raw = await _stream_draft(
        d,
        editorial.extend_chapter(d.llm, blocks, words, max(300, target - words)),
        index=index,
        title=title,
        mode="extend",
        prefix=text.rstrip() + "\n\n",
    )
    new_text = join_text(text, clean_text(raw))
    await _save_text(d, state["chapter_id"], new_text)
    extensions = state.get("extensions", 0) + 1
    await d.emit.artifact(
        "writer",
        f"第{index}章续写到 {word_count(new_text)} 字",
        {
            "type": "chapter_polish",
            "data": {
                "index": index,
                "title": title,
                "action": "extend",
                "before": words,
                "after": word_count(new_text),
            },
        },
    )
    return {
        "extensions": extensions,
        "polish": polish_step(new_text, target, extensions, state.get("ending_fixed", False)),
    }


async def fix_ending_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """结尾写成了总结：写手只重写结尾，停在章纲的钩子上。"""
    d = runtime.context
    await d.check_cancel()
    chapter, blocks, target = await _load_draft(d, state["chapter_id"])
    text, index, title = chapter.content, chapter.index, chapter.title
    body, ending = split_ending(text)
    reason = summary_ending(text)
    await d.emit.status("writer", f"第{index}章的结尾写成了总结（「{reason}」），写手改写结尾…")
    raw = await _stream_draft(
        d,
        editorial.rewrite_ending(
            d.llm, blocks, body[-ENDING_CONTEXT:], ending, reason, (chapter.outline or {}).get("hook", "")
        ),
        index=index,
        title=title,
        mode="ending",
        prefix=body.rstrip() + "\n\n",
    )
    new_ending = clean_text(raw)
    new_text = join_text(body, new_ending) if new_ending else text
    await _save_text(d, state["chapter_id"], new_text)
    await d.emit.artifact(
        "writer",
        f"第{index}章改写了结尾",
        {
            "type": "chapter_polish",
            "data": {"index": index, "title": title, "action": "ending", "reason": reason, "after": new_ending[-160:]},
        },
    )
    return {"ending_fixed": True, "polish": polish_step(new_text, target, state.get("extensions", 0), True)}


async def review_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        blocks = await chapter_blocks(session, await session.get(Book, d.book_id), chapter)
    await d.emit.status("reviewer", f"审稿正在读第{state.get('chapter_index')}章…")
    blocks["strictness"] = strictness_text((await live_settings(d))["review_strictness"])
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


def blocking_issues(review: dict, consistency: dict, strictness: str = "standard") -> list[str]:
    out = []
    review_levels = ("high",) if strictness == "lenient" else ("high", "medium")
    consistency_levels = ("high", "medium") if strictness == "strict" else ("high",)
    if strictness != "standard" or review.get("verdict") == "revise":
        out += [
            f"[审稿] {i['problem']}——{i['suggestion']}"
            for i in review.get("issues", [])
            if i.get("severity") in review_levels
        ]
    out += [
        f"[设定] {i['problem']}——{i['suggestion']}"
        for i in consistency.get("issues", [])
        if i.get("severity") in consistency_levels
    ]
    return out


async def judge_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    review, consistency = state.get("review") or {}, state.get("consistency") or {}
    settings = await live_settings(d)
    max_rewrites = settings["max_rewrites"]
    blocking = blocking_issues(review, consistency, settings["review_strictness"])
    attempt = state.get("attempt", 0)
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        chapter.review = {"review": review, "consistency": consistency}
        if blocking and attempt < max_rewrites:
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
    if attempt < max_rewrites:
        await d.emit.status("chief", f"主编：第{state.get('chapter_index')}章退回重写（第 {attempt + 1} 次）。")
        revision = "\n".join(f"- {line}" for line in blocking)
        return {"step": "write", "attempt": attempt + 1, "revision": revision, "blocking": blocking}
    await d.emit.status("chief", f"第{state.get('chapter_index')}章重写 {max_rewrites} 次仍未通过，请作者定夺。")
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
    done = {
        "written": state.get("written", 0) + 1,
        "attempt": 0,
        "revision": "",
        "review": {},
        "consistency": {},
        "polish": "",
    }
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


async def _unit_recap(d: GraphDeps, unit_id: str) -> None:
    """设定师写单元回顾（已经写过就跳过）。"""
    async with d.sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(unit_id))
        if unit is None or unit.recap.strip():
            return
        blocks = await unit_recap_blocks(session, await session.get(Book, d.book_id), unit)
        label = f"第{blocks['volume_index']}卷第{unit.index}单元「{unit.title}」"
        fallback = unit.outcome
    await d.emit.status("lorekeeper", f"{label}写完了，设定师正在写单元回顾…")
    result = await editorial.recap_unit(d.llm, blocks)
    recap = result.recap.strip() or f"（设定师没有写出回顾，按卷纲结果）{fallback}"
    async with d.sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(unit_id))
        unit.recap = recap
        await session.commit()
    await d.emit.artifact(
        "lorekeeper",
        f"{label}单元回顾",
        {
            "type": "unit_recap",
            "data": {
                "volume": int(blocks["volume_index"]),
                "unit": int(blocks["unit_index"]),
                "title": blocks["unit_title"],
                "recap": recap,
            },
        },
    )


async def _volume_recap(d: GraphDeps, volume_id: str) -> None:
    """设定师写卷回顾（已经写过就跳过）。"""
    async with d.sessionmaker() as session:
        volume = await session.get(Volume, uuid.UUID(volume_id))
        if volume is None or volume.recap.strip():
            return
        blocks = await volume_recap_blocks(session, await session.get(Book, d.book_id), volume)
        index, title, fallback = volume.index, volume.title, volume.summary
    await d.emit.status("lorekeeper", f"第{index}卷写完了，设定师正在写卷回顾…")
    result = await editorial.recap_volume(d.llm, blocks)
    recap = result.recap.strip() or f"（设定师没有写出回顾，按卷纲概要）{fallback}"
    async with d.sessionmaker() as session:
        volume = await session.get(Volume, uuid.UUID(volume_id))
        volume.recap = recap
        await session.commit()
    if result.remark:
        await d.emit.say("lorekeeper", result.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"第{index}卷《{title}》卷回顾",
        {"type": "volume_recap", "data": {"volume": index, "title": title, "recap": recap}},
    )


async def recap_unit_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    await runtime.context.check_cancel()
    await _unit_recap(runtime.context, state["unit_id"])
    return {}


async def recap_volume_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    await runtime.context.check_cancel()
    await _volume_recap(runtime.context, state["volume_id"])
    return {}


async def trial_gate_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    d = runtime.context
    if not (await live_settings(d))["trial_read"]:
        return {}
    decision = interrupt({"kind": "trial_read", "chapters": TRIAL_READ_AFTER})
    feedback = str(decision.get("feedback", "")).strip()
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        book.trial_read_done = True
        if feedback and not decision.get("requirement_saved"):
            await _requirement(session, d.book_id, feedback, "trial")
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


# ---------- 作者重写已定稿的章节 ----------


def rewrite_initial_state(params: dict) -> WriteState:
    return {
        "until": "count",
        "target": 1,
        "written": 0,
        "notes_seen": 0,
        "chapter_id": params["chapter_id"],
        "chapter_index": int(params.get("index") or 0),
        "chapter_title": params.get("title", ""),
        "unit_id": params.get("unit_id") or "",
        "volume_id": params.get("volume_id") or "",
        "attempt": 0,
        "revision": "",
        "feedback": "",
        "author_note": str(params.get("feedback", "")).strip(),
    }


async def reopen_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """撤销这一章原来记进设定库、伏笔期待与信息差表的变化；续跑时已经重开过就跳过。"""
    d = runtime.context
    await d.check_cancel()
    async with d.sessionmaker() as session:
        chapter = await session.get(Chapter, uuid.UUID(state["chapter_id"]))
        if chapter.status != "final":
            return {}
        later = await writing_store.later_finals(session, d.book_id, chapter.index)
        changes = await writing_store.reopen_chapter(session, d.book_id, chapter)
        await session.commit()
        index = chapter.index
    if any(changes.values()):
        undone = f"人物状态 {changes['characters']} 处、伏笔与期待进展 {changes['foreshadowings']} 条" + (
            f"、新人物 {changes['removed']} 位" if changes["removed"] else ""
        )
        if changes.get("secrets"):
            undone += f"、信息差 {changes['secrets']} 条"
        if changes.get("removed_secrets"):
            undone += f"、新秘密 {changes['removed_secrets']} 条"
        note = f"设定师先撤掉了第{index}章原来记进设定库的变化（{undone}），重写后重新提取。"
    else:
        note = f"第{index}章原来没有改动设定库里还作数的内容，直接重写，写完重新提取。"
    await d.emit.status("lorekeeper", note)
    if later:
        await d.emit.say(
            "chief",
            f"提醒一下：第{index}章后面已经定稿了 {later} 章，这次只重写第{index}章，后面的章节不会跟着改，"
            "改动大的话后文可能接不上，需要的话再逐章重写。",
        )
    return {}


async def wrap_rewrite_node(state: WriteState, runtime: Runtime[GraphDeps]) -> dict:
    """重写定稿后：所在单元、卷已经写完的，重新写回顾。"""
    d = runtime.context
    if state.get("unit_id"):
        async with d.sessionmaker() as session:
            unit = await session.get(PlotUnit, uuid.UUID(state["unit_id"]))
            unit_done = unit is not None and unit.status == "done"
        if unit_done:
            await _unit_recap(d, state["unit_id"])
    if state.get("volume_id"):
        async with d.sessionmaker() as session:
            statuses = (
                (
                    await session.execute(
                        select(PlotUnit.status).where(PlotUnit.volume_id == uuid.UUID(state["volume_id"]))
                    )
                )
                .scalars()
                .all()
            )
        if statuses and all(x == "done" for x in statuses):
            await _volume_recap(d, state["volume_id"])
            async with d.sessionmaker() as session:
                volume = await session.get(Volume, uuid.UUID(state["volume_id"]))
                volume.status = "done"
                await session.commit()
    await d.emit.say("system", f"第{state.get('chapter_index')}章按作者的意见重写好了。", kind="decision")
    return {}


# ---------- 建图 ----------


def _chapter_loop(graph: StateGraph) -> None:
    """一章从备资料到定稿的部分，写书主循环和重写小图共用。"""
    for name, node in (
        ("prepare", prepare_node),
        ("write", write_node),
        ("extend", extend_node),
        ("fix_ending", fix_ending_node),
        ("review", review_node),
        ("check", check_node),
        ("judge", judge_node),
        ("chapter_gate", chapter_gate_node),
        ("finalize", finalize_node),
    ):
        graph.add_node(name, node)
    graph.add_edge("prepare", "write")
    # 写完先查字数和结尾：要补就补、要改就改，然后审稿与设定检查并行，两边都做完再判定
    for source in ("write", "extend", "fix_ending"):
        graph.add_conditional_edges(source, route_drafted, ["extend", "fix_ending", "review", "check"])
    graph.add_edge(["review", "check"], "judge")
    graph.add_conditional_edges(
        "judge", route_judge, {"write": "write", "finalize": "finalize", "chapter_gate": "chapter_gate"}
    )


def build_write_graph() -> StateGraph:
    graph = StateGraph(WriteState, context_schema=GraphDeps)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("plan_volume", plan_volume_node)
    graph.add_node("draft_pitch", draft_pitch_node)
    graph.add_node("judge_pitches", judge_pitches_node)
    graph.add_node("merge_pitches", merge_pitches_node)
    graph.add_node("audit_volume", audit_volume_node)
    graph.add_node("revise_volume", revise_volume_node)
    graph.add_node("save_volume", save_volume_node)
    graph.add_node("volume_gate", volume_gate_node)
    graph.add_node("plan_chapters", plan_chapters_node)
    graph.add_node("recap_unit", recap_unit_node)
    graph.add_node("recap_volume", recap_volume_node)
    graph.add_node("trial_gate", trial_gate_node)
    _chapter_loop(graph)

    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        route_step,
        {
            "plan_volume": "plan_volume",
            "volume_gate": "volume_gate",
            "plan_chapters": "plan_chapters",
            "write": "prepare",
            "recap_unit": "recap_unit",
            "recap_volume": "recap_volume",
            "trial_gate": "trial_gate",
            "done": END,
        },
    )
    for source in ("save_volume", "plan_chapters", "finalize", "trial_gate", "recap_unit", "recap_volume"):
        graph.add_edge(source, "dispatch")
    # 拆卷纲：想方向 → 各方向并行起草 → 比稿 →（融合）→ 专项审稿 →（自动改一轮）→ 存库 → 回到 dispatch 等拍板
    graph.add_conditional_edges("plan_volume", route_planned, ["draft_pitch", "revise_volume"])
    graph.add_edge("draft_pitch", "judge_pitches")
    graph.add_conditional_edges("judge_pitches", route_judged, ["merge_pitches", "audit_volume", "save_volume"])
    graph.add_conditional_edges("merge_pitches", route_volume_audit, ["audit_volume", "save_volume"])
    graph.add_conditional_edges("audit_volume", route_audited, ["revise_volume", "save_volume"])
    graph.add_edge("revise_volume", "save_volume")
    return graph


def build_rewrite_graph() -> StateGraph:
    """作者按自己的意见重写一章已定稿的章节：撤销原来的设定变化 → 备资料 → 重写 → 审稿 → 定稿 → 重写回顾。"""
    graph = StateGraph(WriteState, context_schema=GraphDeps)
    graph.add_node("reopen", reopen_node)
    graph.add_node("wrap_rewrite", wrap_rewrite_node)
    _chapter_loop(graph)
    graph.add_edge(START, "reopen")
    graph.add_edge("reopen", "prepare")
    graph.add_edge("finalize", "wrap_rewrite")
    graph.add_edge("wrap_rewrite", END)
    return graph
