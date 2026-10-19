"""拿已经逐章记好的记录（run_read.py 的结果）试整理设定库，不读原文（设计说明第 14.2 节第 6、7 条；架构体检第四节第 1 条）。

看三件事：主要人物的角色卡写不写得满、地点等级势力秘密排不排得出来、「这本书好在哪」要的数字算不算得出。
每张卡、每份整理都让模型把记录里没有的栏目列进 missing，用来数缺什么。

在 backend 下用 `uv run --no-sync python try_settings.py <run_read 的结果文件夹> <输出文件夹> [单元 json]` 运行；
模型照 run_read.py，用环境变量 TEARDOWN_PROFILE 选模型配置。结果有原书的内容，放在不进 git 的 data 下面。
"""

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_read import EFFORT, Roster  # noqa: E402  try_read 里已经读好 .env、接上 backend
from try_read import PROFILE, PROMPTS, profile_row  # noqa: E402

import httpx  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.llm.router import parse_json_output, schema_instruction  # noqa: E402

SYSTEM = "你是「执笔」编辑部的设定师，这次在拆别人写好的书：只照前面记下的记录整理，不评价、不改、不补。一律使用简体中文。"
CARDS = 8  # 写全卡的人数（按出场章数）
PARALLEL = 4


# ---------- 角色卡 ----------


class Moment(BaseModel):
    chapter: int = Field(description="第几章")
    what: str = Field(description="做了什么")
    shows: str = Field(description="立住了这个人的什么")


class Tie(BaseModel):
    who: str = Field(description="对方的名字")
    relation: str = Field(description="什么关系，变过的写从什么变成什么")
    since_chapter: int | None = Field(None, description="从第几章起是这个关系，看不出留空")


class Now(BaseModel):
    location: str = Field("", description="此刻在哪")
    condition: str = Field("", description="此刻处境")
    want: str = Field("", description="此刻想要什么")
    alive: bool = Field(True, description="还活着没有")


class Card(BaseModel):
    name: str = Field(description="姓名")
    aliases: list[str] = Field(default_factory=list, description="别名")
    gender: str = Field(description="性别")
    age: str = Field(description="年龄")
    appearance: str = Field(description="外貌")
    personality: str = Field(description="性格与说话方式")
    background: str = Field(description="身世")
    goal: str = Field(description="想要什么")
    abilities: str = Field(description="能力")
    power: str = Field(description="实力与地位")
    belongs: str = Field(description="所属：哪个家族、门派、公司、圈子")
    weakness: str = Field(description="软肋")
    relation: str = Field(description="和主角的关系")
    growth: str = Field(description="成长：到目前为止从什么样变成什么样、第几章变的")
    now: Now = Field(description="此刻")
    moments: list[Moment] = Field(default_factory=list, description="名场面，两到四场")
    ties: list[Tie] = Field(default_factory=list, description="和书里别的人的关系")
    missing: list[str] = Field(default_factory=list, description="记录里没有、只好写「（记录里没有）」的栏目名")


# ---------- 世界 ----------


class Level(BaseModel):
    name: str
    note: str = Field(description="原文怎么说这一级")
    protagonist_chapter: int | None = Field(None, description="主角第几章到了这一级，看不出留空")


class Ladder(BaseModel):
    name: str = Field(description="这套等级叫什么，比如「修炼境界」")
    how_up: str = Field("", description="怎么往上升、难在哪")
    levels: list[Level] = Field(description="按高低排，低的在前")


class Place(BaseModel):
    name: str
    parent: str = Field("", description="属于哪里：上一级地方的名字，最大的留空")
    first_chapter: int | None = None
    note: str


class Faction(BaseModel):
    name: str
    what: str
    leader: str = ""
    members: list[str] = Field(default_factory=list)
    stance: str = Field("", description="和主角是敌是友")
    first_chapter: int | None = None


class Goldfinger(BaseModel):
    name: str
    what: str
    rules: str = Field("", description="规矩和限制、代价")
    first_chapter: int | None = None
    grows: str = Field("", description="后来怎么变强")


class Secret(BaseModel):
    name: str
    truth: str
    planted_chapter: int | None = None
    revealed_chapter: int | None = None


class Simple(BaseModel):
    name: str
    note: str
    first_chapter: int | None = None


