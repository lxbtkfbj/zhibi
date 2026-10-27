"""作者预设、逐次保存和全局正在用的选择。所有写入由接口显式提交。"""

import uuid
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models import AppSetting, Preset, PresetSave
from app.services import presets

KIND = "chief_group"
KIND_LABEL = "主编群聊"


def ensure_kind(kind: str) -> None:
    if kind != KIND:
        raise HTTPException(422, f"不认识预设种类：{kind}；目前只有主编群聊（chief_group）")


def setting_key(kind: str) -> str:
    ensure_kind(kind)
    return f"active_preset.{kind}"


async def active_selection(session, kind: str = KIND) -> dict:
    row = await session.get(AppSetting, setting_key(kind))
    return deepcopy(row.value) if row is not None else {"source": "system"}


async def get_active_preset(session, kind: str = KIND) -> dict:
    """没有配置时永远取系统最新版；作者的保存不会被系统升级改写。"""
    selected = await active_selection(session, kind)
    if selected.get("source") == "mine":
        try:
            key = uuid.UUID(str(selected.get("id")))
        except (ValueError, TypeError):
            key = None
        row = await session.get(Preset, key) if key is not None else None
        if row is not None and row.kind == kind:
            return {
                "kind": row.kind,
                "source": "mine",
                "id": str(row.id),
                "name": row.name,
                "version": row.saved,
                "blocks": deepcopy(row.blocks),
            }
    return presets.system_preset(kind)


async def mine_of(session, preset_id: uuid.UUID, *, lock: bool = False) -> Preset:
    query = select(Preset).where(Preset.id == preset_id)
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise HTTPException(404, "这份预设不存在")
    return row


def summary(row: Preset) -> dict:
    return {
        "id": str(row.id),
        "source": "mine",
        "kind": row.kind,
        "name": row.name,
        "based_on": deepcopy(row.based_on),
        "block_count": len(row.blocks),
        "enabled_count": sum(bool(b.get("enabled")) for b in row.blocks),
        "saved": row.saved,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def system_base_version(session, row: Preset, seen: set | None = None) -> int | None:
    """沿复制关系回到系统版；复制时另存根版号，原件删除后仍能提示新版。"""
    seen = set() if seen is None else seen
    if row.id in seen:
        return None
    seen.add(row.id)
    basis = row.based_on or {}
    if basis.get("source") == "system":
        return basis.get("version")
    if basis.get("source") != "mine":
        return None
    if isinstance(basis.get("system_version"), int):
        return basis["system_version"]
    try:
        parent_id = uuid.UUID(str(basis.get("id")))
    except (ValueError, TypeError):
        return None
    parent = await session.get(Preset, parent_id)
    return await system_base_version(session, parent, seen) if parent is not None else None


async def detail(session, row: Preset) -> dict:
    result = {**summary(row), "blocks": deepcopy(row.blocks), "issues": presets.check(row.blocks, kind=row.kind)}
    version = await system_base_version(session, row)
    latest = presets.system_preset(row.kind)
    if version is not None and latest["version"] > version:
        result["system_newer"] = {key: latest[key] for key in ("version", "date", "note")}
    return result


def normalize_blocks(blocks: list, *, existing: list | None = None, imported: bool = False) -> list[dict]:
    """新加的作者块只由程序发号；复制/导入既有块的记号原样保留。"""
    if not isinstance(blocks, list):
        raise HTTPException(422, "blocks 必须是预设块清单")
    known = {block["id"]: block for block in existing or []}
    result = []
    for index, raw in enumerate(blocks, 1):
        if not isinstance(raw, dict):
            raise HTTPException(422, f"第 {index} 块必须是一个对象")
        block = {
            "title": "新块",
            "role": "user",
            "enabled": True,
            "required": False,
            "when": "always",
            "content": "",
            **raw,
        }
        key = block.get("id")
        if key is not None and not isinstance(key, str):
            raise HTTPException(422, f"第 {index} 块：id 必须是字符串")
        if (not imported and key not in known) or (imported and not key):
            block["id"] = "custom_" + uuid.uuid4().hex
            block["required"] = False
        if not imported and key in known:
            block["required"] = known[key]["required"]
        try:
            result.append(presets.validate_blocks([block])[0])
        except ValueError as exc:
            raise HTTPException(422, f"第 {index} 块：{exc}") from exc
    try:
        return presets.validate_blocks(result)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def default_name(session, kind: str) -> str:
    names = set(await session.scalars(select(Preset.name).where(Preset.kind == kind)))
    number = 1
    while f"我的{KIND_LABEL} {number}" in names:
        number += 1
    return f"我的{KIND_LABEL} {number}"


def add_save(session, row: Preset) -> None:
    session.add(PresetSave(preset_id=row.id, saved=row.saved, name=row.name, blocks=deepcopy(row.blocks)))


async def create(
    session, *, kind: str = KIND, name: str | None = None, source: str = "system", source_id=None, version=None
):
    ensure_kind(kind)
    if source == "system":
        try:
            original = presets.system_preset(kind, version)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "没有这一版系统预设") from exc
        blocks = presets.copy_blocks(original["blocks"])
        basis = {"source": "system", "version": original["version"]}
    elif source == "mine":
        if source_id is None:
            raise HTTPException(422, "复制作者预设时要给 id")
        original = await mine_of(session, source_id)
        if original.kind != kind:
            raise HTTPException(422, "复制的预设种类不对")
        blocks = deepcopy(original.blocks)
        basis = {"source": "mine", "id": str(original.id), "saved": original.saved}
        root = await system_base_version(session, original)
        if root is not None:
            basis["system_version"] = root
    else:
        raise HTTPException(422, "source 只能是 system 或 mine")
    if not name:
        # 自动起名的「找第一个没被用过」和插入放在同一把事务锁里。
        # 不加名字唯一约束：作者手动起重名不受限制。
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"preset_default_name.{kind}"))))
        name = await default_name(session, kind)
    row = Preset(kind=kind, name=name, based_on=basis, blocks=blocks, saved=1)
    session.add(row)
    await session.flush()
    add_save(session, row)
    await session.commit()
    await session.refresh(row)
    return await detail(session, row)


