"""TXT 导入分章：沿用分章试验版，只整理原文，不调用模型。"""

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import cached_property
from itertools import islice
from time import perf_counter

from opencc import OpenCC

NUM = r"[0-9０-９零〇○一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+"
SEP = r"[\s　:：、.．·\-—_]*"
OPEN, CLOSE = r"[【\[〔(（]?", r"[】\]〕)）]?"
CH = re.compile(
    rf"^(?:正文{SEP})?{OPEN}第{SEP}(?P<num>{NUM}){SEP}(?P<unit>章|回(?!合)|节){CLOSE}{SEP}(?P<name>.{{0,40}})$"
)
VOL = re.compile(
    rf"^{OPEN}(?:第{SEP}(?P<num>{NUM}){SEP}[卷部集]|卷{SEP}(?P<num2>{NUM})){CLOSE}(?P<tail>{SEP}(?P<name>.{{0,40}}))$"
)
BOTH = re.compile(
    rf"^(?P<vol>{OPEN}第{SEP}{NUM}{SEP}[卷部集]{CLOSE}{SEP}.{{0,30}}?){SEP}(?P<ch>第{SEP}{NUM}{SEP}(?:章|回(?!合)).{{0,40}})$"
)
SPECIAL = re.compile(
    r"^[【\[]?(?P<kind>序章|序言|序|楔子|引子|引言|前言|尾声|终章|大结局|后记|番外|外传|完本感言|上架感言|感言|请假条|请假)[】\]]?"
    r"(?:[\s　:：、.．·\-—_]+(?P<name>.{0,40}))?$"
)
NOT_STORY = re.compile(r"请假|感言|通知|公告|求票|月票|推荐票|打赏|抽奖|上架|致谢|新书|单章|作者的话|题外话|废话")
AD_PATTERNS = re.compile(
    r"https?://|www\.|[a-z0-9-]+\.(?:com|net|org|cc|cn|info|la|me|io|co|xyz|top|vip)\b"
    r"|本章未完|点击下一页|请记住本站|最新章节|最快更新|手机用户请|手机阅读|一秒记住|无弹窗|全文免费|txt下载|电子书下载|首发域名|本书首发"
    r"|求收藏|求推荐|求月票|求打赏|移动端浏览|阅读更方便|请收藏本站|内容试读|转送地址|首发地址|^(?:（本章完）|本章完)$",
    re.I,
)
INFO = {
    "title": re.compile(r"^[书書] ?名[:：]\s*《?(?P<v>[^》]+)》?"),
    "author": re.compile(r"^(?:作者|作 者)[:：]\s*(?P<v>.+)"),
}
BOOK_TITLE = re.compile(r"^《(?P<v>[^》]+)》$")
INTRO = re.compile(r"^(?:[内內]容)?[简簡] ?介[:：]?\s*(?P<v>.*)$")
BEG = re.compile(r"[（(【\[][^）)】\]]*(?:求|票|加更|爆更|更新|补更)[^）)】\]]*[）)】\]]\s*$")
QUOTED = re.compile(r'“([^”]*)”|「([^」]*)」|『([^』]*)』|"([^"]*)"')
ENCODINGS = {"utf-8", "gb18030", "utf-16", "big5"}
EXCLUDED_FLAGS = ("不像正文", "空的", "像是混进来的别的书", "乱码", "和前面一章重复")
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
WEB_ERROR = re.compile(r'http/1\.1|content-type|transfer-encoding|"code":|余额不足', re.I)
DIGITS = dict(zip("零〇○一二两三四五六七八九壹贰叁肆伍陆柒捌玖", "0001223456789123456789", strict=True))
UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000, "万": 10000}


@dataclass
class Piece:
    title: str
    raw: str
    volume: int | None
    numbered: bool = False
    number: int | None = None
    lines: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    ignored_headings: list[str] = field(default_factory=list)

    @cached_property
    def text(self) -> str:
        # 分章完成后才读取正文；预览和入库复用，不为每个统计重复拼接长正文。
        return "\n".join(self.lines).strip()

    @cached_property
    def chars(self) -> int:
        return len("".join(self.text.split()))


