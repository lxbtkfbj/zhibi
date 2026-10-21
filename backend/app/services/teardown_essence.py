"""拆书精髓：先分类和逐单元拆剧情，再写十二节、核对和核心要点。"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select

from app.agents import schemas as s
from app.graphs.deps import JobCancelled
from app.models import Chapter, Character, Foreshadowing, PlotUnit
from app.services.teardown_closing import check, locked_book, text_hash
from app.services.teardown_essence_materials import (
    BookData,
    cited_records,
    materials,
    overview_material,
    rail_data,
    scene_material,
    section_text,
    top_tags,
    unit_block,
)
from app.services.teardown_prompts import render
from app.services.teardown_settings import run_parallel

SECTIONS = {
    "source": ("情节怎么想", "essence_source"),
    "skeleton": ("剧情骨架", "essence_skeleton"),
    "link": ("剧情衔接", "essence_link"),
    "fresh": ("保持新鲜", "essence_fresh"),
    "longline": ("长线布局", "essence_longline"),
    "setting": ("设定设计", "essence_setting"),
    "shuang": ("爽点类型", "essence_shuang"),
    "scene": ("爽点戏怎么写", "essence_scene"),
    "hero": ("主角", "essence_hero"),
    "cast": ("配角与对手", "essence_cast"),
    "rhythm": ("节奏与钩子", "essence_rhythm"),
    "opening": ("开篇", "essence_opening"),
}


class EssenceIncomplete(Exception):
    def __init__(self, result, errors):
        self.result, self.errors = result, errors
        super().__init__("；".join(errors))


def essence_counts(essence):
    sections = [
        section
        for section in (essence or {}).get("sections", {}).values()
        if section.get("points") or section.get("figures")
    ]
    return {
        "sections": len(sections),
        "points": sum(len(section.get("points", [])) + len(section.get("figures", [])) for section in sections),
    }


def points_problem(book, result):
    if not result.points:
        return "至少写一个知识点"
    for item in [*getattr(result, "figures", []), *result.points]:
        bad = [i for i in item.chapters if i not in book.by_index]
        if bad:
            name = getattr(item, "title", None) or item.name
            return f"「{name}」里的章号 {bad} 不在已经拆过的章里（第 1–{book.last} 章）"
    return None


def tag_input(chapter):
    return text_hash("\n".join((chapter["feel"], chapter["cool_point"], chapter["summary"])))


async def load_book(runner):
    book, chapters, units, _ = await runner.snapshot()
    await check(runner)
    if book is None or book.source != "teardown":
        raise JobCancelled()
    async with runner.sm() as session:
        waits = list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id)))
        cards = list(await session.scalars(select(Character).where(Character.book_id == book.id)))
    return book, chapters, units, BookData(book, chapters, units, waits, cards)


class EssenceRun:
    def __init__(self, runner, book, chapters, units, data, *, force=False):
        self.runner, self.data, self.force = runner, data, force
        self.chapters = {row.index: row for row in chapters}
        self.units = {row.id: row for row in units}
        self.essence = deepcopy((book.teardown or {}).get("essence") or {})
        self.essence.setdefault("sections", {})
        self.essence.setdefault("inputs", {})
        self.essence.setdefault("scene_parts", {})
        self.essence.setdefault("failures", {})
        self.system = render(
            "persona_essence",
            title=book.title,
            upto=str(data.last),
            total=str(data.meta["total"]),
            rules=render("rules"),
        )
        self.semaphore = asyncio.Semaphore(8)
        self.lock = asyncio.Lock()
        self.progress_lock = asyncio.Lock()
        self.done = self.total = 0
        self.errors = []

    async def progress(self, now):
        await self.runner.progress("essence", essence={"done": self.done, "total": self.total, "now": now})

    async def call(self, schema, user, purpose, now, validate):
        original, problem = user, ""
        async with self.semaphore:
            await check(self.runner)
            async with self.progress_lock:
                await self.progress(now)
            try:
                for _ in range(3):
                    await check(self.runner)
                    try:
                        result = await self.runner.call_user(schema, user, purpose, system=self.system)
                        await check(self.runner)
                        problem = validate(result)
                    except (JobCancelled, asyncio.CancelledError):
                        raise
                    except Exception as exc:
                        problem = " ".join(str(exc).split())[:300] or "没有返回结果"
                    if not problem:
                        return result
                    user = original + f"\n\n【上次写得不对】{problem}。请照要求重新写。"
                raise ValueError(problem)
            finally:
                async with self.progress_lock:
                    self.done += 1
                    await self.progress(now)

    async def save(self, mutate):
        async with self.lock:
            async with self.runner.sm() as session:
                current = await locked_book(self.runner, session)
                mutate(self.essence)
                current.teardown = {**(current.teardown or {}), "essence": deepcopy(self.essence)}
                await session.commit()
            await self.runner.refresh(force=True)

    async def failed(self, key, now, exc):
        error = f"{now}：{' '.join(str(exc).split())[:100] or '没有返回结果'}"
        self.errors.append(error)

        # 强制重做失败时，旧输入即使相同也必须失效，让「补上整理」真的能补。
        def store(state):
            state["inputs"].pop(key, None)
            state["failures"][key] = error

        await self.save(store)

    def tag_batches(self):
        pending = [
            chapter
            for chapter in self.data.chapters
            if chapter["feel"] in ("爽", "大爽")
            and (
                self.force
                or not self.data.tags.get(chapter["index"])
                or self.data.tags[chapter["index"]].get("of") != tag_input(chapter)
            )
        ]
        return [pending[start : start + 80] for start in range(0, len(pending), 80)]

    async def tags(self):
        previous_errors = len(self.errors)
        remove = [chapter["index"] for chapter in self.data.chapters if chapter["feel"] not in ("爽", "大爽")]
        if remove:
            async with self.runner.sm() as session:
                await locked_book(self.runner, session)
                for index in remove:
                    row = await session.get(Chapter, self.chapters[index].id)
                    if "tags" in (row.teardown or {}):
                        row.teardown = {key: value for key, value in row.teardown.items() if key != "tags"}
                    self.data.tags.pop(index, None)
                await session.commit()

        async def one(group):
            want = {chapter["index"] for chapter in group}
            lines = "\n".join(
                f"第 {c['index']} 章（{c['feel']}）看点：{c['cool_point']}｜{c['summary'][:110]}" for c in group
            )

            def validate(result):
                got = {chapter.index for chapter in result.chapters}
                return None if want <= got else f"漏了第 {sorted(want - got)} 章，每章都要写一条"

            try:
                result = await self.call(
                    s.TeardownTags,
                    render("teardown_tags", title=self.data.meta["title"], chapters=lines),
                    "拆书：爽点分类",
                    "爽点分类",
                    validate,
                )
                async with self.runner.sm() as session:
                    await locked_book(self.runner, session)
                    for item in result.chapters:
                        if item.index not in want:
                            continue
                        tags = list(dict.fromkeys(tag.strip() for tag in item.tags if tag.strip()))[:3]
                        value = {"tags": tags, "crowd": item.crowd, "of": tag_input(self.data.by_index[item.index])}
                        row = await session.get(Chapter, self.chapters[item.index].id)
                        row.teardown = {**(row.teardown or {}), "tags": value}
                        self.data.tags[item.index] = value
                    await session.commit()
                await self.runner.refresh(force=True)
            except (JobCancelled, asyncio.CancelledError):
                raise
            except Exception as exc:
                self.errors.append(f"爽点分类：{' '.join(str(exc).split())[:100] or '没有返回结果'}")
                async with self.runner.sm() as session:
                    await locked_book(self.runner, session)
                    for chapter in group:
                        row = await session.get(Chapter, self.chapters[chapter["index"]].id)
                        tags = (row.teardown or {}).get("tags")
                        if tags is not None:
                            # 留旧结果，但不能让相同的旧 of 把一次失败的强制重跑冒充为已完成。
                            value = {key: value for key, value in tags.items() if key != "of"}
                            row.teardown = {**row.teardown, "tags": value}
                            self.data.tags[chapter["index"]] = value
                    await session.commit()

        await run_parallel(one(group) for group in self.tag_batches())
        await self.phase_result("tags", previous_errors)

    async def phase_result(self, key, previous_errors):
        def store(state):
            if len(self.errors) > previous_errors:
                state["failures"][key] = "；".join(self.errors[previous_errors:])
            else:
                state["failures"].pop(key, None)
            state["failed"] = bool(state["failures"])

        await self.save(store)

    def plot_batches(self):
        pending = []
        for unit in self.data.units:
            block = unit_block(self.data, unit)
            row = self.units[unit["id"]]
            if self.force or (row.teardown or {}).get("of") != text_hash(block):
                pending.append((unit, block))
        return [pending[start : start + 8] for start in range(0, len(pending), 8)]

    async def plots(self):
        previous_errors = len(self.errors)

        async def one(group):
            want = {unit["n"] for unit, _ in group}

            def validate(result):
                got = {unit.n for unit in result.units}
                return None if want <= got else f"漏了单元 {sorted(want - got)}，每个单元都要写一条"

            try:
                result = await self.call(
                    s.TeardownUnitPlots,
                    render("teardown_unitplot", title=self.data.meta["title"], units="\n\n".join(b for _, b in group)),
                    "拆书：逐单元拆剧情",
                    "逐单元拆剧情",
                    validate,
                )
                blocks = {unit["n"]: (unit, block) for unit, block in group}
                async with self.runner.sm() as session:
                    await locked_book(self.runner, session)
                    for item in result.units:
                        if item.n not in want:
                            continue
                        unit, block = blocks[item.n]
                        row = await session.get(PlotUnit, unit["id"])
                        if row is None:
                            raise ValueError("单元已经变化，请重新整理")
                        plot = item.model_dump(exclude={"n"})
                        row.teardown = {"plot": plot, "of": text_hash(block)}
                        self.data.plots[item.n] = plot
                    await session.commit()
                await self.runner.refresh(force=True)
            except (JobCancelled, asyncio.CancelledError):
                raise
            except Exception as exc:
                self.errors.append(f"逐单元拆剧情：{' '.join(str(exc).split())[:100] or '没有返回结果'}")
                async with self.runner.sm() as session:
                    await locked_book(self.runner, session)
                    for unit, _ in group:
                        row = await session.get(PlotUnit, unit["id"])
                        if row is not None and "of" in (row.teardown or {}):
                            row.teardown = {key: value for key, value in row.teardown.items() if key != "of"}
                    await session.commit()

        await run_parallel(one(group) for group in self.plot_batches())
        await self.phase_result("unitplot", previous_errors)

    def section_jobs(self, keys):
        jobs = []
        for key in keys:
            name, prompt = SECTIONS[key]
            if key == "scene":
                for tag in top_tags(self.data):
                    user = render(prompt, tag=tag, materials=scene_material(self.data, tag))
                    input_key = f"scene:{tag}"
                    if (
                        self.force
                        or self.essence["inputs"].get(input_key) != text_hash(user)
                        or not self.essence["scene_parts"].get(tag)
                    ):
                        jobs.append((key, tag, user))
            else:
                user = render(prompt, materials=materials(self.data, key))
                if (
                    self.force
                    or self.essence["inputs"].get(key) != text_hash(user)
                    or key not in self.essence["sections"]
                ):
                    jobs.append((key, None, user))
        return jobs

    async def section(self, key, tag, user):
        name = SECTIONS[key][0]
        input_key = f"scene:{tag}" if tag is not None else key
        now = f"{name}·{tag}" if tag is not None else name
        try:
            schema = s.EssenceCast if key == "cast" else s.EssenceSection
            result = await self.call(schema, user, f"拆书精髓：{now}", name, lambda out: points_problem(self.data, out))
            section = {"name": name, **result.model_dump()}
            if key != "scene":
                checked_schema = s.EssenceCastChecked if key == "cast" else s.EssenceSectionChecked
                checked = await self.call(
                    checked_schema,
                    render(
                        "essence_check",
                        title=self.data.meta["title"],
                        section_name=name,
                        section=section_text(section),
                        records=cited_records(self.data, section),
                    ),
                    f"拆书精髓：核对·{name}",
                    f"核对·{name}",
                    lambda out: points_problem(self.data, out),
                )
                section = {"name": name, **checked.model_dump()}

            def store(state):
                state["inputs"][input_key] = text_hash(user)
                state["failures"].pop(input_key, None)
                if key == "scene":
                    state["scene_parts"][tag] = section
                else:
                    state["sections"][key] = section

            await self.save(store)
        except (JobCancelled, asyncio.CancelledError):
            raise
        except Exception as exc:
            await self.failed(input_key, now, exc)

    async def scenes(self):
        tags = top_tags(self.data)
        if any(tag not in self.essence["scene_parts"] or f"scene:{tag}" not in self.essence["inputs"] for tag in tags):
            return

        def store(state):
            state["scene_parts"] = {tag: state["scene_parts"][tag] for tag in tags}
            state["inputs"] = {
                key: value for key, value in state["inputs"].items() if not key.startswith("scene:") or key[6:] in tags
            }
            state["failures"] = {
                key: value
                for key, value in state["failures"].items()
                if not key.startswith("scene:") or key[6:] in tags
            }
            if not tags:
                state["sections"].pop("scene", None)
                return
            parts = [state["scene_parts"][tag] for tag in tags]
            state["sections"]["scene"] = {
                "name": SECTIONS["scene"][0],
                "points": [point for part in parts for point in part["points"]],
                "missing": [missing for part in parts for missing in part.get("missing", [])],
            }

        await self.save(store)

    async def overview(self):
        user = render("essence_overview", materials=overview_material(self.essence["sections"], SECTIONS))
        if (
            not self.force
            and self.essence["inputs"].get("overview") == text_hash(user)
            and self.essence.get("overview")
        ):
            return
        self.total += 1
        try:
            result = await self.call(
                s.EssenceOverview, user, "拆书精髓：核心要点", "核心要点", lambda out: points_problem(self.data, out)
            )

            def store(state):
                state["overview"] = result.model_dump()
                state["inputs"]["overview"] = text_hash(user)
                state["failures"].pop("overview", None)

            await self.save(store)
        except (JobCancelled, asyncio.CancelledError):
            raise
        except Exception as exc:
            await self.failed("overview", "核心要点", exc)


async def new_run(runner, *, force=False):
    book, chapters, units, data = await load_book(runner)
    return EssenceRun(runner, book, chapters, units, data, force=force)


async def collect_tags(runner, *, force=False):
    run = await new_run(runner, force=force)
    run.total = len(run.tag_batches())
    await run.progress("爽点分类")
    await run.tags()
    result = {"chapters": len(run.data.tags)}
    if run.errors:
        raise EssenceIncomplete(result, run.errors)
    return result


async def collect_unitplot(runner, *, force=False):
    run = await new_run(runner, force=force)
    run.total = len(run.plot_batches())
    await run.progress("逐单元拆剧情")
    await run.plots()
    result = {"units": len(run.data.plots)}
    if run.errors:
        raise EssenceIncomplete(result, run.errors)
    return result


async def collect_essence(runner, *, force=False, only: str | None = None):
    if only is not None and only not in SECTIONS:
        raise ValueError(f"没有这一节精髓：{only}")
    run = await new_run(runner, force=force)
    keys = [only] if only else list(SECTIONS)
    # 开跑时估算首轮调用数；分类/单元的新结果可能改变后面哪些节需要调用。
    estimated = run.section_jobs(keys)
    run.total = sum(1 if key == "scene" else 2 for key, _, _ in estimated) + int(only is None)
    if only is None:
        run.total += len(run.tag_batches()) + len(run.plot_batches())
    await run.progress(SECTIONS[only][0] if only else "爽点分类")
    if only is None:
        await run.tags()
        await run.plots()
    jobs = run.section_jobs(keys)
    run.total = run.done + sum(1 if key == "scene" else 2 for key, _, _ in jobs)
    await run_parallel(run.section(*job) for job in jobs)
    if only is None or only == "scene":
        await run.scenes()
    if only is None:
        await run.overview()

    def finish(state):
        state.update(
            upto=run.data.last if only is None else state.get("upto", 0),
            at=datetime.now(UTC).isoformat(),
            failed=bool(run.errors or state["failures"]),
            rails=rail_data(
                run.data,
                {
                    "tags": {str(key): value for key, value in run.data.tags.items()},
                    "plots": run.data.plots,
                    "merges": run.data.merges,
                },
            ),
        )

    await run.save(finish)
    run.total = run.done
    await run.progress(SECTIONS[only][0] if only else "核心要点")
    result = essence_counts(run.essence)
    if run.errors:
        raise EssenceIncomplete(result, run.errors)
    return result


async def estimate_calls(session, book, step="essence", *, force=False):
    """只读估算首轮调用数；分类与单元结果可能改变后续材料，运行时再修正进度。"""
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)))
    units = list(await session.scalars(select(PlotUnit).where(PlotUnit.book_id == book.id)))
    waits = list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id)))
    cards = list(await session.scalars(select(Character).where(Character.book_id == book.id)))
    data = BookData(book, chapters, units, waits, cards)
    run = EssenceRun(None, book, chapters, units, data, force=force)
    if step == "tags":
        return len(run.tag_batches())
    if step == "unitplot":
        return len(run.plot_batches())
    key = step.split(":", 1)[1] if ":" in step else None
    jobs = run.section_jobs([key] if key else SECTIONS)
    sections = sum(1 if name == "scene" else 2 for name, _, _ in jobs)
    if key:
        return sections
    user = render("essence_overview", materials=overview_material(run.essence["sections"], SECTIONS))
    overview = int(
        force
        or bool(jobs)
        or run.essence["inputs"].get("overview") != text_hash(user)
        or not run.essence.get("overview")
    )
    return sections + overview + (0 if key else len(run.tag_batches()) + len(run.plot_batches()))
