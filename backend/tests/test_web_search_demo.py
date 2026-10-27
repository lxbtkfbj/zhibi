"""联网搜索演示规则和仅替换两行的提示词契约，不连接外网。"""

import hashlib
from pathlib import Path

import pytest

from app.llm import demo
from app.llm.router import ToolCall
from app.services import presets

ROOT = Path(__file__).resolve().parents[2]


def _user(note, library=""):
    return f"<作者这次说的>\n{note}\n</作者这次说的>\n<设定库>\n{library}\n</设定库>"


@pytest.mark.parametrize(
    "note,query",
    [
        ("上网搜 斗破苍穹 异火", "斗破苍穹 异火"),
        ("帮我上网搜　「 斗破苍穹 异火 」　。后面不用搜", "斗破苍穹 异火"),
        *((f"上网搜 词{mark}后面不用搜", "词") for mark in "。？！?!\n"),
        ("上网搜 " + "字" * 40, "字" * 30),
        ("先上网搜「」。再说", "先上网搜「」。再说"),
        ("上网搜\n" + "字" * 40, "上网搜\n" + "字" * 26),
    ],
)
def test_demo_search_query_matches_task(note, query):
    planned, text = demo.tool_turn("主编", _user(note), ["search_web"], [])
    assert planned == [("search_web", {"query": query})]
    assert text == ""


def test_demo_search_precedes_lookup_and_continues_normal_tool_flow():
    user = _user("上网搜 《斗破苍穹》异火。开书时楚风的性格怎么样？", "- 楚风：主角")
    tools = ["read_skill", "look_up_settings", "look_up_teardown", "search_web"]
    done = []
    expected = [
        ("search_web", {"query": "《斗破苍穹》异火"}),
        ("look_up_teardown", {"book": "斗破苍穹", "look": "精髓", "words": []}),
        ("read_skill", {"name": "开书"}),
        ("look_up_settings", {"names": ["楚风"]}),
    ]
    for i, call in enumerate(expected):
        planned, text = demo.tool_turn("主编", user, tools, done)
        assert planned == [call]
        assert text == ""
        done.append((ToolCall(str(i), *call), "假资料"))
    for available in (tools, []):
        planned, text = demo.tool_turn("主编", user, available, done)
        assert planned == []
        assert text.count("上网搜了「《斗破苍穹》异火」。") == 1
        assert "翻了《斗破苍穹》的精髓。" in text
        assert "翻了开书手册。" in text and "查了楚风。" in text


@pytest.mark.parametrize(
    "system,user,tools",
    [
        ("主编", _user("上网搜 斗破苍穹 异火"), []),
        ("主编", _user("斗破苍穹 异火"), ["search_web"]),
        ("主编", _user("主角怎么写", "上网搜 斗破苍穹 异火"), ["search_web"]),
        ("主编\n作者导入的别人已经写好的小说", _user("上网搜 斗破苍穹 异火"), ["search_web"]),
        ("主编", "<这本书>\n原书信息\n</这本书>\n" + _user("上网搜 斗破苍穹 异火"), ["search_web"]),
    ],
)
def test_demo_search_does_not_expand_existing_admission(system, user, tools):
    planned, text = demo.tool_turn(system, user, tools, [])
    assert planned == []
    assert "上网搜了「" not in text


@pytest.mark.parametrize(
    "name,prefix,line_digest,rest_digest,draft",
    [
        (
            "chat_agent",
            "3. ",
            "978867b19c0799a4f5453b50f986177d08fcded439cc32d83e361129f9b71462",
            "4cfe66419504bcf297a036c5651c571fa75dc755d9a049e4fdbca47df002a713",
            "chat_agent-第3条.md",
        ),
        (
            "chat_teardown",
            "2. ",
            "383767037ae13581d633a840c6c71ff22ba37f71fe64739dc41ed2f80a28d68d",
            "bb8089538fcc0784a1b6294feafc7309cdd79fa2fab5ce21f32e8ceef3fca86a",
            "chat_teardown-第2条.md",
        ),
    ],
)
def test_web_search_rule_and_layered_prompt_baseline_are_byte_exact(name, prefix, line_digest, rest_digest, draft):
    lines = (ROOT / f"backend/app/prompts/{name}.md").read_bytes().splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if line.startswith(prefix.encode())]
    assert len(indices) == 1
    line = lines.pop(indices[0])
    assert hashlib.sha256(line.rstrip(b"\r\n")).hexdigest() == line_digest
    assert hashlib.sha256(b"".join(lines)).hexdigest() == rest_digest
    assert not (ROOT / "docs/codex任务/主编联网搜索/提示词" / draft).exists()


def test_chief_group_preset_web_instructions_follow_actual_search_tool():
    preset = presets.system_preset()
    block = next(block for block in preset["blocks"] if block["id"] == "tool_web")
    assert block["title"] == "工具：上网搜" and block["when"] == "web"
    values = dict.fromkeys(("concept", "progress", "memory", "viewing", "note"), "")
    tool = {"function": {"name": "search_web"}}
    with_tool = presets.compose(preset, values, read_only=True, tools=[tool])
    without_tool = presets.compose(preset, values, read_only=True, tools=[])
    assert block["content"].strip() in with_tool["system"]
    assert "search_web" in block["content"] and "read_webpage" in block["content"]
    assert block["content"].strip() not in without_tool["system"]
