"""任务 4 的十份提示词原样搬入，新增变量均可显示、渲染。"""

import hashlib
from pathlib import Path

from app.agents import editorial
from app.prompts import VARIABLE, default_content, render
from app.prompts.catalog import BY_NAME, VARIABLE_LABELS, variables

# 原设计稿的 Git blob；第三包任务 5 原样替换 plan_chapters 和 digest_chapter。
# 其余沿用前两包设计稿；文本读取统一换行，与 Git 的标准文本存储一致。
PROMPT_BLOBS = {
    "volume_directions": "dd76ef2a771b108b923fafbc9efd42ec9a08a93f",
    "audit_volume": "8d4298085a876e4a750cecc30431108c0010bbb6",
    "plan_chapters": "7b84e9a4b3d1f71788947a0b3b90fe264c19a616",
    "prepare_chapter": "1f2246e3568111f6f18cbb30f50347bec9804152",
    "write_chapter": "552334325a50476fa570fe5e17c3fc90d1702624",
    "check_consistency": "bace136fa067545cf03089c955a4aaf4a182c704",
    "digest_chapter": "a4a5e48b0a6c9289a76deb30edccb1d7777c2180",
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
