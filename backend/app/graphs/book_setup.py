"""开书五步：定调、主角、世界与人、第一段、第一卷，支持逐块与一口气。"""

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
    format_opening,
    format_previous_directions,
    format_protagonist,
    format_requirements,
    format_secrets,
    format_segment_info,
    format_spine,
    format_target_node,
    format_threads,
    format_volume_card,
    planned_chapters,
)
from app.agents.glossary import clean_techniques, glossary_block
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts, relevant_ledger, unit_hint
from app.agents.playbook import playbook_text
from app.agents.setup_puzzle import (
    NODE_CONTENT,
    ORDER,
    PIECE_NAMES,
    PIECE_ORDER,
    PIECES,
    QUESTIONS,
    clean_reveals,
    normalize_segment,
    normalize_volumes,
    normalize_world,
    piece_checks,
)
from app.book_settings import settings_of
from app.graphs.deps import GraphDeps
from app.models import Book, MeetingMessage, Volume
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
    "concept": "定调",
    "protagonist": "主角卡",
    "world": "世界与人",
    "segment": "第一段的走向",
    "volumes": "第一段的分卷与线索",
    "first_volume": "第一卷卷纲",
}
SYNC_INSTRUCTIONS = {
    "protagonist": "根据修改后的定调同步检查主角卡；作者定下的和不受影响的部分保持原样。",
    "world": "根据修改后的定调和主角卡同步检查世界、第一张地图和这里的人；主角卡里的姓名和在乎的人要对得上；不受影响的部分保持原样。",
    "segment": "根据修改后的上游内容同步检查第一段的走向：开篇、目标、读者等什么、揭开什么、终点和全书方向，铁钉保持原样；不受影响的部分保持原样。",
    "volumes": "根据修改后的第一段走向同步检查分卷、线索和人物出场；不受影响的部分保持原样。",
    "first_volume": "根据修改后的上游内容同步检查第一卷卷纲：这一卷想做成什么、卷首处境、剧情单元和开篇落地；不受影响的部分保持原样。",
}


REVIEW_FOCUS = {
    "protagonist": "【这次审什么】只审「主角卡」，其他部分只作参考，不要对它们提问题。\n重点查：驱动力（开局动机、长线追求、情感根源）够不够具体，长线追求是不是只写了「变强」；驱动力、金手指、核心循环是不是一套；金手指一句话说不说得清，限制能不能逼主角冒险或做选择；起点有没有提前写死境界名称；性格、底线、说话方式能不能让人物立起来。\n题目键（填进 question）：start 起点、drive 驱动力、person 性格底线与说话方式、finger 金手指、flaw_arc 软肋与成长终点、cared 在乎的人、interlock 咬合检查。",
    "segment": "【这次审什么】只审「第一段的走向」和「第一段的分卷、线索与人物出场」，其他部分只作参考，不要对它们提问题。\n重点查：开篇是不是从冲突或异常切入，前 3 章有没有小爽点和钩子；这一段的目标具不具体、有没有期限或对手；终点是不是这一段的最高潮，能不能把主角推向下一张地图或下一个追求；第一段有没有兑现定调里的核心卖点，核心循环有没有完整转一圈；读者等的那件事明不明确；分卷和人物出场合不合理。远处只要有方向，不要因为远处没写细就提问题。\n题目键（填进 question）：opening 开篇、goal 这一段的目标、wait 读者等什么、reveal 揭开什么、end 这一段的终点、cast 人物出场、volumes 分卷、direction 全书方向。",
    "first_volume": "【这次审什么】审整套开书方案，重点看第一卷卷纲，以及各部分之间对不对得上。\n重点查：第一卷想做成什么是不是第一段目标的一步；卷首处境和卷末高潮；每个剧情单元的核心循环有没有转起来；第一个单元有没有把开篇落地；作者的要求是否全部落实；主角卡、世界与人、第一段之间有没有矛盾。\n题目键（第一卷的问题填进 question）：want 这一卷想做成什么、pressure 卷首处境、climax 卷末高潮与结果、rival 这一卷的对手、units 剧情单元、growth 主角的成长、newcomers 新登场的人、landing 开篇落地。其他部分的问题，question 留空。",
}


