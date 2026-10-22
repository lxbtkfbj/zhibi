"""提示词模板：只缓存随程序发布的默认文本，覆盖版本每次从数据库读取。"""

import re
from contextvars import ContextVar
from functools import cache
from importlib import resources

import psycopg

from app.config import get_settings

VARIABLE = re.compile(r"\{\{(\w+)\}\}")
_rendered: ContextVar[tuple[tuple[str, str], ...]] = ContextVar("rendered_prompts", default=())


def canonical_name(name: str) -> str:
    name = name.replace("/", ".")
    if not re.fullmatch(r"(?:playbooks\.)?[a-z][a-z0-9_]*", name):
        raise ValueError("无效的提示词名称")
    return name


@cache
def default_content(name: str) -> str:
    name = canonical_name(name)
    return resources.files(__package__).joinpath(name.replace(".", "/") + ".md").read_text(encoding="utf-8")


def _load(name: str) -> str:
    """render 是同步函数，因此用短连接读取已提交的版本；不依赖 worker 内的缓存失效通知。"""
    name = canonical_name(name)
    fallback = default_content(name)
    with psycopg.connect(get_settings().checkpoint_dsn, connect_timeout=10) as conn:
        row = conn.execute("SELECT content FROM prompt_overrides WHERE name = %s", (name,)).fetchone()
    return row[0] if row is not None else fallback


def load(name: str) -> str:
    """读取当前生效的原文（覆盖版本优先），不进行变量替换。"""
    return _load(name)


def track_rendered(name: str, content: str) -> str:
    # 不可变 ContextVar 保证并行审稿任务不会互相污染。
    if content:
        _rendered.set((*_rendered.get()[-63:], (canonical_name(name), content)))
    return content


def prompt_names_for(system: str, user: str) -> list[str]:
    """仅标记确实包含在本次请求里的模板，而不是根据 purpose 猜测。"""
    return list(dict.fromkeys(name for name, content in _rendered.get() if content in system or content in user))


def tagged(name: str, body: str) -> str:
    """聊天提示词里的一大块资料用 <名字>…</名字> 包起来，和资料里每一条开头的【名字】分开。"""
    return f"<{name}>\n{body.strip()}\n</{name}>"


def render(name: str, /, **values: str) -> str:
    text = _load(name)
    # 一次替换，作者原文里的 {{...}} 不会被二次解释成模板变量。
    missing = sorted(set(VARIABLE.findall(text)) - values.keys())
    if missing:
        raise KeyError(f"提示词 {name} 缺少变量：{missing}")
    text = VARIABLE.sub(lambda match: str(values[match.group(1)]).strip(), text)
    return track_rendered(name, re.sub(r"\n{3,}", "\n\n", text).strip())
