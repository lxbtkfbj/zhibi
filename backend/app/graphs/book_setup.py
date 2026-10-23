"""开书新三步：定调、设定库、大纲；数据库始终是作者改动的最终来源。"""

import json
from copy import deepcopy
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from sqlalchemy import func, select

from app.agents import editorial, schemas
from app.agents.context import format_length, format_requirements, format_revision, format_style
from app.agents.setup_puzzle import ORDER, PIECE_NAMES, PIECE_ORDER, PIECES, piece_checks
from app.book_settings import settings_of
from app.graphs.deps import GraphDeps
from app.library_config import BUILTIN_CATEGORIES, CHARACTER_CATEGORY, GOLDFINGER
from app.llm.router import LLMError
from app.models import Book, Character, MeetingMessage, SettingSuggestion, WorldEntry
from app.prompts import render
from app.services import setup_store
from app.services.library_context import existing_text, genre_defaults, load_context
from app.services.meeting import publish
from app.services.notes import note_prompt, note_thread
from app.services.requirements import (
    active_notes,
    active_requirements,
    add_requirement,
    deleted_texts,
    import_legacy_checkpoint,
    ingest_notes,
    requirement_text,
)
from app.services.versions import target_type_of

LENGTHS = (50, 100, 200, 300, 500)


def length_question(chapter_words: int | None = None) -> dict:
    """篇幅五档，推荐第三档；已保存的其他篇幅不受影响。"""
    chapter_words = chapter_words or 3000
    options = []
    for total, label in zip(LENGTHS, ("短篇", "中篇", "长篇", "长篇", "超长篇"), strict=True):
        chapters = (total * 10000 + 5 * chapter_words) // (10 * chapter_words) * 10
        options.append(
            f"500 万字以上（{label}，约 {chapters} 章起）"
            if total == 500
            else f"约 {total} 万字（{label}，约 {chapters} 章）"
        )
    return {"question": "这本书打算写多长？", "options": options, "recommended": 2, "chapter_words": chapter_words}


class SetupState(TypedDict, total=False):
    flow: int
    mode: Literal["puzzle", "oneshot"]
    idea: str
    style_reference: str
    requirements_ledger_ready: bool
    live_requirements: list[str]
    brief: list[str]
    notes: list[str]
    notes_seen: int
    settings: dict
    pitches: list[dict]
    pitch: dict
    benchmark: str
    recommended: int
    previous: str
    previous_feedback: str
    round: int
    piece: str | None
    pieces: dict[str, str]
    queue: list[str]
    instructions: dict[str, str]
    instruction_sources: dict[str, list[str]]
    concept: dict
    settings_focus: dict
    settings_rest: dict
    library: dict
    outline: dict
    outline_chapters: dict
    outline_checks: list[dict]
    locked_names: list[str]
    decisions: dict[str, list[dict]]
    warnings: list[str]
    revised: dict[str, bool]
    dirty_concept: bool
    library_reviewed: bool
    summary: str
    prefill: bool
    combined_gate: bool
    piece_gates: bool
    concept_warnings: list[str]


def initial_state(
    idea: str, style_reference: str = "", ask: bool = False, mode: str = "oneshot", prefill: bool = False
) -> SetupState:
    return {
        "flow": 3,
        "combined_gate": True,
        "prefill": prefill,
        "idea": idea,
        "style_reference": style_reference,
        "mode": mode,
        "requirements_ledger_ready": True,
        "brief": [],
        "notes": [],
        "notes_seen": 0,
        "piece": "concept",
        "pieces": dict.fromkeys(PIECE_ORDER, "todo"),
        "queue": ["concept"],
        "instructions": {},
        "instruction_sources": {},
        "decisions": {},
        "warnings": [],
        "revised": {},
        "round": 1,
        "previous": "",
        "dirty_concept": False,
        "library_reviewed": False,
    }


def requirements(state: SetupState) -> str:
    # 以前的开书流程要起书名：书名规矩照带
    return format_requirements(state.get("live_requirements") or [], [], state.get("settings"), title=True)


def _saved_state(saved: dict) -> dict:
    return {
        **{key: saved[key] for key in ("concept", "outline", "outline_chapters", "locked_names") if key in saved},
        "library": saved.get("settings") or {},
    }


