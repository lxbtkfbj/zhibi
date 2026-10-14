"""演示模式：不联网，返回内置的示例内容，用于无 API Key 体验全流程和自动化测试。"""

import asyncio
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.agents import schemas as s

DELAY_S = 0.3


def _idea(user: str) -> str:
    match = re.search(r"【作者的点子】\n(.+?)(\n\n|$)", user, re.S)
    return match.group(1).strip()[:60] if match else "一个落魄少年意外得到上古传承"


def _concept(user: str) -> s.BookConcept:
    return s.BookConcept(
        title="青灯问道",
        alt_titles=["一灯照九州", "灯下问长生"],
        genre="玄幻·修仙",
        tags=["凡人流", "宗门", "智斗", "慢热成长"],
        logline=f"{_idea(user)}——杂役弟子陆远捡到一盏能照见他人寿元的青灯，从此在吃人的宗门里步步为营。",
        selling_points=[
            "青灯能看见他人剩余寿元，信息差带来的智斗爽感",
            "杂役翻身，每次突破都用计谋而非奇遇",
            "宗门内斗与正邪两道的灰色地带",
        ],
        protagonist_hook="陆远知道每个人还能活多久，却必须装作什么都不知道",
        tone="冷静克制，带一点黑色幽默，节奏紧凑",
        target_volumes=4,
        chapter_words=3000,
        remark="这本书的钩子我定在「看得见寿元的青灯」上，信息差是最稳的爽点，主角靠脑子赢。",
    )


def _lore() -> s.LoreDraft:
    return s.LoreDraft(
        world_entries=[
            s.WorldEntryDraft(
                category="力量体系",
                name="修行境界",
                content="炼气、筑基、结丹、元婴、化神五境，每境分初、中、后期。每次突破需要消耗寿元换取灵力上限，寿元耗尽者坐化。",
            ),
            s.WorldEntryDraft(
                category="物品",
                name="青灯",
                content="上古遗物，点燃后可看见视野内生灵头顶的寿元数字。每次点燃消耗持灯人一日寿元，灯芯燃尽前无法熄灭。",
            ),
            s.WorldEntryDraft(
                category="势力",
                name="玄冥宗",
                content="北境第一大宗，外门弟子三千，杂役上万。宗规森严，弟子间允许「生死擂」，胜者可夺败者资源。",
            ),
            s.WorldEntryDraft(
                category="势力", name="血河教", content="正道口中的魔教，以吸取他人寿元修行。与玄冥宗高层暗中有交易。"
            ),
            s.WorldEntryDraft(
                category="地理", name="北境寒原", content="终年积雪，灵脉稀薄，玄冥宗建在寒原唯一的地火灵脉之上。"
            ),
            s.WorldEntryDraft(
                category="规则",
                name="寿元交易",
                content="修士之间可以通过契约转让寿元，但违约者会被契约反噬。此事在正道属于禁忌。",
            ),
        ],
        characters=[
            s.CharacterDraft(
                name="陆远",
                role_type="主角",
                gender="男",
                age="十六岁",
                appearance="瘦高，左手缺一根小指",
                personality="谨慎多疑，说话留三分，心软但不让别人看出来",
                background="寒原猎户之子，父母死于兽潮，被卖进玄冥宗当杂役",
                abilities="炼气一层，擅长辨认药草",
                goal="活下去，然后查清父母之死的真相",
                location="玄冥宗杂役院",
                condition="刚挨过一顿打，肋骨有伤",
                secrets=["青灯在他手里", "他看见宗主只剩三年寿元"],
            ),
            s.CharacterDraft(
                name="苏晚晴",
                role_type="女主",
                gender="女",
                age="十七岁",
                appearance="总穿一身旧青衣，笑起来眼角有颗痣",
                personality="外冷内热，嘴硬，极讲规矩",
                background="外门执法堂弟子，出身没落世家",
                abilities="筑基初期，剑修",
                goal="重振家族",
                location="玄冥宗执法堂",
                condition="正常",
                secrets=["她的家族当年被血河教灭门"],
            ),
            s.CharacterDraft(
                name="赵乾",
                role_type="反派",
                gender="男",
                age="二十岁",
                appearance="锦衣玉带，手上总戴扳指",
                personality="笑面虎，睚眦必报",
                background="长老之孙，外门首席",
                abilities="筑基中期",
                goal="拜入内门，成为宗主亲传",
                location="玄冥宗外门",
                condition="正常",
                secrets=["他私下与血河教做寿元交易"],
            ),
            s.CharacterDraft(
                name="老瞎子",
                role_type="配角",
                gender="男",
                age="不详",
                appearance="双目失明，常年抱着一把破扫帚",
                personality="疯疯癫癫，偶尔说出惊人之语",
                background="杂役院扫地人，没人知道他来了多久",
                abilities="深不可测",
                goal="不详",
                location="玄冥宗杂役院",
                condition="寿元只剩七日（陆远所见）",
                secrets=["他是青灯上一任主人"],
            ),
            s.CharacterDraft(
                name="宗主厉沧海",
                role_type="反派",
                gender="男",
                age="三百余岁",
                appearance="白发童颜",
                personality="威严，喜怒不形于色",
                background="玄冥宗宗主，元婴后期",
                abilities="元婴后期",
                goal="突破化神，延长寿元",
                location="玄冥宗主峰",
                condition="寿元仅剩三年（外人不知）",
                secrets=["他在暗中收集寿元"],
            ),
        ],
        relationships=[
            s.RelationshipDraft(
                source="陆远",
                target="老瞎子",
                kind="亦师亦友",
                description="老瞎子常给陆远留半个馒头，青灯也是从他那里流到陆远手上",
            ),
            s.RelationshipDraft(
                source="陆远", target="赵乾", kind="仇敌", description="赵乾的跟班打伤了陆远，陆远记下了这笔账"
            ),
            s.RelationshipDraft(
                source="苏晚晴", target="赵乾", kind="对立", description="苏晚晴在执法堂多次查赵乾，都被长老压下"
            ),
        ],
        remark="力量体系我设计成「突破要烧寿元」，这样青灯看寿元就不只是外挂，而是整个世界的命门。",
    )


