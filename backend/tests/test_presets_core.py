"""系统预设的逐字节来源、拼接与检查；没有模型调用。"""

import hashlib
import itertools
import json
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.llm import web_search
from app.prompts import default_content, tagged
from app.prompts.catalog import BY_NAME
from app.services import chat_tools, presets
from app.services.chat_prompts import material_values

BACKEND = Path(__file__).parents[1]


def agent_values():
    return {
        "concept": "青灯只能照见一天后的危险。",
        "material_note": "（书比较大：设定和大纲只列了目录，要细节用工具查）",
        "library": "- 陆远：提着青灯的主角。",
        "outline": "第一卷：旧城。",
        "progress": "正在写第 3 章。",
        "viewing": "第 2 章《灯火》。",
        "pending": "<等你确认的>\n请作者确认第二卷。\n</等你确认的>",
        "working": "编辑部正在干活，请等当前这一处做完。",
        "memory": "- 不写系统提示音。",
        "summary": "作者已决定青灯的限制。",
        "recent": "作者：还差一个对手。\n主编：对手可以是旧城的守夜人。",
        "quote": "<作者选中的原文>\n灯灭了。\n</作者选中的原文>",
        "retry": "上次已经做完：改了陆远的性格。",
        "note": "把旧城的守夜人补到设定库。",
    }


def tool_list(*names):
    return [{"type": "function", "function": {"name": name}} for name in names]


def custom_block(key, content, *, role="user", enabled=True, when="always"):
    return {
        "id": key,
        "title": key,
        "role": role,
        "enabled": enabled,
        "required": False,
        "when": when,
        "content": content,
    }


def test_published_preset_and_new_handbook_have_supplied_hashes():
    hashes = json.loads((BACKEND / "tests/preset_hashes.json").read_text(encoding="utf-8"))
    assert len(hashes) == 21
    assert set(hashes) == {
        path.relative_to(BACKEND).as_posix()
        for path in (BACKEND / "app/presets/chief_group/v1").iterdir()
        if path.is_file()
    } | {"app/prompts/skills/standards.md"}
    for name, expected in hashes.items():
        assert hashlib.sha256((BACKEND / name).read_bytes()).hexdigest() == expected, name


def test_system_detail_keeps_source_and_has_initial_origins():
    preset = presets.system_preset()
    assert preset["kind"] == "chief_group"
    assert preset["source"] == "system" and preset["version"] == 1
    assert preset["name"] == "主编群聊·系统默认"
    assert len(preset["blocks"]) == 19
    assert [block["id"] for block in preset["blocks"] if not block["enabled"]] == ["think", "manner"]
    for block in preset["blocks"]:
        raw = (BACKEND / f"app/presets/chief_group/v1/{block['id']}.md").read_text(encoding="utf-8")
        assert block["content"] == raw.rstrip("\r\n")
        assert block["history"] == [{"version": 1, "date": "2026-10-27", "change": block["origin"]}]
    preset["blocks"][0]["content"] = "不能污染后续读取"
    assert presets.system_preset()["blocks"][0]["content"].startswith("你是「执笔」编辑部的主编")
    assert presets.check(presets.system_preset()["blocks"]) == []


