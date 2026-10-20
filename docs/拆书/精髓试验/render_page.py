"""把试验结果排成新书页的样子（直接用装修样张的样式，字号、颜色、边框和别的页一致）：
简介页（拆的书）＋新的「精髓」页（左边目录、中间一节一页、右边程序数的数字）。

    python render_page.py <目录名>
输出 data/拆书试验/精髓/<目录名>/精髓页样张.html。地址后面加 #简介 或 #精髓-shuang 这样可以直接打开某一页。
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from analyze import SECTIONS, Book, ctype, spans  # noqa: I001
from common import OUT, load

STYLE = re.search(r"<style>(.*?)</style>", Path("E:/Codex/zhibi/docs/界面原型/装修样张.html").read_text(encoding="utf-8"), re.S).group(1)
EXTRA = """
.kp { padding: calc(16px * var(--s)) 0 calc(18px * var(--s)); border-bottom: 1px dashed var(--rule); }
.kp:last-child { border-bottom: 0; }
.kp h3 { display: flex; gap: 10px; align-items: baseline; margin: 0 0 calc(8px * var(--s)); font-family: var(--serif); font-weight: 700; font-size: calc(17px * var(--s)); line-height: 1.55; color: var(--ink); }
.kp h3 .seal-no { position: relative; top: -2px; }
.kp p { margin: 0 0 calc(10px * var(--s)); font-size: calc(14.5px * var(--s)); line-height: 1.9; color: var(--ink-2); }
.kp .how-to { margin: 0 0 calc(10px * var(--s)); padding: 8px 12px; border-left: 3px solid var(--jade); border-radius: 0 8px 8px 0; background: var(--jade-soft); font-size: calc(13.5px * var(--s)); line-height: 1.75; color: #24564e; }
.kp .how-to b { font-weight: 600; margin-right: 6px; }
.kp .refs { font-size: 12.5px; color: var(--ink-3); }
.figs { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.fig { background: var(--paper-2); border: 1px solid #ece0cb; border-radius: 10px; padding: 13px 16px 12px; }
.fig .nm { font-family: var(--serif); font-weight: 700; font-size: calc(16.5px * var(--s)); margin-right: 8px; }
.fig dl { margin: 8px 0 6px; display: grid; grid-template-columns: 3.4em 1fr; gap: 4px 6px; font-size: calc(13.5px * var(--s)); line-height: 1.75; }
.fig dt { color: var(--ink-3); } .fig dd { margin: 0; color: var(--ink-2); }
.engine { margin: 0 0 calc(6px * var(--s)); font-family: var(--serif); font-size: calc(18.5px * var(--s)); line-height: 1.75; color: var(--ink); }
.bars { list-style: none; margin: 0; padding: 0; }
.bars li { display: grid; grid-template-columns: 5.2em 1fr 2.6em; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; color: var(--ink-2); }
.bars i { display: block; height: 7px; border-radius: 4px; background: var(--seal-line); }
.bars li span:last-child { text-align: right; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.feelstrip { display: flex; gap: 1px; height: 22px; }
.feelstrip i { flex: 1; border-radius: 1px; background: #ece2d0; }
.feelstrip i.s { background: var(--seal-line); } .feelstrip i.b { background: var(--seal); } .feelstrip i.d { background: var(--indigo-line); }
.miss { margin-top: calc(14px * var(--s)); }
"""

GROUPS = [("爽点", ["shuang", "rhythm"]), ("角色", ["hero", "cast"]), ("剧情", ["skeleton", "source", "link", "fresh", "longline"]),
          ("写法", ["opening", "setting", "scene", "genre"])]
LEADS = {
    "overview": "这本书最值得学的几条，各节里挑出来的",
    "shuang": "读者过瘾的是哪几类，每一类怎么造出来",
    "rhythm": "为什么一章接一章停不下来",
    "hero": "主角是什么人设，怎么立起来",
    "cast": "配角和对手各是什么人设、起什么作用",
    "skeleton": "故事怎么搭起来，一个单元通常什么形状",
    "source": "作者怎么想出下一件事",
    "link": "一件事怎么接到下一件事",
    "fresh": "写这么多章为什么不重复",
    "longline": "这么长的书，前后怎么理顺",
    "opening": "开头几章怎么把人留住",
    "setting": "设定怎么替剧情和爽点干活",
    "scene": "最出彩的几场戏是怎么写出来的",
    "genre": "这是一本什么书，这一类书的门道",
}


def rail_data(book: Book, data: dict) -> dict:
    ch = book.chapters
    feel = Counter(c["feel"] for c in ch)
    tags = defaultdict(int)
    for c in ch:
        if c["feel"] in ("爽", "大爽"):
            for t in dict.fromkeys((data.get("tags", {}).get(str(c["index"])) or {}).get("tags") or [ctype(c["cool_point"])]):
                tags[t] += 1
    plots = data.get("plots", {})
    return {
        "feel": dict(feel),
        "strip": [c["feel"] for c in ch],
        "tags": sorted(tags.items(), key=lambda x: -x[1])[:10],
        "crowd": sum(1 for v in data.get("tags", {}).values() if v.get("crowd")),
        "hooks": Counter(ctype(c["hook"]) for c in ch).most_common(6),
        "triggers": Counter(p["trigger_type"] for p in plots.values()).most_common(),
        "stakes": Counter(p["stakes"] for p in plots.values()).most_common(),
        "units": [{"n": u["n"], "first": u["first"], "last": u["last"], "title": u["title"]} for u in book.units],
        "waits": {"total": len(book.waits), "open": sum(1 for w in book.waits if not w["resolved"])},
        "people": [(n, len(book.appear[n])) for n in sorted(book.appear, key=lambda n: -len(book.appear[n]))[:8]],
        "hero": book.hero,
        "merges": data.get("merges", []),
    }


def main() -> None:
    slug = sys.argv[1]
    book = Book(slug)
    data = load(book.folder / "essence.json")
    book._people(data.get("merges", []))
    page = {
        "meta": book.meta, "upto": book.last, "units": len(book.units),
        "sections": data["sections"], "overview": data.get("overview"), "rail": rail_data(book, data),
        "names": {k: v[0] for k, v in SECTIONS.items()}, "leads": LEADS, "groups": GROUPS,
    }
    html = TEMPLATE.replace("/*STYLE*/", STYLE + EXTRA).replace("/*DATA*/", json.dumps(page, ensure_ascii=False))
    out = book.folder / "精髓页样张.html"
    out.write_text(html, encoding="utf-8")
    print(out)


TEMPLATE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>精髓页样张</title>
<link rel="stylesheet" href="../../../../frontend/node_modules/@fontsource/noto-serif-sc/400.css">
<link rel="stylesheet" href="../../../../frontend/node_modules/@fontsource/noto-serif-sc/600.css">
<link rel="stylesheet" href="../../../../frontend/node_modules/@fontsource/noto-serif-sc/700.css">
<style>/*STYLE*/</style></head><body>
<header class="top"><div class="left"><a class="back">‹ 书房</a><span class="sep"></span><span class="mini-cover"></span><span class="book-name" id="bn"></span><span class="tag">拆的书</span></div>
<nav class="tabs" id="tabs"></nav><div class="right"><div class="progress" id="pg"></div></div></header>
<div class="body" id="body"><aside class="toc" id="toc"></aside><main class="desk" id="desk"></main></div>
<div class="ball">编</div>
<script>
const P = /*DATA*/;
const CN = '一二三四五六七八九十'
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))
const refs = s => esc(s).replace(/第\s?\d+(?:\s?[–\-、]\s?\d+)*\s?章/g, m => `<span class="ref">${m}</span>`)
const M = P.meta, R = P.rail
document.getElementById('bn').textContent = M.title
document.getElementById('pg').innerHTML = `已拆 ${P.upto} / ${M.total} 章<span class="track"><b style="width:${Math.round(P.upto / M.total * 100)}%"></b></span><a class="btn seal-line">接着拆</a>`
const count = k => k === 'overview' ? (P.overview ? P.overview.points.length : 0) : (P.sections[k] ? P.sections[k].points.length + (P.sections[k].figures || []).length : 0)
const kp = (p, i) => `<div class="kp"><h3><span class="seal-no">${i + 1}</span><span>${esc(p.title)}</span></h3><p>${refs(p.how)}</p><div class="how-to"><b>通用做法</b>${esc(p.rule)}</div><div class="refs">证据：${p.chapters.map(n => `<span class="ref">第 ${n} 章</span>`).join('、')}</div></div>`
const bars = (rows, unit) => { const max = Math.max(...rows.map(r => r[1]), 1); return `<ul class="bars">${rows.map(([k, v]) => `<li><span>${esc(k)}</span><i style="width:${Math.max(6, v / max * 100)}%"></i><span>${v}${unit}</span></li>`).join('')}</ul>` }
const rb = (h, n, body) => `<div class="rb"><h3>${h}${n ? `<span class="n">${n}</span>` : ''}</h3>${body}</div>`
const strip = () => `<div class="feelstrip">${R.strip.map(f => `<i class="${f === '大爽' ? 'b' : f === '爽' ? 's' : f === '憋屈' ? 'd' : ''}" title="${f}"></i>`).join('')}</div><div class="small" style="display:flex;justify-content:space-between"><span>第 1 章</span><span>深红大爽 · 浅红爽 · 蓝憋屈</span><span>第 ${P.upto} 章</span></div>`
const RAIL = {
  overview: () => rb('这本书的数字', `前 ${P.upto} 章`, `<ul class="plist"><li><span class="nm">单元</span><span class="ct">${P.units} 个</span></li><li><span class="nm">过瘾的章</span><span class="ct">${(R.feel['爽'] || 0) + (R.feel['大爽'] || 0)} 章（大爽 ${R.feel['大爽'] || 0}）</span></li><li><span class="nm">读者在等的事</span><span class="ct">${R.waits.total} 件，还吊着 ${R.waits.open}</span></li></ul>`),
  shuang: () => rb('各类爽点出现几章', '一章可以算几类', bars(R.tags, ' 章')) + rb('靠旁观者放大', '', `<div class="small">过瘾的章里，有 ${R.crowd} 章有人在旁边看着、靠旁观者的反应把爽放大。</div>`),
  rhythm: () => rb('逐章的读者感觉', '模型判的', strip()) + rb('章末钩子', '', bars(R.hooks, ' 章')),
  hero: () => rb('主角', '', `<div class="small">${esc(R.hero)}，出场 ${R.people.find(p => p[0] === R.hero)?.[1] || ''} 章。</div>`),
  cast: () => rb('出场最多的人', '', bars(R.people, ' 章')) + (R.merges.length ? rb('并成同一个人的', '', R.merges.map(g => `<div class="small">${esc(g.names.join('、'))} → <b>${esc(g.keep)}</b>（${esc(g.why)}）</div>`).join('')) : ''),
  skeleton: () => rb('单元', `${P.units} 个`, `<ul class="plist">${R.units.map(u => `<li><span class="nm">${CN[u.n - 1] || u.n} · ${esc(u.title)}</span><span class="ct">${u.first}–${u.last}</span></li>`).join('')}</ul>`),
  source: () => rb('每个单元的事从哪来', '逐单元拆的', bars(R.triggers, ' 个')),
  link: () => rb('读者在等的事', '', `<div class="small">一共 ${R.waits.total} 件，还吊着 ${R.waits.open} 件。</div>`),
  fresh: () => rb('赌注比上一单元', '', bars(R.stakes, ' 次')),
}
function tocEssence(sel) {
  return `<div class="toc-head"><div class="search">找知识点……</div></div><div class="tree">
    <div class="row top1 ${sel === 'overview' ? 'on' : ''}" data-go="overview">核心要点<span class="n">${count('overview')}</span></div>
    ${P.groups.map(([g, keys]) => `<div class="row unit">${g}${g === '剧情' ? '<span class="chip seal" style="margin-left:6px;height:18px">重点</span>' : ''}</div><div class="kids">${keys.filter(k => P.sections[k]).map(k => `<div class="row ${sel === k ? 'on' : ''}" data-go="${k}">${P.names[k]}<span class="n">${count(k)}</span></div>`).join('')}</div>`).join('')}
  </div><div class="toc-foot">存档<span class="muted">8 分钟前存过</span></div>`
}
function essencePage(k) {
  const grp = k === 'overview' ? '精髓' : P.groups.find(g => g[1].includes(k))[0]
  if (k === 'overview') {
    const o = P.overview
    return `<section class="page"><div class="kicker">精髓</div><h1>核心要点</h1><div class="meta">${P.leads.overview} · 基于前 ${P.upto} 章</div><div class="rule1"></div><p class="engine">${esc(o.engine)}</p>${o.points.map(kp).join('')}</section>`
  }
  const s = P.sections[k]
  const figs = s.figures ? `<div class="sec"><div class="label">重要人物<span class="n">${s.figures.length} 个</span></div><div class="figs">${s.figures.map(f => `<div class="fig"><div><span class="nm">${esc(f.name)}</span><span class="chip ochre">${esc(f.archetype)}</span></div><dl><dt>怎么立</dt><dd>${refs(f.build)}</dd><dt>作用</dt><dd>${refs(f.role)}</dd>${f.arc ? `<dt>变化</dt><dd>${refs(f.arc)}</dd>` : ''}</dl><div class="refs small">${f.chapters.map(n => `<span class="ref">第 ${n} 章</span>`).join('、')}</div></div>`).join('')}</div></div><div class="sec"><div class="label">塑造手法</div>` : '<div>'
  return `<section class="page"><div class="kicker">精髓 · ${grp}</div><h1>${P.names[k]}</h1><div class="meta">${P.leads[k]} · 基于前 ${P.upto} 章</div><div class="rule1"></div>${figs}${s.points.map(kp).join('')}</div>${s.missing && s.missing.length ? `<p class="state miss">还看不出来：${esc(s.missing.join('；'))}</p>` : ''}</section>`
}
function intro() {
  const cast = R.people.slice(0, 6)
  const arche = Object.fromEntries((P.sections.cast?.figures || []).map(f => [f.name, f.archetype]))
  const o = P.overview
  return `<section class="page full"><div class="intro-top">
    <div class="hero"><div class="cover"><span class="lbl">${esc(M.title)}</span><span class="stamp">执笔</span></div><div>
      <div class="kicker">拆的书</div><h1>${esc(M.title)}</h1>
      <div class="meta">原书作者 ${esc(M.author || '（没写）')} · ${M.total} 章</div>
      <div class="statline"><span class="chip seal">已拆 ${P.upto} / ${M.total} 章</span><span class="chip ochre">${P.units} 个单元</span></div>
      <div style="margin-top:12px"><a class="btn seal-line">补后面的章节</a></div></div></div>
    <div class="side-box"><div class="label">一句话看懂<span class="n" data-go2="overview">去精髓页</span></div><p class="small" style="font-size:14px;color:var(--ink)">${esc(o.engine)}</p><ul class="plist one">${o.points.slice(0, 3).map(p => `<li><span class="ds">${esc(p.title)}</span></li>`).join('')}</ul></div>
    <div class="side-box"><div class="label">主要人物<span class="n">主角在前，其余按出场</span></div><ul class="plist one">${cast.map(([n, c]) => `<li><span class="nm">${esc(n)}</span><span class="ds">${n === R.hero ? '主角' : esc(arche[n] || '')} · 出场 ${c} 章</span></li>`).join('')}</ul></div>
  </div>
  <div class="sec" style="margin-top:22px"><div class="label">原书简介</div><p class="lead">${esc(M.intro || '原书文件里没有简介。')}</p></div>
  <div class="sec"><div class="label">已拆部分的节奏<span class="n">逐章的读者感觉</span></div>${strip()}</div></section>`
}
function show() {
  const h = decodeURIComponent(location.hash.slice(1)) || '精髓-overview'
  const isIntro = h === '简介'
  const key = isIntro ? null : (h.split('-')[1] || 'overview')
  document.getElementById('tabs').innerHTML = ['简介', '精髓', '设定', '大纲', '正文'].map(t => `<a class="${(isIntro ? '简介' : '精髓') === t ? 'on' : ''}" data-tab="${t}">${t}</a>`).join('')
  const body = document.getElementById('body')
  body.classList.toggle('wide', isIntro)
  document.getElementById('toc').style.display = isIntro ? 'none' : ''
  document.getElementById('toc').innerHTML = isIntro ? '' : tocEssence(key)
  document.getElementById('desk').innerHTML = isIntro ? intro() : essencePage(key) + (RAIL[key] ? `<aside class="rail">${RAIL[key]()}</aside>` : '')
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab]'); if (t) { if (t.dataset.tab === '简介') location.hash = '简介'; if (t.dataset.tab === '精髓') location.hash = '精髓-overview'; return }
  const g = e.target.closest('[data-go]'); if (g) location.hash = '精髓-' + g.dataset.go
  const g2 = e.target.closest('[data-go2]'); if (g2) location.hash = '精髓-' + g2.dataset.go2
})
window.addEventListener('hashchange', show); show()
</script></body></html>"""

if __name__ == "__main__":
    main()