async def live_state(state: SetupState, d: GraphDeps, *, refresh: bool = False) -> SetupState:
    async with d.sessionmaker() as session:
        await import_legacy_checkpoint(session, d.book_id, d.job_id, state)
        await session.commit()
        book = await session.get(Book, d.book_id)
        settings = settings_of(book) if book else {}
        rows = await active_requirements(session, d.book_id)
        deleted = await deleted_texts(session, d.book_id)
        saved = _saved_state(await setup_store.load_new_setup(session, d.book_id)) if book else {}
    if state.get("dirty_concept") and not refresh:
        saved.pop("concept", None)
    current = {**state, **saved, "settings": settings, "live_requirements": [requirement_text(row) for row in rows]}
    instructions = dict(state.get("instructions") or {})
    for target, sources in (state.get("instruction_sources") or {}).items():
        if any(source in deleted for source in sources):
            fallback = (state.get("instruction_fallbacks") or {}).get(target)
            if fallback:
                instructions[target] = fallback
            else:
                instructions.pop(target, None)
    current["instructions"] = instructions
    current["feedback_sources"] = [text for text in state.get("feedback_sources", []) if text not in deleted]
    if any(text in state.get("feedback", "") for text in deleted):
        current["feedback"] = "\n".join(current["feedback_sources"])
    if state.get("previous_feedback") in deleted:
        current["previous"] = ""
    pitch = dict(state.get("pitch") or {})
    if pitch.get("title") and f"书名用《{pitch['title']}》" in deleted:
        pitch.pop("title")
    elif (
        pitch.get("title")
        and (state.get("pieces") or {}).get("concept") in {"waiting", "confirmed"}
        and (saved.get("concept") or {}).get("title")
    ):
        pitch["title"] = saved["concept"]["title"]
    current["pitch"] = pitch
    if settings.get("chapter_words") and current.get("concept"):
        current["concept"] = {**current["concept"], "chapter_words": settings["chapter_words"]}
    return current


def _pieces(state: SetupState) -> dict:
    return {piece: (state.get("pieces") or {}).get(piece, "todo") for piece in PIECE_ORDER}


def _piece_of(target: str) -> str:
    return next(piece for piece, steps in PIECES.items() if target in steps)


async def mark_progress(d: GraphDeps, state: SetupState) -> None:
    progress = {"flow": 3, "mode": state.get("mode", "puzzle"), "current": state.get("piece"), "pieces": _pieces(state)}
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        if book is not None:
            book.setup_progress = progress
            await session.commit()
    await publish(d.redis, d.book_id, "book", {"id": str(d.book_id), "setup_progress": progress})


def _finish(state: SetupState, target: str, value: dict, result=None) -> dict:
    update = {
        target: value,
        "queue": [step for step in state.get("queue", []) if step != target],
        "instructions": {key: text for key, text in (state.get("instructions") or {}).items() if key != target},
    }
    if result is not None and hasattr(result, "decisions"):
        update["decisions"] = {
            **state.get("decisions", {}),
            target: [choice.model_dump() for choice in result.decisions],
        }
    return update


def route_next(state: SetupState) -> str:
    return state["queue"][0] if state.get("queue") else "piece_check"


def route_start(state: SetupState) -> str:
    return "pitches"


async def prefill_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    decision = interrupt({"kind": "setup_prefill", "flow": 3})
    if decision.get("action") != "start":
        raise ValueError("先写设定时请点「出三个故事方向」")
    return {"prefill": False}


def _revision(state: SetupState, target: str, current=None) -> str:
    instruction = (state.get("instructions") or {}).get(target, "")
    if not instruction:
        return ""
    current = current if current is not None else state.get(target) or {}
    return format_revision("当前内容", json.dumps(current, ensure_ascii=False), instruction) if current else instruction


async def pitches_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    pieces = {**_pieces(state), "concept": "drafting"}
    await mark_progress(d, {**state, "pieces": pieces})
    await d.emit.status("chief", "主编正在想三个故事方向…")
    blocks = {
        "idea": state["idea"],
        "style": format_style(state.get("style_reference", "")),
        "requirements": requirements(state),
        "previous": state.get("previous", ""),
        "existing": (await _library_blocks(d, state))["existing"],
    }
    for attempt in range(2):
        result = await editorial.draft_pitches(d.llm, blocks)
        if len(result.pitches) == 3 or attempt:
            break
    pitches = [pitch.model_dump() for pitch in result.pitches[:3]]
    if len(pitches) < 3:
        raise ValueError("主编没有给出三个故事方向，请重试")
    await d.emit.say("chief", result.reply)
    await d.emit.artifact(
        "chief",
        "三个故事方向",
        {
            "type": "pitches",
            "data": {"pitches": pitches, "benchmark": result.benchmark, "recommended": result.recommended},
        },
    )
    return {"pitches": pitches, "benchmark": result.benchmark, "recommended": result.recommended, "pieces": pieces}


