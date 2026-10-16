"""开书流程图。

（可选）主编先问作者几个关键问题 → 主编定概念 → 设定师建设定 → 主编定主线骨架（开篇、结局、关键转折）
→ 主编做线索规划（主线、感情线、反派线、谜团线、成长线）→ 主编写全书总纲（分卷卡片 + 长线伏笔）
→ 主编拆第一卷卷纲（剧情单元）→ 审稿挑刺 →（必要时自动修改一轮）→ 存库 → 作者拍板
作者提意见：主编分派修改 → 对应角色修改 → 存库 → 再次拍板；作者批准：定稿。
作者随时可以插话：每做完一步，主编先看有没有新的插话，已完成的部分需要改就先改，之后每一步都按插话来写。
后面各卷的卷纲和每个单元的章纲，在写作流程里写到之前再做（见 write_book）。
"""

import logging
from copy import deepcopy
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import select

from app.agents import editorial
from app.agents.context import (
    format_character_state,
    format_concept,
    format_direction_choice,
    format_ledger,
    format_locked,
    format_requirements,
    format_secrets,
    format_spine,
    format_target_node,
    format_threads,
    format_volume_card,
    planned_chapters,
)
from app.agents.glossary import clean_techniques, glossary_block
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts, relevant_ledger, unit_hint
from app.agents.playbook import pick, playbook_text
from app.agents.setup_puzzle import (
    NODE_CONTENT,
    ORDER,
    PIECE_NAMES,
    PIECE_ORDER,
    PIECES,
    clean_reveals,
    merge_nodes,
    normalize_lore,
    normalize_outline,
    piece_warnings,
)
from app.book_settings import settings_of
from app.graphs.deps import GraphDeps
from app.models import Book, MeetingMessage, StoryNode, Volume
from app.services import setup_store
from app.services.meeting import publish
from app.services.notes import note_prompt, note_thread
from app.services.requirements import (
    active_notes,
    add_requirement,
    deleted_texts,
    import_legacy_checkpoint,
    ingest_notes,
    list_requirements,
)

