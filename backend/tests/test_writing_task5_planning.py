"""第三包任务 5：补齐不碰骨架、篇保存、提前展开与章纲拍板。"""

import uuid
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.config import get_settings
from app.graphs.write_book import _next_step
from app.llm import demo
from app.main import create_app
from app.models import (
    Book,
    Chapter,
    Character,
    Job,
    MeetingMessage,
    PlotUnit,
    Secret,
    SettingSuggestion,
    SettingVersion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.services import arc_store
from app.services.enrichment import normalize_split
from app.services.job_runner import execute_job
from app.services.segment_planning import normalize_next_segment
from app.services.setup_store import load_nodes


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


@pytest.fixture
async def client():
    app = create_app()
    async with Redis.from_url(get_settings().redis_url) as redis:
        app.state.redis = redis
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def foundation(sessionmaker, *, units=True, skeleton=False):
    async with sessionmaker() as session:
        book = Book(
            title="逆世帝尊",
            idea="测试冲突",
            status="ready",
            concept={"title": "逆世帝尊", "story": "少年追查宗门旧案。", "target_length": 200},
            settings={"trial_read": False, "volume_approval": False, "pitches": 1, "volume_audit": False},
        )
        session.add(book)
        await session.flush()
        node = StoryNode(
            book_id=book.id,
            position=1,
            kind="milestone",
            title="走出宗门",
            event="主角带证据北上。",
            segment={"title": "宗门篇", "text": "已经确认的一段话"}
            if skeleton
            else {"number": 1, "title": "宗门篇", "text": "一段话", "split": True},
        )
        end = StoryNode(book_id=book.id, position=2, kind="ending", title="结局", event="最终的结果。")
        session.add_all(
            [
                node,
                end,
                Character(book_id=book.id, name="林岚", role_type="主角"),
                WorldEntry(book_id=book.id, name="旧日真相", category="往事与秘密", content="这是秘密"),
            ]
        )
        await session.flush()
        volume = Volume(
            book_id=book.id,
            index=1,
            title="作者的卷名",
            summary="作者的卷一段话",
            chapter_count=4,
            locked=True,
            status="approved",
            target_node_id=node.id,
        )
        session.add(volume)
        await session.flush()
        if units:
            session.add_all(
                [
                    PlotUnit(
                        book_id=book.id,
                        volume_id=volume.id,
                        index=i,
                        title=f"作者单元{i}",
                        summary=f"作者单元{i}的一段话",
                        locked=True,
                        chapter_count=2,
                        key_events=[] if skeleton else ["旧事件"],
                    )
                    for i in (1, 2)
                ]
            )
        await session.commit()
        return book.id, volume.id, node.id


async def start_job(sessionmaker, bid, *, until="count", count=1):
    async with sessionmaker() as session:
        job = Job(
            book_id=bid, kind="write_book", thread_id=f"task5-{uuid.uuid4()}", params={"until": until, "count": count}
        )
        session.add(job)
        await session.commit()
        return job.id


async def test_first_write_fills_arc_then_units_preserving_author_skeleton(sessionmaker):
    bid, vid, nid = await foundation(sessionmaker, skeleton=True)
    async with sessionmaker() as session:
        units = list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index)))
        first = units[0]
        chapter = Chapter(
            book_id=bid,
            volume_id=vid,
            unit_id=first.id,
            index=1,
            title="作者已看过的章纲",
            outline={"goal": "保留目标", "hook": "保留钩子"},
        )
        session.add(chapter)
        await session.commit()
        cid = chapter.id
        saved = [(row.id, row.title, row.summary, row.chapter_count, row.locked, row.status) for row in units]
        assert (await _next_step(session, await session.get(Book, bid), {}))["step"] == "fill_segment"
    jid = await start_job(sessionmaker, bid)
    await execute_job(jid)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "succeeded", job.error
        volume = await session.get(Volume, vid)
        assert (volume.title, volume.summary, volume.chapter_count, volume.locked) == (
            "作者的卷名",
            "作者的卷一段话",
            4,
            True,
        )
        node = await session.get(StoryNode, nid)
        assert node.segment == {
            "title": "宗门篇",
            "text": "已经确认的一段话",
            "number": 1,
            "planned_at": 0,
            "split": True,
        }
        for uid, title, summary, count, locked, _ in saved:
            row = await session.get(PlotUnit, uid)
            assert (row.title, row.summary, row.chapter_count, row.locked) == (title, summary, count, locked)
            assert row.key_events
        assert (await session.get(PlotUnit, first.id)).foreshadow_actions == []
        assert (await session.get(Chapter, cid)).outline == {"goal": "保留目标", "hook": "保留钩子"}
        messages = list(
            await session.scalars(
                select(MeetingMessage.content).where(MeetingMessage.job_id == jid).order_by(MeetingMessage.id)
            )
        )
        a = next(i for i, text in enumerate(messages) if "我把第 1 篇的线索" in text)
        b = next(i for i, text in enumerate(messages) if "我把第 1 卷各单元的细节" in text)
        assert a < b
        assert list(await session.scalars(select(Secret).where(Secret.book_id == bid)))


