import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import schemas as s
from app.graphs import write_book as graph
from app.llm import demo
from app.models import Book, Chapter, Foreshadowing, PlotUnit, Secret, StoryNode, Volume


class Emitter:
    def __init__(self):
        self.events = []

    async def say(self, *args, **kwargs):
        self.events.append(("say", args, kwargs))

    async def status(self, *args, **kwargs):
        self.events.append(("status", args, kwargs))

    async def artifact(self, *args, **kwargs):
        self.events.append(("artifact", args, kwargs))


async def context(sessionmaker, *, approval=True, status="pencil"):
    async with sessionmaker() as session:
        book = Book(title="任务四", concept={"title": "任务四"}, settings={"volume_approval": approval})
        session.add(book)
        await session.flush()
        node = StoryNode(
            book_id=book.id,
            position=1,
            kind="milestone",
            title="旧节点",
            event="旧事件",
            prerequisite="旧前提",
            consequence="旧后果",
            volume=1,
            status=status,
        )
        session.add(node)
        await session.flush()
        volume = Volume(
            book_id=book.id, index=1, title="测试卷", chapter_count=6, target_node_id=node.id, status="approved"
        )
        session.add(volume)
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="测试单元", chapter_count=6)
        session.add(unit)
        await session.commit()

    async def check_cancel():
        pass

    emit = Emitter()
    runtime = SimpleNamespace(
        context=SimpleNamespace(
            sessionmaker=sessionmaker, book_id=book.id, llm=None, emit=emit, check_cancel=check_cancel
        )
    )
    state = {"volume_id": str(volume.id), "volume_index": 1, "volume_title": volume.title, "unit_id": str(unit.id)}
    return runtime, state, node


def plan(node):
    return {
        "units": [{"index": 1, "title": "按卷推进", "chapter_count": 6}],
        "_target_snapshot": {
            "node_id": str(node.id),
            "index": 1,
            "current": {key: getattr(node, key) for key in graph.NODE_CONTENT},
        },
        "node_update": {
            "title": "新节点",
            "event": "新事件",
            "prerequisite": "新前提",
            "consequence": "新后果",
            "reason": "沿前文调整",
        },
    }


@pytest.mark.parametrize("automatic", [False, True])
async def test_pencil_proposal_pending_then_approve(sessionmaker, monkeypatch, automatic):
    runtime, state, node = await context(sessionmaker, approval=not automatic)
    saved = await graph.save_volume_node({**state, "volume_draft": plan(node)}, runtime)
    assert saved["node_update"]["node_id"] == str(node.id)
    assert any("节点调整" in issue for issue in saved["open_issues"])
    pending = []

    def approve(value):
        pending.append(value)
        return {"action": "approve"}

    monkeypatch.setattr(graph, "interrupt", approve)
    command = await graph.volume_gate_node({**state, **saved}, runtime)
    assert command.update["node_update"] is None
    if not automatic:
        assert pending[0]["node_update"] == saved["node_update"]
    async with sessionmaker() as session:
        current = await session.get(StoryNode, node.id)
        assert (current.title, current.status, current.origin, current.updated_by_volume) == (
            "新节点",
            "pencil",
            "ai",
            1,
        )
    assert any(
        "按这一卷的写法调整了" in event[1][1] and event[1][0] == ("system" if automatic else "chief")
        for event in runtime.context.emit.events
        if event[0] == "say"
    )


async def test_pinned_proposal_ignored_and_conflict_disclosed(sessionmaker):
    runtime, state, node = await context(sessionmaker, status="pinned")
    draft = {**plan(node), "node_conflict": "前文和节点的前提不符"}
    result = await graph.save_volume_node({**state, "volume_draft": draft}, runtime)
    assert result["node_update"] is None
    assert any(
        "节点冲突：前文和节点的前提不符（主编提议调整锁住节点，已忽略）" in issue for issue in result["open_issues"]
    )
    async with sessionmaker() as session:
        assert (await session.get(StoryNode, node.id)).title == "旧节点"


