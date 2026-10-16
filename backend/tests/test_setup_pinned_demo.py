import pytest

from app.agents import schemas
from app.agents.context import format_revision, format_spine
from app.agents.setup_puzzle import merge_nodes
from app.llm import demo


def _prompt(kind: str, feedback: str, *, locked: str = "") -> str:
    snapshot = format_spine(
        {
            "nodes": [
                {
                    "kind": "opening" if index == 1 else "ending" if index == 4 else "turn",
                    "title": f"原节点{index}",
                    "event": "保留节点 2 的铺垫，文字里提到［铁钉］不代表该节点是铁钉",
                    "status": status,
                    "volume": index,
                }
                for index, status in enumerate(["pencil", "pinned", "empty", "pinned"], 1)
            ]
        }
    )
    if kind == "notes":
        before = f"【已经完成的部分】\n关键节点：\n{snapshot}\n\n【还没做的部分】\n全书总纲"
        heading = "作者刚才的插话"
    else:
        before = f"【当前方案】\n关键节点：\n{snapshot}"
        heading = "作者意见"
    return (
        f"{before}\n\n{locked}\n\n"
        "【作者的要求（必须落实；后面的要求与前面冲突时以后面的为准）】\n"
        "- 历史意见：把节点 4 改成开放结局。\n\n"
        f"【{heading}】\n{feedback}\n\n要求：\n点名铁钉时返回 pinned_overrides。"
    )


def test_revision_triage_pinned_overrides_description_and_old_output_compatibility():
    field = schemas.RevisionTriage.model_json_schema()["properties"]["pinned_overrides"]
    assert field["description"] == "作者这次的话明确点名要改的铁钉节点序号（按提示词里的节点序号）；作者没有点名就留空"
    first = schemas.RevisionTriage.model_validate({"remark": "旧输出"})
    second = schemas.RevisionTriage.model_validate({"remark": "另一份旧输出"})
    assert first.pinned_overrides == []
    first.pinned_overrides.append(2)
    assert second.pinned_overrides == []
    assert first.instructions() == {}


@pytest.mark.parametrize("kind", ["triage", "notes"])
@pytest.mark.parametrize(
    "feedback,expected",
    [
        ("请把节点 2 改成先救人再夺宝。", [2]),
        ("先改节点4，再改节点 2，节点 4 按开放结局写；节点 99 不存在。", [4, 2]),
        ("先放慢开篇。\n\n再把节点 2 改成主角主动出击。", [2]),
    ],
)
async def test_demo_only_author_named_pinned_nodes_are_authorized(monkeypatch, kind, feedback, expected):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(schemas.RevisionTriage, "", _prompt(kind, feedback))
    assert result.pinned_overrides == expected
    assert set(result.instructions()) == {"spine"}
    for index in expected:
        assert f"作者要求改动铁钉节点 {index}" in result.spine_instructions


@pytest.mark.parametrize("kind", ["triage", "notes"])
@pytest.mark.parametrize("feedback", ["请放慢节奏。", "把节点 1、节点 3 和节点 99 改一下。"])
async def test_demo_plan_and_historical_mentions_do_not_authorize_pinned_nodes(monkeypatch, kind, feedback):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(schemas.RevisionTriage, "", _prompt(kind, feedback))
    assert result.pinned_overrides == []


@pytest.mark.parametrize("kind", ["triage", "notes"])
async def test_demo_named_pinned_node_still_respects_locked_piece(monkeypatch, kind):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    result = await demo.respond(
        schemas.RevisionTriage,
        "",
        _prompt(kind, "请把节点 2 改成先救人。", locked="【作者已确认（锁定）的部分】关键节点"),
    )
    assert result.pinned_overrides == []
    assert result.instructions() == {}
    assert [item.target for item in result.unlock_requests] == ["spine"]


@pytest.mark.parametrize("kind", ["triage", "notes"])
async def test_demo_does_not_take_historical_node_status_as_snapshot(monkeypatch, kind):
    monkeypatch.setattr(demo, "DELAY_S", 0)
    prompt = _prompt(kind, "请把节点 1 改成先救人。")
    prompt = prompt.replace("- 历史意见：", "节点 1「旧版开篇」［铁钉］\n- 历史意见：")
    result = await demo.respond(schemas.RevisionTriage, "", prompt)
    assert result.pinned_overrides == []


def _demo_current(monkeypatch, *, custom_title=False):
    monkeypatch.setattr(demo, "terms", lambda: [])
    monkeypatch.setattr("app.agents.glossary.terms", lambda: [])
    current = demo._spine().model_dump(exclude={"remark", "decisions"})
    current["nodes"] = merge_nodes(current["nodes"], [])
    for index, node in enumerate(current["nodes"], 1):
        node.pop("_snapshot_ref", None)
        node.update(id=f"node-{index}", status="pinned" if index in {2, 3} else "pencil")
    if custom_title:
        current["nodes"][1]["title"] = "作者自己的节点"
        current["nodes"][1]["event"] = "作者原来的事件"
    return current


