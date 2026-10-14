"""开书流程图。

主编定概念 → 设定师建设定 → 主编写大纲 → 审稿挑刺 →（必要时自动修改一轮）→ 存库 → 作者拍板
作者提意见：主编分派修改 → 对应角色修改 → 存库 → 再次拍板；作者批准：定稿。
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.agents import editorial
from app.graphs.deps import GraphDeps
from app.models import Book, Volume
from app.services import setup_store

ORDER = ["concept", "lore", "outline"]
TARGET_NAMES = {"concept": "概念", "lore": "世界观与人物", "outline": "大纲"}
SYNC_INSTRUCTIONS = {
    "lore": "根据修改后的概念同步调整世界观与人物，保持与新概念一致；不受影响的部分保持原样。",
    "outline": "根据修改后的概念与设定同步检查大纲，确保情节、人物与设定一致；不受影响的部分保持原样。",
}


class SetupState(TypedDict, total=False):
    idea: str
    style_reference: str
    concept: dict
    lore: dict
    outline: dict
    # 待执行的步骤（concept / lore / outline），依次弹出
    queue: list[str]
    # 本轮各部分的修改要求；为空表示从零起草
    instructions: dict[str, str]
    # draft：首次起草；reviewed：审稿通过；auto_revise：按审稿意见修改；author_revise：按作者意见修改
    phase: str
    auto_revised: bool
    feedback: str
    round: int


def initial_state(idea: str, style_reference: str = "") -> SetupState:
    return {
        "idea": idea,
        "style_reference": style_reference,
        "queue": list(ORDER),
        "instructions": {},
        "phase": "draft",
        "auto_revised": False,
        "round": 0,
    }


def cascade(instructions: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """上游改了，下游要跟着同步：改概念 → 设定、大纲都要检查；改设定 → 大纲要检查。"""
    targets = {t for t, text in instructions.items() if text.strip()}
    if "concept" in targets:
        targets |= {"lore", "outline"}
    if "lore" in targets:
        targets.add("outline")
    queue = [t for t in ORDER if t in targets]
    merged = {t: instructions.get(t, "").strip() or SYNC_INSTRUCTIONS[t] for t in queue}
    return queue, merged


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


async def concept_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "concept")
    await d.emit.status("chief", "主编正在修改书的概念…" if instruction else "主编正在构思这本书…")
    result = await editorial.draft_concept(d.llm, state["idea"], state.get("style_reference", ""), current, instruction)
    concept = result.model_dump(exclude={"remark"})
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"书的概念：《{concept['title']}》", {"type": "concept", "data": concept})
    return {"concept": concept, "queue": state["queue"][1:]}


async def lore_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "lore")
    await d.emit.status("lorekeeper", "设定师正在修改世界观与人物…" if instruction else "设定师正在搭建世界观与人物…")
    result = await editorial.draft_lore(d.llm, state["concept"], current, instruction)
    lore = result.model_dump(exclude={"remark"})
    await d.emit.say("lorekeeper", result.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"世界观 {len(lore['world_entries'])} 条，人物 {len(lore['characters'])} 位",
        {"type": "lore", "data": lore},
    )
    return {"lore": lore, "queue": state["queue"][1:]}


async def outline_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    current, instruction = _revising(state, "outline")
    await d.emit.status("chief", "主编正在修改大纲…" if instruction else "主编正在写分卷大纲…")
    result = await editorial.draft_outline(d.llm, state["concept"], state["lore"], current, instruction)
    outline = result.model_dump(exclude={"remark"})
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"全书 {len(outline['volumes'])} 卷，第一卷 {len(outline['first_volume_units'])} 个剧情单元",
        {"type": "outline", "data": outline},
    )
    return {"outline": outline, "queue": state["queue"][1:]}


async def critique_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    await d.emit.status("reviewer", "审稿正在审阅开书方案…")
    result = await editorial.critique_setup(d.llm, state["idea"], state["concept"], state["lore"], state["outline"])
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


async def persist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    async with d.sessionmaker() as session:
        await setup_store.save_setup(session, d.book_id, state["concept"], state["lore"], state["outline"])
        await setup_store.snapshot(
            session,
            d.book_id,
            d.job_id,
            state.get("round", 0),
            "ai",
            state.get("phase", ""),
            {"concept": state["concept"], "lore": state["lore"], "outline": state["outline"]},
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
        concept, lore, outline = await setup_store.load_setup(session, d.book_id)
    return Command(
        goto="triage",
        update={
            "concept": concept,
            "lore": lore,
            "outline": outline,
            "feedback": str(decision.get("feedback", "")).strip(),
            "round": state.get("round", 0) + 1,
        },
    )


async def triage_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await d.check_cancel()
    await d.emit.status("chief", "主编正在研究作者的意见…")
    result = await editorial.triage_feedback(
        d.llm, state["concept"], state["lore"], state["outline"], state.get("feedback", "")
    )
    await d.emit.say("chief", result.remark)
    raw = {t: getattr(result, f"{t}_instructions") for t in result.targets()}
    queue, instructions = cascade(raw)
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
        concept, lore, outline = await setup_store.load_setup(session, d.book_id)
        await setup_store.snapshot(
            session,
            d.book_id,
            d.job_id,
            state.get("round", 0),
            "author",
            "approved",
            {"concept": concept, "lore": lore, "outline": outline},
        )
        await session.commit()
    await d.emit.say("system", "作者批准了开书方案，编辑部准备开写第一卷。", kind="decision")
    return {}


def build_setup_graph() -> StateGraph:
    graph = StateGraph(SetupState, context_schema=GraphDeps)
    graph.add_node("concept", concept_node)
    graph.add_node("lore", lore_node)
    graph.add_node("outline", outline_node)
    graph.add_node("critique", critique_node)
    graph.add_node("persist", persist_node)
    graph.add_node("author_gate", author_gate_node)
    graph.add_node("triage", triage_node)
    graph.add_node("finalize", finalize_node)

    targets = {name: name for name in ("concept", "lore", "outline", "critique", "persist")}
    for source in (START, "concept", "lore", "outline", "critique", "triage"):
        graph.add_conditional_edges(source, route_next, targets)
    graph.add_edge("persist", "author_gate")
    graph.add_edge("finalize", END)
    return graph
