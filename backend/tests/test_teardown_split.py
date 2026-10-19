"""分章试验版十种样子，以及导入确认页新增规则。"""

import pytest

from app.services.teardown_split import (
    Piece,
    decode,
    filename_title,
    make_preview,
    number_issues,
    parse_number,
    selected_chapters,
    split,
)

BODY = "　　" + "他推开门，屋里一片漆黑。远处传来几声狗叫，像是在提醒他什么。" * 12 + "\n"
LONG_BODY = BODY * 2


def chapter(title: str, body: str = LONG_BODY) -> str:
    return f"{title}\n　　（{title}）{body}"


SAMPLES = [
    (
        "起点式，有卷、广告、请假、重复、番外、感言",
        "\n".join(
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
                chapter("第三章 客人"),
                chapter("请假条", "　　今天家里有事，请假一天，明天两更补上。\n"),
                "第二卷 云岚宗",
                chapter("第四章 三年之约"),
                chapter("第五章：休书"),
                chapter("番外 药老的往事"),
                chapter("完本感言", "　　感谢一路陪伴的读者……\n" * 3),
            ]
        ).encode(),
        6,
        2,
        "utf-8",
    ),
    (
        "章名挂求票、拿章号请假、很短的正常章",
        "\n".join(
            [
                chapter("第十章 决战（求月票！）"),
                chapter("第十一章 请假条", "　　家里有事，今天请假，明天补上。\n"),
                chapter("第十二章 余波", "　　风停了。" * 40 + "\n"),
                chapter("第十三章 新的开始"),
            ]
        ).encode(),
        3,
        0,
        "utf-8",
    ),
    (
        "GBK、数字写法混着、没有卷",
        "\n".join(
            [chapter("第1章 退婚"), chapter("第２章 休书"), chapter("第 3 章 戒指"), chapter("第004章 药老")]
        ).encode("gbk"),
        4,
        0,
        "gb18030",
    ),
    (
        "UTF-16、方括号、正文前缀、冒号",
        "\n".join([chapter("【第一章】风起"), chapter("正文 第二章 云涌"), chapter("第三章：雷动")]).encode("utf-16"),
        3,
        0,
        "utf-16",
    ),
    (
        "一行里先卷后章",
        "\n".join(
            [chapter("第一卷 初入江湖 第一章 下山"), chapter("第二章 客栈"), chapter("第二卷 风云 第三章 比武")]
        ).encode(),
        3,
        2,
        "utf-8",
    ),
    (
        "正文里有第三章开头的长句、楔子在卷前",
        "\n".join(
            [
                chapter("楔子"),
                "第一卷 开局",
                chapter(
                    "第一章 醒来",
                    BODY + "第三章的内容他早就背熟了，可这一次考的偏偏是第三章后面的附录，他一下子愣住了。\n" + BODY,
                ),
                chapter("第二章 考试"),
            ]
        ).encode(),
        3,
        1,
        "utf-8",
    ),
    (
        "章里分小节",
        "\n".join(["第一章 入城", "第一节", BODY, "第二节", BODY, "第二章 遇险", "第一节", BODY]).encode(),
        2,
        0,
        "utf-8",
    ),
    ("一个标题都没有", (BODY * 40).encode(), None, 0, "utf-8"),
    (
        "回、千零",
        "\n".join(
            [chapter("第一回 灵根育孕源流出"), chapter("第二回 悟彻菩提真妙理"), chapter("第一千零八十章 终局")]
        ).encode(),
        3,
        0,
        "utf-8",
    ),
    (
        "同一章分上下",
        "\n".join([chapter("第十章 决战（上）"), chapter("第十章 决战（下）")]).encode(),
        2,
        0,
        "utf-8",
    ),
]


