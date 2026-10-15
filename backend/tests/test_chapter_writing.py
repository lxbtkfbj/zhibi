"""写章节提质（演示模型）：设定师备资料、字数不足续写、总结式结尾改写、伏笔回收带原文、
单元回顾与分层前情、写作过程实时推送、作者重写已定稿的章节。"""

import json
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.config import get_settings
from app.graphs.write_book import polish_step, split_ending, summary_ending, word_count
from app.llm import demo
from app.models import Book, Chapter, Character, Foreshadowing, Job, LlmCall, MeetingMessage, PlotUnit
from app.services import jobs
from app.services.job_runner import execute_job
from app.services.meeting import stream_key
from app.services.writing_context import best_excerpt, fit_entries
from tests.test_write_book import approved_book, chapters, job_state, write_job


@pytest.fixture(autouse=True)
def fast_demo(monkeypatch):
    monkeypatch.setattr(demo, "DELAY_S", 0)


def capture(monkeypatch) -> tuple[list[tuple[str, str]], list[str]]:
    """记下发给演示模型的提示词：结构化调用 (schema 名, 提示词)，流式调用（写手）的提示词。"""
    structured: list[tuple[str, str]] = []
    streamed: list[str] = []
    respond, stream = demo.respond, demo.stream_text

    async def fake_respond(schema, system, user):
        structured.append((schema.__name__, user))
        return await respond(schema, system, user)

    async def fake_stream(system, user):
        streamed.append(user)
        async for chunk in stream(system, user):
            yield chunk

    monkeypatch.setattr(demo, "respond", fake_respond)
    monkeypatch.setattr(demo, "stream_text", fake_stream)
    return structured, streamed


async def purposes_of(sessionmaker, job_id) -> list[str]:
    async with sessionmaker() as session:
        return list(
            (await session.execute(select(LlmCall.purpose).where(LlmCall.job_id == job_id).order_by(LlmCall.id)))
            .scalars()
            .all()
        )


async def artifacts(sessionmaker, job_id, kind: str) -> list[dict]:
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(MeetingMessage)
                .where(MeetingMessage.job_id == job_id, MeetingMessage.kind == "artifact")
                .order_by(MeetingMessage.id)
            )
        ).scalars()
        return [m.payload["data"] for m in rows if m.payload["type"] == kind]


async def written_book(sessionmaker, count: int = 3) -> uuid.UUID:
    """开书 → 写前 3 章 → 试读通过；count 大于 3 时再接着写到第 count 章。"""
    book_id = await approved_book(sessionmaker)
    job_id = await write_job(sessionmaker, book_id, count=3)
    await execute_job(job_id)
    await execute_job(job_id, {"action": "approve"})
    if count > 3:
        job_id = await write_job(sessionmaker, book_id, count=count - 3)
        await execute_job(job_id)
        assert (await job_state(sessionmaker, job_id))[0] == "succeeded"
    return book_id


def test_helpers():
    # 回顾太长时先压缩最早的，再不够就略去最早的
    entries = ["甲" * 300, "乙" * 300, "丙" * 300]
    fitted = fit_entries(entries, 700)
    assert sum(len(e) for e in fitted) <= 700 and fitted[-1] == "丙" * 300 and len(fitted[0]) == 100
    dropped = fit_entries(entries, 350)
    assert dropped[0] == "（更早的 2 段从略）" and dropped[-1].startswith("丙")
    # 伏笔回收：找出和伏笔描述最相关的句子
    text = "风很大。陆远低头看着左手缺的那根小指，没有说话。远处有人喊他。灯灭了。"
    assert "缺的那根小指" in best_excerpt(text, "陆远左手缺的小指是契约印记")
    assert best_excerpt(text, "宗主的寿元只剩三年") == ""
    # 总结式结尾
    assert summary_ending("前文。\n\n他知道，一切才刚刚开始。") == "一切才刚刚开始"
    assert summary_ending("前文。\n\n灯火里，一个本不该出现的人头顶只剩三天寿元。") == ""
    body, ending = split_ending("第一段。\n\n第二段。\n\n第三段。")
    assert body == "第一段。" and ending == "第二段。\n\n第三段。"
    assert polish_step("字" * 1000, 3000, 0, False) == "extend"
    assert polish_step("字" * 1000, 3000, 2, False) == ""  # 续写两次还不够也不再续
    assert polish_step("字" * 2500 + "\n\n一切才刚刚开始。", 3000, 0, False) == "fix_ending"