def _outline() -> s.OutlineDraft:
    return s.OutlineDraft(
        volumes=[
            s.VolumeDraft(
                index=1,
                title="杂役",
                summary="陆远得到青灯，在杂役院和外门之间周旋，借寿元信息差扳倒赵乾的跟班，进入外门。",
                goal="成为外门弟子，发现宗门里有人在收集寿元",
            ),
            s.VolumeDraft(
                index=2,
                title="生死擂",
                summary="外门大比，陆远与赵乾正面冲突，牵出寿元交易的线索。",
                goal="击败赵乾，与苏晚晴结盟",
            ),
            s.VolumeDraft(
                index=3, title="血河", summary="追查血河教，发现宗主与魔教交易的真相。", goal="揭开父母之死的真相"
            ),
            s.VolumeDraft(
                index=4,
                title="青灯尽",
                summary="宗主寿元将尽，孤注一掷；陆远必须在灯芯燃尽前做出选择。",
                goal="结束寿元交易，付出自己的代价",
            ),
        ],
        first_volume_units=[
            s.PlotUnitDraft(
                index=1,
                title="捡灯",
                chapter_count=6,
                goal="活过被欺压的杂役日常",
                conflict="赵乾的跟班克扣口粮并毒打陆远",
                climax="陆远第一次点燃青灯，看见打他的人只剩两天寿元",
                outcome="跟班果然暴毙，陆远意识到青灯的真实性，也被执法堂盯上",
                key_events=["陆远挨打", "老瞎子塞给他一盏旧灯", "灯火照见寿元", "跟班暴毙"],
            ),
            s.PlotUnitDraft(
                index=2,
                title="执法堂",
                chapter_count=8,
                goal="洗清嫌疑",
                conflict="苏晚晴怀疑陆远与暴毙案有关",
                climax="陆远利用寿元信息推断出真凶另有其人，当众对质",
                outcome="苏晚晴欠他一个人情，赵乾开始注意这个杂役",
                key_events=["被带去执法堂", "暗中观察寿元", "找到中毒证据", "当众对质"],
            ),
            s.PlotUnitDraft(
                index=3,
                title="老瞎子的七日",
                chapter_count=7,
                goal="弄清青灯来历",
                conflict="老瞎子只剩七日寿元，且不肯多说",
                climax="老瞎子坐化前留下半句遗言",
                outcome="陆远得知青灯与宗主有关，决定进入外门",
                key_events=["追问老瞎子", "老瞎子病重", "坐化与遗言"],
            ),
            s.PlotUnitDraft(
                index=4,
                title="外门考核",
                chapter_count=10,
                goal="通过外门考核",
                conflict="赵乾在考核中设局",
                climax="陆远将计就计，借寿元信息让设局者自食其果",
                outcome="陆远成为外门弟子，发现考核中有人在偷偷收取寿元",
                key_events=["报名考核", "识破陷阱", "反制", "进入外门"],
            ),
        ],
        foreshadowings=[
            s.ForeshadowingDraft(
                description="陆远左手缺的小指",
                plant_plan="第一卷开头随笔带过",
                payoff_plan="第三卷揭示是幼时被血河教取走的寿元契约印记",
            ),
            s.ForeshadowingDraft(
                description="宗主只剩三年寿元",
                plant_plan="第一卷陆远远远看见宗主时发现",
                payoff_plan="第四卷成为宗主孤注一掷的动机",
            ),
            s.ForeshadowingDraft(
                description="老瞎子的半句遗言", plant_plan="第一卷第三单元结尾", payoff_plan="第三卷补全，指向父母之死"
            ),
        ],
        remark="第一卷我拆成四个单元，每个单元都有一次靠寿元信息差翻盘的高潮，保证前期节奏不拖。",
    )


