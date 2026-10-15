"""演示模式：不联网，返回内置的示例内容，用于无 API Key 体验全流程和自动化测试。"""

import asyncio
import os
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.agents import schemas as s

# 每次「调用」的耗时；演示时可调大，方便看清编辑部的讨论过程、试试中途插话
DELAY_S = float(os.environ.get("ZHIBI_DEMO_DELAY", "0.3"))


def _idea(user: str) -> str:
    match = re.search(r"【作者的点子】\n(.+?)(\n\n|$)", user, re.S)
    return match.group(1).strip()[:60] if match else "一个落魄少年意外得到上古传承"


def _concept(user: str) -> s.BookConcept:
    # 点子里提到后宫时按后宫玄幻爽文来定，便于体验题材打法库的选择
    harem = "后宫" in _idea(user)
    title, alt_titles = "青灯问道", ["一灯照九州", "灯下问长生"]
    rules = re.search(r"【这本书的写作规矩】\n(.*?)(?:\n\n|$)", user, re.S)
    title_rule = re.search(r"^- 书名：(.+)$", rules.group(1), re.M) if rules else None
    if title_rule:
        rule = title_rule.group(1).strip()
        if rule.startswith("番茄式长书名"):
            title = "青灯问道：看透寿元的我在宗门步步为营"
            alt_titles = ["一灯照九州：从杂役开始窥见长生", "灯下问长生：我能看见所有人的死期"]
        elif not rule.startswith("2-6 个字的经典短书名"):
            title = rule.strip("《》")
            alt_titles = [title + "记", title + "录"]
    return s.BookConcept(
        title=title,
        alt_titles=alt_titles,
        genre="玄幻·东方玄幻" if harem else "玄幻·修仙",
        tags=["后宫", "爽文", "宗门", "智斗"] if harem else ["凡人流", "宗门", "智斗", "慢热成长"],
        logline=f"{_idea(user)}——杂役弟子陆远捡到一盏能照见他人寿元的青灯，从此在吃人的宗门里步步为营。",
        selling_points=[
            "青灯能看见他人剩余寿元，信息差带来的智斗爽感",
            "杂役翻身，每次突破都用计谋而非奇遇",
            "宗门内斗与正邪两道的灰色地带",
        ],
        protagonist_hook="陆远知道每个人还能活多久，却必须装作什么都不知道",
        tone="冷静克制，带一点黑色幽默，节奏紧凑",
        target_length=100,
        target_volumes=4,
        chapter_words=3000,
        remark="这本书的钩子我定在「看得见寿元的青灯」上，信息差是最稳的爽点，主角靠脑子赢。篇幅先按 100 万字、四卷来规划。",
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
        remark="主角叫陆远，金手指是一盏能照见寿元的青灯，但每次点燃都要烧掉他自己一天寿命；头号反派是宗主厉沧海。力量体系我设计成「突破要烧寿元」，这样青灯就不只是外挂，而是整个世界的命门。",
    )


def _spine() -> s.StorySpine:
    return s.StorySpine(
        core_conflict="陆远想活下去并查清父母之死，而整个玄冥宗高层都靠暗中收割寿元续命",
        theme="命数可以被看见，却不该被买卖",
        protagonist_arc="从只求自保、事事留三分的杂役，变成愿意为别人的寿元押上自己性命的人",
        opening="寒冬的杂役院，陆远挨了一顿毒打，老瞎子塞给他一盏旧灯。灯火一亮，他看见打他的人头顶只剩两天寿元——第 3 章那人果然暴毙，陆远第一次意识到自己能看见别人的死期。",
        ending="宗主厉沧海在突破化神的大典上发动寿元大阵，要抽干全宗弟子续命。陆远点燃燃尽的青灯，把自己剩下的寿元全部还给被收割的人，阵法反噬，宗主坐化。陆远活了下来，却再也看不见任何人的寿元，他和苏晚晴在寒原上重建杂役院。",
        milestones=[
            s.Milestone(
                index=1,
                title="灯照死期",
                volume=1,
                event="陆远捡到青灯，看见跟班只剩两天寿元，跟班暴毙",
                change="陆远确认青灯为真，同时被执法堂盯上",
            ),
            s.Milestone(
                index=2,
                title="老瞎子坐化",
                volume=1,
                event="青灯的上一任主人老瞎子坐化，留下半句遗言",
                change="陆远失去唯一的庇护，决定进入外门追查",
            ),
            s.Milestone(
                index=3,
                title="生死擂",
                volume=2,
                event="外门大比上陆远与赵乾正面对决，借寿元信息险胜",
                change="陆远成名，也暴露在宗门高层视线里",
            ),
            s.Milestone(
                index=4,
                title="契约印记",
                volume=3,
                event="陆远发现左手缺的小指是幼时被取走寿元的契约印记",
                change="父母之死与宗门交易连成一线，他不再只求自保",
            ),
            s.Milestone(
                index=5,
                title="宗主的三年",
                volume=3,
                event="陆远证实宗主与血河教交易寿元，自己只剩三年可活",
                change="与苏晚晴结盟，主动对抗宗主",
            ),
            s.Milestone(
                index=6,
                title="青灯尽",
                volume=4,
                event="化神大典上陆远燃尽青灯，以自身寿元反噬大阵",
                change="宗主坐化，寿元交易终结，陆远失去青灯",
            ),
        ],
        remark="结局我先定了：陆远最后用自己的寿元破掉宗主的大阵，赢了却失去青灯。中间最关键的转折是第三卷发现小指的契约印记，从那以后他不再只求自保。",
    )


