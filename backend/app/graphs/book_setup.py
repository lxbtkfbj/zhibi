"""开书流程图。

（可选）主编先问作者几个关键问题 → 主编定概念 → 设定师建设定 → 主编定主线骨架（开篇、结局、关键转折）
→ 主编做线索规划（主线、感情线、反派线、谜团线、成长线）→ 主编写全书总纲（分卷卡片 + 长线伏笔）
→ 主编拆第一卷卷纲（剧情单元）→ 审稿挑刺 →（必要时自动修改一轮）→ 存库 → 作者拍板
作者提意见：主编分派修改 → 对应角色修改 → 存库 → 再次拍板；作者批准：定稿。
作者随时可以插话：每做完一步，主编先看有没有新的插话，已完成的部分需要改就先改，之后每一步都按插话来写。
后面各卷的卷纲和每个单元的章纲，在写作流程里写到之前再做（见 write_book）。
"""

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
    format_ledger,
    format_requirements,
    format_spine,
    format_threads,
    format_volume_card,
    planned_chapters,
)
from app.agents.planning import attach_new_foreshadowings, fit_chapter_counts, relevant_ledger, unit_hint
from app.agents.playbook import pick, playbook_text
from app.book_settings import settings_of
from app.graphs.deps import GraphDeps
from app.models import Book, MeetingMessage, Volume
from app.services import setup_store
from app.services.notes import note_prompt, note_thread
from app.services.requirements import (
    active_notes,
    add_requirement,
    deleted_texts,
    import_legacy_checkpoint,
    ingest_notes,
    list_requirements,
)

ORDER = ["concept", "lore", "spine", "threads", "outline", "first_volume"]
TARGET_NAMES = {
    "concept": "概念",
    "lore": "世界观与人物",
    "spine": "主线骨架",
    "threads": "线索",
    "outline": "全书总纲",
    "first_volume": "第一卷卷纲",
}
SYNC_INSTRUCTIONS = {
    "lore": "根据修改后的概念同步调整世界观与人物，保持与新概念一致；不受影响的部分保持原样。",
    "spine": "根据修改后的概念与设定同步检查主线骨架，确保开篇、结局和关键转折与之一致；不受影响的部分保持原样。",
    "threads": "根据修改后的上游内容同步检查线索，确保人物、节拍与之一致；不受影响的部分保持原样。",
    "outline": "根据修改后的上游内容同步检查全书总纲，确保分卷、线索节拍与伏笔与之一致；不受影响的部分保持原样。",
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
    # draft：首次起草；reviewed：审稿通过；auto_revise：按审稿意见修改；author_revise：按作者意见修改
    phase: str
    auto_revised: bool
    feedback: str
    round: int


def initial_state(idea: str, style_reference: str = "", ask: bool = False) -> SetupState:
    return {
        "requirements_ledger_ready": True,
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
    """上游改了，下游要跟着同步：改概念 → 后面全部要检查；改设定 → 主线及之后；以此类推。"""
    targets = {t for t, text in instructions.items() if text.strip() and t in ORDER}
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
    missing = [t for t in ORDER if t not in queue and not has_part(state, t)]
    return [t for t in ORDER if t in queue or t in missing]


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
    for target in list(instructions):
        if legacy_author or any(text in deleted for text in sources.get(target, [])):
            fallback = (state.get("instruction_fallbacks") or {}).get(target)
            if fallback:
                instructions[target] = fallback
            else:
                instructions.pop(target)
    current["instructions"] = instructions
    if settings.get("chapter_words") and state.get("concept"):
        current["concept"] = {**state["concept"], "chapter_words": settings["chapter_words"]}
    return current


def setup_of(state: SetupState) -> dict[str, dict]:
    return {k: state.get(k) or {} for k in ORDER}


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
    origins = {k: v for k, v in (state.get("instruction_sources") or {}).items() if k != target}
    fallbacks = {k: v for k, v in (state.get("instruction_fallbacks") or {}).items() if k != target}
    return {
        target: value,
        "queue": (state.get("queue") or [])[1:],
        "instructions": rest,
        "instruction_sources": origins,
        "instruction_fallbacks": fallbacks,
    }


async def interview_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
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
        d.llm, state["idea"], state.get("style_reference", ""), requirements(state), current, instruction
    )
    concept = result.model_dump(exclude={"remark"})
    if (state.get("settings") or {}).get("chapter_words"):
        concept["chapter_words"] = state["settings"]["chapter_words"]
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", f"书的概念：《{concept['title']}》", {"type": "concept", "data": concept})
    return _finish(state, "concept", concept)


async def lore_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "lore")
    await d.emit.status("lorekeeper", "设定师正在修改世界观与人物…" if instruction else "设定师正在搭建世界观与人物…")
    result = await editorial.draft_lore(d.llm, state["concept"], requirements(state), current, instruction)
    lore = result.model_dump(exclude={"remark"})
    for key in ("anchors", "secrets"):
        if key in (state.get("lore") or {}):
            lore[key] = deepcopy(state["lore"][key])
    await d.emit.say("lorekeeper", result.remark)
    await d.emit.artifact(
        "lorekeeper",
        f"世界观 {len(lore['world_entries'])} 条，人物 {len(lore['characters'])} 位",
        {"type": "lore", "data": lore},
    )
    return _finish(state, "lore", lore)


