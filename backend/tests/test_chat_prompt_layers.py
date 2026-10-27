"""主编口吻只管聊天；真实演示请求锁定分层、资料与写书旧合同。"""

import difflib
import hashlib
import json
import os
import re
import sys
import types
import uuid
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.agents import editorial
from app.config import get_settings
from app.llm import demo
from app.llm.router import LLMRouter, ToolsUnsupported
from app.main import create_app
from app.models import Book, Chapter, Character, ChatThread, Job, LlmCall, MeetingMessage, PromptOverride, Volume
from app.prompts import render, tagged
from app.services import chat, chat_agent, chat_context, chat_plans, presets, teardown_chat

BASELINE_PATH = Path(__file__).with_name("fixtures") / "chat_prompt_layers_before.json"
PRESET_BASELINE_PATH = Path(__file__).with_name("fixtures") / "preset_legacy_prompts_head.json"
PLAN_KEYS = ("concept", "library", "outline", "progress", "pending", "summary", "note")
PLAN_SUMMARY = "作者已经决定：青灯只能照见一天后的危险。"
_EVIDENCE = {}

# 只容许作者在任务第 1 节批准的三处变化，不能用当前 persona 自己证明自己。
SYSTEM_CHANGES = (
    (
        "- 有主见，说实话。觉得不行就直说，不客套、不奉承；该拿主意的时候就推荐一个；别的书记不准的地方，说明是你的印象。",
        "- 有主见，说实话。觉得不行就直说，不客套、不奉承。能拿主意的就拿主意：给出你觉得最好的那一个，说清为什么；真要看作者口味、几条路各有各的好，才摆出来让他挑，也说你倾向哪个。别的书记不准的地方，说明是你的印象。",
    ),
    ("你说话干脆利落，像在开编辑部例会，但用白话", "写给他看的都用白话"),
    ("只完成本次任务要求的事，不要替其他角色做工作。", "只完成本次任务要求的事。"),
)


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture(scope="module", autouse=True)
def optional_evidence():
    """验收时显式指定 Git 外的路径；日常测试不生成任何工作区文件。"""
    yield
    if destination := os.environ.get("ZHIBI_LAYER_EVIDENCE"):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_EVIDENCE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def baseline():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def seed_book(sessionmaker, *, source="new"):
    async with sessionmaker() as session:
        book = Book(
            title="分层回归书",
            source=source,
            status="ready",
            concept={"story": "陆远提着青灯进入旧城。", "target_length": 30, "chapter_words": 3000},
            teardown={"stage": "imported", "author": "原作者", "original_volumes": True}
            if source == "teardown"
            else {},
        )
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="旧城", summary="陆远找到青灯。", status="planned")
        session.add(volume)
        await session.flush()
        session.add_all(
            [
                Character(book_id=book.id, name="陆远", role_type="主角", personality="谨慎", aliases=[]),
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=1,
                    title="灯火",
                    content="陆远提着青灯走进旧城。",
                    summary="陆远入城。",
                    word_count=12,
                    status="final",
                    source="imported" if source == "teardown" else "generated",
                ),
            ]
        )
        await session.commit()
        return book.id


async def seed_plan_conversation(sessionmaker):
    bid = await seed_book(sessionmaker)
    async with sessionmaker() as session:
        session.add(
            Job(
                book_id=bid,
                kind="write_book",
                status="waiting_author",
                thread_id=str(uuid.uuid4()),
                pending={"kind": "volume_review", "volume": 1},
            )
        )
        session.add(ChatThread(book_id=bid, thread="chief", summary=PLAN_SUMMARY))
        session.add_all(
            [
                MeetingMessage(
                    book_id=bid,
                    speaker="author",
                    kind="note",
                    content="青灯只照见一天后的危险，就这么定。",
                    payload={"thread": "chief"},
                ),
                MeetingMessage(
                    book_id=bid,
                    speaker="chief",
                    kind="speech",
                    content="保住一天的限制，陆远得自己判断该不该进城。",
                    payload={"thread": "chief"},
                ),
            ]
        )
        await session.flush()
        note = MeetingMessage(
            book_id=bid,
            speaker="author",
            kind="note",
            content="总结一下前面定下的。",
            payload={"thread": "chief"},
        )
        session.add(note)
        await session.commit()
        return bid, note.id


async def calls_for(sessionmaker, bid):
    async with sessionmaker() as session:
        rows = list(await session.scalars(select(LlmCall).where(LlmCall.book_id == bid).order_by(LlmCall.id)))
    assert rows and all(row.model == "demo" and row.ok for row in rows)
    return rows