@pytest.mark.parametrize("change", ["edit", "pin", "retarget"])
async def test_approval_never_overwrites_author_changes(sessionmaker, monkeypatch, change):
    runtime, state, node = await context(sessionmaker)
    result = await graph.save_volume_node({**state, "volume_draft": plan(node)}, runtime)
    async with sessionmaker() as session:
        current = await session.get(StoryNode, node.id)
        if change == "edit":
            current.event = "作者亲自修改"
        elif change == "pin":
            current.status = "pinned"
        else:
            (await session.get(Volume, uuid.UUID(state["volume_id"]))).target_node_id = None
        await session.commit()
    monkeypatch.setattr(graph, "interrupt", lambda _: {"action": "approve"})
    await graph.volume_gate_node({**state, **result}, runtime)
    async with sessionmaker() as session:
        current = await session.get(StoryNode, node.id)
        assert current.title == "旧节点" and current.updated_by_volume is None
    assert any("已保留作者当前的版本" in event[1][1] for event in runtime.context.emit.events if event[0] == "say")


async def test_feedback_discards_proposal_and_legacy_checkpoint_remains_usable(sessionmaker, monkeypatch):
    runtime, state, node = await context(sessionmaker)
    result = await graph.save_volume_node({**state, "volume_draft": plan(node)}, runtime)
    monkeypatch.setattr(graph, "interrupt", lambda _: {"action": "revise", "feedback": "节奏快一点"})
    command = await graph.volume_gate_node({**state, **result}, runtime)
    assert command.goto == "revise_volume" and command.update["node_update"] is None
    # 旧检查点没有 node_update，不应要求这个新字段。
    monkeypatch.setattr(graph, "interrupt", lambda _: {"action": "approve"})
    await graph.volume_gate_node(state, runtime)
    async with sessionmaker() as session:
        assert (await session.get(StoryNode, node.id)).title == "旧节点"


async def test_stale_generation_snapshot_is_ignored(sessionmaker):
    runtime, state, node = await context(sessionmaker)
    draft = plan(node)
    async with sessionmaker() as session:
        (await session.get(StoryNode, node.id)).title = "作者新名字"
        await session.commit()
    result = await graph.save_volume_node({**state, "volume_draft": draft}, runtime)
    assert result["node_update"] is None and any("目标节点已变化" in issue for issue in result["open_issues"])


@pytest.mark.parametrize("fixed", [False, True])
async def test_chapter_plan_retries_once_and_persists_remaining_issues(sessionmaker, monkeypatch, fixed):
    runtime, state, _ = await context(sessionmaker)
    calls = []

    async def generate(llm, blocks):
        calls.append(dict(blocks))
        title = "正常推进" if fixed and len(calls) > 1 else "测试节奏"
        result = demo._chapter_plan(f"这个单元共 6 章\n【本单元】\n单元1「{title}」")
        if not fixed:
            result.chapters[0].foreshadow_actions = [s.ForeshadowStep(ref="F999", action="提醒")]
            result.chapters[0].reveals = [s.RevealStep(ref="S999", to="读者", how="错误编号")]
        return result

    monkeypatch.setattr(graph.editorial, "plan_chapters", generate)
    await graph.plan_chapters_node(state, runtime)
    assert len(calls) == 2 and calls[0]["revision"] == ""
    assert "【当前章纲】" in calls[1]["revision"] and "章连续 6 章压抑" in calls[1]["revision"]
    async with sessionmaker() as session:
        unit = await session.get(PlotUnit, uuid.UUID(state["unit_id"]))
        assert bool(unit.plan_issues) is not fixed
        chapters = list(
            await session.scalars(
                select(Chapter).where(Chapter.book_id == runtime.context.book_id).order_by(Chapter.index)
            )
        )
        assert len(chapters) == 6 and all("emotion" in chapter.outline for chapter in chapters)
        assert chapters[0].outline["foreshadow_actions"] == [] and chapters[0].outline["reveals"] == []
    # 中断恢复不重复调用模型、不重复建章。
    await graph.plan_chapters_node(state, runtime)
    assert len(calls) == 2


