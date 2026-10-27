"""系统预设、占位符、检查和消息拼接；不读取作者的数据或改变工具权限。"""

import json
import re
from copy import deepcopy
from importlib import resources

from app.prompts import VARIABLE
from app.services.chat_prompts import material_values

KINDS = ({"kind": "chief_group", "label": "主编群聊"},)
CONDITIONS = (
    {"when": "always", "label": "每次都发"},
    {"when": "can_act", "label": "能动手时"},
    {"when": "ask_only", "label": "只问不改时"},
    {"when": "skills", "label": "有手册时"},
    {"when": "teardowns", "label": "有拆过的书时"},
    {"when": "web", "label": "配了联网时"},
)
PLACEHOLDERS = (
    {
        "name": "资料说明",
        "description": "书大的时候是一句「（书比较大：设定和大纲只列了目录，要细节用工具查）」，书小的时候是空的",
    },
    {"name": "简介", "description": "这本书的简介，包在 <简介> 里"},
    {"name": "设定库", "description": "设定库：书小给全文，书大只列名字和一句话"},
    {"name": "大纲", "description": "大纲：书小给全文，书大只给目录"},
    {"name": "写到哪了", "description": "写到第几章、在开书还是在写，包在 <写到哪了> 里"},
    {"name": "正在看的那一页", "description": "作者发话时正在看哪一页，包在 <作者正在看的那一页> 里"},
    {"name": "等你确认的", "description": "编辑部停下来等作者拍板的内容；没有就是空的"},
    {"name": "编辑部正在干活", "description": "编辑部正在写书时的一段提醒；没在写就是空的"},
    {"name": "记忆", "description": "记忆目录，包在 <记忆> 里"},
    {"name": "之前聊过", "description": "太长时缩成的摘要；没有就是「（没有）」"},
    {"name": "聊天记录", "description": "摘要以后的聊天原话，一条一行"},
    {"name": "选中的原文", "description": "作者选中让主编看的那段原文；没有就是空的"},
    {"name": "上次做到一半", "description": "重试时上回已经做完的；不是重试就是空的"},
    {"name": "作者这次说的", "description": "作者这次说的那句话"},
)
PLACEHOLDER_KEYS = dict(
    zip(
        (row["name"] for row in PLACEHOLDERS),
        (
            "material_note",
            "book",
            "library",
            "outline",
            "progress",
            "viewing",
            "pending",
            "working",
            "memory",
            "summary",
            "recent",
            "quote",
            "retry",
            "note",
        ),
        strict=True,
    )
)
BLOCK_FIELDS = ("id", "title", "role", "enabled", "required", "when", "content")
ROLES = {"system", "user", "assistant"}
WHEN = {row["when"] for row in CONDITIONS}


def validate_kind(kind: str) -> str:
    if kind not in {row["kind"] for row in KINDS}:
        raise ValueError("不支持的预设种类：" + str(kind))
    return kind


def _root(kind: str):
    return resources.files("app.presets").joinpath(validate_kind(kind))


def _versions(kind: str) -> list[int]:
    return sorted(
        int(match.group(1))
        for folder in _root(kind).iterdir()
        if folder.is_dir() and (match := re.fullmatch(r"v([1-9]\d*)", folder.name))
    )


def latest_version(kind: str = "chief_group") -> int:
    versions = _versions(kind)
    if not versions:
        raise ValueError("系统预设不存在")
    return versions[-1]


def _read_system(kind: str, version: int) -> dict:
    if version not in _versions(kind):
        raise ValueError("系统预设的这一版不存在")
    folder = _root(kind).joinpath(f"v{version}")
    preset = json.loads(folder.joinpath("preset.json").read_text(encoding="utf-8"))
    for block in preset["blocks"]:
        # 只去掉文件末尾的换行，不改变预设正文里的空白。
        block["content"] = folder.joinpath(f"{block['id']}.md").read_text(encoding="utf-8").rstrip("\r\n")
    return {**preset, "source": "system"}


def system_versions(kind: str = "chief_group") -> list[dict]:
    """版本目录每次发现；部署新版或测试临时加入 v2 无需改代码。"""
    return [
        {key: value for key, value in _read_system(kind, version).items() if key != "blocks"}
        for version in _versions(kind)
    ]


def system_preset(kind: str = "chief_group", version: int | None = None) -> dict:
    version = latest_version(kind) if version is None else version
    preset = _read_system(kind, version)
    previous = [_read_system(kind, v) for v in _versions(kind) if v <= version]
    for block in preset["blocks"]:
        history, last = [], None
        for edition in previous:
            old = next((row for row in edition["blocks"] if row["id"] == block["id"]), None)
            if old is None or old["content"] == last:
                continue
            history.append(
                {
                    "version": edition["version"],
                    "date": edition["date"],
                    "change": old.get("origin", "") if last is None else old.get("change", ""),
                }
            )
            last = old["content"]
        block["history"] = history
    return preset


def copy_blocks(blocks: list[dict]) -> list[dict]:
    """作者的块只存可编辑字段，系统来历仍以系统目录为准。"""
    return [{key: deepcopy(block[key]) for key in BLOCK_FIELDS} for block in blocks]


