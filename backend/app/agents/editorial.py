"""编辑部各角色的「一次发言」：拼好提示词，调用对应角色的模型，拿回结构化结果。"""

from collections.abc import AsyncIterator

from app.agents import schemas as s
from app.agents.context import (
    format_concept,
    format_lore,
    format_outline,
    format_pitches,
    format_revision,
    format_spine,
    format_style,
    format_threads,
    format_volume_plan,
    planned_chapters,
)
from app.agents.glossary import glossary_block
from app.agents.playbook import playbook_text
from app.llm.router import LLMRouter
from app.prompts import render


def persona(role: str) -> str:
    return render(f"persona_{role}", rules=render("rules"))


async def interview(llm: LLMRouter, idea: str, style: str, requirements: str = "") -> s.InterviewDraft:
    user = render("setup_interview", idea=idea, style=format_style(style))
    if requirements:
        user += "\n\n" + requirements
    return await llm.structured("chief", s.InterviewDraft, persona("chief"), user, purpose="开书·动笔前提问")


async def draft_concept(
    llm: LLMRouter,
    idea: str,
    style: str,
    requirements: str,
    current: dict,
    instructions: str,
    chosen_direction: str = "",
) -> s.BookConcept:
    user = render(
        "setup_concept",
        idea=idea,
        chosen_direction=chosen_direction,
        requirements=requirements,
        style=format_style(style),
        revision=format_revision("当前概念", format_concept(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.BookConcept, persona("chief"), user, purpose="开书·概念")


async def draft_directions(llm: LLMRouter, idea: str, style: str, requirements: str = "") -> s.BookDirections:
    user = render(
        "setup_directions", idea=idea, style=format_style(style), requirements=requirements, glossary=glossary_block()
    )
    return await llm.structured("chief", s.BookDirections, persona("chief"), user, purpose="开书·方向")


async def draft_node_slot(
    llm: LLMRouter, concept: dict, spine: dict, slot: str, requirements: str = "", glossary: str | None = None
) -> s.NodeCandidates:
    user = render(
        "setup_node_slot",
        concept=format_concept(concept),
        spine=format_spine(spine),
        slot=slot,
        requirements=requirements,
        glossary=glossary if glossary is not None else glossary_block(),
    )
    return await llm.structured("chief", s.NodeCandidates, persona("chief"), user, purpose="开书·节点候选与补空位")


async def draft_lore(
    llm: LLMRouter, concept: dict, spine: dict, requirements: str, current: dict, instructions: str
) -> s.LoreDraft:
    user = render(
        "setup_lore",
        concept=format_concept(concept),
        spine=format_spine(spine),
        requirements=requirements,
        revision=format_revision("当前设定", format_lore(current), instructions) if current else "",
    )
    return await llm.structured("lorekeeper", s.LoreDraft, persona("lorekeeper"), user, purpose="开书·设定")


async def draft_spine(
    llm: LLMRouter,
    concept: dict,
    requirements: str,
    current: dict,
    instructions: str,
    *,
    playbook: str,
    glossary: str,
    legacy_lore: dict | None = None,
) -> s.StorySpine:
    user = render(
        "setup_spine",
        concept=format_concept(concept),
        playbook=playbook,
        glossary=glossary,
        lore=format_lore(legacy_lore) if legacy_lore else "（设定将在关键节点之后生成）",
        requirements=requirements,
        revision=format_revision("当前主线骨架", format_spine(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.StorySpine, persona("chief"), user, purpose="开书·主线骨架")


async def draft_threads(
    llm: LLMRouter,
    concept: dict,
    lore: dict,
    spine: dict,
    outline: dict,
    requirements: str,
    current: dict,
    instructions: str,
    selection: str = "auto",
) -> s.ThreadsDraft:
    user = render(
        "setup_threads",
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        outline=format_outline(outline),
        playbook=playbook_text(concept, "threads", selection=selection),
        requirements=requirements,
        revision=format_revision("当前线索", format_threads(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.ThreadsDraft, persona("chief"), user, purpose="开书·线索")


async def draft_outline(
    llm: LLMRouter,
    concept: dict,
    lore: dict,
    spine: dict,
    requirements: str,
    current: dict,
    instructions: str,
    selection: str = "auto",
    glossary: str | None = None,
    legacy_threads: dict | None = None,
) -> s.OutlineDraft:
    chapters = planned_chapters(concept)
    user = render(
        "setup_outline",
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        threads=format_threads(legacy_threads) if legacy_threads else "（线索将在总纲之后生成）",
        glossary=glossary if glossary is not None else glossary_block(),
        playbook=playbook_text(concept, "outline", selection=selection),
        requirements=requirements,
        chapter_hint=f"（约 {chapters} 章）" if chapters else "",
        revision=format_revision("当前总纲", format_outline(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.OutlineDraft, persona("chief"), user, purpose="开书·全书总纲")


async def plan_volume(
    llm: LLMRouter, blocks: dict[str, str], current: dict, instructions: str, *, purpose: str
) -> s.VolumePlanDraft:
    """卷纲：开书时拆第一卷、写作中拆后面各卷、比稿时按某个方向拆，都用这一个。blocks 是拼好的各段上下文。"""
    user = render(
        "plan_volume",
        **{"direction": "", **blocks},
        revision=format_revision("当前卷纲", format_volume_plan(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.VolumePlanDraft, persona("chief"), user, purpose=purpose)


async def volume_directions(llm: LLMRouter, blocks: dict[str, str], *, purpose: str) -> s.VolumeDirections:
    user = render("volume_directions", **blocks)
    return await llm.structured("chief", s.VolumeDirections, persona("chief"), user, purpose=purpose)


async def judge_pitches(
    llm: LLMRouter, blocks: dict[str, str], pitches: list[dict], *, purpose: str
) -> s.PitchJudgement:
    """审稿比稿：pitches 是 [{pitch, direction, plan}]。"""
    user = render("judge_pitches", **blocks, pitch_count=str(len(pitches)), pitches=format_pitches(pitches))
    return await llm.structured("reviewer", s.PitchJudgement, persona("reviewer"), user, purpose=purpose)


async def audit_volume(
    llm: LLMRouter, blocks: dict[str, str], plan: dict, found: list[str], *, purpose: str
) -> s.VolumeAudit:
    """卷纲专项审稿。found 是程序已经查出的问题。"""
    user = render(
        "audit_volume",
        **blocks,
        plan=format_volume_plan(plan),
        found="\n".join(f"- {line}" for line in found) or "（没有）",
    )
    return await llm.structured("reviewer", s.VolumeAudit, persona("reviewer"), user, purpose=purpose)


async def critique_setup(
    llm: LLMRouter, idea: str, requirements: str, setup: dict[str, dict], selection: str = "auto", locked: str = ""
) -> s.SetupCritique:
    user = render(
        "setup_critique",
        idea=idea,
        requirements=requirements,
        locked=locked,
        playbook=playbook_text(setup.get("concept"), "review", selection=selection),
        **{k: PART_FORMATTERS[k](setup[k]) if setup.get(k) else "（还没做）" for k in s.SETUP_PARTS},
    )
    return await llm.structured("reviewer", s.SetupCritique, persona("reviewer"), user, purpose="开书·审稿")


async def triage_feedback(
    llm: LLMRouter, setup: dict[str, dict], requirements: str, feedback: str, locked: str = ""
) -> s.RevisionTriage:
    user = render(
        "setup_triage",
        requirements=requirements,
        feedback=feedback,
        locked=locked,
        **{k: PART_FORMATTERS[k](setup.get(k) or {}) for k in s.SETUP_PARTS},
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者意见")


PART_LABELS = {
    "concept": "概念",
    "spine": "关键节点",
    "lore": "世界观、人物与信息差",
    "outline": "全书总纲",
    "threads": "线索",
    "first_volume": "第一卷卷纲",
}
PART_FORMATTERS = {
    "concept": format_concept,
    "spine": format_spine,
    "lore": format_lore,
    "outline": format_outline,
    "threads": format_threads,
    "first_volume": format_volume_plan,
}


async def absorb_notes(
    llm: LLMRouter, done: dict[str, dict], todo: list[str], requirements: str, notes: list[str], locked: str = ""
) -> s.RevisionTriage:
    """作者中途插话：判断已完成的部分要不要跟着改。"""
    user = render(
        "setup_notes",
        done="\n\n".join(f"{PART_LABELS[k]}：\n{PART_FORMATTERS[k](v)}" for k, v in done.items()),
        todo="、".join(PART_LABELS[k] for k in todo) or "（没有了，方案马上交给作者）",
        requirements=requirements,
        locked=locked,
        notes="\n".join(f"- {n}" for n in notes),
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者插话")


# ---------- 写作 ----------


async def plan_chapters(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterPlanDraft:
    user = render("plan_chapters", **blocks)
    return await llm.structured("chief", s.ChapterPlanDraft, persona("chief"), user, purpose="写作·章纲")


async def prepare_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterMaterials:
    """写之前设定师读章纲，从设定库和前文里挑出这一章用得上的资料。"""
    user = render("prepare_chapter", **blocks)
    return await llm.structured("lorekeeper", s.ChapterMaterials, persona("lorekeeper"), user, purpose="写作·备资料")


def write_chapter(llm: LLMRouter, blocks: dict[str, str]) -> AsyncIterator[str]:
    user = render("write_chapter", **blocks)
    return llm.stream_text("writer", persona("writer"), user, purpose="写作·正文")


def extend_chapter(llm: LLMRouter, blocks: dict[str, str], words: int, missing: int) -> AsyncIterator[str]:
    """字数明显不够时让写手接着写。"""
    user = render("extend_chapter", **blocks, words=str(words), missing=str(missing))
    return llm.stream_text("writer", persona("writer"), user, purpose="写作·续写")


def rewrite_ending(
    llm: LLMRouter, blocks: dict[str, str], body: str, ending: str, reason: str, hook: str
) -> AsyncIterator[str]:
    """结尾写成总结式时，让写手只重写结尾。"""
    user = render(
        "rewrite_ending",
        **blocks,
        body=body,
        ending=ending,
        reason=reason,
        hook=hook or "章纲没写钩子，就停在一个让读者想看下一章的悬念上",
        ending_words=str(max(150, min(600, len(ending)))),
    )
    return llm.stream_text("writer", persona("writer"), user, purpose="写作·改结尾")


async def recap_unit(llm: LLMRouter, blocks: dict[str, str]) -> s.StoryRecap:
    user = render("recap_unit", **blocks)
    return await llm.structured("lorekeeper", s.StoryRecap, persona("lorekeeper"), user, purpose="写作·单元回顾")


async def recap_volume(llm: LLMRouter, blocks: dict[str, str]) -> s.StoryRecap:
    user = render("recap_volume", **blocks)
    return await llm.structured("lorekeeper", s.StoryRecap, persona("lorekeeper"), user, purpose="写作·卷回顾")


async def review_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterReview:
    user = render("review_chapter", **{"strictness": "", **blocks})
    return await llm.structured("reviewer", s.ChapterReview, persona("reviewer"), user, purpose="写作·审稿")


async def check_consistency(llm: LLMRouter, blocks: dict[str, str]) -> s.ConsistencyReport:
    user = render("check_consistency", **blocks)
    return await llm.structured("lorekeeper", s.ConsistencyReport, persona("lorekeeper"), user, purpose="写作·设定检查")


async def digest_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterDigest:
    user = render("digest_chapter", **blocks)
    return await llm.structured("lorekeeper", s.ChapterDigest, persona("lorekeeper"), user, purpose="写作·更新设定库")