def test_default_composition_exact_order_and_unchanged_material_values():
    preset = presets.system_preset()
    values = agent_values()
    tools = tool_list("make_changes", "read_skill", "look_up_teardown", "search_web")
    result = presets.compose(preset, values, read_only=False, tools=tools)
    sent_ids = [
        "role",
        "voice",
        "task",
        "reply_style",
        "tool_lookup",
        "tool_skills",
        "tool_teardowns",
        "tool_web",
        "tool_memory",
        "act",
        "cannot",
        "after_done",
        "material",
        "memory",
        "history",
        "note",
    ]
    assert [block["id"] for block in result["preset"]["blocks"]] == sent_ids
    assert result["system"] == "\n\n".join(
        block["content"].strip() for block in preset["blocks"] if block["id"] in sent_ids and block["role"] == "system"
    )
    material = material_values(values, template="chat_agent")
    assert presets.placeholder_values(values) == {
        "资料说明": material["material_note"],
        "简介": material["book"],
        "设定库": material["library"],
        "大纲": material["outline"],
        "写到哪了": material["progress"],
        "正在看的那一页": material["viewing"],
        "等你确认的": material["pending"],
        "编辑部正在干活": material["working"],
        "记忆": material["memory"],
        "之前聊过": material["summary"],
        "聊天记录": material["recent"],
        "选中的原文": material["quote"],
        "上次做到一半": material["retry"],
        "作者这次说的": material["note"],
    }
    expected_user = "\n\n".join(
        [
            "下面是这本书现在的资料，都是最新的。" + material["material_note"],
            material["book"],
            tagged("设定库", material["library"]),
            tagged("大纲", material["outline"]),
            material["progress"],
            material["viewing"],
            material["pending"],
            material["working"],
            material["memory"],
            tagged("之前聊过", material["summary"]),
            tagged("最近的对话", material["recent"]),
            "作者那句话后面写着「（编辑部照这句做了：……）」的，是编辑部当时真改了、真记了的。",
            material["quote"],
            material["retry"],
            tagged("作者这次说的", material["note"]),
            "照前面说的做法，回作者这次说的话。",
        ]
    )
    assert result["messages"] == [
        {"role": "system", "content": result["system"]},
        {"role": "user", "content": expected_user},
    ]
    assert result["user"] == expected_user
    assert material["memory"] == tagged("记忆", values["memory"])
    assert result["user"].index(material["working"]) < result["user"].index(material["memory"])
    # 旧 chat_material 本文不改；它的数据都还在，只有任务批准的结构由预设接管。
    assert default_content("chat_material").index("{{memory}}") < default_content("chat_material").index("{{viewing}}")
    assert "id" not in result["preset"]


@pytest.mark.parametrize(
    "read_only,allow_skills,has_handbooks,has_teardowns,has_web", list(itertools.product([False, True], repeat=5))
)
def test_each_condition_matches_the_actual_tool_specs(
    monkeypatch, read_only, allow_skills, has_handbooks, has_teardowns, has_web
):
    monkeypatch.setattr(
        chat_tools.handbooks, "tool_spec", lambda: tool_list("read_skill")[0] if has_handbooks else None
    )
    teardown = SimpleNamespace(
        title="已经拆过的书",
        chapters=2,
        essence={"upto": 2, "overview": {"points": [{"title": "一条技巧"}]}, "sections": {}},
    )
    web = SimpleNamespace(specs=lambda: web_search.tool_specs(date(2026, 10, 27))) if has_web else None
    tools = chat_tools.tool_specs(
        read_only, skills=allow_skills, teardowns=[teardown] if has_teardowns else [], web=web
    )
    names = {tool["function"]["name"] for tool in tools}
    matched = presets.conditions(read_only=read_only, tools=tools)
    assert matched == {
        "always": True,
        "can_act": not read_only and "make_changes" in names,
        "ask_only": read_only,
        "skills": "read_skill" in names,
        "teardowns": "look_up_teardown" in names,
        "web": "search_web" in names,
    }
    result = presets.compose(presets.system_preset(), agent_values(), read_only=read_only, tools=tools)
    sent = {block["id"] for block in result["preset"]["blocks"]}
    for block_id, condition in {
        "act": "can_act",
        "ask_only": "ask_only",
        "tool_skills": "skills",
        "tool_teardowns": "teardowns",
        "tool_web": "web",
    }.items():
        assert (block_id in sent) is matched[condition]


def test_single_substitution_unknown_placeholder_empty_blocks_and_blank_lines():
    assert (
        presets.render_block(" {{作者这次说的}}\n\n\n\n{{未知}} ", {"作者这次说的": "{{简介}}"})
        == "{{简介}}\n\n{{未知}}"
    )
    values = agent_values()
    values["note"] = "{{简介}}"
    values["quote"] = ""
    preset = {
        "kind": "chief_group",
        "source": "mine",
        "id": "mine-1",
        "name": "自用",
        "version": 4,
        "blocks": [custom_block("empty", "\n {{选中的原文}}\n"), custom_block("note", "{{作者这次说的}}")],
    }
    result = presets.compose(preset, values, read_only=False, tools=[])
    assert result["messages"] == [{"role": "user", "content": "{{简介}}"}]
    assert result["preset"] == {
        "kind": "chief_group",
        "source": "mine",
        "id": "mine-1",
        "name": "自用",
        "version": 4,
        "blocks": [{"id": "note", "title": "note", "role": "user"}],
    }


