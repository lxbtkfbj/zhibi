"""用作者的真模型试「逐章记」：一批几章，看格式对不对、要多久、用多少 token、想得多不多。

只读作者库里的模型配置（不打印密钥），不写任何库。在 backend 下用 `uv run --no-sync python` 运行：
    python try_read.py <原文 json> <标签> [reasoning_effort]
原文 json 是 [{"index": 1, "title": "…", "text": "…"}, …]。结果写在同一个文件夹的 read_<标签>.json。
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
PROMPTS = HERE.parent / "提示词草稿"
# 结果里有原书的内容，放在不进 git 的 data 下面
OUT = Path("E:/Codex/zhibi/data/拆书试验")
OUT.mkdir(parents=True, exist_ok=True)
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
from pydantic import BaseModel, Field  # noqa: E402

from app.crypto import decrypt  # noqa: E402


class Person(BaseModel):
    name: str = Field(description="认得的人写名单上的名字；新人写原文最正式的叫法")
    also_called: list[str] = Field(default_factory=list, description="这一章原文里的别的叫法：外号、昵称、尊称、职务称呼")
    was: str = Field("", description="以前在名单里用别的名字记过、这一章才认出是同一个，写那个旧名字；没有留空")
    shown: str = Field(description="这一章写出了这个人什么，一两句")
    change: str = Field("", description="这一章里变了什么：实力与地位、在哪、处境、死了；没变留空")


class Thing(BaseModel):
    kind: Literal["地方", "势力", "物品功法", "金手指", "等级", "规矩", "秘密"]
    name: str
    note: str = Field(description="原文说了它什么，一句")
    secret: Literal["", "埋下", "揭开"] = ""


class Moment(BaseModel):
    who: str
    what: str = Field(description="做了什么")
    shows: str = Field(description="立住了这个人的什么")


class Wait(BaseModel):
    what: str
    action: Literal["立下", "提起", "兑现"]


class ReadChapter(BaseModel):
    index: int = Field(description="原文标的第几章")
    goal: str = Field(description="一句话：这一章要发生的事")
    scenes: list[str] = Field(description="两到四个场景，按先后，每个一句")
    cool_point: str = Field(description="看点，「哪一种：怎么做出来的」；没有爽点写「铺垫：……」或「情感：……」")
    hook: str = Field(description="结尾钩子，「哪一种：读者带着什么问题点下一章」；没有写「平收」")
    summary: str = Field(description="100-200 字摘要")
    feel: Literal["憋屈", "平", "爽", "大爽"]
    people: list[Person] = Field(default_factory=list)
    things: list[Thing] = Field(default_factory=list)
    moments: list[Moment] = Field(default_factory=list)
    waits: list[Wait] = Field(default_factory=list)
    tropes: list[str] = Field(default_factory=list)


class ReadBatch(BaseModel):
    chapters: list[ReadChapter]


def profile_row(name: str) -> dict:
    with psycopg.connect("postgresql://zhibi:zhibi@127.0.0.1:5433/zhibi") as conn:
        cur = conn.execute(
            "select base_url, model, api_key_encrypted, temperature, timeout_s, reasoning_effort, structured_method from llm_profiles where name = %s",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"作者库里没有叫「{name}」的模型配置")
        base_url, model, key, temperature, timeout_s, effort, method = row
    return {
        "name": name, "base_url": base_url, "model": model, "api_key": decrypt(key), "temperature": temperature,
        "timeout_s": timeout_s, "effort": effort, "method": method,
    }


# 「A 3.8f」后来改名了；试别的模型时设环境变量 TEARDOWN_PROFILE（模型配置的名字）
PROFILE = os.environ.get("TEARDOWN_PROFILE", "A fireworks/deepseek-v4.1-flash-1017")


async def main() -> None:
    source, label = sys.argv[1], sys.argv[2]
    effort = sys.argv[3] if len(sys.argv) > 3 else None
    chapters = json.loads(Path(source).read_text(encoding="utf-8"))
    p = profile_row(PROFILE)
    template = (PROMPTS / "teardown_read.md").read_text(encoding="utf-8")
    body = "\n\n".join(f"「第 {c['index']} 章 {c['title']}」\n{c['text']}" for c in chapters)
    user = (
        template.replace("{{title}}", chapters[0].get("book", "（书名）"))
        .replace("{{first}}", str(chapters[0]["index"]))
        .replace("{{last}}", str(chapters[-1]["index"]))
        .replace("{{roster}}", "（还没有）")
        .replace("{{chapters}}", body)
    )
    system = "你是「执笔」编辑部的设定师，这次在拆别人写好的书：只照原文记，不评价、不改、不补。一律使用简体中文。"
    kwargs = {"reasoning_effort": effort} if effort else {}
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(
            model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
            timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]), **kwargs,
        )
        runnable = llm.with_structured_output(ReadBatch, method="function_calling", include_raw=True)
        started = time.monotonic()
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(user)])
        seconds = time.monotonic() - started
    raw = out["raw"]
    usage = getattr(raw, "usage_metadata", None) or {}
    parsed = out["parsed"]
    result = {
        "label": label,
        "effort": effort,
        "chars_in": len(body),
        "seconds": round(seconds, 1),
        "usage": usage,
        "error": str(out["parsing_error"]) if out["parsing_error"] else None,
        "parsed": parsed.model_dump() if parsed else None,
        "raw_content": str(raw.content)[:2000] if not parsed else None,
    }
    (OUT / f"read_{label}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{label}：原文 {len(body)} 字，{seconds:.1f} 秒，用量 {usage}，{'解析成功' if parsed else '解析失败：' + str(out['parsing_error'])[:200]}")
    if parsed:
        print(f"  拿到 {len(parsed.chapters)} 章：", [c.index for c in parsed.chapters])


if __name__ == "__main__":
    asyncio.run(main())