class World(BaseModel):
    ladders: list[Ladder] = Field(default_factory=list, description="等级体系，可以有几套")
    places: list[Place] = Field(default_factory=list, description="地方")
    factions: list[Faction] = Field(default_factory=list, description="势力")
    goldfingers: list[Goldfinger] = Field(default_factory=list, description="金手指")
    secrets: list[Secret] = Field(default_factory=list, description="往事与秘密")
    items: list[Simple] = Field(default_factory=list, description="物品功法")
    rules: list[Simple] = Field(default_factory=list, description="规矩")
    missing: list[str] = Field(default_factory=list, description="拿不准、记录里看不出的，一句一条")


# ---------- 这本书好在哪 ----------


class Point(BaseModel):
    topic: str = Field(description="开头 / 节奏 / 变强 / 在等什么 / 桥段 / 立得住的人")
    text: str


class Merits(BaseModel):
    points: list[Point]
    missing: list[str] = Field(default_factory=list, description="想写却缺数字、缺记录的，一句一条")


class Caller:
    def __init__(self, llm: ChatOpenAI, method: str) -> None:
        self.llm, self.method = llm, method
        self.calls: list[dict] = []

    async def structured[T: BaseModel](self, schema: type[T], user: str, tag: str) -> T | None:
        for attempt in range(4):
            started = time.monotonic()
            record = {"tag": tag, "chars": len(user)}
            try:
                if self.method == "json_mode":
                    raw = await self.llm.bind(response_format={"type": "json_object"}).ainvoke(
                        [SystemMessage(SYSTEM + schema_instruction(schema)), HumanMessage(user)]
                    )
                    parsed = parse_json_output(schema, str(raw.content))
                else:
                    out = await self.llm.with_structured_output(schema, method="function_calling", include_raw=True).ainvoke(
                        [SystemMessage(SYSTEM), HumanMessage(user)]
                    )
                    raw, parsed = out["raw"], out["parsed"]
                    if parsed is None:
                        raise ValueError(f"解析失败：{out['parsing_error']}")
            except Exception as exc:  # noqa: BLE001
                record.update(seconds=round(time.monotonic() - started, 1), error=f"{type(exc).__name__}: {str(exc)[:300]}")
                self.calls.append(record)
                if "429" in str(exc) or "rate" in str(exc).lower():
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                if isinstance(exc, ValueError) and attempt < 2:
                    print(f"  {tag} 格式不对，再试")
                    continue
                print(f"  {tag} 失败：{record['error'][:150]}")
                return None
            record.update(seconds=round(time.monotonic() - started, 1), usage=getattr(raw, "usage_metadata", None) or {})
            self.calls.append(record)
            print(f"  {tag}：{record['seconds']} 秒")
            return parsed
        return None


def fill(template: str, **values: object) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def spans(numbers: list[int]) -> str:
    """[1,2,3,7,9,10] → 「1–3、7、9–10」"""
    out, start, prev = [], None, None
    for n in sorted(set(numbers)):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}–{prev}" if prev > start else str(start))
            start = prev = n
    if start is not None:
        out.append(f"{start}–{prev}" if prev > start else str(start))
    return "、".join(out)


def load(read_dir: Path) -> list[dict]:
    files = sorted(read_dir.glob("batch_*.json"))
    rows = [c for f in files for c in json.loads(f.read_text(encoding="utf-8"))["chapters"]]
    return sorted({c["index"]: c for c in rows}.values(), key=lambda c: c["index"])


def people_of(chapters: list[dict]) -> tuple[Roster, dict, dict]:
    """名单照读的时候的办法从各章记录重算（别称、旧名并起来），再把每章的人和名场面挂到名单上的人。"""
    roster = Roster()
    for c in chapters:
        roster.add([c])
    rows: dict[str, dict] = {}
    for c in chapters:
        for person in c["people"]:
            entry = roster.find(person["name"].strip())
            if entry is None and person.get("was"):
                entry = roster.find(person["was"].strip())
            if entry is None:
                continue
            rows.setdefault(entry["name"], {"entry": entry, "chapters": []})["chapters"].append((c["index"], person))
    moments: dict[str, list] = {}
    for c in chapters:
        for m in c["moments"]:
            entry = roster.find(m["who"].strip())
            if entry is not None:
                moments.setdefault(entry["name"], []).append((c["index"], m))
    return roster, rows, moments


def dossier_of(name: str, rows: dict, moments: dict) -> str:
    lines = []
    for index, person in rows[name]["chapters"]:
        line = f"第 {index} 章：{person['shown']}"
        if person.get("change"):
            line += f"（变化：{person['change']}）"
        lines.append(line)
    for index, m in moments.get(name, []):
        lines.append(f"第 {index} 章名场面：{m['what']}——立住了{m['shows']}")
    return "\n".join(lines)


