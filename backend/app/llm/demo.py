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


def _next_segment(user: str = "") -> s.NextArcDraft:
    """按实际篇幅栏选终点；仅旧书的明确提示允许推底牌。"""
    length = _section(user, "篇幅").split("\n\n", 1)[0]
    ending = re.search(r"节点 (\d+)「([^」]+)」· 结局", _section(user, "大纲"))
    following = re.search(r"节点 (\d+)「天风国篇」", _section(user, "大纲"))
    number = int(_match(r"第 (\d+) 篇", _section(user, "上一篇")) or 1) + 1
    known = _section(user, "人物当前状态")
    newcomer = "叶清瑶" if "叶清瑶" not in known else f"青云执事{number}"
    text = (
        "楚风带着家族大比的名额进入天风国，想在青云宗大比前找齐修复丹田的灵药，并查出前世背叛者留下的线索。"
        "青云宗长老一派要夺走轮回镜，先借外门考核封掉他的药材渠道，还让柳如烟当众质疑他的资格。"
        "楚风不急着暴露全部实力，先凭帝尊眼界辨出废丹里的药性，与负责药园的叶清瑶结盟，以丹道换取修炼资源。"
        "读者等着他在宗门大比上击败被长老扶持的天才，让轻视楚家的人亲口认输。"
        "收尾时他以同境反杀和药园账册翻盘，发现长老身上的禁制与前世帝骨上的痕迹相同；镜灵只认出这道印记，不说完整来历。"
        "楚风从被宗门拒之门外的少年，走到能向核心长老讨一个公道的弟子，追求也从护住家人推进到追查前世之死。"
    )
    feedback = _section(user, "修改要求")
    changed = _match(r"一段话改成[：: ]*([^\n]+)", feedback)
    if changed:
        text = changed
    plan = s.NextArcDraft(
        title="天风国篇" if number == 2 else f"青云追查篇{number}",
        text=text,
        end=s.EndNodeDraft(
            ref=int(ending[1]) if "只够一篇" in length and ending else int(following[1]) if following else 0,
            title=ending[2] if "只够一篇" in length and ending else "青云宗大比",
            event="楚风在青云宗大比当众击败长老扶持的天才，公开药园账册，夺回被扣的灵药和名额，逼迫长老承认禁制的来历。",
        ),
        fill_entries=[
            s.FillEntry(
                name="天风国",
                content="天风国由皇室与青云宗分掌权力。宗门大比决定修炼资源的归属，楚风从外门新人起步，能在药园找到修复丹田的药，也会碰到前世旧敌留下的暗线。",
            )
        ],
        new_entries=[
            s.EntryDraft(
                category="势力划分",
                name="青云宗",
                status="现在要定",
                one_line="掌握天风国修炼名额的宗门。",
                content="宗门由长老会掌管，药园与内门争夺修炼资源，长老一派借大比把持名额。",
            )
        ],
        new_characters=[
            s.CharacterCardDraft(
                name=newcomer,
                role_type="班底",
                status="现在要定",
                one_line="负责药园的年轻丹师，愿意以灵药换真相。",
                background="青云宗药园弟子。",
                personality="谨慎却护短，说话直接。",
                goal="查清药园账目并护住同门",
                abilities="识药与炼丹",
            )
        ],
        secret="青灯里的残火来自被寿元交易夺走的人，灯主是当年逃过交易的守约者。"
        if "【这本书还没有底牌】" in user
        else "",
        decisions=[
            s.AuthorChoice(
                topic="宗门大比",
                chosen="先炼丹取证再上擂台",
                alternatives=["先上擂台逼长老交账"],
                why="先让对手赢一次，翻盘才有分量",
            )
        ],
        remark="先接住上一篇的线索，让天风国的宗门大比成为下一篇的高潮。",
    )
    choice = _match(r"把「宗门大比」改成「([^」]+)」", feedback)
    if choice:
        plan.decisions[0].chosen = choice
    if "测试篇提醒" in user and not feedback:
        plan.text = "楚风进入青云宗。"
    return plan