def expected_system(role, template, values):
    """逐层写出约定，不调用被测的 chat_prompts.system_prompt。"""
    layers = [render(f"persona_{role}", rules="")]
    if role == "chief":
        layers.append(render("chat_voice", voice=render("voice_chief")))
    layers.append(render(template, **values))
    if template != "chat_teardown":
        layers.append(render("chat_manner", role_focus=values["role_focus"]))
    layers.append(render("rules"))
    return "\n\n".join(layers)


def expected_material(template, values):
    """资料包装独立列清，尤其不能把方案卡要用的 raw 值提前 tagged。"""
    material = dict.fromkeys(
        (
            "material_note",
            "book",
            "library",
            "outline",
            "progress",
            "memory",
            "viewing",
            "related",
            "extras",
            "pending",
            "working",
            "retry",
            "summary",
            "recent",
            "quote",
            "note",
        ),
        "",
    )
    for key in ("material_note", "library", "outline", "pending", "summary", "recent", "quote", "note"):
        material[key] = values.get(key, "")
    if template == "chat_teardown":
        material.update(
            book=tagged("这本书", values["book_info"]),
            library="（从原文拆出来的）\n" + values["library"],
            outline="（从原文倒推的）\n" + values["outline"],
            viewing=tagged("作者正在看的那一页", values["viewing"]),
            related=values["related"],
            retry=values["retry"],
        )
    else:
        material.update(
            book=tagged("简介", values["concept"]),
            progress=tagged("写到哪了", values["progress"]),
            memory=tagged("记忆", values["memory"]),
        )
        if template == "chat_agent":
            material.update(
                viewing=tagged("作者正在看的那一页", values["viewing"]),
                working=values["working"],
                retry=values["retry"],
            )
        else:
            material.update(related=tagged("和这次的话有关的资料", values["related"]), extras=values["extras"])
    return render("chat_material", **material)