def parse_number(value: str) -> int:
    """兼容全角、中文逐位数字及十百千万（包括「百十」「千零」）。"""
    value = "".join(DIGITS.get(char, char) for char in value)
    if value.isdecimal():
        return int(value)
    total = section = number = 0
    for char in value:
        if char.isdecimal():
            number = number * 10 + int(char)
            continue
        unit = UNITS[char]
        if unit == 10000:
            total += (section + number or 1) * unit
            section = 0
        else:
            section += (number or 1) * unit
        number = 0
    return total + section + number


def decode(data: bytes, encoding: str | None = None) -> tuple[str, str]:
    """自动认编码沿用试验版；作者指定的编码必须严格解码，不兜底。"""
    if encoding:
        if encoding not in ENCODINGS:
            raise ValueError("不支持这种编码")
        return data.decode(encoding), encoding
    for bom, name in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return data.decode(name), name
    for name in ("utf-8", "gb18030"):
        try:
            return data.decode(name), name
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8?"


def volume_name(line: str, name: str) -> str:
    if match := QUOTED.search(name):
        return next(group for group in match.groups() if group is not None)
    # 整行被括起来的卷标题，末尾括号不是卷名。
    if line[:1] in "【[〔(（" and name[-1:] in "】]〕)）":
        name = name[:-1]
    return name.strip()


def valid_volume(line: str, name: str, tail: str) -> bool:
    return (
        not name.startswith(("完", "终", "结束"))
        and not tail.lstrip().startswith(("，", ",", "、", "。", "：", ":", "；", ";"))
        and not line.endswith(("、", "，", ","))
    )


def heading(line: str) -> tuple[str, str, str] | None:
    """返回卷、章或特殊章的标题；正文中的长句不当标题。"""
    if len(line) > 50:
        return None
    if (match := BOTH.match(line)) and not line.endswith("。"):
        vol = match.group("vol").strip()
        vol_match = VOL.match(vol)
        if vol_match and valid_volume(vol, vol_match.group("name").strip(), vol_match.group("tail")):
            return "both", volume_name(vol, vol_match.group("name")), match.group("ch").strip()
    if (match := VOL.match(line)) and not line.endswith("。"):
        name = match.group("name").strip()
        if valid_volume(line, name, match.group("tail")):
            return "vol", volume_name(line, name), "卷"
        return None
    if (match := CH.match(line)) and not (line.endswith("。") and len(match.group("name")) > 12):
        return "ch", match.group("name").strip(), match.group("unit")
    if (match := SPECIAL.match(line)) and not line.endswith("。"):
        return "special", (match.group("name") or "").strip(), match.group("kind")
    return None


def clean_lines(text: str) -> tuple[list[str], list[str], int]:
    lines, raw_lines, ads = [], [], 0
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.replace("\u200b", "").replace("\ufeff", "").strip(" \t　\xa0")
        if not line:
            continue
        if len(line) < 80 and AD_PATTERNS.search(line) and not heading(line):
            ads += 1
            continue
        lines.append(line)
        raw_lines.append(raw)
    return lines, raw_lines, ads


def simplify(text: str, t2s: bool | None) -> tuple[str, bool, bool, float]:
    """先认前 20000 个汉字，再用 OpenCC 的 t2s 词组词典转换整份原文。"""
    started = perf_counter()
    converter = OpenCC("t2s")
    sample = "".join(match.group() for match in islice(HAN.finditer(text), 20000))
    converted = converter.convert(sample)
    changed = sum(left != right for left, right in zip(sample, converted, strict=False)) + abs(
        len(sample) - len(converted)
    )
    traditional = bool(sample) and changed / len(sample) >= 0.02
    use_t2s = traditional if t2s is None else t2s
    if use_t2s:
        text = converter.convert(text)
    return text, traditional, use_t2s, perf_counter() - started


