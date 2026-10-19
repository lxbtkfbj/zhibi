"""拆书第一批的分章试验版（设计说明第 14.2 节）：认编码、去广告、认卷和章、标不像正文的章。

还没接进后台；做第一批时照这里的规则搬进 backend，`try_split.py` 里的十种样子改成测试。
"""

import hashlib
import re
from dataclasses import dataclass, field

NUM = r"[0-9０-９零〇○一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+"
SEP = r"[\s　:：、.．·\-—_]*"
OPEN, CLOSE = r"[【\[〔(（]?", r"[】\]〕)）]?"
# 章：第一章 / 第1章 / 第００１章 / 正文 第一章 / 【第一章】 / 第十回；名字最多 40 个字
CH = re.compile(rf"^(?:正文{SEP})?{OPEN}第{SEP}(?P<num>{NUM}){SEP}(?P<unit>[章回节]){CLOSE}{SEP}(?P<name>.{{0,40}})$")
VOL = re.compile(rf"^{OPEN}(?:第{SEP}(?P<num>{NUM}){SEP}[卷部集]|卷{SEP}(?P<num2>{NUM})){CLOSE}{SEP}(?P<name>.{{0,40}})$")
# 一行里先卷后章：第一卷 陨落的天才 第一章 斗之力，三段
BOTH = re.compile(rf"^(?P<vol>{OPEN}第{SEP}{NUM}{SEP}[卷部集]{CLOSE}{SEP}.{{0,30}}?){SEP}(?P<ch>第{SEP}{NUM}{SEP}[章回].{{0,40}})$")
SPECIAL = re.compile(
    r"^[【\[]?(?P<kind>序章|序言|序|楔子|引子|引言|前言|尾声|终章|大结局|后记|番外|外传|完本感言|上架感言|感言|请假条|请假)[】\]]?"
    r"(?:[\s　:：、.．·\-—_]+(?P<name>.{0,40}))?$"
)
NOT_STORY = re.compile(r"请假|感言|通知|公告|求票|月票|推荐票|打赏|抽奖|上架|致谢|新书|单章|作者的话|题外话|废话")
AD_PATTERNS = re.compile(
    r"https?://|www\.|[a-z0-9-]+\.(?:com|net|org|cc|cn|info|la|me|io|co|xyz|top|vip)\b"
    r"|本章未完|点击下一页|请记住本站|最新章节|最快更新|手机用户请|手机阅读|一秒记住|无弹窗|全文免费|txt下载|电子书下载|首发域名|本书首发"
    r"|求收藏|求推荐|求月票|求打赏",
    re.I,
)
INFO = {"title": re.compile(r"^(?:书名|书 名)[:：]\s*《?(?P<v>[^》]+)》?"), "author": re.compile(r"^(?:作者|作 者)[:：]\s*(?P<v>.+)")}
INTRO = re.compile(r"^(?:内容)?(?:简介|简 介)[:：]?\s*(?P<v>.*)$")
BEG = re.compile(r"[（(【\[][^）)】\]]*(?:求|票|加更|爆更|更新|补更)[^）)】\]]*[）)】\]]\s*$")


@dataclass
class Piece:
    title: str
    raw: str
    volume: int | None
    numbered: bool = False
    lines: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def decode(data: bytes) -> tuple[str, str]:
    """认编码：先看 BOM，再试 UTF-8，再试 GB18030；都不对就按 UTF-8 硬读、让作者在确认页换。"""
    for bom, name in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return data.decode(name), name
    for name in ("utf-8", "gb18030"):
        try:
            return data.decode(name), name
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8?"


def clean_lines(text: str) -> tuple[list[str], int]:
    out, ads = [], 0
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.replace("​", "").replace("﻿", "").strip(" \t　\xa0")
        if not line:
            continue
        # 标题行永远不当广告删（「第十章 决战（求月票！）」也是标题）
        if len(line) < 80 and AD_PATTERNS.search(line) and not heading(line):
            ads += 1
            continue
        out.append(line)
    return out, ads


def heading(line: str):
    """这一行是不是标题：返回 ('vol'|'ch'|'special', 名字, 单位)；正文里的长句、带句号的不算。"""
    if len(line) > 50:
        return None
    if (m := BOTH.match(line)) and not line.endswith("。"):
        return ("both", m.group("vol").strip(), m.group("ch").strip())
    if (m := VOL.match(line)) and not line.endswith("。"):
        return ("vol", m.group("name").strip(), "卷")
    if (m := CH.match(line)) and not (line.endswith("。") and len(m.group("name")) > 12):
        return ("ch", m.group("name").strip(), m.group("unit"))
    if (m := SPECIAL.match(line)) and not line.endswith("。"):
        return ("special", (m.group("name") or "").strip(), m.group("kind"))
    return None