def _threads() -> s.ThreadsDraft:
    return s.ThreadsDraft(
        threads=[
            s.ThreadDraft(
                name="主线：青灯与寿元",
                kind="主线",
                characters=["陆远", "宗主厉沧海"],
                summary="陆远靠青灯看见寿元，从自保到揭开玄冥宗收割寿元的真相，最终燃尽青灯破掉寿元大阵。",
                beats=[
                    s.ThreadBeat(volume=1, beat="捡到青灯，确认能看见寿元，借信息差活下来并进入外门"),
                    s.ThreadBeat(volume=2, beat="外门大比中发现有人在比试里偷取败者寿元"),
                    s.ThreadBeat(volume=3, beat="查到宗主与血河教交易寿元，自己也只剩三年可活"),
                    s.ThreadBeat(volume=4, beat="化神大典上燃尽青灯，以自身寿元反噬大阵"),
                ],
            ),
            s.ThreadDraft(
                name="感情线：苏晚晴",
                kind="感情线",
                characters=["陆远", "苏晚晴"],
                summary="从执法堂里的互相怀疑，到并肩查案，再到寒原上一起重建杂役院。",
                beats=[
                    s.ThreadBeat(volume=1, beat="执法堂初见，互相怀疑；陆远替她洗清一桩冤案，她欠下人情"),
                    s.ThreadBeat(volume=2, beat="生死擂前她暗中提醒陆远，两人第一次并肩"),
                    s.ThreadBeat(volume=3, beat="得知灭门真相后她一度迁怒陆远，又在血河教总坛救下他"),
                    s.ThreadBeat(volume=4, beat="大典上她守住阵眼，结局与陆远一起离开宗门"),
                ],
            ),
            s.ThreadDraft(
                name="反派线：玄冥宗高层",
                kind="反派线",
                characters=["赵乾", "宗主厉沧海"],
                summary="从赵乾的跟班，到赵乾本人，再到幕后的宗主，对手一层比一层深。",
                beats=[
                    s.ThreadBeat(volume=1, beat="赵乾的跟班欺压陆远，赵乾在考核中设局"),
                    s.ThreadBeat(volume=2, beat="赵乾在生死擂上被击败，背后长老开始盯上陆远"),
                    s.ThreadBeat(volume=3, beat="宗主借血河教之手清理知情人，陆远成为目标"),
                    s.ThreadBeat(volume=4, beat="宗主发动寿元大阵，最终坐化"),
                ],
            ),
            s.ThreadDraft(
                name="谜团线：父母之死",
                kind="谜团线",
                characters=["陆远", "老瞎子"],
                summary="兽潮、缺失的小指与老瞎子的遗言，一步步指向幼时的寿元契约。",
                beats=[
                    s.ThreadBeat(volume=1, beat="老瞎子坐化前留下半句遗言"),
                    s.ThreadBeat(volume=3, beat="小指的契约印记揭开父母之死与宗门交易的关系"),
                ],
            ),
        ],
        remark="我把这本书拆成四条线：主线是青灯与寿元，苏晚晴一条感情线，反派从赵乾一路升级到宗主，再加一条父母之死的谜团线。第三卷是几条线的交汇点。",
    )


