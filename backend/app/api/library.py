"""设定库配置、分类、历史版本、候选与待处理建议。"""

import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import library_config as config
from app.api.deps import SessionDep, ensure_idle, get_book, get_redis
from app.api.segment_models import SegmentPatch
from app.api.story_map import validate_node
from app.library_schemas import (
    CandidateChoose,
    CandidateOut,
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    SuggestionOut,
    VersionOut,
)
from app.models import (
    Book,
    Chapter,
    Character,
    PlotUnit,
    Secret,
    SettingCandidate,
    SettingCategory,
    SettingSuggestion,
    SettingVersion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.schemas import (
    BookPatch,
    CharacterBase,
    CharacterOut,
    NodePatch,
    UnitPatch,
    VolumePatch,
    WorldEntryBase,
    WorldEntryOut,
)
from app.services import book_saves, suggestions
from app.services.library import ensure_unlocked, load_target, lock_book, parse_uuid, validate_entry
from app.services.library_cascade import generate_cascade_suggestions
from app.services.library_context import load_context
from app.services.meeting import post_message
from app.services.splice import read_path, set_field, splice
from app.services.versions import apply_snapshot, previous_version_id, record_version, snapshot_of

router = APIRouter(tags=["library"])
TargetType = Literal["character", "entry", "concept", "segment", "volume", "unit"]
VersionTargetType = Literal["character", "entry", "concept", "segment", "volume", "unit", "chapter"]


@router.get("/library-config")
async def library_config() -> dict:
    character = deepcopy(config.CHARACTER_CATEGORY)
    for key in ("fields", "state_fields"):
        character[key] = [{"name": name, "column": column} for name, column in character[key]]
    return {
        "statuses": config.STATUSES,
        "styles": config.STYLES,
        "sources": config.SOURCES,
        "focus_tags": config.FOCUS_TAGS,
        "common_tags": config.COMMON_TAGS,
        "role_types": config.ROLE_TYPES,
        "legacy_role_types": config.LEGACY_ROLE_TYPES,
        "character_category": character,
        "builtin_categories": config.BUILTIN_CATEGORIES,
        "genre_defaults": {
            genre: [{"category": category, "name": name, "status": status} for category, name, status in entries]
            for genre, entries in config.GENRE_DEFAULTS.items()
        },
    }


@router.get("/books/{book_id}/library")
async def get_library(book: Book = Depends(get_book), session: AsyncSession = SessionDep) -> dict:
    def sort_key(row):
        return list(config.STATUSES).index(row.status), row.position, row.created_at, str(row.id)

    characters = sorted(await session.scalars(select(Character).where(Character.book_id == book.id)), key=sort_key)
    entries = sorted(await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id)), key=sort_key)
    custom = await session.scalars(
        select(SettingCategory)
        .where(SettingCategory.book_id == book.id)
        .order_by(SettingCategory.position, SettingCategory.created_at, SettingCategory.id)
    )
    categories = []
    for spec in [config.CHARACTER_CATEGORY, *config.BUILTIN_CATEGORIES]:
        members = characters if spec["key"] == "角色卡片" else [r for r in entries if r.category == spec["key"]]
        categories.append(
            {
                **{key: spec[key] for key in ("key", "name", "style", "hint")},
                "builtin": True,
                "count": len(members),
                "must_count": sum(r.status == "must" for r in members),
            }
        )
    for category in custom:
        members = [r for r in entries if r.category == f"custom:{category.key}"]
        categories.append(
            {
                "id": str(category.id),
                "key": f"custom:{category.key}",
                "name": category.name,
                "style": category.style,
                "fields": category.fields,
                "hint": category.hint,
                "builtin": False,
                "count": len(members),
                "must_count": sum(r.status == "must" for r in members),
            }
        )
    focus_tags = set(config.FOCUS_TAGS)
    pending = await session.scalar(
        select(func.count())
        .select_from(SettingSuggestion)
        .where(SettingSuggestion.book_id == book.id, SettingSuggestion.status == "pending")
    )
    return {
        "categories": categories,
        "characters": [CharacterOut.model_validate(row) for row in characters],
        "entries": [WorldEntryOut.model_validate(row) for row in entries],
        "focus": {
            "characters": [str(r.id) for r in characters if r.role_type == "主角" or focus_tags.intersection(r.tags)],
            "entries": [str(r.id) for r in entries if focus_tags.intersection(r.tags)],
        },
        "suggestions_pending": pending,
    }