async def test_fill_empty_model_events_does_not_repeat_or_touch_other_units(sessionmaker):
    bid, vid, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        units = list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index)))
        units[1].key_events = []
        untouched = deepcopy(units[0].key_events)
        volume = await session.get(Volume, vid)
        volume.status = "planned"
        await arc_store.fill_units(session, bid, volume, [], [], want="补目标")
        await session.commit()
        assert units[0].key_events == untouched
        assert units[1].key_events == [units[1].summary]
        assert volume.status == "approved"
        assert (await _next_step(session, await session.get(Book, bid), {}))["step"] == "plan_chapters"


async def test_save_arc_ten_steps_locked_suggestions_and_idempotence(client, sessionmaker):
    bid, _, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.concept = {"title": "旧书"}
        future = WorldEntry(book_id=bid, name="天风国", aliases=["北方"], category="世界与地图", status="later")
        locked = WorldEntry(book_id=bid, name="禁地", category="世界与地图", status="later", locked=True)
        levels = WorldEntry(
            book_id=bid,
            name="修行等级",
            category="等级体系",
            style="ladder",
            levels=[{"name": "入门", "text": "原介绍"}],
        )
        session.add_all([future, locked, levels])
        await session.flush()
        nodes = await load_nodes(session, bid)
        plan, _ = normalize_next_segment(
            {
                "title": "天风国篇",
                "text": "新的篇。" * 60,
                "end": {"ref": 2, "title": "新结局名", "event": "结局方向"},
                "fill_entries": [
                    {"name": "北方", "content": "补充国家设定"},
                    {"name": "禁地", "content": "不能自动采用"},
                ],
                "new_entries": [
                    {
                        "name": "修行等级",
                        "category": "等级体系",
                        "levels": [{"name": "入门", "text": "不可覆盖"}, {"name": "登堂", "text": "新增一级"}],
                    },
                    {"name": "青云宗", "category": "势力划分", "content": "新的宗门", "status": "现在要定"},
                    {"name": "集市", "category": "世界与地图", "parent": "大城", "content": "子地方先出现"},
                    {"name": "大城", "category": "世界与地图", "parent": "北方", "content": "上级地方后出现"},
                ],
                "new_characters": [{"name": "苏晴", "role_type": "女主", "status": "现在要定", "one_line": "新的同伴"}],
                "secret": "底牌真相。后半句。",
                "ending_change": "结局调整",
            },
            nodes,
            [{"name": "林岚"}],
        )
        split, _, _ = normalize_split(
            {
                "volumes": [{"index": 2, "title": "新卷", "summary": "新一段话", "chapter_count": 3}],
                "threads": [
                    {
                        "name": "查案",
                        "kind": "主线",
                        "summary": "查案",
                        "characters": ["林岚"],
                        "beats": [{"volume": 2, "beat": "新线索"}],
                    }
                ],
                "anchors": [{"character": "苏晴", "node": 2, "kind": "登场"}],
                "wait": {"description": "找到真相", "plant_volume": 1, "payoff_volume": 99},
                "secrets": [
                    {
                        "title": "旧案",
                        "truth": "真相",
                        "knowers": ["苏晴"],
                        "reader_knows": "不知道",
                        "entry": "旧日真相",
                    }
                ],
            },
            plan,
            [{"name": "林岚"}, {"name": "苏晴"}],
            2,
        )
        stats = await arc_store.save_arc(session, book, plan, split, number=2, pin_end=True)
        await session.commit()
        assert stats["filled_entries"] == 1 and stats["new_entries"] == 4 and stats["new_characters"] == 1
        city = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid, WorldEntry.name == "大城"))
        market = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid, WorldEntry.name == "集市"))
        assert market.parent_id == city.id and city.parent_id == future.id
        assert future.content == "补充国家设定" and future.status == "must"
        assert locked.content == "" and locked.status == "later"
        assert levels.levels == [{"name": "入门", "text": "原介绍"}, {"name": "登堂", "text": "新增一级"}]
        assert (
            await session.scalar(
                select(func.count()).select_from(SettingSuggestion).where(SettingSuggestion.book_id == bid)
            )
            == 1
        )
        secret = await session.scalar(select(Secret).where(Secret.book_id == bid))
        assert secret.knowers[0]["how"] == "定下第 2 篇时"
        entry = await session.scalar(select(WorldEntry).where(WorldEntry.book_id == bid, WorldEntry.name == "旧日真相"))
        assert entry.secret_id == secret.id
        endpoint = await session.get(StoryNode, uuid.UUID(stats["end_id"]))
        assert endpoint.status == "pinned" and endpoint.event == "结局方向"
        assert (await session.get(WorldEntry, uuid.UUID(book.concept["secret_entry_id"]))).locked
        count = await session.scalar(select(func.count()).select_from(SettingVersion))
        again = await arc_store.save_arc(session, book, plan, split, number=2)
        assert (
            again["already_saved"] and await session.scalar(select(func.count()).select_from(SettingVersion)) == count
        )
        suggestion = await session.scalar(select(SettingSuggestion).where(SettingSuggestion.book_id == bid))
        suggestion_id, locked_id = suggestion.id, locked.id
        await session.commit()
    assert (await client.patch(f"/api/world-entries/{locked_id}", json={"locked": False})).status_code == 200
    response = await client.post(f"/api/suggestions/{suggestion_id}/accept")
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, locked_id)).content == "不能自动采用"