def _segment_volumes(user: str = "") -> s.SegmentVolumesDraft:
    known = [name for name, _ in terms()]
    result = s.SegmentVolumesDraft(
        volumes=[
            s.VolumeDraft(
                index=i,
                title="杂役" if i == 1 else "外门考核",
                stage="玄冥宗杂役院与考核场",
                summary="陆远循寿元异常查药碗、夺回报名资格" if i == 1 else "携证据参加考核，揭穿赵乾的陷阱",
                want="拿到报名资格与药碗证据，为考核翻盘铺路" if i == 1 else "在外门考核当众拆穿赵乾并夺得名额",
                pressure="陆远被栽赃并遭取消报名资格" if i == 1 else "赵乾控制考核名单与证人，盟友也被威胁",
                goal="取得报名资格和可追查的账册" if i == 1 else "进入外门，拿到旧档入口",
                climax="当众举证保住报名资格" if i == 1 else "考核终场揭穿寿元交易",
                antagonist="赵乾要垄断名额，先取消陆远报名资格",
                power_range="炼气一层到三层，学会比对寿元异常",
                chapter_count=31 if i == 1 else 30,
                target_node=2,
                reaches_node=i == 2,
                editor_note="卷末为这一篇的终点再铺一层条件。",
                techniques=known[3:5],
            )
            for i in (1, 2)
        ],
        threads=[
            s.ThreadDraft(
                name=name,
                kind=kind,
                characters=people,
                summary=line,
                beats=[s.ThreadBeat(volume=1, beat=first), s.ThreadBeat(volume=2, beat=second)],
            )
            for name, kind, people, line, first, second in [
                (
                    "主线：青灯与寿元",
                    "主线",
                    ["陆远", "赵乾"],
                    "循寿元异常查清父母旧事，远处写到再定",
                    "借青灯取证并保住名额",
                    "揭穿考核交易，拿到旧档入口",
                ),
                (
                    "感情线：苏晚晴",
                    "感情线",
                    ["陆远", "苏晚晴"],
                    "从怀疑到并肩追查",
                    "执法堂互相试探",
                    "考核时公开作证",
                ),
                (
                    "反派线：赵乾",
                    "反派线",
                    ["赵乾", "周长老"],
                    "守住垄断名额和资源的利益",
                    "取消陆远报名资格，先赢一局",
                    "考核设局，被陆远证据反制",
                ),
            ]
        ],
        anchors=[
            s.NodeAnchorDraft(
                character=name,
                node=1 if name in {"陆远", "老瞎子"} else 2,
                kind="登场",
                note="在第一篇与主角的目标发生关联",
            )
            for name in ["陆远", "老瞎子", "苏晚晴", "赵乾", "宗主厉沧海", "周长老"]
        ],
        decisions=[
            s.AuthorChoice(
                topic="前期节奏",
                chosen="先查药碗再考核",
                alternatives=["查案与考核交叉"],
                why="两卷走完第一篇，不排远处的卷",
            )
        ],
        remark="第一篇分两卷，31 章加 30 章，每卷都走向外门考核。",
    )
    fixed = re.findall(r"^第 (\d+) 卷「([^」]+)」约 (\d+) 章[^：]*：(.*)$", _section(user, "这一篇已经分好的卷"), re.M)
    start = int(fixed[0][0]) if fixed else int(_match(r"卷号从第 (\d+) 卷开始", user) or 1)
    short = any(mark in user for mark in ("测试短段", "测试短篇", "测试收尾"))
    if fixed:
        result.volumes = [result.volumes[i % len(result.volumes)].model_copy(deep=True) for i in range(len(fixed))]
        result.decisions = []
    elif short:
        result.volumes = result.volumes[:1]
        result.volumes[0].chapter_count = 6
    end_index = int(_match(r"终点：节点 (\d+)", user) or 2)
    for i, volume in enumerate(result.volumes):
        volume.index = start + i
        volume.target_node = end_index
        volume.reaches_node = i == len(result.volumes) - 1
        if start > 1:
            volume.title = "药园取证" if i == 0 else "青云大比"
            volume.stage = "天风国青云宗"
            volume.summary = "楚风以炼丹换取资源，联合药园弟子查清账目，在宗门大比上击败长老扶持的天才。"
        if fixed:
            volume.index, volume.title, volume.chapter_count, volume.summary = (
                int(fixed[i][0]),
                fixed[i][1],
                int(fixed[i][2]),
                fixed[i][3],
            )
    for thread in result.threads:
        thread.beats = [
            s.ThreadBeat(volume=start + i, beat=thread.beats[i % len(thread.beats)].beat)
            for i in range(len(result.volumes))
        ]
    names = re.findall(r"角色卡片 · ([^\n]+)", user)
    if not names:
        names = re.findall(r"^【([^】]+)】", _section(user, "人物当前状态"), re.M)
    if names:
        result.anchors = [
            s.NodeAnchorDraft(character=name, node=end_index, kind="登场", note="在这一篇与主角的目标发生关联")
            for name in dict.fromkeys(names)
        ]
    result.wait = s.ExpectationDraft(
        description="主角要在大比上击败对手并公开证据",
        plant_plan="对手当众放话，主角立下应战约定",
        payoff_plan="不只赢下比试，也让幕后操纵名额的人付出代价",
        plant_volume=start,
        payoff_volume=result.volumes[-1].index,
        node=end_index,
    )
    past = re.search(r"往事与秘密 · ([^\n]+)", user)
    entry = past[1] if past and past[1] != "底牌" else ("前世之死" if "前世之死" in user else "")
    existing = _section(user, "信息差")
    result.secrets = [
        s.ArcSecretDraft(
            title=f"大比暗线{start}",
            truth="药园账册藏着被篡改的名额，主角能用它反制对手。",
            knowers=[names[0]] if names else [],
            reader_knows="部分",
            reveal_plan="在终点公开账册",
            node=end_index,
            entry=entry,
        ),
        s.ArcSecretDraft(
            title=f"旧敌印记{start}",
            truth="对手身上的禁制与旧案证据上的印记相同，来历仍未查明。",
            knowers=[],
            reader_knows="不知道",
            reveal_plan="大比交锋时显出印记",
            node=end_index,
        ),
    ]
    result.secrets = [secret for secret in result.secrets if secret.title not in existing]
    result.remark = f"从第 {start} 卷接着分卷，排好这一篇的线索、人物出场、读者期待和信息差。"

    if "测试提醒" in user:
        result.volumes[0].want = ""
    return result


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
        thread_beats=[s.ThreadStep(thread="主线：青灯与寿元", beat="老瞎子留下与父母旧案有关的半句遗言")],
        foreshadow_actions=[s.ForeshadowStep(ref="F3", action="埋下", detail="遗言只说了半句")],
        tropes=["身份揭晓"],
        resolution="借势借力",
    ),
    s.PlotUnitDraft(
        index=4,
        title="夺回报名资格",
        chapter_count=10,
        goal="追回被赵乾取消的外门考核报名资格",
        conflict="赵乾把持名单，周长老拒绝受理证据",
        climax="陆远借公示规矩当众举证，逼对方归还报名资格",
        outcome="陆远拿回资格和一角账册，真正的外门考核在下一卷开始",
        key_events=["报名被拒", "找到名单疑点", "当众举证", "追回资格"],
        thread_beats=[s.ThreadStep(thread="反派线：赵乾", beat="赵乾先取消资格，又被迫接受陆远报名")],
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
            s.ForeshadowStep(ref=ref, action=act) for act, ref in re.findall(r"(埋下|提醒|回收)([FE]\d+)", body)
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
                thread_beats=[s.ThreadStep(thread="主线：青灯与寿元", beat=f"第{volume}卷第{i + 1}单元推进")],
                tropes=[trope],
                resolution=resolution,
            )
        )
    remark = (
        f"第{volume}卷按「{direction}」拆成 {n} 个单元，前面蓄势，最后一个单元是全卷最大的高潮。"
        if direction
        else f"第{volume}卷我拆成 {n} 个单元，前面蓄势，最后一个单元是全卷最大的高潮。"
    )
    if revising:
        units = _revise_units(user, units)
        remark = f"第{volume}卷按意见改好了：给对手补了后手，重复的套路换掉了，漏排的伏笔也排进去了。"
        if "融合建议" in _section(user, "修改要求"):
            units[1].key_events.insert(1, "苏晚晴暗中提醒陆远小心长老")
            remark = f"第{volume}卷以选中的方案为底，把另一份方案里苏晚晴暗中提醒的戏融进了第二个单元。"
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
    if any(mark in user for mark in ("测试短段", "测试短篇", "测试收尾")):
        plan.units = plan.units[:2]
        for unit in plan.units:
            unit.chapter_count = 3
        plan.new_foreshadowings = [f for f in plan.new_foreshadowings if f.plant_unit <= 2]
        for item in plan.new_foreshadowings:
            item.payoff_unit = min(item.payoff_unit, 2)
        plan.remark = f"第{volume}卷两个单元各三章，共六章，卷末完成这一篇的高潮。"
    fixed = re.findall(r"^单元 (\d+)「([^」]+)」(\d+) 章[^：]*：(.*)$", _section(user, "这一卷已经拆好的单元"), re.M)
    if fixed:
        plan.units = [plan.units[i % len(plan.units)].model_copy(deep=True) for i in range(len(fixed))]
        for unit, (index, title, count, summary) in zip(plan.units, fixed, strict=True):
            unit.index, unit.title, unit.chapter_count, unit.summary = int(index), title, int(count), summary
        plan.new_foreshadowings = [item for item in plan.new_foreshadowings if item.plant_unit <= len(fixed)]
        for item in plan.new_foreshadowings:
            item.payoff_unit = min(item.payoff_unit, len(fixed))
    plan.want = (
        "拿到报名资格与药碗证据，为外门考核翻盘铺路" if volume == 1 else "完成本卷取证与反击，为这一篇终点创造条件"
    )
    plan.pressure = "陆远遭栽赃并被取消报名资格" if volume == 1 else "盟友被迫退场，主角必须独自守住证据"
    known = [name for name, _ in terms()]
    expectations = dict(re.findall(r"^- (E\d+)［([^］]*)］", _section(user, "伏笔与期待台账") or user, re.M))
    secrets = re.findall(r"^- (S\d+)「", user, re.M)
    valid_refs = set(re.findall(r"^- ([FE]\d+)［", _section(user, "伏笔与期待台账") or user, re.M))
    for i, unit in enumerate(plan.units):
        unit.summary = (
            unit.summary or f"{unit.goal}；{unit.conflict}。主角以本事应对：{unit.climax}。最后{unit.outcome}。"
        )
        # 模板示例编号不是台账编号；新伏笔由程序分配后补排，避免 F1 与新书 E1 混用。
        unit.foreshadow_actions = [action for action in unit.foreshadow_actions if action.ref in valid_refs]
        unit.loop = "发现寿元异常，冒险搜证，以信息差翻盘，追回父母旧案的一条线索。"
        unit.editor_note = "先让读者看到主角的目标，再把对手的阻力变成一次有代价的翻盘。"
        unit.techniques = known[3:5]
        for ref, metadata in expectations.items():
            if "已兑现" in metadata or "放弃" in metadata:
                continue
            plant = _match(r"第(\d+)卷立", metadata) == str(volume)
            payoff = _match(r"第(\d+)卷兑现", metadata) == str(volume)
            action = ""
            if i == 0 and plant and "未立" in metadata:
                action = "埋下"
            elif payoff and i == len(plan.units) - 1:
                action = "回收"
            elif "已立" in metadata or plant:
                action = "提醒"
            if action and not any(step.ref == ref and step.action == action for step in unit.foreshadow_actions):
                unit.foreshadow_actions.append(
                    s.ForeshadowStep(ref=ref, action=action, detail="把当众立下的约定和眼前的冲突连起来")
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
    if "测试提醒" in user:
        plan.pressure = ""
    if "测试节点调整" in user:
        plan.node_update = s.NodeUpdate(
            title="顺势破局",
            event="陆远顺着前文已经查明的账册与证据，当众揭穿对手的布局，取得下一阶段的主动权。",
            prerequisite="前文的关键证据已经被陆远掌握，盟友愿意在众人面前作证。",
            consequence="旧对手退场，背后的势力开始正视陆远，主角获得继续追查的入口。",
            reason="前文已经写成循证破局，暂定节点改成当众举证更自然。",
        )
    return plan


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
            s.AuditCheck(aspect="expectation", ok=True, comment="约定在单元间持续提醒，卷末超出预期地兑现"),
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
    unit_title = _match(r"【本单元】\n单元\d+「(.+?)」", user) or "这一篇"
    unit = _section(user, "本单元")
    actions = re.findall(r"(埋下|提醒|回收)([FE]\d+)", unit)
    reveals = [
        s.RevealStep(ref=ref, to=to.strip(), how=how.strip())
        for ref, to, how in re.findall(r"揭晓：(S\d+) 揭给 (.*?)——([^\n]+)", unit)
    ]
    bad_rhythm = "测试节奏" in unit_title
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
                emotion=-2
                if bad_rhythm
                else (2 if i == count - 2 else (1 if i == count - 1 else (-1 if i % 4 == 1 else 0))),
                mood="虐" if bad_rhythm else ["悬", "虐", "爽", "惊", "暖", "燃"][i % 6],
                reveals=reveals if i == count - 2 else [],
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
    marks = re.findall(r"（(?:伏笔|期待)·(埋下|提醒|回收)([FE]\d+)）", _section(user, "正文"))
    reveals = re.findall(r"（揭晓·(S\d+)·([^·）]+)·([^）]+)）", _section(user, "正文"))
    return s.ChapterDigest(
        summary=f"《{title}》：陆远借青灯看穿对手的底牌，当场反将一军；结尾灯火里出现了一个只剩三天寿元的人。",
        character_updates=[
            s.CharacterUpdate(
                name="陆远",
                condition="伤势好转，心事更重",
                want=(
                    "查清师兄的死因"
                    if int(_match(r"第 (\d+) 章", user) or 1) % 6 == 0
                    else "拿到外门考核资格并保护老人"
                )
                if int(_match(r"第 (\d+) 章", user) or 1) % 3 == 0
                else "",
            )
        ],
        foreshadow_updates=[s.ForeshadowUpdate(ref=ref, action=act) for act, ref in marks],
        secret_updates=[
            s.SecretUpdate(ref=ref, learned_by=[] if to in ("读者", "众人") else [to], public=to == "众人", how=how)
            for ref, to, how in reveals
        ],
        new_entries=[
            s.ChapterEntry(
                category="世界与地图",
                name=f"坊市{int(_match(r'第 (\d+) 章', user) or 1)}号药铺",
                one_line="能买到修炼药材的常用铺子。",
                content="铺子掌柜熟悉药材渠道，之后还会与主角交易。",
            )
        ],
        conflicts=["设定库里钱用灵石，正文的坊市却写了金币。"] if "测试冲突" in user else [],
        remark=f"《{title}》的变化记好了：陆远的状态更新了一条。",
    )


def _match(pattern: str, text: str) -> str:
    found = re.search(pattern, text, re.S)
    return found.group(1).strip() if found else ""


def _section(text: str, name: str) -> str:
    """取出提示词里【name…】这一篇的内容。"""
    found = re.search(rf"【{name}[^】]*】\n(.*?)(?=\n【|\Z)", text, re.S)
    return found.group(1) if found else ""


def _book_draft(user: str) -> s.BookDraft:
    """演示：按点子填一版；按意见改时照现在的样子交回，只在简介后面注明改过。"""
    current = _section(user, "新建页上现在的样子")
    if current:
        row = dict(re.findall(r"^(书名|简介|频道|类别|标签|篇幅)：(.*)$", current, re.M))
        keep = {key: "" if value == "（空着）" else value for key, value in row.items()}
        return s.BookDraft(
            title=keep.get("书名", ""),
            blurb=f"{keep.get('简介', '')}（已按意见改过）",
            channel=keep.get("频道") or "男频",
            genre=keep.get("类别", ""),
            tags=[tag for tag in keep.get("标签", "").split("、") if tag],
            target_length=int(re.sub(r"\D", "", keep.get("篇幅", "")) or 200),
            reply="按你的意见改了简介，别的没动。",
        )
    idea = _section(user, "作者的点子").strip() or "一个普通人卷进了不普通的事"
    return s.BookDraft(
        title="寿命簿" if "寿命" in idea else "青灯照夜",
        blurb=f"{idea.rstrip('。')}。他以为自己只是想活下去，直到发现，整座宗门都在等同一天。",
        channel="男频",
        genre="玄幻",
        tags=["苟道", "宗门", "扮猪吃虎"],
        target_length=200,
        reply="按你的点子先填了一版，主打苟着变强。",
    )


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


def _library_current(user: str) -> str:
    match = re.search(r"(?:^|\n)原文：\n(.*?)(?=\n\n【|\Z)", user, re.S)
    return match[1].rstrip("\r") if match and match[1].strip() else "新写法"


def _library_options(user: str) -> s.RewriteOptions:
    current = _library_current(user)
    options = []
    for label in ("稳妥", "大胆", "出格"):
        renamed = [s.Renamed(old="灵海", new="灵渊")] if label == "大胆" and "灵海" in current else []
        text = current.replace("灵海", "灵渊") if renamed else current
        options.append(s.RewriteOption(label=label, text=f"（{label}）{text}", renamed=renamed))
    return s.RewriteOptions(options=options, note="三种写法都备好了，推荐先看最贴近原意的稳妥写法。")


def _library_fill(user: str) -> s.EntryFill:
    """补齐一条：要补的栏目逐栏填演示文字。"""
    labels = [label for label in _match(r"【要补的栏目】\n(.*?)\n", user).split("、") if label]
    values = [s.FieldValue(name=label, value=f"（演示）补上的{label}") for label in labels]
    return s.EntryFill(values=values, note=f"（演示）补了 {len(values)} 栏。")


def _outline_write(user: str, chapter: bool) -> s.OutlineNodeWrite | s.ChapterOutlineWrite:
    """大纲帮写一段：照「要写的那一段」的名字出演示文字。"""
    name = (re.search(r"在看大纲上的(.+?)，想让你", user) or [None, "这一段"])[1]
    if chapter:
        return s.ChapterOutlineWrite(
            title="演示章名", goal=f"（演示）{name}要做成的事", scenes=["（演示）场景一", "（演示）场景二"],
            cool_point="（演示）爽点", hook="（演示）钩子", note="（演示）写了章纲。",
        )
    return s.OutlineNodeWrite(title="演示名字", text=f"（演示）{name}的剧情：起、压、爆、收。", note="（演示）写了一段。")


def _library_draft(user: str) -> s.DraftSet:
    """帮写几条：按提示里的栏目逐栏填演示文字。"""
    category = (re.search(r"「(.+?)」这一类", user) or [None, "设定"])[1]
    fields = _match(r"【这一类的栏目】\n(.*?)\n\n", user)
    count = int(_match(r"【写几条】\n(\d+)", user) or 3)
    labels = [label for line in fields.splitlines() if "：" in line for label in line.split("：", 1)[1].split("、") if label]
    entries = []
    for i in range(1, count + 1):
        if "一级一级往上排" in fields:
            values = [s.FieldValue(name="总说明", value="一级一级往上走，越级要付代价。")]
            levels = [s.LevelDraft(name=f"第{i}套一阶", text="入门"), s.LevelDraft(name=f"第{i}套二阶", text="")]
            entries.append(s.DraftEntry(name=f"演示{category}{i}", values=values, levels=levels))
            continue
        values = [
            s.FieldValue(name=label, value="配角" if label == "定位" else f"（演示）第{i}条的{label}") for label in labels
        ]
        entries.append(s.DraftEntry(name=f"演示{category}{i}", values=values))
    return s.DraftSet(entries=entries, note=f"（演示）写了 {count} 条{category}。")


def _library_gaps(user: str) -> s.GapReport:
    library = _match(r"【设定库目录】\n(.*?)(?=\n\n要求：|\Z)", user)
    categories = []
    if "厉鬼" in library:
        categories.append(
            s.NewCategory(
                name="厉鬼",
                style="卡片",
                fields=["外形", "杀人规律", "怎么应对", "现在在哪"],
                hint="说清厉鬼的外形、杀人规律、怎么应对和现在在哪。",
                why="每只厉鬼都有独立的规则，需要分开记录。",
            )
        )
    return s.GapReport(
        entries=[
            s.NewEntry(
                category="物品与功法",
                name="九叶还魂草",
                status="一句话就好",
                one_line="能救命的珍稀药草，先记下名字和用途。",
                why="后续救人的目标需要一个能找到的具体物品。",
            ),
            s.NewEntry(
                category="角色卡片",
                name="楚雄",
                status="现在要定",
                one_line="与主角争夺资源的对手。",
                fields=[s.FieldValue(name="定位", value="对手")],
                why="眼前的阻力需要落在具体的人身上。",
            ),
        ],
        categories=categories,
        note="建议补一件关键物品和一位对手，先把眼前用得上的设定记清。",
    )


def _library_review(user: str) -> s.LibraryReview:
    library = _match(r"【设定库】\n(.*?)(?=\n【大纲】|\Z)", user)
    issues = [
        s.LibraryIssue(
            kind="好看",
            title="核心设定还可以多一个让人记住的名场面",
            why="把能力与代价放进一次具体选择，读者更容易记住。",
        )
    ]
    # 段落样式的一句话后才是一段话；卡片和阶梯不会被误当成正文。
    for entry in re.split(r"\n\n(?=[^\n]+ · )", library):
        match = re.match(r"[^\n]+ · ([^\n]+)\n一句话：[^\n]*\n(.+)", entry, re.S)
        if not match or not match[2].strip():
            continue
        sentence = re.match(r"[^。！？!?\n]+[。！？!?]?", match[2].strip())
        if sentence:
            quote = sentence[0]
            issues.append(
                s.LibraryIssue(
                    kind="矛盾",
                    title="这句话需要对齐设定",
                    target_name=match[1],
                    quote=quote,
                    fix=quote + "（已改）",
                    why="把这处表述统一，避免后文产生不同理解。",
                )
            )
            break
    return s.LibraryReview(issues=issues, note="查过了，建议先核对具体表述，再补一个能体现设定代价的场面。")


def _library_intent(user: str) -> s.LibraryIntent:
    note = _match(r"【作者的话】\n(.*?)(?=\n\n要求：|\Z)", user).strip()
    if "测试分流出错" in note:
        raise RuntimeError("演示分流出错")
    # 写大纲：「帮我写一下这篇」「把第三卷写一下」
    if any(w in note for w in ("写一下", "写写", "帮我写", "细化", "重写")) and any(
        w in note for w in ("篇", "卷", "章", "单元", "结局", "这一段", "这段", "大纲")
    ):
        target = (re.search(r"第\s*[0-9一二两三四五六七八九十]+\s*[篇卷章]|结局", note) or [None])[0]
        return s.LibraryIntent(
            kind="写大纲", outline_target=target or "正在看的", instruction="", reply="好，这一段我来写。"
        )
    if note.endswith(("？", "?")) or any(word in note for word in ("吗", "为什么", "怎么样", "什么")):
        who = (
            "设定师"
            if any(w in note for w in ("境界", "设定", "在哪", "谁知道"))
            else "写手"
            if any(w in note for w in ("怎么写", "文风", "示范"))
            else "审稿"
            if any(w in note for w in ("毛病", "不好看", "漏洞"))
            else "主编"
        )
        return s.LibraryIntent(kind="提问闲聊", who=who)
    library = _match(r"【设定库目录】\n(.*?)(?=\n【最近的对话】|\Z)", user)
    names = re.findall(r"^- ([^\n（：]+)", library, re.M)
    name = next((name for name in names if name in note), "")
    if not name and "主角" in note:
        name = next(iter(re.findall(r"^- ([^（：\n]+)（主角）", library, re.M)), "")
    if not name and "师父" in note:
        name = next(iter(re.findall(r"^- ([^（：\n]+)（导师）", library, re.M)), "")
    if not name and "境界" in note:
        name = next((name for name in names if "境界" in name), "")
    if name and any(w in note for w in ("改", "换", "重想")):
        return s.LibraryIntent(
            kind="改设定",
            target_name=name,
            part=(
                "名称"
                if "名称" in note or "名字" in note
                else "性格与说话方式"
                if "性格" in note
                else "身世"
                if "师父" in note
                else "一段话"
            ),
            mode="照作者的意思改" if "改成" in note or "变成" in note else "给几个写法",
            instruction=note,
            reply=(
                f"好，已经按你的意思改了「{name}」。"
                if "改成" in note or "变成" in note
                else f"好，我给「{name}」出三种写法，去设定库挑一个。"
            ),
        )
    scope = (
        "只管下一章"
        if "下一章" in note
        else "只管这一卷"
        if "这一卷" in note
        else "只管下一卷"
        if "下一卷" in note
        else "一直有效"
    )
    if not any(
        word in note
        for word in (
            "下一",
            "以后",
            "要",
            "别",
            "不要",
            "改",
            "换",
            "就用",
            "从现在",
            "记下",
            "记住",
            "第一个单元",
            "第三个单元",
        )
    ):
        return s.LibraryIntent(kind="提问闲聊")
    return s.LibraryIntent(kind="写作要求", requirement=note, scope=scope, reply="记下了。")


def _chat_reply(system, user):
    note = _match(r"【作者这次说的】\n(.*?)(?=\n\n要求：|\Z)", user)
    related = _match(r"【和这次的话有关的资料】\n(.*?)(?=\n\n【|\Z)", user)
    names = re.findall(r"^.+? · ([^\n]+)$", related, re.M)
    role = next((r for r in ("主编", "设定师", "写手", "审稿") if r in (system.splitlines() or ["主编"])[0]), "主编")
    return s.ChatReply(reply=f"（演示）{role}回答：{note[:20]}。相关资料里有：{'、'.join(names) or '没有'}。")


def _chat_plan(user):
    recent = _match(r"【最近的对话】\n(.*?)(?=\n\n【|\n\n要求：|\Z)", user)
    library = _match(r"【设定库目录】\n(.*?)(?=\n\n【|\Z)", user)
    entries = library.split("【", 1)[-1] if library else ""
    entries = re.sub(r"角色卡片】.*?(?=【|\Z)", "", entries, flags=re.S)
    target = next(iter(re.findall(r"^- ([^（：\n]+)", entries, re.M)), "世界概况")
    items = [
        s.PlanItem(where="写作要求", change="（演示）开篇两百字内进入压抑处境"),
        s.PlanItem(where="设定库", target=target, part="一句话", change="（演示）改过的一句话"),
        s.PlanItem(
            where="设定库", target="老怪", category="角色卡片", change="（演示）表面是救命恩师，实际想夺舍主角。"
        ),
        s.PlanItem(where="大纲", target="第 1 卷", change="（演示）第 1 卷从夺舍反杀开始。"),
    ]
    has_notes = bool(re.search(r"^作者：", recent, re.M))
    return s.ChatPlan(
        title="（演示）方案",
        summary="（演示）这是根据最近的对话整理的方案。",
        items=items if has_notes else [],
        open_questions=["（演示）老怪临死说了什么"] if has_notes else [],
    )


def _setup_notes(user):
    notes = _match(r"【作者刚才的插话】\n(.*?)(?=\n\n要求：|\n【|\Z)", user)
    parts = {"concept": [], "settings": [], "outline": []}
    for clause in re.split(r"[，；。\n]", notes):
        clause = clause.strip().removeprefix("- ")
        if not clause.strip():
            continue
        matched = False
        for key, words in (
            ("concept", ("故事", "定调", "主线")),
            ("settings", ("改成", "设定", "人物")),
            ("outline", ("大纲", "篇", "卷")),
        ):
            if any(word in clause for word in words):
                parts[key].append(clause)
                matched = True
        if not matched:
            parts["settings"].append(clause)
    return s.SetupNotePlan(
        **{f"{key}_instructions": "；".join(value) for key, value in parts.items()},
        remark="收到，定调、设定库和大纲的意见分别处理。",
    )


def _requirements_tidy(user):
    items = []
    for n, text in re.findall(r"^(\d+)\. (.*?)（[^\n]+；来自[^\n]*）$", user, re.M):
        if text.endswith(("？", "?")):
            items.append(s.TidyItem(index=int(n), action="删掉", reason="这是一句提问，不是要求"))
        elif re.match(r"^对(主编|设定师|写手|审稿)：", text):
            items.append(
                s.TidyItem(index=int(n), action="改写", reason="去掉聊天时的称呼", rewrite=text.split("：", 1)[1])
            )
        else:
            items.append(s.TidyItem(index=int(n), action="保留", reason="这是一条清楚的要求"))
    return s.RequirementsTidy(items=items)


async def respond(schema: type[BaseModel], system: str, user: str) -> BaseModel:
    await asyncio.sleep(DELAY_S)
    from app.llm import demo_setup

    handlers = {
        s.BookDraft: lambda: _book_draft(user),
        s.PitchSet: lambda: demo_setup.pitches(user),
        s.StoryConcept: lambda: demo_setup.concept(user),
        s.LibraryFocus: lambda: demo_setup.focus(user),
        s.LibraryRest: lambda: demo_setup.rest(user),
        s.OutlineDraft: lambda: demo_setup.outline(user),
        s.SetupNotePlan: lambda: _setup_notes(user),
        s.NextArcDraft: lambda: _next_segment(user),
        s.SegmentVolumesDraft: lambda: _segment_volumes(user),
        s.VolumePlanDraft: lambda: _volume_plan(user),
        s.VolumeDirections: lambda: _directions(user),
        s.PitchJudgement: lambda: _judge(user),
        s.VolumeAudit: _audit,
        s.ChapterPlanDraft: lambda: _chapter_plan(user),
        s.ChapterReview: lambda: _review(user),
        s.ConsistencyReport: lambda: s.ConsistencyReport(issues=[], remark="对过设定库了，没有矛盾。"),
        s.ChapterDigest: lambda: _digest(user),
        s.ChapterMaterials: lambda: _materials(user),
        s.StoryRecap: lambda: _recap(user),
        s.RewriteOptions: lambda: _library_options(user),
        s.RewriteOne: lambda: s.RewriteOne(
            text=f"{_library_current(user)}（已按要求修改）", note="已按要求修改这一处。"
        ),
        s.GapReport: lambda: _library_gaps(user),
        s.DraftSet: lambda: _library_draft(user),
        s.EntryFill: lambda: _library_fill(user),
        s.OutlineNodeWrite: lambda: _outline_write(user, False),
        s.ChapterOutlineWrite: lambda: _outline_write(user, True),
        s.LibraryReview: lambda: _library_review(user),
        s.LibraryIntent: lambda: _library_intent(user),
        s.ChatReply: lambda: _chat_reply(system, user),
        s.ChatSummary: lambda: s.ChatSummary(
            summary=f"（演示）之前聊了 {len(re.findall(r'^(?:作者|主编|设定师|写手|审稿)：', _match(r'【要并进去的对话】\n(.*?)(?=\n\n要求：|\Z)', user), re.M))} 条。"
        ),
        s.ChatPlan: lambda: _chat_plan(user),
        s.RequirementsTidy: lambda: _requirements_tidy(user),
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
    items = re.findall(
        r"^- (埋下|立下|提醒|回收|兑现)([FE]\d+)［[^］]*］([^（\n]+)", _section(user, "本章要处理的伏笔"), re.M
    )
    if not items:
        items = [(act, ref, "") for act, ref in re.findall(r"(埋下|提醒|回收)([FE]\d+)", outline)]
    items = [({"立下": "埋下", "兑现": "回收"}.get(act, act), ref, desc) for act, ref, desc in items]
    author = _match(r"- \[作者\] ([^\n]+)", _section(user, "修改要求"))
    head = [f"（演示模式{'·重写稿' if rewrite else ''}）{title}。" + ("（重写稿）" if rewrite else "")]
    head.append(f"他记下了坊市{index}号药铺的门牌，往后补药仍要来这里。")
    if "测试冲突" in user:
        head.append("坊市掌柜说这里用金币结账。（测试冲突）")
    if author:
        head.append(f"（按作者的意见改：{author}）")
    head += [f"{scene}。{FILLER[i % len(FILLER)]}" for i, scene in enumerate(scenes)]
    head.append(f"{cool}。那一刻，周围的人都没反应过来，只有他自己知道，这一步他已经算了很久。")
    head += [
        f"{desc.strip() or '那件旧事'}——{FORESHADOW_LINES[act]}（{'期待' if ref.startswith('E') else '伏笔'}·{act}{ref}）"
        for act, ref, desc in items
    ]
    for ref, to, how in re.findall(r"揭晓：(S\d+) 揭给 (.*?)——([^\n]+)", outline):
        head.append(f"{to}终于得知了真相：{how}。（揭晓·{ref}·{to}·{how}）")
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