@pytest.mark.parametrize("name,data,chapter_count,volume_count,encoding", SAMPLES, ids=[item[0] for item in SAMPLES])
def test_trial_samples(name, data, chapter_count, volume_count, encoding):
    result = split(data)
    chapters = selected_chapters(result)
    assert len(result["volumes"]) == volume_count, name
    assert result["encoding"] == encoding
    if chapter_count is not None:
        assert len(chapters) == chapter_count, name
        assert result["by_length"] is False
    else:
        assert len(chapters) > 1
        assert result["by_length"] is True
        assert all(piece.number is None and piece.flags == ["按字数切的"] for piece in chapters)


def test_trial_metadata_ads_duplicates_and_extra():
    result = split(SAMPLES[0][1])
    assert result["info"] == {"title": "斗破天穹", "author": "某某某"}
    assert result["intro"] == "这里是斗气的世界。少年天才一夜之间沦为废物……\n三十年河东，三十年河西。"
    assert result["ads_removed"] == 2
    assert result["duplicates_removed"] == 1
    assert [piece.title for piece in result["chapters"] if "不像正文" in piece.flags] == ["请假条", "完本感言"]
    assert selected_chapters(result)[-1].flags == ["番外"]
    assert all("www.xxbiquge.com" not in piece.text for piece in result["chapters"])


def test_begging_suffix_and_short_story_preserve_heading():
    result = split(SAMPLES[1][1])
    assert result["chapters"][0].title == "决战"
    assert result["chapters"][0].raw == "第十章 决战（求月票！）"
    assert result["chapters"][1].flags == ["不像正文"]
    assert result["chapters"][2].flags == ["太短"]
    assert result["chapters"][2] in selected_chapters(result)


def test_volume_and_chapter_one_line_and_prologue():
    combined = split(SAMPLES[4][1])
    assert combined["volumes"] == ["初入江湖", "风云"]
    assert [(piece.title, piece.volume, piece.number) for piece in combined["chapters"]] == [
        ("下山", 1, 1),
        ("客栈", 1, 2),
        ("比武", 2, 3),
    ]
    prologue = split(SAMPLES[5][1])
    assert prologue["chapters"][0].volume == 1
    assert prologue["chapters"][0].number is None
    assert "第三章的内容他早就背熟了" in prologue["chapters"][1].text


@pytest.mark.parametrize("ending", ["完结。", "完", "终", "结束了"])
def test_volume_ending_stays_in_previous_chapter(ending):
    line = f"【第一卷{ending}】"
    result = split(f"第一卷 起点\n{chapter('第一章 开始')}\n{line}\n{chapter('第二章 后续')}".encode())
    assert result["volumes"] == ["起点"]
    assert line in result["chapters"][0].text
    assert [piece.volume for piece in result["chapters"]] == [1, 1]


@pytest.mark.parametrize("left,right", [("“", "”"), ("「", "」"), ("『", "』"), ('"', '"')])
def test_volume_name_uses_first_pair_of_quotes(left, right):
    line = f"【第二卷{left}苍风烟云{right}开启……关键字：“后面的不是卷名”】"
    result = split(f"第一卷 开局\n{chapter('第一章 开始')}\n{line}\n{chapter('第二章 后续')}".encode())
    assert result["volumes"] == ["开局", "苍风烟云"]


def test_missing_first_volume_is_recovered_from_explicit_second_volume():
    data = (
        "序章\n开头。\n第一章 开始\n正文。\n【第一卷完结。】\n【第二卷“苍风烟云”开启……】\n第二章 后续\n后续正文。"
    ).encode()
    result = split(data)
    assert result["volumes"] == ["第一卷", "苍风烟云"]
    assert [piece.volume for piece in result["chapters"]] == [1, 1, 2]
    assert "【第一卷完结。】" in result["chapters"][1].text
    assert make_preview(result, "原书.txt", len(data))["volumes"] == [
        {"index": 1, "title": "第一卷", "chapters": 2},
        {"index": 2, "title": "苍风烟云", "chapters": 1},
    ]
    only_prologue = split("序章\n开头。\n第二卷 苍风烟云\n第一章 开始\n正文。".encode())
    assert only_prologue["volumes"] == ["苍风烟云"]
    assert [piece.volume for piece in only_prologue["chapters"]] == [1, 1]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("004", 4),
        ("００１", 1),
        ("零", 0),
        ("十", 10),
        ("百十", 110),
        ("两百零三", 203),
        ("第一", None),
        ("一千零八十", 1080),
        ("千零八", 1008),
        ("壹仟零捌拾", 1080),
        ("一〇八", 108),
        ("一万零两百三十四", 10234),
    ],
)
def test_original_chapter_number(value, expected):
    if expected is None:
        with pytest.raises(KeyError):
            parse_number(value)
        return
    assert parse_number(value) == expected
    for unit in ("章", "回", "节"):
        result = split(chapter(f"第{value}{unit} 来处").encode())
        assert result["chapters"][0].number == expected
        assert result["chapters"][0].title == "来处"