async def test_expand_api_and_chapters_review(client, sessionmaker):
    bid, vid, _ = await foundation(sessionmaker, units=False)
    response = await client.post(f"/api/volumes/{vid}/expand")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved" and response.json()["units"]
    assert (await client.post(f"/api/volumes/{vid}/expand")).status_code == 409
    units = response.json()["units"]
    if len(units) > 1:
        response = await client.post(f"/api/units/{units[1]['id']}/expand")
        assert response.status_code == 409 and response.json()["detail"] == "先展开前面的单元"
    response = await client.post(f"/api/units/{units[0]['id']}/expand")
    assert response.status_code == 200, response.text
    assert (await client.post(f"/api/units/{units[0]['id']}/expand")).status_code == 409


async def test_chapters_gate_revise_then_approve(sessionmaker):
    bid, _, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.settings = {**book.settings, "chapters_approval": True}
        await session.commit()
    jid = await start_job(sessionmaker, bid)
    await execute_job(jid)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "waiting_author", job.error
        assert job.pending["kind"] == "chapters_review"
        assert set(job.pending) == {"kind", "volume", "unit_id", "unit_title", "first", "last"}
        ids = set(await session.scalars(select(Chapter.id).where(Chapter.book_id == bid)))
    await execute_job(jid, {"action": "revise", "feedback": "章尾悬念更强"})
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "waiting_author" and job.pending["kind"] == "chapters_review", job.error
        assert not ids.intersection(set(await session.scalars(select(Chapter.id).where(Chapter.book_id == bid))))
    await execute_job(jid, {"action": "approve"})
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "succeeded", job.error
        assert (
            await session.scalar(
                select(func.count()).select_from(Chapter).where(Chapter.book_id == bid, Chapter.status == "final")
            )
            == 1
        )