async def test_materials_polish_recap_and_recall(sessionmaker, monkeypatch):
    book_id = await written_book(sessionmaker, 3)
    structured, streamed = capture(monkeypatch)
    job_id = await write_job(sessionmaker, book_id, count=4)  # 第 4-7 章
    await execute_job(job_id)
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error

    purposes = await purposes_of(sessionmaker, job_id)
    assert purposes.count("写作·备资料") == 4
    assert purposes.count("写作·续写") == 1  # 第 4 章初稿太短，接着写了一次
    assert purposes.count("写作·改结尾") == 1  # 第 5 章结尾写成了总结
    assert purposes.count("写作·单元回顾") == 1  # 第一单元（6 章）写完
    assert purposes.index("写作·单元回顾") < purposes.index("写作·章纲")  # 先写回顾，再给下一单元出章纲

    rows = await chapters(sessionmaker, book_id)
    by_index = {c.index: c for c in rows}
    assert all(by_index[i].status == "final" for i in range(1, 8))
    # 字数：第 4 章续写后够了；结尾：第 5 章改成了停在钩子上
    assert by_index[4].word_count >= 3000 * 0.7
    assert by_index[4].content.rstrip().endswith(f"{by_index[4].outline['hook']}。")
    assert "一切才刚刚开始" not in by_index[5].content
    assert by_index[5].content.rstrip().endswith(f"{by_index[5].outline['hook']}。")
    polish = await artifacts(sessionmaker, job_id, "chapter_polish")
    assert [(p["index"], p["action"]) for p in polish] == [(4, "extend"), (5, "ending")]
    assert polish[0]["before"] < 3000 * 0.7 <= polish[0]["after"]

    # 设定师备的资料：章纲点名的人物之外补上了老瞎子，挑了青灯，回顾第 1 章，写了提醒
    materials = by_index[4].materials
    assert "老瞎子" in materials["characters"] and "青灯" in materials["world"]
    assert materials["chapters"] == [1] and materials["notes"]
    write4 = next(u for u in streamed if "请写第 4 章" in u)
    assert "【老瞎子】" in write4  # 资料里的人物带上了完整人物卡
    assert "【设定师的提醒】" in write4 and "陆远每点一次青灯就折一日寿元" in write4
    assert "【设定师挑出的相关前文】\n第1章《" in write4

    # 第一单元写完，设定师写了单元回顾；给第二单元出章纲时带上分层的前情
    async with sessionmaker() as session:
        first = (
            (await session.execute(select(PlotUnit).where(PlotUnit.book_id == book_id, PlotUnit.index == 1)))
            .scalars()
            .first()
        )
    assert first.recap.startswith("「捡灯」共 6 章")
    assert (await artifacts(sessionmaker, job_id, "unit_recap"))[0]["recap"] == first.recap
    plan = next(u for name, u in structured if name == "ChapterPlanDraft")
    assert "◆ 本卷前面各单元回顾\n单元1「捡灯」：「捡灯」共 6 章" in plan and "◆ 最近几章" in plan

    # 第 7 章回收第 1 章埋下的药碗伏笔：F/E 共用编号，按内容定位而不写死序号。
    async with sessionmaker() as session:
        poison = (
            await session.execute(
                select(Foreshadowing).where(
                    Foreshadowing.book_id == book_id,
                    Foreshadowing.kind == "伏笔",
                    Foreshadowing.description == "跟班暴毙前喝过的那碗药被人动过手脚",
                )
            )
        ).scalar_one()
    write7 = next(u for u in streamed if "请写第 7 章" in u)
    assert "【本章要处理的伏笔】" in write7
    assert f"- 回收F{poison.seq}［已埋］跟班暴毙前喝过的那碗药被人动过手脚" in write7
    assert "第1章《" in write7 and "（埋下）原文：「" in write7 and "跟班暴毙前喝过的那碗药被人动过手脚——" in write7
    assert "单元1「捡灯」：「捡灯」共 6 章" in write7
    assert poison.status == "resolved" and poison.planted_chapter == 1 and poison.resolved_chapter == 7

    # 写的过程实时推给网页：只走 Redis，带着到目前为止的全文，最后一条标记写完
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        entries = await redis.xrange(stream_key(book_id))
    finally:
        await redis.aclose()
    drafts = [json.loads(f["data"]) for _, f in entries if f["event"] == "draft"]
    extend = [x for x in drafts if x["chapter"] == 4 and x["mode"] == "extend"]
    assert len(extend) > 1 and extend[-1]["done"] and not extend[0]["done"]
    assert len(extend[-1]["text"]) > len(extend[0]["text"])
    assert {x["mode"] for x in drafts if x["chapter"] == 5} == {"write", "ending"}


