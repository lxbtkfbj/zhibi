"""用作者的真模型把一本书的前 N 章「逐章记」跑完（设计说明第 14.2 节第 4 条）。

在 backend 下用 `uv run --no-sync python run_read.py <prep_chapters.py 出的 json> <结果文件夹>` 运行。
- 一批四章左右，合起来一万二千字以内；一章超了就单独一批，不拆开一章。
- 第一批先单独跑，拿到主角和开头几个人；以后四批同时跑，每批开跑时带上已经读完的各批认出的人。
- 思考调低（reasoning_effort=low）；被限流（429）先等几秒再试；一批失败或漏章，漏的章一章一章再试，还不行跳过、最后列出来。
- 每批读完马上存成 batch_XXX.json，重跑时读过的批不重读。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from try_read import PROMPTS, ReadBatch, profile_row  # noqa: E402  try_read 里已经读好 .env、接上 backend

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

MAX_CHARS = 12000
PER_BATCH = 4
PARALLEL = 4
SYSTEM = "你是「执笔」编辑部的设定师，这次在拆别人写好的书：只照原文记，不评价、不改、不补。一律使用简体中文。"


def make_batches(chapters: list[dict]) -> list[list[dict]]:
    batches, cur = [], []
    for c in chapters:
        if cur and (len(cur) >= PER_BATCH or sum(len(x["text"]) for x in cur) + len(c["text"]) > MAX_CHARS):
            batches.append(cur)
            cur = []
        cur.append(c)
    if cur:
        batches.append(cur)
    return batches


class Roster:
    """已经认得的人：名字、别称、一句话。按读完的批合起来。"""

    def __init__(self) -> None:
        self.people: list[dict] = []

    def find(self, name: str) -> dict | None:
        for p in self.people:
            if name == p["name"] or name in p["aliases"]:
                return p
        return None

    def add(self, chapters: list[dict]) -> None:
        for ch in chapters:
            for person in ch["people"]:
                name, was = person["name"].strip(), person.get("was", "").strip()
                hit = self.find(name)
                old = self.find(was) if was else None
                if old and old is not hit:
                    # 这一章才认出是同一个人：旧的那条并过来
                    self.people.remove(old)
                    if hit:
                        hit["aliases"] += [n for n in [old["name"], *old["aliases"]] if n != hit["name"] and n not in hit["aliases"]]
                    else:
                        old["aliases"].append(old["name"])
                        old["name"] = name
                        self.people.append(old)
                        hit = old
                if not hit:
                    hit = {"name": name, "aliases": [], "note": person["shown"][:50]}
                    self.people.append(hit)
                for alias in person.get("also_called", []):
                    alias = alias.strip()
                    if alias and alias != hit["name"] and alias not in hit["aliases"]:
                        hit["aliases"].append(alias)

    def text(self) -> str:
        if not self.people:
            return "（还没有）"
        return "\n".join(
            f"- {p['name']}｜别称：{'、'.join(p['aliases']) or '无'}｜{p['note']}" for p in self.people
        )


class Reader:
    def __init__(self, book: str, out: Path, llm: ChatOpenAI) -> None:
        self.book, self.out, self.llm = book, out, llm
        self.template = (PROMPTS / "teardown_read.md").read_text(encoding="utf-8")
        self.runnable = llm.with_structured_output(ReadBatch, method="function_calling", include_raw=True)
        self.calls: list[dict] = []

    async def call(self, chapters: list[dict], roster: str, tag: str) -> list[dict]:
        """读一批，返回拿到的章；被限流等几秒再试，别的错直接当失败。"""
        body = "\n\n".join(f"「第 {c['index']} 章 {c['title']}」\n{c['text']}" for c in chapters)
        user = (
            self.template.replace("{{title}}", self.book)
            .replace("{{first}}", str(chapters[0]["index"]))
            .replace("{{last}}", str(chapters[-1]["index"]))
            .replace("{{roster}}", roster)
            .replace("{{chapters}}", body)
        )
        for attempt in range(6):
            started = time.monotonic()
            record = {"tag": tag, "chapters": [c["index"] for c in chapters], "chars": len(body), "roster_people": roster.count("\n- ") + (roster.startswith("- "))}
            try:
                out = await self.runnable.ainvoke([SystemMessage(SYSTEM), HumanMessage(user)])
            except Exception as exc:  # noqa: BLE001
                record.update(seconds=round(time.monotonic() - started, 1), error=f"{type(exc).__name__}: {str(exc)[:300]}")
                self.calls.append(record)
                if "429" in str(exc) or "rate" in str(exc).lower():
                    wait = 5 * (attempt + 1)
                    print(f"  {tag} 被限流，等 {wait} 秒再试")
                    await asyncio.sleep(wait)
                    continue
                print(f"  {tag} 失败：{record['error'][:150]}")
                return []
            usage = getattr(out["raw"], "usage_metadata", None) or {}
            record.update(seconds=round(time.monotonic() - started, 1), usage=usage)
            if out["parsing_error"] or not out["parsed"]:
                record["error"] = f"解析失败：{str(out['parsing_error'])[:300]}"
                self.calls.append(record)
                print(f"  {tag} {record['error'][:150]}")
                return []
            self.calls.append(record)
            want = {c["index"] for c in chapters}
            got = [c.model_dump() for c in out["parsed"].chapters if c.index in want]
            return list({c["index"]: c for c in got}.values())
        return []

    async def batch(self, n: int, chapters: list[dict], roster: Roster) -> dict:
        path = self.out / f"batch_{n:03d}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        roster_text = roster.text()
        started = time.monotonic()
        got = await self.call(chapters, roster_text, f"第 {n} 批")
        have = {c["index"] for c in got}
        missing = [c for c in chapters if c["index"] not in have]
        # 一批失败或漏了章：漏的一章一章再试
        for c in missing:
            print(f"  第 {n} 批漏了第 {c['index']} 章，单独再试")
            got += await self.call([c], roster_text, f"第 {n} 批·第 {c['index']} 章重试")
        got.sort(key=lambda c: c["index"])
        result = {
            "batch": n,
            "chapters": got,
            "skipped": sorted({c["index"] for c in chapters} - {c["index"] for c in got}),
            "roster_size": len(roster.people),
            "seconds": round(time.monotonic() - started, 1),
        }
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"第 {n} 批（第 {chapters[0]['index']}–{chapters[-1]['index']} 章）{result['seconds']} 秒，带 {result['roster_size']} 人，拿到 {len(got)} 章" + (f"，跳过 {result['skipped']}" if result["skipped"] else ""))
        return result


async def main() -> None:
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(source.read_text(encoding="utf-8"))
    batches = make_batches(data["chapters"])
    print(f"{len(data['chapters'])} 章分成 {len(batches)} 批")
    p = profile_row("A 3.8f")
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(
            model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
            timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
            reasoning_effort="low",
        )
        reader = Reader(data["book"], out, llm)
        roster = Roster()
        done: dict[int, dict] = {}
        # 第一批单独跑，后面每批开跑时带上已经读完的
        done[1] = await reader.batch(1, batches[0], roster)
        roster.add(done[1]["chapters"])
        queue = list(enumerate(batches, start=1))[1:]
        running: set[asyncio.Task] = set()
        while queue or running:
            while queue and len(running) < PARALLEL:
                n, chs = queue.pop(0)
                task = asyncio.create_task(reader.batch(n, chs, roster))
                task.n = n  # type: ignore[attr-defined]
                running.add(task)
            finished, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            for task in finished:
                result = task.result()
                done[task.n] = result  # type: ignore[attr-defined]
                roster.add(result["chapters"])
    total = round(time.monotonic() - started, 1)
    summary = {
        "seconds": total,
        "batches": len(batches),
        "calls": reader.calls,
        "skipped": sorted(i for r in done.values() for i in r["skipped"]),
        "roster": roster.people,
    }
    (out / "read_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    ins = sum(c.get("usage", {}).get("input_tokens", 0) for c in reader.calls)
    outs = sum(c.get("usage", {}).get("output_tokens", 0) for c in reader.calls)
    fails = sum(1 for c in reader.calls if c.get("error"))
    print(f"一共 {total} 秒，调用 {len(reader.calls)} 次（失败 {fails} 次），输入 {ins:,} token，输出 {outs:,} token，认得 {len(roster.people)} 人，跳过 {summary['skipped']}")


if __name__ == "__main__":
    asyncio.run(main())
