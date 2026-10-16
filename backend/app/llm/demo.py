"""演示模式：不联网，返回内置的示例内容，用于无 API Key 体验全流程和自动化测试。"""

import asyncio
import os
import re
from collections.abc import AsyncIterator

from pydantic import BaseModel

from app.agents import schemas as s
from app.agents.glossary import terms

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
    length = int(_match(r"这本书打算写多长？[—－-]+[^\n]*?(\d+)\s*万", user) or 100)
    # 演示也落实作者换选项的决定，不只回显一份不变的示例。
    feelings = re.findall(r"(?:把)?「感情线」改成[：:]?\s*[「]?([^」\n]+)", user)
    feeling = feelings[-1].strip() if feelings else "并肩查案慢慢靠近"
    cost = "每次点灯消耗一天寿元，必须权衡救人与自保"
    revised_cost = cost in user
    return s.BookConcept(
        title=title,
        alt_titles=alt_titles,
        genre="玄幻·东方玄幻" if harem else "玄幻·修仙",
        tags=["后宫", "爽文", "宗门", "智斗"] if harem else ["凡人流", "宗门", "智斗", "慢热成长"],
        logline=f"{_idea(user)}——杂役弟子陆远捡到一盏能照见他人寿元的青灯，从此在吃人的宗门里步步为营。",
        selling_points=[
            "青灯能看见他人剩余寿元，信息差带来的智斗爽感",
            "杂役翻身，每次突破都用计谋而非奇遇",
            f"宗门内斗与正邪两道的灰色地带；感情线：{feeling}",
        ],
        protagonist_hook=cost if revised_cost else "陆远知道每个人还能活多久，却必须装作什么都不知道",
        tone="冷静克制，带一点黑色幽默，节奏紧凑",
        target_length=length,
        target_volumes=8,
        chapter_words=3000,
        stage_ladder="玄冥宗杂役院 → 外门 → 北境寒原 → 血河总坛 → 宗主峰",
        target_reader="男频，喜欢信息差智斗与代价明确的成长，不喜欢无代价开挂",
        decisions=[
            s.AuthorChoice(
                topic="感情线",
                chosen=feeling,
                alternatives=[x for x in ["并肩查案慢慢靠近", "从欢喜冤家开始", "先有师徒之谊"] if x != feeling][:2],
                why="互相试探能让智斗与感情一起推进",
            )
        ],
        remark="这本书的钩子我定在「看得见寿元的青灯」上，信息差是最稳的爽点，主角靠脑子赢。篇幅先按 100 万字、八卷来规划。",
    )


def _lore(user: str = "") -> s.LoreDraft:
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
            ),
            s.CharacterDraft(
                name="周长老",
                role_type="配角",
                personality="谨慎护短，习惯先留退路",
                background="赵乾的祖父，掌管外门资源",
                goal="保住家族在宗门的地位",
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
        anchors=[
            s.NodeAnchorDraft(character=name, node=number, kind="登场", note="进入故事并和主角的目标发生关联")
            for name, number in [
                ("陆远", 1),
                ("苏晚晴", 2),
                ("赵乾", 2),
                ("老瞎子", 1),
                ("宗主厉沧海", 3),
                ("周长老", 3),
            ]
        ],
        secrets=[
            s.SecretDraft(
                title=title,
                truth=truth,
                knowers=knowers,
                reader_knows=reader,
                reveal_plan="在对应节点通过对质和证据揭开，迫使知情者重新站队",
                node=number,
            )
            for title, truth, knowers, reader, number in [
                ("青灯的持有人", "青灯已经到了陆远手中，点灯能看见他人的寿元", ["陆远"], "知道", 3),
                ("宗主剩余寿元", "厉沧海只剩三年寿元，正在以宗门弟子的寿元准备续命", ["陆远", "宗主厉沧海"], "知道", 7),
                ("苏家灭门真相", "苏晚晴的家族被血河教灭门，留下的账册可以查出幕后交易", ["苏晚晴"], "部分", 5),
                ("赵乾寿元交易", "赵乾私下用败者的寿元与血河教交换修炼资源", ["赵乾"], "不知道", 3),
                ("老人的青灯来历", "老瞎子曾是青灯上一任主人，知道逆转寿元契约的方法", ["老瞎子"], "不知道", 6),
            ]
        ],
        decisions=[
            s.AuthorChoice(
                topic="主要对手",
                chosen="从赵乾查到宗主",
                alternatives=["宗主先以恩人出现"],
                why="反派逐层出现，成长才有分量",
            )
        ],
        remark="主角叫陆远，金手指是一盏能照见寿元的青灯，但每次点燃都要烧掉他自己一天寿命；头号反派是宗主厉沧海。力量体系我设计成「突破要烧寿元」，这样青灯就不只是外挂，而是整个世界的命门。",
    )