def split(
    data: bytes,
    *,
    encoding: str | None = None,
    short: int = 500,
    fallback_size: int = 3000,
    append: bool = False,
    t2s: bool | None = None,
) -> dict:
    text, actual_encoding = decode(data, encoding)
    text, traditional, use_t2s, t2s_seconds = simplify(text, t2s)
    lines, raw_lines, ads = clean_lines(text)
    marks = [heading(line) for line in lines]
    units = {mark[2] for mark in marks if mark and mark[0] == "ch"}
    # 有「章」又有「节」时，节是章内小节，不另起一章。
    sub_sections = "节" in units and ("章" in units or "回" in units)
    info: dict[str, str] = {}
    intro: list[str] = []
    volumes: list[str] = []
    pieces: list[Piece] = []
    current: Piece | None = None
    in_intro = False
    for line, raw, mark in zip(lines, raw_lines, marks, strict=True):
        if mark and mark[0] == "ch" and mark[2] == "节" and sub_sections:
            mark = None
        if mark and mark[0] == "ch" and not mark[1] and current is not None and current.number is not None:
            number = parse_number(CH.match(line).group("num"))
            if number not in (current.number + 1, current.number + 2):
                current.ignored_headings.append(line)
                mark = None
        if mark is None:
            if current is not None:
                current.lines.append(line)
            else:
                for key, pattern in INFO.items():
                    if match := pattern.match(line):
                        info[key] = match.group("v").strip()
                        break
                else:
                    if (match := BOOK_TITLE.match(line)) and not in_intro:
                        info.setdefault("title", match.group("v").strip())
                    elif match := INTRO.match(line):
                        in_intro = True
                        if match.group("v"):
                            intro.append(match.group("v"))
                    elif in_intro:
                        intro.append(line)
            continue
        kind, name, unit = mark
        chapter_line = line
        if kind in ("vol", "both"):
            original_volume = BOTH.match(line).group("vol") if kind == "both" else line
            volume_match = VOL.match(original_volume)
            volume_number = (volume_match.group("num") or volume_match.group("num2")) if volume_match else None
            if (
                not append
                and not volumes
                and volume_number
                and parse_number(volume_number) == 2
                and any(piece.number is not None for piece in pieces)
            ):
                # 有的 TXT 漏了首卷标题，却明确写了「第二卷」；已有编号正文属于
                # 第一卷，不能并进第二卷。这里只按原文卷号补缺名首卷，不猜剧情分卷。
                volumes.append("第一卷")
                for piece in pieces:
                    piece.volume = 1
            volumes.append(name)
            if kind == "vol":
                continue
            chapter_line = unit
            sub = heading(unit)
            name = sub[1] if sub else unit
            kind, unit = "ch", "章"
        title = f"{unit}{('：' + name) if name else ''}" if kind == "special" else BEG.sub("", name).strip()
        number_match = CH.match(chapter_line) if kind == "ch" else None
        current = Piece(
            title=title,
            raw=raw,
            volume=len(volumes) or None,
            numbered=kind == "ch",
            number=parse_number(number_match.group("num")) if number_match else None,
        )
        if kind == "special" and unit in ("番外", "外传"):
            current.flags.append("番外")
        pieces.append(current)

    total = sum(len(line) for line in lines)
    by_length = not pieces or total / len(pieces) > 20000
    if by_length:
        pieces, size, buf = [], 0, []
        for line in lines:
            buf.append(line)
            size += len(line)
            if size >= fallback_size:
                pieces.append(
                    Piece(title=f"第 {len(pieces) + 1} 段", raw="", volume=None, lines=buf, flags=["按字数切的"])
                )
                buf, size = [], 0
        if buf:
            pieces.append(Piece(title=f"第 {len(pieces) + 1} 段", raw="", volume=None, lines=buf, flags=["按字数切的"]))
        volumes = []

    seen: set[str] = set()
    previous_versions: dict[tuple[int, str], list[Piece]] = {}
    kept: list[Piece] = []
    dropped = 0
    main_number: int | None = None
    foreign_number: int | None = None
    for piece in pieces:
        if piece.number is not None:
            if main_number is not None and main_number >= 50:
                foreign = piece.number < main_number - 5 and (
                    (bool(piece.title) and 1 <= piece.number <= 3)
                    or (foreign_number is not None and piece.number == foreign_number + 1)
                )
                if foreign:
                    piece.flags.append("像是混进来的别的书")
                    foreign_number = piece.number
                else:
                    main_number, foreign_number = piece.number, None
            else:
                main_number = piece.number
        key = (piece.number, piece.title) if piece.number is not None else None
        versions = previous_versions.get(key, []) if key else []
        if (
            piece.text
            and versions
            and any(
                SequenceMatcher(None, previous.text[:3000], piece.text[:3000]).ratio() >= 0.9 for previous in versions
            )
        ):
            piece.flags.append("和前面一章重复")
        digest = hashlib.sha1((piece.title + "|" + piece.text).encode()).hexdigest()
        if piece.text and digest in seen and "和前面一章重复" not in piece.flags:
            dropped += 1
            continue
        seen.add(digest)
        if key:
            previous_versions.setdefault(key, []).append(piece)
        if not piece.text:
            piece.flags.append("空的")
        else:
            compact = "".join(piece.text.split())
            if WEB_ERROR.search(piece.text) or (len(compact) >= 50 and len(HAN.findall(compact)) < len(compact) / 2):
                piece.flags.append("乱码")
            brief = len(piece.text) < short and "按字数切的" not in piece.flags
            if piece.numbered:
                not_story = brief and bool(NOT_STORY.search(piece.title) or NOT_STORY.search(piece.text[:200]))
            else:
                not_story = bool(NOT_STORY.search(piece.title))
            if not_story:
                piece.flags.append("不像正文")
            elif brief:
                piece.flags.append("太短")
        if not append and volumes and piece.volume is None:
            piece.volume = 1
        kept.append(piece)
    return {
        "encoding": actual_encoding,
        "traditional": traditional,
        "t2s": use_t2s,
        "t2s_seconds": t2s_seconds,
        "info": info,
        "intro": "\n".join(intro),
        "volumes": volumes,
        "chapters": kept,
        "ads_removed": ads,
        "duplicates_removed": dropped,
        "chars": sum(piece.chars for piece in kept),
        "by_length": by_length,
    }