def length_question(chapter_words: int | None = None) -> dict:
    """按本书每章字数估算五档篇幅，章数四舍五入到十位。"""
    chapter_words = chapter_words or 3000
    options = []
    for total, label in ((50, "短篇"), (100, "中篇"), (200, "长篇"), (300, "长篇"), (500, "超长篇")):
        chapters = (total * 10000 + 5 * chapter_words) // (10 * chapter_words) * 10
        options.append(
            f"500 万字以上（{label}，约 {chapters} 章起）"
            if total == 500
            else f"约 {total} 万字（{label}，约 {chapters} 章）"
        )
    return {
        "question": "这本书打算写多长？",
        "options": options,
        "recommended": 2,
        "chapter_words": chapter_words,
    }


class SetupState(TypedDict, total=False):
    mode: Literal["puzzle", "oneshot"]
    reference: str
    directions: list[dict]
    previous_directions: dict
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
    flow: int
    check_notes: list[dict]
    check_notes_by_step: dict[str, list[dict]]
    review_notes: list[dict]
    flags: dict[str, list[str]]
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
    protagonist: dict
    world: dict
    segment: dict
    volumes: dict
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
        "flow": 2,
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
        "check_notes": [],
        "check_notes_by_step": {},
        "review_notes": [],
        "flags": {},
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
    if target == "segment":
        return bool(value.get("nodes"))
    if target == "volumes":
        return bool(value.get("volumes"))
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
    direction = state.get("direction") or {}
    if selected_title := direction.get("title"):
        direction = dict(direction)
        if f"书名用《{selected_title}》" in deleted:
            # 作者编辑或删除了原选名要求，检查点不能把已撤销的硬约束带回来。
            direction.pop("title", None)
        elif book and (book.concept or {}).get("title") and book.concept["title"] != selected_title:
            # 初次生成前没有已存概念；此后手动保存的新书名优先，不能永久锁在开书时的候选。
            direction["title"] = book.concept["title"]
            if current.get("concept"):
                current["concept"] = {**current["concept"], "title": book.concept["title"]}
        current["direction"] = direction
    previous = state.get("previous_directions") or {}
    if previous.get("feedback") in deleted:
        current["previous_directions"] = {**previous, "feedback": ""}
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
    revoked_segment = False
    for target in list(instructions):
        if legacy_author or any(text in deleted for text in sources.get(target, [])):
            revoked_segment |= target == "segment"
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
    if (
        revoked_segment
        or not instructions.get("segment")
        or instructions.get("segment") == SYNC_INSTRUCTIONS["segment"]
    ):
        allowed = []
    current.update(
        pinned_overrides=allowed,
        pinned_override_sources={node_id: override_sources.get(node_id, []) for node_id in allowed},
    )
    if settings.get("chapter_words") and current.get("concept"):
        current["concept"] = {**current["concept"], "chapter_words": settings["chapter_words"]}
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
    progress = {
        "flow": 2,
        "mode": state.get("mode", "oneshot"),
        "current": state.get("piece"),
        "pieces": _pieces(state),
    }
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        if book is not None:
            book.setup_progress = progress
            await session.commit()
    await publish(d.redis, d.book_id, "book", {"id": str(d.book_id), "setup_progress": progress})


def normalization_update(state: SetupState, target: str, notes: list[dict]) -> dict:
    """本块用于 flags 的说明和一口气模式按步保留的说明，共用原文。"""
    by_step = {**(state.get("check_notes_by_step") or {}), target: notes}
    current = [item for step in PIECES[_piece_of(target)] for item in by_step.get(step, [])]
    return {"check_notes": current, "check_notes_by_step": by_step}


