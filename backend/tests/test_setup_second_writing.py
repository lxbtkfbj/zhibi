"""卷纲新问题与任务 4 接入前的段边界保护，兼容没有分段信息的旧书。"""

import pytest

from app.graphs.write_book import _next_step
from app.models import Book, Character, StoryNode, Volume
from app.prompts import render
from app.services.writing_context import volume_blocks
from app.services.writing_store import save_volume_plan


async def fixture(session, *, segmented=True, end=False):
    book = Book(
        title="卷纲上下文",
        status="writing",
        concept={"title": "卷纲上下文", "core_loop": "接委托查案找妹妹", "protagonist_hook": "旧书主角钩子"},
        protagonist={"name": "林岚", "pursuit": "找回妹妹"} if segmented else {},
        world={"maps": [{"name": "旧城区", "rules": "日落后封门"}]} if segmented else {},
    )
    session.add(book)
    await session.flush()
    target = StoryNode(
        book_id=book.id,
        position=2,
        kind="ending" if end else "milestone",
        title="找到线人",
        segment={
            "number": 1,
            "planned_at": 0,
            "goal": "救出线人",
            "map": "旧城区",
            "opening": {"scene": "城门突然落锁", "pressure": "追兵将至"},
        }
        if segmented
        else None,
    )
    session.add(target)
    await session.flush()
    volume = Volume(
        book_id=book.id,
        index=1,
        title="入城",
        want="找到妹妹的下落",
        pressure="身无分文",
        target_node_id=target.id,
        status="done",
        recap="这一卷已经写完",
    )
    protagonist = Character(book_id=book.id, name="林岚", role_type="主角", want="天黑前找到线人", goal="找妹妹")
    session.add_all([volume, protagonist])
    await session.flush()
    return book, volume, target


@pytest.mark.parametrize("segmented", [True, False])
async def test_volume_prompt_all_variables_render_for_new_and_old_books(sessionmaker, segmented):
    async with sessionmaker() as session:
        book, volume, _ = await fixture(session, segmented=segmented)
        blocks = await volume_blocks(session, book, volume)
        rendered = render("plan_volume", **blocks, direction="", revision="")
        assert rendered and "天黑前找到线人" in blocks["protagonist"]
        if segmented:
            assert "救出线人" in blocks["segment"] and "城门突然落锁" in blocks["opening"]
            assert "下一卷：无（后面的卷写到再定）" in blocks["neighbors"]
            assert "最后一卷" not in blocks["neighbors"]
            volume.index = 2
            assert (await volume_blocks(session, book, volume))["opening"] == ""
        else:
            assert blocks["segment"] == "（这本书开书时还没有分段规划，按本卷卡片和走向的节点规划）"
            assert "旧书主角钩子" in blocks["protagonist"]
            assert blocks["opening"] == ""
            assert "下一卷：无（这是最后一卷）" in blocks["neighbors"]


async def test_volume_plan_nonempty_answers_replace_card_but_empty_answers_preserve_it(sessionmaker):
    async with sessionmaker() as session:
        book, volume, _ = await fixture(session)
        await save_volume_plan(session, book.id, volume, [], [], replace_new=False, want="", pressure="  ")
        assert (volume.want, volume.pressure) == ("找到妹妹的下落", "身无分文")
        await save_volume_plan(
            session,
            book.id,
            volume,
            [{"index": 1, "title": "破局", "loop": "受托查案换到妹妹线索"}],
            [],
            replace_new=False,
            want="救出线人",
            pressure="城门只开半个时辰",
        )
        assert (volume.want, volume.pressure) == ("救出线人", "城门只开半个时辰")


@pytest.mark.parametrize(
    ("segmented", "end", "completed"), [(True, False, False), (True, True, True), (False, False, True)]
)
async def test_finishing_planned_volumes_does_not_complete_unfinished_new_book(sessionmaker, segmented, end, completed):
    async with sessionmaker() as session:
        book, _, _ = await fixture(session, segmented=segmented, end=end)
        result = await _next_step(session, book, {"until": "book"})
        assert result["step"] == "done"
        assert (book.status == "completed") is completed
        assert result["reason"] == (
            "全书写完了！"
            if completed
            else "这一段写完了。下一段怎么走，等「定下一段」功能接入后由主编来定，先停在这里。"
        )


@pytest.mark.parametrize("ending", [True, False])
async def test_finale_volume_without_following_card_can_say_final_volume(sessionmaker, ending):
    async with sessionmaker() as session:
        book, volume, target = await fixture(session, end=ending)
        if not ending:
            target.segment = {**target.segment, "finale": True}
        await session.flush()
        assert "下一卷：无（这是最后一卷）" in (await volume_blocks(session, book, volume))["neighbors"]
