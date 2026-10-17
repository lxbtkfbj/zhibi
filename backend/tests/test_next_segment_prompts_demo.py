"""第二包任务4：schema原文、六份提示词与演示短段/收尾契约。"""

import ast
import hashlib
import re
from pathlib import Path

from app.agents import schemas as s
from app.llm import demo
from app.prompts import VARIABLE, default_content, render
from app.prompts.catalog import BY_NAME, VARIABLE_LABELS, validate_content

ROOT = Path(__file__).resolve().parents[2]
PROMPT_BLOBS = {
    "plan_segment": "20d2e12185b7b3eb44344e22aa4980e01144daec",
    "volume_directions": "dd76ef2a771b108b923fafbc9efd42ec9a08a93f",
    "audit_volume": "8d4298085a876e4a750cecc30431108c0010bbb6",
    "plan_chapters": "89520ac5bfa259475ff831a867b8e7d94739528b",
    "digest_chapter": "1f8d84c9eb8eb89ef9924ea9de9f3d70eeb3381a",
    "write_chapter": "552334325a50476fa570fe5e17c3fc90d1702624",
}


def test_schema_fields_and_descriptions_are_verbatim():
    task = (ROOT / "docs/codex任务/第二包/4-定下一段.md").read_text(encoding="utf-8")
    block = re.search(r"```python\n(.*?)```", task, re.S).group(1)
    namespace = dict(vars(s))
    exec(compile(ast.parse(block), "task-schema", "exec"), namespace)
    reference = namespace["NextSegmentDraft"]
    assert list(s.NextSegmentDraft.model_fields) == list(reference.model_fields)
    for key, field in reference.model_fields.items():
        assert s.NextSegmentDraft.model_fields[key].description == field.description
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
    assert BY_NAME["plan_segment"] == ("plan_segment", "定下一段", "规划", "chief", "每一段开写前规划下一段")
    assert VARIABLE_LABELS["last_segment"] == "上一段"
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
    base = "【全书方向：关键节点】\n节点 4「重建家园」· 结局\n\n【篇幅】\n"
    normal = demo._next_segment(base + "篇幅还宽裕，按正常的一段来规划。\n\n要求：说只够一段时选结局。")
    assert normal.end.ref == 0 and not normal.answers
    finale = demo._next_segment(base + "剩下的篇幅只够两段左右：这一段是收尾段。")
    assert finale.answers and finale.end.ref == 0
    last = demo._next_segment(base + "剩下的篇幅只够一段了：这一段就是最后一段，终点就是结局。")
    assert last.end.ref == 4 and last.end.kind == "结局"


def test_demo_want_changes_every_few_chapters():
    assert demo._digest("第 1 章《开篇》已经定稿").character_updates[0].want == ""
    assert demo._digest("第 3 章《资格》已经定稿").character_updates[0].want == "拿到外门考核资格并保护老人"
    assert demo._digest("第 6 章《取证》已经定稿").character_updates[0].want == "查清师兄的死因"


def test_demo_segment_flag_fixture_only_affects_explicit_first_round():
    marker = "测试短段，测试段提醒"
    first = demo._next_segment(marker)
    assert not first.pursuit
    revised = demo._next_segment(marker + "\n【当前的下一段】\n这一段的目标：取证\n【修改要求】\n补全追求")
    assert revised.pursuit
    assert demo._next_segment("普通演示").pursuit