async def test_expand_busy_and_model_failure_release_reservation(client, sessionmaker, monkeypatch):
    from app.api import outline_expand

    bid, vid, _ = await foundation(sessionmaker, units=False)
    jid = await start_job(sessionmaker, bid)
    response = await client.post(f"/api/volumes/{vid}/expand")
    assert response.status_code == 409 and response.json()["detail"] == "编辑部正在工作，等这一步做完再展开"
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        job.status = "succeeded"
        await session.commit()

    async def fail(*args, **kwargs):
        raise ValueError("演示异常")

    monkeypatch.setattr(outline_expand.editorial, "plan_volume", fail)
    response = await client.post(f"/api/volumes/{vid}/expand")
    assert response.status_code == 502 and response.json()["detail"] == "模型出错了：演示异常"
    async with sessionmaker() as session:
        reserved = await session.scalar(select(Job).where(Job.book_id == bid, Job.kind == "outline_expand"))
        assert reserved.status == "failed"
        assert not list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == vid)))
        failed_id = reserved.id
    response = await client.post(f"/api/jobs/{failed_id}/resume")
    assert response.status_code == 409 and "展开这一个" in response.text


async def test_fill_arc_short_response_preserves_unmatched_volume_details(sessionmaker):
    bid, vid, nid = await foundation(sessionmaker, skeleton=True)
    async with sessionmaker() as session:
        second = Volume(
            book_id=bid,
            index=2,
            title="原卷名",
            summary="原一段话",
            chapter_count=5,
            target_node_id=nid,
            stage="原舞台",
            goal="原目标",
            pressure="原压力",
            locked=True,
        )
        session.add(second)
        await session.flush()
        await arc_store.fill_arc(
            session,
            await session.get(Book, bid),
            nid,
            {"volumes": [{"stage": "补齐舞台"}, {"stage": "", "goal": "", "pressure": ""}]},
            await load_nodes(session, bid),
            matching_count=1,
        )
        await session.commit()
        assert (await session.get(Volume, vid)).stage == "补齐舞台"
        assert (
            second.title,
            second.summary,
            second.chapter_count,
            second.stage,
            second.goal,
            second.pressure,
            second.locked,
        ) == ("原卷名", "原一段话", 5, "原舞台", "原目标", "原压力", True)
        assert second.reaches_node


async def test_revise_chapters_is_safe_to_repeat_and_keeps_original_until_generation_succeeds(sessionmaker):
    from app.graphs.write_book import revise_chapters_node

    bid, vid, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index))
        uid = unit.id
        session.add(Chapter(book_id=bid, volume_id=vid, unit_id=uid, index=1, title="旧章纲"))
        await session.commit()
    state = {"unit_id": str(uid), "chapters_revision": "旧章纲全文与作者意见"}
    runtime = SimpleNamespace(context=SimpleNamespace(sessionmaker=sessionmaker))
    await revise_chapters_node(state, runtime)
    await revise_chapters_node(state, runtime)
    assert state["chapters_revision"] == "旧章纲全文与作者意见"
    async with sessionmaker() as session:
        assert len(list(await session.scalars(select(Chapter).where(Chapter.unit_id == uid)))) == 1
        assert (await session.get(PlotUnit, uid)).status == "planned"


@pytest.mark.parametrize("target", ["volume", "unit"])
async def test_expand_version_failure_rolls_back_all_saved_content(client, sessionmaker, monkeypatch, target):
    from app.api import outline_expand

    bid, vid, _ = await foundation(sessionmaker, units=target == "unit")
    async with sessionmaker() as session:
        uid = await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index))
        (await session.get(Volume, vid)).status = "planned"
        await session.commit()

    async def fail(*args, **kwargs):
        raise ValueError("版本保存中断")

    monkeypatch.setattr(outline_expand, "record_version", fail)
    response = await client.post(
        f"/api/{'volumes' if target == 'volume' else 'units'}/{vid if target == 'volume' else uid}/expand"
    )
    assert response.status_code == 502 and "版本保存中断" in response.text
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(Job).where(Job.book_id == bid, Job.kind == "outline_expand"))
        ).status == "failed"
        if target == "volume":
            assert not list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == vid)))
            assert (await session.get(Volume, vid)).status == "planned"
        else:
            assert not list(await session.scalars(select(Chapter).where(Chapter.unit_id == uid)))
            assert (await session.get(PlotUnit, uid)).status == "planned"
        assert not list(await session.scalars(select(SettingVersion).where(SettingVersion.book_id == bid)))


