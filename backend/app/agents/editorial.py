"""编辑部各角色的「一次发言」：拼好提示词，调用对应角色的模型，拿回结构化结果。"""

from app.agents import schemas as s
from app.agents.context import format_concept, format_lore, format_outline, format_revision, format_style
from app.llm.router import LLMRouter
from app.prompts import render


def persona(role: str) -> str:
    return render(f"persona_{role}", rules=render("rules"))


async def draft_concept(llm: LLMRouter, idea: str, style: str, current: dict, instructions: str) -> s.BookConcept:
    user = render(
        "setup_concept",
        idea=idea,
        style=format_style(style),
        revision=format_revision("当前概念", format_concept(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.BookConcept, persona("chief"), user, purpose="开书·概念")


async def draft_lore(llm: LLMRouter, concept: dict, current: dict, instructions: str) -> s.LoreDraft:
    user = render(
        "setup_lore",
        concept=format_concept(concept),
        revision=format_revision("当前设定", format_lore(current), instructions) if current else "",
    )
    return await llm.structured("lorekeeper", s.LoreDraft, persona("lorekeeper"), user, purpose="开书·设定")


async def draft_outline(llm: LLMRouter, concept: dict, lore: dict, current: dict, instructions: str) -> s.OutlineDraft:
    user = render(
        "setup_outline",
        concept=format_concept(concept),
        lore=format_lore(lore),
        revision=format_revision("当前大纲", format_outline(current), instructions) if current else "",
    )
    return await llm.structured("chief", s.OutlineDraft, persona("chief"), user, purpose="开书·大纲")


async def critique_setup(llm: LLMRouter, idea: str, concept: dict, lore: dict, outline: dict) -> s.SetupCritique:
    user = render(
        "setup_critique",
        idea=idea,
        concept=format_concept(concept),
        lore=format_lore(lore),
        outline=format_outline(outline),
    )
    return await llm.structured("reviewer", s.SetupCritique, persona("reviewer"), user, purpose="开书·审稿")


async def triage_feedback(llm: LLMRouter, concept: dict, lore: dict, outline: dict, feedback: str) -> s.RevisionTriage:
    user = render(
        "setup_triage",
        concept=format_concept(concept),
        lore=format_lore(lore),
        outline=format_outline(outline),
        feedback=feedback,
    )
    return await llm.structured("chief", s.RevisionTriage, persona("chief"), user, purpose="开书·处理作者意见")