log = logging.getLogger(__name__)
TARGET_NAMES = {
    "concept": "概念",
    "lore": "世界观、人物与信息差",
    "spine": "关键节点",
    "threads": "线索",
    "outline": "全书总纲",
    "first_volume": "第一卷卷纲",
}
SYNC_INSTRUCTIONS = {
    "spine": "根据修改后的概念同步检查关键节点，铁钉保持原样；不受影响的部分保持原样。",
    "lore": "根据修改后的概念和关键节点同步调整世界观、人物锚点与信息差；不受影响的部分保持原样。",
    "threads": "根据修改后的上游内容同步检查线索，确保人物、节拍与之一致；不受影响的部分保持原样。",
    "outline": "根据修改后的关键节点、人物锚点与信息差同步检查分卷、长线伏笔和期待；不受影响的部分保持原样。",
    "first_volume": "根据修改后的上游内容同步检查第一卷卷纲，确保剧情单元、线索与伏笔与之一致；不受影响的部分保持原样。",
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
    mode: Literal["puzzle", "oneshot"]
    directions: list[dict]
    recommended: int
    direction: dict
    piece: str | None
    pieces: dict[str, str]
    decisions: dict[str, list[dict]]
    warnings: list[str]
    suggestions: list[dict]
    unlock_requests: list[dict]
    candidates: dict | None
    node_snapshot: list[str | None]
    resync: list[str]
    piece_reviewed: dict[str, bool]
    piece_revised: dict[str, bool]
    dropped: dict[str, int]
    outline_warnings: list[str]
    op: dict
    requirements_ledger_ready: bool
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
    threads: dict
    outline: dict
    first_volume: dict
    # 待执行的步骤（ORDER 中的部分），依次弹出
    queue: list[str]
    # 本轮各部分的修改要求；为空表示从零起草
    instructions: dict[str, str]
    instruction_sources: dict[str, list[str]]
    instruction_fallbacks: dict[str, str]
    feedback_sources: list[str]
    # 仅存检查点的本轮节点 ID 授权；生成节点后即清空，不写入作者要求或书籍设置。
    pinned_overrides: list[str]
    pinned_override_sources: dict[str, list[str]]
    # draft：首次起草；reviewed：审稿通过；auto_revise：按审稿意见修改；author_revise：按作者意见修改
    phase: str
    auto_revised: bool
    feedback: str
    round: int


def initial_state(idea: str, style_reference: str = "", ask: bool = False, mode: str = "oneshot") -> SetupState:
    return {
        "requirements_ledger_ready": True,
        "idea": idea,
        "style_reference": style_reference,
        "ask": ask,
        "brief": [],
        "notes": [],
        "notes_seen": 0,
        "mode": mode,
        "queue": ["concept"] if mode == "puzzle" else list(ORDER),
        "piece": "concept",
        "pieces": dict.fromkeys(PIECE_ORDER, "todo"),
        "decisions": {},
        "warnings": [],
        "suggestions": [],
        "unlock_requests": [],
        "candidates": None,
        "node_snapshot": [],
        "resync": [],
        "piece_reviewed": {},
        "piece_revised": {},
        "instructions": {},
        "pinned_overrides": [],
        "pinned_override_sources": {},
        "phase": "draft",
        "auto_revised": False,
        "round": 0,
    }


def cascade(instructions: dict[str, str], state: SetupState | None = None) -> tuple[list[str], dict[str, str]]:
    """上游改了，下游要跟着同步：改概念 → 后面全部要检查；改设定 → 主线及之后；以此类推。"""
    allowed = PIECES.get(state.get("piece"), []) if state and state.get("mode") == "puzzle" else ORDER
    targets = {t for t, text in instructions.items() if text.strip() and t in allowed}
    for i, target in enumerate(allowed):
        if target in targets:
            targets |= set(allowed[i + 1 :])
    queue = [t for t in allowed if t in targets]
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


def has_part(state: SetupState, target: str) -> bool:
    value = state.get(target) or {}
    if target == "threads":
        return bool(value.get("threads"))
    if target == "first_volume":
        return bool(value.get("units"))
    return bool(value)


def fill_missing_steps(state: SetupState, queue: list[str]) -> list[str]:
    """旧版流程的检查点或旧书缺少后来新增的步骤（主线骨架、线索、第一卷卷纲）：继续执行时补上。"""
    if not queue:
        return queue
    allowed = PIECES.get(state.get("piece"), []) if state.get("mode") == "puzzle" else ORDER
    missing = [t for t in allowed if t not in queue and not has_part(state, t)]
    return [t for t in allowed if t in queue or t in missing]


def requirements(state: SetupState) -> str:
    # live_requirements is loaded from the sole ledger before every model step, never checkpoint brief/notes.
    return format_requirements(state.get("live_requirements") or [], [], state.get("settings"))


async def live_state(state: SetupState, d: GraphDeps) -> SetupState:
    async with d.sessionmaker() as session:
        await import_legacy_checkpoint(session, d.book_id, d.job_id, state)
        await session.commit()
        book = await session.get(Book, d.book_id)
        settings = settings_of(book) if book else {}
        rows = await list_requirements(session, d.book_id)
        deleted = await deleted_texts(session, d.book_id)
    current = {**state, "settings": settings, "live_requirements": [row.text for row in rows]}
    if state.get("spine"):
        current["spine"] = setup_store.spine_from_legacy(state["spine"])
    current["feedback_sources"] = [text for text in state.get("feedback_sources") or [] if text not in deleted]
    # Author-derived directives are transient, but still must respect explicit deletion.
    # Source tracking lets us invalidate paraphrased instructions without erasing reviewer-only revisions.
    feedback = state.get("feedback", "")
    if any(text in feedback for text in deleted):
        current["feedback"] = "\n".join(current["feedback_sources"])
    instructions = dict(state.get("instructions") or {})
    sources = state.get("instruction_sources") or {}
    legacy_author = (
        state.get("phase") == "author_revise"
        and not sources
        and any(text in "\n".join(state.get("notes") or []) for text in deleted)
    )
    revoked_spine = False
    for target in list(instructions):
        if legacy_author or any(text in deleted for text in sources.get(target, [])):
            revoked_spine |= target == "spine"
            fallback = (state.get("instruction_fallbacks") or {}).get(target)
            if fallback:
                instructions[target] = fallback
            else:
                instructions.pop(target)
    current["instructions"] = instructions
    override_sources = state.get("pinned_override_sources") or {}
    allowed = [
        node_id
        for node_id in state.get("pinned_overrides") or []
        if not any(text in deleted for text in override_sources.get(node_id, []))
    ]
    if revoked_spine or not instructions.get("spine") or instructions.get("spine") == SYNC_INSTRUCTIONS["spine"]:
        allowed = []
    current.update(
        pinned_overrides=allowed,
        pinned_override_sources={node_id: override_sources.get(node_id, []) for node_id in allowed},
    )
    if settings.get("chapter_words") and state.get("concept"):
        current["concept"] = {**state["concept"], "chapter_words": settings["chapter_words"]}
    return current


def setup_of(state: SetupState) -> dict[str, dict]:
    return {k: state.get(k) or {} for k in ORDER}


def locked_steps(state: SetupState) -> set[str]:
    if state.get("mode") != "puzzle":
        return set()
    return {
        target
        for piece, targets in PIECES.items()
        if (state.get("pieces") or {}).get(piece) == "confirmed"
        for target in targets
    }


def _pieces(state: SetupState) -> dict[str, str]:
    return {piece: (state.get("pieces") or {}).get(piece, "todo") for piece in PIECE_ORDER}


def _piece_of(target: str) -> str:
    return next(piece for piece, targets in PIECES.items() if target in targets)


async def mark_progress(d: GraphDeps, state: SetupState) -> None:
    progress = {"mode": state.get("mode", "oneshot"), "current": state.get("piece"), "pieces": _pieces(state)}
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        if book is not None:
            book.setup_progress = progress
            await session.commit()
    await publish(d.redis, d.book_id, "book", {"id": str(d.book_id), "setup_progress": progress})


async def _finished(d: GraphDeps, state: SetupState, target: str, value: dict, result=None) -> dict:
    update = _finish(state, target, value)
    if result is not None and hasattr(result, "decisions"):
        update["decisions"] = {**(state.get("decisions") or {}), target: [c.model_dump() for c in result.decisions[:3]]}
    piece = _piece_of(target)
    pieces = _pieces(state)
    if state.get("mode") != "puzzle" and not any(t in update["queue"] for t in PIECES[piece]):
        pieces[piece] = "done"
    update.update(piece=piece, pieces=pieces)
    await mark_progress(d, {**state, **update})
    return update


def _unlock_requests(state: SetupState, result) -> list[dict]:
    requests = list(state.get("unlock_requests") or [])
    locked = locked_steps(state)
    for request in getattr(result, "unlock_requests", []):
        item = request.model_dump()
        if item["target"] in locked:
            requests.append(item)
    # 不依赖模型自觉遵守锁定：它仍给锁定块发修改指令时，只生成解锁请求。
    for target, reason in result.instructions().items():
        if target in locked:
            requests.append({"target": target, "reason": reason})
    return list({(item["target"], item["reason"]): item for item in requests}.values())


async def _explain_unlocks(d: GraphDeps, requests: list[dict]) -> None:
    if requests:
        names = "、".join(dict.fromkeys(PIECE_NAMES[_piece_of(r["target"])] for r in requests))
        await d.emit.say("chief", f"这需要改已经确认的「{names}」，要解锁的话点「解锁并修改」。")


def _pinned_overrides(result, snapshot: list[dict]) -> list[str]:
    """模型序号只认本次渲染时的快照，不用最新顺序或历史 node_snapshot 猜测。"""
    return list(
        dict.fromkeys(
            snapshot[ref - 1]["id"]
            for ref in getattr(result, "pinned_overrides", [])
            if type(ref) is int
            and 1 <= ref <= len(snapshot)
            and snapshot[ref - 1].get("id")
            and snapshot[ref - 1].get("status") == "pinned"
        )
    )


def _override_update(ids: list[str], sources: list[str]) -> dict:
    return {
        "pinned_overrides": list(dict.fromkeys(ids)),
        "pinned_override_sources": {node_id: list(sources) for node_id in ids},
    }


async def directions_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    pieces = {**_pieces(state), "concept": "drafting"}
    await mark_progress(d, {**state, "piece": "concept", "pieces": pieces})
    await d.emit.status("chief", "主编在想几个开书方向…")
    result = await editorial.draft_directions(
        d.llm, state["idea"], state.get("style_reference", ""), requirements(state)
    )
    directions = [item.model_dump() for item in result.directions[:3]]
    for item in directions:
        item["techniques"] = clean_techniques(item.get("techniques"))
    recommended = min(max(0, result.recommended), max(0, len(directions) - 1))
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"开书方向：{len(directions)} 个",
        {"type": "directions", "data": {"directions": directions, "recommended": recommended}},
    )
    return {"directions": directions, "recommended": recommended, "piece": "concept", "pieces": pieces}