async def save(session, row: Preset, name: str, blocks: list) -> dict:
    row.name, row.blocks, row.saved = name, blocks, row.saved + 1
    await session.flush()
    add_save(session, row)
    await session.commit()
    await session.refresh(row)
    return await detail(session, row)


async def set_active(session, *, kind: str, source: str, preset_id: uuid.UUID | None) -> dict:
    ensure_kind(kind)
    if source == "system":
        target = presets.system_preset(kind)
        selection = {"source": "system"}
    elif source == "mine":
        if preset_id is None:
            raise HTTPException(422, "使用作者预设时要给 id")
        row = await mine_of(session, preset_id, lock=True)
        if row.kind != kind:
            raise HTTPException(422, "预设种类不对")
        target = {"blocks": row.blocks}
        selection = {"source": "mine", "id": str(row.id)}
    else:
        raise HTTPException(422, "source 只能是 system 或 mine")
    issues = presets.check(target["blocks"], kind=kind)
    if any(issue["severity"] == "error" for issue in issues):
        raise HTTPException(422, {"message": "这份预设还不能用", "issues": issues})
    await session.execute(
        insert(AppSetting)
        .values(key=setting_key(kind), value=selection)
        .on_conflict_do_update(index_elements=["key"], set_={"value": selection})
    )
    await session.commit()
    return {"kind": kind, **selection, "issues": issues}


async def remove(session, row: Preset) -> None:
    selected = await active_selection(session, row.kind)
    if selected.get("source") == "mine" and selected.get("id") == str(row.id):
        raise HTTPException(409, "这份正在用，先换一份再删")
    await session.delete(row)
    await session.commit()


def exported(preset: dict) -> dict:
    return {
        "format": "zhibi-preset",
        "format_version": 1,
        "kind": preset["kind"],
        "name": preset["name"],
        "blocks": presets.copy_blocks(preset["blocks"]),
    }


async def import_preset(session, data) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(422, "预设文件必须是一个 JSON 对象")
    if (
        data.get("format") != "zhibi-preset"
        or type(data.get("format_version")) is not int
        or data["format_version"] != 1
    ):
        raise HTTPException(422, "预设文件格式不对，需要 zhibi-preset 第 1 版")
    ensure_kind(data.get("kind", ""))
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise HTTPException(422, "预设名字不能为空，且不能超过 200 字")
    try:
        blocks = presets.validate_blocks(data.get("blocks"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = Preset(kind=data["kind"], name=name, based_on={"source": "import"}, blocks=blocks, saved=1)
    session.add(row)
    await session.flush()
    add_save(session, row)
    await session.commit()
    await session.refresh(row)
    return await detail(session, row)
