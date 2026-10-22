"""从随程序发布的文件发现手册；目录和全文都读作者当前生效的版本。"""

import re
from dataclasses import dataclass
from importlib import resources

from app.prompts import default_content, load


@dataclass(frozen=True)
class Handbook:
    key: str
    name: str
    when: str
    content: str

    def entry(self) -> tuple[str, str, str, str, str]:
        return (
            f"skills.{self.key}",
            self.name,
            "手册",
            "chief,lorekeeper,writer,reviewer",
            "群聊里编辑部自己翻：" + self.when,
        )


def keys() -> list[str]:
    folder = resources.files("app.prompts").joinpath("skills")
    if not folder.is_dir():
        return []
    return sorted(
        item.name[:-3]
        for item in folder.iterdir()
        if item.is_file() and re.fullmatch(r"[a-z][a-z0-9_]*\.md", item.name)
    )


def parse(key: str, content: str) -> Handbook:
    lines = content.splitlines()
    heading = re.fullmatch(r"# ([^#\s].*)", lines[0]) if lines else None
    if heading is None or not heading[1].strip():
        raise ValueError("第一行必须是 # 名称")
    when = next(
        (line.removeprefix("什么时候翻：").strip() for line in lines[1:] if line.startswith("什么时候翻：")), ""
    )
    if not when:
        raise ValueError("必须有「什么时候翻：」那一行，并写清什么时候翻")
    if "{{" in content or "}}" in content:
        raise ValueError("手册不能有 {{变量}}")
    return Handbook(key, heading[1].strip(), when, content)


def catalog(contents: dict[str, str] | None = None) -> list[Handbook]:
    """contents 供提示词 API 使用同一次查询的已提交覆盖版本；群聊一律走 prompts.load。"""
    result = []
    for key in keys():
        name = f"skills.{key}"
        content = load(name) if contents is None else contents.get(name, default_content(name))
        result.append(parse(key, content))
    return result


def validate(name: str, content: str, contents: dict[str, str] | None = None) -> None:
    current = parse(name.split(".", 1)[1], content)
    if any(other.key != current.key and other.name == current.name for other in catalog(contents)):
        raise ValueError(f"手册名称不能重名：{current.name}")


def tool_spec() -> dict | None:
    books = catalog()
    if not books:
        return None
    return {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "翻编辑部的专业手册，拿到全文再答。手册目录：\n"
            + "\n".join(f"- {book.name}：{book.when}" for book in books),
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
