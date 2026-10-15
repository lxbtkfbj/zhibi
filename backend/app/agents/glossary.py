"""编辑批注使用的术语表：随作者保存的覆盖版本实时更新。"""

import re
from collections.abc import Iterable

from app.prompts import load


def parse(text: str) -> list[tuple[str, str]]:
    entries = []
    for block in re.split(r"^##\s+", text, flags=re.M)[1:]:
        name, _, explanation = block.partition("\n")
        entries.append((name.strip(), explanation.strip()))
    return entries


def terms() -> list[tuple[str, str]]:
    return parse(load("glossary"))


def glossary_block() -> str:
    return "【术语表】可用的技巧名称：" + "、".join(name for name, _ in terms())


def clean_techniques(items: Iterable[str] | None) -> list[str]:
    if not items:
        return []
    known = {name for name, _ in terms()}
    return list(dict.fromkeys(item for item in items if isinstance(item, str) and item in known))[:3]