async def directions_gate_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["directions", "intake"]]:
    decision = interrupt(
        {
            "kind": "setup_directions",
            "directions": state.get("directions") or [],
            "recommended": state.get("recommended", 0),
            "length": LENGTH_QUESTION,
        }
    )
    if decision.get("action") == "redo":
        if not decision.get("requirement_saved") and decision.get("feedback", "").strip():
            async with runtime.context.sessionmaker() as session:
                await add_requirement(session, runtime.context.book_id, decision["feedback"].strip(), "note")
                await session.commit()
        return Command(goto="directions")
    directions = state.get("directions") or []
    choice = decision.get("choice")
    if not isinstance(choice, int) or not 0 <= choice < len(directions):
        raise ValueError("请选择有效的开书方向")
    direction = {**directions[choice], "mix": decision.get("mix", ""), "length": decision.get("length", "")}
    if not decision.get("requirement_saved"):
        async with runtime.context.sessionmaker() as session:
            if direction["length"]:
                await add_requirement(
                    session, runtime.context.book_id, f"这本书打算写多长？——{direction['length']}", "answer"
                )
            note = f"开书方向：选用「{direction['name']}」" + (
                f"；混搭：{direction['mix']}" if direction["mix"] else ""
            )
            await add_requirement(session, runtime.context.book_id, note, "answer")
            await session.commit()
    return Command(goto="intake", update={"direction": direction, "queue": ["concept"]})


def route_start(state: SetupState) -> str:
    if state.get("mode") == "puzzle":
        return "directions"
    return "interview" if state.get("ask") else "intake"


def route_next(state: SetupState) -> str:
    queue = state.get("queue") or []
    if queue:
        return queue[0]
    if state.get("mode") == "puzzle":
        return "piece_check"
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
    origins = {k: v for k, v in (state.get("instruction_sources") or {}).items() if k != target}
    fallbacks = {k: v for k, v in (state.get("instruction_fallbacks") or {}).items() if k != target}
    return {
        target: value,
        "queue": (state.get("queue") or [])[1:],
        "instructions": rest,
        "instruction_sources": origins,
        "instruction_fallbacks": fallbacks,
        **(_override_update([], []) if target == "spine" else {}),
    }


async def interview_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await mark_progress(d, state)
    await d.emit.status("chief", "主编动笔前想先问你几个问题…")
    result = await editorial.interview(d.llm, state["idea"], state.get("style_reference", ""), requirements(state))
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
    async with d.sessionmaker() as session:
        if not answer.get("requirement_saved"):
            for line in brief:
                await add_requirement(session, d.book_id, line, "answer")
        await session.commit()
    return {"brief": brief}


async def concept_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "concept")
    await d.emit.status("chief", "主编正在修改书的概念…" if instruction else "主编正在构思这本书…")
    result = await editorial.draft_concept(
        d.llm,
        state["idea"],
        state.get("style_reference", ""),
        requirements(state),
        current,
        instruction,
        chosen_direction=format_direction_choice(state.get("direction") or {}) if state.get("mode") == "puzzle" else "",
    )
    concept = result.model_dump(exclude={"remark", "decisions"})
    if (state.get("settings") or {}).get("chapter_words"):
        concept["chapter_words"] = state["settings"]["chapter_words"]
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"书的概念：《{concept['title']}》", {"type": "concept", "data": concept})
    return await _finished(d, state, "concept", concept, result)


async def lore_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "lore")
    await d.emit.status("lorekeeper", "设定师正在修改世界观与人物…" if instruction else "设定师正在搭建世界观与人物…")
    result = await editorial.draft_lore(
        d.llm, state["concept"], state.get("spine") or {}, requirements(state), current, instruction
    )
    nodes = (state.get("spine") or {}).get("nodes") or []
    lore, dropped = normalize_lore(
        result.model_dump(exclude={"remark", "decisions"}), nodes, (state.get("lore") or {}).get("secrets") or []
    )
    await d.emit.say("lorekeeper", result.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"世界观 {len(lore['world_entries'])} 条，人物 {len(lore['characters'])} 位",
        {"type": "lore", "data": lore},
    )
    return {
        **await _finished(d, state, "lore", lore, result),
        "dropped": dropped,
        "node_snapshot": [n.get("id") for n in nodes],
    }


async def spine_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "spine")
    previous_nodes = deepcopy((state.get("spine") or {}).get("nodes") or [])
    allowed = set(state.get("pinned_overrides") or [])
    if state.get("phase") == "auto_revise" or instruction == SYNC_INSTRUCTIONS["spine"]:
        allowed.clear()
    # 卡片按 ID 授权后也显式告诉模型；始终按本次节点提示词的序号，不沿用旧序号。
    if allowed and instruction:
        instruction += "\n" + "\n".join(
            f"作者要求改动铁钉节点 {i}，只按作者本轮意见修改，改完仍是铁钉。"
            for i, node in enumerate(previous_nodes, 1)
            if node.get("id") in allowed and node.get("status") == "pinned"
        )
    await d.emit.status("chief", "主编正在修改主线骨架…" if instruction else "主编正在定主线：开篇、结局和关键转折…")
    result = await editorial.draft_spine(
        d.llm,
        state["concept"],
        requirements(state),
        current,
        instruction,
        playbook=playbook_text(
            state.get("concept"), "nodes", selection=(state.get("settings") or {}).get("playbook", "auto")
        ),
        glossary=glossary_block(),
        legacy_lore=state.get("lore") or {},
    )
    spine = result.model_dump(exclude={"remark", "decisions"})
    # 模型只引用本次提示词中的序号，状态和铁钉内容始终由程序决定。
    spine["nodes"] = merge_nodes(spine.get("nodes") or [], previous_nodes, pinned_overrides=allowed)
    remapped = setup_store.remap_node_refs(setup_of(state), previous_nodes, spine["nodes"])
    await d.emit.say("chief", result.remark)
    previous_by_id = {node.get("id"): node for node in previous_nodes if node.get("id")}
    for i, node in enumerate(spine["nodes"], 1):
        previous = previous_by_id.get(node.get("id"), {})
        if (
            node.get("id") in allowed
            and previous.get("status") == "pinned"
            and any(node.get(key) != previous.get(key) for key in NODE_CONTENT)
        ):
            await d.emit.say("chief", f"按你的意思改了铁钉节点 {i}「{node.get('title', '')}」，它还是铁钉。")
    milestones = sum(node["kind"] == "milestone" for node in spine["nodes"])
    await d.emit.artifact("chief", f"主线骨架：{milestones} 个关键转折", {"type": "spine", "data": spine})
    return {
        **{key: remapped[key] for key in ("lore", "outline", "first_volume") if key in state},
        **await _finished(d, state, "spine", spine, result),
        "node_snapshot": [node.get("id") for node in previous_nodes],
    }


