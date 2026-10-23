"""任务 4：新提示词逐字契约、提示词页、结构化产出及演示判断。"""

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.schemas import FeedbackMemory, FeedbackMemoryItem
from app.llm import demo
from app.prompts import VARIABLE, default_content
from app.prompts.catalog import entry, validate_content, variables

ROOT = Path(__file__).parents[2]
PROMPT_SHA256 = "7f842a7d67970e56ddb31f1594bb38c0304c2dc929a1af51d82f429c21f2e524"


def prompt(feedback, what_happens="编辑部会照这段意见改这一处，这件事不用你管。"):
    values = {"where": "第 3 卷的卷纲", "what_happens": what_happens, "feedback": feedback, "memory": "还没有记忆"}
    return VARIABLE.sub(lambda match: values[match[1]], default_content("feedback_memory"))


def test_feedback_memory_prompt_is_verbatim_design_99_with_locked_fingerprint():
    design = (ROOT / "docs/主编聊天/记忆系统.md").read_text(encoding="utf-8")
    section = design.split("### 9.9 ", 1)[1]
    expected = section.split("```\n", 1)[1].split("```", 1)[0].encode("utf-8")
    raw = (ROOT / "backend/app/prompts/feedback_memory.md").read_bytes()
    assert raw == expected
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert hashlib.sha256(raw).hexdigest() == PROMPT_SHA256


def test_feedback_memory_prompt_catalog_metadata_and_variables():
    assert entry("feedback_memory") == (
        "feedback_memory",
        "看稿意见要不要记",
        "聊天",
        "chief",
        "编辑部停下来请作者看稿时，作者写的意见里有没有以后要一直照做的，有才记进记忆",
    )
    assert variables("feedback_memory") == [
        {"name": "where", "label": "看稿的那一步"},
        {"name": "what_happens", "label": "这段意见怎么处理"},
        {"name": "feedback", "label": "作者写的意见"},
        {"name": "memory", "label": "记忆"},
    ]
    validate_content("feedback_memory", default_content("feedback_memory"))
    with pytest.raises(ValueError, match="缺少变量"):
        validate_content("feedback_memory", "{{where}}{{feedback}}{{memory}}")


def test_feedback_memory_schema_matches_design_fields_and_limits():
    item = FeedbackMemoryItem(summary="每章打斗多一点", detail="以后每章打斗都多一点", lasts="一直有效")
    assert item.id == ""
    assert FeedbackMemory(reply="这一处照改，不记成规矩。").items == []
    assert set(FeedbackMemory.model_fields) == {"items", "reply"}
    assert set(FeedbackMemoryItem.model_fields) == {"id", "summary", "detail", "lasts"}
    assert FeedbackMemory.model_json_schema()["properties"]["items"]["maxItems"] == 3
    schema = FeedbackMemoryItem.model_json_schema()["properties"]
    assert schema["summary"]["maxLength"] == 30
    assert schema["lasts"]["enum"] == ["一直有效", "只管下一章", "只管这一卷", "只管下一卷"]
    assert FeedbackMemory(items=[item] * 3, reply="记住了。").items == [item] * 3
    with pytest.raises(ValidationError):
        FeedbackMemory(items=[item] * 4, reply="太多了。")
    with pytest.raises(ValidationError):
        FeedbackMemoryItem(summary="长" * 31, detail="原话", lasts="一直有效")
    with pytest.raises(ValidationError):
        FeedbackMemoryItem(summary="记一条", detail="原话", lasts="只管明天")
    assert FeedbackMemoryItem(summary="短" * 30, detail="原话", lasts="一直有效").summary == "短" * 30


@pytest.mark.parametrize("feedback", ["以后打斗多一点", "每章结尾留钩子", "打斗都多一点", "以后" + "打斗" * 20])
async def test_feedback_memory_demo_remembers_only_one_lasting_rule(monkeypatch, feedback):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(FeedbackMemory, "主编", prompt(feedback))
    assert len(result.items) == 1
    item = result.items[0]
    assert item.id == "" and item.summary == feedback[:30] and item.detail == feedback and item.lasts == "一直有效"
    assert result.reply == f"记住了：{feedback[:30]}。后面写书时会照着做。"


@pytest.mark.parametrize("feedback", ["这一卷打斗多一点", "这章打斗多一点", "这里节奏太慢", ""])
async def test_feedback_memory_demo_does_not_remember_one_off_feedback(monkeypatch, feedback):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(FeedbackMemory, "主编", prompt(feedback))
    assert result.items == []
    assert result.reply == "这段意见只用来改眼前这一处，不记成以后都要照做的规矩。"


@pytest.mark.parametrize("scope", ["下一章", "这一卷", "下一卷"])
async def test_feedback_memory_demo_preserves_selected_duration(monkeypatch, scope):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(FeedbackMemory, "主编", prompt(f"{scope}打斗都多一点"))
    assert result.items[0].lasts == f"只管{scope}"


@pytest.mark.parametrize(
    "what_happens,reply",
    [
        (
            "作者点了确认，这一处不再改。只说这一处的，不记，回话里告诉作者：要改这一处，在聊天里跟编辑部说。",
            "这段意见不记成规矩；要改这一处，在聊天里跟编辑部说。",
        ),
        (
            "前 3 章已经写完，不会照这段意见重写，这段意见是说给后面的章听的。只说前 3 章里某一章的，不记，回话里告诉作者：要改那一章，去「正文」那一页让编辑部重写。",
            "这段意见不记成规矩；要改那一章，去「正文」那一页让编辑部重写。",
        ),
    ],
)
async def test_feedback_memory_demo_explains_confirmation_and_trial_without_claiming_rewrite(
    monkeypatch, what_happens, reply
):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(FeedbackMemory, "主编", prompt("这章打斗多一点", what_happens))
    assert result.items == [] and result.reply == reply