async def pitches_gate_node(state: SetupState, runtime: Runtime[GraphDeps]) -> Command[Literal["pitches", "intake"]]:
    d = runtime.context
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        length = length_question(settings_of(book).get("chapter_words") if book else None)
    if state.get("mode") == "oneshot":
        decision = {"action": "pick", "index": state["recommended"], "length": LENGTHS[length["recommended"]]}
    else:
        decision = interrupt(
            {
                "kind": "setup_pitches",
                "open": True,
                "flow": 3,
                "round": state.get("round", 1),
                "benchmark": state.get("benchmark", ""),
                "pitches": state["pitches"],
                "recommended": state["recommended"],
                "length": length,
            }
        )
    if decision.get("action") == "redo":
        feedback = decision.get("feedback", "").strip()
        if not feedback:
            raise ValueError("请写一句对故事方向的意见")
        if not decision.get("requirement_saved"):
            async with d.sessionmaker() as session:
                await add_requirement(session, d.book_id, feedback, "trial")
                await session.commit()
        previous = (
            "【上一轮的故事方向】\n"
            + "\n".join(f"{index}. {pitch['name']}：{pitch['text']}" for index, pitch in enumerate(state["pitches"], 1))
            + f"\n【作者的意见】\n{feedback}"
        )
        return Command(
            goto="pitches",
            update={"previous": previous, "previous_feedback": feedback, "round": state.get("round", 1) + 1},
        )
    chosen_length = decision.get("length") or LENGTHS[length["recommended"]]
    if chosen_length not in LENGTHS:
        raise ValueError("请选择五档篇幅之一")
    filling = decision.get("action") == "fill"
    index = decision.get("index")
    if filling:
        pitch = {"from_story": True, "length": chosen_length}
    else:
        if decision.get("action") != "pick" or not isinstance(index, int) or not 1 <= index <= 3:
            raise ValueError("请选择一个故事方向")
        pitch = {**state["pitches"][index - 1], "length": chosen_length}
    if decision.get("title"):
        pitch["title"] = decision["title"].strip()
    if not decision.get("requirement_saved"):
        async with d.sessionmaker() as session:
            await add_requirement(
                session,
                d.book_id,
                "开书不挑故事方向，用已经写好的定调和设定补齐。"
                if filling
                else f"开书的故事方向：选用「{pitch['name']}」",
                "answer",
            )
            await add_requirement(session, d.book_id, f"这本书打算写多长？——约 {chosen_length} 万字", "answer")
            if pitch.get("title"):
                await add_requirement(session, d.book_id, f"书名用《{pitch['title']}》", "answer")
            await session.commit()
    if state.get("mode") == "oneshot" and not filling:
        await d.emit.say("chief", f"一口气模式：用了第 {index} 个故事方向「{pitch['name']}」。")
    return Command(goto="intake", update={"pitch": pitch, "queue": ["concept"], "piece_gates": False})


async def _new_notes(d: GraphDeps, seen: int) -> list:
    async with d.sessionmaker() as session:
        rows = await session.execute(
            select(MeetingMessage.id, MeetingMessage.content, MeetingMessage.payload)
            .where(MeetingMessage.job_id == d.job_id, MeetingMessage.kind == "note", MeetingMessage.id > seen)
            .order_by(MeetingMessage.id)
        )
        messages = [(row.id, row.content, row.payload) for row in rows]
        return await active_notes(session, d.book_id, messages) if messages else []


async def _review(d: GraphDeps, scope: str, kind: str = "review") -> None:
    from app.api.library_ai import review_library

    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        await review_library(session, d.redis, book, scope=scope, kind=kind)
        await session.commit()