def all_program_warnings(state: SetupState) -> list[str]:
    by_step = state.get("check_notes_by_step") or {}
    setup = setup_of(state)
    warnings = []
    for piece in PIECE_ORDER:
        notes = [item for target in PIECES[piece] for item in by_step.get(target, [])]
        for item in [*notes, *piece_checks(piece, setup)]:
            warnings.append(f"【{PIECE_NAMES[piece]}】{item['text']}")
    return list(dict.fromkeys(warnings))


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
        d.llm,
        state["idea"],
        state.get("style_reference", ""),
        requirements(state),
        previous=format_previous_directions(state.get("previous_directions")),
    )
    directions = [item.model_dump() for item in result.directions[:3]]
    for item in directions:
        item["techniques"] = clean_techniques(item.get("techniques"))
    recommended = min(max(0, result.recommended), max(0, len(directions) - 1))
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"开书方向：{len(directions)} 个",
        {
            "type": "directions",
            "data": {"reference": result.reference, "directions": directions, "recommended": recommended},
        },
    )
    return {
        "reference": result.reference,
        "directions": directions,
        "recommended": recommended,
        "piece": "concept",
        "pieces": pieces,
    }


async def directions_gate_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["directions", "intake"]]:
    # 此处只读设置；恢复时节点从头执行，数据库写入仍全部放在 interrupt 之后。
    async with runtime.context.sessionmaker() as session:
        book = await session.get(Book, runtime.context.book_id)
        chapter_words = settings_of(book).get("chapter_words") if book else None
    decision = interrupt(
        {
            "kind": "setup_directions",
            "flow": 2,
            "reference": state.get("reference", ""),
            "directions": state.get("directions") or [],
            "recommended": state.get("recommended", 0),
            "length": length_question(chapter_words),
        }
    )
    if decision.get("action") == "redo":
        if not decision.get("requirement_saved") and decision.get("feedback", "").strip():
            async with runtime.context.sessionmaker() as session:
                await add_requirement(session, runtime.context.book_id, decision["feedback"].strip(), "note")
                await session.commit()
        return Command(
            goto="directions",
            update={
                "previous_directions": {
                    "reference": state.get("reference", ""),
                    "directions": deepcopy(state.get("directions") or []),
                    "feedback": decision.get("feedback", "").strip(),
                }
            },
        )
    directions = state.get("directions") or []
    choice = decision.get("choice")
    if not isinstance(choice, int) or not 0 <= choice < len(directions):
        raise ValueError("请选择有效的开书方向")
    direction = {**directions[choice], "mix": decision.get("mix", ""), "length": decision.get("length", "")}
    title = decision.get("title")
    if title is not None:
        if title not in (direction.get("titles") or []):
            raise ValueError("请选择这个方向里的书名候选")
        direction["title"] = title
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
            if title is not None:
                await add_requirement(session, runtime.context.book_id, f"书名用《{title}》", "answer")
            await session.commit()
    return Command(goto="intake", update={"direction": direction, "queue": ["concept"]})


def route_start(state: SetupState) -> str:
    if state.get("mode") == "puzzle":
        return "intake" if state.get("direction") or state.get("concept") else "directions"
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
        **(_override_update([], []) if target == "segment" else {}),
    }


async def interview_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await mark_progress(d, state)
    await d.emit.status("chief", "主编动笔前想先问你几个问题…")
    result = await editorial.interview(d.llm, state["idea"], state.get("style_reference", ""), requirements(state))
    questions = [length_question((state.get("settings") or {}).get("chapter_words"))]
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
    answer = interrupt({"kind": "setup_questions", "flow": 2, "questions": state.get("questions") or []})
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
    if (state.get("concept") or {}).get("protagonist_hook") and "protagonist_hook" not in concept:
        concept["protagonist_hook"] = state["concept"]["protagonist_hook"]
    title = (state.get("direction") or {}).get("title")
    if title and concept["title"] != title:
        concept["alt_titles"] = list(
            dict.fromkeys([concept["title"], *(alt for alt in concept.get("alt_titles") or [] if alt != title)])
        )
        concept["title"] = title
    if (state.get("settings") or {}).get("chapter_words"):
        concept["chapter_words"] = state["settings"]["chapter_words"]
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"书的概念：《{concept['title']}》", {"type": "concept", "data": concept})
    return await _finished(d, state, "concept", concept, result)