def frozen_legacy_request(role, template, values):
    """用开工 HEAD 的源码和原文拼，不拿当前被测 helper 或当前提示词证明自己。"""
    baseline = json.loads(PRESET_BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["head"] == "e2e9970f98ad9038528739d6937344839f7cfc25"

    def frozen_render(name, **parameters):
        text = re.sub(r"\{\{(\w+)\}\}", lambda match: str(parameters[match[1]]).strip(), baseline["prompts"][name])
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    namespace = {"render": frozen_render, "tagged": lambda name, body: f"<{name}>\n{body.strip()}\n</{name}>"}
    source = baseline["chat_prompts_source"].replace("from app.prompts import render, tagged", "")
    exec(compile(source, f"{baseline['head']}:chat_prompts.py", "exec"), namespace)
    return {
        "system": namespace["system_prompt"](role, template, **values),
        "user": frozen_render("chat_material", **namespace["material_values"](values, template=template)),
    }


@pytest.mark.parametrize(
    "source,tools,role,private",
    [
        ("new", True, "chief", False),
        ("new", True, "lorekeeper", False),
        ("new", False, "chief", True),
        ("new", False, "lorekeeper", True),
        ("teardown", True, "chief", False),
        ("teardown", False, "chief", False),
        ("teardown", False, "lorekeeper", True),
    ],
)
async def test_demo_requests_have_exact_layers_and_material(
    client, sessionmaker, monkeypatch, source, tools, role, private
):
    monkeypatch.setattr(demo, "FAKE_TOOLS", tools)
    captured = []
    module, name = (
        (chat_agent, "agent_values")
        if tools
        else ((teardown_chat, "values") if source == "teardown" else (chat, "reply_values"))
    )
    original = getattr(module, name)

    async def capture(*args, **kwargs):
        values = await original(*args, **kwargs)
        captured.append(values)
        return values

    monkeypatch.setattr(module, name, capture)
    bid = await seed_book(sessionmaker, source=source)
    note = "这本书的气氛怎么样？"
    target = {"to": role} if private else {"ask": role} if role != "chief" else {}
    response = await client.post(f"/api/books/{bid}/notes", json={"content": note, **target})
    assert response.status_code == 201, response.text
    history = (await client.get(f"/api/books/{bid}/meeting")).json()
    reply = next(row for row in history if row["payload"].get("reply_to") == [response.json()["id"]])
    assert reply["content"] and not reply["payload"].get("state"), reply
    assert len(captured) == 1
    values = captured[0]
    template = "chat_teardown" if source == "teardown" else "chat_agent" if tools else "chat_reply"
    calls = [
        row
        for row in await calls_for(sessionmaker, bid)
        if row.purpose == f"聊天·{'主编' if role == 'chief' else '设定师'}"
    ]
    assert calls
    for call in calls:
        request = call.request
        if source != "teardown" and tools and role == "chief":
            expected = presets.compose(presets.system_preset(), values, read_only=True, tools=request["schema"])
            assert {key: request[key] for key in ("system", "user", "messages", "preset")} == expected
            assert request["system"].startswith("你是「执笔」编辑部的主编")
            assert request["preset"]["name"] == "主编群聊·系统默认"
            assert request["preset"]["source"] == "system" and request["preset"]["version"] == 1
            assert request["messages"] == [
                {"role": "system", "content": request["system"]},
                {"role": "user", "content": request["user"]},
            ]
            assert "<口吻>" not in request["system"]
            assert "persona_chief" not in request["prompt_names"]
            continue
        frozen = frozen_legacy_request(role, template, values)
        assert request["system"].encode("utf-8") == frozen["system"].encode("utf-8")
        assert request["user"].encode("utf-8") == frozen["user"].encode("utf-8")
        assert "preset" not in request and "messages" not in request
        assert request["system"] == expected_system(role, template, values)
        assert request["user"] == expected_material(template, values)
        assert request["system"].endswith(render("rules"))
        assert request["system"].count("## 通用规则") == 1
        assert request["user"].endswith(tagged("作者这次说的", note) + "\n\n照前面说的做法，接作者这次说的话。")
        assert "回答的时候，想着这四件事" not in request["user"]
        assert "## 通用规则" not in request["user"]
        assert "照你的角色说话：" not in request["user"]
        if role == "chief":
            assert values["role_focus"] == ""
            assert "照你的角色说话：" not in request["system"]
            assert request["system"].count("\n<口吻>\n") == 1
        else:
            focus = (teardown_chat if source == "teardown" else chat_context).ROLE_FOCUS[role]
            assert values["role_focus"] == "照你的角色说话：" + focus
            assert "照你的角色说话：" + focus in request["system"]
            assert "<口吻>" not in request["system"]
            assert "voice_chief" not in request["prompt_names"]
            assert "chat_voice" not in request["prompt_names"]
        if source == "teardown":
            lookup = teardown_chat.LOOKUP_TOOLS if tools else teardown_chat.LOOKUP_PLAIN
            assert lookup in request["system"] and lookup not in request["user"]
            assert "chat_manner" not in request["prompt_names"]
            assert "<这本书>" in request["user"] and "<写到哪了>" not in request["user"]
            assert "（从原文拆出来的）\n" in request["user"]
            assert "（从原文倒推的）\n" in request["user"]
        elif tools:
            assert request["prompt_parts"] == {
                "system": ["persona_lorekeeper", "chat_agent", "chat_manner", "rules"],
                "user": ["chat_material"],
            }
            assert set(request["prompt_names"]) == {
                "persona_lorekeeper",
                "chat_agent",
                "chat_manner",
                "rules",
                "chat_material",
            }
        else:
            assert "<简介>" in request["user"] and "<定调>" not in request["user"]
            assert "<作者正在看的那一页>" not in request["user"]
    _EVIDENCE[f"{source}_{template}_{role}_{'tools' if tools else 'plain'}"] = calls[0].request


@pytest.mark.parametrize("route", ["fall_back", "again"])
async def test_fallback_and_rewrite_only_requests_are_byte_identical_to_opening_head(
    client, sessionmaker, monkeypatch, route
):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    captured = []
    original = chat.reply_values

    async def capture(*args, **kwargs):
        values = await original(*args, **kwargs)
        captured.append(values)
        return values

    monkeypatch.setattr(chat, "reply_values", capture)
    if route == "fall_back":

        async def refuse(self, *args, **kwargs):
            raise ToolsUnsupported("演示拒绝工具")
            yield

        monkeypatch.setattr(LLMRouter, "tool_rounds", refuse)
    bid = await seed_book(sessionmaker)
    response = await client.post(f"/api/books/{bid}/notes", json={"content": "这本书的气氛怎么样？"})
    assert response.status_code == 201, response.text
    if route == "again":
        history = (await client.get(f"/api/books/{bid}/meeting")).json()
        reply = next(row for row in history if row["payload"].get("reply_to") == [response.json()["id"]])
        rewritten = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
        assert rewritten.status_code == 202, rewritten.text
    assert len(captured) == 1
    call = (await calls_for(sessionmaker, bid))[-1]
    expected = frozen_legacy_request("chief", "chat_reply", captured[0])
    assert call.request["system"].encode("utf-8") == expected["system"].encode("utf-8")
    assert call.request["user"].encode("utf-8") == expected["user"].encode("utf-8")
    assert call.request["method"] == "demo_stream" and "preset" not in call.request
    _EVIDENCE[f"preset_legacy_{route}"] = {"head": "e2e9970f98ad9038528739d6937344839f7cfc25", **expected}


@pytest.mark.parametrize("route", ["teardown", "private", "again", "fall_back", "lorekeeper"])
async def test_unchanged_routes_send_identical_bytes_to_real_opening_head_calls(
    client, sessionmaker, monkeypatch, route
):
    """先让冻结 HEAD 的实际 answer/answer_note 写 LlmCall，再与当前实际请求比，而不是只比 helper。"""
    baseline = json.loads(PRESET_BASELINE_PATH.read_text(encoding="utf-8"))
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    if route == "fall_back":

        async def refuse(self, *args, **kwargs):
            raise ToolsUnsupported("演示拒绝工具")
            yield

        monkeypatch.setattr(LLMRouter, "tool_rounds", refuse)

    async def send():
        bid = await seed_book(sessionmaker, source="teardown" if route == "teardown" else "new")
        target = {"to": "chief"} if route == "private" else {"ask": "lorekeeper"} if route == "lorekeeper" else {}
        response = await client.post(f"/api/books/{bid}/notes", json={"content": "这本书的气氛怎么样？", **target})
        assert response.status_code == 201, response.text
        if route == "again":
            history = (await client.get(f"/api/books/{bid}/meeting")).json()
            reply = next(row for row in history if row["payload"].get("reply_to") == [response.json()["id"]])
            response = await client.post(f"/api/books/{bid}/chat/replies/{reply['id']}/again")
            assert response.status_code == 202, response.text
        request = (await calls_for(sessionmaker, bid))[-1].request
        assert "preset" not in request
        return {key: request[key] for key in ("system", "user")}

    with monkeypatch.context() as opening:
        modules = {}
        for name, source in baseline["runtime_sources"].items():
            module_name = f"tests._preset_opening_head_{name}"
            module = types.ModuleType(module_name)
            opening.setitem(sys.modules, module_name, module)
            exec(compile(source, f"{baseline['head']}:{name}.py", "exec"), module.__dict__)
            modules[name] = module

        # chat_prompts 与提示词自身这次不改，仍显式冻结它们，防止将来用当前模板自证。
        def frozen_render(name, **values):
            text = re.sub(r"\{\{(\w+)\}\}", lambda match: str(values[match[1]]).strip(), baseline["prompts"][name])
            return re.sub(r"\n{3,}", "\n\n", text).strip()

        namespace = {"render": frozen_render, "tagged": lambda name, body: f"<{name}>\n{body.strip()}\n</{name}>"}
        source = baseline["chat_prompts_source"].replace("from app.prompts import render, tagged", "")
        exec(compile(source, f"{baseline['head']}:chat_prompts.py", "exec"), namespace)
        for module in modules.values():
            module.render = frozen_render
            module.system_prompt = namespace["system_prompt"]
            module.material_values = namespace["material_values"]
        modules["chat_agent"].answer = modules["chat"].answer
        opening.setattr(chat, "answer", modules["chat"].answer)
        opening.setattr(chat_agent, "answer_note", modules["chat_agent"].answer_note)
        before = await send()
    after = await send()
    assert after["system"].encode("utf-8") == before["system"].encode("utf-8")
    assert after["user"].encode("utf-8") == before["user"].encode("utf-8")
    _EVIDENCE[f"opening_head_actual_{route}"] = {"head": baseline["head"], "before": before, "after": after}


@pytest.mark.parametrize("operation", ["plan_chapters", "draft_pitches"])
async def test_writing_requests_match_frozen_head_except_three_approved_changes(sessionmaker, baseline, operation):
    bid = await seed_book(sessionmaker)
    llm = LLMRouter(sessionmaker, book_id=bid)
    try:
        await getattr(editorial, operation)(llm, baseline["writing"][operation]["blocks"])
    finally:
        await llm.aclose()
    request = (await calls_for(sessionmaker, bid))[-1].request
    original_system = baseline["chief_system"]
    expected = original_system
    for before, after in SYSTEM_CHANGES:
        assert expected.count(before) == 1
        expected = expected.replace(before, after)
    assert request["system"] == expected
    assert request["user"] == baseline["writing"][operation]["user"]
    assert "<口吻>" not in request["system"]
    assert "回答的时候，想着这四件事" not in request["system"]
    _EVIDENCE[operation] = {
        "before_system": original_system,
        "after_system": request["system"],
        "system_diff": "\n".join(
            difflib.unified_diff(
                original_system.splitlines(), request["system"].splitlines(), fromfile="HEAD", tofile="after"
            )
        ),
        "user_unchanged": True,
    }


async def test_voice_override_changes_private_chat_but_not_preset_group_or_writing(
    client, sessionmaker, baseline, monkeypatch
):
    monkeypatch.setattr(demo, "FAKE_TOOLS", True)
    bid = await seed_book(sessionmaker)
    custom = "你是灯塔管理员，称作者为「船长」，自称「守灯人」；说话温和但有主见。"
    first = await client.post(f"/api/books/{bid}/notes", json={"content": "聊聊书的气氛？", "to": "chief"})
    assert first.status_code == 201, first.text
    before = (await calls_for(sessionmaker, bid))[-1].request["system"]
    assert custom not in before
    saved = await client.put("/api/prompts/voice_chief", json={"content": custom})
    assert saved.status_code == 200 and saved.json()["customized"], saved.text
    async with sessionmaker() as session:
        assert (await session.get(PromptOverride, "voice_chief")).content == custom
    second = await client.post(f"/api/books/{bid}/notes", json={"content": "再聊聊气氛？", "to": "chief"})
    assert second.status_code == 201, second.text
    after = (await calls_for(sessionmaker, bid))[-1].request["system"]
    assert tagged("口吻", custom) in after
    assert after != before
    group = await client.post(f"/api/books/{bid}/notes", json={"content": "再聊聊气氛？"})
    assert group.status_code == 201, group.text
    group_request = (await calls_for(sessionmaker, bid))[-1].request
    assert custom not in group_request["system"] and group_request["preset"]["source"] == "system"
    llm = LLMRouter(sessionmaker, book_id=bid)
    try:
        await editorial.plan_chapters(llm, baseline["writing"]["plan_chapters"]["blocks"])
    finally:
        await llm.aclose()
    writing = (await calls_for(sessionmaker, bid))[-1].request
    assert custom not in writing["system"] and "<口吻>" not in writing["system"]
    assert "voice_chief" not in writing["prompt_names"] and "chat_voice" not in writing["prompt_names"]
    _EVIDENCE["voice_override"] = {"saved": custom, "next_chat_has_override": True, "writing_has_override": False}


async def test_plan_user_and_seven_raw_values_are_byte_identical_to_frozen_head(sessionmaker, baseline):
    bid, note_id = await seed_plan_conversation(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        rows = await chat_context.dialogue(session, bid, "chief")
        note = await session.get(MeetingMessage, note_id)
        values = await chat_context.reply_values(session, book, "chief", "chief", rows, [note], PLAN_SUMMARY)
        assert {key: values[key] for key in PLAN_KEYS} == baseline["plan_values"]
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await chat_plans.make_plan_background(bid, "chief", note_id, redis)
    finally:
        await redis.aclose()
    calls = [row for row in await calls_for(sessionmaker, bid) if row.purpose == "总结方案"]
    assert len(calls) == 1
    request = calls[0].request
    assert request["user"].encode("utf-8") == baseline["plan_user"].encode("utf-8")
    assert "chat_material" not in request["prompt_names"] and "chat_voice" not in request["prompt_names"]
    _EVIDENCE["plan"] = {
        "baseline_head": baseline["head"],
        "before_user": baseline["plan_user"],
        "after_user": request["user"],
        "sha256": hashlib.sha256(request["user"].encode("utf-8")).hexdigest(),
        "seven_raw_values_unchanged": True,
    }


async def test_teardown_again_related_stays_inside_one_material_block(sessionmaker):
    bid = await seed_book(sessionmaker, source="teardown")
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        note = MeetingMessage(content="第一章发生了什么？", payload={})
        values = await teardown_chat.values(
            session, book, "chief", note, [], "", tools=False, related="【这一轮工具】\n找到了青灯的原文。"
        )
    user = expected_material("chat_teardown", values)
    matches = re.findall(r"<和这次的话有关的资料>\n(.*?)\n</和这次的话有关的资料>", user, re.S)
    assert len(matches) == 1 and "找到了青灯的原文。" in matches[0]
    assert user.count("找到了青灯的原文。") == 1