def _spine(user: str = "") -> s.StorySpine:
    events = [
        (
            "开篇",
            "寒夜捡灯",
            1,
            "老瞎子把青灯交给受伤的陆远，灯火第一次照见别人的死期",
            "陆远陷入杂役院的欺压",
            "陆远得到危险的信息优势",
        ),
        (
            "节点",
            "外门考核",
            1,
            "陆远借寿元信息拆穿考核陷阱，和苏晚晴合力查明跟班死亡原因",
            "青灯能力已验证，药碗证据已找齐",
            "陆远进入外门，赵乾把他当作真正的对手",
        ),
        (
            "节点",
            "生死擂台",
            2,
            "陆远在生死擂正面击败赵乾，当众留下寿元交易的证据",
            "主角具备迎战实力，赵乾已立下赌约",
            "败者交易暴露，调查走出宗门",
        ),
        (
            "节点",
            "寒原追查",
            3,
            "陆远追到寒原旧村，发现兽潮和寿元契约的联系",
            "盟友建立信任，旧村路线与证人得到保护",
            "父母死亡不再是天灾，主角决定追究责任",
        ),
        (
            "节点",
            "血河潜入",
            4,
            "陆远与苏晚晴潜入血河总坛，抢出灭门交易账册",
            "已掌握换岗规律，能识别伪造的账册",
            "双方结成牢固同盟，幕后交易有了实证",
        ),
        (
            "节点",
            "契约印记",
            5,
            "陆远对照账册发现缺失的小指是幼时被取走寿元的印记",
            "老瞎子的遗言、账册与童年证据已经对上",
            "主角不再只求自保，要阻止更多人被收割",
        ),
        (
            "节点",
            "宗主真相",
            6,
            "陆远揭开宗主的续命计划，联合弟子准备反制寿元大阵",
            "主角有足够盟友与证据，也找到大阵的阵眼",
            "宗门内斗公开化，大典成为最后倒计时",
        ),
        (
            "节点",
            "青灯燃尽",
            7,
            "化神大典上陆远燃尽青灯逆转寿元大阵，厉沧海遭到反噬",
            "苏晚晴能守住阵眼，陆远明白青灯真正代价",
            "宗主坐化，寿元交易终结，陆远失去青灯",
        ),
        (
            "结局",
            "重建家园",
            8,
            "陆远与苏晚晴归还受害者的寿元，在寒原重建杂役院",
            "大阵已被摧毁，受害者与剩余资源妥善安置",
            "主角失去外挂却拥有可以共同生活的家园",
        ),
    ]
    current = _section(user, "当前主线骨架") or _section(user, "当前关键节点")
    refs = {title: int(index) for index, title in re.findall(r"节点\s+(\d+)「([^」]+)」", current)}
    known = [name for name, _ in terms()]
    nodes = [
        s.StoryNodeDraft(
            ref=refs.get(title, 0),
            kind=kind,
            title=title,
            volume=volume,
            event=event,
            prerequisite=prerequisite,
            consequence=consequence,
            editor_note="先把主角必须付出的代价摆出来，再让这一节点改变局面。",
            techniques=known[3:5],
        )
        for kind, title, volume, event, prerequisite, consequence in events
    ]
    instruction = _match(r"【修改要求】\n(.*?)(?=\n\n请在当前版本|\n\n要求：|\Z)", user)
    if re.search(r"只改节点\s*\d+", instruction):
        # 卡片定向修改按当前快照回填，不能凭初始九节点重新引入作者已经删掉的节点。
        snapshot = []
        for match in re.finditer(
            r"^节点\s+(\d+)「([^」]*)」([^\n［]*)［(?:铁钉|暂定|留空)(?:｜约第 (\d+) 卷)?］(?:发生：)?([^\n]*)((?:\n  [^\n]*)*)",
            current,
            re.M,
        ):
            index, title, label, volume, event, details = match.groups()
            existing = next((node for node in nodes if node.ref == int(index)), None)
            snapshot.append(
                s.StoryNodeDraft(
                    ref=int(index),
                    kind="开篇" if "开篇" in label else "结局" if "结局" in label else "节点",
                    title=title,
                    volume=int(volume or 1),
                    event=event,
                    prerequisite=_match(r"之前得先有：([^\n]*)", details),
                    consequence=_match(r"之后变成：([^\n]*)", details),
                    editor_note=existing.editor_note if existing else "",
                    techniques=existing.techniques if existing else [],
                )
            )
        if snapshot:
            nodes = snapshot
    revised_pins = _revise_demo_pins(nodes, current, user)
    if "测试提醒" in user:
        nodes[3].prerequisite = ""
    return s.StorySpine(
        core_conflict="陆远想查清父母之死，而宗门高层靠收割寿元续命",
        theme="命数不该被买卖",
        protagonist_arc="从只求自保到愿意保护别人",
        nodes=nodes,
        decisions=[
            s.AuthorChoice(
                topic="故事收束",
                chosen="失去青灯但重建家园",
                alternatives=["保留青灯继续守护"],
                why="让胜利有代价，成长才可信",
            )
        ],
        remark=(
            "演示模式已按本轮点名要求修改节点事件，其他铁钉仍由程序保护。"
            if revised_pins
            else "九个节点从捡灯走到重建家园，铁钉由程序原样保留，其余节点按序号衔接。"
        ),
    )


