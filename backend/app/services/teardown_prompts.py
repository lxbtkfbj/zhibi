"""拆书上下文保留书名变量的绑定；后台任务真正调用前才取作者的新书名。"""

import re

from app.prompts import VARIABLE, load, track_rendered
from app.prompts import render as render_plain


class TitlePrompt(str):
    def __new__(cls, name, template, values, *, prefix="", suffix=""):
        # 与普通 render 一样只解释模板一次；原文里的 {{title}} 和旧书名都不替换。
        text = VARIABLE.sub(lambda match: str(values[match.group(1)]).strip(), template)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        value = super().__new__(cls, prefix + text + suffix)
        value.name, value.template, value.values = name, template, values
        value.prefix, value.suffix = prefix, suffix
        track_rendered(name, str(value))
        return value

    def with_title(self, title):
        return type(self)(
            self.name, self.template, {**self.values, "title": title}, prefix=self.prefix, suffix=self.suffix
        )

    def __add__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return type(self)(self.name, self.template, self.values, prefix=self.prefix, suffix=self.suffix + other)

    def __radd__(self, other):
        if not isinstance(other, str):
            return NotImplemented
        return type(self)(self.name, self.template, self.values, prefix=other + self.prefix, suffix=self.suffix)


def render(name: str, /, **values: str) -> str:
    if "title" not in values:
        return render_plain(name, **values)
    template = load(name)
    missing = sorted(set(VARIABLE.findall(template)) - values.keys())
    if missing:
        raise KeyError(f"提示词 {name} 缺少变量：{missing}")
    return TitlePrompt(name, template, dict(values))
