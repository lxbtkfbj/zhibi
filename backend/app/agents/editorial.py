"""编辑部各角色的「一次发言」：拼好提示词，调用对应角色的模型，拿回结构化结果。"""

from collections.abc import AsyncIterator

from app.agents import schemas as s
from app.agents.context import (
    format_concept,
    format_lore,
    format_outline,
    format_revision,
    format_spine,
    format_style,
    format_threads,
    format_volume_plan,
    planned_chapters,
)
from app.llm.router import LLMRouter
from app.prompts import render


def persona(role: str) -> str:
    return render(f"persona_{role}", rules=render("rules"))


async def interview(llm: LLMRouter, idea: str, style: str) -> s.InterviewDraft:
    user = render("setup_interview", idea=idea, style=format_style(style))
    return await llm.structured("chief", s.InterviewDraft, persona("chief"), user, purpose="开书·动笔前提问")


async def draft_concept(
    llm: LLMRouter, idea: str, style: str, requirements: str, current: dict, instructions: str
) -> s.BookConcept:
    user = render(
        "setup_concept",
        idea=idea,
        requirements=requirements,
        style=format_style(style),
        revision=format_revision("当前概念", format_concept(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.BookConcept, persona("chief"), user, purpose="开书·概念")


async def draft_lore(llm: LLMRouter, concept: dict, requirements: str, current: dict, instructions: str) -> s.LoreDraft:
    user = render(
        "setup_lore",
        concept=format_concept(concept),
        requirements=requirements,
        revision=format_revision("当前设定", format_lore(current), instructions) if current else "",
    )
    return await llm.structured("lorekeeper", s.LoreDraft, persona("lorekeeper"), user, purpose="开书·设定")


async def draft_spine(
    llm: LLMRouter, concept: dict, lore: dict, requirements: str, current: dict, instructions: str
) -> s.StorySpine:
    user = render(
        "setup_spine",
        concept=format_concept(concept),
        lore=format_lore(lore),
        requirements=requirements,
        revision=format_revision("当前主线骨架", format_spine(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.StorySpine, persona("chief"), user, purpose="开书·主线骨架")


async def draft_threads(
    llm: LLMRouter, concept: dict, lore: dict, spine: dict, requirements: str, current: dict, instructions: str
) -> s.ThreadsDraft:
    user = render(
        "setup_threads",
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        requirements=requirements,
        revision=format_revision("当前线索", format_threads(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.ThreadsDraft, persona("chief"), user, purpose="开书·线索")


async def draft_outline(
    llm: LLMRouter,
    concept: dict,
    lore: dict,
    spine: dict,
    threads: dict,
    requirements: str,
    current: dict,
    instructions: str,
) -> s.OutlineDraft:
    chapters = planned_chapters(concept)
    user = render(
        "setup_outline",
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        threads=format_threads(threads),
        requirements=requirements,
        chapter_hint=f"（约 {chapters} 章）" if chapters else "",
        revision=format_revision("当前总纲", format_outline(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.OutlineDraft, persona("chief"), user, purpose="开书·全书总纲")


async def plan_volume(
    llm: LLMRouter, blocks: dict[str, str], current: dict, instructions: str, *, purpose: str
) -> s.VolumePlanDraft:
    """卷纲：开书时拆第一卷、写作中拆后面各卷共用。blocks 是拼好的各段上下文。"""
    user = render(
        "plan_volume",
        **blocks,
        revision=format_revision("当前卷纲", format_volume_plan(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.VolumePlanDraft, persona("chief"), user, purpose=purpose)


async def critique_setup(llm: LLMRouter, idea: str, requirements: str, setup: dict[str, dict]) -> s.SetupCritique:
    user = render(
        "setup_critique",
        idea=idea,
        requirements=requirements,
        **{k: PART_FORMATTERS[k](setup.get(k) or {}) for k in s.SETUP_PARTS},
    )
    return await llm.structured("reviewer", s.SetupCritique, persona("reviewer"), user, purpose="开书·审稿")


async def triage_feedback(llm: LLMRouter, setup: dict[str, dict], requirements: str, feedback: str) -> s.RevisionTriage:
    user = render(
        "setup_triage",
        requirements=requirements,
        feedback=feedback,
        **{k: PART_FORMATTERS[k](setup.get(k) or {}) for k in s.SETUP_PARTS},
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者意见")


PART_LABELS = {
    "concept": "概念",
    "lore": "世界观与人物",
    "spine": "主线骨架",
    "threads": "线索",
    "outline": "全书总纲",
    "first_volume": "第一卷卷纲",
}
PART_FORMATTERS = {
    "concept": format_concept,
    "lore": format_lore,
    "spine": format_spine,
    "threads": format_threads,
    "outline": format_outline,
    "first_volume": format_volume_plan,
}


async def absorb_notes(
    llm: LLMRouter, done: dict[str, dict], todo: list[str], requirements: str, notes: list[str]
) -> s.RevisionTriage:
    """作者中途插话：判断已完成的部分要不要跟着改。"""
    user = render(
        "setup_notes",
        done="\n\n".join(f"{PART_LABELS[k]}：\n{PART_FORMATTERS[k](v)}" for k, v in done.items()),
        todo="、".join(PART_LABELS[k] for k in todo) or "（没有了，方案马上交给作者）",
        requirements=requirements,
        notes="\n".join(f"- {n}" for n in notes),
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者插话")


# ---------- 写作 ----------


async def plan_chapters(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterPlanDraft:
    user = render("plan_chapters", **blocks)
    return await llm.structured("chief", s.ChapterPlanDraft, persona("chief"), user, purpose="写作·章纲")


def write_chapter(llm: LLMRouter, blocks: dict[str, str]) -> AsyncIterator[str]:
    user = render("write_chapter", **blocks)
    return llm.stream_text("writer", persona("writer"), user, purpose="写作·正文")


async def review_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterReview:
    user = render("review_chapter", **blocks)
    return await llm.structured("reviewer", s.ChapterReview, persona("reviewer"), user, purpose="写作·审稿")


async def check_consistency(llm: LLMRouter, blocks: dict[str, str]) -> s.ConsistencyReport:
    user = render("check_consistency", **blocks)
    return await llm.structured("lorekeeper", s.ConsistencyReport, persona("lorekeeper"), user, purpose="写作·设定检查")


async def digest_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterDigest:
    user = render("digest_chapter", **blocks)
    return await llm.structured("lorekeeper", s.ChapterDigest, persona("lorekeeper"), user, purpose="写作·更新设定库")
