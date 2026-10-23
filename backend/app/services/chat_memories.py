"""Chat-only memory tools; independent of book edits, plans and their budgets."""

import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models import Book, Memory
from app.services.memories import forget, lock_memories, remember, remembered_outcome
from app.services.requirements import SCOPE_INPUTS, requirement_states, scope_label, set_scope


class Remember(BaseModel):
    """记住一件事，存进编辑部的记忆；带上编号就是改那一条。"""

    id: str = Field(default="", description="要改哪一条，填目录里的编号（比如「记12」）；新记一条留空")
    kind: Literal["写书时照做", "聊天时记得"] = Field(
        description="「写书时照做」或「聊天时记得」：编辑部自己写书时也得守住的（写什么、不写什么、怎么写）选「写书时照做」；只在和作者商量时用得上的（作者的口味、作者的话该怎么理解、怎么跟作者合作、暂时写不进书的事）选「聊天时记得」"
    )
    scope: Literal["这本书", "全局"] = Field(
        description="「这本书」或「全局」：只关于这本书的选「这本书」；换一本书也成立的选「全局」；只管下一章、这一卷、下一卷的只能选「这本书」"
    )
    summary: str = Field(min_length=1, max_length=30, description="简述：一句话，让人一眼看懂记的是什么，30 字以内")
    detail: str = Field(description="详细内容：作者原话怎么说的、为什么；写书时照做的，再写清楚具体怎么做")
    lasts: Literal["一直有效", "只管下一章", "只管这一卷", "只管下一卷"] = Field(
        default="一直有效", description="写书时照做才填：作者说了只管下一章、这一卷、下一卷的照选，没说的选「一直有效」"
    )


class ReadMemory(BaseModel):
    """翻记忆的详细内容。目录里每条只有简述，要细节时按编号翻，一次最多 5 条。"""

    ids: list[str] = Field(max_length=5, description="要翻的编号，比如「记12」。")


class Forget(BaseModel):
    """删掉一条记忆。只在作者明说这条不要了、记错了的时候用。"""

    id: str = Field(description="要删的编号。")


MEMORY_TOOLS = {"remember": Remember, "read_memory": ReadMemory, "forget": Forget}
KINDS = {"writing": "写书时照做", "chat": "聊天时记得"}
SNAPSHOT_FIELDS = (
    "book_id",
    "kind",
    "summary",
    "detail",
    "source",
    "scope",
    "chapter_index",
    "volume_index",
    "message_id",
)


def snapshot(row):
    values = {key: getattr(row, key) for key in SNAPSHOT_FIELDS}
    values["book_id"] = str(row.book_id) if row.book_id else None
    return {**values, "label": scope_label(row)}


async def directory_rows(session, book_id):
    book = await session.get(Book, book_id)
    if book is None or book.source == "teardown":
        return []
    return [item["row"] for item in await requirement_states(session, book_id, include_global=True) if item["active"]]


async def memory_directory(session, book_id):
    rows = await directory_rows(session, book_id)
    blocks = []
    for global_library in (True, False):
        for kind, label in KINDS.items():
            group = sorted(
                (row for row in rows if (row.book_id is None) == global_library and row.kind == kind),
                key=lambda row: row.id,
            )
            if group:
                lines = [("全局" if global_library else "这本书") + " · " + label]
                for row in group:
                    duration = f"（{scope_label(row)}）" if row.kind == "writing" and row.scope != "always" else ""
                    lines.append(f"- 记{row.id}{duration}：{' '.join(row.summary.splitlines())}")
                blocks.append("\n".join(lines))
    return "\n".join(blocks) or "还没有记忆"


def number(code):
    match = re.fullmatch(r"(?:记)?([1-9]\d*)", code.strip())
    return int(match[1]) if match else None


def code_of(code):
    return f"记{number(code)}" if number(code) else code.strip() if code.startswith("记") else f"记{code.strip()}"