def filename_title(filename: str) -> str:
    name = re.split(r"[/\\]", filename)[-1]
    name = re.sub(r"\.[^.]*$", "", name).replace("《", "").replace("》", "").strip()
    name = re.sub(r"^(?:【[^】]*(?:精校|全本|完结|txt)[^】]*】\s*)+", "", name, flags=re.I)
    while match := re.search(r"[（(]([^（）()]*)[）)]\s*$", name):
        if not re.search(r"\d|章|完|全本|精校|txt", match.group(1), flags=re.I):
            break
        name = name[: match.start()].rstrip()
    return name or "未命名"


def selected_chapters(result: dict, include: Iterable[int] = ()) -> list[Piece]:
    included = set(include)
    return [
        piece
        for order, piece in enumerate(result["chapters"])
        if order in included or not any(flag in piece.flags for flag in EXCLUDED_FLAGS)
    ]


def number_issues(chapters: Sequence[Piece]) -> tuple[list[dict], int]:
    numbered = [
        (index, piece)
        for index, piece in enumerate(chapters, 1)
        if piece.number is not None and "番外" not in piece.flags and "像是混进来的别的书" not in piece.flags
    ]
    issues, total = [], 0
    previous: int | None = None
    previous_volume: int | None = None
    position = 0
    while position < len(numbered):
        index, piece = numbered[position]
        number = piece.number
        new_volume = piece.volume != previous_volume
        if previous is not None and number != previous + 1 and not (new_volume and number == 1):
            expected = previous + 1
            typo_count = 0
            if not new_volume:
                for count in range(1, 11):
                    if position + count >= len(numbered):
                        break
                    following = numbered[position + count][1]
                    if following.volume != piece.volume:
                        break
                    if following.number == expected + count:
                        typo_count = count
                        break
                    if following.number != number + count:
                        break
            kind = (
                "打错了"
                if typo_count
                else "跳了"
                if number > expected
                else "重了"
                if number == previous
                else "倒回去了"
            )
            total += 1
            if len(issues) < 50:
                issue = {"index": index, "title": piece.raw, "number": number, "expected": expected, "kind": kind}
                if typo_count > 1:
                    end_index, end_piece = numbered[position + typo_count - 1]
                    issue.update(count=typo_count, end_index=end_index, end_number=end_piece.number)
                issues.append(issue)
            if typo_count:
                # 用应有的章号接着比，避免下一章再报一次因同一笔误产生的跳号。
                number = expected + typo_count - 1
                position += typo_count - 1
        previous, previous_volume = number, piece.volume
        position += 1
    return issues, total