def _outline() -> s.OutlineDraft:
    return s.OutlineDraft(
        volumes=[
            s.VolumeDraft(
                index=1,
                title="杂役",
                stage="玄冥宗杂役院 → 外门",
                summary="陆远得到青灯，在杂役院和外门之间周旋，借寿元信息差扳倒赵乾的跟班，进入外门。",
                goal="成为外门弟子，发现宗门里有人在收集寿元",
                climax="外门考核中将计就计，让设局者自食其果",
                antagonist="赵乾和他的跟班：想把陆远这个碍眼的杂役踩死",
                power_range="炼气一层 → 炼气四层",
                thread_beats=[
                    s.ThreadStep(thread="主线：青灯与寿元", beat="捡到青灯并确认其真假"),
                    s.ThreadStep(thread="感情线：苏晚晴", beat="执法堂初见，她欠下人情"),
                ],
                new_characters=["苏晚晴：执法堂弟子"],
                chapter_count=31,
            ),
            s.VolumeDraft(
                index=2,
                title="生死擂",
                stage="玄冥宗外门",
                summary="外门大比，陆远与赵乾正面冲突，牵出寿元交易的线索。",
                goal="击败赵乾，与苏晚晴结盟",
                climax="生死擂上借寿元信息险胜赵乾",
                antagonist="赵乾与他背后的长老",
                power_range="炼气四层 → 筑基初期",
                thread_beats=[
                    s.ThreadStep(thread="反派线：玄冥宗高层", beat="击败赵乾，长老开始盯上陆远"),
                    s.ThreadStep(thread="感情线：苏晚晴", beat="生死擂前两人第一次并肩"),
                ],
                new_characters=["周长老：赵乾的祖父"],
                chapter_count=90,
            ),
            s.VolumeDraft(
                index=3,
                title="血河",
                stage="北境寒原 → 血河教总坛",
                summary="追查血河教，发现宗主与魔教交易的真相。",
                goal="揭开父母之死的真相",
                climax="血河教总坛里，契约印记揭开父母之死",
                antagonist="血河教与暗中出手的宗主",
                power_range="筑基初期 → 结丹初期",
                thread_beats=[
                    s.ThreadStep(thread="谜团线：父母之死", beat="小指的契约印记揭开真相"),
                    s.ThreadStep(thread="主线：青灯与寿元", beat="查到宗主交易寿元"),
                ],
                chapter_count=100,
            ),
            s.VolumeDraft(
                index=4,
                title="青灯尽",
                stage="玄冥宗主峰",
                summary="宗主寿元将尽，孤注一掷；陆远必须在灯芯燃尽前做出选择。",
                goal="结束寿元交易，付出自己的代价",
                climax="化神大典上燃尽青灯，大阵反噬",
                antagonist="宗主厉沧海",
                power_range="结丹初期 → 结丹后期",
                thread_beats=[s.ThreadStep(thread="主线：青灯与寿元", beat="燃尽青灯破阵")],
                chapter_count=112,
            ),
        ],
        foreshadowings=[
            s.ForeshadowingDraft(
                description="陆远左手缺的小指，是幼时被血河教取走寿元的契约印记",
                span="长",
                plant_plan="第一卷开头随笔带过，读者以为只是旧伤",
                payoff_plan="第三卷揭示是契约印记，指向父母之死",
                plant_volume=1,
                payoff_volume=3,
            ),
            s.ForeshadowingDraft(
                description="宗主只剩三年寿元",
                span="长",
                plant_plan="第一卷陆远远远看见宗主时发现，却不敢声张",
                payoff_plan="第四卷成为宗主孤注一掷的动机",
                plant_volume=1,
                payoff_volume=4,
            ),
            s.ForeshadowingDraft(
                description="老瞎子的半句遗言",
                span="长",
                plant_plan="第一卷老瞎子坐化前只说了半句",
                payoff_plan="第三卷补全，指向父母之死",
                plant_volume=1,
                payoff_volume=3,
            ),
        ],
        remark="全书四卷三百多章：舞台从杂役院一路走到宗主峰，对手从跟班升级到宗主。最长的伏笔是陆远缺的那根小指，第一卷埋，第三卷收。",
    )


FIRST_VOLUME_UNITS = [
    s.PlotUnitDraft(
        index=1,
        title="捡灯",
        chapter_count=6,
        goal="活过被欺压的杂役日常",
        conflict="赵乾的跟班克扣口粮并毒打陆远",
        climax="陆远第一次点燃青灯，看见打他的人只剩两天寿元",
        outcome="跟班果然暴毙，陆远意识到青灯的真实性，也被执法堂盯上",
        key_events=["陆远挨打", "老瞎子塞给他一盏旧灯", "灯火照见寿元", "跟班暴毙"],
        thread_beats=[s.ThreadStep(thread="主线：青灯与寿元", beat="捡到青灯，确认能看见寿元")],
        foreshadow_actions=[s.ForeshadowStep(ref="F1", action="埋下", detail="挨打时随笔带过缺的小指")],
        tropes=["以弱胜强"],
        resolution="底牌显露",
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
        thread_beats=[s.ThreadStep(thread="感情线：苏晚晴", beat="执法堂初见，互相怀疑")],
        foreshadow_actions=[s.ForeshadowStep(ref="F2", action="埋下", detail="远远看见宗主头顶只剩三年")],
        tropes=["对质揭穿"],
        resolution="算计设局",
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
        thread_beats=[s.ThreadStep(thread="谜团线：父母之死", beat="老瞎子留下半句遗言")],
        foreshadow_actions=[s.ForeshadowStep(ref="F3", action="埋下", detail="遗言只说了半句")],
        tropes=["身份揭晓"],
        resolution="借势借力",
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
        thread_beats=[s.ThreadStep(thread="反派线：玄冥宗高层", beat="赵乾在考核中设局")],
        tropes=["比试竞赛"],
        resolution="算计设局",
    ),
]

UNIT_TEMPLATES = [
    (
        "暗流",
        "查清对手的布局",
        "对手先一步设下圈套",
        "陆远看穿寿元的异常，反设一局",
        "对手吃了暗亏，却留下更大的隐患",
        "对质揭穿",
        "算计设局",
    ),
    (
        "交锋",
        "在比试中站稳脚跟",
        "对手借规则压人",
        "关键一战以弱胜强",
        "名声大振，也引来更强的敌人",
        "比试竞赛",
        "底牌显露",
    ),
    (
        "夜探",
        "找到交易的证据",
        "守卫森严，线索真假难辨",
        "在最后一刻拿到账册",
        "账册指向一个没想到的人",
        "潜入调查",
        "借势借力",
    ),
    (
        "围杀",
        "活着走出埋伏",
        "多方势力同时出手",
        "借敌人之间的矛盾脱身",
        "盟友受伤，陆远欠下人情",
        "绝境逃亡",
        "算计设局",
    ),
    (
        "破局",
        "扭转被动局面",
        "对手掌握主动，步步紧逼",
        "底牌尽出的一场翻盘",
        "局势反转，主线向前推进一大步",
        "以弱胜强",
        "底牌显露",
    ),
]

