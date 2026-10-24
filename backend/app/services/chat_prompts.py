"""聊天的规矩放进系统提示，资料另用同一份用户提示；写书仍用原来的 persona。"""

from app.prompts import render, tagged


def system_prompt(role: str, template: str, **values: str) -> str:
    parts = [render(f"persona_{role}", rules="")]
    if role == "chief":
        parts.append(render("chat_voice", voice=render("voice_chief")))
    parts.append(render(template, **values))
    if template != "chat_teardown":
        parts.append(render("chat_manner", role_focus=values["role_focus"]))
    parts.append(render("rules"))
    return "\n\n".join(parts)


def material_values(values: dict[str, str], *, template: str) -> dict[str, str]:
    """发送前才包资料标签，不改 reply_values 留给总结方案的七样原值。"""
    material = {
        name: values.get(name, "")
        for name in (
            "material_note",
            "library",
            "outline",
            "extras",
            "pending",
            "working",
            "summary",
            "recent",
            "quote",
            "retry",
            "note",
        )
    }
    if template == "chat_teardown":
        material.update(
            book=tagged("这本书", values["book_info"]),
            library="（从原文拆出来的）\n" + values["library"],
            outline="（从原文倒推的）\n" + values["outline"],
            progress="",
            memory="",
            viewing=tagged("作者正在看的那一页", values["viewing"]),
            related=values["related"],
            extras="",
            pending="",
            working="",
        )
    else:
        agent = template == "chat_agent"
        if agent:
            material["extras"] = ""
        else:
            material.update(material_note="", working="", retry="")
        material.update(
            book=tagged("简介", values["concept"]),
            progress=tagged("写到哪了", values["progress"]),
            memory=tagged("记忆", values["memory"]),
            viewing=tagged("作者正在看的那一页", values["viewing"]) if agent else "",
            related="" if agent else tagged("和这次的话有关的资料", values["related"]),
        )
    return material
