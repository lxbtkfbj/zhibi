"""手册文件与已提交的作者版本；数据库内容不缓存。"""

import re
from dataclasses import dataclass
from importlib import resources

import psycopg

from app.config import get_settings


@dataclass(frozen=True)
class Handbook:
    key: str
    name: str
    when: str
    body: str
    content: str


def keys() -> list[str]:
    folder = resources.files("app.prompts").joinpath("skills")
    if not folder.is_dir():
        return []
    return sorted(
        item.name[:-3]
        for item in folder.iterdir()
        if item.is_file() and re.fullmatch(r"[a-z][a-z0-9_]*\.md", item.name)
    )


def compose(name: str, when: str, body: str) -> str:
    return f"# {name}\n\n什么时候翻：{when}\n\n{body}"


def parse(key: str, content: str) -> Handbook:
    """只拆标题和第一条目录说明；保留正文的原始行尾和末尾空白。"""
    lines = content.splitlines(keepends=True)
    name = lines.pop(0).rstrip("\r\n").removeprefix("# ").strip() if lines else ""
    when = ""
    for index, line in enumerate(lines):
        if line.startswith("什么时候翻："):
            when = line.removeprefix("什么时候翻：").strip()
            lines.pop(index)
            break
    while lines and not lines[0].strip():
        lines.pop(0)
    return Handbook(key, name, when, "".join(lines), content)


def system_books() -> dict[str, Handbook]:
    folder = resources.files("app.prompts").joinpath("skills")
    # 不经提示词覆盖，也不规范化文件行尾。
    return {key: parse(key, folder.joinpath(f"{key}.md").read_bytes().decode("utf-8")) for key in keys()}


def resolve(rows: list[dict], systems: dict[str, Handbook] | None = None) -> list[tuple[Handbook, dict | None]]:
    """合并虚拟的系统手册和数据库行，文件被移除的作者版本作为自写手册保留。"""
    systems = system_books() if systems is None else systems
    by_key = {row["key"]: row for row in rows}
    result = []
    for key, system in systems.items():
        row = by_key.get(key)
        book = (
            Handbook(key, row["name"], row["when"], row["body"], compose(row["name"], row["when"], row["body"]))
            if row and row["name"] is not None
            else system
        )
        result.append((book, row))
    mine = [row for row in rows if row["key"] not in systems and row["name"] is not None]
    for row in sorted(mine, key=lambda row: (row["created_at"], row["key"])):
        book = Handbook(
            row["key"], row["name"], row["when"], row["body"], compose(row["name"], row["when"], row["body"])
        )
        result.append((book, row))
    return result


def catalog() -> list[Handbook]:
    """一次短连接读整张表，主编只看到已打开的版本。"""
    from psycopg.rows import dict_row

    with psycopg.connect(get_settings().checkpoint_dsn, connect_timeout=10, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT * FROM handbooks").fetchall()
    return [book for book, row in resolve(rows) if row is None or row["enabled"]]


def description(books: list[Handbook]) -> str:
    if not books:
        return ""
    return "翻编辑部的专业手册，拿到全文再答。手册目录：\n" + "\n".join(f"- {book.name}：{book.when}" for book in books)


def tool_spec() -> dict | None:
    books = catalog()
    if not books:
        return None
    return {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": description(books),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": [book.name for book in books],
                        "description": "手册的名称，照目录写",
                    }
                },
                "required": ["name"],
            },
        },
    }


def read(name: str) -> str:
    books = catalog()
    return next(
        (book.content for book in books if book.name == name),
        f"没有这本手册：{name}。目录里有：" + "、".join(book.name for book in books),
    )
