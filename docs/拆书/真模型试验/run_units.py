"""把 run_read.py 读好的章归成单元（设计说明第 14.2 节第 5 条）。

在 backend 下用 `uv run --no-sync python run_units.py <read 文件夹> <书名> [是不是读到全书头了 yes/no]` 运行。
四十章左右归一次；最后没收尾的几章挂着，和下一批章一起再归。结果写在 read 文件夹旁边的 units.json。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from try_read import profile_row  # noqa: E402
from try_units import Units  # noqa: E402

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

STEP = 40
SYSTEM = "你是「执笔」编辑部的主编，这次在拆别人写好的书：只照原文归纳，不评价、不改、不补。一律使用简体中文。"


def check(units: list[dict], first: int, last: int, open_from: int | None) -> str | None:
    """单元要从 first 起一个挨一个、不重叠不跳章，停在 open_from 前（或 last）。"""
    expect = first
    for u in units:
        if u["first"] != expect or u["last"] < u["first"]:
            return f"第 {u['first']}–{u['last']} 章接不上（应从第 {expect} 章起）"
        expect = u["last"] + 1
    end = (open_from - 1) if open_from else last
    if expect - 1 != end:
        return f"单元归到第 {expect - 1} 章，还没收尾从第 {open_from} 章起，中间对不上"
    return None


async def main() -> None:
    folder, book = Path(sys.argv[1]), sys.argv[2]
    final = len(sys.argv) > 3 and sys.argv[3] == "yes"
    chapters = sorted((c for f in folder.glob("batch_*.json") for c in json.loads(f.read_text(encoding="utf-8"))["chapters"]), key=lambda c: c["index"])
    by_index = {c["index"]: c for c in chapters}
    template = (HERE.parent / "提示词草稿" / "teardown_units.md").read_text(encoding="utf-8")
    p = profile_row("A 3.8f")
    done: list[dict] = []
    calls: list[dict] = []
    start = chapters[0]["index"]
    last_index = chapters[-1]["index"]
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
                         timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
                         reasoning_effort="low")
        runnable = llm.with_structured_output(Units, method="function_calling", include_raw=True)
        upto = start - 1
        open_from = start
        while open_from and open_from <= last_index:
            upto = min(upto + STEP, last_index)
            is_tail = upto == last_index and final
            group = [by_index[i] for i in range(open_from, upto + 1) if i in by_index]
            lines = "\n".join(f"第 {c['index']} 章：{c['summary']}｜{c['cool_point']}｜{c['hook']}" for c in group)
            done_text = "\n".join(f"第 {u['first']}–{u['last']} 章「{u['title']}」：{u['text']}" for u in done[-5:]) or "（还没有）"
            tail = "这是全书最后几章：全部归完，不留 open_from。" if is_tail else "后面还有没读到的章：最后一件事要是还没了结，就留着不归。"
            user = (template.replace("{{title}}", book).replace("{{done_units}}", done_text)
                    .replace("{{chapters}}", lines).replace("{{tail_rule}}", tail).replace("{{first}}", str(open_from)))
            for attempt in range(3):
                started = time.monotonic()
                out = await runnable.ainvoke([SystemMessage(SYSTEM), HumanMessage(user)])
                usage = getattr(out["raw"], "usage_metadata", None) or {}
                record = {"chapters": [open_from, upto], "seconds": round(time.monotonic() - started, 1), "usage": usage}
                parsed = out["parsed"]
                problem = f"解析失败：{out['parsing_error']}" if not parsed else check(
                    [u.model_dump() for u in parsed.units], open_from, upto, parsed.open_from)
                record["error"] = problem
                calls.append(record)
                if not problem:
                    break
                print(f"  第 {open_from}–{upto} 章归单元出错，再试：{problem[:200]}")
            else:
                print("  三次都不对，停下")
                break
            for u in parsed.units:
                done.append(u.model_dump())
                print(f"第 {u.first}–{u.last} 章「{u.title}」：{u.text}")
            print(f"  （这次第 {open_from}–{upto} 章，{record['seconds']} 秒，还没收尾从第 {parsed.open_from} 章起）")
            if upto == last_index:
                open_from = parsed.open_from
                break
            open_from = parsed.open_from or upto + 1
    result = {"units": done, "open_from": open_from, "calls": calls}
    (folder.parent / "units.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"归了 {len(done)} 个单元，最后挂着的从第 {open_from} 章起")


if __name__ == "__main__":
    asyncio.run(main())