def test_sections_remain_in_body_and_title_only_chapter_is_empty_title():
    result = split("第一章\n第一节\n风来了。\n第二节\n雨也来了。\n第二章\n晴了。".encode())
    assert len(result["chapters"]) == 2
    assert [piece.title for piece in result["chapters"]] == ["", ""]
    assert result["chapters"][0].text == "第一节\n风来了。\n第二节\n雨也来了。"


def numbered(numbers, volume=1):
    return [Piece(title="", raw=f"第{number}章", volume=volume, numbered=True, number=number) for number in numbers]


def test_number_typo_only_reported_once_and_original_indices_kept():
    chapters = [Piece(title="序章", raw="序章", volume=1), *numbered([363, 36, 365, 413, 415])]
    issues, total = number_issues(chapters)
    assert total == 3
    assert issues == [
        {"index": 3, "title": "第36章", "number": 36, "expected": 364, "kind": "打错了"},
        {"index": 5, "title": "第413章", "number": 413, "expected": 366, "kind": "跳了"},
        {"index": 6, "title": "第415章", "number": 415, "expected": 414, "kind": "跳了"},
    ]
    assert number_issues(numbered([363, 36, 365])) == ([{**issues[0], "index": 2}], 1)


def test_number_repeat_backwards_and_volume_reset():
    assert [issue["kind"] for issue in number_issues(numbered([1, 2, 2, 5, 3]))[0]] == ["重了", "跳了", "倒回去了"]
    chapters = numbered([1, 2]) + numbered([1, 2], volume=2) + numbered([4], volume=3)
    issues, total = number_issues(chapters)
    assert total == 1
    assert issues[0]["index"] == 5
    assert issues[0]["expected"] == 3
    extra = Piece(title="番外", raw="番外", volume=1, number=50, flags=["番外"])
    assert number_issues([*numbered([1]), extra, *numbered([2])]) == ([], 0)


def test_number_issues_are_capped_but_total_is_not():
    issues, total = number_issues(numbered(range(1, 124, 2)))
    assert len(issues) == 50
    assert total == 61
    assert issues[-1]["index"] == 51


@pytest.mark.parametrize("encoding", ["utf-8", "gb18030", "utf-16", "big5"])
def test_explicit_encoding(encoding):
    text = "第一章 初見\n這是正文。"
    result = split(text.encode(encoding), encoding=encoding)
    assert result["encoding"] == encoding
    assert result["chapters"][0].text == "這是正文。"


def test_explicit_encoding_does_not_fall_back():
    data = "第一章 开始\n开始了。".encode("gb18030")
    assert split(data)["encoding"] == "gb18030"
    with pytest.raises(UnicodeDecodeError):
        split(data, encoding="utf-8")
    with pytest.raises(UnicodeError):
        split(b"abc", encoding="utf-16")
    with pytest.raises(ValueError, match="不支持这种编码"):
        split(data, encoding="latin-1")
    assert decode(b"\xff")[1] == "utf-8?"


def test_bom_is_detected_and_removed_from_text():
    data = "书名：《书名》\n第一章 开始\n正文。".encode("utf-8-sig")
    automatic = split(data)
    explicit = split(data, encoding="utf-8")
    assert automatic["encoding"] == "utf-8-sig"
    assert automatic["info"]["title"] == explicit["info"]["title"] == "书名"