async def test_expand_redis_notification_failure_keeps_committed_result(client, sessionmaker, monkeypatch):
    from redis.exceptions import RedisError

    from app.api import outline_expand

    bid, vid, _ = await foundation(sessionmaker, units=False)

    async def fail(*args, **kwargs):
        raise RedisError("通知暂时不可用")

    monkeypatch.setattr(outline_expand, "publish", fail)
    response = await client.post(f"/api/volumes/{vid}/expand")
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        assert (
            await session.scalar(select(Job).where(Job.book_id == bid, Job.kind == "outline_expand"))
        ).status == "succeeded"
        assert list(await session.scalars(select(PlotUnit).where(PlotUnit.volume_id == vid)))


async def test_new_arc_library_merge_obeys_source_alias_and_position(sessionmaker):
    bid, _, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        original = [
            WorldEntry(
                book_id=bid, name=name, category="势力划分", source=source, locked=locked, position=i, content="原文"
            )
            for i, (name, source, locked) in enumerate(
                [
                    ("旧AI", "ai", False),
                    ("旧迁移", "migration", False),
                    ("作者改过", "author", False),
                    ("锁住", "ai", True),
                ],
                1,
            )
        ]
        session.add_all(original)
        await session.flush()
        raw = {
            "title": "下一篇",
            "text": "一段话",
            "end": {"ref": 2, "title": "结局", "event": "结果"},
            "new_entries": [{"name": row.name, "category": "势力划分", "content": "更新"} for row in original]
            + [
                {"name": name, "category": category, "content": "新增"}
                for name, category in [
                    ("乙地", "世界与地图"),
                    ("世界概况", "世界与地图"),
                    ("甲地", "世界与地图"),
                    ("新势力一", "势力划分"),
                    ("新势力二", "势力划分"),
                ]
            ],
            "new_characters": [
                {"name": "化名", "aliases": ["林岚"]},
                {"name": "新角色", "aliases": ["新外号"]},
                {"name": "第二化名", "aliases": ["新外号"]},
            ],
        }
        plan, _ = normalize_next_segment(raw, await load_nodes(session, bid), [{"name": "林岚"}])
        assert [row["name"] for row in plan["new_characters"]] == ["新角色"]
        stats = await arc_store.save_arc(
            session, book, plan, {"volumes": [{"index": 2, "title": "新卷", "chapter_count": 3}]}, number=2
        )
        await session.commit()
        assert [row.content for row in original] == ["更新", "更新", "原文", "原文"]
        entries = {row.name: row for row in await session.scalars(select(WorldEntry).where(WorldEntry.book_id == bid))}
        assert entries["世界概况"].position == 0 < entries["乙地"].position < entries["甲地"].position
        assert entries["新势力一"].position == 5 and entries["新势力二"].position == 6
        assert stats["new_entries"] == 5 and stats["new_characters"] == 1


@pytest.mark.parametrize("actual", [0, 1, 3])
async def test_expand_wrong_chapter_count_retries_once_without_changing_skeleton(
    client, sessionmaker, monkeypatch, actual
):
    from app.agents import editorial

    bid, vid, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        uid = await session.scalar(select(PlotUnit.id).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index))
    calls = []

    async def wrong_count(llm, blocks):
        calls.append(deepcopy(blocks))
        result = demo._chapter_plan(f"这个单元共 {max(actual, 1)} 章")
        if not actual:
            result.chapters = []
        return result

    monkeypatch.setattr(editorial, "plan_chapters", wrong_count)
    response = await client.post(f"/api/units/{uid}/expand")
    assert response.status_code == 502 and "章纲数量不符" in response.text
    assert len(calls) == 2 and calls[0]["chapter_count"] == "2"
    assert "必须照作者已定的章数重出" in calls[1]["revision"]
    async with sessionmaker() as session:
        unit = await session.get(PlotUnit, uid)
        assert (unit.title, unit.summary, unit.chapter_count, unit.locked) == (
            "作者单元1",
            "作者单元1的一段话",
            2,
            True,
        )
        assert not list(await session.scalars(select(Chapter).where(Chapter.unit_id == uid)))