def validate_blocks(blocks: list[dict]) -> list[dict]:
    if not isinstance(blocks, list):
        raise ValueError("blocks 必须是块的清单")
    seen = set()
    for index, block in enumerate(blocks, 1):
        prefix = f"第 {index} 块："
        if not isinstance(block, dict):
            raise ValueError(prefix + "必须是一个对象")
        for field in BLOCK_FIELDS:
            if field not in block:
                raise ValueError(prefix + f"缺少 {field}")
            expected = bool if field in {"enabled", "required"} else str
            if not isinstance(block[field], expected):
                raise ValueError(prefix + f"{field} 必须是{'布尔值' if expected is bool else '字符串'}")
        if not block["id"].strip() or block["id"] in seen:
            raise ValueError(prefix + "id 不能为空或重复")
        seen.add(block["id"])
        if block["role"] not in ROLES:
            raise ValueError(prefix + "不认识的 role：" + block["role"])
        if block["when"] not in WHEN:
            raise ValueError(prefix + "不认识的 when：" + block["when"])
    return copy_blocks(blocks)


def placeholder_values(values: dict[str, str]) -> dict[str, str]:
    """只换占位符名字；十四份值来自今天的同一份 material_values。"""
    material = material_values(values, template="chat_agent")
    return {name: material[key] for name, key in PLACEHOLDER_KEYS.items()}


def conditions(*, read_only: bool, tools: list[dict]) -> dict[str, bool]:
    """以这一轮真正给模型的工具为准，不另算一份权限。"""
    names = {spec["function"]["name"] for spec in tools}
    return {
        "always": True,
        "can_act": not read_only and "make_changes" in names,
        "ask_only": read_only,
        "skills": "read_skill" in names,
        "teardowns": "look_up_teardown" in names,
        "web": "search_web" in names,
    }


def render_block(content: str, values: dict[str, str]) -> str:
    # 一次替换；未知名字和值里本来就有的 {{…}} 都原样留下。
    text = VARIABLE.sub(lambda match: str(values[match[1]]).strip() if match[1] in values else match[0], content)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def message_texts(messages: list[dict]) -> tuple[str, str]:
    system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
    user = "\n\n".join(
        ("【assistant】\n" if message["role"] == "assistant" else "") + message["content"]
        for message in messages
        if message["role"] != "system"
    )
    return system, user


def compose(preset: dict, values: dict[str, str], *, read_only: bool, tools: list[dict]) -> dict:
    allowed = conditions(read_only=read_only, tools=tools)
    replacements = placeholder_values(values)
    system, messages, sent = [], [], []
    for block in preset["blocks"]:
        if not block["enabled"] or not allowed[block["when"]]:
            continue
        content = render_block(block["content"], replacements)
        if not content:
            continue
        sent.append({key: block[key] for key in ("id", "title", "role")})
        if block["role"] == "system":
            system.append(content)
        elif messages and messages[-1]["role"] == block["role"]:
            messages[-1]["content"] += "\n\n" + content
        else:
            messages.append({"role": block["role"], "content": content})
    if system:
        messages.insert(0, {"role": "system", "content": "\n\n".join(system)})
    record = {
        "kind": preset["kind"],
        "source": preset["source"],
        "name": preset["name"],
        "version": preset["version"],
        "blocks": sent,
    }
    if preset["source"] == "mine":
        record["id"] = str(preset["id"])
    system_text, user_text = message_texts(messages)
    return {"messages": messages, "system": system_text, "user": user_text, "preset": record}


def check(blocks: list[dict], *, kind: str = "chief_group") -> list[dict]:
    """内容没写完也可保存；只有缺作者这次说的话会阻止设为正在用。"""
    problems = []

    def add(severity, code, block, message):
        problems.append(
            {
                "severity": severity,
                "code": code,
                "block_id": block.get("id") if block else None,
                "title": block.get("title") if block else None,
                "message": message,
            }
        )

    if not any(
        block["enabled"] and block["when"] != "ask_only" and "作者这次说的" in VARIABLE.findall(block["content"])
        for block in blocks
    ):
        add("error", "missing_note", None, "没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。")
    reference = {block["id"]: block for block in system_preset(kind)["blocks"]}
    required = {key: block for key, block in reference.items() if block["required"]}
    required.update({block["id"]: block for block in blocks if block["required"] and block["id"] not in required})
    actual = {block["id"]: block for block in blocks}
    for key, block in required.items():
        if key not in actual or not actual[key]["enabled"]:
            without = block.get("without", "这一块的规矩不会发给主编。")
            add("warning", "required_disabled", block, f"关了『{block['title']}』：{without}")
    for block in blocks:
        for unknown in dict.fromkeys(
            name for name in VARIABLE.findall(block["content"]) if name not in PLACEHOLDER_KEYS
        ):
            add("warning", "unknown_placeholder", block, "『{{" + unknown + "}}』不是占位符，发出去会原样露出来。")
        if not block["content"].strip():
            add("warning", "empty_block", block, "这一块是空的，发不出去。")
    enabled = [block for block in blocks if block["enabled"] and block["content"].strip() and block["role"] != "system"]
    if enabled and enabled[-1]["role"] == "assistant":
        add(
            "warning",
            "assistant_last",
            enabled[-1],
            "最后一条是 assistant，模型可能不接着回；最后一条最好是 user。",
        )
    return problems
