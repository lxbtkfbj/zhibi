"""提示词模板。模板里的 {{name}} 会被替换；单独成行且替换为空的占位会连同空行一起去掉。"""

import re
from functools import cache
from importlib import resources


@cache
def _load(name: str) -> str:
    return resources.files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: str) -> str:
    text = _load(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value.strip())
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise KeyError(f"提示词 {name} 缺少变量：{missing}")
    return re.sub(r"\n{3,}", "\n\n", text).strip()
