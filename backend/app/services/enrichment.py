"""规划新篇和补齐既有大纲共用的上下文与确定性整理。"""

from copy import deepcopy

from app.agents.context import format_spine
from app.agents.setup_puzzle import normalize_secrets, normalize_volumes
from app.models import Character, WorldEntry


def arc_text(spine, world, plan, number):
    end = plan.get("end") or {}
    return (
        format_spine({**spine, "nodes": plan["nodes_view"]}, world)
        + f"\n\n这一篇：\n第 {number} 篇「{plan.get('title', '')}」：{plan.get('text', '')}"
        + f"\n终点：节点 {plan['end_index']}「{end.get('title', '')}」：{end.get('event', '')}"
    )


def pending_library(ctx, plan):
    sections = []
    for key, heading, model in (
        ("new_characters", "这一篇新登场的人物：", Character),
        ("new_entries", "这一篇新建的设定：", WorldEntry),
    ):
        rendered = []
        for data in plan.get(key) or []:
            fields = {key: deepcopy(value) for key, value in data.items() if key in model.__table__.columns}
            if model is WorldEntry:
                category = next(
                    (item for item in ctx.categories if data.get("category") in {item["key"], item["name"]}), None
                )
                fields["category"] = category["key"] if category else "特殊规则"
                fields["style"] = category["style"] if category else "paragraph"
            rendered.append(ctx.entry_full_text(model(**fields)))
        if rendered:
            sections.append(heading + "\n" + "\n\n".join(rendered))
    if plan.get("fill_entries"):
        sections.append(
            "这一篇写全的设定：\n"
            + "\n".join(f"- {row['name']}：{row.get('content', '')}" for row in plan["fill_entries"])
        )
    return "\n\n".join(sections)


def normalize_split(data, plan, characters, start):
    wait = data.get("wait")
    expectations = [{**wait, "kind": "期待", "span": "长", "node": plan["end_index"]}] if wait else []
    part, normalized, notes = normalize_volumes(
        data,
        {"nodes": plan["nodes_view"], "expectations": expectations},
        characters,
        start=start,
        end_index=plan["end_index"],
    )
    part["wait"] = normalized["expectations"][0] if expectations else None
    secrets, dropped = normalize_secrets(data.get("secrets") or [], characters, normalized["nodes"])
    part["secrets"] = [{**secret, "node": plan["end_index"]} for secret in secrets]
    if dropped:
        notes.append({"question": "secrets", "text": f"已丢弃 {dropped} 个不在人物表里的知情人。"})
    for note in notes:
        note["text"] = note["text"].replace("这一段", "这一篇").replace("铁钉", "已锁")
    return part, normalized["nodes"], notes