async def threads_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "threads")
    playbook = pick(state.get("concept"), (state.get("settings") or {}).get("playbook", "auto")).name
    await d.emit.status(
        "chief",
        "主编正在修改线索…"
        if instruction
        else f"主编正在做线索规划（题材打法：{playbook}）：主线、感情线、反派线、谜团线…",
    )
    result = await editorial.draft_threads(
        d.llm,
        state["concept"],
        state["lore"],
        state.get("spine") or {},
        state.get("outline") or {},
        requirements(state),
        current,
        instruction,
        selection=(state.get("settings") or {}).get("playbook", "auto"),
    )
    threads = result.model_dump(exclude={"remark"})
    for t in threads["threads"]:
        t["beats"] = sorted(t["beats"], key=lambda b: b["volume"])
    outline = deepcopy(state.get("outline") or {})
    for volume in outline.get("volumes") or []:
        volume["thread_beats"] = [
            {"thread": t["name"], "beat": b["beat"]}
            for t in threads["threads"]
            for b in t.get("beats") or []
            if b.get("volume") == volume.get("index")
        ]
    await d.emit.say("chief", result.remark)
    kinds = "、".join(dict.fromkeys(t["kind"] for t in threads["threads"]))
    await d.emit.artifact("chief", f"线索 {len(threads['threads'])} 条：{kinds}", {"type": "threads", "data": threads})
    return {**await _finished(d, state, "threads", threads), "outline": outline}


async def outline_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "outline")
    await d.emit.status(
        "chief", "主编正在修改全书总纲…" if instruction else "主编正在写全书总纲：每卷的舞台、对手与线索…"
    )
    result = await editorial.draft_outline(
        d.llm,
        state["concept"],
        state["lore"],
        state.get("spine") or {},
        requirements(state),
        current,
        instruction,
        selection=(state.get("settings") or {}).get("playbook", "auto"),
        glossary=glossary_block(),
        legacy_threads=state.get("threads") or {},
    )
    outline, nodes, warnings = normalize_outline(
        result.model_dump(exclude={"remark", "decisions"}), (state.get("spine") or {}).get("nodes") or []
    )
    # 长线伏笔编号：与当前版本内容相同的沿用原编号，第一卷卷纲引用的编号才不会乱
    previous = setup_store.ledger_of(setup_of(state))
    ledger = setup_store.assign_seqs(
        [{**f, "kind": "伏笔", "span": "长"} for f in outline["foreshadowings"]]
        + [{**f, "kind": "期待"} for f in outline.get("expectations") or []],
        previous,
    )
    outline["foreshadowings"] = [f for f in ledger if f["kind"] == "伏笔"]
    outline["expectations"] = [f for f in ledger if f["kind"] == "期待"]
    await d.emit.say("chief", result.remark)
    total = sum(v.get("chapter_count") or 0 for v in outline["volumes"]) or planned_chapters(state["concept"])
    await d.emit.artifact(
        "chief",
        f"全书 {len(outline['volumes'])} 卷"
        + (f"约 {total} 章" if total else "")
        + f"，长线伏笔 {len(outline['foreshadowings'])} 条",
        {"type": "outline", "data": outline},
    )
    return {
        **await _finished(d, state, "outline", outline, result),
        "spine": {**(state.get("spine") or {}), "nodes": nodes},
        "outline_warnings": warnings,
        "node_snapshot": [n.get("id") for n in nodes],
    }


def first_volume_blocks(state: SetupState) -> dict[str, str]:
    """开书时拆第一卷：上下文都来自方案本身。"""
    volumes = (state.get("outline") or {}).get("volumes") or []
    card = next((v for v in volumes if v.get("index") == 1), volumes[0] if volumes else {})
    following = next((v for v in volumes if v.get("index") == 2), None)
    chapter_count = int(card.get("chapter_count") or 0)
    lore = state.get("lore") or {}
    spine = setup_store.spine_from_legacy(state.get("spine") or {})
    opening = next((n.get("event", "") for n in spine.get("nodes", []) if n.get("kind") == "opening"), "（暂无）")
    ledger = setup_store.ledger_of({"outline": state.get("outline") or {}})
    return {
        "volume_index": "1",
        "concept": format_concept(state.get("concept") or {}),
        "spine": format_spine(spine),
        "target_node": format_target_node(card, spine.get("nodes") or []),
        "secrets": format_secrets(lore.get("secrets") or []),
        "glossary": glossary_block(),
        "threads": format_threads(state.get("threads") or {}, volume=1),
        "volume": format_volume_card(card),
        "neighbors": "上一卷：无（这是第一卷）\n下一卷：" + (format_volume_card(following) if following else "无"),
        "story_so_far": f"还没开写，这是第一卷。开篇设计：{opening}",
        "used_climaxes": "（暂无）",
        "characters": "\n".join(format_character_state(c) for c in lore.get("characters", [])) or "（暂无）",
        "ledger": format_ledger(relevant_ledger(ledger, 1)),
        "trope_usage": "（还没用过任何套路，这是第一卷）",
        "playbook": playbook_text(
            state.get("concept"), "volume", selection=(state.get("settings") or {}).get("playbook", "auto")
        ),
        "requirements": requirements(state),
        "unit_hint": unit_hint(chapter_count),
        "chapter_count": str(chapter_count or "若干"),
    }


async def first_volume_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "first_volume")
    await d.emit.status(
        "chief", "主编正在修改第一卷卷纲…" if instruction else "主编正在拆第一卷：剧情单元、线索交织与伏笔…"
    )
    blocks = first_volume_blocks(state)
    result = await editorial.plan_volume(d.llm, blocks, current, instruction, purpose="开书·第一卷卷纲")
    plan = result.model_dump(exclude={"remark"})
    target = int(blocks["chapter_count"]) if blocks["chapter_count"].isdigit() else 0
    units = fit_chapter_counts(plan["units"], target)
    # 新伏笔接着总纲的长线伏笔编号；修改时内容没变的沿用原编号
    fresh = setup_store.assign_seqs(
        [{**f, "kind": "伏笔"} for f in plan["new_foreshadowings"]]
        + [{**f, "kind": "期待"} for f in plan.get("new_expectations") or []],
        setup_store.ledger_of(setup_of(state)),
    )
    units, fresh = attach_new_foreshadowings(units, fresh, 1)
    units = clean_reveals(units, (state.get("lore") or {}).get("secrets") or [])
    for unit in units:
        unit["techniques"] = clean_techniques(unit.get("techniques"))
    first_volume = {
        "units": units,
        "new_foreshadowings": [f for f in fresh if f["kind"] == "伏笔"],
        "new_expectations": [f for f in fresh if f["kind"] == "期待"],
    }
    if plan.get("node_update") or plan.get("node_conflict"):
        log.info("开书阶段忽略卷纲节点调整提议：%s", d.book_id)
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"第一卷拆成 {len(units)} 个剧情单元，新埋伏笔 {len(fresh)} 条",
        {"type": "volume_plan", "data": {"volume": 1, **first_volume}},
    )
    return await _finished(d, state, "first_volume", first_volume)


