"""拆书的整本书收尾：篇、结局和顺序推进的读者期待台账。"""

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.agents import schemas as s
from app.agents.context import foreshadow_code
from app.graphs.deps import JobCancelled
from app.models import Book, Foreshadowing, StoryNode, Volume
from app.prompts import render

ENDING_MARK = re.compile(r"大结局|终章|尾声|全书完|全文完|全剧终|完本|完结|（完）|【完】|\(完\)")


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def arc_hash(node):
    # title 是节点名，segment.title 是目录使用的篇名；任一处作者改过都保护。
    return text_hash(json.dumps([node.title, node.segment or {}], ensure_ascii=False, sort_keys=True))


def closed_volumes(book, volumes):
    """只拿从第 1 卷开始连续收住的前缀，不能跨过悬挂的中间卷。"""
    meta = book.teardown or {}
    rows = []
    for volume in sorted(volumes, key=lambda row: row.index):
        if volume.index != len(rows) + 1 or not (volume.summary or "").strip():
            break
        if not meta.get("original_volumes") and str(volume.id) == str(meta.get("open_volume_id")):
            break
        rows.append(volume)
    return rows


async def check(runner):
    if await runner.cancelled():
        raise JobCancelled()


async def locked_book(runner, session):
    book = await session.scalar(select(Book).where(Book.id == runner.book_id).with_for_update())
    await check(runner)
    if book is None or book.source != "teardown":
        raise JobCancelled()
    return book


async def nodes_of(session, book_id, kind):
    return list(
        await session.scalars(
            select(StoryNode).where(StoryNode.book_id == book_id, StoryNode.kind == kind).order_by(StoryNode.position)
        )
    )


async def collect_arcs(runner, *, final, force=False):
    book, chapters, _, volumes = await runner.snapshot()
    await check(runner)
    if book is None:
        raise JobCancelled()
    closed = closed_volumes(book, volumes)
    user = render(
        "teardown_arcs",
        title=book.title,
        volumes=runner.volume_lines(closed, chapters),
        first=str(closed[0].index if closed else 1),
        max_arcs=str(math.ceil(len(closed) / 2)),
        tail_rule=(
            "这是全书最后几卷：全部归完，open_from 写 null。"
            if final
            else "后面还有没拆的章：最后几卷要是还没收在一个大阶段的结尾（主角还没离开这个舞台），就先不归，open_from 写从第几卷起还没收住。"
        ),
    )
    signature = text_hash(user)
    previous = (book.teardown or {}).get("arcs") or {}
    same = not force and previous.get("inputs") == signature and previous.get("final") == final
    parsed = None
    if len(closed) >= 3 and not same:
        await runner.progress("arcs")
        parsed = await runner.validated(
            s.TeardownArcs, user, "拆书：归篇", closed[0].index, closed[-1].index, close=final
        )
        await check(runner)
    async with runner.sm() as session:
        current = await locked_book(runner, session)
        nodes = await nodes_of(session, book.id, "milestone")
        current_volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book.id)))
        endings = await nodes_of(session, book.id, "ending")
        meta = dict(current.teardown or {})
        if len(closed) < 3:
            for volume in current_volumes:
                volume.target_node_id = None
            for node in nodes:
                await session.delete(node)
            meta.pop("arcs", None)
            current.teardown = meta
            await session.commit()
            return {"count": 0}
        rows = []
        if same:
            # 输入没变只修复挂卷，不覆盖作者改过的篇文字，也不改变原来的写入 hash。
            node_ids = {str(node.id) for node in nodes}
            rows = [row for row in previous.get("rows", []) if row.get("node") in node_ids]
        else:
            old_rows = previous.get("rows") or []
            for index, item in enumerate(parsed.arcs):
                ids = [str(v.id) for v in closed if item.first <= v.index <= item.last]
                node = nodes[index] if index < len(nodes) else StoryNode(book_id=book.id, kind="milestone")
                old = old_rows[index] if index < len(old_rows) else {}
                protected = (
                    old.get("node") == str(node.id)
                    and old.get("volumes") == ids
                    and old.get("hash") is not None
                    and arc_hash(node) != old["hash"]
                )
                if not protected:
                    node.title, node.event = item.title[:100], ""
                    node.segment = {"title": item.title, "text": item.text}
                    node.status, node.origin = "pencil", "ai"
                node.position = index + 1
                session.add(node)
                await session.flush()
                rows.append(
                    {"node": str(node.id), "volumes": ids, "hash": old["hash"] if protected else arc_hash(node)}
                )
            for node in nodes[len(parsed.arcs) :]:
                await session.delete(node)
        targets = {vid: row["node"] for row in rows for vid in row["volumes"]}
        for volume in current_volumes:
            target = targets.get(str(volume.id))
            volume.target_node_id = uuid.UUID(target) if target else None
        for index, ending in enumerate(endings, len(rows) + 1):
            ending.position = index
        meta["arcs"] = {"inputs": signature, "final": final, "rows": rows, "at": datetime.now(UTC).isoformat()}
        current.teardown = meta
        await session.commit()
    await runner.refresh(force=True)
    return {"count": len(rows)}


