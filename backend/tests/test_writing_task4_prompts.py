"""任务 4 的十份提示词原样搬入，新增变量均可显示、渲染。"""

import hashlib
from pathlib import Path

from app.agents import editorial
from app.prompts import VARIABLE, default_content, render
from app.prompts.catalog import BY_NAME, VARIABLE_LABELS, variables

# 原设计稿在任务开始时的 Git blob；文本读取统一换行，与 Git 的标准文本存储一致。
PROMPT_BLOBS = {
    "volume_directions": "ccf7cb1d15aab4483e1a06c1ddd1368ff311c0d1",
    "audit_volume": "29421dc1d473844210b395e7ac636f44395ca3a1",
    "plan_chapters": "35b2501f07920e3c122eccbab7958efd4d693315",
    "prepare_chapter": "1f2246e3568111f6f18cbb30f50347bec9804152",
    "write_chapter": "62907539b5c999ca6d5877ce96e8c16fbafcff4c",
    "check_consistency": "bace136fa067545cf03089c955a4aaf4a182c704",
    "digest_chapter": "617d97c60b66a5391d5b55ac9a2d82c6ff5028c6",
    "review_chapter": "0461852be16ad7f0a4f81c4f537be0f9041da04e",
    "recap_unit": "c564536ba7ae7825f2bc2ed813d342df7a4439fe",
    "recap_volume": "a060bdccbe7e54325d0787388702e72c5403cd68",
}


def test_prompt_sources_moved_verbatim_and_every_variable_registered():
    root = Path(__file__).resolve().parents[2]
    for name, expected in PROMPT_BLOBS.items():
        assert name in BY_NAME
        assert not (root / "docs/codex任务/第一包/提示词" / f"{name}.md").exists()
        content = (root / "backend/app/prompts" / f"{name}.md").read_text(encoding="utf-8").encode()
        assert hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == expected
        expected_variables = set(VARIABLE.findall(default_content(name)))
        assert {item["name"] for item in variables(name)} == expected_variables
        assert expected_variables <= VARIABLE_LABELS.keys()
        assert "{{" not in render(name, **dict.fromkeys(expected_variables, "测试上下文"))
    assert VARIABLE_LABELS["rhythm"] == "节奏底线"
    assert {"secrets", "rhythm", "revision"} <= {item["name"] for item in variables("plan_chapters")}


class PromptCapture:
    def __init__(self):
        self.prompts = []

    async def structured(self, role, schema, system, user, *, purpose):
        self.prompts.append(user)

    async def stream_text(self, role, system, user, *, purpose):
        self.prompts.append(user)
        yield "正文"


async def test_editorial_volume_calls_receive_target_and_writer_receives_writer_secrets():
    llm = PromptCapture()
    for name, call in (("volume_directions", editorial.volume_directions), ("audit_volume", editorial.audit_volume)):
        blocks = dict.fromkeys(VARIABLE.findall(default_content(name)), "")
        blocks["target_node"] = "节点 2「走向第二卷」"
        if name == "audit_volume":
            blocks.pop("plan")
            blocks.pop("found")
            await call(llm, blocks, {}, ["提示：单元没有期待动作"], purpose="测试")
        else:
            await call(llm, blocks, purpose="测试")
        assert "节点 2「走向第二卷」" in llm.prompts[-1]
    blocks = dict.fromkeys(VARIABLE.findall(default_content("write_chapter")), "")
    blocks.update(secrets="列表版不应交给写手", secrets_for_writer="【本章的信息差】写手版")
    assert [chunk async for chunk in editorial.write_chapter(llm, blocks)] == ["正文"]
    assert "【本章的信息差】写手版" in llm.prompts[-1] and "列表版不应交给写手" not in llm.prompts[-1]