async def protagonist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "protagonist")
    await d.emit.status("chief", "主编正在修改主角卡…" if instruction else "主编正在写主角卡…")
    result = await editorial.draft_protagonist(
        d.llm,
        state["idea"],
        state["concept"],
        requirements(state),
        current,
        instruction,
        chosen_direction=format_direction_choice(state.get("direction") or {}) if state.get("mode") == "puzzle" else "",
    )
    protagonist = result.model_dump(exclude={"remark", "decisions"})
    for key in ("escalation", "finger_later"):
        protagonist[key] = (state.get("protagonist") or {}).get(key, "")
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"主角卡：{protagonist['name']}", {"type": "protagonist", "data": protagonist})
    return await _finished(d, state, "protagonist", protagonist, result)


async def world_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "world")
    await d.emit.status(
        "lorekeeper", "设定师正在修改世界与人…" if instruction else "设定师正在搭建世界、第一张地图和这里的人…"
    )
    result = await editorial.draft_world(
        d.llm, state["concept"], state.get("protagonist") or {}, requirements(state), current, instruction
    )
    world, notes = normalize_world(
        {
            **result.model_dump(exclude={"remark", "decisions"}),
            "mystery_answer": (state.get("world") or {}).get("mystery_answer", ""),
        },
        state.get("protagonist") or {},
    )
    await d.emit.say("lorekeeper", result.remark)
    maps = world.get("maps") or []
    name = maps[0].get("name", "") if maps else ""
    await d.emit.artifact(
        "lorekeeper",
        f"世界与人：第一张地图「{name}」，人物 {len(world['characters'])} 位",
        {"type": "world", "data": world},
    )
    return {**await _finished(d, state, "world", world, result), **normalization_update(state, "world", notes)}


def volume_hint(concept: dict, segment: dict) -> str:
    parts = []
    if concept.get("target_length"):
        parts.append(f"全书计划约 {concept['target_length']} 万字")
    chapters = planned_chapters(concept)
    if chapters:
        parts.append(f"约 {chapters} 章（每章约 {concept.get('chapter_words') or 3000} 字）")
    length = "、".join(parts)
    if concept.get("target_volumes"):
        length += ("，" if length else "") + f"粗估分 {concept['target_volumes']} 卷"
    nodes = segment.get("nodes") or []
    endpoint = nodes[1] if len(nodes) > 1 else {}
    end_hint = f"这一段的终点约在第 {endpoint['volume']} 卷。" if endpoint.get("volume") else ""
    return "卷号从第 1 卷开始。" + (length + "；" if length else "") + end_hint + "每卷通常 25-60 万字。"


async def volumes_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "volumes")
    await d.emit.status(
        "chief", "主编正在修改第一段的分卷与线索…" if instruction else "主编正在给第一段分卷、排线索和人物出场…"
    )
    result = await editorial.split_segment(
        d.llm,
        state["concept"],
        state.get("protagonist") or {},
        state.get("world") or {},
        state.get("segment") or {},
        requirements(state),
        current,
        instruction,
        playbook=playbook_text(
            state.get("concept"), "outline", selection=(state.get("settings") or {}).get("playbook", "auto")
        ),
        glossary=glossary_block(),
        volume_hint=volume_hint(state["concept"], state.get("segment") or {}),
        threads="（还没有线索，这是第一段）",
    )
    volumes, segment, notes = normalize_volumes(
        result.model_dump(exclude={"remark", "decisions"}),
        state.get("segment") or {},
        (state.get("world") or {}).get("characters") or [],
        start=1,
    )
    await d.emit.say("chief", result.remark)
    total = sum(volume.get("chapter_count") or 0 for volume in volumes["volumes"])
    await d.emit.artifact(
        "chief", f"第一段分 {len(volumes['volumes'])} 卷，约 {total} 章", {"type": "segment_volumes", "data": volumes}
    )
    return {
        **await _finished(d, state, "volumes", volumes, result),
        "segment": segment,
        **normalization_update(state, "volumes", notes),
    }