async def test_audit_hints_are_not_automatic_revision_but_missing_expectation_is(sessionmaker, monkeypatch):
    runtime, state, node = await context(sessionmaker)
    found = []

    async def audit(llm, blocks, plan, issues, **kwargs):
        found.append(issues)
        assert "旧节点" in blocks["target_node"]
        return s.VolumeAudit(
            verdict="pass",
            checks=[s.AuditCheck(aspect=aspect, ok=True, comment="通过") for aspect in graph.ASPECT_NAMES],
            remark="审过了",
        )

    monkeypatch.setattr(graph.editorial, "audit_volume", audit)
    draft = plan(node)
    hints = await graph.audit_volume_node({**state, "volume_draft": draft}, runtime)
    assert hints["volume_fix"] == "" and found[-1] and all(line.startswith("提示：") for line in found[-1])
    async with sessionmaker() as session:
        session.add(
            Foreshadowing(
                book_id=runtime.context.book_id,
                seq=1,
                kind="期待",
                span="中",
                description="三年之约",
                plant_volume=1,
                payoff_volume=1,
            )
        )
        await session.commit()
    issues = await graph.audit_volume_node({**state, "volume_draft": draft}, runtime)
    assert issues["volume_fix"] and any(line.startswith("问题：") and "E1" in line for line in found[-1])


async def test_valid_references_accept_only_matching_ledger_kind(sessionmaker):
    runtime, _, _ = await context(sessionmaker)
    async with sessionmaker() as session:
        session.add_all(
            [
                Foreshadowing(book_id=runtime.context.book_id, seq=2, kind="期待", description="约定"),
                Secret(book_id=runtime.context.book_id, seq=3, title="身份"),
            ]
        )
        await session.commit()
    plans = [
        {
            "emotion": 2,
            "mood": "爽",
            "foreshadow_actions": [{"ref": "F2", "action": "提醒"}, {"ref": "e2", "action": "提醒"}],
            "reveals": [{"ref": "s3"}, {"ref": "S4"}],
        }
    ]
    issues = graph._chapter_plan_issues(plans, 1, "general", [], [{"seq": 2, "kind": "期待"}], [{"seq": 3}])
    assert len(issues) == 2
    assert plans[0]["foreshadow_actions"] == [{"ref": "E2", "action": "提醒"}]
    assert plans[0]["reveals"] == [{"ref": "S3"}]


def test_demo_reveal_digest_and_node_trigger():
    plan = demo._chapter_plan("这个单元共 6 章\n【本单元】\n单元1「揭晓身份」\n揭晓：S1 揭给 苏晚晴——当面展示证据")
    outline = graph.format_chapter_outline(plan.chapters[-2].model_dump())
    content = demo._chapter_text(f"请写第 5 章《揭晓》\n字数约 3000 字\n【本章章纲】\n{outline}")
    digest = demo._digest(f"第 5 章《揭晓》已经定稿\n【正文】\n{content}")
    assert digest.secret_updates[0].ref == "S1" and digest.secret_updates[0].learned_by == ["苏晚晴"]
    assert demo._volume_plan("测试节点调整").node_update is not None
    assert len(demo._audit().checks) == 5


def test_demo_schedules_each_due_expectation_instead_of_only_reminding_first():
    plan = demo._volume_plan(
        "请为第 2 卷写「卷纲」\n【伏笔与期待台账】\n"
        "- E6［期待·长·已立·第1卷立、第2卷兑现］三年之约\n"
        "- E8［期待·中·未立·第2卷立、第2卷兑现］本卷约定\n"
        "- E9［期待·长·已立·第1卷立、第4卷兑现］跨卷目标\n"
        "- E10［期待·中·已兑现·第1卷立、第1卷兑现］已结束\n"
    )
    first = {(step.ref, step.action) for step in plan.units[0].foreshadow_actions}
    last = {(step.ref, step.action) for step in plan.units[-1].foreshadow_actions}
    assert ("E8", "埋下") in first
    assert {("E6", "回收"), ("E8", "回收"), ("E9", "提醒")} <= last
    assert not any(step.ref == "E10" for unit in plan.units for step in unit.foreshadow_actions)
