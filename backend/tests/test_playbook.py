"""题材打法库：按类型和标签挑打法、各环节取用的内容、套路台账与程序检查（套路超限、连续使用、伏笔漏排）。"""

from app.agents import playbook as pb
from app.agents.planning import schedule_issues

HAREM = {"genre": "玄幻·东方玄幻", "tags": ["后宫", "升级流"]}


def unit(index, tropes=(), resolution="", volume=2, title=""):
    return {
        "volume": volume,
        "index": index,
        "title": title or f"单元{index}",
        "tropes": list(tropes),
        "resolution": resolution,
    }


def problems(issues):
    return [i["problem"] for i in issues]


def test_pick_by_genre_and_tags():
    assert pb.pick(HAREM).key == "harem_xuanhuan"
    assert pb.pick({"genre": "仙侠", "tags": ["爽文"]}).key == "harem_xuanhuan"
    assert pb.pick({"genre": "玄幻·修仙", "tags": ["凡人流", "慢热成长"]}).key == "general"  # 不是爽文、后宫
    assert pb.pick({"genre": "都市·重生", "tags": ["后宫"]}).key == "general"  # 不是玄幻
    assert pb.pick(None).key == "general"


def test_limits_are_parsed_from_markdown():
    harem = pb.load("harem_xuanhuan")
    assert harem.name == "后宫玄幻爽文"
    assert harem.tropes["退婚打脸"].book == 1 and harem.tropes["拍卖会"].book == 3
    assert harem.tropes["女主登场"].book is None  # 每位女主一次，不设全书上限
    assert {"扮猪吃虎", "秘境探险", "宗门大比", "修罗场"} <= set(harem.tropes)
    assert harem.resolutions["算计设局"] == pb.Limit(streak=2)
    assert harem.resolutions["越级硬拼"].volume == 2
    assert harem.resolutions["双修解困"].book == 1 and harem.resolutions["长辈出手"].book == 2
    general = pb.load("general")
    assert general.tropes and general.resolutions and general.name == "通用"


def test_each_stage_gets_its_own_sections():
    harem = pb.load("harem_xuanhuan")
    threads = harem.text("threads")
    assert threads.startswith("【题材打法：后宫玄幻爽文")
    assert "女主登场节奏" in threads and "救命之恩、双修疗伤全书各最多用一次" in threads
    assert "### 拍卖会" not in threads and "◆ 套路库" not in threads
    volume = harem.text("volume")
    assert "◆ 套路库" in volume and "◆ 破局手法" in volume and "欲扬先抑" in volume
    # 章纲只带本单元用到的套路，模型写的名称也能对上
    chapters = harem.text("chapters", tropes=["拍卖会风波", "扮猪吃虎"])
    assert "拍卖会（全书最多 3 次）" in chapters and "扮猪吃虎（全书最多 6 次）" in chapters
    assert "秘境探险" not in chapters
    assert "◆ 套路库" not in harem.text("chapters", tropes=[])
    # 审稿只看上限一览，不看每个套路的写法
    review = harem.text("review")
    assert "退婚打脸（全书最多 1 次" in review and "节拍：当众退婚" not in review


def test_usage_text_counts_and_flags_used_up():
    harem = pb.load("harem_xuanhuan")
    assert "还没用过" in pb.usage_text(harem, [])
    prior = [
        unit(1, ["退婚打脸"], "算计设局", volume=1),
        unit(2, ["拍卖会风波"], "底牌显露", volume=1),
        unit(3, ["拍卖会"], "临阵突破", volume=1),
    ]
    text = pb.usage_text(harem, prior)
    assert "退婚打脸 1/1 次（已用完，不能再用）" in text
    assert "拍卖会 2/3 次" in text  # 「拍卖会风波」也算拍卖会
    assert "临阵突破 1/4 次" in text and "算计设局 1 次" in text
    assert "第1卷单元3" in text and "第1卷单元1" not in text  # 只列最近两个单元


def test_repetition_issues():
    harem = pb.load("harem_xuanhuan")
    prior = [unit(1, ["退婚打脸"], "算计设局", volume=1), unit(2, ["秘境探险"], "底牌显露", volume=1)]
    plan = [
        unit(1, ["秘境探险"], "底牌显露"),  # 接着上一卷最后一个单元：套路、破局手法都连着用了
        unit(2, ["退婚打脸"], "越级硬拼"),  # 退婚打脸全书只能一次
        unit(3, ["拍卖会"], "越级硬拼"),
        unit(4, ["宗门大比"], "越级硬拼"),  # 越级硬拼每卷最多两次
        unit(5, ["修罗场"], "算计设局"),
        unit(6, ["扮猪吃虎"], "算计设局"),  # 算计设局可以连着两个单元
        unit(7, ["拍卖会"], "算计设局"),  # 第三个就不行了
    ]
    issues = pb.repetition_issues(harem, prior, plan)
    found = problems(issues)
    assert "第1单元和上一个单元的核心套路都是「秘境探险」" in found
    assert "破局手法「底牌显露」连着用了 2 个单元" in found
    assert "套路「退婚打脸」全书最多用 1 次，算上这一卷已经用到 2 次" in found
    assert "破局手法「越级硬拼」每卷最多用 2 次，这一卷用了 3 次" in found
    assert "破局手法「越级硬拼」连着用了 2 个单元" in found
    assert "破局手法「算计设局」连着用了 3 个单元" in found
    assert not any("「算计设局」连着用了 2" in p for p in found)
    assert {i["aspect"] for i in issues} == {"repetition"}
    by_problem = {i["problem"]: i for i in issues}
    assert by_problem["套路「退婚打脸」全书最多用 1 次，算上这一卷已经用到 2 次"]["severity"] == "high"
    assert by_problem["套路「退婚打脸」全书最多用 1 次，算上这一卷已经用到 2 次"]["unit"] == 2
    # 换着用就没有问题
    clean = [unit(1, ["拍卖会"], "借势借力"), unit(2, ["扮猪吃虎"], "算计设局"), unit(3, ["宗门大比"], "底牌显露")]
    assert pb.repetition_issues(harem, prior, clean) == []


def test_schedule_issues():
    ledger = [
        {"seq": 1, "description": "小指", "status": "planned", "plant_volume": 2, "payoff_volume": 3},
        {"seq": 2, "description": "宗主寿元", "status": "planted", "plant_volume": 1, "payoff_volume": 2},
        {"seq": 3, "description": "已经回收", "status": "resolved", "plant_volume": 1, "payoff_volume": 2},
        {"seq": 4, "description": "没埋过的旧伏笔", "status": "planned", "plant_volume": 1, "payoff_volume": 2},
    ]
    units = [{"index": 1, "foreshadow_actions": []}, {"index": 2, "foreshadow_actions": []}]
    fresh = [
        {"description": "玉简", "plant_unit": 2, "payoff_unit": 1},
        {"description": "阵纹", "plant_unit": 5, "payoff_unit": 0},
    ]
    found = problems(schedule_issues(units, fresh, ledger, 2))
    assert found == [
        "F1「小指」计划在本卷埋下，卷纲里没有安排",
        "F2「宗主寿元」计划在本卷回收，卷纲里没有安排",
        "新伏笔「玉简」回收（第1单元）比埋下（第2单元）还早",
        "新伏笔「阵纹」埋在第5单元，本卷只有 2 个单元",
    ]
    units[0]["foreshadow_actions"] = [{"ref": "F1", "action": "埋下"}]
    units[1]["foreshadow_actions"] = [{"ref": "F2", "action": "回收"}]
    assert schedule_issues(units, [], ledger, 2) == []
