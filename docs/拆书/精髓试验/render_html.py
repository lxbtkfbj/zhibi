"""把 essence.json 排成新简介页（精髓页）的样张：data/拆书试验/精髓/<目录名>/精髓样张.html。

    python render_html.py <目录名>
样式照新书页装修样张的颜色和字体；左边小目录，右边一节一节往下滚。
"""

import html
import sys

from common import OUT, load

GROUPS = [
    ("核心要点", ["overview"]),
    ("爽点", ["shuang", "rhythm"]),
    ("角色", ["hero", "cast"]),
    ("剧情", ["skeleton", "source", "link", "fresh", "longline"]),
    ("写法", ["opening", "setting", "scene", "genre"]),
]
NAMES = {
    "overview": "核心要点", "shuang": "爽点设计", "rhythm": "节奏与钩子", "hero": "主角塑造", "cast": "配角与对手",
    "skeleton": "剧情骨架", "source": "情节来源", "link": "剧情衔接", "fresh": "保持新鲜", "longline": "长线布局",
    "opening": "开篇", "setting": "设定运用", "scene": "名场面写法", "genre": "类型要点",
}
LEADS = {
    "shuang": "读者读得过瘾的是哪几样，每一样怎么造出来",
    "rhythm": "为什么一章接一章停不下来",
    "hero": "主角为什么让人愿意跟着读",
    "cast": "重要的人怎么立住、在剧情里干什么用",
    "skeleton": "故事是怎么搭起来的，一个单元通常什么形状",
    "source": "作者怎么想出下一件事",
    "link": "一件事怎么接到下一件事",
    "fresh": "写这么多章为什么不重复",
    "longline": "这么长的书，前后怎么理顺",
    "opening": "开头几章怎么把人留住",
    "setting": "设定怎么替剧情和爽点干活",
    "scene": "最出彩的几场戏是怎么写出来的",
    "genre": "这是一本什么书，这一类书的门道",
}

