"""用几种常见的 TXT 样子试分章规则，看哪里会出错。"""

import sys

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
sys.stdout.reconfigure(encoding="utf-8")

from split_txt import split  # noqa: E402

BODY = "　　" + "他推开门，屋里一片漆黑。远处传来几声狗叫，像是在提醒他什么。" * 12 + "\n"
LONG_BODY = BODY * 2


def chapter(title: str, body: str = LONG_BODY) -> str:
    # 每章正文带上自己的标题，免得假数据每章一模一样
    return f"{title}\n　　（{title}）{body}"


SAMPLES: dict[str, tuple[bytes, dict]] = {}

# 1. 常见的起点式 TXT：书名作者简介、分卷、广告行、请假条、重复的章、番外、完本感言
std = "\n".join(
    [
        "书名：《斗破天穹》",
        "作者：某某某",
        "内容简介：",
        "　　这里是斗气的世界。少年天才一夜之间沦为废物……",
        "　　三十年河东，三十年河西。",
        "",
        "第一卷 陨落的天才",
        chapter("第一章 斗之力，三段"),
        "本章未完，请点击下一页继续阅读》》",
        "天才一秒记住本站地址：www.xxbiquge.com",
        chapter("第二章 斗气大陆"),
        chapter("第三章 客人"),
        chapter("第三章 客人"),  # 盗版重复
        chapter("请假条", "　　今天家里有事，请假一天，明天两更补上。\n"),
        "第二卷 云岚宗",
        chapter("第四章 三年之约"),
        chapter("第五章：休书"),
        chapter("番外 药老的往事"),
        chapter("完本感言", "　　感谢一路陪伴的读者……\n" * 3),
    ]
)
SAMPLES["起点式，有卷、广告、请假、重复、番外、感言"] = (std.encode("utf-8"), {"chapters": 6, "volumes": 2})

# 1b. 章名后面挂求票、拿章号发请假条、正常但很短的一章
beg = "\n".join(
    [
        chapter("第十章 决战（求月票！）"),
        chapter("第十一章 请假条", "　　家里有事，今天请假，明天补上。\n"),
        chapter("第十二章 余波", "　　风停了。" * 40 + "\n"),
        chapter("第十三章 新的开始"),
    ]
)
SAMPLES["章名挂求票、拿章号请假、很短的正常章"] = (beg.encode("utf-8"), {"chapters": 3, "volumes": 0})

# 2. GBK 编码、阿拉伯数字、全角数字、带空格、没有卷
gbk = "\n".join([chapter("第1章 退婚"), chapter("第２章 休书"), chapter("第 3 章 戒指"), chapter("第004章 药老")])
SAMPLES["GBK、数字写法混着、没有卷"] = (gbk.encode("gbk"), {"chapters": 4, "volumes": 0})

# 3. UTF-16 带 BOM、方括号标题、正文前缀、冒号
u16 = "\n".join([chapter("【第一章】风起"), chapter("正文 第二章 云涌"), chapter("第三章：雷动")])
SAMPLES["UTF-16、方括号、正文前缀、冒号"] = (u16.encode("utf-16"), {"chapters": 3, "volumes": 0})

# 4. 一行里先卷后章
both = "\n".join([chapter("第一卷 初入江湖 第一章 下山"), chapter("第二章 客栈"), chapter("第二卷 风云 第三章 比武")])
SAMPLES["一行里先卷后章"] = (both.encode("utf-8"), {"chapters": 3, "volumes": 2})

# 5. 正文里有「第三章」开头的长句、楔子在第一卷前面
tricky = "\n".join(
    [
        chapter("楔子"),
        "第一卷 开局",
        chapter("第一章 醒来", BODY + "第三章的内容他早就背熟了，可这一次考的偏偏是第三章后面的附录，他一下子愣住了。\n" + BODY),
        chapter("第二章 考试"),
    ]
)
SAMPLES["正文里有「第三章」开头的长句、楔子在卷前"] = (tricky.encode("utf-8"), {"chapters": 3, "volumes": 1})

# 6. 章里分小节（第一节、第二节），不该拆成章
sections = "\n".join(
    [
        "第一章 入城",
        "第一节",
        BODY,
        "第二节",
        BODY,
        "第二章 遇险",
        "第一节",
        BODY,
    ]
)
SAMPLES["章里分小节"] = (sections.encode("utf-8"), {"chapters": 2, "volumes": 0})

# 7. 一个标题都没有
plain = BODY * 40
SAMPLES["一个标题都没有"] = (plain.encode("utf-8"), {"volumes": 0})

# 8. 古典小说的「回」、大写数字和「千零」
classic = "\n".join([chapter("第一回 灵根育孕源流出"), chapter("第二回 悟彻菩提真妙理"), chapter("第一千零八十章 终局")])
SAMPLES["回、千零"] = (classic.encode("utf-8"), {"chapters": 3, "volumes": 0})

# 9. 同一章分上下
updown = "\n".join([chapter("第十章 决战（上）"), chapter("第十章 决战（下）")])
SAMPLES["同一章分上下"] = (updown.encode("utf-8"), {"chapters": 2, "volumes": 0})

bad = 0
for name, (data, want) in SAMPLES.items():
    out = split(data)
    chapters = out["chapters"]
    story = [c for c in chapters if "不像正文" not in c.flags]
    got = {"chapters": len(story), "volumes": len(out["volumes"])}
    ok = all(got[k] == v for k, v in want.items())
    bad += not ok
    print(f"{'✓' if ok else '✗'} {name}：编码 {out['encoding']}，{got['volumes']} 卷，正文 {got['chapters']} 章（共 {len(chapters)} 章），去掉广告 {out['ads_removed']} 行、重复 {out['duplicates_removed']} 章")
    if out["info"] or out["intro"]:
        print(f"    书的信息 {out['info']}；简介 {out['intro'][:30]!r}")
    for c in chapters[:10]:
        print(f"    卷{c.volume or '-'} 「{c.title}」 {len(c.text)} 字 {' '.join(c.flags)}")
    if not ok:
        print(f"    想要 {want}，得到 {got}")
print(f"\n{len(SAMPLES) - bad}/{len(SAMPLES)} 种对了")
