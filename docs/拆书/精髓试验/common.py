"""精髓试验的公共部分：读作者库（只读）、调作者指定的模型、套提示词。

不往作者库里写任何东西（不走 LLMRouter，免得记进 llm_calls）。结果和用量写到 data/拆书试验/精髓/ 下面（不进 git）。
在 backend 下用 `uv run --no-sync python ../docs/拆书/精髓试验/<脚本>.py` 运行。
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "提示词"
APP_PROMPTS = Path("E:/Codex/zhibi/backend/app/prompts")
OUT = Path("E:/Codex/zhibi/data/拆书试验/精髓")
OUT.mkdir(parents=True, exist_ok=True)
for line in Path("E:/Codex/zhibi/.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))
sys.path.insert(0, "E:/Codex/zhibi/backend")
sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402
import openai  # noqa: E402
import psycopg  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from app.crypto import decrypt  # noqa: E402
from app.llm.router import ResolvedProfile, build_chat_model, parse_json_output, schema_instruction  # noqa: E402

DSN = "postgresql://zhibi:zhibi@127.0.0.1:5433/zhibi"
PROFILE = os.environ.get("TEARDOWN_PROFILE", "【Alicia】gemini-3.8-flash")
VARIABLE = re.compile(r"\{\{(\w+)\}\}")


def db():
    conn = psycopg.connect(DSN)
    conn.execute("set default_transaction_read_only = on")
    return conn


def profile() -> ResolvedProfile:
    with db() as conn:
        row = conn.execute(
            "select name, provider, base_url, api_key_encrypted, model, temperature, max_tokens, structured_method, timeout_s"
            " from llm_profiles where name = %s",
            (PROFILE,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"作者库里没有叫「{PROFILE}」的模型配置")
    name, provider, base_url, key, model, temperature, max_tokens, method, timeout_s = row
    return ResolvedProfile(
        name=name, provider=provider, base_url=base_url, api_key=decrypt(key) if key else "", model=model,
        temperature=temperature, max_tokens=max_tokens, structured_method=method, timeout_s=timeout_s,
    )


def template(name: str) -> str:
    path = PROMPTS / f"{name}.md"
    return (path if path.exists() else APP_PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values) -> str:
    text = template(name)
    missing = sorted(set(VARIABLE.findall(text)) - values.keys())
    if missing:
        raise KeyError(f"{name} 缺少变量：{missing}")
    text = VARIABLE.sub(lambda m: str(values[m.group(1)]).strip(), text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


TEARDOWN_SYSTEM = None


def teardown_system() -> str:
    global TEARDOWN_SYSTEM
    if TEARDOWN_SYSTEM is None:
        TEARDOWN_SYSTEM = render("persona_teardown", rules=template("rules").strip())
    return TEARDOWN_SYSTEM


class Caller:
    """一个并发上限、三次解析重试、429 退避；每次调用的用量追加进 calls.jsonl。"""

    def __init__(self, folder: Path, parallel: int = 4):
        self.p = profile()
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(parallel)
        self.log = folder / "calls.jsonl"
        self.client = httpx.Client(timeout=self.p.timeout_s)
        self.aclient = httpx.AsyncClient(timeout=self.p.timeout_s)
        self.llm = build_chat_model(self.p, http_client=self.client, http_async_client=self.aclient)

    async def close(self):
        await self.aclient.aclose()
        self.client.close()

    async def once(self, schema, system: str, user: str):
        method = self.p.structured_method
        if method == "json_mode":
            raw = await self.llm.bind(response_format={"type": "json_object"}).ainvoke(
                [SystemMessage(system + schema_instruction(schema)), HumanMessage(user)]
            )
            return raw, parse_json_output(schema, str(raw.content))
        runnable = self.llm.with_structured_output(schema, method=method, include_raw=True)
        out = await runnable.ainvoke([SystemMessage(system), HumanMessage(user)])
        if out["parsed"] is None:
            raise ValueError(str(out["parsing_error"] or "没有按结构化格式输出"))
        return out["raw"], out["parsed"]

    async def call(self, schema, user: str, label: str, system: str | None = None, check=None):
        system = system or teardown_system()
        original, problem, limited = user, "", 0
        async with self.sem:
            for attempt in range(1, 4):
                started = time.monotonic()
                try:
                    raw, parsed = await self.once(schema, system, user)
                    problem = check(parsed) if check else None
                    usage = getattr(raw, "usage_metadata", None) or {}
                    self.write(label, attempt, started, usage, problem or "")
                    if not problem:
                        return parsed
                except openai.APIStatusError as exc:
                    self.write(label, attempt, started, {}, f"HTTP {exc.status_code}")
                    if exc.status_code == 429 and limited < 5:
                        limited += 1
                        await asyncio.sleep(min(5 * 2 ** (limited - 1), 40))
                        continue
                    problem = str(exc)[:300]
                except Exception as exc:  # 解析失败照样重来
                    problem = str(exc)[:300]
                    self.write(label, attempt, started, {}, problem)
                user = original + f"\n\n【上次写得不对】{problem}。请照要求重新写。"
        raise RuntimeError(f"{label} 三次都不行：{problem}")

    def write(self, label, attempt, started, usage, error):
        row = {
            "label": label, "attempt": attempt, "seconds": round(time.monotonic() - started, 1),
            "input": usage.get("input_tokens"), "output": usage.get("output_tokens"), "error": error,
        }
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  {label}#{attempt} {row['seconds']}s in={row['input']} out={row['output']} {error[:120]}")


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
