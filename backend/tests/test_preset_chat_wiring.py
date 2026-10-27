"""预设消息真正交给路由器、逐来回记调用；全程假客户端或演示模型。"""

import json
from unittest.mock import AsyncMock, Mock

from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.llm import demo
from app.llm.router import LLMRouter, ResolvedProfile
from app.models import LlmCall
from app.prompts import prompt_names_for, prompt_parts_for
from app.services import chat_tools


async def test_message_list_reaches_model_in_order_and_keeps_tool_round_contract(sessionmaker, monkeypatch):
    messages = [
        {"role": "system", "content": "主编系统"},
        {"role": "user", "content": "前面的问题"},
        {"role": "assistant", "content": "前面的答复"},
        {"role": "user", "content": "查楚风的设定"},
    ]
    preset = {
        "kind": "chief_group",
        "source": "mine",
        "id": "作者预设",
        "name": "自己的预设",
        "version": 3,
        "blocks": [{"id": "custom", "title": "作者这次说的", "role": "user"}],
    }
    histories, choices = [], []

    class FakeModel:
        def bind_tools(self, tools, **kwargs):
            choices.append(kwargs)
            return self

        async def astream(self, history):
            histories.append(list(history))
            if len(histories) == 1:
                yield AIMessageChunk(
                    content="先查。",
                    tool_call_chunks=[
                        {
                            "id": "q",
                            "index": 0,
                            "name": "look_up_settings",
                            "args": json.dumps({"names": ["楚风"]}, ensure_ascii=False),
                        }
                    ],
                    usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
                )
            else:
                yield AIMessageChunk(
                    content="查好了。", usage_metadata={"input_tokens": 30, "output_tokens": 6, "total_tokens": 36}
                )

    profile = ResolvedProfile(name="假多消息客户端", provider="openai_compatible", model="fake-no-network")
    run_tool = AsyncMock(return_value="资料全文")
    tools = chat_tools.tool_specs(True, skills=False, memories=False)
    expected_user = "前面的问题\n\n【assistant】\n前面的答复\n\n查楚风的设定"
    async with LLMRouter(sessionmaker) as llm:
        monkeypatch.setattr(llm, "resolve", AsyncMock(return_value=profile))
        monkeypatch.setattr(llm, "_chat_model", Mock(return_value=FakeModel()))
        output = [
            event
            async for event in llm.tool_rounds(
                "chief",
                "不能用这个 system",
                "不能用这个 user",
                tools,
                run_tool,
                purpose="多消息预设测试",
                max_rounds=2,
                messages=messages,
                preset=preset,
            )
        ]
    assert [(message.type, message.content) for message in histories[0]] == [
        ("system", "主编系统"),
        ("human", "前面的问题"),
        ("ai", "前面的答复"),
        ("human", "查楚风的设定"),
    ]
    assert [(message.type, message.content) for message in histories[1][-2:]] == [
        ("ai", "先查。"),
        ("tool", "资料全文"),
    ]
    assert histories[1][-2].tool_calls[0]["id"] == histories[1][-1].tool_call_id == "q"
    assert choices == [{}, {"tool_choice": "none"}]
    assert output == [("text", "先查。"), ("reset", ""), ("text", "查好了。")]
    run_tool.assert_awaited_once()
    async with sessionmaker() as session:
        calls = list(await session.scalars(select(LlmCall).order_by(LlmCall.id)))
    assert len(calls) == 2 and all(call.ok for call in calls)
    assert [(call.prompt_tokens, call.completion_tokens) for call in calls] == [(20, 5), (30, 6)]
    for call in calls:
        assert call.request["system"] == "主编系统"
        assert call.request["messages"] == messages and call.request["preset"] == preset
        assert call.request["prompt_names"] == prompt_names_for("主编系统", expected_user)
        assert call.request["prompt_parts"] == prompt_parts_for("主编系统", expected_user)
    assert calls[0].request["user"] == expected_user
    assert calls[1].request["user"] == expected_user + (
        '\n\n—— 第 1 来回调的工具 ——\n调了 look_up_settings：{"names": ["楚风"]}\n工具回：资料全文'
    )


async def test_demo_accepts_user_only_message_list_and_records_first_round(sessionmaker, monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    messages = [{"role": "user", "content": "<作者这次说的>\n你好\n</作者这次说的>"}]
    async with LLMRouter(sessionmaker) as llm:
        output = [
            event
            async for event in llm.tool_rounds(
                "chief",
                "",
                "",
                [],
                AsyncMock(),
                purpose="无 system 的预设",
                messages=messages,
            )
        ]
    assert any(kind == "text" and content for kind, content in output)
    async with sessionmaker() as session:
        call = await session.scalar(select(LlmCall))
        assert call.request["messages"] == messages
        assert call.request["system"] == "" and call.request["user"] == messages[0]["content"]