def _critique() -> s.SetupCritique:
    return s.SetupCritique(
        verdict="revise",
        highlights=["寿元信息差的设定和主角性格很搭", "第一卷每个单元都有明确的翻盘点"],
        issues=[
            s.ReviewIssue(
                target="outline",
                problem="第二单元「执法堂」8 章只围绕一个案子，中段容易拖",
                suggestion="压缩到 6 章，并在中段加入赵乾的试探",
                severity="medium",
            ),
        ],
        remark="整体能打，但执法堂那段太长了，读者会在第 10 章左右流失。",
    )


def _triage(user: str) -> s.RevisionTriage:
    feedback = re.search(r"【作者意见】\n(.+?)(\n\n|$)", user, re.S)
    text = feedback.group(1).strip() if feedback else "按审稿意见调整"
    return s.RevisionTriage(outline_instructions=text, remark=f"作者的意见我看了：{text[:40]}。主要影响大纲，我来改。")


def _outline_revised() -> s.OutlineDraft:
    draft = _outline()
    draft.first_volume_units[1].chapter_count = 6
    draft.first_volume_units[1].key_events.insert(2, "赵乾派人试探陆远")
    draft.remark = "执法堂单元压到 6 章，中间加了一场赵乾的试探，节奏紧一些了。"
    return draft


async def respond(schema: type[BaseModel], system: str, user: str) -> BaseModel:
    await asyncio.sleep(DELAY_S)
    revising = "【修改要求】" in user or "【审稿意见】" in user
    if schema is s.BookConcept:
        return _concept(user)
    if schema is s.LoreDraft:
        return _lore()
    if schema is s.OutlineDraft:
        return _outline_revised() if revising else _outline()
    if schema is s.SetupCritique:
        return _critique()
    if schema is s.RevisionTriage:
        return _triage(user)
    raise NotImplementedError(f"演示模式暂不支持 {schema.__name__}")


async def stream_text(system: str, user: str) -> AsyncIterator[str]:
    text = "（演示模式）夜里的杂役院很静，陆远捂着肋下的伤，借着月光看那盏旧灯。灯芯是青色的，像一截还没长开的竹子。"
    for i in range(0, len(text), 8):
        await asyncio.sleep(0.05)
        yield text[i : i + 8]