async def test_wrong_count_during_chapters_revision_keeps_original_ids_and_outline(sessionmaker, monkeypatch):
    from app.agents import editorial

    bid, _, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        book = await session.get(Book, bid)
        book.settings = {**book.settings, "chapters_approval": True}
        await session.commit()
    jid = await start_job(sessionmaker, bid)
    await execute_job(jid)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "waiting_author", job.error
        uid = uuid.UUID(job.pending["unit_id"])
        original = [
            (row.id, row.title, row.outline)
            for row in await session.scalars(select(Chapter).where(Chapter.unit_id == uid).order_by(Chapter.index))
        ]
    calls = []

    async def wrong_count(llm, blocks):
        calls.append(deepcopy(blocks))
        return demo._chapter_plan("这个单元共 1 章")

    monkeypatch.setattr(editorial, "plan_chapters", wrong_count)
    await execute_job(jid, {"action": "revise", "feedback": "保留章数加强悬念"})
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "failed" and "章纲数量不符" in job.error
        assert [
            (row.id, row.title, row.outline)
            for row in await session.scalars(select(Chapter).where(Chapter.unit_id == uid).order_by(Chapter.index))
        ] == original
        assert (await session.get(PlotUnit, uid)).chapter_count == 2
    assert len(calls) == 2 and "保留章数加强悬念" in calls[0]["revision"]


async def test_chapter_generation_only_fills_missing_tail_and_keeps_author_count(sessionmaker, monkeypatch):
    from app.agents import editorial

    bid, vid, _ = await foundation(sessionmaker)
    async with sessionmaker() as session:
        unit = await session.scalar(select(PlotUnit).where(PlotUnit.volume_id == vid).order_by(PlotUnit.index))
        uid = unit.id
        unit.chapter_count = 3
        book = await session.get(Book, bid)
        book.settings = {**book.settings, "chapters_approval": True}
        chapter = Chapter(
            book_id=bid, volume_id=vid, unit_id=uid, index=1, title="原定稿", content="作者原正文", status="final"
        )
        session.add(chapter)
        await session.commit()
        cid = chapter.id
    calls = []

    async def generated(llm, blocks):
        calls.append(deepcopy(blocks))
        return demo._chapter_plan(f"这个单元共 {1 if len(calls) == 1 else 2} 章")

    monkeypatch.setattr(editorial, "plan_chapters", generated)
    jid = await start_job(sessionmaker, bid)
    await execute_job(jid)
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "waiting_author", job.error
        assert (job.pending["first"], job.pending["last"]) == (2, 3)
        assert (await session.get(PlotUnit, uid)).chapter_count == 3
        assert (await session.get(Chapter, cid)).content == "作者原正文"
        assert list(
            await session.scalars(select(Chapter.index).where(Chapter.unit_id == uid).order_by(Chapter.index))
        ) == [1, 2, 3]
    assert len(calls) == 2 and all(
        blocks["chapter_count"] == "2" and blocks["first_chapter"] == "2" for blocks in calls
    )
    await execute_job(jid, {"action": "revise", "feedback": "只改新出的章纲"})
    async with sessionmaker() as session:
        job = await session.get(Job, jid)
        assert job.status == "waiting_author", job.error
        assert (job.pending["first"], job.pending["last"]) == (2, 3)
        assert (await session.get(Chapter, cid)).content == "作者原正文"
        assert (await session.get(PlotUnit, uid)).chapter_count == 3
        assert list(
            await session.scalars(select(Chapter.index).where(Chapter.unit_id == uid).order_by(Chapter.index))
        ) == [1, 2, 3]
    assert calls[-1]["chapter_count"] == "2" and calls[-1]["first_chapter"] == "2"