async def spine_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    current, instruction = _revising(state, "spine")
    await d.emit.status("chief", "主编正在修改主线骨架…" if instruction else "主编正在定主线：开篇、结局和关键转折…")
    result = await editorial.draft_spine(
        d.llm, state["concept"], state["lore"], requirements(state), current, instruction
    )
    # 旧 schema 没有节点 ID、铁钉等字段；进入后续线索与总纲前先恢复作者的硬约束。
    previous_nodes = (state.get("spine") or {}).get("nodes") or []
    spine = setup_store.merge_legacy_spine(result.model_dump(exclude={"remark"}), previous_nodes)
    remapped = setup_store.remap_node_refs(setup_of(state), previous_nodes, spine["nodes"])
    await d.emit.say("chief", result.remark)
    milestones = sum(node["kind"] == "milestone" for node in spine["nodes"])
    await d.emit.artifact("chief", f"主线骨架：{milestones} 个关键转折", {"type": "spine", "data": spine})
    return {
        **{key: remapped[key] for key in ("lore", "outline", "first_volume") if key in state},
        **_finish(state, "spine", spine),
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
        requirements(state),
        current,
        instruction,
        selection=(state.get("settings") or {}).get("playbook", "auto"),
    )
    threads = result.model_dump(exclude={"remark"})
    for t in threads["threads"]:
        t["beats"] = sorted(t["beats"], key=lambda b: b["volume"])
    await d.emit.say("chief", result.remark)
    kinds = "、".join(dict.fromkeys(t["kind"] for t in threads["threads"]))
    await d.emit.artifact("chief", f"线索 {len(threads['threads'])} 条：{kinds}", {"type": "threads", "data": threads})
    return _finish(state, "threads", threads)


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
        state.get("threads") or {},
        requirements(state),
        current,
        instruction,
        selection=(state.get("settings") or {}).get("playbook", "auto"),
    )
    outline = result.model_dump(exclude={"remark"})
    if "expectations" in (state.get("outline") or {}):
        outline["expectations"] = deepcopy(state["outline"]["expectations"])
    # 长线伏笔编号：与当前版本内容相同的沿用原编号，第一卷卷纲引用的编号才不会乱
    previous = setup_store.ledger_of(setup_of(state))
    outline["foreshadowings"] = setup_store.assign_seqs(
        [{**f, "span": "长"} for f in outline["foreshadowings"]], previous
    )
    await d.emit.say("chief", result.remark)
    total = sum(v.get("chapter_count") or 0 for v in outline["volumes"]) or planned_chapters(state["concept"])
    await d.emit.artifact(
        "chief",
        f"全书 {len(outline['volumes'])} 卷"
        + (f"约 {total} 章" if total else "")
        + f"，长线伏笔 {len(outline['foreshadowings'])} 条",
        {"type": "outline", "data": outline},
    )
    return _finish(state, "outline", outline)


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
    fresh = setup_store.assign_seqs(plan["new_foreshadowings"], setup_store.ledger_of(setup_of(state)))
    units, fresh = attach_new_foreshadowings(units, fresh, 1)
    first_volume = {"units": units, "new_foreshadowings": fresh}
    if "new_expectations" in (state.get("first_volume") or {}):
        first_volume["new_expectations"] = deepcopy(state["first_volume"]["new_expectations"])
    await d.emit.say("chief", result.remark)
    await d.emit.artifact(
        "chief",
        f"第一卷拆成 {len(units)} 个剧情单元，新埋伏笔 {len(fresh)} 条",
        {"type": "volume_plan", "data": {"volume": 1, **first_volume}},
    )
    return _finish(state, "first_volume", first_volume)


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
            "phase": "auto_revise",
            "auto_revised": True,
        }
    return {"queue": [], "instructions": {}, "phase": "reviewed"}


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
    done = {t: state[t] for t in ORDER if has_part(state, t) and t not in queue}
    if not done:
        if any(not note_thread(payload) for _, _, payload in rows):
            await d.emit.say("chief", "收到，接下来就按你说的写。")
        await _reply_to_notes(d, rows)
        return update

    await d.check_cancel()
    await d.emit.status("chief", "主编正在看你的插话…")
    todo = [t for t in ORDER if t not in done]
    result = await editorial.absorb_notes(d.llm, done, todo, requirements(state), fresh)
    if any(not note_thread(payload) for _, _, payload in rows):
        await d.emit.say("chief", result.remark)
    raw = {t: text for t, text in result.instructions().items() if t in done}
    if raw:
        extra_queue, extra = cascade(raw)
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
    await d.emit.status("system", "开书方案已整理好，请作者过目并拍板。")
    return {"queue": [], "instructions": {}}


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
    update: dict = {**setup, "feedback": feedback, "round": state.get("round", 0) + 1}
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
    result = await editorial.triage_feedback(d.llm, setup_of(state), requirements(state), state.get("feedback", ""))
    await d.emit.say("chief", result.remark)
    queue, instructions = cascade(result.instructions())
    if queue:
        await d.emit.artifact("chief", "修改分工", {"type": "triage", "data": instructions})
    origins = list(state.get("feedback_sources") or ([state["feedback"]] if state.get("feedback") else []))
    return {
        "queue": queue,
        "instructions": instructions,
        "instruction_sources": {target: origins for target in queue},
        "instruction_fallbacks": {},
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
    return {}


def build_setup_graph() -> StateGraph:
    graph = StateGraph(SetupState, context_schema=GraphDeps)
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

    graph.add_conditional_edges(START, route_start, ["interview", "intake"])
    graph.add_edge("interview", "interview_gate")
    # 每一步做完都先经过 intake，读作者的插话，再决定下一步
    for source in ("interview_gate", *ORDER, "critique", "triage"):
        graph.add_edge(source, "intake")
    graph.add_conditional_edges("intake", route_next, {n: n for n in (*ORDER, "critique", "persist")})
    graph.add_edge("persist", "author_gate")
    graph.add_edge("finalize", END)
    return graph
