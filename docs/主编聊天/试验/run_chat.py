"""主编聊天提示词新旧对照：拿作者一段真聊天当考题，每一轮用同样的资料和聊天记录，只换提示词。

在 backend 下用 `uv run --no-sync python -X utf8 ../docs/主编聊天/试验/run_chat.py <书的 id> [模型配置名]` 运行。
- 从作者库的 llm_calls 里取这本书每一次「聊天·主编」的原始请求（系统提示 + 用户提示），只读。
- 旧版：原样发；新版：系统提示里的主编人设换成草稿，用户提示里「要求：」以后换成草稿（how_to_apply、role_focus 照原请求里填好的字）。
- 两版都发给同一个模型（默认作者指定的「【Alicia】gemini-3.8-flash」），参数照执笔里的配置。
- 结果存在 data/主编聊天试验/<书的 id>/results.json，跑过的轮次重跑时跳过；最后出一页并排对照 对照.html。
"""

import asyncio
import html
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRAFTS = HERE.parent / "提示词草稿"
PROMPTS = Path("E:/Codex/zhibi/backend/app/prompts")
for line in Path("E:/Codex/zhibi/.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))
sys.path.insert(0, "E:/Codex/zhibi/backend")
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402
import psycopg  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from app.crypto import decrypt  # noqa: E402

DB = "postgresql://zhibi:zhibi@127.0.0.1:5433/zhibi"
PARALLEL = 4


def profile_row(name: str) -> dict:
    with psycopg.connect(DB) as conn:
        conn.execute("set default_transaction_read_only = on")
        row = conn.execute(
            "select base_url, model, api_key_encrypted, temperature, timeout_s, reasoning_effort, max_tokens "
            "from llm_profiles where name = %s",
            (name,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"作者库里没有叫「{name}」的模型配置")
    base_url, model, key, temperature, timeout_s, effort, max_tokens = row
    return {
        "name": name, "base_url": base_url, "model": model, "api_key": decrypt(key), "temperature": temperature,
        "timeout_s": timeout_s, "effort": effort, "max_tokens": max_tokens,
    }


def chief_calls(book_id: str) -> list[dict]:
    with psycopg.connect(DB) as conn:
        conn.execute("set default_transaction_read_only = on")
        rows = conn.execute(
            "select id, model, request->>'system', request->>'user', response from llm_calls "
            "where book_id = %s and role = 'chief' and request->>'method' = 'stream_text' and ok order by id",
            (book_id,),
        ).fetchall()
    return [{"call": r[0], "model": r[1], "system": r[2], "user": r[3], "response": r[4] or ""} for r in rows]


def head(template: str) -> str:
    """模板里 {{rules}} 之前的部分，照执笔的 render 去掉首尾空白。"""
    return template.split("{{rules}}")[0].strip()


def between(text: str, start: str, end: str) -> str:
    i = text.index(start) + len(start)
    return text[i : text.index(end, i)]


def new_prompts(call: dict) -> tuple[str, str]:
    old_head = head((PROMPTS / "persona_chief.md").read_text(encoding="utf-8"))
    new_head = head((DRAFTS / "persona_chief.md").read_text(encoding="utf-8"))
    if old_head not in call["system"]:
        raise SystemExit(f"调用 {call['call']} 的系统提示里找不到现在的主编人设，可能提示词改过")
    system = call["system"].replace(old_head, new_head)
    user = call["user"]
    how = between(user, "「我记下了」。", "\n2. ")
    focus = between(user, "照你的角色说话：", "\n8. ")
    rules = (DRAFTS / "chat_reply.md").read_text(encoding="utf-8").split("要求：\n", 1)[1]
    rules = rules.replace("{{how_to_apply}}", how).replace("{{role_focus}}", focus).strip()
    return system, user.split("要求：\n", 1)[0] + "要求：\n" + rules


def note_of(user: str) -> str:
    return between(user, "【作者这次说的】\n", "\n\n要求：").strip()


async def ask(llm: ChatOpenAI, system: str, user: str) -> dict:
    started = time.monotonic()
    for attempt in range(3):
        try:
            result = await llm.ainvoke([SystemMessage(system), HumanMessage(user)])
            return {"text": str(result.content).strip(), "seconds": round(time.monotonic() - started, 1)}
        except Exception as exc:  # noqa: BLE001 试验脚本：限流、网络抖动都等一下再试
            if attempt == 2:
                return {"text": "", "error": f"{type(exc).__name__}: {exc}"[:300], "seconds": round(time.monotonic() - started, 1)}
            await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError


def paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in parts) or "<p class='empty'>（没有回答）</p>"


def report(out: Path, turns: list[dict], model: str) -> None:
    rows = []
    for t in turns:
        old, new = t.get("old", {}), t.get("new", {})
        rows.append(f"""
<section class="turn">
  <div class="author"><span class="who">第 {t['n']} 轮 · 作者说</span>{paragraphs(t['note'])}</div>
  <div class="pair">
    <div class="col old"><div class="tag">旧提示词 · {len(old.get('text', ''))} 字</div>{paragraphs(old.get('text', '') or old.get('error', ''))}</div>
    <div class="col new"><div class="tag">新提示词 · {len(new.get('text', ''))} 字</div>{paragraphs(new.get('text', '') or new.get('error', ''))}</div>
  </div>
  <details><summary>当时实际的回答（{html.escape(t['orig_model'])}）</summary>{paragraphs(t['orig'])}</details>
</section>""")
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>主编聊天新旧对照</title>
<style>
:root {{ --bg:#f6f1e7; --card:#fffdf8; --ink:#2b2520; --ink2:#5b5148; --ink3:#8c8177; --line:#e6dccb; --old:#efe8dc; --new:#e8f0ea; --seal:#a23b2a; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#1d1a17; --card:#26221e; --ink:#ece4d8; --ink2:#c9bfb1; --ink3:#9a8f82; --line:#3a332c; --old:#2c2722; --new:#22302a; --seal:#e07a63; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.75 "Noto Serif SC","Songti SC",serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 16px 60px; }}
h1 {{ font-size:24px; margin:0 0 6px; }}
.lead {{ color:var(--ink2); margin:0 0 18px; }}
.notes {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 18px; margin-bottom:26px; color:var(--ink2); font-size:14px; }}
.notes b {{ color:var(--ink); }}
.turn {{ margin:0 0 30px; }}
.author {{ background:var(--card); border:1px solid var(--line); border-left:3px solid var(--seal); border-radius:10px; padding:10px 16px; margin-bottom:10px; }}
.who {{ display:block; font:12px/1.6 sans-serif; color:var(--seal); letter-spacing:.04em; }}
.pair {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; }}
.col {{ border:1px solid var(--line); border-radius:10px; padding:10px 16px; }}
.col.old {{ background:var(--old); }} .col.new {{ background:var(--new); }}
.tag {{ font:12px/1.6 sans-serif; color:var(--ink3); margin-bottom:2px; }}
p {{ margin:6px 0; }} .empty {{ color:var(--ink3); }}
details {{ margin-top:8px; font-size:14px; color:var(--ink2); }} summary {{ cursor:pointer; color:var(--ink3); font:13px sans-serif; }}
@media (max-width:760px) {{ .pair {{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>主编聊天：新旧提示词对照</h1>
<p class="lead">考题是你在《佔位》里和主编的 {len(turns)} 轮真实聊天。两版都用 {html.escape(model)}。</p>
<div class="notes">
<p><b>怎么比的：</b>每一轮给主编的资料、前面的聊天记录、你那句话都和当时一模一样，只有提示词不同。前面的聊天记录用的是当时真实的回答，所以新版每一轮看到的「前情」还是旧主编说过的话。</p>
<p><b>新提示词改了什么：</b>不再每次都给三个方向让你挑；你没想好、或者话能有两种理解时，先问清楚；要给主意就讲清道理，能深挖一个就只挖一个；说到别的书，拿不准的说「印象里，不一定准」；有自己的判断，不客套、不奉承、不连声道歉；不再每次都说设定库是空的；先回答再展开，一般不超过三百字。</p>
<p><b>请你看：</b>哪一版对你更有启发、更像一个懂行的编辑在跟你聊；哪一轮新版反而更差。左右两栏每一轮都是只跑了一次，同一个提示词再跑一次说法会有出入，看的是整体的路子。</p>
</div>
{''.join(rows)}
</main></body></html>"""
    (out / "对照.html").write_text(page, encoding="utf-8")


async def main() -> None:
    book_id = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "【Alicia】gemini-3.8-flash"
    out = Path("E:/Codex/zhibi/data/主编聊天试验") / book_id
    out.mkdir(parents=True, exist_ok=True)
    saved = out / "results.json"
    turns = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else []
    calls = chief_calls(book_id)
    p = profile_row(name)
    print(f"{len(calls)} 轮；模型：{p['name']}（{p['model']}，温度 {p['temperature']}）")
    by_call = {t["call"]: t for t in turns}
    for n, call in enumerate(calls, 1):
        system, user = new_prompts(call)
        t = by_call.setdefault(call["call"], {"call": call["call"]})
        t.update(n=n, note=note_of(call["user"]), orig=call["response"], orig_model=call["model"])
        t["prompts"] = {"old": [call["system"], call["user"]], "new": [system, user]}
    turns = [by_call[c["call"]] for c in calls]
    lock, sem = asyncio.Lock(), asyncio.Semaphore(PARALLEL)
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(
            model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
            max_tokens=p["max_tokens"], timeout=p["timeout_s"], max_retries=0,
            http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
            **({"reasoning_effort": p["effort"]} if p["effort"] else {}),
        )

        async def one(t: dict, version: str) -> None:
            if t.get(version, {}).get("text"):
                return
            async with sem:
                t[version] = await ask(llm, *t["prompts"][version])
            async with lock:
                saved.write_text(json.dumps(turns, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"第 {t['n']} 轮 {version}：{len(t[version].get('text', ''))} 字，{t[version]['seconds']} 秒{'，出错 ' + t[version]['error'] if t[version].get('error') else ''}")

        await asyncio.gather(*(one(t, v) for t in turns for v in ("old", "new")))
    report(out, turns, f"{p['name']}（{p['model']}）")
    print(f"对照页：{out / '对照.html'}")


if __name__ == "__main__":
    asyncio.run(main())
