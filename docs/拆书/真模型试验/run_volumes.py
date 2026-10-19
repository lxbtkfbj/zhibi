"""把 run_units.py 归好的单元归成卷（原书没分卷时，设计说明第 14.2 节第 5 条）。

在 backend 下用 `uv run --no-sync python run_volumes.py <结果文件夹> <书名> [是不是读到全书头了 yes/no]` 运行。
读结果文件夹里的 units.json，写 volumes.json。前一百章只归一次；整本书时每攒够一百章左右的单元归一次，没收尾的挂着。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_units import SYSTEM, check  # noqa: E402
from try_read import profile_row  # noqa: E402

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class Volume(BaseModel):
    first: int
    last: int
    title: str = Field(description="4-8 个字")
    text: str = Field(description="一段话，120 字以内")


class Volumes(BaseModel):
    volumes: list[Volume]
    open_from: int | None = Field(None, description="从第几章起还没收尾；都收完了就不填")


async def main() -> None:
    folder, book = Path(sys.argv[1]), sys.argv[2]
    final = len(sys.argv) > 3 and sys.argv[3] == "yes"
    units = json.loads((folder / "units.json").read_text(encoding="utf-8"))["units"]
    first, last = units[0]["first"], units[-1]["last"]
    bounds = {u["first"] for u in units} | {last + 1}
    lines = "\n".join(f"第 {u['first']}–{u['last']} 章「{u['title']}」：{u['text']}" for u in units)
    tail = "这是全书最后几个单元：全部归完，不留 open_from。" if final else "后面还有没读到的章：最后几个单元要是还没收在一次大高潮上，就留着不归。"
    user = ((HERE.parent / "提示词草稿" / "teardown_volumes.md").read_text(encoding="utf-8")
            .replace("{{title}}", book).replace("{{done_volumes}}", "（还没有）").replace("{{units}}", lines)
            .replace("{{tail_rule}}", tail).replace("{{first}}", str(first)))
    p = profile_row("A 3.8f")
    calls = []
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
                         timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
                         reasoning_effort="low")
        runnable = llm.with_structured_output(Volumes, method="function_calling", include_raw=True)
        for _ in range(3):
            started = time.monotonic()
            out = await runnable.ainvoke([SystemMessage(SYSTEM), HumanMessage(user)])
            usage = getattr(out["raw"], "usage_metadata", None) or {}
            parsed = out["parsed"]
            problem = f"解析失败：{out['parsing_error']}" if not parsed else check(
                [v.model_dump() for v in parsed.volumes], first, last, parsed.open_from)
            # 卷的分界只能落在单元的分界上
            if not problem and any(v.first not in bounds or v.last + 1 not in bounds for v in parsed.volumes):
                problem = "卷的分界拆开了单元"
            calls.append({"seconds": round(time.monotonic() - started, 1), "usage": usage, "error": problem})
            if not problem:
                break
            print(f"  归卷出错，再试：{problem[:200]}")
        else:
            print("  三次都不对，停下")
            return
    for v in parsed.volumes:
        print(f"第 {v.first}–{v.last} 章「{v.title}」：{v.text}")
    print(f"  {calls[-1]['seconds']} 秒，还没收尾从第 {parsed.open_from} 章起")
    result = {"volumes": [v.model_dump() for v in parsed.volumes], "open_from": parsed.open_from, "calls": calls}
    (folder / "volumes.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
