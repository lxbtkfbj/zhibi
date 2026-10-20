"""把试验结果排成新书页的样子（直接用装修样张的样式和「按 1700 宽排、屏幕大就整页放大」的规矩，
字号、颜色、边框和别的页一致）：拆的书的简介页＋新的「精髓」页（左边目录、中间一节一页、右边程序数的数字）。

    python render_page.py <目录名>
输出 data/拆书试验/精髓/<目录名>/精髓页样张.html。地址后面加 #简介 或 #精髓-source 这样可以直接打开某一页。
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from analyze import SECTIONS, Book, ctype  # noqa: I001
from common import load

STYLE = re.search(r"<style>(.*?)</style>", Path("E:/Codex/zhibi/docs/界面原型/装修样张.html").read_text(encoding="utf-8"), re.S).group(1)
EXTRA = """
.kp { padding: 18px 0 20px; border-bottom: 1px dashed var(--rule); }
.kp:first-of-type { padding-top: 4px; }
.kp:last-child { border-bottom: 0; }
.kp h3 { display: flex; gap: 10px; align-items: baseline; margin: 0 0 10px; font-family: var(--serif); font-weight: 700; font-size: 18px; line-height: 1.5; color: var(--ink); }
.kp h3 .seal-no { position: relative; top: -2px; }
.kp h3 em { font-style: normal; color: var(--seal); }
.kp .steps { margin: 0 0 10px; padding: 0; list-style: none; counter-reset: s; }
.kp .steps li { position: relative; padding: 3px 0 3px 30px; font-family: var(--serif); font-size: 15.5px; line-height: 1.75; color: var(--ink); counter-increment: s; }
.kp .steps li::before { content: counter(s); position: absolute; left: 0; top: 6px; width: 19px; height: 19px; border-radius: 50%; background: var(--jade-soft); border: 1px solid var(--jade-line); color: var(--jade); font: 600 11.5px/17px var(--sans); text-align: center; }
.kp .ev { margin: 0; font-size: 13.5px; line-height: 1.8; color: var(--ink-2); }
.kp .ev b { font-weight: 600; color: var(--ink-3); margin-right: 6px; }
.kp .nt { margin: 6px 0 0; font-size: 13px; line-height: 1.7; color: var(--ochre); }
.kp .nt b { font-weight: 600; margin-right: 6px; }
.figs { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.fig { background: var(--paper-2); border: 1px solid #ece0cb; border-radius: 10px; padding: 13px 16px 12px; }
.fig .nm { font-family: var(--serif); font-weight: 700; font-size: 17px; margin-right: 8px; }
.fig dl { margin: 8px 0 6px; display: grid; grid-template-columns: 3.4em 1fr; gap: 4px 6px; font-size: 13.5px; line-height: 1.75; }
.fig dt { color: var(--ink-3); } .fig dd { margin: 0; color: var(--ink-2); }
.genre { margin: 0 0 6px; font-size: 13.5px; color: var(--ink-3); }
.engine { margin: 0 0 14px; font-family: var(--serif); font-size: 19px; line-height: 1.75; color: var(--ink); }
.bars { list-style: none; margin: 0; padding: 0; }
.bars li { display: grid; grid-template-columns: 6.6em 1fr 2.8em; align-items: center; gap: 8px; padding: 4px 0; font-size: 13px; color: var(--ink-2); }
.bars i { display: block; height: 7px; border-radius: 4px; background: var(--seal-line); }
.bars li span:last-child { text-align: right; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.feelstrip { display: flex; gap: 1px; height: 22px; }
.feelstrip i { flex: 1; border-radius: 1px; background: #ece2d0; }
.feelstrip i.s { background: var(--seal-line); } .feelstrip i.b { background: var(--seal); } .feelstrip i.d { background: var(--indigo-line); }
.legend { display: flex; justify-content: space-between; margin-top: 6px; font-size: 12px; color: var(--ink-3); }
.miss { margin-top: 16px; }
/* 简介页 */
.intro2 { display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(300px, 1fr); gap: 26px; }
.intro2 .main > .sec { margin-top: 24px; }
.intro2 .side { display: flex; flex-direction: column; gap: 14px; }
.intro2 .hero { grid-template-columns: 132px 1fr; gap: 24px; }
.intro2 .hero .cover { width: 132px; height: 184px; }
.intro2 .actions { display: flex; gap: 10px; margin-top: 16px; }
.intro2 .learn { margin: 0; padding: 0; list-style: none; counter-reset: l; }
.intro2 .learn li { position: relative; padding: 10px 0 10px 34px; border-bottom: 1px dashed #ece2d0; counter-increment: l; }
.intro2 .learn li:last-child { border-bottom: 0; }
.intro2 .learn li::before { content: counter(l); position: absolute; left: 0; top: 12px; width: 21px; height: 21px; border-radius: 5px; border: 1px solid var(--seal-line); background: var(--seal-soft); color: var(--seal); font: 600 12px/19px var(--sans); text-align: center; }
.intro2 .learn b { display: block; font-family: var(--serif); font-size: 15.5px; color: var(--ink); line-height: 1.6; }
.intro2 .learn span { display: block; margin-top: 2px; font-size: 13px; color: var(--ink-3); line-height: 1.7; }
.intro2 .ugrid { grid-template-columns: repeat(3, 1fr); gap: 10px; }
.intro2 .ucard { padding: 10px 13px 11px; }
.intro2 .ucard b { display: flex; gap: 7px; align-items: center; font-family: var(--serif); font-size: 14.5px; color: var(--ink); }
.intro2 .ucard small { display: block; margin-top: 4px; font-size: 12px; color: var(--ink-3); }
.intro2 .ucard.wait { background: transparent; border-style: dashed; }
.cast2 li { grid-template-columns: auto 1fr auto; }
.cast2 .chip { margin: 0; }
.waits2 li { display: block; padding: 7px 0; border-bottom: 1px dashed #ece2d0; font-size: 13.5px; line-height: 1.65; color: var(--ink-2); }
.waits2 li:last-child { border-bottom: 0; }
.waits2 li b { font-weight: 600; color: var(--seal-dark); margin-right: 6px; }
"""

GROUPS = [
    ("剧情", ["source", "skeleton", "link", "fresh", "longline"]),
    ("设定", ["setting"]),
    ("爽点", ["shuang", "scene"]),
    ("人物", ["hero", "cast"]),
    ("节奏与开篇", ["rhythm", "opening"]),
]
LEADS = {
    "overview": "如果只学几件事，先学这几件",
    "source": "想不出下一件事时，作者是怎么想的",
    "skeleton": "主线、大段落，一个单元通常什么形状",
    "link": "一件事怎么接到下一件事",
    "fresh": "写这么多章为什么不重复",
    "longline": "这么长的书，前后怎么理顺",
    "setting": "设定怎么想出来、为什么这么设",
    "shuang": "读者过瘾的是哪几类，每一类怎么造出来",
    "scene": "这几类爽点戏，一拍一拍怎么写",
    "hero": "主角是什么人设，怎么让人愿意跟着读",
    "cast": "配角和对手各是什么人设、起什么作用",
    "rhythm": "为什么一章接一章停不下来",
    "opening": "开头几章怎么把人留住",
}


def rail_data(book: Book, data: dict) -> dict:
    ch = book.chapters
    tags = Counter(t for c in ch if c["feel"] in ("爽", "大爽")
                   for t in dict.fromkeys((data.get("tags", {}).get(str(c["index"])) or {}).get("tags") or []))
    plots = data.get("plots", {})
    things = Counter(t["kind"] for c in ch for t in c.get("things", []))
    open_waits = sorted([w for w in book.waits if not w["resolved"]], key=lambda w: w["planted"])
    return {
        "feel": dict(Counter(c["feel"] for c in ch)),
        "strip": [c["feel"] for c in ch],
        "tags": tags.most_common(8),
        "crowd": sum(1 for v in data.get("tags", {}).values() if v.get("crowd")),
        "hooks": Counter(ctype(c["hook"]) for c in ch).most_common(6),
        "triggers": Counter(p["trigger_type"] for p in plots.values()).most_common(),
        "stakes": Counter(p["stakes"] for p in plots.values()).most_common(),
        "units": [{"n": u["n"], "first": u["first"], "last": u["last"], "title": u["title"]} for u in book.units],
        "tail": [book.units[-1]["last"] + 1, book.last] if book.units and book.units[-1]["last"] < book.last else None,
        "waits": {"total": len(book.waits), "open": len(open_waits)},
        "open": [{"at": w["planted"], "what": w["what"]} for w in open_waits[-4:]],
        "people": [(n, len(book.appear[n])) for n in sorted(book.appear, key=lambda n: -len(book.appear[n]))[:7]],
        "things": things.most_common(),
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
<header class="top"><div class="left"><a class="back">‹ 书房</a><span class="sep"></span><span class="mini-cover"></span><span class="book-name" id="bn"></span><span class="tag" id="tg"></span></div>
<nav class="tabs" id="tabs"></nav><div class="right"><div class="progress" id="pg"></div></div></header>
<div class="body" id="body"><aside class="toc" id="toc"></aside><main class="desk" id="desk"></main></div>
<div class="ball">编</div>
<script>
const P = /*DATA*/;
const CN = '一二三四五六七八九十'
const cn = n => n <= 10 ? CN[n - 1] : n <= 19 ? '十' + CN[n - 11] : String(n)
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))
const refs = s => esc(s).replace(/第\s?\d+(?:\s?[–\-、]\s?\d+)*\s?章/g, m => `<span class="ref">${m}</span>`)
const M = P.meta, R = P.rail
document.getElementById('bn').textContent = M.title
document.getElementById('tg').textContent = '拆的书' + (M.author ? ' · ' + M.author : '')
document.getElementById('pg').innerHTML = `已拆 ${P.upto} / ${M.total} 章<span class="track"><b style="width:${Math.max(2, Math.round(P.upto / M.total * 100))}%"></b></span><a class="btn seal-line">接着拆</a>`
const count = k => k === 'overview' ? (P.overview ? P.overview.points.length : 0) : (P.sections[k] ? P.sections[k].points.length + (P.sections[k].figures || []).length : 0)
const kp = (p, i) => {
  const [name, rest] = p.title.includes('：') ? [p.title.slice(0, p.title.indexOf('：')), p.title.slice(p.title.indexOf('：') + 1)] : ['', p.title]
  return `<div class="kp"><h3><span class="seal-no">${i + 1}</span><span>${name ? `<em>${esc(name)}</em>：` : ''}${esc(rest)}</span></h3>
  <ol class="steps">${p.steps.map(s => `<li>${refs(s)}</li>`).join('')}</ol>
  <p class="ev"><b>这本书里</b>${refs(p.evidence)}</p>${p.note ? `<p class="nt"><b>注意</b>${esc(p.note)}</p>` : ''}</div>`
}
const bars = (rows, unit) => { const max = Math.max(...rows.map(r => r[1]), 1); return `<ul class="bars">${rows.map(([k, v]) => `<li><span>${esc(k)}</span><i style="width:${Math.max(6, v / max * 100)}%"></i><span>${v}${unit}</span></li>`).join('')}</ul>` }
const rb = (h, n, body) => `<div class="rb"><h3>${h}${n ? `<span class="n">${n}</span>` : ''}</h3>${body}</div>`
const strip = () => `<div class="feelstrip">${R.strip.map((f, i) => `<i class="${f === '大爽' ? 'b' : f === '爽' ? 's' : f === '憋屈' ? 'd' : ''}" title="第 ${i + 1} 章 · ${f}"></i>`).join('')}</div><div class="legend"><span>第 1 章</span><span>深红大爽 · 浅红爽 · 蓝憋屈</span><span>第 ${P.upto} 章</span></div>`
const unitList = () => `<ul class="plist">${R.units.map(u => `<li><span class="nm">${cn(u.n)} · ${esc(u.title)}</span><span class="ct">${u.first}–${u.last}</span></li>`).join('')}${R.tail ? `<li><span class="nm">… 还没收尾</span><span class="ct">${R.tail[0]}–${R.tail[1]}</span></li>` : ''}</ul>`
const RAIL = {
  overview: () => rb('这本书的数字', `前 ${P.upto} 章`, `<ul class="plist"><li><span class="nm">单元</span><span class="ct">${P.units} 个</span></li><li><span class="nm">过瘾的章</span><span class="ct">${(R.feel['爽'] || 0) + (R.feel['大爽'] || 0)} 章（大爽 ${R.feel['大爽'] || 0}）</span></li><li><span class="nm">读者在等的事</span><span class="ct">${R.waits.total} 件，还吊着 ${R.waits.open}</span></li></ul>`) + rb('各类爽点出现几章', '', bars(R.tags.slice(0, 6), ' 章')),
  source: () => rb('每个单元的事从哪来', '逐单元拆的', bars(R.triggers, ' 个')) + rb('单元', `${P.units} 个`, unitList()),
  skeleton: () => rb('单元', `${P.units} 个`, unitList()),
  link: () => rb('读者在等的事', '', `<div class="small">一共 ${R.waits.total} 件，还吊着 ${R.waits.open} 件。</div>`) + rb('单元', `${P.units} 个`, unitList()),
  fresh: () => rb('赌注比上一单元', '', bars(R.stakes, ' 次')),
  setting: () => rb('拆出来的设定', '逐章记录里新冒出来的', bars(R.things, ' 条')),
  shuang: () => rb('各类爽点出现几章', '一章可以算几类', bars(R.tags, ' 章')) + rb('靠旁观者放大', '', `<div class="small">过瘾的章里，有 ${R.crowd} 章有人在旁边看着、靠旁观者的反应把爽放大。</div>`),
  hero: () => rb('出场最多的人', '', bars(R.people, ' 章')),
  cast: () => rb('出场最多的人', '', bars(R.people, ' 章')) + (R.merges.length ? rb('并成同一个人的', '', R.merges.map(g => `<div class="small">${esc(g.names.join('、'))} → <b>${esc(g.keep)}</b>（${esc(g.why)}）</div>`).join('')) : ''),
  rhythm: () => rb('逐章的读者感觉', '模型判的', strip()) + rb('章末钩子', '', bars(R.hooks, ' 章')),
}
function tocEssence(sel) {
  return `<div class="toc-head"><div class="search">找知识点……</div></div><div class="tree">
    <div class="row top1 ${sel === 'overview' ? 'on' : ''}" data-go="overview">核心要点<span class="n">${count('overview')}</span></div>
    ${P.groups.map(([g, keys]) => `<div class="row unit">${g}${g === '剧情' ? '<span class="chip seal" style="margin-left:4px;height:18px">重点</span>' : ''}</div><div class="kids">${keys.filter(k => P.sections[k]).map(k => `<div class="row ${sel === k ? 'on' : ''}" data-go="${k}">${P.names[k]}<span class="n">${count(k)}</span></div>`).join('')}</div>`).join('')}
  </div><div class="toc-foot">存档<span class="muted">8 分钟前存过</span></div>`
}
function essencePage(k) {
  if (k === 'overview') {
    const o = P.overview
    return `<section class="page"><div class="kicker">精髓</div><h1>核心要点</h1><div class="meta">${P.leads.overview} · 基于前 ${P.upto} 章</div><div class="rule1"></div><p class="genre">${esc(o.genre)}</p><p class="engine">${esc(o.engine)}</p>${o.points.map(kp).join('')}</section>`
  }
  const grp = P.groups.find(g => g[1].includes(k))[0], s = P.sections[k]
  const figs = s.figures ? `<div class="sec"><div class="label">重要人物<span class="n">${s.figures.length} 个</span></div><div class="figs">${s.figures.map(f => `<div class="fig"><div><span class="nm">${esc(f.name)}</span><span class="chip ochre">${esc(f.archetype)}</span></div><dl><dt>怎么立</dt><dd>${refs(f.build)}</dd><dt>作用</dt><dd>${refs(f.role)}</dd>${f.arc ? `<dt>变化</dt><dd>${refs(f.arc)}</dd>` : ''}</dl></div>`).join('')}</div></div><div class="sec"><div class="label">人设怎么搭、怎么立</div>` : '<div>'
  return `<section class="page"><div class="kicker">精髓 · ${grp}</div><h1>${P.names[k]}</h1><div class="meta">${P.leads[k]} · 基于前 ${P.upto} 章</div><div class="rule1"></div>${figs}${s.points.map(kp).join('')}</div>${s.missing && s.missing.length ? `<p class="state miss">还看不出来：${esc(s.missing.join('；'))}</p>` : ''}</section>`
}
function intro() {
  const arche = Object.fromEntries((P.sections.cast?.figures || []).map(f => [f.name, f.archetype]))
  const o = P.overview
  return `<section class="page full"><div class="intro2"><div class="main">
    <div class="hero"><div class="cover"><span class="lbl">${esc(M.title)}</span><span class="stamp">执笔</span></div><div>
      <div class="kicker">拆的书</div><h1>${esc(M.title)}</h1>
      <div class="meta">原书作者 ${esc(M.author || '（文件里没写）')} · ${M.total} 章</div>
      <div class="statline"><span class="chip seal">已拆 ${P.upto} / ${M.total} 章</span><span class="chip ochre">${P.units} 个单元</span><span class="chip jade">精髓基于前 ${P.upto} 章</span></div>
      <p class="genre" style="margin-top:14px">${esc(o.genre)}</p>
      <div class="actions"><a class="btn seal-line">补后面的章节</a></div></div></div>
    <div class="sec"><div class="label">一句话看懂<span class="n" data-go="overview" style="cursor:pointer">去精髓页 ›</span></div><p class="lead">${esc(o.engine)}</p></div>
    <div class="sec"><div class="label">最值得学的几件事<span class="n" data-go="overview" style="cursor:pointer">全部知识点 ›</span></div><ol class="learn">${o.points.slice(0, 4).map(p => `<li data-go="overview"><b>${esc(p.title)}</b><span>${esc(p.steps.map(s => s.replace(/[；;。，,]+$/, '')).join(' → '))}</span></li>`).join('')}</ol></div>
    <div class="sec"><div class="label">故事走到哪了<span class="n">一格一个单元</span></div><div class="ugrid">${R.units.map(u => `<div class="ucard"><b><span class="seal-no">${cn(u.n)}</span>${esc(u.title)}</b><small>第 ${u.first}–${u.last} 章 · ${u.last - u.first + 1} 章</small></div>`).join('')}${R.tail ? `<div class="ucard wait"><b><span class="seal-no">…</span>还没收尾</b><small>第 ${R.tail[0]}–${R.tail[1]} 章</small></div>` : ''}</div></div>
    ${M.intro ? `<div class="sec"><div class="label">原书简介</div><p class="lead" style="font-size:16px;white-space:pre-line">${esc(M.intro)}</p></div>` : ''}
  </div><div class="side">
    <div class="side-box"><div class="label">主要人物<span class="n">主角在前，其余按出场</span></div><ul class="plist cast2">${R.people.slice(0, 7).map(([n, c]) => `<li><span class="nm">${esc(n)}</span><span>${n === R.hero ? '<span class="chip seal">主角</span>' : arche[n] ? `<span class="chip ochre">${esc(arche[n])}</span>` : ''}</span><span class="ct">${c} 章</span></li>`).join('')}</ul></div>
    <div class="side-box"><div class="label">读者爽在哪<span class="n">各类出现几章</span></div>${bars(R.tags.slice(0, 6), ' 章')}</div>
    <div class="side-box"><div class="label">读者还在等<span class="n">${R.waits.open} 件还吊着</span></div><ul class="waits2">${R.open.map(w => `<li><b>第 ${w.at} 章立下</b>${esc(w.what)}</li>`).join('')}</ul></div>
    <div class="side-box"><div class="label">已拆部分的节奏<span class="n">逐章的读者感觉</span></div>${strip()}</div>
  </div></div></section>`
}
function show() {
  const h = decodeURIComponent(location.hash.slice(1)) || '简介'
  const isIntro = h === '简介'
  const key = isIntro ? null : (h.split('-')[1] || 'overview')
  document.getElementById('tabs').innerHTML = ['简介', '精髓', '设定', '大纲', '正文'].map(t => `<a class="${(isIntro ? '简介' : '精髓') === t ? 'on' : ''}" data-tab="${t}">${t}</a>`).join('')
  document.getElementById('body').classList.toggle('wide', isIntro)
  const toc = document.getElementById('toc')
  toc.style.display = isIntro ? 'none' : ''
  toc.innerHTML = isIntro ? '' : tocEssence(key)
  document.getElementById('desk').innerHTML = isIntro ? intro() : essencePage(key) + (RAIL[key] ? `<aside class="rail">${RAIL[key]()}</aside>` : '<aside class="rail"></aside>')
  fit()
}
// 和新书页一样：按 1700 宽排的版，屏幕更宽就整页等比放大（最多 1.5 倍）
function fit() {
  const z = Math.min(1.5, Math.max(1, innerWidth / 1700), Math.max(1, innerHeight / 800))
  document.body.style.zoom = z
  document.body.style.height = innerHeight / z + 'px'
}
document.addEventListener('click', e => {
  const t = e.target.closest('[data-tab]'); if (t) { if (t.dataset.tab === '简介') location.hash = '简介'; if (t.dataset.tab === '精髓') location.hash = '精髓-overview'; return }
  const g = e.target.closest('[data-go]'); if (g) location.hash = '精髓-' + g.dataset.go
})
addEventListener('resize', fit)
addEventListener('hashchange', show); show()
</script></body></html>"""

if __name__ == "__main__":
    main()