CSS = """
:root{--desk:#e8dfcf;--chrome:#f7f2e9;--toc:#f3ece0;--paper:#fffcf6;--paper-2:#faf4ea;--rule:#e2d6c2;--rule-2:#d6c7ad;
--ink:#2a2420;--ink-2:#554c43;--ink-3:#6f665b;--seal:#b4432e;--seal-soft:#f6e4dc;--seal-line:#ebc4b6;--indigo:#3d4f7c;
--indigo-soft:#e7eaf3;--indigo-line:#c9d0e3;--jade:#2f7a6e;--jade-soft:#e0efe9;--jade-line:#b9d9cf;--ochre:#9a5f27;
--ochre-soft:#f5ead9;--ochre-line:#e4cfab;--serif:"Noto Serif SC","Songti SC","SimSun",serif;
--sans:"PingFang SC","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font-family:var(--sans);color:var(--ink);background:var(--desk);display:flex;flex-direction:column;overflow:hidden}
::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background-color:rgb(140 115 85/.26);border:3px solid transparent;border-radius:10px;background-clip:padding-box}
a{color:inherit;text-decoration:none}
.top{height:54px;flex:none;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:0 20px;background:var(--chrome);border-bottom:1px solid var(--rule)}
.top .left{display:flex;align-items:center;gap:13px}.back{font-size:13.5px;color:var(--ink-3)}
.mini{width:20px;height:27px;border-radius:2px 3px 3px 2px;background:linear-gradient(90deg,#5f391f 0 4px,#7a4a2a 4px)}
.bname{font-family:var(--serif);font-weight:700;font-size:17px}
.tag{font-size:12px;padding:1px 8px;border-radius:999px;color:var(--ochre);background:var(--ochre-soft);border:1px solid var(--ochre-line)}
.tabs{display:flex;gap:32px;height:54px}.tabs a{position:relative;display:flex;align-items:center;font-family:var(--serif);font-size:15.5px;color:var(--ink-3);letter-spacing:.12em}
.tabs a.on{color:var(--ink);font-weight:600}.tabs a.on::after{content:"";position:absolute;left:-4px;right:-2px;bottom:-1px;height:2px;border-radius:2px;background:var(--seal)}
.top .right{display:flex;justify-content:flex-end;align-items:center;gap:12px;font-size:13px;color:var(--ink-2)}
.btn{font-size:13px;padding:5px 12px;border-radius:6px;border:1px solid var(--seal-line);color:var(--seal);background:var(--paper)}
.desk{flex:1;min-height:0;padding:22px 28px}
.sheet{height:100%;max-width:1480px;margin:0 auto;background:var(--paper);border-radius:10px;box-shadow:0 1px 2px rgb(60 40 20/.08),0 10px 30px rgb(60 40 20/.10);display:grid;grid-template-columns:232px 1fr;overflow:hidden}
.toc{background:var(--toc);border-right:1px solid var(--rule);padding:22px 16px;overflow:auto}
.book{display:flex;gap:12px;padding:0 6px 16px;border-bottom:1px solid var(--rule);margin-bottom:12px}
.cover{width:44px;height:60px;flex:none;border-radius:3px 5px 5px 3px;background:linear-gradient(90deg,#5f391f 0 6px,#7a4a2a 6px);box-shadow:0 2px 4px rgb(60 35 15/.3)}
.book b{font-family:var(--serif);font-size:16px;display:block}.book small{font-size:12px;color:var(--ink-3);line-height:1.6;display:block;margin-top:3px}
.toc h4{margin:16px 6px 6px;font-size:12px;color:var(--ink-3);font-weight:400;letter-spacing:.1em}
.toc a{display:flex;justify-content:space-between;padding:6px 10px;border-radius:6px;font-size:14px;color:var(--ink-2)}
.toc a:hover{background:#ebe2d2}.toc a.on{background:var(--seal-soft);color:var(--seal)}.toc a span{font-size:12px;color:var(--ink-3)}
.toc .key{font-size:11px;color:var(--seal);border:1px solid var(--seal-line);border-radius:999px;padding:0 6px;margin-left:6px}
.main{overflow:auto;padding:30px 56px 80px;scroll-behavior:smooth}
.inner{max-width:860px}
.basis{font-size:12.5px;color:var(--ink-3);margin-bottom:22px}
section{margin-bottom:44px;scroll-margin-top:18px}
.kicker{font-size:12px;color:var(--seal);letter-spacing:.15em}
h2{font-family:var(--serif);font-size:24px;margin:4px 0 4px}.lead{font-size:13.5px;color:var(--ink-3);margin-bottom:16px}
.engine{font-family:var(--serif);font-size:20px;line-height:1.7;padding:16px 20px;border-left:3px solid var(--seal);background:var(--paper-2);border-radius:0 8px 8px 0;margin-bottom:18px}
.pt{border:1px solid var(--rule);border-radius:9px;padding:16px 18px 14px;margin-bottom:12px;background:#fffdf9}
.pt h3{font-family:var(--serif);font-size:17px;margin:0 0 8px;line-height:1.5}.pt h3 i{font-style:normal;color:var(--seal);margin-right:8px;font-size:14px}
.pt p{margin:0 0 10px;font-size:14.5px;line-height:1.85;color:var(--ink-2)}
.rule{font-size:13.5px;line-height:1.7;padding:8px 12px;border-radius:6px;background:var(--jade-soft);border:1px solid var(--jade-line);color:#24564e;margin-bottom:10px}
.rule b{font-weight:600;margin-right:6px}
.chs{display:flex;flex-wrap:wrap;gap:6px}.chs a{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--indigo-soft);border:1px solid var(--indigo-line);color:var(--indigo)}
.figs{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:16px}
.fig{border:1px solid var(--rule);border-radius:9px;padding:14px 16px;background:#fffdf9}
.fig h3{font-family:var(--serif);font-size:17px;margin:0 0 8px}.fig dl{margin:0;font-size:13.5px;line-height:1.75}
.fig dt{float:left;color:var(--ink-3);width:3.2em}.fig dd{margin:0 0 4px 3.4em;color:var(--ink-2)}
.miss{font-size:12.5px;color:var(--ink-3);padding:8px 12px;border:1px dashed var(--rule-2);border-radius:6px}
.sub{font-size:13px;color:var(--ink-3);margin:18px 0 10px}
"""


def esc(text) -> str:
    return html.escape(str(text or ""))