async def _library_feedback(d: GraphDeps, feedback: str) -> None:
    from app.api.library_ai import RewriteIn, rewrite_target
    from app.services.chat_context import conversation_state, dialogue, dialogue_text
    from app.services.group_notes import viewing_text

    async with d.sessionmaker() as session:
        ctx = await load_context(session, await session.get(Book, d.book_id))
        library, outline = ctx.library, ctx.outline
        # 最近聊的那一段对话
        conv = await conversation_state(session, d.book_id, "group")
        recent = dialogue_text((await dialogue(session, d.book_id, "group", conv=conv.id))[-6:])
        await session.commit()
    result = await d.llm.structured(
        "router",
        schemas.LibraryIntent,
        editorial.persona("chief"),
        # 开书流程里提的意见：没有「正在看的那一页」
        render(
            "library_route", library=library, outline=outline, recent=recent, viewing=viewing_text(None), note=feedback
        ),
        purpose="群聊分流",
    )
    if result.kind == "改设定":
        async with d.sessionmaker() as session:
            book = await session.get(Book, d.book_id)
            ctx = await load_context(session, book)
            target = ctx.find_target(result.target_name)
            if target is not None:
                body = RewriteIn(
                    target_type=target_type_of(target),
                    target_id=target.id,
                    path=ctx.route_path(target, result.part, result.quote),
                    mode="options" if result.mode == "给几个写法" else "instruction",
                    instruction=result.instruction or feedback,
                )
                await rewrite_target(session, d.redis, book, body)
                await session.commit()
                if result.reply:
                    await d.emit.say("chief", result.reply)
                return
    await _review(d, f"按作者的意见查一遍：{feedback}")


async def _combined_feedback(d, state, feedback):
    import re

    from app.api.library_ai import RewriteIn, rewrite_target

    result = await editorial.absorb_notes(
        d.llm,
        {"concept": state.get("concept", {}), "settings": state.get("library", {})},
        [],
        requirements(state),
        [feedback],
    )
    await d.emit.say("chief", result.remark)
    if result.concept_instructions:
        clauses = re.split(r"[；\n]", result.concept_instructions)
        metadata = [
            c
            for c in clauses
            if any(w in c for w in ("底牌", "书名", "类型", "篇幅", "每章字数", "目标读者", "基调", "文风"))
        ]
        story = "；".join(c for c in clauses if c not in metadata)
        async with d.sessionmaker() as session:
            book = await session.get(Book, d.book_id)
            if story.strip():
                await rewrite_target(
                    session,
                    d.redis,
                    book,
                    RewriteIn(
                        target_type="concept", target_id=d.book_id, path="story", mode="instruction", instruction=story
                    ),
                )
            for clause in metadata:
                session.add(
                    SettingSuggestion(
                        book_id=d.book_id, kind="review", title=clause, payload={"op": "note", "content": clause}
                    )
                )
            await session.commit()
    if result.settings_instructions:
        await _library_feedback(d, result.settings_instructions)
    if result.outline_instructions:
        async with d.sessionmaker() as session:
            await add_requirement(session, d.book_id, result.outline_instructions, "note")
            await session.commit()


async def intake_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    update = {}
    if state.get("queue"):
        piece = _piece_of(state["queue"][0])
        update.update(piece=piece, pieces={**_pieces(state), piece: "drafting"})
        await mark_progress(d, {**state, **update})
    rows = await _new_notes(d, state.get("notes_seen", 0))
    if not rows:
        return update
    async with d.sessionmaker() as session:
        await ingest_notes(session, d.book_id, rows)
        await session.commit()
    state = await live_state({**state, **update}, d)
    fresh = [note_prompt(content, payload) for _, content, payload in rows]
    update.update(notes=[*state.get("notes", []), *fresh], notes_seen=rows[-1][0])
    done = {
        key: state.get(key)
        for key in ("concept", "outline")
        if state.get(key) and state[key].get("story" if key == "concept" else "arcs")
    }
    if (state.get("library") or {}).get("characters"):
        done["settings"] = state["library"]
    if done:
        result = await editorial.absorb_notes(d.llm, done, state.get("queue", []), requirements(state), fresh)
        await d.emit.say("chief", result.remark)
        instructions = dict(state.get("instructions") or {})
        queue = list(state.get("queue") or [])
        for target, text in result.instructions().items():
            if target == "settings" and done.get("settings"):
                await _library_feedback(d, text)
            elif target == state.get("piece") and target in {"concept", "outline"}:
                instructions[target] = text
                queue = list(dict.fromkeys([*PIECES[target], *queue]))
            elif target in done:
                # 已确认上游绝不从流程检查点整块回写，意见只进入建议。
                await _review(d, f"按作者的意见查一遍：{text}", "concept" if target == "concept" else "review")
        update.update(
            queue=queue,
            instructions=instructions,
            instruction_sources={
                **state.get("instruction_sources", {}),
                **{target: [content for _, content, _ in rows] for target in instructions},
            },
        )
    else:
        await d.emit.say("chief", "收到，接下来就按你说的写。")
    for _, _, payload in rows:
        if thread := note_thread(payload):
            await d.emit.say(thread, "收到，主编已经安排，按你说的改。", payload={"thread": thread})
    return update