def ending_hint(book, chapters):
    main = [c for c in chapters if "番外" not in ((c.teardown or {}).get("flags") or [])]
    last = main[-1] if main else None
    texts = [c.title for c in chapters[-3:]]
    if last is not None:
        texts.extend([last.title, (last.teardown or {}).get("raw_title", ""), (last.content or "")[-300:]])
    texts.extend(row.get("title", "") for row in (book.teardown or {}).get("excluded", []))
    match = ENDING_MARK.search("\n".join(texts))
    mark = match[0] if match else ""
    return mark, (
        f"文件最后有「{mark}」，原书应该在这里完结。"
        if mark
        else "文件最后没看到「大结局」「全书完」「完本」这类字样，原书可能还没写完。"
    )


async def collect_ending(runner, *, force=False):
    book, chapters, units, volumes = await runner.snapshot()
    await check(runner)
    if book is None:
        raise JobCancelled()
    mark, hint = ending_hint(book, chapters)
    async with runner.sm() as session:
        arcs = await nodes_of(session, book.id, "milestone")
    lines = []
    for index, node in enumerate(arcs, 1):
        own = [v for v in volumes if v.target_node_id == node.id]
        if own:
            segment = node.segment or {}
            lines.append(
                f"第 {index} 篇「{segment.get('title', node.title)}」（第 {min(v.index for v in own)}–{max(v.index for v in own)} 卷）：{segment.get('text', '')}"
            )
    lines.append(runner.volume_lines(volumes, chapters))
    last = max((c.index for c in chapters), default=0)
    user = render(
        "teardown_ending",
        title=book.title,
        last=str(last),
        hint=hint,
        outline="\n".join(lines),
        units=runner.unit_lines(
            [u for u in units if volumes and u.volume_id == volumes[-1].id], runner.unit_ranges(chapters, units)
        ),
        chapters="\n".join(
            f"第 {c.index} 章「{c.title}」：{c.summary or ''}｜{(c.outline or {}).get('hook', '')}"
            for c in chapters[-10:]
        ),
    )
    signature = text_hash(user)
    previous = (book.teardown or {}).get("ending") or {}
    if not force and previous.get("inputs") == signature:
        return previous
    await runner.progress("ending")
    original = user
    for _ in range(3):
        await check(runner)
        try:
            result = await runner.call_user(s.TeardownEnding, user, "拆书：全书结局")
            problem = "完结了却没有写结局" if result.ended and not result.text.strip() else None
        except JobCancelled:
            raise
        except Exception as exc:
            from app.services.teardown_runner import one_line

            problem = one_line(exc)
        if not problem:
            break
        user = original + f"\n\n【上次写得不对】{problem}。请照要求重新写。"
    else:
        raise ValueError(f"写了三次都对不上：{problem}")
    async with runner.sm() as session:
        current = await locked_book(runner, session)
        endings = await nodes_of(session, book.id, "ending")
        if result.ended:
            arcs = await nodes_of(session, book.id, "milestone")
            node = endings[0] if endings else StoryNode(book_id=book.id, kind="ending")
            node.title, node.event, node.segment = "结局", result.text, None
            node.position, node.status, node.origin = len(arcs) + 1, "pencil", "ai"
            session.add(node)
            for extra in endings[1:]:
                await session.delete(extra)
        else:
            for node in endings:
                await session.delete(node)
        state = {"upto": last, "ended": result.ended, "inputs": signature, "hint": mark}
        current.teardown = {**current.teardown, "ending": state}
        await session.commit()
    await runner.refresh(force=True)
    return state


