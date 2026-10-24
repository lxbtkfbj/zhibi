"""查拆过的书的演示规则与只插一行的提示词契约，不调真实模型。"""

import ast
import hashlib
import re
from pathlib import Path

import pytest

from app.llm import demo
from app.llm.router import ToolCall

ROOT = Path(__file__).resolve().parents[2]


def _user(note, library=""):
    return f"<作者这次说的>\n{note}\n</作者这次说的>\n<设定库>\n{library}\n</设定库>"


def test_demo_first_book_lookup_precedes_handbook_and_existing_setting_lookup():
    user = _user("开书时《逆天邪神》和《惊悚乐园》怎么写，楚风的性格怎么样？", "- 楚风：主角")
    tools = ["read_skill", "look_up_settings", "look_up_teardown"]
    planned, text = demo.tool_turn("主编", user, tools, [])
    assert planned == [("look_up_teardown", {"book": "逆天邪神", "look": "精髓", "words": []})]
    assert text == ""

    done = [(ToolCall("t", *planned[0]), "精髓全文")]
    planned, text = demo.tool_turn("主编", user, tools, done)
    assert planned == [("read_skill", {"name": "开书"})]
    done.append((ToolCall("s", *planned[0]), "手册全文"))
    planned, text = demo.tool_turn("主编", user, tools, done)
    assert planned == [("look_up_settings", {"names": ["楚风"]})]
    done.append((ToolCall("q", *planned[0]), "性格全文"))
    planned, text = demo.tool_turn("主编", user, tools, done)
    assert planned == []
    assert "翻了《逆天邪神》的精髓。" in text
    assert "翻了《惊悚乐园》的精髓。" not in text
    assert "翻了开书手册。" in text and "查了楚风。" in text


@pytest.mark.parametrize(
    "note,tools",
    [
        ("《逆天邪神》开局怎么写的？", []),
        ("逆天邪神开局怎么写的？", ["look_up_teardown"]),
        ("《》开局怎么写的？", ["look_up_teardown"]),
    ],
)
def test_demo_does_not_lookup_without_book_title_or_tool(note, tools):
    planned, text = demo.tool_turn("主编", _user(note), tools, [])
    assert planned == []
    assert "的精髓。" not in text


def test_demo_uses_this_note_not_other_prompt_sections():
    planned, text = demo.tool_turn("主编", _user("主角该怎么写？", "《逆天邪神》"), ["look_up_teardown"], [])
    assert planned == []
    assert "的精髓。" not in text


def test_demo_done_lookup_is_not_repeated_and_remains_in_final_without_tools():
    done = [(ToolCall("t", "look_up_teardown", {"book": "逆天邪神", "look": "精髓", "words": []}), "精髓")]
    for tools in (["look_up_teardown"], []):
        planned, text = demo.tool_turn("主编", _user("《逆天邪神》开局怎么写的？"), tools, done)
        assert planned == []
        assert text.count("翻了《逆天邪神》的精髓。") == 1


def test_demo_fake_tools_still_defaults_to_false():
    tree = ast.parse(Path(demo.__file__).read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FAKE_TOOLS" for t in node.targets)
    ]
    assert len(assignments) == 1
    assert ast.literal_eval(assignments[0].value) is False


def test_teardown_prompt_only_inserts_approved_line_and_renumbers_later_rules():
    prompt = ROOT / "backend/app/prompts/chat_agent.md"
    lines = prompt.read_bytes().splitlines(keepends=True)
    handbook = next(i for i, line in enumerate(lines) if line.startswith("2. 编辑部有几本专业手册".encode()))
    added = lines.pop(handbook + 1)
    assert hashlib.sha256(added.rstrip(b"\r\n")).hexdigest() == (
        "18fbaae647f9e48534d9a42eb62cf72b4a4640a701ad4e579dcd2823b667db47"
    )
    changed = 0
    for i in range(handbook + 1, len(lines)):
        if re.match(rb"^[4-8]\. ", lines[i]):
            lines[i] = str(int(lines[i][:1]) - 1).encode() + lines[i][1:]
            changed += 1
    assert changed == 5
    assert hashlib.sha256(b"".join(lines)).hexdigest() == (
        "42894c24975b767516a766cd15716e7dbfed31d2425bb086f71f559aeb2344e0"
    )
    assert not (ROOT / "docs/codex任务/主编查拆过的书/提示词/chat_agent-查拆过的书一条.md").exists()