@router.get("/books/{book_id}/setting-categories", response_model=list[CategoryOut])
async def list_categories(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    return list(
        await session.scalars(
            select(SettingCategory)
            .where(SettingCategory.book_id == book.id)
            .order_by(SettingCategory.position, SettingCategory.created_at, SettingCategory.id)
        )
    )


@router.post("/books/{book_id}/setting-categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryCreate, book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    await lock_book(session, book.id)
    await ensure_idle(session, book.id)
    row = SettingCategory(book_id=book.id, key=uuid.uuid4().hex[:20], **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _editable_row(session: AsyncSession, model: Any, row_id: uuid.UUID, *, allow_busy: bool = False):
    row = await session.get(model, row_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    await lock_book(session, row.book_id)
    if not allow_busy:
        await ensure_idle(session, row.book_id)
    row = await session.scalar(
        select(model).where(model.id == row_id).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "记录不存在")
    return row


@router.patch("/setting-categories/{row_id}", response_model=CategoryOut)
async def update_category(row_id: uuid.UUID, body: CategoryPatch, session: AsyncSession = SessionDep):
    row = await _editable_row(session, SettingCategory, row_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row


@router.delete("/setting-categories/{row_id}", status_code=204)
async def delete_category(row_id: uuid.UUID, session: AsyncSession = SessionDep) -> None:
    row = await _editable_row(session, SettingCategory, row_id)
    count = await session.scalar(
        select(func.count())
        .select_from(WorldEntry)
        .where(WorldEntry.book_id == row.book_id, WorldEntry.category == f"custom:{row.key}")
    )
    if count:
        raise HTTPException(409, f"这个类别下还有 {count} 条设定，先删掉或挪走")
    await session.delete(row)
    await session.commit()


@router.get("/books/{book_id}/versions", response_model=list[VersionOut])
async def list_versions(
    target_type: VersionTargetType,
    target_id: uuid.UUID,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
):
    await load_target(session, book.id, target_type, target_id)
    return list(
        await session.scalars(
            select(SettingVersion)
            .where(
                SettingVersion.book_id == book.id,
                SettingVersion.target_type == target_type,
                SettingVersion.target_id == target_id,
            )
            .order_by(SettingVersion.version.desc())
        )
    )


def _target_out(target):
    if isinstance(target, WorldEntry):
        return WorldEntryOut.model_validate(target)
    if isinstance(target, Character):
        return CharacterOut.model_validate(target)
    if isinstance(target, Book):
        return {"id": target.id, "concept": deepcopy(target.concept)}
    return {"id": target.id, **snapshot_of(target)}


async def _validate_changed_target(session, book_id, target, before, *, category_changed=False):
    if isinstance(target, WorldEntry):
        data = snapshot_of(target)
        if category_changed:
            data.pop("style", None)
        values = await validate_entry(session, book_id, data, current=target)
        # 用同一个公开输入 schema 检查长度、列表结构、状态等，不允许写入无效版本。
        WorldEntryBase.model_validate(values)
        apply_snapshot(target, values)
    elif isinstance(target, Chapter):
        if not isinstance(target.title, str) or len(target.title) > 200 or not isinstance(target.content, str):
            raise ValueError("章节标题和正文必须是文字，标题不能超过 200 字")
        target.word_count = len("".join(target.content.split()))
    elif isinstance(target, Character):
        CharacterBase.model_validate(snapshot_of(target))
        if before.get("name") != target.name:
            secrets = await session.scalars(select(Secret).where(Secret.book_id == book_id))
            for secret in secrets:
                secret.knowers = [
                    {**knower, "name": target.name} if knower.get("name") == before["name"] else knower
                    for knower in secret.knowers
                ]
    elif isinstance(target, (Volume, PlotUnit)):
        schema = VolumePatch if isinstance(target, Volume) else UnitPatch
        values = snapshot_of(target)
        schema.model_validate({key: value for key, value in values.items() if key in schema.model_fields})
        # 0 是作者自己留的「还没定」；编辑部的建议要改章数就得给个实数
        if values.get("chapter_count") != before.get("chapter_count") and values.get("chapter_count", 1) < 1:
            raise ValueError("章数至少一章")
        if isinstance(target, Volume):
            await validate_node(session, book_id, target.target_node_id)
    elif isinstance(target, StoryNode):
        NodePatch.model_validate({"title": target.title, "event": target.event, "status": target.status})
        if target.segment is not None:
            SegmentPatch.model_validate(
                {key: value for key, value in target.segment.items() if key in SegmentPatch.model_fields}
            )
    elif isinstance(target, Book):
        if target.concept.get("title"):
            BookPatch.model_validate({"title": target.concept["title"]})
        checked = Book(concept=deepcopy(target.concept))
        for key in ("story", "pitches", "secret_entry_id"):
            if key in target.concept:
                set_field(checked, key, target.concept[key])
        entry_id = target.concept.get("secret_entry_id")
        if entry_id is not None:
            entry = await session.get(WorldEntry, parse_uuid(entry_id, "底牌"))
            if entry is None or entry.book_id != book_id:
                raise HTTPException(422, "底牌条目不属于这本书")


@router.post("/versions/{version_id}/revert")
async def revert_version(
    version_id: uuid.UUID,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    version = await _editable_row(session, SettingVersion, version_id, allow_busy=True)
    target = await load_target(session, version.book_id, version.target_type, version.target_id, for_update=True)
    if isinstance(target, Chapter) and target.status != "final":
        raise HTTPException(409, "这一章还在写作或重写，定稿后再退回正文版本")
    structure = None
    if isinstance(target, (Volume, PlotUnit)) and version.snapshot.get("chapter_count") != target.chapter_count:
        from app.services import outline_structure

        await ensure_idle(session, version.book_id)
        structure = await outline_structure.load_structure(session, version.book_id)
    before = snapshot_of(target)
    previous_source = getattr(target, "source", "ai")
    try:
        with session.no_autoflush:
            apply_snapshot(target, version.snapshot)
            await _validate_changed_target(session, version.book_id, target, before)
        if isinstance(target, (Character, WorldEntry)):
            target.source = "revert"
        if structure is not None:
            await outline_structure.resize_target(session, structure, target, target.chapter_count)
            await outline_structure.finish_structure(
                session,
                version.book_id,
                structure,
                f"退回到第 {version.version} 版",
                affected={target.id},
                source="revert",
            )
        else:
            await record_version(
                session,
                version.book_id,
                version.target_type,
                target,
                "revert",
                f"退回到第 {version.version} 版",
                before=before,
                previous_source=previous_source,
            )
        await session.commit()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "退回后的名称重复或引用已不存在") from exc
    await session.refresh(target)
    result = _target_out(target)
    if isinstance(target, Book):
        await _review_changed_concept(session, redis, target.id, before.get("story", ""))
    return result


@router.get("/books/{book_id}/candidates", response_model=list[CandidateOut])
async def list_candidates(
    target_type: TargetType,
    target_id: uuid.UUID,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
):
    await load_target(session, book.id, target_type, target_id)
    return list(
        await session.scalars(
            select(SettingCandidate)
            .where(
                SettingCandidate.book_id == book.id,
                SettingCandidate.target_type == target_type,
                SettingCandidate.target_id == target_id,
            )
            .order_by(SettingCandidate.created_at.desc(), SettingCandidate.id)
        )
    )


def _splice_error(exc: ValueError) -> HTTPException:
    return HTTPException(409 if "原文已经改过" in str(exc) else 422, str(exc))


async def _choose_candidate(
    row_id: uuid.UUID,
    body: CandidateChoose,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    candidate = await _editable_row(session, SettingCandidate, row_id, allow_busy=True)
    if body.index >= len(candidate.options):
        raise HTTPException(422, "没有这个候选")
    option = candidate.options[body.index]
    if not isinstance(option, dict) or not isinstance(option.get("text"), str):
        raise HTTPException(422, "候选文字不正确")
    target = await load_target(session, candidate.book_id, candidate.target_type, candidate.target_id, for_update=True)
    ensure_unlocked(target)
    before = snapshot_of(target)
    previous_source = getattr(target, "source", "ai")
    try:
        with session.no_autoflush:
            # 原文可能整体移位；成功替换后保存真正的新范围，长度变化和重复选项也能继续切换。
            updated_path = candidate.path
            if "@" in candidate.path:
                field, bounds = candidate.path.rsplit("@", 1)
                start, end = (int(value) for value in bounds.split(":"))
                current_text = read_path(target, field)
                if not isinstance(current_text, str):
                    raise ValueError("这个位置不是文字")
                if end > len(current_text) or current_text[start:end] != candidate.base:
                    start = current_text.find(candidate.base)
                if start >= 0:
                    updated_path = f"{field}@{start}:{start + len(option['text'])}"
            splice(target, candidate.path, option["text"], base=candidate.base)
            await _validate_changed_target(session, candidate.book_id, target, before)
        candidate.path = updated_path
        candidate.base = option["text"]
        candidate.chosen = body.index
        if isinstance(target, (Character, WorldEntry)):
            target.source = "candidate"
        await record_version(
            session,
            candidate.book_id,
            candidate.target_type,
            target,
            "candidate",
            before=before,
            previous_source=previous_source,
        )
        suggestions = await generate_cascade_suggestions(
            session,
            candidate.book_id,
            target,
            candidate.path,
            option.get("renamed") or [],
            one_line=option.get("one_line") or "",
        )
        book = await session.get(Book, candidate.book_id)
        context = await load_context(session, book)
        # 和直接改一处相同：候选选择、正文快照、建议和群聊消息一起提交。
        await post_message(
            session,
            redis,
            book_id=candidate.book_id,
            job_id=None,
            speaker="lorekeeper",
            kind="speech",
            content=f"已把「{context.target_name(target)}」的{context.part_label(target, candidate.path)}换成你选的写法。",
        )
    except ValueError as exc:
        raise _splice_error(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "候选修改后的名称重复或引用已不存在") from exc
    revert_version_id = await previous_version_id(session, candidate.target_type, candidate.target_id)
    await session.refresh(target)
    result = {
        "candidate": CandidateOut.model_validate(candidate),
        "target": _target_out(target),
        "revert_version_id": revert_version_id,
        "suggestions": [SuggestionOut.model_validate(suggestion) for suggestion in suggestions],
    }
    if isinstance(target, Book):
        await _review_changed_concept(session, redis, target.id, before.get("story", ""))
    return result


async def _review_changed_concept(session, redis, book_id, old_story):
    # 先保存作者这次改动，再查下游；查出来的只挂建议，不递归接受。
    from app.api.library_ai import review_concept_change

    await review_concept_change(session, redis, book_id, old_story)


@router.get("/books/{book_id}/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    status: Literal["pending", "accepted", "ignored"] = "pending",
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
):
    return list(
        await session.scalars(
            select(SettingSuggestion)
            .where(SettingSuggestion.book_id == book.id, SettingSuggestion.status == status)
            .order_by(SettingSuggestion.created_at.desc(), SettingSuggestion.id)
        )
    )


def _require(payload: dict, name: str, expected: type):
    value = payload.get(name)
    if not isinstance(value, expected):
        raise HTTPException(422, f"建议缺少有效的 {name}")
    return value


async def _apply_suggestion(session: AsyncSession, suggestion: SettingSuggestion):
    if suggestion.kind == "chat":
        raise ValueError("群聊里说的建议要等编辑部空闲后点「现在改」")
    if suggestion.status != "pending":
        raise HTTPException(409, "这条建议已经处理过")
    payload = suggestion.payload
    if not isinstance(payload, dict):
        raise HTTPException(422, "建议操作必须是对象")
    op = payload.get("op")
    target = None
    before = None
    previous_source = None
    target_type = None
    if op in {"create_entry", "create_character"}:
        is_entry = op == "create_entry"
        data = deepcopy(_require(payload, "entry" if is_entry else "character", dict))
        schema = WorldEntryBase if is_entry else CharacterBase
        # 服务端字段不能夹带，亦不能通过创建建议写入不属于角色卡片的运行时状态。
        allowed = set(schema.model_fields)
        if not is_entry:
            allowed -= {"want", "location", "condition", "is_alive"}
        if set(data) - allowed:
            raise HTTPException(422, "建议包含不能编辑的字段")
        data = schema.model_validate(data).model_dump(exclude_unset=True)
        if is_entry:
            data = await validate_entry(session, suggestion.book_id, data)
        target = (WorldEntry if is_entry else Character)(book_id=suggestion.book_id, source="suggestion", **data)
        session.add(target)
        await session.flush()
        target_type = "entry" if is_entry else "character"
    elif op == "create_category":
        data = deepcopy(_require(payload, "category", dict))
        entries = data.pop("entries", [])
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise HTTPException(422, "自建类别的条目必须是列表")
        data["style"] = {"卡片": "card", "段落": "paragraph"}.get(data.get("style"), data.get("style"))
        values = CategoryCreate.model_validate(data).model_dump()
        category = SettingCategory(book_id=suggestion.book_id, key=uuid.uuid4().hex[:20], **values)
        session.add(category)
        await session.flush()
        for position, entry in enumerate(entries):
            entry = deepcopy(entry)
            if set(entry) - (set(WorldEntryBase.model_fields) | {"parent"}):
                raise HTTPException(422, "建议包含不能编辑的字段")
            # 建议里的类别名是模型给的显示名，接受后由程序绑定刚建立的类别。
            entry.pop("parent", None)
            entry["category"] = f"custom:{category.key}"
            entry["status"] = {value: key for key, value in config.STATUSES.items()}.get(
                entry.get("status"), entry.get("status", "must")
            )
            entry["style"] = category.style
            entry["position"] = position
            entry = WorldEntryBase.model_validate(entry).model_dump(exclude_unset=True)
            entry = await validate_entry(session, suggestion.book_id, entry)
            created = WorldEntry(book_id=suggestion.book_id, source="suggestion", **entry)
            session.add(created)
            await session.flush()
            await record_version(session, suggestion.book_id, "entry", created, "suggestion", suggestion.title)
    elif op == "replace_in_chapters":
        old, new = _require(payload, "old", str), _require(payload, "new", str)
        numbers = _require(payload, "chapters", list)
        if not old or old == new or not numbers or any(type(number) is not int or number < 1 for number in numbers):
            raise HTTPException(422, "前文替换需要旧叫法、新叫法和有效的章号")
        chapters = list(
            await session.scalars(
                select(Chapter)
                .where(Chapter.book_id == suggestion.book_id, Chapter.index.in_(numbers))
                .order_by(Chapter.index)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(chapters) != len(set(numbers)) or any(chapter.status != "final" for chapter in chapters):
            raise HTTPException(409, "有章节已不在定稿状态，先重新查看前文")
        if any(old not in chapter.content for chapter in chapters):
            raise HTTPException(409, "原文已经改过，没法只换这一段")
        for chapter in chapters:
            # 正文手改也可能发生在两次建议之间；每次替换前完整存一版，不能漏掉这一稿。
            await record_version(session, suggestion.book_id, "chapter", chapter, "suggestion", "替换前文前")
            chapter.content = chapter.content.replace(old, new)
            chapter.word_count = len("".join(chapter.content.split()))
            await record_version(session, suggestion.book_id, "chapter", chapter, "suggestion", suggestion.title)
    elif op in {"replace_text", "splice", "set_field"}:
        target_type = _require(payload, "target_type", str)
        target_id = parse_uuid(payload.get("target_id"))
        # 显示目标和实际执行目标不能暗中指向不同内容。
        if suggestion.target_type is not None and suggestion.target_type != target_type:
            raise HTTPException(422, "建议的目标类型不一致")
        if suggestion.target_id is not None and suggestion.target_id != target_id:
            raise HTTPException(422, "建议的目标编号不一致")
        target = await load_target(session, suggestion.book_id, target_type, target_id, for_update=True)
        ensure_unlocked(target)
        before = snapshot_of(target)
        previous_source = getattr(target, "source", "ai")
        path = _require(payload, "path", str)
        with session.no_autoflush:
            if op == "replace_text":
                old, new = _require(payload, "old", str), _require(payload, "new", str)
                current = read_path(target, path)
                if not old or not isinstance(current, str) or old not in current:
                    raise HTTPException(409, "原文已经改过，没法只换这一段")
                splice(target, path, current.replace(old, new), base=current)
            elif op == "splice":
                splice(target, path, _require(payload, "new", str), base=_require(payload, "base", str))
            else:
                if "value" not in payload:
                    raise HTTPException(422, "建议缺少 value")
                set_field(target, path, deepcopy(payload["value"]))
            await _validate_changed_target(
                session, suggestion.book_id, target, before, category_changed=path == "category"
            )
        if isinstance(target, (Character, WorldEntry)):
            target.source = "suggestion"
    elif op != "note":
        raise HTTPException(422, "不支持的建议操作")

    if target is not None:
        await record_version(
            session,
            suggestion.book_id,
            target_type,
            target,
            "suggestion",
            suggestion.title,
            before=before,
            previous_source=previous_source,
        )
    suggestion.status = "accepted"
    suggestion.resolved_at = datetime.now(UTC)
    await session.flush()
    return target


async def _accept_suggestion(row_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    suggestion = await _editable_row(session, SettingSuggestion, row_id, allow_busy=True)
    book_id = suggestion.book_id
    book = await session.get(Book, book_id)
    old_story = (book.concept or {}).get("story", "")
    try:
        # 改前改后记在建议上：新书页的待处理当场摆出来，能「换回原来的」
        await suggestions.applied(session, suggestion, lambda: _apply_suggestion(session, suggestion))
        await session.commit()
    except ValueError as exc:
        raise _splice_error(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "建议里的名称重复或引用已不存在") from exc
    result = SuggestionOut.model_validate(suggestion)
    await _review_changed_concept(session, redis, book_id, old_story)
    return result


@router.post("/suggestions/{row_id}/ignore", response_model=SuggestionOut)
async def ignore_suggestion(row_id: uuid.UUID, session: AsyncSession = SessionDep):
    suggestion = await _editable_row(session, SettingSuggestion, row_id, allow_busy=True)
    if suggestion.status != "pending":
        raise HTTPException(409, "这条建议已经处理过")
    suggestion.status = "ignored"
    suggestion.resolved_at = datetime.now(UTC)
    await session.commit()
    return suggestion


async def _accept_all_suggestions(book: Book, session: AsyncSession, redis: Redis, only_changes: bool = False):
    await lock_book(session, book.id)
    book_id = book.id
    old_story = (book.concept or {}).get("story", "")
    rows = list(
        await session.scalars(
            select(SettingSuggestion)
            .where(SettingSuggestion.book_id == book.id, SettingSuggestion.status == "pending")
            .order_by(SettingSuggestion.created_at, SettingSuggestion.id)
        )
    )
    # 新书页的「全部同意」只管有具体改法的；只说了毛病的、群聊里说的要作者自己点
    ids = [row.id for row in rows if not (only_changes and suggestions.can_hand_over(row))]
    accepted, skipped = [], []
    for suggestion_id in ids:
        try:
            # 一条失败只能撤回这一条；后续建议仍然可执行，且不得留下失败的版本或半截改动。
            async with session.begin_nested():
                suggestion = await session.scalar(
                    select(SettingSuggestion).where(SettingSuggestion.id == suggestion_id).with_for_update()
                )
                await suggestions.applied(session, suggestion, lambda row=suggestion: _apply_suggestion(session, row))
            accepted.append(suggestion_id)
        except HTTPException as exc:
            skipped.append({"id": suggestion_id, "reason": exc.detail})
        except ValueError as exc:
            skipped.append({"id": suggestion_id, "reason": str(exc)})
        except IntegrityError:
            skipped.append({"id": suggestion_id, "reason": "建议里的名称重复或引用已不存在"})
    await session.commit()
    await _review_changed_concept(session, redis, book_id, old_story)
    return jsonable_encoder(
        {"accepted": accepted, "skipped": skipped, "accepted_count": len(accepted), "skipped_count": len(skipped)}
    )


# 编辑部的东西放进书里：做事前先存作者自己改了还没存的，做完存一档（设计说明 9.13「第二批：存档」）
@router.post("/candidates/{row_id}/choose")
async def choose_candidate(
    row_id: uuid.UUID,
    body: CandidateChoose,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    row = await session.get(SettingCandidate, row_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return await book_saves.editorial(
        session,
        row.book_id,
        "lorekeeper",
        "换上了挑中的写法：",
        lambda: _choose_candidate(row_id, body, session, redis),
    )


@router.post("/suggestions/{row_id}/accept", response_model=SuggestionOut)
async def accept_suggestion(row_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    row = await session.get(SettingSuggestion, row_id)
    if row is None:
        raise HTTPException(404, "记录不存在")
    return await book_saves.editorial(
        session, row.book_id, "lorekeeper", "收下了建议：", lambda: _accept_suggestion(row_id, session, redis)
    )


@router.post("/books/{book_id}/suggestions/accept-all")
async def accept_all_suggestions(
    only_changes: bool = False,
    book: Book = Depends(get_book),
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    return await book_saves.editorial(
        session,
        book.id,
        "lorekeeper",
        "收下了全部建议：",
        lambda: _accept_all_suggestions(book, session, redis, only_changes),
    )


@router.get("/books/{book_id}/suggestion-changes")
async def suggestion_changes(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    """同意过的建议现在还能不能「换回原来的」"""
    result = await suggestions.changes(session, book.id)
    await session.commit()
    return result


@router.post("/suggestions/{row_id}/revert", response_model=SuggestionOut)
async def revert_suggestion(row_id: uuid.UUID, session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)):
    """同意以后的「换回原来的」：这一处后来又被动过就 409"""
    return await suggestions.revert(session, redis, row_id)


class HandOverIn(BaseModel):
    # 发在作者正在看的那一段对话；不给就是最近聊的那一段
    conv: str | None = None


@router.post("/suggestions/{row_id}/to-chat", status_code=201)
async def hand_over_suggestion(
    row_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: HandOverIn | None = None,
    session: AsyncSession = SessionDep,
    redis: Redis = Depends(get_redis),
):
    """让编辑部改：只说了毛病的、群聊里说了当时没改的，当成作者在聊天里说的一句话"""
    return await suggestions.hand_over(session, redis, row_id, body.conv if body else None, background_tasks)
