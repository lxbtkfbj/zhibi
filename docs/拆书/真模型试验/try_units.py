"""用作者的真模型试「归单元」：拿逐章记的结果，看分界、单元名和那段话像不像样。

在 backend 下用 `uv run --no-sync python try_units.py <read_xxx.json> <标签> <是不是最后几章 yes/no>` 运行。
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for line in Path("E:/Codex/zhibi/.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))
sys.path.insert(0, "E:/Codex/zhibi/backend")
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

sys.path.insert(0, str(HERE))
from try_read import profile_row  # noqa: E402  只借用读模型配置的那一段


class Unit(BaseModel):
    first: int
    last: int
    title: str = Field(description="4-8 个字")
    text: str = Field(description="一段话，120 字以内")


class Units(BaseModel):
    units: list[Unit]
    open_from: int | None = Field(None, description="从第几章起还没收尾；都收完了就不填")


async def main() -> None:
    source, label, final = sys.argv[1], sys.argv[2], sys.argv[3] == "yes"
    read = json.loads(Path(source).read_text(encoding="utf-8"))["parsed"]["chapters"]
    lines = "\n".join(f"第 {c['index']} 章：{c['summary']}｜{c['cool_point']}｜{c['hook']}" for c in read)
    tail = "这是全书最后几章：全部归完，不留 open_from。" if final else "后面还有没读到的章：最后一件事要是还没了结，就留着不归。"
    user = (
        (HERE.parent / "提示词草稿" / "teardown_units.md").read_text(encoding="utf-8")
        .replace("{{title}}", "窥命长生").replace("{{done_units}}", "（还没有）")
        .replace("{{chapters}}", lines).replace("{{tail_rule}}", tail).replace("{{first}}", str(read[0]["index"]))
    )
    p = profile_row("A 3.8f")
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
                         timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
                         reasoning_effort="low")
        started = time.monotonic()
        out = await llm.with_structured_output(Units, method="function_calling", include_raw=True).ainvoke(
            [SystemMessage("你是「执笔」编辑部的主编，这次在拆别人写好的书：只照原文归纳，不评价、不改、不补。一律使用简体中文。"), HumanMessage(user)]
        )
        seconds = time.monotonic() - started
    usage = getattr(out["raw"], "usage_metadata", None) or {}
    print(f"{label}：{seconds:.1f} 秒，用量 {usage.get('input_tokens')}/{usage.get('output_tokens')}")
    if out["parsed"]:
        for u in out["parsed"].units:
            print(f"  第 {u.first}–{u.last} 章「{u.title}」：{u.text}")
        print("  还没收尾：", out["parsed"].open_from)
    else:
        print("  解析失败", out["parsing_error"])


if __name__ == "__main__":
    asyncio.run(main())