async def concept_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("chief", "主编正在展开定调…")
    pitch = state.get("pitch") or {}
    chosen = f"{pitch.get('name', '')}：{pitch.get('text', '')}\n书名候选：{'、'.join(pitch.get('titles') or [])}"
    if state.get("benchmark"):
        chosen += f"\n对标理解：{state['benchmark']}"
    story = (state.get("concept") or {}).get("story", "")
    if pitch.get("from_story"):
        chosen = f"作者已经定好了定调的一段话，一个字都不要改，照着它补齐其余各项：\n{story}"
    result = await editorial.draft_story(
        d.llm,
        {
            "idea": state["idea"],
            "existing": (await _library_blocks(d, state))["existing"],
            "pitch": chosen,
            "style": format_style(state.get("style_reference", "")),
            "requirements": requirements(state),
            "revision": _revision(state, "concept"),
        },
    )
    value = result.model_dump(exclude={"remark", "decisions"})
    if pitch.get("from_story"):
        value["story"] = story
    if pitch.get("length"):
        value["target_length"] = pitch["length"]
    if pitch.get("title"):
        value["title"] = pitch["title"]
    if state.get("settings", {}).get("chapter_words"):
        value["chapter_words"] = state["settings"]["chapter_words"]
    value.update(pitches=deepcopy(state.get("pitches") or []), benchmark=state.get("benchmark", ""))
    await d.emit.say("chief", result.remark)
    await d.emit.artifact("chief", "定调", {"type": "concept", "data": value})
    return {**_finish(state, "concept", value, result), "dirty_concept": True}


async def _library_blocks(
    d: GraphDeps, state: SetupState, *, secret: bool = False, exclude_focus: bool = False
) -> dict:
    async with d.sessionmaker() as session:
        ctx = await load_context(session, await session.get(Book, d.book_id))
        focus = [
            target
            for target in ctx.targets
            if (isinstance(target, Character) and target.role_type == "主角")
            or "金手指" in (target.tags or [])
            or (secret and "底牌" in (target.tags or []))
        ]
        return {
            "existing": existing_text(ctx, exclude=focus if exclude_focus else ()),
            "concept": ctx.concept,
            "library": ctx.library,
            "focus": "\n\n".join(ctx.entry_full_text(target) for target in focus),
            "genre_defaults": genre_defaults((ctx.book.concept or {}).get("genre", "")),
            "requirements": requirements(state),
        }


async def settings_focus_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("lorekeeper", "设定师正在写主角和金手指…")
    blocks = await _library_blocks(d, state)
    result = await editorial.build_library_focus(
        d.llm,
        {key: blocks[key] for key in ("concept", "genre_defaults", "requirements", "existing")}
        | {"revision": _revision(state, "settings_focus")},
    )
    value = result.model_dump()
    async with d.sessionmaker() as session:
        await setup_store.save_library_focus(session, d.book_id, value)
        await session.commit()
    hero, finger = value["protagonist"], value["finger"]
    await d.emit.say("chief", f"重点先出来了：主角「{hero['name']}」和金手指「{finger['name']}」。其余设定正在补。")
    await d.emit.artifact("lorekeeper", "主角和金手指", {"type": "settings_focus", "data": value})
    await publish(d.redis, d.book_id, "library", {"phase": "focus"})
    await mark_progress(d, state)
    return _finish(state, "settings_focus", value, result)


async def settings_rest_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("lorekeeper", "设定师正在补齐其余设定…")
    blocks = await _library_blocks(d, state, exclude_focus=True)
    blocks.pop("library")
    # 金手指上一步已经写好，这一步不再建
    blocks["category_hints"] = "\n".join(
        f"【{category['name']}】{category['hint']}"
        for category in [CHARACTER_CATEGORY, *BUILTIN_CATEGORIES]
        if category["key"] != GOLDFINGER
    )
    blocks["revision"] = _revision(state, "settings_rest")
    result = await editorial.build_library_rest(d.llm, blocks)
    return _finish(state, "settings_rest", result.model_dump(exclude={"decisions", "remark"}), result)