@pytest.mark.parametrize(
    "name,want",
    [
        ("逆天邪神(1-500章).txt", "逆天邪神"),
        ("【精校】某某书（全本）.TXT", "某某书"),
        ("《某某书》（精校）（txt）.txt", "某某书"),
        ("某某书（完结）.txt", "某某书"),
        ("某某书（外传）.txt", "某某书（外传）"),
        ("某某书（2026）.txt", "某某书"),
        ("C:\\Users\\someone\\Desktop\\《原名》.txt", "原名"),
    ],
)
def test_filename_title(name, want):
    assert filename_title(name) == want


def test_recognized_book_title_takes_precedence_over_filename():
    for heading in ("书名：《原名》", "《原名》"):
        data = f"{heading}\n作者：原作者\n内容简介：简介\n第一章 开始\n一段正文。".encode()
        preview = make_preview(split(data), "文件名（全本）.txt", len(data))
        assert preview["title"] == "原名"
        assert preview["author"] == "原作者"
        assert preview["intro"] == "简介"


def test_preview_excludes_empty_and_nonstory_and_include_uses_zero_based_order():
    data = (
        "第一卷 开局\n序章\n  起点。\n第52章 前事\n 前事内容。\n"
        "第53章 上架感言\n感谢大家。\n第543章、刮目相看！\n第544章 刮目相看！\n  正文。\n"
    ).encode()
    result = split(data)
    preview = make_preview(result, "某书.txt", len(data), encoding_auto=False)
    assert preview["title"] == "某书"
    assert preview["encoding_auto"] is False
    assert preview["chapter_count"] == 3
    assert preview["chars"] == len("起点。前事内容。正文。")
    assert preview["volumes"] == [{"index": 1, "title": "开局", "chapters": 3}]
    assert preview["first"] == {"index": 1, "title": "序章"}
    assert preview["last"] == {"index": 3, "title": "刮目相看！"}
    assert preview["opening"] == "起点。"
    assert preview["excluded"] == [
        {"order": 2, "title": "上架感言", "chars": 5, "reason": "不像正文", "head": "感谢大家。"},
        {"order": 3, "title": "刮目相看！", "chars": 0, "reason": "空的", "head": ""},
    ]
    chosen = selected_chapters(result, [2, 3])
    assert len(chosen) == 5
    assert chosen[2].flags == ["不像正文"]
    assert chosen[3].flags == ["空的"]
    assert number_issues(chosen)[0][0]["index"] == 4
    assert preview["number_issues"][0]["index"] == 3


def test_preserves_raw_title_but_normalizes_body_and_counts_without_whitespace():
    raw = "　\t第００１章：开始  "
    result = split(f"{raw}\r\n　 第一段。\r第二 段。\n\n".encode())
    piece = result["chapters"][0]
    assert piece.raw == raw
    assert piece.title == "开始"
    assert piece.number == 1
    assert piece.text == "第一段。\n第二 段。"
    assert piece.chars == 8


def test_same_body_different_titles_are_not_removed_and_empty_stays_available():
    result = split("第一章 甲\n本章待修\n第二章 乙\n本章待修\n第三章 丙\n第四章 丁\n".encode())
    assert len(result["chapters"]) == 4
    assert result["duplicates_removed"] == 0
    assert len(selected_chapters(result)) == 2
    assert len(selected_chapters(result, [2, 3])) == 4


def test_long_average_falls_back_and_blank_input_has_no_body():
    result = split(("第一章 唯一标题\n" + BODY * 100).encode())
    assert result["by_length"] is True
    assert all(piece.number is None and piece.volume is None for piece in result["chapters"])
    blank = split(b" \r\n\t")
    assert blank["chars"] == 0
    assert selected_chapters(blank) == []
    assert make_preview(blank, "空.txt", 4)["first"] is None