# 比稿时主编想的几个方向；方案几就把单元模板轮转几位，拆出来的卷纲各不相同
DIRECTIONS = [
    ("步步为营", "贴着本卷卡片走：每个单元一次信息差翻盘，对手一层层升级，卷末一战定位。", "最稳，节奏均匀"),
    (
        "借刀杀人",
        "陆远不正面出手，借长老之间的矛盾让对手互相撕咬，自己坐收渔利；高潮是两派长老当众翻脸。",
        "主角藏在幕后，智斗为主",
    ),
    (
        "并肩查案",
        "让苏晚晴的感情线唱主角：两人一明一暗查寿元交易，在互相试探里靠近；高潮是她为了陆远违抗执法堂。",
        "感情线比重最大",
    ),
    (
        "绝境脱身",
        "把全卷写成一场被多方追捕的逃亡，陆远借敌对势力的矛盾反过来布局。",
        "以追逐、失去与营救推动线索，卷末逆转追捕者与猎物的地位。",
    ),
]


def _revise_units(user: str, units: list[s.PlotUnitDraft]) -> list[s.PlotUnitDraft]:
    """演示的修改稿：以当前版本为底（标题、关键事件、套路、伏笔动作都保留），再按修改要求改几处。"""
    current = _section(user, "当前卷纲")
    for m in re.finditer(r"单元(\d+)「([^」]*)」(.*?)(?=\n\n单元\d+「|\n\n本卷新埋|\Z)", current, re.S):
        index, body = int(m.group(1)), m.group(3)
        if not 1 <= index <= len(units):
            continue
        unit = units[index - 1]
        unit.title = m.group(2)
        # 每个字段只取一行（_match 带 re.S，这里必须用 [^\n] 防止吞掉后面几行）
        for label, field in (("目标", "goal"), ("冲突", "conflict"), ("高潮", "climax"), ("结果", "outcome")):
            setattr(unit, field, _match(rf"\n{label}：([^\n]+)", body) or getattr(unit, field))
        events = _match(r"\n关键事件：([^\n]+)", body)
        if events:
            unit.key_events = events.split(" → ")
        tropes, resolution = _match(r"\n套路：([^\n]+?)；", body), _match(r"；破局：([^\n]+)", body)
        if tropes and tropes != "未标":
            unit.tropes = tropes.split("、")
        if resolution and resolution != "未标":
            unit.resolution = resolution
        unit.foreshadow_actions = [
            s.ForeshadowStep(ref=ref, action=act) for act, ref in re.findall(r"(埋下|提醒|回收)(F\d+)", body)
        ]
    fix = _section(user, "修改要求")
    for ref, act in re.findall(r"(F\d+)「[^」]*」计划在本卷(埋下|回收)", fix):
        target = units[0] if act == "埋下" else units[-1]
        target.foreshadow_actions.append(s.ForeshadowStep(ref=ref, action=act, detail="按审稿意见补排"))
    if "反派智商" in fix:
        units[min(2, len(units) - 1)].key_events.insert(2, "对手提前布下假账册当诱饵，陆远将计就计")
    # 套路重复：换成和前后单元都不一样的套路
    for index in {int(x) for x in re.findall(r"第(\d+)单元和上一个单元的核心套路都是", fix)}:
        if not 1 <= index <= len(units):
            continue
        # 前一个、后一个单元的套路，以及审稿点名重复的套路，都要避开
        near = {(units[i].tropes or [""])[0] for i in (index - 2, index) if 0 <= i < len(units)}
        near |= set(re.findall(r"核心套路都是「(.+?)」", fix))
        template = next(t for t in UNIT_TEMPLATES if t[5] not in near)
        units[index - 1].tropes, units[index - 1].resolution = [template[5]], template[6]
    return units


