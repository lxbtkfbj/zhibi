"""编辑部各角色的结构化产出；开书三步与写作共用的模型入口。"""

import json
from collections.abc import AsyncIterator

from app.agents import schemas as s
from app.agents.context import format_pitches, format_revision, format_volume_plan
from app.llm.router import LLMRouter
from app.prompts import render


def persona(role: str) -> str:
    return render(f"persona_{role}", rules=render("rules"))


async def draft_pitches(llm: LLMRouter, blocks: dict[str, str]) -> s.PitchSet:
    return await llm.structured(
        "chief", s.PitchSet, persona("chief"), render("setup_pitches", **blocks), purpose="开书·三个短版"
    )


async def draft_story(llm: LLMRouter, blocks: dict[str, str]) -> s.StoryConcept:
    return await llm.structured(
        "chief", s.StoryConcept, persona("chief"), render("setup_story", **blocks), purpose="开书·定调"
    )


async def build_library_focus(llm: LLMRouter, blocks: dict[str, str]) -> s.LibraryFocus:
    return await llm.structured(
        "lorekeeper",
        s.LibraryFocus,
        persona("lorekeeper"),
        render("library_build_focus", **blocks),
        purpose="开书·主角和金手指",
    )


async def build_library_rest(llm: LLMRouter, blocks: dict[str, str]) -> s.LibraryRest:
    return await llm.structured(
        "lorekeeper",
        s.LibraryRest,
        persona("lorekeeper"),
        render("library_build_rest", **blocks),
        purpose="开书·其余设定",
    )


async def draft_setup_outline(llm: LLMRouter, blocks: dict[str, str]) -> s.OutlineDraft:
    return await llm.structured(
        "chief", s.OutlineDraft, persona("chief"), render("setup_outline", **blocks), purpose="开书·大纲"
    )


async def absorb_notes(
    llm: LLMRouter, done: dict[str, dict], todo: list[str], requirements: str, notes: list[str], locked: str = ""
) -> s.SetupNotePlan:
    from app.agents.setup_puzzle import PIECE_NAMES, TARGET_NAMES

    user = render(
        "setup_notes",
        done="\n\n".join(
            f"{PIECE_NAMES.get(k, TARGET_NAMES.get(k, k))}：\n{json.dumps(v, ensure_ascii=False)}"
            for k, v in done.items()
        ),
        todo="、".join(TARGET_NAMES.get(k, k) for k in todo) or "（没有了，方案马上交给作者）",
        requirements=requirements,
        notes="\n".join(f"- {n}" for n in notes),
        locked=locked,
    )
    return await llm.structured("chief", s.SetupNotePlan, persona("chief"), user, purpose="开书·处理作者插话")


async def plan_segment(llm: LLMRouter, blocks: dict[str, str]) -> s.NextSegmentDraft:
    user = render("plan_segment", **blocks)
    return await llm.structured("chief", s.NextSegmentDraft, persona("chief"), user, purpose="写作·定下一段")


async def split_next_segment(llm: LLMRouter, blocks: dict[str, str]) -> s.SegmentVolumesDraft:
    user = render("split_segment", **blocks)
    return await llm.structured("chief", s.SegmentVolumesDraft, persona("chief"), user, purpose="写作·下一段分卷")


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


async def plan_chapters(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterPlanDraft:
    user = render("plan_chapters", **blocks)
    return await llm.structured("chief", s.ChapterPlanDraft, persona("chief"), user, purpose="写作·章纲")


async def prepare_chapter(llm: LLMRouter, blocks: dict[str, str]) -> s.ChapterMaterials:
    """写之前设定师读章纲，从设定库和前文里挑出这一章用得上的资料。"""
    user = render("prepare_chapter", **blocks)
    return await llm.structured("lorekeeper", s.ChapterMaterials, persona("lorekeeper"), user, purpose="写作·备资料")


def write_chapter(llm: LLMRouter, blocks: dict[str, str]) -> AsyncIterator[str]:
    user = render("write_chapter", **{**blocks, "secrets": blocks.get("secrets_for_writer", blocks.get("secrets", ""))})
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