def split(data: bytes, *, short=500, fallback_size=3000) -> dict:
    text, encoding = decode(data)
    lines, ads = clean_lines(text)
    marks = [heading(line) for line in lines]
    units = {m[2] for m in marks if m and m[0] == "ch"}
    # 有「章」又有「节」：节当成章里面的小节，不另起一章
    sub_sections = "节" in units and ("章" in units or "回" in units)

    info: dict[str, str] = {}
    intro: list[str] = []
    volumes: list[str] = []
    pieces: list[Piece] = []
    current: Piece | None = None
    in_intro = False
    for line, mark in zip(lines, marks):
        if mark and mark[0] == "ch" and mark[2] == "节" and sub_sections:
            mark = None
        if mark is None:
            if current is None:
                for key, pattern in INFO.items():
                    if m := pattern.match(line):
                        info[key] = m.group("v").strip()
                        break
                else:
                    if m := INTRO.match(line):
                        in_intro = True
                        if m.group("v"):
                            intro.append(m.group("v"))
                    elif in_intro:
                        intro.append(line)
            else:
                current.lines.append(line)
            continue
        kind, name, unit = mark
        if kind in ("vol", "both"):
            volumes.append(name if kind == "vol" else re.sub(rf"^{OPEN}第{SEP}{NUM}{SEP}[卷部集]{CLOSE}{SEP}", "", name))
            if kind == "vol":
                continue
            sub = heading(unit)
            name = sub[1] if sub else unit
            kind, unit = "ch", "章"
        vol = len(volumes) or None
        if kind == "special":
            title = f"{unit}{('：' + name) if name else ''}"
        else:
            # 标题后面挂的「（求月票！）」「（加更）」去掉
            title = BEG.sub("", name).strip()
        current = Piece(title=title, raw=line, volume=vol, numbered=kind == "ch")
        if kind == "special" and unit in ("番外", "外传"):
            current.flags.append("番外")
        pieces.append(current)

    # 一个标题都没有，或者平均一章太长（多半是认漏了）：按字数切
    total = sum(len(line) for line in lines)
    if not pieces or total / max(len(pieces), 1) > 20000:
        pieces, size, buf = [], 0, []
        for line in lines:
            buf.append(line)
            size += len(line)
            if size >= fallback_size:
                pieces.append(Piece(title=f"第 {len(pieces) + 1} 段", raw="", volume=None, lines=buf, flags=["按字数切的"]))
                buf, size = [], 0
        if buf:
            pieces.append(Piece(title=f"第 {len(pieces) + 1} 段", raw="", volume=None, lines=buf, flags=["按字数切的"]))
        volumes = []

    # 完全重复的章（盗版文件常见）去掉；不像正文的标出来
    seen: set[str] = set()
    kept: list[Piece] = []
    dropped = 0
    for piece in pieces:
        # 标题和正文都一样才算重复：只看正文会把「本章待修」这类一样的短章误删
        digest = hashlib.sha1((piece.title + "|" + piece.text).encode()).hexdigest()
        if piece.text and digest in seen:
            dropped += 1
            continue
        seen.add(digest)
        brief = len(piece.text) < short and "按字数切的" not in piece.flags
        # 有章号的是正文，除非又短又是请假、感言这类（作者常拿一个章号发请假条）；
        # 没章号的（请假条、完本感言）看标题。只是短的标「太短」，照样算正文。
        if piece.numbered:
            not_story = brief and bool(NOT_STORY.search(piece.title) or NOT_STORY.search(piece.text[:200]))
        else:
            not_story = bool(NOT_STORY.search(piece.title))
        if not_story:
            piece.flags.append("不像正文")
        elif brief:
            piece.flags.append("太短")
        kept.append(piece)
    # 卷前面的楔子、序章归进第一卷
    if volumes:
        for piece in kept:
            if piece.volume is None:
                piece.volume = 1
    return {
        "encoding": encoding,
        "info": info,
        "intro": "\n".join(intro),
        "volumes": volumes,
        "chapters": kept,
        "ads_removed": ads,
        "duplicates_removed": dropped,
        "chars": sum(len(p.text) for p in kept),
    }