def missing(code):
    return f"没做成：没有这条记忆（{code_of(code)}），只能改、删 <记忆> 目录里有的。"


async def execute(session, book_id, message_id, args):
    """Return (model result, persisted receipt or None, query proof blocks)."""
    from app.services import jobs
    from app.services.library import lock_book
    from app.services.requirements import suppress_legacy_text, unsuppress_legacy_text

    book = await session.get(Book, book_id)
    if book is None or book.source == "teardown":
        return "拆的书群聊不能用记忆。", None, []
    if not isinstance(args, ReadMemory):
        await lock_book(session, book_id)
        await lock_memories(session)
    rows = {row.id: row for row in await directory_rows(session, book_id)}
    if isinstance(args, ReadMemory):
        proof = []
        for code in args.ids:
            row = rows.get(number(code))
            if row:
                label = f"记忆「{row.summary}」"
                header = f"记{row.id}（{'这本书' if row.book_id else '全局'} · {KINDS[row.kind]}"
                header += f" · {scope_label(row)}" if row.kind == "writing" else ""
                block = f"{header}）\n简述：{row.summary}\n详细：{row.detail}"
            else:
                label, block = f"记忆「{code_of(code)}」", f"没有这条记忆：{code_of(code)}"
            proof.append((label, block))
        return "\n\n".join(block for _, block in proof), None, proof
    row = rows.get(number(args.id)) if args.id else None
    if args.id and row is None:
        return missing(args.id), None, []
    before = snapshot(row) if row else None
    working = await jobs.is_busy(session, book_id)
    if isinstance(args, Forget):
        await forget(session, row)
        outcome = remembered_outcome(row, working=working)
        outcome["kind"] = "memory"
        outcome["memory"].update(action="forget", before=before)
        return f"做成了：删掉了记{row.id}「{row.summary}」。", outcome, []
    kind = "writing" if args.kind == "写书时照做" else "chat"
    forced = args.scope == "全局" and args.lasts != "一直有效"
    target = book_id if args.scope == "这本书" or forced else None
    duplicate = await session.scalar(
        select(Memory).where(
            Memory.book_id == target,
            Memory.kind == kind,
            Memory.summary == args.summary.strip(),
            Memory.deleted_at.is_(None),
        )
    )
    if row is not None and duplicate is not None and row.id != duplicate.id:
        return f"做成了：目录里已经有这一条（记{duplicate.id}），没有重记。", None, []
    if row is None:
        before = snapshot(duplicate) if duplicate else None
        row = await remember(
            session,
            target,
            args.summary,
            args.detail,
            kind=kind,
            source="聊天里记的",
            scope=SCOPE_INPUTS[args.lasts],
            message_id=message_id,
        )
        text = (
            f"做成了：目录里已经有这一条（记{row.id}），没有重记。"
            if duplicate
            else f"做成了：记住了「{row.summary}」，编号记{row.id}。"
        )
    else:
        if row.book_id is not None and row.kind == "writing":
            await suppress_legacy_text(session, row.book_id, row.detail)
        row.book_id, row.kind, row.summary = target, kind, args.summary.strip()
        row.detail, row.source, row.message_id = args.detail.strip() or row.summary, "聊天里记的", message_id
        row.version += 1
        await set_scope(session, row, SCOPE_INPUTS[args.lasts])
        if row.book_id is not None and row.kind == "writing":
            await unsuppress_legacy_text(session, row.book_id, row.detail)
        await session.flush()
        text = f"做成了：记{row.id} 改成了「{row.summary}」。"
    if forced:
        text = f"做成了：记住了「{row.summary}」，编号记{row.id}。只管下一章、这一卷、下一卷的只能放这本书，已经放进这本书。"
    outcome = remembered_outcome(row, working=working)
    outcome["kind"] = "memory"
    outcome["memory"].update(action="update" if before else "create", before=before)
    return text, outcome, []