def test_system_is_hoisted_and_adjacent_non_system_roles_merge():
    preset = {
        "kind": "chief_group",
        "source": "system",
        "name": "排列",
        "version": 1,
        "blocks": [
            custom_block("a", "一"),
            custom_block("s1", "系统一", role="system"),
            custom_block("b", "二"),
            custom_block("c", "答一", role="assistant"),
            custom_block("s2", "系统二", role="system"),
            custom_block("d", "答二", role="assistant"),
            custom_block("e", "三"),
        ],
    }
    result = presets.compose(preset, agent_values(), read_only=False, tools=[])
    assert result["messages"] == [
        {"role": "system", "content": "系统一\n\n系统二"},
        {"role": "user", "content": "一\n\n二"},
        {"role": "assistant", "content": "答一\n\n答二"},
        {"role": "user", "content": "三"},
    ]
    assert result["system"] == "系统一\n\n系统二"
    assert result["user"] == "一\n\n二\n\n【assistant】\n答一\n\n答二\n\n三"
    assert [block["id"] for block in result["preset"]["blocks"]] == ["a", "s1", "b", "c", "s2", "d", "e"]


@pytest.mark.parametrize("mode", ["deleted", "disabled", "ask_only"])
def test_check_missing_note_is_the_only_blocking_problem(mode):
    blocks = presets.system_preset()["blocks"]
    if mode == "deleted":
        blocks = [block for block in blocks if block["id"] != "note"]
    else:
        note = next(block for block in blocks if block["id"] == "note")
        note["enabled" if mode == "disabled" else "when"] = False if mode == "disabled" else "ask_only"
    errors = [row for row in presets.check(blocks) if row["severity"] == "error"]
    assert errors == [
        {
            "severity": "error",
            "code": "missing_note",
            "block_id": None,
            "title": None,
            "message": "没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。",
        }
    ]


@pytest.mark.parametrize("mode", ["deleted", "disabled"])
def test_check_required_block_warns_with_original_without(mode):
    blocks = presets.system_preset()["blocks"]
    if mode == "deleted":
        blocks = [block for block in blocks if block["id"] != "tool_skills"]
    else:
        next(block for block in blocks if block["id"] == "tool_skills")["enabled"] = False
    warnings = presets.check(blocks)
    assert warnings == [
        {
            "severity": "warning",
            "code": "required_disabled",
            "block_id": "tool_skills",
            "title": "工具：翻手册",
            "message": "关了『工具：翻手册』：主编不会翻手册，手册放着没用。",
        }
    ]


def test_check_unknown_empty_and_last_assistant_are_reminders_only():
    blocks = presets.system_preset()["blocks"]
    blocks.extend(
        [
            custom_block("unknown", "{{设定}} {{设定}}"),
            custom_block("empty", "\n "),
            custom_block("assistant", "主编以前答过", role="assistant"),
            custom_block("last_system", "最后写了系统块也一样会放到最前", role="system"),
        ]
    )
    assert presets.check(blocks) == [
        {
            "severity": "warning",
            "code": "unknown_placeholder",
            "block_id": "unknown",
            "title": "unknown",
            "message": "『{{设定}}』不是占位符，发出去会原样露出来。",
        },
        {
            "severity": "warning",
            "code": "empty_block",
            "block_id": "empty",
            "title": "empty",
            "message": "这一块是空的，发不出去。",
        },
        {
            "severity": "warning",
            "code": "assistant_last",
            "block_id": "assistant",
            "title": "assistant",
            "message": "最后一条是 assistant，模型可能不接着回；最后一条最好是 user。",
        },
    ]