async def outline_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    state = await live_state(state, d)
    await d.check_cancel()
    await d.emit.status("chief", "主编正在写大纲…")
    blocks = await _library_blocks(d, state, secret=True)
    blocks.pop("genre_defaults")
    blocks.update(length=format_length(state.get("concept") or {}), revision=_revision(state, "outline"))
    retried = False
    for attempt in range(2):
        result = await editorial.draft_setup_outline(d.llm, blocks)
        draft = result.model_dump(exclude={"decisions", "remark"})
        checks = [item for item in piece_checks("outline", {"outline": draft}) if item["question"] != "chapters"]
        if not checks or attempt:
            break
        retried = True
        blocks["revision"] = format_revision(
            "当前大纲",
            json.dumps(draft, ensure_ascii=False),
            "\n".join([*[(state.get("instructions") or {}).get("outline", "")], *[item["text"] for item in checks]]),
        )
    async with d.sessionmaker() as session:
        await setup_store.save_outline(session, d.book_id, draft)
        await session.commit()
        saved = _saved_state(await setup_store.load_new_setup(session, d.book_id))
    await d.emit.say("chief", result.remark)
    return {
        **_finish(state, "outline", saved["outline"], result),
        **saved,
        "revised": {**state.get("revised", {}), "outline": retried},
        "outline_checks": checks,
    }


async def outline_chapters_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    from app.graphs.write_book import plan_chapters_node

    d = runtime.context
    state = await live_state(state, d)
    units = state.get("outline", {}).get("units") or []
    if units:
        try:
            await plan_chapters_node({"unit_id": str(units[0]["id"])}, runtime)
        except LLMError as exc:
            if str(exc) != "主编没有给出章纲":
                raise
    async with d.sessionmaker() as session:
        saved = _saved_state(await setup_store.load_new_setup(session, d.book_id))
    return {**_finish(state, "outline_chapters", saved.get("outline_chapters", {})), **saved}


async def piece_check_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["intake", "piece_persist"]]:
    d = runtime.context
    state = await live_state(state, d)
    piece = state["piece"]
    checks = piece_checks(piece, state)
    if piece == "outline":
        checks = [*(state.get("outline_checks") or []), *checks]
    target = {"concept": "concept", "settings": "settings_rest", "outline": "outline_chapters"}[piece]
    rewrite = [
        item
        for item in checks
        if (piece == "concept" and item["question"] == "story")
        or piece == "settings"
        or (piece == "outline" and item["question"] == "chapters")
    ]
    if rewrite and not state.get("revised", {}).get(target):
        return Command(
            goto="intake",
            update={
                "queue": [target],
                "instructions": {**state.get("instructions", {}), target: "\n".join(item["text"] for item in rewrite)},
                "revised": {**state.get("revised", {}), target: True},
            },
        )
    return Command(goto="piece_persist", update={"warnings": list(dict.fromkeys(item["text"] for item in checks))})


async def piece_persist_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d, piece = runtime.context, state["piece"]
    async with d.sessionmaker() as session:
        if piece == "concept":
            await setup_store.save_story_concept(session, d.book_id, state["concept"])
        elif piece == "settings":
            await setup_store.save_library_rest(session, d.book_id, state["settings_rest"])
            await _save_warnings(session, d.book_id, state.get("warnings") or [])
        await session.commit()
    if piece == "settings" and not state.get("library_reviewed"):
        await _review(d, "这是开书时刚建好的设定库，查整个设定库。")
    state = await live_state({**state, "dirty_concept": False}, d, refresh=True)
    async with d.sessionmaker() as session:
        await setup_store.snapshot(
            session,
            d.book_id,
            d.job_id,
            state.get("round", 1),
            "ai",
            f"piece:{piece}",
            {
                "concept": state.get("concept", {}),
                "settings": state.get("library", {}),
                "outline": state.get("outline", {}),
            },
        )
        await session.commit()
    if piece == "settings":
        await d.emit.artifact("lorekeeper", "设定库", {"type": "settings_rest", "data": state.get("library", {})})
    elif piece == "outline":
        await d.emit.artifact("chief", "大纲", {"type": "outline", "data": state.get("outline", {})})
    summary = state.get("library", {}).get("summary", "") if piece == "settings" else ""
    if summary:
        await d.emit.say("chief", summary)
    else:
        await d.emit.say("chief", f"「{PIECE_NAMES[piece]}」好了，请你看看。")
    update = {
        key: state[key] for key in ("concept", "library", "outline", "outline_chapters", "locked_names") if key in state
    }
    update.update(
        dirty_concept=False,
        summary=summary,
        pieces={**_pieces(state), piece: "waiting" if state.get("piece_gates", True) else "drafting"},
        library_reviewed=piece == "settings" or state.get("library_reviewed", False),
        concept_warnings=state.get("warnings", []) if piece == "concept" else state.get("concept_warnings", []),
    )
    await mark_progress(d, {**state, **update})
    return update


