"""拆书的独立流水线：逐章记和串行归大纲并行，不使用 LangGraph。"""

import asyncio
import contextlib
import logging
import math
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.agents import schemas as s
from app.graphs.deps import JobCancelled, cancel_key
from app.llm.router import TeardownPolicy
from app.models import Book, Chapter, Job, PlotUnit, Volume
from app.prompts import render
from app.services import book_saves
from app.services.meeting import Emitter, job_dict, publish
from app.services.teardown_roster import Roster

log = logging.getLogger(__name__)
MAX_CHARS = 12000
PER_BATCH = 4
FEEL = {"憋屈": -2, "平": 0, "爽": 1, "大爽": 2}
READ_FIELDS = ("feel", "people", "things", "moments", "waits", "tropes")


def make_batches(chapters: list[Any]) -> list[list[Any]]:
    batches, current, chars = [], [], 0
    for chapter in chapters:
        content = chapter["text"] if isinstance(chapter, dict) else chapter.content
        if current and (len(current) >= PER_BATCH or chars + len(content) > MAX_CHARS):
            batches.append(current)
            current, chars = [], 0
        current.append(chapter)
        chars += len(content)
    if current:
        batches.append(current)
    return batches


def chapter_text(chapters: list[Chapter]) -> str:
    return "\n\n".join(f"「第 {c.index} 章{' ' + c.title if c.title else ''}」\n{c.content}" for c in chapters)


def unit_tail_rule(last: int, total: int, original: bool, volume_last: int) -> str:
    if last == total:
        return "这是全书最后几章：全部归完，不留 open_from。"
    if original and last == volume_last:
        return "这几章是原书这一卷的最后几章：全部归完，不留 open_from。"
    return "后面还有没读到的章：最后一件事要是还没了结，就留着不归。"


def check_groups(
    groups: list[Any],
    first: int,
    last: int,
    open_from: int | None,
    *,
    close: bool = False,
    bounds: set[int] | None = None,
) -> str | None:
    """严格检查覆盖范围，也检查 open_from 本身，避免空输出绕过检查。"""
    if open_from is not None and not first <= open_from <= last + 1:
        return f"还没收尾从第 {open_from} 章起，不在第 {first}–{last} 章里"
    if close and open_from is not None:
        return "这次必须全部归完，不留 open_from"
    expect = first
    for group in groups:
        a, b = (group["first"], group["last"]) if isinstance(group, dict) else (group.first, group.last)
        if a != expect or b < a or b > last:
            return f"第 {a}–{b} 章接不上（应从第 {expect} 章起）"
        if bounds is not None and (a not in bounds or b + 1 not in bounds):
            return "卷的分界拆开了单元"
        expect = b + 1
    end = open_from - 1 if open_from is not None else last
    if expect - 1 != end:
        return f"单元归到第 {expect - 1} 章，还没收尾从第 {open_from} 章起，中间对不上"
    if bounds is not None and open_from is not None and open_from not in bounds:
        return "卷的分界拆开了单元"
    return None


def one_line(error: Any) -> str:
    return " ".join(str(error).split())[:300] or "模型没有返回记录"


class TeardownStopped(Exception):
    def __init__(self, reason: str, note: str) -> None:
        super().__init__(note)
        self.reason, self.note = reason, note