def _volume_plan(user: str) -> s.VolumePlanDraft:
    volume = int(_match(r"请为第 (\d+) 卷写「卷纲」", user) or 1)
    revising = "【修改要求】" in user
    if volume == 1:
        units = [u.model_copy(deep=True) for u in FIRST_VOLUME_UNITS]
        remark = "第一卷我拆成四个单元，每个单元都有一次靠寿元信息差翻盘的高潮，保证前期节奏不拖。"
        if revising:
            units[1].chapter_count = 6
            units[1].key_events.insert(2, "赵乾派人试探陆远")
            remark = "执法堂单元压到 6 章，中间加了一场赵乾的试探，节奏紧一些了。"
        return s.VolumePlanDraft(
            units=units,
            new_foreshadowings=[
                s.NewForeshadowing(
                    description="跟班暴毙前喝过的那碗药被人动过手脚",
                    span="短",
                    plant_plan="跟班暴毙时陆远注意到药碗",
                    payoff_plan="执法堂对质时成为关键证据",
                    plant_unit=1,
                    payoff_unit=2,
                ),
                s.NewForeshadowing(
                    description="考核场地里有一座不该存在的聚灵阵",
                    span="中",
                    plant_plan="报名时陆远看见阵纹",
                    payoff_plan="第二卷发现那是收取寿元的阵法",
                    plant_unit=4,
                    payoff_unit=0,
                    payoff_volume=2,
                ),
            ],
            remark=remark,
        )
    count = int(_match(r"必须等于本卷预计的 (\d+) 章", user) or 30)
    n = max(3, round(count / 10))
    direction = _match(r"【这一稿的方向：(.+?)】", user)
    shift = next((i for i, d in enumerate(DIRECTIONS) if d[0] == direction), 0)
    units = []
    for i in range(n):
        name, goal, conflict, climax, outcome, trope, resolution = UNIT_TEMPLATES[(i + shift) % len(UNIT_TEMPLATES)]
        units.append(
            s.PlotUnitDraft(
                index=i + 1,
                title=f"{name}·其{i + 1}",
                chapter_count=max(3, count // n),
                goal=goal,
                conflict=conflict,
                climax=climax,
                outcome=outcome,
                key_events=["起因", "试探", "冲突升级", "高潮", "收尾与钩子"],
                thread_beats=[s.ThreadStep(thread="主线：青灯与寿元", beat=f"第{volume}卷第{i + 1}段推进")],
                tropes=[trope],
                resolution=resolution,
            )
        )
    remark = (
        f"第{volume}卷按「{direction}」拆成 {n} 段，前面蓄势，最后一段是全卷最大的高潮。"
        if direction
        else f"第{volume}卷我拆成 {n} 段，前面蓄势，最后一段是全卷最大的高潮。"
    )
    if revising:
        units = _revise_units(user, units)
        remark = f"第{volume}卷按意见改好了：给对手补了后手，重复的套路换掉了，漏排的伏笔也排进去了。"
        if "融合建议" in _section(user, "修改要求"):
            units[1].key_events.insert(1, "苏晚晴暗中提醒陆远小心长老")
            remark = f"第{volume}卷以选中的方案为底，把另一份方案里苏晚晴暗中提醒的戏融进了第二段。"
    return s.VolumePlanDraft(
        units=units,
        new_foreshadowings=[
            s.NewForeshadowing(
                description=f"第{volume}卷里一枚来历不明的玉简",
                span="中",
                plant_plan="第一个单元里随手捡到",
                payoff_plan="最后一个单元打开，揭开对手的底牌",
                plant_unit=1,
                payoff_unit=n,
            )
        ],
        remark=remark,
    )


def _directions(user: str = "") -> s.VolumeDirections:
    match = re.search(r"本轮按设置给出\s*(\d+)\s*个不同方向", user)
    count = max(1, min(4, int(match.group(1)))) if match else 3
    choices = DIRECTIONS[:count]
    return s.VolumeDirections(
        directions=[s.VolumeDirection(name=n, idea=idea, difference=diff) for n, idea, diff in choices],
        remark=f"这一卷按设置想了 {count} 种拆法："
        + "、".join(choice[0] for choice in choices)
        + "。各拆一份，请审稿比一比。",
    )


def _judge(user: str) -> s.PitchJudgement:
    pitches = sorted({int(x) for x in re.findall(r"【方案(\d+)：", user)}) or [1]
    table = {
        1: (7, 6, 6, 5, "稳，但套路都是前面用过的"),
        2: (8, 7, 9, 8, "对手之间的博弈最好看"),
        3: (7, 8, 6, 7, "感情线细腻，反派偏弱"),
    }
    scores = []
    for p in pitches:
        cool, weaving, villain, novelty, comment = table.get(p, (6, 6, 6, 6, "中规中矩"))
        scores.append(
            s.PitchScore(pitch=p, cool=cool, weaving=weaving, villain=villain, novelty=novelty, comment=comment)
        )
    winner = 2 if 2 in pitches else pitches[0]
    return s.PitchJudgement(
        scores=scores,
        winner=winner,
        merge="把方案3里苏晚晴暗中提醒陆远的那场戏放进选中方案的第二单元，感情线不断档" if 3 in pitches else "",
        remark=f"方案{winner}赢在反派会算计：长老之间互相下套，陆远在夹缝里翻盘，比单纯打脸好看。",
    )


def _audit() -> s.VolumeAudit:
    # 演示：专项审稿总会挑出一个反派智商的问题，便于看到自动修改一轮
    return s.VolumeAudit(
        verdict="revise",
        checks=[
            s.AuditCheck(aspect="villain", ok=False, comment="第三单元的对手守着账册却不设防，像在等主角来拿"),
            s.AuditCheck(aspect="rhythm", ok=True, comment="小高潮一个接一个，卷末最燃"),
            s.AuditCheck(aspect="foreshadow", ok=True, comment="新伏笔埋收都排进了单元"),
            s.AuditCheck(aspect="repetition", ok=True, comment="和第一卷的套路错开了"),
        ],
        issues=[
            s.AuditIssue(
                aspect="villain",
                unit=3,
                problem="对手明知陆远在查账册，却没有任何防备",
                suggestion="让对手提前布下假账册当诱饵，陆远将计就计",
                severity="medium",
            )
        ],
        remark="整体能打，就是第三单元的对手太好对付了，得给他一手后招。",
    )


def _chapter_plan(user: str) -> s.ChapterPlanDraft:
    count = int(_match(r"这个单元共 (\d+) 章", user) or 5)
    unit_title = _match(r"【本单元】\n单元\d+「(.+?)」", user) or "这一段"
    actions = re.findall(r"(埋下|提醒|回收)(F\d+)", _section(user, "本单元"))
    chapters = []
    for i in range(count):
        step = ["起", "承", "转", "合"][min(3, i * 4 // max(1, count))]
        foreshadow = [s.ForeshadowStep(ref=ref, action=act) for act, ref in actions if i == 0]
        chapters.append(
            s.ChapterOutlineDraft(
                title=f"{unit_title}·{step}{i + 1}",
                goal=f"推进「{unit_title}」的第 {i + 1} 步",
                scenes=["杂役院的清晨，陆远盘算下一步", "与对手的正面试探", "夜里点燃青灯，看见不该看见的东西"],
                conflict="对手先发制人，陆远处处受制",
                cool_point="陆远借寿元信息看穿对方底牌，当场反将一军",
                hook="灯火里，一个本不该出现的人头顶只剩三天寿元",
                characters=["陆远", "苏晚晴"] if i % 2 else ["陆远", "赵乾"],
                foreshadow_actions=foreshadow,
            )
        )
    return s.ChapterPlanDraft(chapters=chapters, remark=f"「{unit_title}」{count} 章：前面蓄势，倒数第二章最燃。")


def _review(user: str) -> s.ChapterReview:
    # 演示：第 2 章初稿退回一次，重写稿通过，便于看到退稿循环
    if "第 2 章" in user and "（重写稿）" not in user:
        return s.ChapterReview(
            verdict="revise",
            highlights=["开头接得自然"],
            issues=[
                s.ChapterIssue(
                    problem="章纲里的爽点没写出来：陆远看穿底牌那一段一笔带过",
                    suggestion="把反将一军的过程写成完整的一场戏",
                    severity="high",
                )
            ],
            remark="这一章最该爽的地方一笔带过了，退回去重写。",
        )
    return s.ChapterReview(
        verdict="pass",
        highlights=["结尾钩子有力", "寿元信息差用得巧"],
        issues=[s.ChapterIssue(problem="中段对话略多", suggestion="可以删掉两三句寒暄", severity="low")],
        remark="能定稿，结尾的钩子让人想点下一章。",
    )


def _digest(user: str) -> s.ChapterDigest:
    title = _match(r"第 \d+ 章《(.+?)》已经定稿", user) or "本章"
    marks = re.findall(r"（伏笔·(埋下|提醒|回收)(F\d+)）", _section(user, "正文"))
    return s.ChapterDigest(
        summary=f"《{title}》：陆远借青灯看穿对手的底牌，当场反将一军；结尾灯火里出现了一个只剩三天寿元的人。",
        character_updates=[s.CharacterUpdate(name="陆远", condition="伤势好转，心事更重")],
        foreshadow_updates=[s.ForeshadowUpdate(ref=ref, action=act) for act, ref in marks],
        remark=f"《{title}》的变化记好了：陆远的状态更新了一条。",
    )


def _critique() -> s.SetupCritique:
    return s.SetupCritique(
        verdict="revise",
        highlights=["寿元信息差的设定和主角性格很搭", "第一卷每个单元都有明确的翻盘点"],
        issues=[
            s.ReviewIssue(
                target="first_volume",
                problem="第二单元「执法堂」8 章只围绕一个案子，中段容易拖",
                suggestion="压缩到 6 章，并在中段加入赵乾的试探",
                severity="medium",
            ),
        ],
        remark="整体能打，但执法堂那段太长了，读者会在第 10 章左右流失。",
    )


def _interview() -> s.InterviewDraft:
    return s.InterviewDraft(
        questions=[
            s.InterviewQuestion(
                question="主角叫什么名字？",
                options=["陆远", "沈青", "顾长生"],
                recommended=0,
            ),
            s.InterviewQuestion(
                question="主角的金手指想要什么样的？",
                options=["能看见别人的寿命，但用一次折自己的寿", "能偷走别人的寿命", "每活一天都能预知一件事"],
                recommended=0,
            ),
            s.InterviewQuestion(
                question="感情线怎么安排？",
                options=["一位女主，慢热", "感情线很淡，专心搞事业", "暂时不定，看剧情发展"],
                recommended=0,
            ),
            s.InterviewQuestion(
                question="结局想要什么感觉？",
                options=["主角赢了，但付出很大代价", "大团圆", "开放式，留点余味"],
                recommended=0,
            ),
        ],
        remark="动笔前先跟你对几件事：主角叫什么、金手指怎么设计、感情线和结局。这几样定了，后面就不会大改。",
    )


def _absorb(user: str) -> s.RevisionTriage:
    """演示：插话里提到人物就改设定，否则留给后面的步骤。"""
    match = re.search(r"【作者刚才的插话】\n(.+?)(\n\n|$)", user, re.S)
    text = match.group(1).strip().lstrip("- ") if match else ""
    if any(word in text for word in ("名字", "叫", "主角", "金手指", "人物")):
        return s.RevisionTriage(
            lore_instructions=f"按作者的插话修改人物：{text}",
            remark=f"收到：{text[:40]}。人物已经定了，我让设定师先改一下，后面的步骤跟着同步。",
        )
    return s.RevisionTriage(remark=f"收到：{text[:40]}。已完成的部分不受影响，后面的步骤直接按你说的写。")


def _triage(user: str) -> s.RevisionTriage:
    feedback = re.search(r"【作者意见】\n(.+?)(\n\n|$)", user, re.S)
    text = feedback.group(1).strip() if feedback else "按审稿意见调整"
    return s.RevisionTriage(
        first_volume_instructions=text, remark=f"作者的意见我看了：{text[:40]}。主要影响第一卷卷纲，我来改。"
    )


def _match(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.S)
    return found.group(1).strip() if found else ""


def _section(text: str, name: str) -> str:
    """取出提示词里【name…】这一段的内容。"""
    found = re.search(rf"【{name}[^】]*】\n(.*?)(?=\n【|\Z)", text, re.S)
    return found.group(1) if found else ""


def _materials(user: str) -> s.ChapterMaterials:
    """演示：章纲点名的人物之外再补上老瞎子；挑出章纲里提到的设定条目和青灯；第 3 章以后回顾一下第 1 章。"""
    outline = _section(user, "本章章纲") + _section(user, "所在剧情单元")
    # 人物名单每行以【姓名】开头，不能用 _section 截
    people = _match(r"【设定库：人物名单[^】]*】\n(.*?)\n\n【", user)
    roster = re.findall(r"^【(.+?)】", people, re.M)
    named = (_match(r"出场人物：(.+)", outline) or "").split("、")
    characters = [n for n in roster if n in named or n == "老瞎子"]
    world = [n for n in re.findall(r"^- \[[^\]]+\] (.+?)：", _section(user, "设定库：设定条目目录"), re.M)]
    world = [n for n in world if n in outline or n == "青灯"]
    index = int(_match(r"马上要写第 (\d+) 章", user) or 1)
    hero = re.search(r"^【陆远】[^\n]*?状态：([^；\n]+)", people, re.M)
    notes = ["陆远每点一次青灯就折一日寿元，不能随手乱用"]
    if hero:
        notes.append(f"陆远此刻：{hero.group(1)}")
    return s.ChapterMaterials(
        characters=characters,
        world=world,
        chapters=[1] if index > 3 else [],
        notes=notes,
        remark="资料备好了：人物、用得上的设定和要回顾的前文都在里面。",
    )


def _recap(user: str) -> s.StoryRecap:
    """演示回顾：按各章摘要（或各单元回顾）串起来。"""
    if "请写一份单元回顾" in user:
        title = _match(r"剧情单元「(.+?)」写完了", user)
        lines = re.findall(r"^第(\d+)章《[^》]*》：(.+)$", _section(user, "这个单元各章的摘要"), re.M)
        first, last = (lines[0][1][:40], lines[-1][1][:40]) if lines else ("", "")
        recap = f"「{title}」共 {len(lines)} 章：{first}……到单元结束时，{last}。留下的悬念：灯火里那个只剩三天寿元的人是谁。"
        return s.StoryRecap(recap=recap, remark=f"「{title}」的单元回顾写好了。")
    volume = _match(r"第 (\d+) 卷《", user)
    units = re.findall(r"^单元(\d+)「(.+?)」", _section(user, "这一卷各单元的回顾"), re.M)
    recap = (
        f"第{volume}卷经历了"
        + "、".join(f"「{t}」" for _, t in units)
        + "几段，陆远从杂役一路走进外门，青灯的秘密仍然只有他自己知道。"
    )
    return s.StoryRecap(recap=recap, remark=f"第{volume}卷的卷回顾写好了，后面拆卷纲时会带上。")


async def respond(schema: type[BaseModel], system: str, user: str) -> BaseModel:
    await asyncio.sleep(DELAY_S)
    handlers = {
        s.BookConcept: lambda: _concept(user),
        s.LoreDraft: _lore,
        s.StorySpine: _spine,
        s.ThreadsDraft: _threads,
        s.OutlineDraft: _outline,
        s.VolumePlanDraft: lambda: _volume_plan(user),
        s.VolumeDirections: lambda: _directions(user),
        s.PitchJudgement: lambda: _judge(user),
        s.VolumeAudit: _audit,
        s.SetupCritique: _critique,
        s.InterviewDraft: _interview,
        s.RevisionTriage: lambda: _absorb(user) if "【作者刚才的插话】" in user else _triage(user),
        s.ChapterPlanDraft: lambda: _chapter_plan(user),
        s.ChapterReview: lambda: _review(user),
        s.ConsistencyReport: lambda: s.ConsistencyReport(issues=[], remark="对过设定库了，没有矛盾。"),
        s.ChapterDigest: lambda: _digest(user),
        s.ChapterMaterials: lambda: _materials(user),
        s.StoryRecap: lambda: _recap(user),
    }
    if schema not in handlers:
        raise NotImplementedError(f"演示模式暂不支持 {schema.__name__}")
    return handlers[schema]()


FILLER = [
    "风从寒原上吹下来，陆远把手缩进袖子里，指节冻得发白。",
    "院子里的积雪被踩得发黑，远处传来执事的吆喝声，一声比一声近。",
    "他把青灯藏在怀里，灯身贴着胸口，竟有一丝若有若无的暖意。",
    "对面的人笑了笑，那笑意却没有到眼睛里。陆远心里有数，脸上却装得更怯了几分。",
    "灯火一跳，那人头顶的数字又少了一截。陆远垂下眼，把这个数字记在心里。",
    "他想起老瞎子说过的话：看得见的东西未必是真的，看不见的才要命。",
    "有人在背后窃窃私语，声音压得很低，却刚好能让他听见。",
    "陆远在心里把每一步都过了一遍，像猎户在雪地里辨认兽迹。",
    "檐下的冰棱滴着水，一滴，又一滴，像是谁在暗处数着时辰。",
    "他没有急着开口，只是慢慢把袖口理平，等对方先沉不住气。",
]
FORESHADOW_LINES = {
    "埋下": "他没有多想，只是把这件事压在了心底。",
    "提醒": "这件事他一直没忘，此刻又想了起来。",
    "回收": "直到这一刻，他才明白当初那一幕是什么意思。",
}


def _filler(start: int, size: int) -> list[str]:
    """演示用的填充段落，凑够字数。"""
    paragraphs, total, i = [], 0, start
    while total < size:
        paragraph = "".join(FILLER[(i + k) % len(FILLER)] for k in range(3))
        paragraphs.append(paragraph)
        total += len(paragraph)
        i += 1
    return paragraphs


def _chapter_text(user: str) -> str:
    """演示正文：按章纲把场景、爽点和钩子串起来，写出本章要处理的伏笔并标出动作，供设定师「提取」。

    为了演示写完后的检查：第 4 章初稿故意写短（会被要求接着写），第 5 章初稿用总结式结尾（会被要求改结尾）。
    """
    outline = _section(user, "本章章纲")
    index = int(_match(r"请写第 (\d+) 章", user) or 0)
    title = _match(r"请写第 \d+ 章《(.+?)》", user)
    scenes = re.findall(r"^\d+\. (.+)$", outline, re.M)
    cool = _match(r"爽点：([^\n]+)", outline)
    hook = _hook(user)
    target = int(_match(r"字数约 (\d+) 字", user) or 3000)
    rewrite = "【上一稿】" in user
    items = re.findall(r"^- (埋下|提醒|回收)(F\d+)［[^］]*］([^（\n]+)", _section(user, "本章要处理的伏笔"), re.M)
    if not items:
        items = [(act, ref, "") for act, ref in re.findall(r"(埋下|提醒|回收)(F\d+)", outline)]
    author = _match(r"- \[作者\] ([^\n]+)", _section(user, "修改要求"))
    head = [f"（演示模式{'·重写稿' if rewrite else ''}）{title}。" + ("（重写稿）" if rewrite else "")]
    if author:
        head.append(f"（按作者的意见改：{author}）")
    head += [f"{scene}。{FILLER[i % len(FILLER)]}" for i, scene in enumerate(scenes)]
    head.append(f"{cool}。那一刻，周围的人都没反应过来，只有他自己知道，这一步他已经算了很久。")
    head += [f"{desc.strip() or '那件旧事'}——{FORESHADOW_LINES[act]}（伏笔·{act}{ref}）" for act, ref, desc in items]
    short = index == 4 and not rewrite
    goal = int(target * (0.35 if short else 0.85)) - sum(len(p) for p in head)
    paragraphs = head + _filler(index, goal)
    if not short:
        paragraphs.append(f"{hook}。")
    if index == 5 and not rewrite:
        paragraphs.append("他知道，一切才刚刚开始。")
    return "\n\n".join(paragraphs)


def _continuation(user: str) -> str:
    """演示续写：补足字数，最后停在章纲的钩子上。"""
    missing = int(_match(r"补足约 (\d+) 字", user) or 800)
    hook = _hook(user)
    return "\n\n".join([*_filler(7, missing - len(hook)), f"{hook}。"])


def _new_ending(user: str) -> str:
    return f"话音未落，院门外忽然传来一声闷响，有人重重地摔在了雪地里。\n\n{_hook(user)}。"


def _hook(user: str) -> str:
    """章纲里的结尾钩子（只取那一行）。"""
    return _match(r"结尾钩子：([^\n]+)", _section(user, "本章章纲"))


async def stream_text(system: str, user: str) -> AsyncIterator[str]:
    if "请接着往下写" in user:
        text = _continuation(user)
    elif "请只重写结尾" in user:
        text = _new_ending(user)
    elif "【本章章纲】" in user:
        text = _chapter_text(user)
    else:
        text = (
            "（演示模式）夜里的杂役院很静，陆远捂着肋下的伤，借着月光看那盏旧灯。灯芯是青色的，像一截还没长开的竹子。"
        )
    for i in range(0, len(text), 40):
        await asyncio.sleep(DELAY_S / 20)
        yield text[i : i + 40]
