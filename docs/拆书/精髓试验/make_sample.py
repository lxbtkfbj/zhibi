"""生成给 Codex 照做的正式样张：docs/界面原型/精髓样张.html ＋ 精髓样张-数据.js。

数据就是接口 GET /api/books/{id}/teardown/essence 要返回的样子（加上书的几样基本信息），
页面上的每一个字都从数据里来；样式照装修样张，另加精髓页和新简介页、编辑部印章按钮的样式。

    python make_sample.py <目录名>
"""

import json
import re
import sys
from pathlib import Path

from analyze import SECTIONS, Book  # noqa: I001
from common import load
from render_page import EXTRA, GROUPS, LEADS, STYLE, TEMPLATE, rail_data

OUT = Path("E:/Codex/zhibi/docs/界面原型")

BALL = """
/* 编辑部按钮：朱砂印章，能拖 */
.ball { position: fixed; right: 24px; bottom: 22px; width: 50px; height: 50px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: var(--seal); color: #f6eadf; font: 700 21px var(--serif); box-shadow: inset 0 0 0 3px var(--seal), inset 0 0 0 4.5px rgb(246 234 223 / .78), 0 8px 18px -8px rgb(143 51 34 / .7), 0 2px 4px rgb(60 35 15 / .2); cursor: grab; user-select: none; touch-action: none; z-index: 30; transition: background .15s, transform .15s, box-shadow .15s; }
.ball:hover { background: #a93d29; }
.ball.dragging { cursor: grabbing; transform: scale(1.06); transition: none; box-shadow: inset 0 0 0 3px var(--seal), inset 0 0 0 4.5px rgb(246 234 223 / .78), 0 16px 28px -10px rgb(143 51 34 / .75), 0 2px 4px rgb(60 35 15 / .2); }
"""

DRAG = r"""
// 编辑部按钮：按住拖动（移动超过 4px 才算拖），松手贴到最近的左边或右边、离边 24px，上下位置照松手处（离顶栏和底边至少 16px）；
// 位置记在 localStorage「zhibi.ball」（{side, top}，top 是离窗口顶部的比例）；没拖只是点一下，才打开编辑部。
;(() => {
  const ball = document.querySelector('.ball'), KEY = 'zhibi.ball', GAP = 24, EDGE = 16, TOP = 54
  const zoom = () => Number(document.body.style.zoom || 1)
  const place = pos => {
    const h = innerHeight / zoom(), size = ball.offsetHeight
    const top = Math.min(Math.max(TOP + EDGE, pos.top * h), h - size - EDGE)
    ball.style.top = top + 'px'; ball.style.bottom = 'auto'
    ball.style.left = pos.side === 'left' ? GAP + 'px' : 'auto'; ball.style.right = pos.side === 'left' ? 'auto' : GAP + 'px'
  }
  let saved = null
  try { saved = JSON.parse(localStorage.getItem(KEY) || 'null') } catch { saved = null }
  if (saved) place(saved)
  let start = null, moved = false
  ball.addEventListener('pointerdown', e => { start = { x: e.clientX, y: e.clientY, rect: ball.getBoundingClientRect() }; moved = false; ball.setPointerCapture(e.pointerId) })
  ball.addEventListener('pointermove', e => {
    if (!start) return
    const dx = e.clientX - start.x, dy = e.clientY - start.y
    if (!moved && Math.hypot(dx, dy) < 4) return
    moved = true; ball.classList.add('dragging')
    const z = zoom()
    ball.style.left = (start.rect.left + dx) / z + 'px'; ball.style.top = (start.rect.top + dy) / z + 'px'; ball.style.right = 'auto'; ball.style.bottom = 'auto'
  })
  ball.addEventListener('pointerup', e => {
    if (!start) return
    const r = ball.getBoundingClientRect(); start = null; ball.classList.remove('dragging')
    if (!moved) { /* 打开编辑部 */ return }
    const pos = { side: r.left + r.width / 2 < innerWidth / 2 ? 'left' : 'right', top: (r.top / zoom()) / (innerHeight / zoom()) }
    place(pos)
    try { localStorage.setItem(KEY, JSON.stringify(pos)) } catch { /* 存不了就只管这一次 */ }
  })
  addEventListener('resize', () => { let pos = null; try { pos = JSON.parse(localStorage.getItem(KEY) || 'null') } catch { pos = null } if (pos) place(pos) })
})()
"""


def main() -> None:
    slug = sys.argv[1]
    book = Book(slug)
    data = load(book.folder / "essence.json")
    book._people(data.get("merges", []))
    sections = {}
    for key in SECTIONS:
        sec = data["sections"].get(key)
        if not sec:
            continue
        # 核对过的用核对后的（爽点戏怎么写引的是原文，不核对）；fixes 不上页面
        if key != "scene" and key in data.get("checked", {}):
            sec = {k: v for k, v in data["checked"][key].items() if k != "fixes"}
        sections[key] = {"name": sec["name"], "points": sec["points"], **({"figures": sec["figures"]} if sec.get("figures") else {}),
                         "missing": sec.get("missing", [])}
    payload = {
        "book": {"title": book.meta["title"], "author": book.meta.get("author", ""), "chapters": book.meta["total"],
                 "read": book.last, "intro": book.meta.get("intro", ""), "units": len(book.units)},
        "essence": {"upto": book.last, "overview": data["overview"], "sections": sections, "rails": rail_data(book, data)},
        "names": {k: v[0] for k, v in SECTIONS.items()}, "leads": LEADS, "groups": GROUPS,
    }
    (OUT / "精髓样张-数据.js").write_text(
        "// 精髓样张的数据：《逆天邪神》拆到第 100 章的真记录，精髓是 2026-10-20 用 Alicia gemini-3.8-flash 试拆、核对过的结果。\n"
        "// essence 这一块就是 GET /api/books/{id}/teardown/essence 要返回的样子。\n"
        "window.DATA = " + json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    html = TEMPLATE
    html = html.replace("<title>精髓页样张</title>", "<title>精髓样张 · 拆的书的简介页和精髓页</title>")
    html = html.replace("../../../../frontend/node_modules", "../../frontend/node_modules")
    html = html.replace("<style>/*STYLE*/</style>", "<style>" + STYLE + EXTRA + BALL + "</style>")
    # 数据换成外部文件，字段名照接口
    html = html.replace("const P = /*DATA*/;", """<!--DATA-->""")
    html = html.replace("<script>\n<!--DATA-->", "<script src=\"精髓样张-数据.js\"></script>\n<script>\n" + ADAPT)
    html = html.replace("</script></body></html>", DRAG + "</script></body></html>")
    html = html.replace("<div class=\"toc-foot\">存档<span class=\"muted\">8 分钟前存过</span></div>",
                        "<div class=\"toc-foot\">存档<span class=\"muted\">8 分钟前存过</span></div>")
    (OUT / "精髓样张.html").write_text(html, encoding="utf-8")
    print(OUT / "精髓样张.html")


# 样张里的渲染代码原本吃 render_page 的 P；这里把接口形状的 DATA 转成同一个 P，页面代码不用改
ADAPT = """const D = window.DATA, E = D.essence
const P = { meta: { title: D.book.title, author: D.book.author, total: D.book.chapters, intro: D.book.intro }, upto: E.upto, units: D.book.units,
  sections: E.sections, overview: E.overview, rail: E.rails, names: D.names, leads: D.leads, groups: D.groups }
"""

if __name__ == "__main__":
    main()