def wait_batches(chapters, *, after=0):
    batches, batch, count = [], [], 0
    for chapter in sorted(chapters, key=lambda c: c.index):
        if chapter.index <= after or (chapter.teardown or {}).get("read_version") is None:
            continue
        waits = len(((chapter.teardown or {}).get("read") or {}).get("waits") or [])
        if batch and (len(batch) >= 80 or count + waits > 150):
            batches.append(batch)
            batch, count = [], 0
        batch.append(chapter)
        count += waits
    if batch:
        batches.append(batch)
    return batches


def wait_code(row):
    return foreshadow_code({"kind": row.kind, "seq": row.seq})


def open_waits(rows):
    recent = sorted(
        [row for row in rows if row.status == "planted"],
        key=lambda row: (max([row.planted_chapter or 0, *(row.hint_chapters or [])]), row.seq),
        reverse=True,
    )[:400]
    return sorted(recent, key=lambda row: (row.planted_chapter or 0, row.seq))


def wait_problem(result, batch, opened):
    indices = {c.index for c in batch}
    known = {wait_code(row).upper(): row.planted_chapter for row in opened}
    refs = set()
    for item in result.new:
        if not re.fullmatch(r"N\d+", item.ref) or item.ref in refs:
            return f"新编号 {item.ref} 要写成不重复的 N 加数字"
        if item.chapter not in indices:
            return f"新立下的章号 {item.chapter} 不在这一段里"
        if not 1 <= len(item.what.strip()) <= 40:
            return f"{item.ref} 的这件事要写 1–40 字"
        refs.add(item.ref)
        known[item.ref] = item.chapter
    resolved = set()
    for item in [*result.hinted, *result.resolved]:
        code = item.code.upper()
        if code not in known:
            return f"编号 {item.code} 不在还吊着的事或本次新编号里"
        if item.chapter not in indices or item.chapter < known[code]:
            return f"{item.code} 的章号 {item.chapter} 不在这一段里，或早于立下那章"
    for item in result.resolved:
        code = item.code.upper()
        if code in resolved:
            return f"编号 {item.code} 不能了结两次"
        resolved.add(code)
    return None


def wait_chapters(batch):
    lines = []
    for chapter in batch:
        lines.append(f"第 {chapter.index} 章：{chapter.summary or ''}")
        for item in ((chapter.teardown or {}).get("read") or {}).get("waits") or []:
            lines.append(f"  {item.get('action', '')}：{item.get('what', '')}")
    return "\n".join(lines)


def wait_open_text(rows):
    return (
        "\n".join(
            f"{wait_code(row)}｜{row.kind}｜第 {row.planted_chapter} 章立下｜{row.description}｜"
            + (f"最近提起：第 {max(row.hint_chapters)} 章" if row.hint_chapters else "还没提起过")
            for row in rows
        )
        or "（还没有）"
    )