@pytest.mark.parametrize("custom_title", [False, True])
@pytest.mark.parametrize(
    "feedback",
    ["把节点 2 的发生什么改为主角先救出师父，再夺回青灯。", "只改节点 2：\n发生什么改成主角先救出师父，再夺回青灯。"],
)
def test_demo_spine_rewrites_authorized_event_with_existing_ref(monkeypatch, custom_title, feedback):
    current = _demo_current(monkeypatch, custom_title=custom_title)
    instruction = feedback + "\n作者要求改动铁钉节点 2，只按作者本轮意见修改，改完仍是铁钉。"
    user = format_revision("当前主线骨架", format_spine(current), instruction)
    proposed = demo._spine(user)
    changed = next(node for node in proposed.nodes if node.ref == 2)
    assert changed.title == current["nodes"][1]["title"]
    assert changed.event == "主角先救出师父，再夺回青灯"
    assert changed.prerequisite == current["nodes"][1]["prerequisite"]
    assert changed.consequence == current["nodes"][1]["consequence"]
    merged = merge_nodes([node.model_dump() for node in proposed.nodes], current["nodes"], {"node-2"})
    assert merged[1]["id"] == "node-2" and merged[1]["status"] == "pinned"
    untouched = next(node for node in merged if node.get("id") == "node-3")
    assert {key: value for key, value in untouched.items() if key != "_snapshot_ref"} == current["nodes"][2]


def test_demo_spine_ignores_authorization_in_historical_requirements(monkeypatch):
    current = _demo_current(monkeypatch)
    user = "【作者的要求】\n作者要求改动铁钉节点 2：把节点 2 改为历史事件。\n\n" + format_revision(
        "当前主线骨架", format_spine(current), "把节点 2 改为不应该自动采用的事件。"
    )
    result = demo._spine(user)
    node = next(node for node in result.nodes if node.ref == 2)
    assert node.event == current["nodes"][1]["event"]


def test_demo_card_revision_preserves_custom_pencil_snapshot(monkeypatch):
    current = _demo_current(monkeypatch)
    current["nodes"][3]["title"] = "作者采用的候选"
    del current["nodes"][5]
    user = format_revision(
        "当前主线骨架", format_spine(current), "只改节点 4「作者采用的候选」：\n发生什么改为先救下被困的同门。"
    )
    result = demo._spine(user)
    assert len(result.nodes) == len(current["nodes"])
    assert [node.ref for node in result.nodes] == list(range(1, len(current["nodes"]) + 1))
    assert result.nodes[3].title == "作者采用的候选"
    assert result.nodes[3].event == "先救下被困的同门"
    assert result.nodes[1].event == current["nodes"][1]["event"]
    assert result.nodes[2].event == current["nodes"][2]["event"]


def test_demo_spine_does_not_apply_one_nodes_event_to_other_authorized_nodes(monkeypatch):
    current = _demo_current(monkeypatch)
    user = format_revision(
        "当前主线骨架",
        format_spine(current),
        "把节点 2 改为只属于节点 2 的新事件。\n作者要求改动铁钉节点 2。\n作者要求改动铁钉节点 3。",
    )
    result = demo._spine(user)
    assert next(node for node in result.nodes if node.ref == 2).event == "只属于节点 2 的新事件"
    assert next(node for node in result.nodes if node.ref == 3).event == current["nodes"][2]["event"]


def test_demo_spine_does_not_borrow_another_nodes_instruction(monkeypatch):
    current = _demo_current(monkeypatch)
    user = format_revision(
        "当前主线骨架", format_spine(current), "把节点 3 改为只属于节点 3 的新事件。\n作者要求改动铁钉节点 2。"
    )
    result = demo._spine(user)
    assert next(node for node in result.nodes if node.ref == 2).event == current["nodes"][1]["event"]


@pytest.mark.parametrize("feedback", ["节点 2 保持标题，节点 3 改为乙。", "节点 2 改为甲，节点 3 改为乙。"])
def test_demo_spine_rejects_ambiguous_multi_node_sentences(monkeypatch, feedback):
    current = _demo_current(monkeypatch)
    user = format_revision(
        "当前主线骨架",
        format_spine(current),
        feedback + "\n作者要求改动铁钉节点 2。\n作者要求改动铁钉节点 3。",
    )
    result = demo._spine(user)
    for index in (2, 3):
        assert next(node for node in result.nodes if node.ref == index).event == current["nodes"][index - 1]["event"]