def bible_digest(monkeypatch, label=lambda n: f"第{n}章之后"):
    """让每一章的设定变化都不一样，便于检查撤销：主角状态、新人物、伏笔提醒。"""
    original = demo.respond

    async def respond(schema, system, user):
        if schema is demo.s.ChapterDigest:
            n = int(demo._match(r"第 (\d+) 章《", user))
            rewritten = "按作者的意见改" in demo._section(user, "正文")
            return demo.s.ChapterDigest(
                summary=f"第{n}章摘要" + ("（重写）" if rewritten else ""),
                character_updates=[
                    demo.s.CharacterUpdate(name="陆远", condition=label(n) + ("·重写" if rewritten else ""))
                ],
                new_characters=[] if rewritten else [demo.s.NewCharacter(name=f"路人{n}")],
                foreshadow_updates=[]
                if rewritten
                else [demo.s.ForeshadowUpdate(ref="F1", action="埋下" if n == 1 else "提醒")],
                remark="记好了。",
            )
        return await original(schema, system, user)

    monkeypatch.setattr(demo, "respond", respond)


async def rewrite(sessionmaker, book_id, index: int, feedback: str) -> uuid.UUID:
    async with sessionmaker() as session:
        chapter = (
            await session.execute(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == index))
        ).scalar()
        job = jobs.new_rewrite_job(await session.get(Book, book_id), chapter, feedback)
        session.add(job)
        await session.commit()
        job_id = job.id
    await execute_job(job_id)
    return job_id


async def bible_state(sessionmaker, book_id):
    async with sessionmaker() as session:
        hero = (
            await session.execute(select(Character).where(Character.book_id == book_id, Character.name == "陆远"))
        ).scalar()
        names = set((await session.execute(select(Character.name).where(Character.book_id == book_id))).scalars())
        f1 = (
            await session.execute(select(Foreshadowing).where(Foreshadowing.book_id == book_id, Foreshadowing.seq == 1))
        ).scalar()
        return hero.condition, names, f1


async def test_rewrite_latest_final_chapter(sessionmaker, monkeypatch):
    bible_digest(monkeypatch)
    book_id = await written_book(sessionmaker, 3)
    condition, names, f1 = await bible_state(sessionmaker, book_id)
    assert condition == "第3章之后" and {"路人1", "路人2", "路人3"} <= names
    assert f1.hint_chapters == [2, 3] and f1.planted_chapter == 1

    _, streamed = capture(monkeypatch)
    job_id = await rewrite(sessionmaker, book_id, 3, "打斗再多一点")
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    # 先撤销第 3 章原来的变化再重写：写手看到的是第 3 章之前的状态
    prompt = streamed[0]
    assert "请写第 3 章" in prompt and "【上一稿】" in prompt and "- [作者] 打斗再多一点" in prompt
    assert "当前：玄冥宗杂役院，第2章之后" in prompt
    purposes = await purposes_of(sessionmaker, job_id)
    assert purposes[0] == "写作·正文" and "写作·备资料" not in purposes  # 资料第一次写时备过了
    assert purposes[-1] == "写作·更新设定库"

    chapter = (await chapters(sessionmaker, book_id))[2]
    assert chapter.status == "final" and "（按作者的意见改：打斗再多一点）" in chapter.content
    assert chapter.summary == "第3章摘要（重写）"
    condition, names, f1 = await bible_state(sessionmaker, book_id)
    assert condition == "第3章之后·重写"  # 重新提取的变化
    assert "路人3" not in names and "路人2" in names  # 第 3 章新建的人物撤掉了，前面的不动
    assert f1.hint_chapters == [2]  # 第 3 章的提醒撤掉了
    assert chapter.bible_changes["characters"][0]["after"]["condition"] == "第3章之后·重写"
    async with sessionmaker() as session:
        kinds = [
            m.content
            for m in (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job_id))).scalars()
            if m.kind == "decision"
        ]
    assert kinds == ["第3章按作者的意见重写好了。"]


async def test_rewrite_earlier_chapter_keeps_later_changes(sessionmaker, monkeypatch):
    bible_digest(monkeypatch)
    book_id = await written_book(sessionmaker, 3)
    job_id = await rewrite(sessionmaker, book_id, 2, "苏晚晴的台词再冷一点")
    status, _, error = await job_state(sessionmaker, job_id)
    assert status == "succeeded", error
    condition, names, f1 = await bible_state(sessionmaker, book_id)
    # 主角状态后来被第 3 章改过：撤销第 2 章时不动，重新提取第 2 章时也不拿旧状态盖掉
    assert condition == "第3章之后"
    # 后面已经有定稿的章节，第 2 章新建的人物保留（后文可能写到）；第 2 章的提醒撤掉
    assert "路人2" in names
    assert f1.hint_chapters == [3]
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        speeches = [
            m.content
            for m in (await session.execute(select(MeetingMessage).where(MeetingMessage.job_id == job.id))).scalars()
            if m.speaker == "chief"
        ]
    assert any("后面已经定稿了 1 章" in s for s in speeches)
    assert word_count((await chapters(sessionmaker, book_id))[1].content) > 0