def test_system_versions_discover_new_directories_and_history_only_changed_text(monkeypatch, tmp_path):
    root = tmp_path / "chief_group"
    shutil.copytree(BACKEND / "app/presets/chief_group/v1", root / "v1")
    shutil.copytree(root / "v1", root / "v2")
    v2 = json.loads((root / "v2/preset.json").read_text(encoding="utf-8"))
    v2.update(version=2, date="2026-10-28", note="换一句口吻")
    next(block for block in v2["blocks"] if block["id"] == "voice")["change"] = "改成另一种口吻，因为作者提出意见。"
    (root / "v2/preset.json").write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
    (root / "v2/voice.md").write_text("新口吻\n", encoding="utf-8")
    shutil.copytree(root / "v2", root / "v3")
    v3 = deepcopy(v2)
    v3.update(version=3, date="2026-10-29", note="只改了标题")
    next(block for block in v3["blocks"] if block["id"] == "voice")["title"] = "口吻的新标题"
    (root / "v3/preset.json").write_text(json.dumps(v3, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(presets, "_root", lambda kind: root)
    assert presets.latest_version() == 3
    assert [version["version"] for version in presets.system_versions()] == [1, 2, 3]
    assert presets.system_preset()["version"] == 3
    voice = next(block for block in presets.system_preset()["blocks"] if block["id"] == "voice")
    assert voice["content"] == "新口吻"
    assert [row["version"] for row in voice["history"]] == [1, 2]
    assert voice["history"][-1]["change"] == "改成另一种口吻，因为作者提出意见。"
    assert presets.system_preset(version=1)["version"] == 1
    with pytest.raises(ValueError, match="这一版不存在"):
        presets.system_preset(version=4)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"role": "tool"}, "role"),
        ({"when": "sometimes"}, "when"),
        ({"enabled": "yes"}, "enabled"),
        ({"content": None}, "content"),
        ({"id": " "}, "id"),
    ],
)
def test_invalid_block_shape_gives_clear_field_error(changes, match):
    block = {**custom_block("a", "内容"), **changes}
    with pytest.raises(ValueError, match=match):
        presets.validate_blocks([block])


def test_copy_blocks_drops_system_metadata_without_changing_seven_saved_fields():
    source = presets.system_preset()["blocks"]
    copied = presets.validate_blocks(source)
    assert copied == presets.copy_blocks(source)
    assert all(set(block) == set(presets.BLOCK_FIELDS) for block in copied)
    copied[0]["content"] = "只改副本"
    assert source[0]["content"] != "只改副本"
    with pytest.raises(ValueError, match="id"):
        presets.validate_blocks([custom_block("a", "一"), custom_block("a", "二")])
    with pytest.raises(ValueError, match="不支持的预设种类"):
        presets.system_preset("private")


@pytest.mark.parametrize(
    "name,text",
    [
        ("voice_chief", "私聊里主编的身份、称呼和口吻；只用在聊天，写书不带。主编在群聊里的口吻，在「预设管理」里改"),
        (
            "chat_agent",
            "群聊里点名设定师、写手、审稿，模型又能调工具时，这一路的开场和规矩：怎么查、怎么改、怎么记。主编答群聊改用「预设管理」里的预设",
        ),
        (
            "chat_voice",
            "私聊、拆的书的群聊、点名别的角色时，接在主编口吻后面：口吻只管怎么说、不改判断，写进书里和记忆里的字不带口吻。主编答群聊不用这份",
        ),
        (
            "chat_manner",
            "自己的书里私聊、点名别的角色时用：回答时想着的四件事和另外几件事；实际用接话的人的角色。主编答群聊不用这份",
        ),
        (
            "chat_material",
            "私聊、拆的书的群聊、点名别的角色时的用户提示：书的资料、之前聊过的、最近的对话和作者这次说的。主编答群聊的资料在「预设管理」里用占位符放",
        ),
        ("persona_chief", "主编的专业底子：写书的各样活都带；私聊也带。主编答群聊不用这份，用的是「预设管理」里的预设"),
    ],
)
def test_catalog_descriptions_are_the_six_task_supplied_sentences(name, text):
    assert BY_NAME[name][4] == text