def _revise_demo_pins(nodes: list[s.StoryNodeDraft], current: str, user: str) -> bool:
    """演示用确定性规则：只把本轮授权节点的「改为／改成」落实到事件，不模拟自然语言理解。"""
    instruction = _match(r"【修改要求】\n(.*?)(?=\n\n请在当前版本|\n\n要求：|\Z)", user)
    allowed = {int(index) for index in re.findall(r"作者要求改动铁钉节点\s*(\d+)", instruction)}
    selected = {int(index) for index in re.findall(r"只改节点\s*(\d+)", instruction)}
    targets = allowed | selected
    changed = False
    for match in re.finditer(
        r"^节点\s+(\d+)「([^」]*)」([^\n［]*)［(铁钉|暂定)(?:｜约第 (\d+) 卷)?］发生：[^\n]*((?:\n  [^\n]*)*)",
        current,
        re.M,
    ):
        index, title, label, status, volume, details = match.groups()
        ref = int(index)
        if ref not in (allowed if status == "铁钉" else targets):
            continue
        event = ""
        for clause in re.split(r"[。；\n]", instruction):
            changes = list(re.finditer(r"改(?:为|成)[：:\s]*", clause))
            # 一句里有多个改动或多个节点时不猜，防止把另一个节点的指令串进来。
            if len(changes) != 1:
                continue
            change = changes[0]
            mentioned = {int(value) for value in re.findall(r"节点\s*(\d+)", clause[: change.start()])}
            if mentioned != {ref} and (mentioned or len(targets) != 1):
                continue
            event = clause[change.end() :].strip()
            if event:
                break
        if not event:
            continue
        existing = next((node for node in nodes if node.ref == ref), None)
        replacement = s.StoryNodeDraft(
            ref=ref,
            kind="开篇" if "开篇" in label else "结局" if "结局" in label else "节点",
            title=title,
            volume=int(volume or 1),
            event=event,
            prerequisite=_match(r"之前得先有：([^\n]*)", details),
            consequence=_match(r"之后变成：([^\n]*)", details),
            editor_note=existing.editor_note if existing else "",
            techniques=existing.techniques if existing else [],
        )
        if existing is None:
            nodes.append(replacement)
        else:
            nodes[nodes.index(existing)] = replacement
        changed = True
    return changed


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