async def segment_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "segment")
    previous_nodes = deepcopy((state.get("segment") or {}).get("nodes") or [])
    allowed = set(state.get("pinned_overrides") or [])
    if state.get("phase") == "auto_revise" or instruction == SYNC_INSTRUCTIONS["segment"]:
        allowed.clear()
    # 卡片按 ID 授权后也显式告诉模型；始终按本次节点提示词的序号，不沿用旧序号。
    if allowed and instruction:
        instruction += "\n" + "\n".join(
            f"作者要求改动铁钉节点 {i}，只按作者本轮意见修改，改完仍是铁钉。"
            for i, node in enumerate(previous_nodes, 1)
            if node.get("id") in allowed and node.get("status") == "pinned"
        )
    await d.emit.status(
        "chief", "主编正在修改第一段的走向…" if instruction else "主编正在规划第一段：开篇、目标、终点和全书方向…"
    )
    result = await editorial.draft_segment(
        d.llm,
        state["concept"],
        state.get("protagonist") or {},
        state.get("world") or {},
        requirements(state),
        current,
        instruction,
        playbook=playbook_text(
            state.get("concept"), "nodes", selection=(state.get("settings") or {}).get("playbook", "auto")
        ),
        glossary=glossary_block(),
    )
    segment, notes = normalize_segment(
        result.model_dump(exclude={"remark", "decisions"}),
        previous_nodes,
        (state.get("world") or {}).get("characters") or [],
        state.get("segment") or {},
        world=state.get("world") or {},
        pinned_overrides=allowed,
        existing_ledger=setup_store.ledger_of(setup_of(state)),
    )
    remapped = setup_store.remap_node_refs(setup_of(state), previous_nodes, segment["nodes"])
    segment["foreshadowings"] = remapped["segment"].get("foreshadowings") or []
    await d.emit.say("chief", result.remark)
    previous_by_id = {node.get("id"): node for node in previous_nodes if node.get("id")}
    for i, node in enumerate(segment["nodes"], 1):
        previous = previous_by_id.get(node.get("id"), {})
        if (
            node.get("id") in allowed
            and previous.get("status") == "pinned"
            and any(node.get(key) != previous.get(key) for key in NODE_CONTENT)
        ):
            await d.emit.say("chief", f"按你的意思改了铁钉节点 {i}「{node.get('title', '')}」，它还是铁钉。")
    endpoint = segment["nodes"][1] if len(segment["nodes"]) > 1 else {}
    await d.emit.artifact(
        "chief", f"第一段：走到节点 2「{endpoint.get('title', '')}」", {"type": "segment", "data": segment}
    )
    return {
        **{key: remapped[key] for key in ("volumes", "first_volume") if key in state},
        **await _finished(d, state, "segment", segment, result),
        **normalization_update(state, "segment", notes),
        "node_snapshot": [node.get("id") for node in previous_nodes],
    }