async def collect_waits(runner, *, force=False, full_only=False, attempted=None):
    book, chapters, _, volumes = await runner.snapshot()
    await check(runner)
    if book is None:
        raise JobCancelled()
    if force:
        async with runner.sm() as session:
            current = await locked_book(runner, session)
            await session.execute(delete(Foreshadowing).where(Foreshadowing.book_id == book.id))
            meta = dict(current.teardown or {})
            meta.pop("waits", None)
            current.teardown = meta
            await session.commit()
        book, chapters, _, volumes = await runner.snapshot()
    previous = (book.teardown or {}).get("waits") or {}
    read_last = max((c.index for c in chapters if (c.teardown or {}).get("read_version") is not None), default=0)
    by_chapter = {c.index: c for c in chapters}
    volume_index = {v.id: v.index for v in volumes}
    state = previous
    batches = wait_batches(chapters, after=previous.get("upto", 0))
    if full_only:
        batches = batches[:-1]
    for batch in batches:
        if full_only:
            if any((c.teardown or {}).get("read_version") is None for c in chapters if c.index <= batch[-1].index):
                break
            identity = (batch[0].index, batch[-1].index)
            if attempted is not None:
                if identity in attempted:
                    break
                attempted.add(identity)
        await check(runner)
        async with runner.sm() as session:
            rows = list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id)))
        opened = open_waits(rows)
        user = render(
            "teardown_waits",
            title=book.title,
            first=str(batch[0].index),
            last=str(batch[-1].index),
            open=wait_open_text(opened),
            chapters=wait_chapters(batch),
        )
        original = user
        await runner.progress("waits", waits={"first": batch[0].index, "last": batch[-1].index})
        for _ in range(3):
            await check(runner)
            try:
                result = await runner.call_user(s.TeardownWaitLedger, user, "拆书：读者在等的事")
                problem = wait_problem(result, batch, opened)
            except JobCancelled:
                raise
            except Exception as exc:
                from app.services.teardown_runner import one_line

                problem = one_line(exc)
            if not problem:
                break
            user = original + f"\n\n【上次记得不对】{problem}。请照要求重新记。"
        else:
            raise ValueError(f"第 {batch[0].index}–{batch[-1].index} 章记了三次都对不上：{problem}")
        async with runner.sm() as session:
            current = await locked_book(runner, session)
            rows = list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id)))
            known = {wait_code(row).upper(): row for row in rows if row.status == "planted"}
            seq = max((row.seq for row in rows), default=0)
            for item in result.new:
                seq += 1
                chapter = by_chapter[item.chapter]
                row = Foreshadowing(
                    book_id=book.id,
                    seq=seq,
                    kind=item.kind,
                    description=item.what,
                    status="planted",
                    planted_chapter=item.chapter,
                    hint_chapters=[],
                    node_id=None,
                    plant_plan=f"第 {item.chapter} 章",
                    payoff_plan="",
                    plant_volume=volume_index.get(chapter.volume_id),
                )
                session.add(row)
                rows.append(row)
                known[item.ref] = row
            for item in result.hinted:
                row = known[item.code.upper()]
                row.hint_chapters = sorted(set([*(row.hint_chapters or []), item.chapter]))
            for item in result.resolved:
                row = known[item.code.upper()]
                row.status, row.resolved_chapter = "resolved", item.chapter
                row.payoff_plan = f"第 {item.chapter} 章：{item.how}"
                row.payoff_volume = volume_index.get(by_chapter[item.chapter].volume_id)
            for row in rows:
                start, end = by_chapter.get(row.planted_chapter), by_chapter.get(row.resolved_chapter or read_last)
                row.span = (
                    "短"
                    if start and end and start.unit_id and start.unit_id == end.unit_id
                    else "中"
                    if start and end and start.volume_id == end.volume_id
                    else "长"
                )
            state = {
                "upto": batch[-1].index,
                "total": len(rows),
                "open": sum(row.status == "planted" for row in rows),
                "at": datetime.now(UTC).isoformat(),
            }
            current.teardown = {**current.teardown, "waits": state}
            await session.commit()
        await runner.refresh(force=True)
    return state or {"upto": 0, "total": 0, "open": 0}