def _outline(user: str = "") -> s.OutlineDraft:
    total = int(_match(r"合计约 (\d+) 章", user) or 333)
    counts = [31, 90, 36, 36, 35, 35, 35, 35]
    if total != sum(counts):
        counts = [max(1, total // 8)] * 8
        counts[-1] += total - sum(counts)
    known = [name for name, _ in terms()]
    nodes = _spine().nodes
    volumes = [
        s.VolumeDraft(
            index=i,
            title=("杂役" if i == 1 else "生死擂" if i == 2 else node.title),
            stage="玄冥宗 → 北境寒原 → 血河总坛 → 宗主峰",
            summary=node.event,
            goal=node.consequence,
            climax=node.event,
            antagonist="赵乾及其背后的宗门长老" if i < 4 else "宗主厉沧海与血河教",
            power_range="修为随着证据与盟友积累逐步提高",
            chapter_count=counts[i - 1],
            target_node=i + 1,
            reaches_node=True,
            editor_note="这卷铺齐下个大事件的条件，再用卷末高潮兑现。",
            techniques=known[3:5],
        )
        for i, node in enumerate(nodes[1:], 1)
    ]
    truths = [
        "陆远左手缺的小指，是幼时被血河教取走寿元的契约印记",
        "宗主只剩三年寿元",
        "老瞎子的半句遗言",
        "药碗上的火漆属于外门库房",
        "苏家的旧账册还有另一半",
    ]
    foreshadowings = [
        s.ForeshadowingDraft(
            description=value,
            span="长",
            plant_plan="用一个看似普通的细节带过",
            payoff_plan="关键证据出现后重新解释这个细节",
            plant_volume=1 if i < 3 else 2,
            payoff_volume=5 if i in (0, 2) else 6 if i == 1 else 4,
            node=6 if i in (0, 2) else 7 if i == 1 else 5,
        )
        for i, value in enumerate(truths)
    ]
    expectations = [
        s.ExpectationDraft(
            description="陆远要在生死擂当众击败赵乾",
            plant_plan="赵乾立下生死擂赌约",
            payoff_plan="不只赢擂台，还拿到寿元交易证据",
            plant_volume=1,
            payoff_volume=2,
            node=3,
        ),
        s.ExpectationDraft(
            description="陆远要查清父母之死，给被害者一个交代",
            plant_plan="主角对着旧信承诺查清真相",
            payoff_plan="不只找到凶手，还终结收割寿元的规则",
            plant_volume=1,
            payoff_volume=7,
            node=8,
        ),
    ]
    return s.OutlineDraft(
        volumes=volumes,
        foreshadowings=foreshadowings,
        expectations=expectations,
        decisions=[
            s.AuthorChoice(
                topic="前期节奏",
                chosen="第一卷短、第二卷展开",
                alternatives=["两卷均衡推进"],
                why="先让主角有一次完整翻身，再加深冲突",
            )
        ],
        remark=f"八卷合计 {total} 章，开篇之后每个节点都由一卷到达，长线伏笔与期待分开编号。",
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


def _base_volume_plan(user: str) -> s.VolumePlanDraft:
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


def _volume_plan(user: str) -> s.VolumePlanDraft:
    plan = _base_volume_plan(user)
    volume = int(_match(r"请为第 (\d+) 卷写「卷纲」", user) or 1)
    known = [name for name, _ in terms()]
    expectations = re.findall(r"^- (E\d+)［", user, re.M)
    secrets = re.findall(r"^- (S\d+)「", user, re.M)
    for i, unit in enumerate(plan.units):
        unit.editor_note = "先让读者看到主角的目标，再把对手的阻力变成一次有代价的翻盘。"
        unit.techniques = known[3:5]
        if expectations:
            unit.foreshadow_actions.append(
                s.ForeshadowStep(
                    ref=expectations[0],
                    action="埋下" if i == 0 else "提醒",
                    detail="把当众立下的约定和眼前的冲突连起来",
                )
            )
        if secrets and i == 1:
            unit.reveals = [
                s.RevealStep(ref=secrets[0], to="苏晚晴", how="陆远以证据解释先前异常，双方因此开始互相信任")
            ]
    plan.new_expectations = [
        s.NewExpectation(
            description=f"第{volume}卷要让对手为轻视陆远付出代价",
            plant_plan="主角当众约定在本卷末拿出证据",
            payoff_plan="不只证实清白，还揭开对手背后的利益链",
            plant_volume=volume,
            payoff_volume=volume,
            plant_unit=1,
            payoff_unit=len(plan.units),
        )
    ]
    return plan


def _book_directions(user: str) -> s.BookDirections:
    techniques = [name for name, _ in terms()]
    variants = [
        (
            "青灯藏锋",
            "杂役少年陆远",
            "看见寿元，每次点灯消耗自己一天寿命",
            "受伤的杂役捡到青灯，发现欺压他的人只剩两天寿元",
            "宗门 → 寒原 → 血河总坛",
            "信息差智斗",
        ),
        (
            "逆命医女",
            "被逐出家门的医女苏青",
            "转移伤势，但必须自己承受一半代价",
            "医馆被封的当天，她救活了本该死去的巡城使",
            "边城医馆 → 王都 → 古战场",
            "救人与身份反转",
        ),
        (
            "寒原契约",
            "被追捕的少年账房程越",
            "能看见契约漏洞，但利用漏洞会失去一段记忆",
            "押送途中发现自己是寿元账册上的抵押品，设局逃走",
            "流亡商队 → 地下市集 → 王庭",
            "冒险与契约博弈",
        ),
    ]
    return s.BookDirections(
        directions=[
            s.BookDirection(
                name=name,
                logline=f"{hero}为了找回自己的命运，与买卖寿元的人周旋",
                protagonist=f"{hero}，处境艰难却不肯放弃判断，表面退让而心里有自己的底线",
                golden_finger=power,
                opening=opening,
                selling_points=[advantage, "每次取胜都有明确代价"],
                stage_ladder=ladder,
                tone="冷静智斗，关键时刻热血",
                reader="男频，爱看靠判断赢下强敌，不喜欢无代价开挂",
                difference=f"这个方向主要靠{advantage}吸引读者",
                editor_note="先给主角一个别人看不见的优势，再用必须付出的代价保住悬念。",
                techniques=techniques[3:5],
            )
            for name, hero, power, opening, ladder, advantage in variants
        ],
        recommended=0,
        remark="我推荐青灯藏锋，信息差与代价能一起推动长篇；另外两个方向分别偏救人和冒险。",
    )


def _node_candidates(user: str) -> s.NodeCandidates:
    slot = _section(user, "要补的位置")
    count = 3 if re.search(r"3\s*个候选", slot) else 1
    index = int(_match(r"节点\s*(\d+)", slot) or 2)
    volume = int(_match(rf"节点\s+{index}「[^\n]*?约第\s*(\d+)\s*卷", user) or 1)
    phrase = _match(r"作者写了一句：「(.+?)」", slot)
    techniques = [name for name, _ in terms()]
    variants = [
        ("筹码交换", "主角用关键证据和对手交换保护盟友的承诺"),
        ("夜探账房", "主角潜入账房取走契约原件，在追捕中暴露一张底牌"),
        ("当众对质", "盟友在众人面前提出证据，使幕后交易第一次被公开质疑"),
    ]
    return s.NodeCandidates(
        nodes=[
            s.StoryNodeDraft(
                kind="节点",
                title=phrase[:10] if phrase else title,
                volume=volume,
                event=phrase or event,
                prerequisite="上一个节点留下的线索已经查明，主角与盟友具备行动条件",
                consequence="对手被迫改变原计划，下一个节点所需的证据和矛盾开始聚齐",
                editor_note="让这个节点既接住前面的变化，又给后面的冲突留下必须解决的事。",
                techniques=techniques[3:5],
            )
            for title, event in variants[:count]
        ],
        remark=f"这个位置给出 {count} 个方案，人物得失和推进方式各有区别。",
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


def _critique(user: str = "") -> s.SetupCritique:
    if _section(user, "第一卷卷纲").strip().startswith("（还没做）"):
        return s.SetupCritique(
            verdict="pass",
            highlights=["关键节点的前提和后果能连起来"],
            issues=[],
            remark="已完成的节点可以交给作者确认，后面的部分等做完再审。",
        )
    cross_piece = []
    # 由验收点子显式开启，日常示例仍保持原审稿；解锁改好后不再重复建议。
    if "跨块审稿演示" in user and "每次点灯消耗一天寿元，必须权衡救人与自保" not in user:
        cross_piece.append(
            s.ReviewIssue(
                target="concept",
                problem="概念的主角钩子还没有写清青灯的代价",
                suggestion="主角钩子补充：每次点灯消耗一天寿元，必须权衡救人与自保",
                severity="medium",
            )
        )
    return s.SetupCritique(
        verdict="revise",
        highlights=["寿元信息差的设定和主角性格很搭", "第一卷每个单元都有明确的翻盘点"],
        issues=[
            *cross_piece,
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


def _author_feedback(user: str, heading: str) -> str:
    """只读本轮意见，保留多段插话，不把模板要求混进作者授权。"""
    match = re.search(rf"【{heading}】\n(.*?)(?=\n\n要求：|\n【|\Z)", user, re.S)
    return match.group(1).strip().lstrip("- ") if match else ""


def _pinned_revision(user: str, text: str) -> s.RevisionTriage | None:
    """演示只识别本轮点名、且当前方案里确实标为铁钉的节点。"""
    snapshot = _match(
        r"【(?:当前方案|已经完成的部分)】\n(.*?)(?=\n【(?:还没做的部分|作者已确认|这本书的写作规矩|作者的要求|作者意见|作者刚才)|\Z)",
        user,
    )
    pinned = {
        int(index) for index in re.findall(r"^节点\s+(\d+)「[^」]*」[^\n［]*［铁钉(?:｜[^］]*)?］", snapshot, re.M)
    }
    overrides = list(dict.fromkeys(int(index) for index in re.findall(r"节点\s*(\d+)", text) if int(index) in pinned))
    if not overrides:
        return None
    locked = _match(r"【作者已确认（锁定）的部分】([^\n]*)", user) or _section(user, "作者已确认（锁定）的部分")
    if "关键节点" in locked:
        return s.RevisionTriage(
            unlock_requests=[s.UnlockRequest(target="spine", reason=f"作者要求调整：{text}")],
            remark="你点名的铁钉节点在已经确认的部分，我先提出解锁请求，等你决定后再改。",
        )
    return s.RevisionTriage(
        spine_instructions="；".join(f"作者要求改动铁钉节点 {index}" for index in overrides) + f"：{text}",
        pinned_overrides=overrides,
        remark="收到，你点名的铁钉节点按这次的意见修改，改完仍是铁钉，其他铁钉保持不变。",
    )


def _absorb(user: str) -> s.RevisionTriage:
    """演示：先处理点名的铁钉，再按人物或后续步骤安排插话。"""
    text = _author_feedback(user, "作者刚才的插话")
    pinned_revision = _pinned_revision(user, text)
    if pinned_revision is not None:
        return pinned_revision
    # format_locked 的块名按产品格式紧接标题，不能用只识别换行正文的 _section。
    locked = _match(r"【作者已确认（锁定）的部分】([^\n]*)", user) or _section(user, "作者已确认（锁定）的部分")
    target = "concept" if any(word in text for word in ("概念", "基调", "方向")) else "lore"
    if locked and ((target == "concept" and "定调" in locked) or (target == "lore" and "人物上轴" in locked)):
        return s.RevisionTriage(
            unlock_requests=[s.UnlockRequest(target=target, reason=f"作者要求调整：{text}")],
            remark="这会影响已经确认的部分，我先提出解锁请求，等你决定后再改。",
        )
    if any(word in text for word in ("名字", "叫", "主角", "金手指", "人物")):
        return s.RevisionTriage(
            lore_instructions=f"按作者的插话修改人物：{text}",
            remark=f"收到：{text[:40]}。人物已经定了，我让设定师先改一下，后面的步骤跟着同步。",
        )
    return s.RevisionTriage(remark=f"收到：{text[:40]}。已完成的部分不受影响，后面的步骤直接按你说的写。")


def _triage(user: str) -> s.RevisionTriage:
    text = _author_feedback(user, "作者意见") or "按审稿意见调整"
    pinned_revision = _pinned_revision(user, text)
    if pinned_revision is not None:
        return pinned_revision
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
        s.BookDirections: lambda: _book_directions(user),
        s.NodeCandidates: lambda: _node_candidates(user),
        s.BookConcept: lambda: _concept(user),
        s.LoreDraft: lambda: _lore(user),
        s.StorySpine: lambda: _spine(user),
        s.ThreadsDraft: _threads,
        s.OutlineDraft: lambda: _outline(user),
        s.VolumePlanDraft: lambda: _volume_plan(user),
        s.VolumeDirections: lambda: _directions(user),
        s.PitchJudgement: lambda: _judge(user),
        s.VolumeAudit: _audit,
        s.SetupCritique: lambda: _critique(user),
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
