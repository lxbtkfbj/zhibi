import pytest

from app.agents.rhythm import check_chapter_plan, overdue_expectations, rhythm_text
from app.agents.schemas import ChapterDigest, ChapterOutlineDraft, VolumeAudit


def chapter(index, emotion, mood="悬"):
    return {"index": index, "emotion": emotion, "mood": mood}


def test_cross_unit_streaks_and_legacy_breaks():
    prior = [chapter(i, -1, "虐") for i in (12, 13, 14)]
    plans = [chapter(15, -1, "虐"), chapter(16, 2, "爽"), chapter(17, 0)]
    issues = check_chapter_plan(plans, "harem_xuanhuan", prior)
    assert any("第 12-15 章连续 4 章压抑" in issue for issue in issues)
    assert any("第 12-15 章主情绪都是「虐」" in issue for issue in issues)
    assert not check_chapter_plan(plans, "general", [*prior, {"index": 14}])
    assert check_chapter_plan([{"index": 18}, {"index": 19, "mood": "虐"}], "general", prior) == []


def test_low_share_climax_and_tied_peaks():
    plans = [chapter(18, 2, "爽"), chapter(19, -1, "虐"), chapter(20, -1, "悬"), chapter(21, 0, "暖")]
    strict = check_chapter_plan(plans, "harem_xuanhuan", [])
    assert "本单元 4 章里有 2 章压抑，超过三分之一" in strict
    assert any("第 18 章，不在最后 2 章内" in issue for issue in strict)
    general = check_chapter_plan(plans, "general", [])
    assert not any("超过" in issue for issue in general)
    plans[-1]["emotion"] = 2
    assert check_chapter_plan(plans, "general", []) == []


def test_old_outlines_not_in_share_denominator():
    issues = check_chapter_plan([chapter(1, -1, "虐"), {"index": 2}, chapter(3, 0)], "harem_xuanhuan", [])
    assert "本单元 2 章里有 1 章压抑，超过三分之一" in issues


def test_rhythm_text_defaults_and_numbers():
    assert "最多 3 章" in rhythm_text("harem_xuanhuan") and "三分之一" in rhythm_text("harem_xuanhuan")
    assert "最多 5 章" in rhythm_text("general") and "二分之一" in rhythm_text("general")
    assert rhythm_text("unknown") == rhythm_text("general")


@pytest.mark.parametrize("span,limit", [("中", 20), ("长", 50)])
def test_expectation_threshold_mentions_and_arranged_reminder(span, limit):
    ledger = [
        {
            "seq": 3,
            "kind": "期待",
            "status": "planted",
            "span": span,
            "planted_chapter": 1,
            "hint_chapters": [4],
            "description": "三年之约",
        }
    ]
    assert overdue_expectations(ledger, 5, 4 + limit, []) == []
    assert len(overdue_expectations(ledger, 5, 5 + limit, [])) == 1
    assert overdue_expectations(ledger, 5, 5 + limit, [{"ref": "E3", "action": "提醒"}]) == []
    assert overdue_expectations(ledger, 5, 5 + limit, [{"ref": "E3", "action": "回收"}]) == []
    assert overdue_expectations(ledger, 5, 5 + limit, [{"ref": "F3", "action": "提醒"}])
    ledger[0]["kind"] = "伏笔"
    assert overdue_expectations(ledger, 5, 5 + limit, []) == []


@pytest.mark.parametrize("raw,wanted", [("+2", 2), ("2分", 2), ("-9 分", -2), ("不明", 0), (None, 0), (99, 2)])
def test_emotion_tolerates_model_strings(raw, wanted):
    outline = ChapterOutlineDraft(
        title="一章", goal="推进", scenes=[], conflict="阻力", cool_point="突破", hook="后续", emotion=raw
    )
    assert outline.emotion == wanted


def test_task_schema_descriptions_exact():
    assert ChapterOutlineDraft.model_fields["reveals"].description == "本章揭开的秘密；没有就留空"
    assert (
        ChapterDigest.model_fields["secret_updates"].description
        == "本章正文里真的发生的信息差变化：谁新知道了哪个秘密、哪个秘密公开了"
    )
    assert VolumeAudit.model_fields["checks"].description == "五项各一条"