def chips(chapters) -> str:
    return '<div class="chs">' + "".join(f'<a title="点了跳到这一章原文">第 {n} 章</a>' for n in sorted(set(chapters))) + "</div>"


def point(p, number) -> str:
    return (
        f'<div class="pt"><h3><i>{number:02d}</i>{esc(p["title"])}</h3><p>{esc(p["how"])}</p>'
        f'<div class="rule"><b>通用做法</b>{esc(p["rule"])}</div>{chips(p["chapters"])}</div>'
    )


def main() -> None:
    slug = sys.argv[1]
    folder = OUT / slug
    data = load(folder / "essence.json")
    meta = load(folder / "meta.json")
    secs = data["sections"]
    upto = max(c["index"] for c in load(folder / "chapters.json"))
    toc, body = [], []
    for group, keys in GROUPS:
        toc.append(f"<h4>{group}{'<span class=key>重点</span>' if group == '剧情' else ''}</h4>")
        for key in keys:
            if key == "overview":
                ov = data.get("overview")
                if not ov:
                    continue
                toc.append(f'<a href="#overview" class="on">核心要点<span>{len(ov["points"])}</span></a>')
                body.append(
                    f'<section id="overview"><div class="kicker">核心要点</div><h2>一眼看懂这本书</h2>'
                    f'<div class="engine">{esc(ov["engine"])}</div>' + "".join(point(p, i) for i, p in enumerate(ov["points"], 1)) + "</section>"
                )
                continue
            sec = secs.get(key)
            if not sec:
                continue
            n = len(sec["points"]) + len(sec.get("figures", []))
            toc.append(f'<a href="#{key}">{NAMES[key]}<span>{n}</span></a>')
            parts = [f'<section id="{key}"><div class="kicker">{group}</div><h2>{NAMES[key]}</h2><div class="lead">{LEADS[key]}</div>']
            if sec.get("figures"):
                parts.append('<div class="figs">')
                for f in sec["figures"]:
                    parts.append(
                        f'<div class="fig"><h3>{esc(f["name"])}</h3><dl><dt>魅力</dt><dd>{esc(f["charm"])}</dd>'
                        f'<dt>作用</dt><dd>{esc(f["role"])}</dd>' + (f'<dt>变化</dt><dd>{esc(f["arc"])}</dd>' if f.get("arc") else "")
                        + f"</dl>{chips(f['chapters'])}</div>"
                    )
                parts.append('</div><div class="sub">塑造手法</div>')
            parts += [point(p, i) for i, p in enumerate(sec["points"], 1)]
            if sec.get("missing"):
                parts.append(f'<div class="miss">还看不出来：{esc("；".join(sec["missing"]))}</div>')
            parts.append("</section>")
            body.append("".join(parts))
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>精髓样张 · {esc(meta['title'])}</title>
<style>{CSS}</style></head><body>
<div class="top"><div class="left"><a class="back">‹ 书房</a><div class="mini"></div><span class="bname">{esc(meta['title'])}</span><span class="tag">拆的书</span></div>
<div class="tabs"><a class="on">简介</a><a>设定</a><a>大纲</a><a>正文</a></div>
<div class="right">已拆 {upto} / {meta['total']} 章 <a class="btn">接着拆</a></div></div>
<div class="desk"><div class="sheet">
<nav class="toc"><div class="book"><div class="cover"></div><div><b>{esc(meta['title'])}</b><small>{esc(meta.get('author') or '')}<br>{meta['total']} 章 · 已拆 {upto} 章</small></div></div>
{''.join(toc)}</nav>
<main class="main"><div class="inner"><div class="basis">下面的分析基于前 {upto} 章的拆书记录。拆得越多越准；补了章节、接着拆以后会重新整理。</div>
{''.join(body)}</div></main></div></div>
<script>
const main=document.querySelector('.main'),links=[...document.querySelectorAll('.toc a')];
main.addEventListener('scroll',()=>{{let cur=links[0];for(const a of links){{const s=document.querySelector(a.getAttribute('href'));if(s&&s.offsetTop-main.scrollTop<120)cur=a}}links.forEach(a=>a.classList.toggle('on',a===cur))}});
</script></body></html>"""
    out = folder / "精髓样张.html"
    out.write_text(page, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
