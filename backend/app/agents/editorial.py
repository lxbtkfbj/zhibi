"""编辑部各角色的「一次发言」：拼好提示词，调用对应角色的模型，拿回结构化结果。"""

from app.agents import schemas as s
from app.agents.context import (
    format_concept,
    format_lore,
    format_outline,
    format_revision,
    format_spine,
    format_style,
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


async def draft_outline(
    llm: LLMRouter, concept: dict, lore: dict, spine: dict, requirements: str, current: dict, instructions: str
) -> s.OutlineDraft:
    chapters = planned_chapters(concept)
    user = render(
        "setup_outline",
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        requirements=requirements,
        chapter_hint=f"（约 {chapters} 章）" if chapters else "",
        revision=format_revision("当前大纲", format_outline(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.OutlineDraft, persona("chief"), user, purpose="开书·大纲")


async def critique_setup(
    llm: LLMRouter, idea: str, requirements: str, concept: dict, lore: dict, spine: dict, outline: dict
) -> s.SetupCritique:
    user = render(
        "setup_critique",
        idea=idea,
        requirements=requirements,
        concept=format_concept(concept),
        lore=format_lore(lore),
        spine=format_spine(spine),
        outline=format_outline(outline),
    )
    return await llm.structured("reviewer", s.SetupCritique, persona("reviewer"), user, purpose="开书·审稿")


async def triage_feedback(llm: LLMRouter, setup: dict[str, dict], requirements: str, feedback: str) -> s.RevisionTriage:
    user = render(
        "setup_triage",
        concept=format_concept(setup.get("concept") or {}),
        lore=format_lore(setup.get("lore") or {}),
        spine=format_spine(setup.get("spine") or {}),
        outline=format_outline(setup.get("outline") or {}),
        requirements=requirements,
        feedback=feedback,
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者意见")


PART_LABELS = {"concept": "概念", "lore": "世界观与人物", "spine": "主线骨架", "outline": "分卷大纲"}
PART_FORMATTERS = {"concept": format_concept, "lore": format_lore, "spine": format_spine, "outline": format_outline}


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