async def critique_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("reviewer", "审稿正在审阅开书方案…")
    result = await editorial.critique_setup(
        d.llm,
        state["idea"],
        requirements(state),
        setup_of(state),
        selection=(state.get("settings") or {}).get("playbook", "auto"),
        locked=format_locked(state),
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
        return {
            "queue": queue,
            "instructions": instructions,
            "instruction_sources": {},
            "instruction_fallbacks": {},
            **_override_update([], []),
            "phase": "auto_revise",
            "auto_revised": True,
        }
    return {"queue": [], "instructions": {}, "phase": "reviewed", **_override_update([], [])}


async def _new_notes(d: GraphDeps, seen: int) -> list[tuple[int, str, dict | None]]:
    async with d.sessionmaker() as session:
        rows = await session.execute(
            select(MeetingMessage.id, MeetingMessage.content, MeetingMessage.payload)
            .where(MeetingMessage.job_id == d.job_id, MeetingMessage.kind == "note", MeetingMessage.id > seen)
            .order_by(MeetingMessage.id)
        )
        messages = [(row.id, row.content, row.payload) for row in rows]
        return await active_notes(session, d.book_id, messages) if messages else []


async def _reply_to_notes(d: GraphDeps, rows: list[tuple[int, str, dict | None]]) -> None:
    for _, _, payload in rows:
        if thread := note_thread(payload):
            await d.emit.say(thread, "收到，主编已经安排，按你说的改。", payload={"thread": thread})


async def intake_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    """每做完一步都过一下：作者有没有插话。已完成的部分要改就排进计划，没做的部分之后直接按插话写。"""
    d = runtime.context
    queue = list(state.get("queue") or [])
    update: dict = {}
    filled = fill_missing_steps(state, queue)
    if filled != queue:
        queue = filled
        update["queue"] = queue
    state = {**state, "queue": queue}
    if queue:
        piece = _piece_of(queue[0])
        pieces = {**_pieces(state), piece: "drafting"}
        update.update(piece=piece, pieces=pieces)
        state = {**state, **update}
        await mark_progress(d, state)
    rows = await _new_notes(d, state.get("notes_seen", 0))
    if not rows:
        return update
    async with d.sessionmaker() as session:
        await ingest_notes(session, d.book_id, rows)
        await session.commit()
    state = await live_state(state, d)
    fresh = [note_prompt(content, payload) for _, content, payload in rows]
    notes = [*(state.get("notes") or []), *fresh]
    update.update(notes=notes, notes_seen=rows[-1][0])
    # 已有节点即使排队等待修改，也要给这次插话同一份快照，才能补充点名授权。
    done = {t: state[t] for t in ORDER if has_part(state, t) and (t not in queue or t == "spine")}
    if not done:
        if any(not note_thread(payload) for _, _, payload in rows):
            await d.emit.say("chief", "收到，接下来就按你说的写。")
        await _reply_to_notes(d, rows)
        return update

    await d.check_cancel()
    await d.emit.status("chief", "主编正在看你的插话…")
    todo = [t for t in ORDER if t not in done]
    snapshot = deepcopy((done.get("spine") or {}).get("nodes") or [])
    result = await editorial.absorb_notes(d.llm, done, todo, requirements(state), fresh, locked=format_locked(state))
    if any(not note_thread(payload) for _, _, payload in rows):
        await d.emit.say("chief", result.remark)
    requests = _unlock_requests(state, result)
    update["unlock_requests"] = requests
    await _explain_unlocks(d, requests)
    raw = {t: text for t, text in result.instructions().items() if t in done and t not in locked_steps(state)}
    if raw:
        extra_queue, extra = cascade(raw, state)
        queue, instructions = merge_plan(queue, state.get("instructions") or {}, extra_queue, extra)
        await d.emit.artifact("chief", "按作者插话调整", {"type": "triage", "data": extra})
        update.update(queue=queue, instructions=instructions)
        origins = dict(state.get("instruction_sources") or {})
        fallbacks = dict(state.get("instruction_fallbacks") or {})
        for target in extra_queue:
            if not origins.get(target) and (state.get("instructions") or {}).get(target):
                fallbacks[target] = state["instructions"][target]
            origins[target] = list(
                dict.fromkeys(
                    [
                        *origins.get(target, []),
                        *(content for _, content, payload in rows if not (payload or {}).get("settings_change")),
                    ]
                )
            )
        update["instruction_sources"] = origins
        update["instruction_fallbacks"] = fallbacks
        if "spine" in raw and "spine" in extra_queue:
            sources = [content for _, content, payload in rows if not (payload or {}).get("settings_change")]
            allowed = (
                _pinned_overrides(result, snapshot) if sources and raw["spine"] != SYNC_INSTRUCTIONS["spine"] else []
            )
            # 后续插话可以补充本轮授权；不能清掉尚未执行的、先前作者已点名的节点。
            combined = list(dict.fromkeys([*(state.get("pinned_overrides") or []), *allowed]))
            update.update(_override_update(combined, []))
            update["pinned_override_sources"] = {
                **(state.get("pinned_override_sources") or {}),
                **{node_id: sources for node_id in allowed},
            }
            if allowed and state.get("phase") == "auto_revise":
                update["phase"] = "author_revise"
    await _reply_to_notes(d, rows)
    return update


async def persist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    setup = setup_of(state)
    async with d.sessionmaker() as session:
        await setup_store.save_setup(session, d.book_id, setup)
        await setup_store.snapshot(
            session, d.book_id, d.job_id, state.get("round", 0), "ai", state.get("phase", ""), setup
        )
        await session.commit()
        saved = await setup_store.load_setup(session, d.book_id)
    await d.emit.status("system", "开书方案已整理好，请作者过目并拍板。")
    await mark_progress(d, state)
    return {**saved, "queue": [], "instructions": {}, **_override_update([], [])}


async def author_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> Command[Literal["finalize", "triage"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    decision = interrupt(
        {"kind": "setup_review", "round": state.get("round", 0), "title": (state.get("concept") or {}).get("title", "")}
    )
    d = runtime.context
    if decision.get("action") == "approve":
        # 最后一次 intake 到等待拍板之间仍可能收到已被接口接受的插话。
        # 批准不偷偷改动已审阅的方案；这些新要求留给之后的规划与正文，不能随开书任务结束而丢掉。
        rows = await _new_notes(d, state.get("notes_seen", 0))
        if not rows:
            return Command(goto="finalize")
        fresh = [note_prompt(content, payload) for _, content, payload in rows]
        async with d.sessionmaker() as session:
            await ingest_notes(session, d.book_id, rows)
            await session.commit()
        if any(not note_thread(payload) for _, _, payload in rows):
            await d.emit.say("chief", "收到，要求已经记下，之后的规划和章节都会照办。")
        await _reply_to_notes(d, rows)
        return Command(
            goto="finalize", update={"notes": [*(state.get("notes") or []), *fresh], "notes_seen": rows[-1][0]}
        )
    # 作者可能在网页上手动改过设定和大纲，以数据库里的当前版本为准
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    # 方案定稿前一刻插的话还没人读过，并进这次的意见
    rows = await _new_notes(d, state.get("notes_seen", 0))
    feedback = "\n".join(
        x for x in [*(note_prompt(c, p) for _, c, p in rows), str(decision.get("feedback", "")).strip()] if x
    )
    async with d.sessionmaker() as session:
        await ingest_notes(session, d.book_id, rows)
        if decision.get("feedback", "").strip() and not decision.get("requirement_saved"):
            await add_requirement(session, d.book_id, decision["feedback"], "note")
        await session.commit()
    update: dict = {
        **setup,
        "feedback": feedback,
        "round": state.get("round", 0) + 1,
        **_override_update([], []),
    }
    update["feedback_sources"] = [*(content for _, content, _ in rows), str(decision.get("feedback", "")).strip()]
    # 作者的意见之后每一轮都要遵守，不能下一次修改又改回去
    update["notes"] = [*(state.get("notes") or []), *([feedback] if feedback else [])]
    if rows:
        update["notes_seen"] = rows[-1][0]
        await _reply_to_notes(d, rows)
    return Command(goto="triage", update=update)


async def triage_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("chief", "主编正在研究作者的意见…")
    snapshot = deepcopy((state.get("spine") or {}).get("nodes") or [])
    result = await editorial.triage_feedback(
        d.llm, setup_of(state), requirements(state), state.get("feedback", ""), locked=format_locked(state)
    )
    await d.emit.say("chief", result.remark)
    raw = result.instructions()
    queue, instructions = cascade(raw)
    if queue:
        await d.emit.artifact("chief", "修改分工", {"type": "triage", "data": instructions})
    origins = list(state.get("feedback_sources") or ([state["feedback"]] if state.get("feedback") else []))
    return {
        "queue": queue,
        "instructions": instructions,
        "instruction_sources": {target: origins for target in queue},
        "instruction_fallbacks": {},
        **_override_update(
            _pinned_overrides(result, snapshot)
            if raw.get("spine") and raw["spine"] != SYNC_INSTRUCTIONS["spine"]
            else [],
            origins,
        ),
        "phase": "author_revise",
    }


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
    update = {
        "piece": None,
        "pieces": dict.fromkeys(PIECE_ORDER, "confirmed"),
        "warnings": [],
        "suggestions": [],
        "unlock_requests": [],
        "candidates": None,
        **_override_update([], []),
    }
    await mark_progress(d, {**state, **update})
    return update


async def piece_check_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["intake", "piece_persist"]]:
    d = runtime.context
    state = await live_state(state, d)
    piece = state["piece"]
    warnings = piece_warnings(piece, setup_of(state), state.get("dropped"))
    if piece == "fill":
        warnings = list(dict.fromkeys([*warnings, *(state.get("outline_warnings") or [])]))
    update = {"warnings": warnings, **_override_update([], [])}
    review = piece == "first_volume" or (piece == "nodes" and (state.get("settings") or {}).get("volume_audit", True))
    if review and not (state.get("piece_reviewed") or {}).get(piece):
        await d.check_cancel()
        await d.emit.status("reviewer", f"审稿正在检查「{PIECE_NAMES[piece]}」…")
        completed = {target for p in PIECE_ORDER[: PIECE_ORDER.index(piece) + 1] for target in PIECES[p]}
        setup = {target: state.get(target) or {} for target in ORDER if target in completed}
        checks = requirements(state) + ("\n\n【程序提醒】\n" + "\n".join(warnings) if warnings else "")
        result = await editorial.critique_setup(
            d.llm,
            state["idea"],
            checks,
            setup,
            selection=(state.get("settings") or {}).get("playbook", "auto"),
            locked=format_locked(state),
        )
        await d.emit.say("reviewer", result.remark)
        await d.emit.artifact(
            "reviewer",
            "单块审稿" if piece == "nodes" else "跨块审稿",
            {"type": "critique", "data": result.model_dump(exclude={"remark"})},
        )
        update["piece_reviewed"] = {**(state.get("piece_reviewed") or {}), piece: True}
        suggestions = list(state.get("suggestions") or [])
        for issue in result.issues:
            if issue.target in locked_steps(state):
                suggestions.append({"target": issue.target, "problem": issue.problem, "suggestion": issue.suggestion})
        update["suggestions"] = list({(s["target"], s["problem"], s["suggestion"]): s for s in suggestions}.values())
        local = [i for i in result.issues if i.target in PIECES[piece] and i.severity in ("high", "medium")]
        if local and not (state.get("piece_revised") or {}).get(piece):
            raw = {}
            for issue in local:
                raw[issue.target] = (
                    raw.get(issue.target, "") + f"- 审稿意见：{issue.problem}\n  建议：{issue.suggestion}\n"
                )
            queue, instructions = cascade(raw, state)
            update.update(
                queue=queue,
                instructions=instructions,
                instruction_sources={},
                instruction_fallbacks={},
                piece_revised={**(state.get("piece_revised") or {}), piece: True},
                phase="auto_revise",
            )
            return Command(goto="intake", update=update)
    return Command(goto="piece_persist", update=update)


async def piece_persist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d, piece = runtime.context, state["piece"]
    async with d.sessionmaker() as session:
        # 填中间只同步已有非铁钉节点的卷号，不能借旧检查点增删节点或覆盖作者的其他字段。
        if piece == "fill":
            existing_nodes = {
                str(node.id): node
                for node in await session.scalars(select(StoryNode).where(StoryNode.book_id == d.book_id))
            }
            for item in (state.get("spine") or {}).get("nodes") or []:
                node = existing_nodes.get(str(item.get("id")))
                if node is not None and node.status != "pinned" and "volume" in item:
                    node.volume = item["volume"]
        await setup_store.save_piece(session, d.book_id, piece, setup_of(state))
        await setup_store.snapshot(
            session, d.book_id, d.job_id, state.get("round", 0), "ai", f"piece:{piece}", setup_of(state)
        )
        await session.commit()
        saved = await setup_store.load_setup(session, d.book_id)
    update = {**{target: saved[target] for target in PIECES[piece]}, **_override_update([], [])}
    if piece == "fill":
        update["spine"] = saved["spine"]
    update["pieces"] = {**_pieces(state), piece: "waiting"}
    await mark_progress(d, {**state, **update})
    hint = f"提醒：{state['warnings'][0]}。" if state.get("warnings") else ""
    await d.emit.say(
        "chief",
        f"第 {PIECE_ORDER.index(piece) + 1} 块「{PIECE_NAMES[piece]}」好了。{hint}请你看看，没问题就点「确认这一块」。",
    )
    await d.emit.status("chief", f"等你确认：{PIECE_NAMES[piece]}")
    return update


async def _confirm_piece(state: SetupState, d: GraphDeps) -> Command:
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    piece = state["piece"]
    pieces = {**_pieces(state), piece: "confirmed"}
    update = {
        **setup,
        "pieces": pieces,
        "warnings": [],
        "suggestions": [],
        "unlock_requests": [],
        "candidates": None,
        "op": {},
        **_override_update([], []),
    }
    if piece == "first_volume":
        await mark_progress(d, {**state, **update})
        return Command(goto="finalize", update=update)
    following = PIECE_ORDER[PIECE_ORDER.index(piece) + 1]
    queue = list(PIECES[following])
    resync = state.get("resync") or []
    instructions = {target: SYNC_INSTRUCTIONS[target] for target in queue if target in resync}
    update.update(
        piece=following,
        queue=queue,
        instructions=instructions,
        instruction_sources={},
        instruction_fallbacks={},
        pieces={**pieces, following: "drafting"},
        resync=[target for target in resync if target not in queue],
    )
    await mark_progress(d, {**state, **update})
    return Command(goto="intake", update=update)


async def piece_gate_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["intake", "piece_gate", "node_op", "finalize"]]:
    # 必须先 interrupt，恢复此节点会从头执行；所有数据库写入和发言都放在后面。
    decision = interrupt(
        {
            "kind": "setup_piece",
            "piece": state["piece"],
            "round": state.get("round", 0),
            "warnings": state.get("warnings") or [],
            "decisions": [
                choice for target in PIECES[state["piece"]] for choice in (state.get("decisions") or {}).get(target, [])
            ],
            "suggestions": state.get("suggestions") or [],
            "unlock_requests": state.get("unlock_requests") or [],
            "candidates": state.get("candidates") or None,
        }
    )
    d = runtime.context
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    state = await live_state({**state, **setup}, d)
    action, piece = decision.get("action"), state["piece"]
    if action in {"confirm", "delegate"}:
        if piece == "nodes" and any(n["status"] == "empty" for n in setup["spine"]["nodes"]):
            return Command(goto="node_op", update={**setup, "op": {"kind": "fill_all", "then": "confirm"}})
        return await _confirm_piece(state, d)
    if action in {"candidates", "fill"}:
        return Command(
            goto="node_op",
            update={
                **setup,
                "op": {"kind": action, "node_id": decision.get("node_id"), "feedback": decision.get("feedback", "")},
            },
        )
    feedback = (decision.get("feedback") or "").strip()
    flips = [f"把「{flip['topic']}」改成「{flip['choice']}」" for flip in decision.get("flips") or []]
    if not decision.get("requirement_saved"):
        async with d.sessionmaker() as session:
            if feedback:
                await add_requirement(session, d.book_id, feedback, "note")
            for flip in decision.get("flips") or []:
                await add_requirement(session, d.book_id, f"「{flip['topic']}」改成：{flip['choice']}", "answer")
            await session.commit()
        state = await live_state(state, d)
    if action in {"reopen", "unlock"}:
        reopened = decision.get("piece")
        if (
            reopened not in PIECE_ORDER
            or PIECE_ORDER.index(reopened) >= PIECE_ORDER.index(piece)
            or _pieces(state)[reopened] != "confirmed"
        ):
            raise ValueError("只能重新打开当前块之前已确认的块")
        span = PIECE_ORDER[PIECE_ORDER.index(reopened) : PIECE_ORDER.index(piece) + 1]
        pieces = _pieces(state)
        for p in span:
            pieces[p] = "todo"
        pieces[reopened] = "drafting" if feedback else "waiting"
        resync = list(
            dict.fromkeys(
                [*(state.get("resync") or []), *(t for p in span[1:] for t in PIECES[p] if has_part(state, t))]
            )
        )
        queue, instructions = (
            cascade({PIECES[reopened][0]: feedback}, {**state, "piece": reopened}) if feedback else ([], {})
        )
        update = {
            **setup,
            "piece": reopened,
            "pieces": pieces,
            "queue": queue,
            "instructions": instructions,
            "instruction_sources": {t: [feedback] for t in queue},
            "instruction_fallbacks": {},
            "resync": resync,
            "warnings": [],
            "suggestions": [],
            "unlock_requests": [],
            "candidates": None,
            "piece_reviewed": {k: v for k, v in (state.get("piece_reviewed") or {}).items() if k not in span},
            "piece_revised": {k: v for k, v in (state.get("piece_revised") or {}).items() if k not in span},
            "round": state.get("round", 0) + 1,
            "phase": "author_revise",
            **_override_update([], []),
        }
        if reopened == "nodes" and feedback:
            # 解锁只是打开块，不自动授权铁钉；仍须分析作者本轮意见是否点名。
            snapshot = deepcopy((setup.get("spine") or {}).get("nodes") or [])
            result = await editorial.triage_feedback(
                d.llm, setup, requirements(state), feedback, locked=format_locked({**state, **update})
            )
            await d.emit.say("chief", result.remark)
            raw = result.instructions()
            if raw.get("spine") and raw["spine"] != SYNC_INSTRUCTIONS["spine"]:
                update["instructions"]["spine"] = "\n".join([feedback, raw["spine"]])
                update.update(_override_update(_pinned_overrides(result, snapshot), [feedback]))
        await mark_progress(d, {**state, **update})
        return Command(goto="intake" if feedback else "piece_gate", update=update)
    if action != "revise":
        raise ValueError("未知的拼图操作")
    prefix = ""
    allowed = []
    if decision.get("node_id"):
        match = next(
            ((i, n) for i, n in enumerate(setup["spine"]["nodes"], 1) if n.get("id") == decision["node_id"]), None
        )
        if match is None:
            raise ValueError("节点已不存在")
        prefix = f"只改节点 {match[0]}「{match[1]['title']}」："
        allowed = [match[1]["id"]]
    combined = prefix + "\n".join([feedback, *flips]).strip()
    requests = list(state.get("unlock_requests") or [])
    if not feedback and (prefix or flips):
        raw = {PIECES[piece][0]: combined}
    else:
        snapshot = deepcopy((setup.get("spine") or {}).get("nodes") or [])
        result = await editorial.triage_feedback(
            d.llm, setup, requirements(state), combined, locked=format_locked(state)
        )
        await d.emit.say("chief", result.remark)
        requests = _unlock_requests(state, result)
        raw = {target: instruction for target, instruction in result.instructions().items() if target in PIECES[piece]}
        if raw.get("spine") and raw["spine"] != SYNC_INSTRUCTIONS["spine"]:
            allowed.extend(_pinned_overrides(result, snapshot))
    if prefix and piece == "nodes":
        # node_id 是作者的直接授权，不依赖分派模型是否再次复述这个节点。
        raw["spine"] = "\n".join(filter(None, [combined, raw.get("spine")]))
    queue, instructions = cascade(raw, state)
    await _explain_unlocks(d, requests)
    update = {
        **setup,
        "queue": queue,
        "instructions": instructions,
        "unlock_requests": requests,
        "instruction_sources": {
            t: [feedback, *[f"「{f['topic']}」改成：{f['choice']}" for f in decision.get("flips") or []]] for t in queue
        },
        "instruction_fallbacks": {},
        "round": state.get("round", 0) + 1,
        "phase": "author_revise",
        "candidates": None,
        **_override_update(allowed if "spine" in queue else [], [feedback]),
    }
    return Command(goto="intake" if queue else "piece_gate", update=update)


def _slot(nodes: list[dict], index: int, kind: str, feedback: str) -> str:
    node = nodes[index]
    previous = f"节点 {index}「{nodes[index - 1]['title']}」" if index else "全书起点"
    following = f"节点 {index + 2}「{nodes[index + 1]['title']}」" if index + 1 < len(nodes) else "全书终点"
    if feedback:
        return f"节点 {index + 1}，作者写了一句：「{feedback}」。以作者的想法为核心，补成 1 个完整节点。前一个是{previous}，后一个是{following}。"
    if kind == "candidates":
        return f"替换节点 {index + 1}「{node['title']}」（作者想换一个）。前一个是{previous}，后一个是{following}。给出 3 个候选。"
    return f"节点 {index + 1}（目前留空），夹在{previous}和{following}之间。补成 1 个节点。"


async def node_op_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["piece_gate", "intake", "finalize"]]:
    d = runtime.context
    state = await live_state(state, d)
    op = state.get("op") or {}
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    nodes = setup["spine"]["nodes"]
    selected = (
        [n["id"] for n in nodes if n["status"] == "empty"] if op.get("kind") == "fill_all" else [op.get("node_id")]
    )
    candidates = None
    for node_id in selected:
        await d.check_cancel()
        index = next((i for i, n in enumerate(nodes) if n["id"] == node_id), None)
        if index is None:
            raise ValueError("节点已不存在")
        node = nodes[index]
        feedback = op.get("feedback", "")
        if node["status"] == "pinned" and op.get("kind") != "candidates":
            raise ValueError("铁钉节点不能由编辑部改写")
        if feedback and op.get("kind") != "candidates":
            node["origin"] = "author"
        result = await editorial.draft_node_slot(
            d.llm,
            setup["concept"],
            {**setup["spine"], "nodes": nodes},
            _slot(nodes, index, op.get("kind", "fill"), feedback),
            requirements(state),
        )
        values = []
        for draft in result.nodes:
            value = draft.model_dump(exclude={"ref", "kind"})
            value["techniques"] = clean_techniques(value.get("techniques"))
            values.append(value)
        if not values:
            raise ValueError("没有生成可用的节点")
        if op.get("kind") == "candidates":
            candidates = {"node_id": node_id, "nodes": values[:3]}
        else:
            node.update(values[0], status="pinned" if feedback else "pencil")
            async with d.sessionmaker() as session:
                await setup_store.save_nodes(session, d.book_id, nodes)
                await session.commit()
        await d.emit.say(
            "chief",
            f"节点 {index + 1} 给你出了 {len(values[:3])} 个候选。"
            if op.get("kind") == "candidates"
            else f"节点 {index + 1} 已经补好了。",
        )
    async with d.sessionmaker() as session:
        setup = await setup_store.load_setup(session, d.book_id)
    update = {**setup, "candidates": candidates, "op": {}, "warnings": piece_warnings("nodes", setup)}
    if op.get("then") == "confirm":
        return await _confirm_piece({**state, **update}, d)
    return Command(goto="piece_gate", update=update)


