"""第二包任务4：schema原文、六份提示词与演示短段/收尾契约。"""

import hashlib
from pathlib import Path

from app.agents import schemas as s
from app.llm import demo
from app.prompts import VARIABLE, default_content, render
from app.prompts.catalog import BY_NAME, VARIABLE_LABELS, validate_content

ROOT = Path(__file__).resolve().parents[2]
PROMPT_BLOBS = {
    "volume_directions": "dd76ef2a771b108b923fafbc9efd42ec9a08a93f",
    "audit_volume": "8d4298085a876e4a750cecc30431108c0010bbb6",
    "write_chapter": "552334325a50476fa570fe5e17c3fc90d1702624",
}


def test_schema_fields_and_descriptions_are_verbatim():
    assert not hasattr(s, "NextSegmentDraft")
    assert "text" in s.NextArcDraft.model_fields
    assert (
        s.CharacterUpdate.model_fields["want"].description == "本章结束时此人此刻最想马上做成的事；变了才写，没变就留空"
    )
    fields = list(s.CharacterUpdate.model_fields)
    assert fields.index("want") == fields.index("condition") + 1


def test_six_prompts_moved_verbatim_and_registered():
    for name, expected in PROMPT_BLOBS.items():
        assert not (ROOT / "docs/codex任务/第二包/提示词" / f"{name}.md").exists()
        content = default_content(name)
        encoded = content.encode()
        assert hashlib.sha1(f"blob {len(encoded)}\0".encode() + encoded).hexdigest() == expected
        keys = set(VARIABLE.findall(content))
        assert keys <= VARIABLE_LABELS.keys()
        validate_content(name, content)
        assert "{{" not in render(name, **dict.fromkeys(keys, "测试上下文"))
    assert BY_NAME["plan_segment"] == ("plan_segment", "定下一篇", "规划", "chief", "每一篇开写前规划下一篇")
    assert VARIABLE_LABELS["last_segment"] == "上一篇"
    assert VARIABLE_LABELS["length"] == "篇幅与收束"


def test_short_segment_and_finale_demo_contract():
    for marker in ("测试短段", "测试收尾"):
        text = marker
        assert marker in text
        split = demo._segment_volumes(text + "\n卷号从第 5 卷开始")
        assert [(v.index, v.chapter_count) for v in split.volumes] == [(5, 6)]
        for index in (1, 5):
            plan = demo._volume_plan(text + f"\n请为第 {index} 卷写「卷纲」")
            assert [u.chapter_count for u in plan.units] == [3, 3]
    assert [v.index for v in demo._segment_volumes("卷号从第 5 卷开始").volumes] == [5, 6]
    base = "【大纲】\n节点 4「重建家园」· 结局\n\n【篇幅】\n"
    normal = demo._next_segment(base + "篇幅还宽裕，按正常的一篇来规划。\n\n要求：说只够一篇时选结局。")
    assert normal.end.ref == 0 and not normal.secret
    finale = demo._next_segment(base + "剩下的篇幅只够两篇左右：这一篇是收尾篇。")
    assert finale.text and finale.end.ref == 0
    last = demo._next_segment(base + "剩下的篇幅只够一篇了：这一篇就是最后一篇，终点就是结局。")
    assert last.end.ref == 4 and last.end.title == "重建家园"


def test_demo_want_changes_every_few_chapters():
    assert demo._digest("第 1 章《开篇》已经定稿").character_updates[0].want == ""
    assert demo._digest("第 3 章《资格》已经定稿").character_updates[0].want == "拿到外门考核资格并保护老人"
    assert demo._digest("第 6 章《取证》已经定稿").character_updates[0].want == "查清师兄的死因"


def test_demo_segment_flag_fixture_only_affects_explicit_first_round():
    marker = "测试短篇，测试篇提醒"
    first = demo._next_segment(marker)
    assert len(first.text) < 150
    revised = demo._next_segment(marker + "\n【当前的下一篇】\n这一篇的目标：取证\n【修改要求】\n补全追求")
    assert len(revised.text) >= 150
    assert len(demo._next_segment("普通演示").text) >= 150
