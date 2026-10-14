"""开书流程图。

（可选）主编先问作者几个关键问题 → 主编定概念 → 设定师建设定 → 主编定主线骨架（开篇、结局、关键转折）
→ 主编写分卷大纲 → 审稿挑刺 →（必要时自动修改一轮）→ 存库 → 作者拍板
作者提意见：主编分派修改 → 对应角色修改 → 存库 → 再次拍板；作者批准：定稿。
作者随时可以插话：每做完一步，主编先看有没有新的插话，已完成的部分需要改就先改，之后每一步都按插话来写。
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.agents import editorial
from app.agents.context import format_requirements, planned_chapters
from app.graphs.deps import GraphDeps
from app.models import Book, MeetingMessage, Volume
from app.services import setup_store

ORDER = ["concept", "lore", "spine", "outline"]
TARGET_NAMES = {"concept": "概念", "lore": "世界观与人物", "spine": "主线骨架", "outline": "大纲"}
SYNC_INSTRUCTIONS = {
    "lore": "根据修改后的概念同步调整世界观与人物，保持与新概念一致；不受影响的部分保持原样。",
    "spine": "根据修改后的概念与设定同步检查主线骨架，确保开篇、结局和关键转折与之一致；不受影响的部分保持原样。",
    "outline": "根据修改后的概念、设定与主线骨架同步检查大纲，确保情节、人物与设定一致；不受影响的部分保持原样。",
}

# 篇幅由系统固定提问：它决定全书章数，作者最需要拍板
LENGTH_QUESTION = {
    "question": "这本书打算写多长？",
    "options": [
        "约 30 万字（短篇，100 章左右）",
        "约 100 万字（中长篇，300 章左右）",
        "约 200 万字（标准网文长篇，600 章左右）",
        "300 万字以上（超长篇）",
    ],
    "recommended": 2,
}


class SetupState(TypedDict, total=False):
    idea: str
    style_reference: str
    # 动笔前是否先问作者几个问题
    ask: bool
    questions: list[dict]
    # 作者对提问的回答，以及过程中的插话与修改意见：之后每一步都要落实
    brief: list[str]
    notes: list[str]
    # 已经读过的最后一条插话（会议消息 ID）
    notes_seen: int
    concept: dict
    lore: dict
    spine: dict
    outline: dict
    # 待执行的步骤（concept / lore / spine / outline），依次弹出
    queue: list[str]
    # 本轮各部分的修改要求；为空表示从零起草
    instructions: dict[str, str]
    # draft：首次起草；reviewed：审稿通过；auto_revise：按审稿意见修改；author_revise：按作者意见修改
    phase: str
    auto_revised: bool
    feedback: str
    round: int


def initial_state(idea: str, style_reference: str = "", ask: bool = False) -> SetupState:
    return {
        "idea": idea,
        "style_reference": style_reference,
        "ask": ask,
        "brief": [],
        "notes": [],
        "notes_seen": 0,
        "queue": list(ORDER),
        "instructions": {},
        "phase": "draft",
        "auto_revised": False,
        "round": 0,
    }


def cascade(instructions: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """上游改了，下游要跟着同步：改概念 → 后面全部要检查；改设定 → 主线和大纲；改主线 → 大纲。"""
    targets = {t for t, text in instructions.items() if text.strip()}
    for i, target in enumerate(ORDER):
        if target in targets:
            targets |= set(ORDER[i + 1 :])
    queue = [t for t in ORDER if t in targets]
    merged = {t: instructions.get(t, "").strip() or SYNC_INSTRUCTIONS[t] for t in queue}
    return queue, merged


def merge_plan(
    queue: list[str], instructions: dict[str, str], extra_queue: list[str], extra: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """把新加的修改并进还没做完的计划：步骤按流程顺序去重，同一部分的要求合并。"""
    targets = set(queue) | set(extra_queue)
    merged: dict[str, str] = {}
    for t in ORDER:
        parts = [x.strip() for x in (instructions.get(t, ""), extra.get(t, "")) if x.strip()]
        if parts:
            merged[t] = "\n".join(dict.fromkeys(parts))
    return [t for t in ORDER if t in targets], merged


def requirements(state: SetupState) -> str:
    return format_requirements(state.get("brief") or [], state.get("notes") or [])


def route_start(state: SetupState) -> str:
    return "interview" if state.get("ask") else "intake"


def route_next(state: SetupState) -> str:
    queue = state.get("queue") or []
    if queue:
        return queue[0]
    if state.get("phase") == "draft":
        return "critique"
    return "persist"


def _revising(state: SetupState, target: str) -> tuple[dict, str]:
    """返回 (当前版本, 修改要求)。没有修改要求时视为从零起草。"""
    instruction = (state.get("instructions") or {}).get(target, "")
    current = state.get(target) or {}
    return (current, instruction) if instruction and current else ({}, "")


def _finish(state: SetupState, target: str, value: dict) -> dict:
    """一步做完：存下结果，弹出队列，用掉这一部分的修改要求。"""
    rest = {k: v for k, v in (state.get("instructions") or {}).items() if k != target}
    return {target: value, "queue": (state.get("queue") or [])[1:], "instructions": rest}


async def interview_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    await d.emit.status("chief", "主编动笔前想先问你几个问题…")
    result = await editorial.interview(d.llm, state["idea"], state.get("style_reference", ""))
    questions = [LENGTH_QUESTION]
    for q in result.questions[:5]:
        options = [o.strip() for o in q.options if o.strip()][:4]
        if q.question.strip() and options:
            questions.append(
                {
                    "question": q.question.strip(),
                    "options": options,
                    "recommended": min(q.recommended, len(options) - 1),
                }
            )
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"动笔前想问你的 {len(questions)} 件事", {"type": "questions", "data": questions})
    return {"questions": questions}


async def interview_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    answer = interrupt({"kind": "setup_questions", "questions": state.get("questions") or []})
    brief = [str(line).strip() for line in answer.get("brief") or [] if str(line).strip()]
    d = runtime.context
    await d.emit.status("chief", "收到，按你的意思开工。" if brief else "好，那就都交给编辑部来定。")
    return {"brief": brief}


async def concept_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "concept")
    await d.emit.status("chief", "主编正在修改书的概念…" if instruction else "主编正在构思这本书…")
    result = await editorial.draft_concept(
        d.llm, state["idea"], state.get("style_reference", ""), requirements(state), current, instruction
    )
    concept = result.model_dump(exclude={"remark"})
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"书的概念：《{concept['title']}》", {"type": "concept", "data": concept})
    return _finish(state, "concept", concept)


async def lore_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "lore")
    await d.emit.status("lorekeeper", "设定师正在修改世界观与人物…" if instruction else "设定师正在搭建世界观与人物…")
    result = await editorial.draft_lore(d.llm, state["concept"], requirements(state), current, instruction)
    lore = result.model_dump(exclude={"remark"})
    await d.emit.say("lorekeeper", result.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"世界观 {len(lore['world_entries'])} 条，人物 {len(lore['characters'])} 位",
        {"type": "lore", "data": lore},
    )
    return _finish(state, "lore", lore)


async def spine_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "spine")
    await d.emit.status("chief", "主编正在修改主线骨架…" if instruction else "主编正在定主线：开篇、结局和关键转折…")
    result = await editorial.draft_spine(
        d.llm, state["concept"], state["lore"], requirements(state), current, instruction
    )
    spine = result.model_dump(exclude={"remark"})
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"主线骨架：{len(spine['milestones'])} 个关键转折", {"type": "spine", "data": spine})
    return _finish(state, "spine", spine)


async def outline_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "outline")
    await d.emit.status("chief", "主编正在修改大纲…" if instruction else "主编正在写分卷大纲…")
    result = await editorial.draft_outline(
        d.llm, state["concept"], state["lore"], state.get("spine") or {}, requirements(state), current, instruction
    )
    outline = result.model_dump(exclude={"remark"})
    await d.emit.say("chief", result.remark)
    total = sum(v.get("chapter_count") or 0 for v in outline["volumes"]) or planned_chapters(state["concept"])
    await d.emit.artifact(
        "chief",
        f"全书 {len(outline['volumes'])} 卷"
        + (f"约 {total} 章" if total else "")
        + f"，第一卷 {len(outline['first_volume_units'])} 个剧情单元",
        {"type": "outline", "data": outline},
    )
    return _finish(state, "outline", outline)


async def critique_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    await d.emit.status("reviewer", "审稿正在审阅开书方案…")
    result = await editorial.critique_setup(
        d.llm,
        state["idea"],
        requirements(state),
        state["concept"],
        state["lore"],
        state.get("spine") or {},
        state["outline"],
    )
    await d.emit.say("reviewer", result.remark)
    await d.emit.artifact("reviewer", "审稿意见", {"type": "critique", "data": result.model_dump(exclude={"remark"})})

    serious = [i for i in result.issues if i.severity in ("high", "medium")]
    if result.verdict == "revise" and serious and not state.get("auto_revised"):
        raw: dict[str, str] = {}
        for issue in serious:
            raw[issue.target] = raw.get(issue.target, "") + f"- 审稿意见：{issue.problem}\n  建议：{issue.suggestion}\n"
        queue, instructions = cascade(raw)
        names = "、".join(TARGET_NAMES[t] for t in queue)
        await d.emit.status("chief", f"主编采纳审稿意见，先修改一轮：{names}")
        return {"queue": queue, "instructions": instructions, "phase": "auto_revise", "auto_revised": True}
    return {"queue": [], "instructions": {}, "phase": "reviewed"}


async def _new_notes(d: GraphDeps, seen: int) -> list[tuple[int, str]]:
    async with d.sessionmaker() as session:
        rows = await session.execute(
            select(MeetingMessage.id, MeetingMessage.content)
            .where(MeetingMessage.job_id == d.job_id, MeetingMessage.kind == "note", MeetingMessage.id > seen)
            .order_by(MeetingMessage.id)
        )
        return [(row.id, row.content) for row in rows]


async def intake_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    """每做完一步都过一下：作者有没有插话。已完成的部分要改就排进计划，没做的部分之后直接按插话写。"""
    d = runtime.context
    queue = list(state.get("queue") or [])
    update: dict = {}
    if "outline" in queue and "spine" not in queue and not state.get("spine"):
        # 旧版流程的检查点没有「主线骨架」这一步：继续执行时补上，大纲才有骨架可依
        queue.insert(queue.index("outline"), "spine")
        update["queue"] = queue
    rows = await _new_notes(d, state.get("notes_seen", 0))
    if not rows:
        return update
    fresh = [content for _, content in rows]
    notes = [*(state.get("notes") or []), *fresh]
    update.update(notes=notes, notes_seen=rows[-1][0])
    done = {t: state[t] for t in ORDER if state.get(t) and t not in queue}
    if not done:
        await d.emit.say("chief", "收到，接下来就按你说的写。")
        return update

    await d.check_cancel()
    await d.emit.status("chief", "主编正在看你的插话…")
    todo = [t for t in ORDER if t not in done]
    result = await editorial.absorb_notes(
        d.llm, done, todo, format_requirements(state.get("brief") or [], notes), fresh
    )
    await d.emit.say("chief", result.remark)
    raw = {t: text for t, text in result.instructions().items() if t in done}
    if raw:
        extra_queue, extra = cascade(raw)
        queue, instructions = merge_plan(queue, state.get("instructions") or {}, extra_queue, extra)
        await d.emit.artifact("chief", "按作者插话调整", {"type": "triage", "data": extra})
        update.update(queue=queue, instructions=instructions)
    return update


async def persist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    setup = {k: state.get(k) or {} for k in ORDER}
    async with d.sessionmaker() as session:
        await setup_store.save_setup(session, d.book_id, setup)
        await setup_store.snapshot(
            session, d.book_id, d.job_id, state.get("round", 0), "ai", state.get("phase", ""), setup
        )
        await session.commit()
    await d.emit.status("system", "开书方案已整理好，请作者过目并拍板。")
    return {"queue": [], "instructions": {}}


async def author_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> Command[Literal["finalize", "triage"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    decision = interrupt(
        {"kind": "setup_review", "round": state.get("round", 0), "title": (state.get("concept") or {}).get("title", "")}
    )
    if decision.get("action") == "approve":
        return Command(goto="finalize")
    d = runtime.context
    # 作者可能在网页上手动改过设定和大纲，以数据库里的当前版本为准
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    # 方案定稿前一刻插的话还没人读过，并进这次的意见
    rows = await _new_notes(d, state.get("notes_seen", 0))
    feedback = "\n".join(x for x in [*(c for _, c in rows), str(decision.get("feedback", "")).strip()] if x)
    update: dict = {**setup, "feedback": feedback, "round": state.get("round", 0) + 1}
    # 作者的意见之后每一轮都要遵守，不能下一次修改又改回去
    update["notes"] = [*(state.get("notes") or []), *([feedback] if feedback else [])]
    if rows:
        update["notes_seen"] = rows[-1][0]
    return Command(goto="triage", update=update)


async def triage_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    await d.emit.status("chief", "主编正在研究作者的意见…")
    setup = {k: state.get(k) or {} for k in ORDER}
    result = await editorial.triage_feedback(d.llm, setup, requirements(state), state.get("feedback", ""))
    await d.emit.say("chief", result.remark)
    queue, instructions = cascade(result.instructions())
    if queue:
        await d.emit.artifact("chief", "修改分工", {"type": "triage", "data": instructions})
    return {"queue": queue, "instructions": instructions, "phase": "author_revise"}


async def finalize_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        if book is not None:
            book.status = "ready"
        first = (await session.execute(select(Volume).where(Volume.book_id == d.book_id, Volume.index == 1))).scalar()
        if first is not None:
            first.status = "approved"
        setup = await setup_store.load_setup(session, d.book_id)
        await setup_store.snapshot(session, d.book_id, d.job_id, state.get("round", 0), "author", "approved", setup)
        await session.commit()
    await d.emit.say("system", "作者批准了开书方案，编辑部准备开写第一卷。", kind="decision")
    return {}


def build_setup_graph() -> StateGraph:
    graph = StateGraph(SetupState, context_schema=GraphDeps)
    graph.add_node("interview", interview_node)
    graph.add_node("interview_gate", interview_gate_node)
    graph.add_node("intake", intake_node)
    graph.add_node("concept", concept_node)
    graph.add_node("lore", lore_node)
    graph.add_node("spine", spine_node)
    graph.add_node("outline", outline_node)
    graph.add_node("critique", critique_node)
    graph.add_node("persist", persist_node)
    graph.add_node("author_gate", author_gate_node)
    graph.add_node("triage", triage_node)
    graph.add_node("finalize", finalize_node)

    graph.add_conditional_edges(START, route_start, ["interview", "intake"])
    graph.add_edge("interview", "interview_gate")
    # 每一步做完都先经过 intake，读作者的插话，再决定下一步
    for source in ("interview_gate", *ORDER, "critique", "triage"):
        graph.add_edge(source, "intake")
    graph.add_conditional_edges("intake", route_next, {n: n for n in (*ORDER, "critique", "persist")})
    graph.add_edge("persist", "author_gate")
    graph.add_edge("finalize", END)
    return graph