def build_setup_graph() -> StateGraph:
    graph = StateGraph(SetupState, context_schema=GraphDeps)
    graph.add_node("directions", directions_node)
    graph.add_node("directions_gate", directions_gate_node)
    graph.add_node("interview", interview_node)
    graph.add_node("interview_gate", interview_gate_node)
    graph.add_node("intake", intake_node)
    graph.add_node("concept", concept_node)
    graph.add_node("lore", lore_node)
    graph.add_node("spine", spine_node)
    graph.add_node("threads", threads_node)
    graph.add_node("outline", outline_node)
    graph.add_node("first_volume", first_volume_node)
    graph.add_node("critique", critique_node)
    graph.add_node("persist", persist_node)
    graph.add_node("author_gate", author_gate_node)
    graph.add_node("triage", triage_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("piece_check", piece_check_node)
    graph.add_node("piece_persist", piece_persist_node)
    graph.add_node("piece_gate", piece_gate_node)
    graph.add_node("node_op", node_op_node)

    graph.add_conditional_edges(START, route_start, ["directions", "interview", "intake"])
    graph.add_edge("directions", "directions_gate")
    graph.add_edge("interview", "interview_gate")
    # 每一步做完都先经过 intake，读作者的插话，再决定下一步
    for source in ("interview_gate", *ORDER, "critique", "triage"):
        graph.add_edge(source, "intake")
    graph.add_conditional_edges("intake", route_next, {n: n for n in (*ORDER, "critique", "persist", "piece_check")})
    graph.add_edge("piece_persist", "piece_gate")
    graph.add_edge("persist", "author_gate")
    graph.add_edge("finalize", END)
    return graph