def make_preview(result: dict, filename: str, size: int, *, encoding_auto: bool = True) -> dict:
    chapters = selected_chapters(result)
    issues, issue_total = number_issues(chapters)
    counts: dict[int | None, int] = {}
    for piece in chapters:
        counts[piece.volume] = counts.get(piece.volume, 0) + 1
    excluded = []
    for order, piece in enumerate(result["chapters"]):
        if reason := next((flag for flag in EXCLUDED_FLAGS if flag in piece.flags), None):
            excluded.append(
                {"order": order, "title": piece.title, "chars": piece.chars, "reason": reason, "head": piece.text[:60]}
            )
    volumes = [
        {"index": index, "title": title, "chapters": counts.get(index, 0)}
        for index, title in enumerate(result["volumes"], 1)
    ]
    largest_volume = max(volumes, key=lambda volume: volume["chapters"], default=None)
    chapter_indices = {id(piece): index for index, piece in enumerate(chapters, 1)}
    ignored_heading_candidates = [
        {"order": order, "title": piece.title, "line": line}
        for order, piece in enumerate(result["chapters"])
        for line in piece.ignored_headings
    ]
    ignored_headings = [
        {**candidate, "index": chapter_indices[id(result["chapters"][candidate["order"]])]}
        for candidate in ignored_heading_candidates
        if id(result["chapters"][candidate["order"]]) in chapter_indices
    ]
    title = result["info"].get("title") or filename_title(filename)
    if result["t2s"]:
        title = OpenCC("t2s").convert(title)
    return {
        "title": title,
        "author": result["info"].get("author", ""),
        "intro": result["intro"],
        "file": {"name": filename, "size": size},
        "encoding": result["encoding"],
        "encoding_auto": encoding_auto,
        "traditional": result["traditional"],
        "t2s": result["t2s"],
        "t2s_seconds": result["t2s_seconds"],
        "chars": sum(piece.chars for piece in chapters),
        "chapter_count": len(chapters),
        "volumes": volumes,
        "volume_mode": "editor" if largest_volume and largest_volume["chapters"] > 400 else "original",
        "largest_volume": largest_volume,
        "first": {"index": 1, "title": chapters[0].title} if chapters else None,
        "last": {"index": len(chapters), "title": chapters[-1].title} if chapters else None,
        "opening": chapters[0].text[:300] if chapters else "",
        "excluded": excluded,
        "number_issues": issues,
        "number_issue_total": issue_total,
        "ignored_headings": ignored_headings[:20],
        "ignored_heading_total": len(ignored_headings),
        "ignored_heading_candidates": ignored_heading_candidates,
        "ads_removed": result["ads_removed"],
        "duplicates_removed": result["duplicates_removed"],
        "by_length": result["by_length"],
    }