def first_volume_blocks(state: SetupState) -> dict[str, str]:
    """开书第一卷只从已规划的第一段取材料。"""
    volumes_part = state.get("volumes") or {}
    volumes = volumes_part.get("volumes") or []
    card = next((v for v in volumes if v.get("index") == 1), volumes[0] if volumes else {})
    following = next((v for v in volumes if v.get("index") == 2), None)
    chapter_count = int(card.get("chapter_count") or 0)
    world = state.get("world") or {}
    segment = state.get("segment") or {}
    nodes = segment.get("nodes") or []
    info = (nodes[1].get("segment") or {}) if len(nodes) > 1 else {}
    opening_event = next((n.get("event", "") for n in nodes if n.get("kind") == "opening"), "（暂无）")
    hero = next((person for person in world.get("characters") or [] if person.get("role_type") == "主角"), None)
    return {
        "volume_index": "1",
        "concept": format_concept(state.get("concept") or {}),
        "spine": format_spine(segment, world),
        "target_node": format_target_node(card, nodes),
        "segment": format_segment_info(info, world) if info else "（暂无）",
        "protagonist": format_protagonist(state.get("protagonist") or {}, hero),
        "opening": format_opening(info.get("opening")),
        "secrets": format_secrets(segment.get("secrets") or []),
        "glossary": glossary_block(),
        "threads": format_threads(volumes_part, volume=1),
        "volume": format_volume_card(card),
        "neighbors": "上一卷：无（这是第一卷）\n下一卷："
        + (format_volume_card(following) if following else "无（这一段只有一卷）"),
        "story_so_far": f"还没开写，这是第一卷。开篇设计：{opening_event}",
        "used_climaxes": "（暂无）",
        "characters": "\n".join(format_character_state(c) for c in world.get("characters", [])) or "（暂无）",
        "ledger": format_ledger(relevant_ledger(setup_store.ledger_of(setup_of(state)), 1)),
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
    units = clean_reveals(units, (state.get("segment") or {}).get("secrets") or [])
    for unit in units:
        unit["techniques"] = clean_techniques(unit.get("techniques"))
    first_volume = {
        "want": plan.get("want", ""),
        "pressure": plan.get("pressure", ""),
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
    warnings = all_program_warnings(state)
    checks = requirements(state) + ("\n\n【程序提醒】\n" + "\n".join(warnings) if warnings else "")
    result = await editorial.critique_setup(
        d.llm,
        state["idea"],
        checks,
        setup_of(state),
        selection=(state.get("settings") or {}).get("playbook", "auto"),
        locked=format_locked(state),
        focus=REVIEW_FOCUS["first_volume"],
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
            "warnings": warnings,
            "queue": queue,
            "instructions": instructions,
            "instruction_sources": {},
            "instruction_fallbacks": {},
            **_override_update([], []),
            "phase": "auto_revise",
            "auto_revised": True,
        }
    return {"warnings": warnings, "queue": [], "instructions": {}, "phase": "reviewed", **_override_update([], [])}


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
    done = {t: state[t] for t in ORDER if has_part(state, t) and (t not in queue or t == "segment")}
    if not done:
        if any(not note_thread(payload) for _, _, payload in rows):
            await d.emit.say("chief", "收到，接下来就按你说的写。")
        await _reply_to_notes(d, rows)
        return update

    await d.check_cancel()
    await d.emit.status("chief", "主编正在看你的插话…")
    todo = [t for t in ORDER if t not in done]
    snapshot = deepcopy((done.get("segment") or {}).get("nodes") or [])
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
        if "segment" in raw and "segment" in extra_queue:
            sources = [content for _, content, payload in rows if not (payload or {}).get("settings_change")]
            allowed = (
                _pinned_overrides(result, snapshot)
                if sources and raw["segment"] != SYNC_INSTRUCTIONS["segment"]
                else []
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
    return {
        **saved,
        "warnings": all_program_warnings({**state, **saved}),
        "queue": [],
        "instructions": {},
        **_override_update([], []),
    }


async def author_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> Command[Literal["finalize", "triage"]]:
    # interrupt 之前不要放有副作用的代码：恢复执行时本节点会从头重跑
    decision = interrupt(
        {
            "kind": "setup_review",
            "flow": 2,
            "warnings": state.get("warnings") or [],
            "round": state.get("round", 0),
            "title": (state.get("concept") or {}).get("title", ""),
        }
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
    snapshot = deepcopy((state.get("segment") or {}).get("nodes") or [])
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
            if raw.get("segment") and raw["segment"] != SYNC_INSTRUCTIONS["segment"]
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
        "check_notes": [],
        "review_notes": [],
        "flags": {},
        "suggestions": [],
        "unlock_requests": [],
        "candidates": None,
        **_override_update([], []),
    }
    await mark_progress(d, {**state, **update})
    return update


def check_payload(piece: str, setup: dict, notes: list[dict], review: list[dict] | None = None) -> dict:
    checks = [*notes, *piece_checks(piece, setup)]
    warnings = list(dict.fromkeys(item["text"] for item in checks))
    flags: dict[str, list[str]] = {}
    keys = {key for key, _ in QUESTIONS[piece]}
    for item in checks:
        if item.get("question") in keys:
            flags.setdefault(item["question"], []).append(item["text"])
    for item in review or []:
        if item.get("question") in keys:
            flags.setdefault(item["question"], []).append(f"审稿：{item['problem']}——{item['suggestion']}")
    return {"warnings": warnings, "flags": {key: list(dict.fromkeys(values)) for key, values in flags.items()}}


async def piece_check_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["intake", "piece_persist"]]:
    d = runtime.context
    state = await live_state(state, d)
    piece = state["piece"]
    notes = state.get("check_notes") or []
    update = {**check_payload(piece, setup_of(state), notes, state.get("review_notes")), **_override_update([], [])}
    review = piece == "first_volume" or (
        piece in {"protagonist", "segment"} and (state.get("settings") or {}).get("volume_audit", True)
    )
    if review and not (state.get("piece_reviewed") or {}).get(piece):
        await d.check_cancel()
        await d.emit.status("reviewer", f"审稿正在检查「{PIECE_NAMES[piece]}」…")
        completed = {target for p in PIECE_ORDER[: PIECE_ORDER.index(piece) + 1] for target in PIECES[p]}
        setup = {target: state.get(target) or {} for target in ORDER if target in completed}
        checks = requirements(state) + (
            "\n\n【程序提醒】\n" + "\n".join(update["warnings"]) if update["warnings"] else ""
        )
        result = await editorial.critique_setup(
            d.llm,
            state["idea"],
            checks,
            setup,
            selection=(state.get("settings") or {}).get("playbook", "auto"),
            locked=format_locked(state),
            focus=REVIEW_FOCUS[piece],
        )
        await d.emit.say("reviewer", result.remark)
        await d.emit.artifact(
            "reviewer",
            "跨块审稿" if piece == "first_volume" else "单块审稿",
            {"type": "critique", "data": result.model_dump(exclude={"remark"})},
        )
        update["piece_reviewed"] = {**(state.get("piece_reviewed") or {}), piece: True}
        suggestions = list(state.get("suggestions") or [])
        for issue in result.issues:
            if issue.target in locked_steps(state):
                suggestions.append({"target": issue.target, "problem": issue.problem, "suggestion": issue.suggestion})
        update["suggestions"] = list(
            {(item["target"], item["problem"], item["suggestion"]): item for item in suggestions}.values()
        )
        local = [issue for issue in result.issues if issue.target in PIECES[piece]]
        serious = [issue for issue in local if issue.severity in ("high", "medium")]
        revise = serious and not (state.get("piece_revised") or {}).get(piece)
        review_notes = [
            {"question": issue.question, "problem": issue.problem, "suggestion": issue.suggestion}
            for issue in local
            if not revise or issue.severity == "low"
        ]
        update.update(review_notes=review_notes, **check_payload(piece, setup_of(state), notes, review_notes))
        if revise:
            raw = {}
            for issue in serious:
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
        await setup_store.save_piece(session, d.book_id, piece, setup_of(state))
        saved = await setup_store.load_setup(session, d.book_id)
        await setup_store.snapshot(session, d.book_id, d.job_id, state.get("round", 0), "ai", f"piece:{piece}", saved)
        await session.commit()
        saved = await setup_store.load_setup(session, d.book_id)
    update = {**{target: saved[target] for target in PIECES[piece]}, **_override_update([], [])}
    update["pieces"] = {**_pieces(state), piece: "waiting"}
    await mark_progress(d, {**state, **update})
    hint = f"提醒：{state['warnings'][0]}" if state.get("warnings") else ""
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
        "check_notes": [],
        "review_notes": [],
        "flags": {},
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
            "flow": 2,
            "piece": state["piece"],
            "round": state.get("round", 0),
            "warnings": state.get("warnings") or [],
            "flags": state.get("flags") or {},
            "review": state.get("review_notes") or [],
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
        if piece == "segment" and any(n["status"] == "empty" for n in setup["segment"]["nodes"]):
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
            "check_notes": [],
            "review_notes": [],
            "flags": {},
            "suggestions": [],
            "unlock_requests": [],
            "candidates": None,
            "piece_reviewed": {k: v for k, v in (state.get("piece_reviewed") or {}).items() if k not in span},
            "piece_revised": {k: v for k, v in (state.get("piece_revised") or {}).items() if k not in span},
            "round": state.get("round", 0) + 1,
            "phase": "author_revise",
            **_override_update([], []),
        }
        if reopened == "segment" and feedback:
            # 解锁只是打开块，不自动授权铁钉；仍须分析作者本轮意见是否点名。
            snapshot = deepcopy((setup.get("segment") or {}).get("nodes") or [])
            result = await editorial.triage_feedback(
                d.llm, setup, requirements(state), feedback, locked=format_locked({**state, **update})
            )
            await d.emit.say("chief", result.remark)
            raw = result.instructions()
            if raw.get("segment") and raw["segment"] != SYNC_INSTRUCTIONS["segment"]:
                update["instructions"]["segment"] = "\n".join([feedback, raw["segment"]])
                update.update(_override_update(_pinned_overrides(result, snapshot), [feedback]))
        await mark_progress(d, {**state, **update})
        return Command(goto="intake" if feedback else "piece_gate", update=update)
    if action != "revise":
        raise ValueError("未知的拼图操作")
    prefix = ""
    allowed = []
    if decision.get("node_id"):
        match = next(
            ((i, n) for i, n in enumerate(setup["segment"]["nodes"], 1) if n.get("id") == decision["node_id"]), None
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
        snapshot = deepcopy((setup.get("segment") or {}).get("nodes") or [])
        result = await editorial.triage_feedback(
            d.llm, setup, requirements(state), combined, locked=format_locked(state)
        )
        await d.emit.say("chief", result.remark)
        requests = _unlock_requests(state, result)
        raw = {target: instruction for target, instruction in result.instructions().items() if target in PIECES[piece]}
        if raw.get("segment") and raw["segment"] != SYNC_INSTRUCTIONS["segment"]:
            allowed.extend(_pinned_overrides(result, snapshot))
    if prefix and piece == "segment":
        # node_id 是作者的直接授权，不依赖分派模型是否再次复述这个节点。
        raw["segment"] = "\n".join(filter(None, [combined, raw.get("segment")]))
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
        **_override_update(allowed if "segment" in queue else [], [feedback]),
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
    nodes = setup["segment"]["nodes"]
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
            {**setup["segment"], "nodes": nodes},
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
    update = {**setup, "candidates": candidates, "op": {}, **check_payload("segment", setup, [])}
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
    graph.add_node("protagonist", protagonist_node)
    graph.add_node("world", world_node)
    graph.add_node("segment", segment_node)
    graph.add_node("volumes", volumes_node)
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


LEGACY_CONCEPT = "这是按旧流程确认过的定调。按新的定调题补上缺的「核心循环」（作者提过对标作品的，再补上「对标」），其余内容保持原样；原来的「主角钩子」不用再写，下一步「主角」会参考它。"


def restart_state(params: dict, old_values: dict, concept: dict) -> SetupState:
    """只带回作者已选择/确认的材料，不把旧图的步骤和检查点恢复到新图。"""
    mode = params.get("mode", "oneshot")
    state = initial_state(params.get("idea", ""), params.get("style_reference", ""), ask=False, mode=mode)
    if not old_values:
        return state
    if old_values.get("direction"):
        state["direction"] = deepcopy(old_values["direction"])
    if params.get("keep_concept") and concept.get("title"):
        state["concept"] = deepcopy(concept)
        if concept.get("core_loop"):
            state["pieces"]["concept"] = "confirmed"
            state["piece"] = "protagonist"
            state["queue"] = ["protagonist"] if mode == "puzzle" else list(ORDER[1:])
        else:
            state["instructions"] = {"concept": LEGACY_CONCEPT}
    return state