async def _save_warnings(session, book_id, warnings):
    if not warnings:
        return
    pending = set(
        await session.scalars(
            select(SettingSuggestion.title).where(
                SettingSuggestion.book_id == book_id,
                SettingSuggestion.status == "pending",
                SettingSuggestion.title.in_(warnings),
            )
        )
    )
    for warning in dict.fromkeys(warnings):
        if warning not in pending:
            session.add(
                SettingSuggestion(book_id=book_id, kind="review", title=warning, payload={"op": "note", "why": warning})
            )


async def _piece_notices(state: SetupState, d: GraphDeps) -> None:
    async with d.sessionmaker() as session:
        await _save_warnings(session, d.book_id, state.get("warnings") or [])
        await session.commit()
    decisions = [choice for target in PIECES[state["piece"]] for choice in state.get("decisions", {}).get(target, [])]
    if decisions:
        lines = []
        for choice in decisions:
            line = f"· {choice['topic']}：用了「{choice['chosen']}」"
            if choice.get("alternatives"):
                line += f"（也可以：{'、'.join(choice['alternatives'])}）"
            lines.append(line)
        await d.emit.say("chief", "替你做了这几个决定，想换哪个就在群聊里说：\n" + "\n".join(lines))


async def _confirm_piece(state: SetupState, d: GraphDeps) -> Command:
    state = await live_state(state, d, refresh=True)
    piece = state["piece"]
    update = {
        key: state[key] for key in ("concept", "library", "outline", "outline_chapters", "locked_names") if key in state
    }
    pieces = {**_pieces(state), piece: "confirmed"}
    if piece == "concept" and state.get("mode") != "oneshot" and state.get("piece_gates", True):
        pieces["concept"] = "waiting"
    if piece == "settings":
        pieces["concept"] = "confirmed"
    update.update(pieces=pieces, warnings=[], summary="", dirty_concept=False, combined_gate=True)
    if piece == "outline":
        await mark_progress(d, {**state, **update})
        return Command(goto="finalize", update=update)
    following = PIECE_ORDER[PIECE_ORDER.index(piece) + 1]
    update.update(piece=following, queue=list(PIECES[following]), instructions={}, instruction_sources={})
    await mark_progress(d, {**state, **update})
    return Command(goto="intake", update=update)


async def piece_gate_node(
    state: SetupState, runtime: Runtime[GraphDeps]
) -> Command[Literal["intake", "piece_gate", "finalize"]]:
    d = runtime.context
    if not state.get("piece_gates", True):
        await _piece_notices(state, d)
        return await _confirm_piece(state, d)
    if (state.get("mode") == "oneshot" and state["piece"] != "outline") or (
        state.get("combined_gate") and state["piece"] == "concept"
    ):
        return await _confirm_piece(state, d)
    # 中断前只有读取；恢复时必须读回作者刚保存的数据，不用检查点覆盖。
    state = await live_state(state, d, refresh=True)
    decision = interrupt(
        {
            "kind": "setup_piece",
            "flow": 3,
            "piece": state["piece"],
            "round": state.get("round", 1),
            "warnings": state.get("warnings", []),
            "concept_warnings": state.get("concept_warnings", []),
            "concept_decisions": state.get("decisions", {}).get("concept", []),
            "decisions": [
                choice for target in PIECES[state["piece"]] for choice in state.get("decisions", {}).get(target, [])
            ],
            "summary": state.get("library", {}).get("summary", "") if state["piece"] == "settings" else "",
            "suggestion_count": state.get("library", {}).get("suggestion_count", 0),
            "setup": {
                "concept": state.get("concept", {}),
                "settings": state.get("library", {}),
                "outline": state.get("outline", {}),
            },
        }
    )
    state = await live_state(state, d, refresh=True)
    action = decision.get("action")
    if action in {"confirm", "delegate"}:
        return await _confirm_piece(state, d)
    if action != "revise":
        raise ValueError("只支持确认、交给编辑部定或提意见")
    feedback = decision.get("feedback", "").strip()
    flips = decision.get("flips") or []
    if not decision.get("requirement_saved"):
        async with d.sessionmaker() as session:
            if feedback:
                await add_requirement(session, d.book_id, feedback, "trial")
            for flip in flips:
                await add_requirement(session, d.book_id, f"「{flip['topic']}」改成：{flip['choice']}", "trial")
            await session.commit()
    if state["piece"] == "settings":
        concept_flips = flips if decision.get("decision_piece") == "concept" else []
        settings_flips = [] if concept_flips else flips
        notes = [feedback, *[f"把「{flip['topic']}」改成「{flip['choice']}」" for flip in concept_flips]]
        if any(notes):
            await _combined_feedback(d, state, "\n".join(filter(None, notes)))
        for flip in settings_flips:
            await _library_feedback(d, f"把「{flip['topic']}」改成「{flip['choice']}」")
        latest = await live_state(state, d, refresh=True)
        summary = latest.get("library", {}).get("summary", "")
        await d.emit.say("chief", summary)
        return Command(goto="piece_gate", update={"library": latest.get("library", {}), "summary": summary})
    target = state["piece"]
    instruction = "\n".join(
        filter(None, [feedback, *[f"把「{flip['topic']}」改成「{flip['choice']}」" for flip in flips]])
    )
    if target == "outline":
        instruction += f"\n下面这些节点作者锁住了，原样保留：{'、'.join(state.get('locked_names') or [])}"
    return Command(
        goto="intake",
        update={
            # 带回 live_state 已同步或撤销的选名约束；下一节点会进入 drafting，
            # 不能再从旧检查点恢复最初选中的书名覆盖作者刚保存的名字。
            "pitch": state.get("pitch") or {},
            "queue": list(PIECES[target]),
            "instructions": {target: instruction},
            "instruction_sources": {
                target: [feedback, *[f"「{flip['topic']}」改成：{flip['choice']}" for flip in flips]]
            },
            "revised": {},
            "warnings": [],
        },
    )