def things_of(chapters: list[dict]) -> tuple[dict, dict]:
    groups: dict[tuple[str, str], list] = {}
    for c in chapters:
        for t in c["things"]:
            groups.setdefault((t["kind"], t["name"].strip()), []).append((c["index"], t["note"], t.get("secret", "")))
    # 只收再出现过的；金手指、等级、秘密一律收（第 14.2 节第 6 条）
    keep = {k: v for k, v in groups.items() if len({i for i, _, _ in v}) >= 2 or k[0] in ("金手指", "等级", "秘密")}
    return groups, keep


def things_text(keep: dict) -> str:
    order = ["等级", "金手指", "地方", "势力", "物品功法", "秘密", "规矩"]
    blocks = []
    for kind in order:
        items = [(name, rows) for (k, name), rows in keep.items() if k == kind]
        if not items:
            continue
        lines = [f"【{kind}】"]
        for name, rows in items:
            notes = "；".join(f"第 {i} 章{('（' + s + '）') if s else ''}：{note}" for i, note, s in rows)
            lines.append(f"- {name}（第 {spans([i for i, _, _ in rows])} 章）：{notes}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def facts_of(chapters: list[dict], rows: dict, moments: dict, protagonist: str, units: list[dict]) -> str:
    first = chapters[0]
    lines = [f"读到第 {chapters[-1]['index']} 章，共 {len(chapters)} 章。", f"主角：{protagonist}。"]
    lines.append(f"第 1 章摘要：{first['summary']}")
    lines.append("前三章的结尾钩子：" + "；".join(f"第 {c['index']} 章「{c['hook']}」" for c in chapters[:3]))
    gf = next(((c["index"], t["name"]) for c in chapters for t in c["things"] if t["kind"] == "金手指"), None)
    lines.append(f"金手指第一次出现：第 {gf[0]} 章「{gf[1]}」。" if gf else "记录里没有金手指。")
    cool = next((c for c in chapters if c["feel"] in ("爽", "大爽")), None)
    if cool:
        lines.append(f"第一次爽：第 {cool['index']} 章，看点「{cool['cool_point']}」。")
    feel = Counter(c["feel"] for c in chapters)
    lines.append("读者感觉（模型判的）：" + "，".join(f"{k} {feel.get(k, 0)} 章" for k in ("憋屈", "平", "爽", "大爽")) + "。")
    big = [c["index"] for c in chapters if c["feel"] == "大爽"]
    if big:
        lines.append(f"大爽在第 {'、'.join(map(str, big))} 章。")
    best, run = [], []
    for c in chapters:
        run = run + [c["index"]] if c["feel"] == "憋屈" else []
        if len(run) > len(best):
            best = run
    lines.append(f"最长连着憋屈：第 {best[0]}–{best[-1]} 章，{len(best)} 章。" if best else "没有憋屈的章。")
    if units:
        sizes = [u["last"] - u["first"] + 1 for u in units]
        lines.append(f"单元：{len(units)} 个，平均 {sum(sizes) / len(sizes):.1f} 章，最短 {min(sizes)} 章，最长 {max(sizes)} 章。")
        lines.append("各单元：" + "；".join(f"第 {u['first']}–{u['last']} 章「{u['title']}」" for u in units))
    changes = [(i, p["change"]) for i, p in rows.get(protagonist, {}).get("chapters", []) if p.get("change")]
    lines.append("主角各章的变化：\n" + ("\n".join(f"- 第 {i} 章：{ch}" for i, ch in changes) or "（没有）"))
    waits = [(c["index"], w["action"], w["what"]) for c in chapters for w in c["waits"]]
    lines.append("读者在等的事（各章立下、提起、兑现的）：\n" + ("\n".join(f"- 第 {i} 章{a}：{w}" for i, a, w in waits) or "（没有）"))
    tropes = Counter(t for c in chapters for t in c["tropes"])
    first_use = {}
    for c in chapters:
        for t in c["tropes"]:
            first_use.setdefault(t, c["index"])
    lines.append("用过的桥段（用了几章、第一次在第几章）：" + "；".join(f"{t} {n} 章（第 {first_use[t]} 章起）" for t, n in tropes.most_common(12)))
    top = sorted(moments.items(), key=lambda kv: -len(kv[1]))[:5]
    lines.append(
        "名场面最多的人：\n"
        + "\n".join(f"- {name}（{len(ms)} 场）：" + "；".join(f"第 {i} 章 {m['what']}——{m['shows']}" for i, m in ms[:4]) for name, ms in top)
    )
    return "\n".join(lines)


async def main() -> None:
    read_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    units = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))["units"] if len(sys.argv) > 3 else []
    out.mkdir(parents=True, exist_ok=True)
    chapters = load(read_dir)
    book = json.loads((read_dir.parent / "chapters.json").read_text(encoding="utf-8"))["book"]
    last = chapters[-1]["index"]
    roster, rows, moments = people_of(chapters)
    ranked = sorted(rows, key=lambda n: -len({i for i, _ in rows[n]["chapters"]}))
    protagonist = ranked[0]
    shared = roster.shared()
    groups, keep = things_of(chapters)
    print(f"《{book}》{len(chapters)} 章：名单 {len(roster.people)} 人，主角 {protagonist}；东西 {len(groups)} 样，再出现过的 {len(keep)} 样")

    p = profile_row(PROFILE)
    print(f"模型：{p['name']}（{p['model']}，{p['method']}）")
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=p["timeout_s"]) as client:
        llm = ChatOpenAI(
            model=p["model"], base_url=p["base_url"], api_key=p["api_key"], temperature=p["temperature"],
            timeout=p["timeout_s"], max_retries=0, http_async_client=client, http_client=httpx.Client(timeout=p["timeout_s"]),
            **({"reasoning_effort": EFFORT} if EFFORT else {}),
        )
        caller = Caller(llm, p["method"])
        gate = asyncio.Semaphore(PARALLEL)
        card_template = (PROMPTS / "teardown_card.md").read_text(encoding="utf-8")

        async def card(name: str) -> dict:
            entry = rows[name]["entry"]
            indexes = sorted({i for i, _ in rows[name]["chapters"]})
            user = fill(
                card_template, title=book, name=name, aliases="、".join(a for a in entry["aliases"] if a not in shared) or "无",
                count=len(indexes), chapters=f"第 {spans(indexes)} 章", protagonist=protagonist,
                dossier=dossier_of(name, rows, moments), last=last,
            )
            async with gate:
                got = await caller.structured(Card, user, f"角色卡·{name}")
            return {"name": name, "chapters": len(indexes), "input_chars": len(user), "card": got.model_dump() if got else None}

        world_user = fill(
            (PROMPTS / "teardown_world.md").read_text(encoding="utf-8"), title=book, protagonist=protagonist,
            protagonist_changes="\n".join(f"- 第 {i} 章：{p_['change']}" for i, p_ in rows[protagonist]["chapters"] if p_.get("change")) or "（没有）",
            things=things_text(keep),
        )
        facts = facts_of(chapters, rows, moments, protagonist, units)
        merits_user = fill((PROMPTS / "teardown_merits.md").read_text(encoding="utf-8"), title=book, last=last, facts=facts)

        async def world() -> World | None:
            async with gate:
                return await caller.structured(World, world_user, "整理设定")

        async def merits() -> Merits | None:
            async with gate:
                return await caller.structured(Merits, merits_user, "这本书好在哪")

        results = await asyncio.gather(*(card(n) for n in ranked[:CARDS]), world(), merits())
    cards, world_out, merits_out = results[:CARDS], results[-2], results[-1]
    total = round(time.monotonic() - started, 1)
    missing = Counter(m for c in cards if c["card"] for m in c["card"]["missing"])
    summary = {
        "book": book, "profile": p["name"], "chapters": len(chapters), "roster": len(roster.people), "protagonist": protagonist,
        "things": len(groups), "things_kept": len(keep), "seconds": total, "calls": caller.calls,
        "card_missing": missing.most_common(), "world_input_chars": len(world_user), "merits_input_chars": len(merits_user),
    }
    (out / "cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "world.json").write_text(json.dumps(world_out.model_dump() if world_out else None, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "merits.json").write_text(
        json.dumps({"facts": facts, "merits": merits_out.model_dump() if merits_out else None}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    ins = sum(c.get("usage", {}).get("input_tokens", 0) for c in caller.calls)
    outs = sum(c.get("usage", {}).get("output_tokens", 0) for c in caller.calls)
    fails = sum(1 for c in caller.calls if c.get("error"))
    print(f"一共 {total} 秒，调用 {len(caller.calls)} 次（失败 {fails} 次），输入 {ins:,} token，输出 {outs:,} token")
    print("角色卡里记录没有的栏目：", missing.most_common())


if __name__ == "__main__":
    asyncio.run(main())