class Runner:
    def __init__(self, job_id, sm, redis, router) -> None:
        self.job_id, self.sm, self.redis, self.router = job_id, sm, redis, router
        self.policy = TeardownPolicy()
        self.book_id = None
        self.target = self.total = 0
        self.original = False
        self.title = ""
        self.active: dict[int, list[int]] = {}
        self.history: deque[tuple[int, float, float]] = deque(maxlen=5)
        self.batches_done = 0
        self.initial_failures: dict[int, str] = {}
        self.stop: TeardownStopped | None = None
        self.reading_done = False
        self.changed = asyncio.Event()
        self.progress_lock = asyncio.Lock()
        self.last_refresh: float | None = None
        self.tried_units: set[tuple[int, int]] = set()
        self.tried_volumes: set[tuple[int, int]] = set()
        self.calls: list[dict] = []
        self.retry_failed_only = False
        self.retry_previous: dict | None = None

    async def initialize(self, book_id: uuid.UUID | None = None) -> None:
        async with self.sm() as session:
            job = await session.get(Job, self.job_id) if self.job_id else None
            if book_id is None:
                if job is None:
                    raise ValueError("拆书任务不存在")
                book_id = job.book_id
            book = await session.get(Book, book_id)
            if book is None or book.source != "teardown":
                raise ValueError("只能拆导入的拆书书籍")
            chapters = list(
                await session.scalars(select(Chapter).where(Chapter.book_id == book_id).order_by(Chapter.index))
            )
            self.book_id, self.title = book_id, book.title
            self.total = max((c.index for c in chapters), default=0)
            self.target = min(int((book.teardown or {}).get("upto") or self.total), self.total)
            self.original = bool((book.teardown or {}).get("original_volumes"))
            self.retry_failed_only = bool(job and (job.params or {}).get("retry_failed_only"))
            previous = (job.params or {}).get("previous_teardown", {}) if job else {}
            if self.retry_failed_only and previous.get("stage") == "stopped":
                self.retry_previous = previous
            self.router.book_id = book_id

    async def snapshot(self):
        async with self.sm() as session:
            book = await session.get(Book, self.book_id)
            chapters = list(
                await session.scalars(select(Chapter).where(Chapter.book_id == self.book_id).order_by(Chapter.index))
            )
            units = list(
                await session.scalars(select(PlotUnit).where(PlotUnit.book_id == self.book_id).order_by(PlotUnit.index))
            )
            volumes = list(
                await session.scalars(select(Volume).where(Volume.book_id == self.book_id).order_by(Volume.index))
            )
        return book, chapters, units, volumes

    async def cancelled(self) -> bool:
        return bool(self.job_id and await self.redis.exists(cancel_key(self.job_id)))

    async def should_stop(self) -> bool:
        return self.stop is not None or await self.cancelled()

    async def progress(self, doing: str = "read", **extra) -> None:
        if not self.job_id:
            return
        async with self.progress_lock:
            _, chapters, _, _ = await self.snapshot()
            read = sum(bool((c.teardown or {}).get("read_version")) for c in chapters if c.index <= self.target)
            failed = [c.index for c in chapters if c.index <= self.target and "read_failed" in (c.teardown or {})]
            units_upto = max((c.index for c in chapters if c.unit_id), default=0)
            eta = None
            if self.batches_done >= 2 and self.history:
                done = sum(item[0] for item in self.history)
                seconds = max(item[2] for item in self.history) - min(item[1] for item in self.history)
                remaining = max(0, self.target - read - len(failed))
                eta = round(remaining / (done / seconds) if done and seconds else 0)
                eta += (
                    math.ceil(max(0, self.target - units_upto) / 40) + math.ceil(max(0, self.target - units_upto) / 100)
                ) * 30
            indices = [n for batch in self.active.values() for n in batch]
            data = dict(
                doing=doing,
                reading=[min(indices), max(indices)] if indices else None,
                read=read,
                target=self.target,
                total=self.total,
                units_upto=units_upto,
                parallel=self.policy.parallel,
                eta_seconds=eta,
                failed=failed,
            )
            data.update(extra)
            async with self.sm() as session:
                job = await session.get(Job, self.job_id)
                if job is None:
                    return
                job.pending = {"teardown": data}
                await session.commit()
                await session.refresh(job)
                await publish(self.redis, self.book_id, "job", job_dict(job))

    async def refresh(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or self.last_refresh is None or now - self.last_refresh >= 60:
            await publish(
                self.redis,
                self.book_id,
                "teardown_saved",
                {"book_id": str(self.book_id), "job_id": str(self.job_id) if self.job_id else None},
            )
            self.last_refresh = now

    async def call(self, schema, template, purpose: str, **values):
        user = render(template, **values)
        return await self.call_user(schema, user, purpose)

    async def call_user(self, schema, user: str, purpose: str):
        system = render("persona_teardown", rules=render("rules"))
        started = time.monotonic()
        try:
            result = await self.router.structured(
                "teardown", schema, system, user, purpose=purpose, teardown_policy=self.policy
            )
        except Exception as exc:
            self.calls.append({"purpose": purpose, "seconds": time.monotonic() - started, "error": one_line(exc)})
            raise
        self.calls.append({"purpose": purpose, "seconds": time.monotonic() - started, "error": ""})
        return result

    async def read_call(self, chapters: list[Chapter], roster: str) -> tuple[dict[int, Any], str]:
        try:
            result = await self.call(
                s.TeardownRead,
                "teardown_read",
                "拆书：读原文",
                title=self.title,
                first=str(chapters[0].index),
                last=str(chapters[-1].index),
                chapters=chapter_text(chapters),
                roster=roster,
            )
        except Exception as exc:
            return {}, one_line(exc)
        want, found = {c.index for c in chapters}, {}
        for item in result.chapters:
            if item.index in want and item.index not in found:
                found[item.index] = item
        return found, "模型漏了这一批的章" if len(found) != len(want) else ""

    async def store_chapter(self, chapter_id, record=None, error: str = "") -> None:
        async with self.sm() as session:
            chapter = await session.get(Chapter, chapter_id)
            if chapter is None:
                return
            data = dict(chapter.teardown or {})
            if record is None:
                data["read_failed"] = {"at": datetime.now(UTC).isoformat(), "error": error}
            else:
                value = record.model_dump()
                outline = dict(chapter.outline or {})
                outline.update({key: value[key] for key in ("goal", "scenes", "cool_point", "hook")})
                outline["emotion"] = FEEL[value["feel"]]
                chapter.outline, chapter.summary = outline, value["summary"]
                data.update(
                    read={key: value[key] for key in READ_FIELDS}, read_version=1, read_at=datetime.now(UTC).isoformat()
                )
                data.pop("read_failed", None)
            chapter.teardown = data
            await session.commit()

    async def read_batch(self, number: int, chapters: list[Chapter]) -> None:
        started = time.monotonic()
        self.active[number] = [c.index for c in chapters]
        await self.progress()
        _, existing, _, _ = await self.snapshot()
        roster = Roster()
        roster.add(
            [
                {"index": c.index, **((c.teardown or {}).get("read") or {})}
                for c in existing
                if (c.teardown or {}).get("read_version")
            ]
        )
        roster_text = roster.text("\n".join(c.content for c in chapters))
        found, error = await self.read_call(chapters, roster_text)
        # 「整批失败」按首轮结果记，单章补读不掩盖模型开头不适用。
        if number <= 3 and not found:
            self.initial_failures[number] = error
            if len(self.initial_failures) >= 2:
                first_error = self.initial_failures[min(self.initial_failures)]
                self.stop = TeardownStopped(
                    "model",
                    f"开头几批模型连着出错（{first_error}），停下了。可以在系统设置的模型分工里给「拆书」换一个模型，再点「接着拆」。",
                )
        # 首轮成功的先落库，不能被别的章的补读拖住。
        for chapter in chapters:
            if chapter.index in found:
                await self.store_chapter(chapter.id, found[chapter.index])
        success = len(found)
        for chapter in chapters:
            if chapter.index in found:
                continue
            single, chapter_error = await self.read_call([chapter], roster_text)
            record = single.get(chapter.index)
            await self.store_chapter(chapter.id, record, chapter_error or "模型没有返回这一章")
            success += record is not None
        self.active.pop(number, None)
        self.batches_done += 1
        self.history.append((success, started, time.monotonic()))
        await self.progress()
        await self.refresh()
        self.changed.set()

    async def read_chapters(self, chapters: list[Chapter], *, first_alone: bool) -> None:
        batches = deque(enumerate(make_batches(chapters), 1))
        running: set[asyncio.Task] = set()
        try:
            if first_alone and batches and not await self.should_stop():
                number, batch = batches.popleft()
                await self.read_batch(number, batch)
            while batches or running:
                while batches and len(running) < self.policy.parallel and not await self.should_stop():
                    number, batch = batches.popleft()
                    running.add(asyncio.create_task(self.read_batch(number, batch)))
                if not running:
                    break
                done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        finally:
            # 取消/其他异常也先等手上几批存好，不能留下后台游离写入。
            if running:
                await asyncio.gather(*running, return_exceptions=True)

    @staticmethod
    def unit_ranges(chapters, units) -> dict:
        out = {}
        for unit in units:
            indices = [c.index for c in chapters if c.unit_id == unit.id]
            if indices:
                out[unit.id] = (min(indices), max(indices))
        return out

    @staticmethod
    def unit_lines(units, ranges) -> str:
        return (
            "\n".join(
                f"第 {ranges[u.id][0]}–{ranges[u.id][1]} 章「{u.title}」：{u.summary}" for u in units if u.id in ranges
            )
            or "（还没有）"
        )

    @staticmethod
    def volume_lines(volumes, chapters) -> str:
        lines = []
        for volume in volumes:
            indices = [c.index for c in chapters if c.volume_id == volume.id]
            if indices:
                lines.append(
                    f"第 {volume.index} 卷「{volume.title}」（第 {min(indices)}–{max(indices)} 章）：{volume.summary}"
                )
        return "\n".join(lines) or "（还没有）"

    def ready_prefix(
        self, chapters: list[Chapter], *, final: bool, neighbors: list[Chapter] | None = None
    ) -> list[Chapter]:
        ready = []
        by_index = (
            {c.index: c for c in neighbors if c is not None}
            if neighbors is not None
            else {c.index: c for c in chapters}
        )
        for chapter in chapters:
            if ready and chapter.index != ready[-1].index + 1:
                break
            data = chapter.teardown or {}
            valid = bool(data.get("read_version"))
            if not valid and "read_failed" in data:
                before = by_index.get(chapter.index - 1)
                after = by_index.get(chapter.index + 1)
                # 已经完成本轮重试的缺章，收尾时也要能列出并归入结构。
                valid = final or bool(
                    before
                    and after
                    and (before.teardown or {}).get("read_version")
                    and (after.teardown or {}).get("read_version")
                )
            if not valid:
                break
            ready.append(chapter)
        return ready

    async def group_once(self, *, final: bool = False) -> bool:
        book, chapters, units, volumes = await self.snapshot()
        ranges = self.unit_ranges(chapters, units)
        for volume in volumes:
            volume_chapters = [c for c in chapters if c.volume_id == volume.id]
            candidates = [c for c in volume_chapters if not c.unit_id and c.index <= self.target]
            if not candidates:
                continue
            ready = self.ready_prefix(candidates, final=final, neighbors=volume_chapters)
            if not ready or (
                len(ready) < 40 and not final and ready[-1].index != max(c.index for c in volume_chapters)
            ):
                return False
            ready = ready[:60]
            a, b = ready[0].index, ready[-1].index
            if (a, b) in self.tried_units:
                return False
            self.tried_units.add((a, b))
            tail = unit_tail_rule(b, self.total, self.original, max(c.index for c in volume_chapters))
            done = sorted(
                [u for u in units if u.id in ranges and (not self.original or u.volume_id == volume.id)],
                key=lambda u: ranges[u.id][0],
            )[-5:]
            lines = []
            for chapter in ready:
                if not (chapter.teardown or {}).get("read_version"):
                    lines.append(f"第 {chapter.index} 章：（这一章没读成，章名「{chapter.title}」）")
                else:
                    outline = chapter.outline or {}
                    lines.append(
                        f"第 {chapter.index} 章：{chapter.summary}｜{outline.get('cool_point', '')}｜{outline.get('hook', '')}"
                    )
            user = render(
                "teardown_units",
                title=self.title,
                first=str(a),
                done_units=self.unit_lines(done, ranges),
                chapters="\n".join(lines),
                tail_rule=tail,
            )
            await self.progress("units", range=[a, b])
            parsed = await self.validated(
                s.TeardownUnits,
                user,
                "拆书：归单元",
                a,
                b,
                close=b == self.total or (self.original and b == max(c.index for c in volume_chapters)),
            )
            if await self.should_stop():
                return False
            async with self.sm() as session:
                alive = await session.scalar(select(Book).where(Book.id == self.book_id).with_for_update())
                if alive is None or await self.should_stop():
                    return False
                next_index = max((u.index for u in units if u.volume_id == volume.id), default=0) + 1
                for offset, item in enumerate(parsed.units):
                    unit = PlotUnit(
                        book_id=self.book_id,
                        volume_id=volume.id,
                        index=next_index + offset,
                        title=item.title,
                        summary=item.text,
                        chapter_count=item.last - item.first + 1,
                        status="done",
                    )
                    session.add(unit)
                    await session.flush()
                    for chapter in ready:
                        if item.first <= chapter.index <= item.last:
                            row = await session.get(Chapter, chapter.id)
                            if row:
                                row.unit_id = unit.id
                await session.commit()
            await self.refresh(force=True)
            await self.progress()
            return True
        return False

    async def validated(
        self, schema, user: str, purpose: str, a: int, b: int, *, close: bool = False, bounds: set[int] | None = None
    ):
        original = user
        for _ in range(3):
            try:
                parsed = await self.call_user(schema, user, purpose)
                groups = parsed.units if schema is s.TeardownUnits else parsed.volumes
                problem = check_groups(groups, a, b, parsed.open_from, close=close, bounds=bounds)
            except Exception as exc:
                problem = one_line(exc)
            if not problem:
                return parsed
            user = original + f"\n\n【上次归得不对】{problem}。请照要求重新归。"
        kind = "单元" if schema is s.TeardownUnits else "卷"
        raise TeardownStopped("error", f"主编归第 {a}–{b} 章的{kind}归了三次都对不上，停下了。点「接着拆」再试一次。")

    async def volumes_once(self, *, final: bool = False) -> bool:
        book, chapters, units, volumes = await self.snapshot()
        ranges = self.unit_ranges(chapters, units)
        if self.original:
            for volume in volumes:
                own = [c for c in chapters if c.volume_id == volume.id]
                if not own or volume.summary or not all(c.unit_id for c in own):
                    continue
                await self.progress("volumes")
                a, b = own[0].index, own[-1].index
                tail = (
                    f"这是文件里最后一卷，原书可能还没写完：卷末要是没收在一次大高潮上，照读到的写，最后一句写「到第 {b} 章还没收住」。"
                    if volume.id == volumes[-1].id
                    else ""
                )
                result = await self.call(
                    s.TeardownVolumeText,
                    "teardown_volume_text",
                    "拆书：写卷",
                    title=self.title,
                    index=str(volume.index),
                    volume_title=volume.title,
                    first=str(a),
                    last=str(b),
                    done_volumes=self.volume_lines([v for v in volumes if v.index < volume.index][-3:], chapters),
                    units=self.unit_lines([u for u in units if u.volume_id == volume.id], ranges),
                    tail_rule=tail,
                )
                if await self.should_stop():
                    return False
                async with self.sm() as session:
                    alive = await session.scalar(select(Book).where(Book.id == self.book_id).with_for_update())
                    if alive is None or await self.should_stop():
                        return False
                    row = await session.get(Volume, volume.id)
                    if row:
                        row.summary, row.status = result.text, "done"
                    await session.commit()
                await self.refresh(force=True)
                return True
            return False
        open_id = (book.teardown or {}).get("open_volume_id")
        if not open_id:
            return False
        volume = next((v for v in volumes if str(v.id) == str(open_id)), None)
        own = (
            sorted([u for u in units if u.volume_id == volume.id and u.id in ranges], key=lambda u: ranges[u.id][0])
            if volume
            else []
        )
        if not own or (sum(u.chapter_count for u in own) < 100 and not final):
            return False
        a, b = ranges[own[0].id][0], ranges[own[-1].id][1]
        if (a, b) in self.tried_volumes:
            return False
        self.tried_volumes.add((a, b))
        close = b == self.total
        tail = (
            "这是全书最后几个单元：全部归完，不留 open_from。"
            if close
            else "后面还有没读到的章：最后几个单元要是还没收在一次大高潮上，就留着不归。"
        )
        user = render(
            "teardown_volumes",
            title=self.title,
            first=str(a),
            done_volumes=self.volume_lines([v for v in volumes if v.index < volume.index][-3:], chapters),
            units=self.unit_lines(own, ranges),
            tail_rule=tail,
        )
        await self.progress("volumes")
        parsed = await self.validated(
            s.TeardownVolumes, user, "拆书：归卷", a, b, close=close, bounds={ranges[u.id][0] for u in own} | {b + 1}
        )
        if await self.should_stop():
            return False
        if parsed.volumes:
            await self.store_volumes(volume, parsed, chapters, own, ranges)
        await self.refresh(force=True)
        await self.progress()
        return True

    async def store_volumes(self, opened, parsed, chapters, units, ranges) -> None:
        # 没有 open_from 但还有未来的未归单元章时，保留真实的「还没收尾」行。
        remaining = [c for c in chapters if c.volume_id == opened.id and c.index > parsed.volumes[-1].last]
        reuse_last = parsed.open_from is None and not remaining
        insert_count = len(parsed.volumes) - int(reuse_last)
        async with self.sm() as session:
            alive = await session.scalar(select(Book).where(Book.id == self.book_id).with_for_update())
            if alive is None or await self.should_stop():
                return
            later = list(
                await session.scalars(
                    select(Volume)
                    .where(Volume.book_id == self.book_id, Volume.index >= opened.index)
                    .order_by(Volume.index.desc())
                )
            )
            for row in later:
                row.index += insert_count
                await session.flush()
            open_row = await session.get(Volume, opened.id)
            for offset, item in enumerate(parsed.volumes):
                if reuse_last and offset == len(parsed.volumes) - 1:
                    new = open_row
                    new.title, new.summary, new.chapter_count, new.status = (
                        item.title,
                        item.text,
                        item.last - item.first + 1,
                        "done",
                    )
                else:
                    new = Volume(
                        book_id=self.book_id,
                        index=opened.index + offset,
                        title=item.title,
                        summary=item.text,
                        chapter_count=item.last - item.first + 1,
                        status="done",
                    )
                    session.add(new)
                    await session.flush()
                moved_units = [u for u in units if item.first <= ranges[u.id][0] and ranges[u.id][1] <= item.last]
                for index, unit in enumerate(moved_units, 1):
                    row = await session.get(PlotUnit, unit.id)
                    row.volume_id, row.index = new.id, index
                for chapter in chapters:
                    if item.first <= chapter.index <= item.last:
                        row = await session.get(Chapter, chapter.id)
                        row.volume_id = new.id
            if reuse_last:
                book = await session.get(Book, self.book_id)
                book.teardown = {**book.teardown, "open_volume_id": None}
            else:
                open_row.chapter_count = sum(
                    c.volume_id == opened.id and c.index > parsed.volumes[-1].last for c in chapters
                )
                # 原序号不会与新卷碰撞；剩下单元的序号可有空档，但显示次序不变。
            await session.commit()

    async def grouping(self) -> None:
        try:
            while True:
                await self.changed.wait()
                self.changed.clear()
                if await self.should_stop():
                    return
                while not await self.should_stop():
                    # 已有足够单元的旧卷先收，不能越过去先归后面章节的单元。
                    if await self.volumes_once(final=self.reading_done):
                        continue
                    if await self.group_once(final=self.reading_done):
                        continue
                    break
                if self.reading_done:
                    return
        except TeardownStopped as exc:
            self.stop = exc
        except Exception as exc:
            self.stop = TeardownStopped(
                "error", f"拆的时候出错了（{one_line(exc)}），停下了。点「接着拆」从停的地方往下拆，读过的不重读。"
            )
            log.exception("拆书 %s 归大纲失败", self.book_id)

    async def run(self) -> None:
        await self.initialize()
        async with self.sm() as session:
            book = await session.scalar(select(Book).where(Book.id == self.book_id).with_for_update())
            job = await session.scalar(select(Job).where(Job.id == self.job_id).with_for_update())
            if job is None or job.status in ("succeeded", "cancelled") or book is None:
                return
            job.status, job.error = "running", ""
            book.teardown = {**book.teardown, "stage": "running", "stop_reason": None, "stop_note": ""}
            if not self.original and book.teardown.get("open_volume_id"):
                opened = await session.get(Volume, uuid.UUID(str(book.teardown["open_volume_id"])))
                if opened is not None:
                    opened.title = "还没收尾"
            await session.commit()
        await self.progress()
        # worker 恢复不重复发开始；只允许显式启动的一条群聊消息由 API 发送。
        grouper = asyncio.create_task(self.grouping())
        try:
            _, chapters, _, _ = await self.snapshot()
            wanted = [
                c
                for c in chapters
                if c.index <= self.target
                and (
                    "read_failed" in (c.teardown or {})
                    or (not self.retry_failed_only and (c.teardown or {}).get("read_version") is None)
                )
            ]
            first_alone = not any((c.teardown or {}).get("read_version") for c in chapters)
            self.changed.set()
            await self.read_chapters(wanted, first_alone=first_alone)
            self.reading_done = True
            self.changed.set()
            await grouper
        except Exception as exc:
            self.stop = TeardownStopped(
                "error", f"拆的时候出错了（{one_line(exc)}），停下了。点「接着拆」从停的地方往下拆，读过的不重读。"
            )
            log.exception("拆书 %s 失败", self.book_id)
        finally:
            if not grouper.done():
                grouper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await grouper
        await self.finish()

    async def finish(self) -> None:
        await self.progress("closing")
        current_book, chapters, units, volumes = await self.snapshot()
        if current_book is None:
            return
        read = [c.index for c in chapters if (c.teardown or {}).get("read_version")]
        failed = [c.index for c in chapters if "read_failed" in (c.teardown or {})]
        volume_count = sum(v.title not in ("还没收尾", "还没分卷", "") for v in volumes)
        author_stop = await self.cancelled()
        if author_stop:
            reason, note = "author", f"你点了停下，停在第 {max(read, default=0)} 章。"
        elif self.stop:
            reason, note = self.stop.reason, self.stop.note
        elif self.target < self.total:
            reason, note = "upto", f"拆到第 {self.target} 章了（你定的）。"
        elif (
            any(
                not c.unit_id
                or ((c.teardown or {}).get("read_version") is None and "read_failed" not in (c.teardown or {}))
                for c in chapters
            )
            or (current_book.teardown or {}).get("open_volume_id")
            or any(not v.summary for v in volumes)
        ):
            reason, note = (
                "error",
                "拆的时候出错了（还有章或卷没有归完），停下了。点「接着拆」从停的地方往下拆，读过的不重读。",
            )
        else:
            reason, note = None, ""
        if reason is not None and self.retry_previous is not None and not author_stop:
            reason = self.retry_previous.get("stop_reason") or reason
            note = self.retry_previous.get("stop_note") or note
        stage = "done" if reason is None else "stopped"
        async with self.sm() as session:
            book = await session.get(Book, self.book_id)
            job = await session.get(Job, self.job_id)
            if book is None or job is None:
                return
            book.teardown = {**book.teardown, "stage": stage, "stop_reason": reason, "stop_note": note}
            await session.commit()
            await book_saves.checkpoint(
                session, self.book_id, "lorekeeper", "拆完了" if stage == "done" else "停下拆书"
            )
        message = (
            f"拆完了：{self.total} 章都有章纲，归成了 {len(units)} 个单元、{volume_count} 卷。"
            if stage == "done"
            else note
        )
        if failed:
            message += f"有 {len(failed)} 章没读成：第 {'、'.join(map(str, failed))} 章，点「再试一次」重读这几章。"
        await Emitter(self.sm, self.redis, self.book_id, self.job_id).say("lorekeeper", message)
        # 终态是收尾完成的承诺：存档和最后一句话都已持久化，才能让 API 显示任务结束。
        async with self.sm() as session:
            job = await session.get(Job, self.job_id)
            if job is None:
                return
            job.status = "cancelled" if author_stop else "failed" if reason in ("model", "error") else "succeeded"
            job.error = note if reason in ("model", "error") else ""
            job.finished_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(job)
            await publish(self.redis, self.book_id, "job", job_dict(job))
        await self.refresh(force=True)
        await self.redis.delete(cancel_key(self.job_id))

    async def read_range(self, first: int, last: int) -> None:
        _, chapters, _, _ = await self.snapshot()
        selected = [c for c in chapters if first <= c.index <= last]
        await self.read_chapters(
            selected, first_alone=not any((c.teardown or {}).get("read_version") for c in chapters)
        )
        await self.check_rerun_stop()

    async def check_rerun_stop(self) -> None:
        if await self.cancelled():
            raise JobCancelled()
        if self.stop:
            raise self.stop

    async def regroup_units(self, first: int | None = None) -> None:
        await self.check_rerun_stop()
        _, chapters, units, volumes = await self.snapshot()
        self.target = max(
            (
                c.index
                for c in chapters
                if (c.teardown or {}).get("read_version") or (c.teardown or {}).get("read_failed")
            ),
            default=0,
        )
        ranges = self.unit_ranges(chapters, units)
        removed = [u.id for u in units if first is None or (u.id in ranges and ranges[u.id][1] >= first)]
        async with self.sm() as session:
            alive = await session.scalar(select(Book).where(Book.id == self.book_id).with_for_update())
            if alive is None:
                raise JobCancelled()
            await self.check_rerun_stop()
            for chapter in chapters:
                if chapter.unit_id in removed:
                    row = await session.get(Chapter, chapter.id)
                    row.unit_id = None
            await session.flush()
            if removed:
                await session.execute(delete(PlotUnit).where(PlotUnit.id.in_(removed)))
            if not self.original and volumes:
                # AI 归出来的卷是下游结果，不能拿旧的卷界限制新的单元。
                # 只失效待重归范围涉及的最早卷及后面的卷，之前的卷和完整单元不动。
                affected_ids = {u.volume_id for u in units if u.id in removed}
                affected_ids |= {c.volume_id for c in chapters if not c.unit_id and (first is None or c.index >= first)}
                earliest = min((v.index for v in volumes if first is None or v.id in affected_ids), default=None)
                if earliest is not None:
                    affected = [v for v in volumes if v.index >= earliest]
                    affected_ids = {v.id for v in affected}
                    opened = affected[0]
                    surviving = sorted(
                        [u for u in units if u.id not in removed and u.volume_id in affected_ids],
                        key=lambda u: ranges.get(u.id, (0, 0))[0],
                    )
                    for index, unit in enumerate(surviving, 1):
                        row = await session.get(PlotUnit, unit.id)
                        row.index = 1000000 + index
                        await session.flush()
                        row.volume_id = opened.id
                    for chapter in chapters:
                        if chapter.volume_id in affected_ids:
                            row = await session.get(Chapter, chapter.id)
                            row.volume_id = opened.id
                    await session.flush()
                    await session.execute(delete(Volume).where(Volume.id.in_(affected_ids - {opened.id})))
                    for index, unit in enumerate(surviving, 1):
                        row = await session.get(PlotUnit, unit.id)
                        row.index = index
                    row = await session.get(Volume, opened.id)
                    row.title, row.summary, row.status = "还没收尾", "", "planned"
                    row.chapter_count = sum(c.volume_id in affected_ids for c in chapters)
                    alive.teardown = {**alive.teardown, "open_volume_id": str(opened.id)}
            await session.commit()
        self.tried_units.clear()
        while not await self.should_stop() and await self.group_once(final=True):
            pass
        await self.check_rerun_stop()

    async def regroup_volumes(self) -> None:
        await self.check_rerun_stop()
        book, chapters, units, volumes = await self.snapshot()
        if self.original:
            async with self.sm() as session:
                for volume in volumes:
                    row = await session.get(Volume, volume.id)
                    row.summary = ""
                await session.commit()
        elif volumes:
            open_id = (book.teardown or {}).get("open_volume_id")
            opened = next((v for v in volumes if str(v.id) == str(open_id)), volumes[-1])
            async with self.sm() as session:
                ordered = sorted(units, key=lambda u: min((c.index for c in chapters if c.unit_id == u.id), default=0))
                for index, unit in enumerate(ordered, 1):
                    row = await session.get(PlotUnit, unit.id)
                    # 先用互不碰撞的临时序号，单元跨卷并回时不会撞唯一约束。
                    row.index = 1000000 + index
                    await session.flush()
                    row.volume_id = opened.id
                for chapter in chapters:
                    row = await session.get(Chapter, chapter.id)
                    row.volume_id = opened.id
                await session.flush()
                for index, unit in enumerate(ordered, 1):
                    row = await session.get(PlotUnit, unit.id)
                    row.index = index
                await session.execute(delete(Volume).where(Volume.book_id == self.book_id, Volume.id != opened.id))
                row = await session.get(Volume, opened.id)
                row.index, row.title, row.summary, row.chapter_count, row.status = (
                    1,
                    "还没收尾",
                    "",
                    self.total,
                    "planned",
                )
                book = await session.get(Book, self.book_id)
                book.teardown = {**book.teardown, "open_volume_id": str(opened.id)}
                await session.commit()
        self.tried_volumes.clear()
        while not await self.should_stop() and await self.volumes_once(final=True):
            pass
        await self.check_rerun_stop()


async def run_teardown(job_id, sm, redis, router) -> None:
    """调用方已经持有与普通任务相同的 Redis 任务锁及心跳。"""
    await Runner(job_id, sm, redis, router).run()