async def finalize_node(state: SetupState, runtime: Runtime[GraphDeps]) -> dict:
    d = runtime.context
    await live_state(state, d, refresh=True)
    async with d.sessionmaker() as session:
        book = await session.get(Book, d.book_id)
        book.status = "ready"
        total = (
            await session.scalar(select(func.count()).select_from(Character).where(Character.book_id == d.book_id))
        ) + (await session.scalar(select(func.count()).select_from(WorldEntry).where(WorldEntry.book_id == d.book_id)))
        await session.commit()
    update = {"piece": None, "pieces": dict.fromkeys(PIECE_ORDER, "confirmed")}
    await mark_progress(d, {**state, **update})
    await d.emit.say(
        "chief",
        f"开书稿齐了：定调、设定 {total} 条、大纲排到第一个单元的章纲。哪里不对，直接在群聊里说，或者在页面上改；满意了点「开写」。"
        if not state.get("piece_gates", True)
        else "开书方案定好了，可以开写了。",
    )
    return update


def build_setup_graph() -> StateGraph:
    graph = StateGraph(SetupState, context_schema=GraphDeps)
    for name, node in (
        ("pitches", pitches_node),
        ("pitches_gate", pitches_gate_node),
        ("intake", intake_node),
        ("concept", concept_node),
        ("settings_focus", settings_focus_node),
        ("settings_rest", settings_rest_node),
        ("outline", outline_node),
        ("outline_chapters", outline_chapters_node),
        ("piece_check", piece_check_node),
        ("piece_persist", piece_persist_node),
        ("piece_gate", piece_gate_node),
        ("finalize", finalize_node),
    ):
        graph.add_node(name, node)
    graph.add_node("prefill_gate", prefill_gate_node)
    graph.add_conditional_edges(START, route_start, ["prefill_gate", "pitches"])
    graph.add_edge("prefill_gate", "pitches")
    graph.add_edge("pitches", "pitches_gate")
    graph.add_conditional_edges("intake", route_next, [*ORDER, "piece_check"])
    for name in ORDER:
        graph.add_edge(name, "intake")
    graph.add_edge("piece_persist", "piece_gate")
    graph.add_edge("finalize", END)
    return graph


def restart_state(params: dict, old_values: dict, concept: dict) -> SetupState:
    state = initial_state(params.get("idea", ""), params.get("style_reference", ""), mode=params.get("mode", "puzzle"))
    if direction := old_values.get("direction"):
        state["previous"] = (
            f"【之前按旧流程选过的方向】\n{direction.get('name', '')}：{direction.get('logline') or direction.get('story', '')}\n（作者之前选过它，三个故事方向里请保留它的好东西。）"
        )
    return state
